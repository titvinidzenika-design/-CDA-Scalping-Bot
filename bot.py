import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("გამარჯობა! ბოტი ჩართულია.")

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN არ არის მითითებული")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    # run_polling ავტომატურად აგვარებს event loop-ის პრობლემას
    app.run_polling()

if __name__ == "__main__":
    main()
