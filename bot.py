import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# იღებს ტოკენს Render-ის Environment Variables-იდან
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("გამარჯობა! ბოტი წარმატებით მუშაობს Render-ზე.")

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN არ არის მითითებული!")

    # აპლიკაციის შექმნა
    app = ApplicationBuilder().token(TOKEN).build()

    # ჰენდლერის დამატება
    app.add_handler(CommandHandler("start", start))

    # run_polling ავტომატურად მართავს event loop-ს და აგვარებს ამ შეცდომას
    app.run_polling()

if __name__ == "__main__":
    main()
