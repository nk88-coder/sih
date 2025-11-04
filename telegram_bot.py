from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
import asyncio
import requests
import io
import pdfplumber
from PIL import Image
import numpy as np
import easyocr
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.docstore.document import Document


# Hardcoded token per user request
TOKEN = "tele token"

# Sarvam API config (mirrors sih.py)
SARVAM_BASE_URL = "https://api.sarvam.ai/v1"
MODEL_PATH = "sarvam-m"
SARVAM_API_KEY = "sarvam api key"


def _sarvam_chat_sync(user_message: str, max_tokens: int = 200, temperature: float = 0.7) -> str:
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    messages = [
        {"role": "system", "content": "You are a helpful, witty assistant."},
        {"role": "user", "content": user_message},
    ]
    payload = {
        "model": MODEL_PATH,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        resp = requests.post(f"{SARVAM_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=45)
        if resp.status_code != 200:
            return f"[Sarvam API {resp.status_code}] {resp.text[:300]}"
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            return data.get("choices", [{}])[0].get("text", "") or "[No response]"
    except Exception as e:
        return f"[Sarvam error] {e}"

def _sarvam_chat_with_context_sync(system_content: str, user_message: str, max_tokens: int = 300, temperature: float = 0.7) -> str:
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_message},
    ]
    payload = {
        "model": MODEL_PATH,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        resp = requests.post(f"{SARVAM_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=60)
        if resp.status_code != 200:
            return f"[Sarvam API {resp.status_code}] {resp.text[:300]}"
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            return data.get("choices", [{}])[0].get("text", "") or "[No response]"
    except Exception as e:
        return f"[Sarvam error] {e}"

# Embeddings loaded once
EMBEDDINGS = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
OCR_READER = easyocr.Reader(['en'], gpu=False)

# Per-chat memory: vectorstore and chat history
VECTORSTORE_BY_CHAT = {}
HISTORY_BY_CHAT = {}


def custom_chunker(text: str, max_sentences: int = 3):
    sentences = text.split('.')
    chunks = []
    for i in range(0, len(sentences), max_sentences):
        chunk = '.'.join(sentences[i:i+max_sentences]).strip()
        if chunk:
            chunks.append(chunk + ".")
    return chunks


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not chat_id:
            return

        # If a PDF/document is sent
        if update.message and update.message.document:
            doc = update.message.document
            if doc.mime_type == 'application/pdf':
                await update.message.reply_text('📄 PDF received. Processing...')
                try:
                    tg_file = await context.bot.get_file(doc.file_id)
                    buf = io.BytesIO()
                    await tg_file.download_to_memory(out=buf)
                    buf.seek(0)

                    # Extract text
                    all_text_parts = []
                    with pdfplumber.open(buf) as pdf:
                        for page in pdf.pages:
                            try:
                                txt = page.extract_text() or ""
                            except Exception:
                                txt = ""
                            if txt:
                                all_text_parts.append(txt)
                    full_text = "\n".join(all_text_parts)
                    if not full_text:
                        await update.message.reply_text('⚠️ Could not read any text from the PDF.')
                        return

                    # Cap to 20k chars and index
                    capped = full_text[:20000]
                    chunks = custom_chunker(capped, max_sentences=3)
                    docs = [Document(page_content=c) for c in chunks]
                    if not docs:
                        await update.message.reply_text('⚠️ No chunks produced from PDF.')
                        return
                    vstore = FAISS.from_documents(docs, EMBEDDINGS)
                    VECTORSTORE_BY_CHAT[chat_id] = vstore
                    await update.message.reply_text('✅ PDF indexed. Now send your question to query it.')
                except Exception as e:
                    await update.message.reply_text(f'❌ PDF processing failed: {e}')
                return
            else:
                await update.message.reply_text(f"📎 You sent a document ({doc.mime_type})")
                return

        # If a photo/image is sent (Telegram 'photo' sizes or image document)
        if update.message and (update.message.photo or (update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith('image/'))):
            await update.message.reply_text('🖼️ Image received. Performing OCR...')
            try:
                # Get file: for 'photo' pick the largest size; else document
                if update.message.photo:
                    photo_sizes = update.message.photo
                    file_id = photo_sizes[-1].file_id  # highest resolution
                else:
                    file_id = update.message.document.file_id

                tg_file = await context.bot.get_file(file_id)
                buf = io.BytesIO()
                await tg_file.download_to_memory(out=buf)
                buf.seek(0)

                img = Image.open(buf).convert('RGB')
                np_img = np.array(img)
                lines = OCR_READER.readtext(np_img, detail=0, paragraph=False)
                full_text = "\n".join([ln.strip() for ln in lines if ln and ln.strip()])
                if not full_text:
                    await update.message.reply_text('⚠️ No text detected in this image.')
                    return

                capped = full_text[:20000]
                chunks = custom_chunker(capped, max_sentences=3)
                docs = [Document(page_content=c) for c in chunks]
                if not docs:
                    await update.message.reply_text('⚠️ No chunks produced from OCR text.')
                    return
                vstore = FAISS.from_documents(docs, EMBEDDINGS)
                VECTORSTORE_BY_CHAT[chat_id] = vstore
                await update.message.reply_text('✅ Image OCR indexed. Now send your question to query it.')
            except Exception as e:
                await update.message.reply_text(f'❌ OCR failed: {e}')
            return

        # If text message
        if update.message and update.message.text:
            user_message = update.message.text.strip()
            # If we have a vectorstore for this chat, run RAG
            vstore = VECTORSTORE_BY_CHAT.get(chat_id)
            history = HISTORY_BY_CHAT.setdefault(chat_id, [])
            if vstore:
                try:
                    # Retrieve top chunks
                    results = vstore.similarity_search(user_message, k=3)
                    hits = [r.page_content for r in results] if results else []

                    # Build system content
                    sys_parts = [
                        "You are a helpful, witty assistant. Explain the answer in simple human terms. Keep the answer under 250 tokens.",
                    ]
                    if hits:
                        joined = "\n\n".join(hits)
                        if len(joined) > 4000:
                            joined = joined[:4000] + "\n... [context truncated]"
                        sys_parts.append(f"Context from the PDF:\n{joined}")
                    if history:
                        sys_parts.append(f"Previous convos: {history[-5:]}")
                    system_content = "\n\n".join(sys_parts)

                    # Call Sarvam with messages
                    loop = asyncio.get_running_loop()
                    answer = await loop.run_in_executor(None, _sarvam_chat_with_context_sync, system_content, user_message)

                    # Store history and reply
                    try:
                        history.append({"user": user_message, "ai": answer})
                        HISTORY_BY_CHAT[chat_id] = history
                    except Exception:
                        pass
                    await update.message.reply_text(answer)
                    return
                except Exception as e:
                    await update.message.reply_text(f"[RAG error] {e}")
                    return
            else:
                # No PDF context, build system with recent convos like sih.py
                sys_parts = ["You are a helpful, witty assistant."]
                if history:
                    sys_parts.append(f"Here are previous convos: {history[-5:]}")
                system_content = "\n\n".join(sys_parts)
                loop = asyncio.get_running_loop()
                answer = await loop.run_in_executor(None, _sarvam_chat_with_context_sync, system_content, user_message, 200, 0.7)
                try:
                    history.append({"user": user_message, "ai": answer})
                    HISTORY_BY_CHAT[chat_id] = history
                except Exception:
                    pass
                await update.message.reply_text(answer)
                return

        # Fallback
        await update.message.reply_text("🤔 I don't know what this is!")
    except Exception as e:
        try:
            await update.message.reply_text(f"[Bot error] {e}")
        except Exception:
            pass


def run_bot():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    print("[Telegram] Bot is running... Press CTRL+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    run_bot()



