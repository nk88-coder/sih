from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
import asyncio
import requests


# Hardcoded token per user request
TOKEN = "7807406039:AAHFfQgjDnnQ6ZdBIOk050v_VoMOC5_0M5M"

# Sarvam API config (mirrors sih.py)
SARVAM_BASE_URL = "https://api.sarvam.ai/v1"
MODEL_PATH = "sarvam-m"
SARVAM_API_KEY = "sk_y1l5grsk_TZnY6k9GJ9Ea8a0QL8sGrePN"


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


async def reply_with_sarvam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_message = update.message.text or ""
        loop = asyncio.get_running_loop()
        answer = await loop.run_in_executor(None, _sarvam_chat_sync, user_message)
        await update.message.reply_text(answer)
    except Exception as e:
        await update.message.reply_text(f"[Bot error] {e}")


def run_bot():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_with_sarvam))
    print("[Telegram] Bot is running... Press CTRL+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    run_bot()


