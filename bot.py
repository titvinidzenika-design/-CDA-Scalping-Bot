import os
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram import Update

# ტოკენის წაკითხვა Environment Variable-იდან
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("გამარჯობა! ბოტი წარმატებით ჩაირთო.")

if __name__ == '__main__':
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN არ არის მითითებული")

    # ბოტის აპლიკაციის აწყობა
    app = ApplicationBuilder().token(TOKEN).build()

    # ბრძანებების (Handler) დამატება
    app.add_handler(CommandHandler("start", start))

    # გაშვება (გამოიყენეთ ეს მეთოდი)
    app.run_polling()
