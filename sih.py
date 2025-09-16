import os
import sys
import json
import requests
from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS
import pdfplumber
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.docstore.document import Document
import threading
import subprocess
import asyncio
from PIL import Image
import numpy as np
import easyocr


SARVAM_BASE_URL = "https://api.sarvam.ai/v1"
MODEL_PATH = "sarvam-m"
SARVAM_API_KEY = "sk_y1l5grsk_TZnY6k9GJ9Ea8a0QL8sGrePN"

# Initialize embeddings once at startup
print("[SIH] Loading sentence-transformers embeddings (all-MiniLM-L6-v2)...")
EMBEDDINGS = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
print("[SIH] Embeddings loaded.")

# Initialize EasyOCR once (English)
print("[SIH] Loading EasyOCR reader (en)...")
OCR_READER = easyocr.Reader(['en'], gpu=False)
print("[SIH] EasyOCR loaded.")


def get_api_key() -> str:
    """Return the hardcoded Sarvam API key."""
    return SARVAM_API_KEY


def sarvam_create_completion(prompt: str, max_tokens: int = 200, temperature: float = 0.7, chat_history=None) -> str:
    """Call Sarvam AI Chat Completions API with a simple user prompt.

    Returns assistant text on success, or an error message string on failure.
    """
    api_key = get_api_key()
    if not api_key:
        return "[ERROR] SARVAM_API_KEY is not set (env or secrets.env)."

    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }
    history = chat_history or []
    last_five = history[-5:]
    system_context = f"You are a helpful, witty assistant. Here are previous convos: {last_five}" if last_five else "You are a helpful, witty assistant."
    data = {
        "model": MODEL_PATH,
        "messages": [
            {"role": "system", "content": system_context},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    url = f"{SARVAM_BASE_URL}/chat/completions"
    try:
        response = requests.post(url, headers=headers, json=data, timeout=45)
    except Exception as e:
        return f"[ERROR] Request failed: {e}"

    if response.status_code != 200:
        # Try to include server error text for debugging
        text_snippet = response.text[:500]
        return f"[ERROR] API {response.status_code}: {text_snippet}"

    try:
        payload = response.json()
    except Exception:
        return f"[ERROR] Non-JSON response: {response.text[:500]}"

    # Try both possible shapes
    assistant_text = ""
    try:
        assistant_text = payload["choices"][0]["message"]["content"]
    except Exception:
        assistant_text = payload.get("choices", [{}])[0].get("text", "")

    if not assistant_text:
        return "[WARN] Empty response from Sarvam."

    return assistant_text


def sarvam_create_chat_completion(messages, max_tokens: int = 200, temperature: float = 0.7, stream: bool = False):
    """Call Sarvam AI Chat Completions API with a messages array.

    messages: list of {"role": "system"|"user"|"assistant", "content": str}
    """
    api_key = get_api_key()
    if not api_key:
        return "[ERROR] SARVAM_API_KEY is not set (env or secrets.env)."

    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL_PATH,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": bool(stream),
    }
    url = f"{SARVAM_BASE_URL}/chat/completions"
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
    except Exception as e:
        return f"[ERROR] Request failed: {e}"

    if response.status_code != 200:
        return f"[ERROR] API {response.status_code}: {response.text[:500]}"

    try:
        data = response.json()
    except Exception:
        return f"[ERROR] Non-JSON response: {response.text[:500]}"

    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return data.get("choices", [{}])[0].get("text", "") or "[WARN] Empty response from Sarvam."

def main() -> int:
    # If a prompt is passed as CLI args, run once and exit; otherwise start Flask server
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        prompt = " ".join(sys.argv[2:]).strip()
        if not prompt:
            print("Provide a non-empty prompt after --cli or run server without args.")
            return 1
        out = sarvam_create_completion(prompt)
        print(out)
        return 0

    app = Flask(__name__, static_folder=None)
    CORS(app)

    base_dir = os.path.dirname(__file__)
    chat_history = []  # list of {"user": str, "ai": str}

    def custom_chunker(text: str, max_sentences: int = 3):
        sentences = text.split('.')
        chunks = []
        for i in range(0, len(sentences), max_sentences):
            chunk = '.'.join(sentences[i:i+max_sentences]).strip()
            if chunk:
                chunks.append(chunk + ".")
        return chunks

    @app.post("/api/sih")
    def api_sih():
        try:
            payload = request.get_json(silent=True) or {}
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                return jsonify({"error": "prompt is required"}), 400
            reply = sarvam_create_completion(prompt, chat_history=chat_history)
            # Store exchange in memory
            try:
                chat_history.append({"user": prompt, "ai": reply})
            except Exception:
                pass
            return jsonify({"reply": reply})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.post("/api/sih-upload")
    def api_sih_upload():
        try:
            if 'file' not in request.files:
                return jsonify({"error": "No file part in request"}), 400
            file = request.files['file']
            if file.filename is None or file.filename.strip() == "":
                return jsonify({"error": "No file selected"}), 400
            filename = file.filename
            if not filename.lower().endswith('.pdf'):
                return jsonify({"error": "Only .pdf files are allowed"}), 400

            # Parse PDF directly from file stream without saving
            all_text_parts = []
            try:
                with pdfplumber.open(file.stream) as pdf:
                    for i, page in enumerate(pdf.pages, start=1):
                        try:
                            text = page.extract_text() or ""
                        except Exception:
                            text = ""
                        if text:
                            all_text_parts.append(f"\n--- Page {i} ---\n{text}\n")
            except Exception as e:
                return jsonify({"error": f"Failed to read PDF: {e}"}), 500

            all_text = "".join(all_text_parts).strip()
            if not all_text:
                all_text = "[No extractable text found in PDF]"

            # Return text to frontend; do not store server-side
            # Optionally cap payload size to avoid huge responses
            max_chars = 20000
            truncated = False
            if len(all_text) > max_chars:
                all_text = all_text[:max_chars] + "\n... [truncated]"
                truncated = True

            return jsonify({"text": all_text, "truncated": truncated, "filename": filename})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.post("/api/sih-ask")
    def api_sih_ask():
        try:
            query = request.form.get('query', '').strip()
            if not query:
                return jsonify({"error": "query is required"}), 400
            file = request.files.get('file')
            if not file or not file.filename:
                return jsonify({"error": "PDF file is required"}), 400
            if not file.filename.lower().endswith('.pdf'):
                return jsonify({"error": "Only .pdf files are allowed"}), 400

            # Extract text from PDF
            all_text_parts = []
            with pdfplumber.open(file.stream) as pdf:
                for i, page in enumerate(pdf.pages, start=1):
                    try:
                        text = page.extract_text() or ""
                    except Exception:
                        text = ""
                    if text:
                        all_text_parts.append(text)
            all_text = "\n".join(all_text_parts)
            if not all_text:
                return jsonify({"error": "No extractable text found in PDF"}), 400

            # Cap to top 20k characters
            capped_text = all_text[:20000]

            # Chunk and embed
            chunks = custom_chunker(capped_text, max_sentences=3)
            docs = [Document(page_content=c) for c in chunks]
            if not docs:
                return jsonify({"error": "No chunks produced from PDF"}), 400

            vectorstore = FAISS.from_documents(docs, EMBEDDINGS)
            results = vectorstore.similarity_search(query, k=3)
            hits = [r.page_content for r in results] if results else []

            # Build Sarvam prompt with context and recent convo
            recent_convos = chat_history[-5:] if chat_history else []
            system_context_parts = [
                "You are a helpful, witty assistant. Explain the answer in simple human terms. Keep the answer under 250 tokens.",
            ]
            if hits:
                joined_context = "\n\n".join(hits)
                if len(joined_context) > 4000:
                    joined_context = joined_context[:4000] + "\n... [context truncated]"
                system_context_parts.append(f"Context from the PDF:\n{joined_context}")
            if recent_convos:
                system_context_parts.append(f"Previous convos: {recent_convos}")
            system_content = "\n\n".join(system_context_parts)

            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": query},
            ]

            try:
                ai_reply = sarvam_create_chat_completion(messages, max_tokens=300, temperature=0.7, stream=False)
            except Exception as e:
                ai_reply = f"[Sarvam error] {e}"

            # Append to history
            try:
                chat_history.append({"user": query, "ai": ai_reply})
            except Exception:
                pass

            return jsonify({"results": hits, "chunks": len(docs), "answer": ai_reply})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Edge TTS synthesis
    @app.post("/api/sih-tts")
    def api_sih_tts():
        try:
            data = request.get_json(silent=True) or {}
            text = str(data.get("text", "")).strip()
            voice = str(data.get("voice", "en-US-JennyNeural")).strip() or "en-US-JennyNeural"
            rate = str(data.get("rate", "+0%"))
            if not text:
                return jsonify({"error": "text is required"}), 400

            import edge_tts  # lazy import

            async def synth(t: str, v: str, r: str) -> bytes:
                communicate = edge_tts.Communicate(t, v, rate=r)
                audio_bytes = bytearray()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_bytes.extend(chunk["data"]) 
                return bytes(audio_bytes)

            audio = asyncio.run(synth(text, voice, rate))
            from flask import Response
            return Response(audio, mimetype='audio/mpeg')
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # OCR image extraction (EasyOCR)
    @app.post("/api/sih-ocr")
    def api_sih_ocr():
        try:
            if 'file' not in request.files:
                return jsonify({"error": "No file part in request"}), 400
            file = request.files['file']
            if file.filename is None or file.filename.strip() == "":
                return jsonify({"error": "No file selected"}), 400
            filename = file.filename
            allowed = (filename.lower().endswith('.png') or filename.lower().endswith('.jpg') or filename.lower().endswith('.jpeg'))
            if not allowed:
                return jsonify({"error": "Only image files (.png, .jpg, .jpeg) are allowed"}), 400

            try:
                img = Image.open(file.stream).convert('RGB')
                np_img = np.array(img)
                # EasyOCR returns list of text lines when detail=0
                lines = OCR_READER.readtext(np_img, detail=0, paragraph=False)
                text = "\n".join([line.strip() for line in lines if line and line.strip()])
            except Exception as e:
                return jsonify({"error": f"OCR failed: {e}"}), 500

            text = (text or '').strip()
            if not text:
                text = "[No text detected]"

            max_chars = 20000
            if len(text) > max_chars:
                text = text[:max_chars] + "\n... [truncated]"

            return jsonify({"text": text, "filename": filename})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Ask over OCR image (RAG flow similar to PDF)
    @app.post("/api/sih-ask-ocr")
    def api_sih_ask_ocr():
        try:
            query = request.form.get('query', '').strip()
            if not query:
                return jsonify({"error": "query is required"}), 400
            if 'file' not in request.files:
                return jsonify({"error": "No file part in request"}), 400
            file = request.files['file']
            if file.filename is None or file.filename.strip() == "":
                return jsonify({"error": "No file selected"}), 400
            filename = file.filename
            allowed = (filename.lower().endswith('.png') or filename.lower().endswith('.jpg') or filename.lower().endswith('.jpeg'))
            if not allowed:
                return jsonify({"error": "Only image files (.png/.jpg/.jpeg) are allowed"}), 400

            # OCR extract
            try:
                img = Image.open(file.stream).convert('RGB')
                np_img = np.array(img)
                lines = OCR_READER.readtext(np_img, detail=0, paragraph=False)
                full_text = "\n".join([line.strip() for line in lines if line and line.strip()])
            except Exception as e:
                return jsonify({"error": f"OCR failed: {e}"}), 500

            if not full_text:
                return jsonify({"error": "No extractable text found in image"}), 400

            # Cap and chunk
            capped_text = full_text[:20000]
            chunks = custom_chunker(capped_text, max_sentences=3)
            docs = [Document(page_content=c) for c in chunks]
            if not docs:
                return jsonify({"error": "No chunks produced from OCR text"}), 400

            vectorstore = FAISS.from_documents(docs, EMBEDDINGS)
            results = vectorstore.similarity_search(query, k=3)
            hits = [r.page_content for r in results] if results else []

            # Build Sarvam prompt with OCR context and convo
            recent_convos = chat_history[-5:] if chat_history else []
            system_context_parts = [
                "You are a helpful, witty assistant. Explain the answer in simple human terms. Keep the answer under 250 tokens.",
            ]
            if hits:
                joined_context = "\n\n".join(hits)
                if len(joined_context) > 4000:
                    joined_context = joined_context[:4000] + "\n... [context truncated]"
                system_context_parts.append(f"Context from the OCR image:\n{joined_context}")
            if recent_convos:
                system_context_parts.append(f"Previous convos: {recent_convos}")
            system_content = "\n\n".join(system_context_parts)

            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": query},
            ]

            try:
                ai_reply = sarvam_create_chat_completion(messages, max_tokens=300, temperature=0.7, stream=False)
            except Exception as e:
                ai_reply = f"[Sarvam error] {e}"

            try:
                chat_history.append({"user": query, "ai": ai_reply})
            except Exception:
                pass

            return jsonify({"answer": ai_reply, "chunks": len(docs)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/sih")
    def serve_html():
        return send_from_directory(base_dir, "sih.html")

    @app.get("/")
    def root():
        return redirect("/sih")

    @app.get("/sih.css")
    def serve_css():
        return send_from_directory(base_dir, "sih.css")

    @app.get("/sih.js")
    def serve_js():
        return send_from_directory(base_dir, "sih.js")

    @app.get("/favicon.ico")
    def favicon():
        return ("", 204)

    port = int(os.getenv("PORT", "8081"))
    # Start Telegram bot in a separate thread (non-blocking)
    try:
        def _start_tg():
            try:
                import telegram_bot
                telegram_bot.run_bot()
            except Exception as e:
                print(f"[Telegram] Bot failed to start: {e}")

        tg_thread = threading.Thread(target=_start_tg, daemon=True)
        tg_thread.start()
        print("[Telegram] Launching bot thread...")
    except Exception as e:
        print(f"[Telegram] Could not launch bot thread: {e}")

    app.run(host="0.0.0.0", port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


