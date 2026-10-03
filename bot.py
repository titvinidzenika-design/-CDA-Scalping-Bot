import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "გამარჯობა! CDA Scalping Bot ჩაირთო.\n\n"
        "ეს სატესტო ვერსიაა. რეალური საბაზრო სიგნალები ჯერ არ არის ჩართული.\n\n"
        "გამოიყენე /help ბრძანებების სანახავად."
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "სისტემის სტატუსი: მუშაობს სატესტო რეჟიმში.\n"
        "საბაზრო მონაცემები: ჯერ არ არის დაკავშირებული.\n"
        "ავტომატური ვაჭრობა: გამორთულია."
    )

async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ანალიზის მოდული ჯერ მზადდება. BTC და SOL მონაცემების წყარო მოგვიანებით დაემატება."
    )

async def signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ამ დროისთვის დადასტურებული სიგნალები არ არის."
    )

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "საწყისი პარამეტრები:\n"
        "აქტივები: BTC, SOL\n"
        "ტაიმფრეიმები: 4H, 1H, 15M, 5M\n"
        "რეჟიმი: მხოლოდ შეტყობინებები"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - ბოტის გაშვება\n"
        "/status - სისტემის სტატუსი\n"
        "/analyze - ანალიზი\n"
        "/signals - ბოლო სიგნალები\n"
        "/settings - პარამეტრები\n"
        "/help - დახმარება"
    )

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN არ არის მითითებული")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("signals", signals))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("help", help_command))
    app.run_polling()

if __name__ == "__main__":
    main()