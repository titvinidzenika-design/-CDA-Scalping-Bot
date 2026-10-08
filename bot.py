import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# პორტის მოთხოვნის დაკმაყოფილება Render-ისთვის
app_flask = Flask(__name__)

@app_flask.route('/')
def health_check():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

# ტელეგრამის ბოტის ლოგიკა
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("გამარჯობა! ბოტი წარმატებით მუშაობს Render-ზე.")

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN არ არის מითითებული")

    # Flask სერვერის ფონურ რეჟიმში გაშვება პორტისთვის
    threading.Thread(target=run_flask, daemon=True).start()

    # ტელეგრამის ბოტის გაშვება
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()
