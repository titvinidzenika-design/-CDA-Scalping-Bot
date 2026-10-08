import os
import asyncio
import threading
import ccxt
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Flask სერვერი Render-ის პორტისთვის
app_flask = Flask(__name__)

@app_flask.route('/')
def health_check():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

# Telegram & Exchange
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = None
exchange = ccxt.binance()
SYMBOLS = ['BTC/USDT', 'SOL/USDT']

def analyze_market(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=20)
        closes = [x[4] for x in ohlcv]
        if not closes:
            return None

        current_price = closes[-1]
        avg_price = sum(closes) / len(closes)

        if current_price > avg_price * 1.005:
            return {
                'type': '🟢 LONG (ზრდის სიგნალი)',
                'symbol': symbol,
                'price': current_price,
                'sl': round(current_price * 0.99, 2),
                'tp': round(current_price * 1.02, 2)
            }
        elif current_price < avg_price * 0.995:
            return {
                'type': '🔴 SHORT (კლების სიგნალი)',
                'symbol': symbol,
                'price': current_price,
                'sl': round(current_price * 1.01, 2),
                'tp': round(current_price * 0.98, 2)
            }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
    return None

async def market_monitor(app):
    global CHAT_ID
    while True:
        if CHAT_ID:
            for symbol in SYMBOLS:
                signal = analyze_market(symbol)
                if signal:
                    msg = (
                        f"🚨 **SCALPING ALERT ({signal['symbol']})**\n\n"
                        f"📊 **მიმართულება:** {signal['type']}\n"
                        f"💵 **მიმდინარე ფასი:** ${signal['price']}\n"
                        f"🛑 **SL:** ${signal['sl']} | 🎯 **TP:** ${signal['tp']}"
                    )
                    await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
        await asyncio.sleep(60)

async def post_init(app):
    asyncio.create_task(market_monitor(app))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    CHAT_ID = update.effective_chat.id
    await update.message.reply_text(
        "გამარჯობა! 👋\n"
        "BTC და SOL სკალპინგის მონიტორინგი წარმატებით ჩაირთო.\n"
        "სიგნალის გამოჩენისთანავე მიიღებთ შეტყობინებას."
    )

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN არ არის მითითებული!")

    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()

