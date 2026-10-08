import os
import asyncio
import threading
import ccxt
import pandas as pd
import pandas_ta as ta
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# 1. Flask სერვერი Render-ისთვის
app_flask = Flask(__name__)

@app_flask.route('/')
def health_check():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

# 2. Telegram & Exchange პარამეტრები
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = None

exchange = ccxt.binance()
SYMBOLS = ['BTC/USDT', 'SOL/USDT']

# 3. ანალიზის ფუნქცია
def analyze_market(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['RSI'] = ta.rsi(df['close'], length=14)
        df['EMA_20'] = ta.ema(df['close'], length=20)
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)

        last_row = df.iloc[-1]
        close_price = last_row['close']
        rsi = last_row['RSI']
        ema_20 = last_row['EMA_20']
        atr = last_row['ATR']

        if rsi < 35 and close_price > ema_20:
            return {
                'type': '🟢 LONG',
                'symbol': symbol,
                'price': close_price,
                'sl': round(close_price - (atr * 1.5), 2),
                'tp': round(close_price + (atr * 3.0), 2),
                'rsi': round(rsi, 2)
            }
        elif rsi > 65 and close_price < ema_20:
            return {
                'type': '🔴 SHORT',
                'symbol': symbol,
                'price': close_price,
                'sl': round(close_price + (atr * 1.5), 2),
                'tp': round(close_price - (atr * 3.0), 2),
                'rsi': round(rsi, 2)
            }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
    return None

# 4. ფონური მონიტორინგი
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
                        f"💵 **ფასი:** ${signal['price']}\n"
                        f"🛑 **SL:** ${signal['sl']} | 🎯 **TP:** ${signal['tp']}\n"
                        f"📉 **RSI:** {signal['rsi']}"
                    )
                    await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
        await asyncio.sleep(60)

async def post_init(app):
    asyncio.create_task(market_monitor(app))

# 5. /start ბრძანების დამუშავება
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    CHAT_ID = update.effective_chat.id
    await update.message.reply_text(
        "გამარჯობა! 👋\n"
        "BTC და SOL სკალპინგის მონიტორინგი ჩაირთო.\n"
        "სიგნალის გამოჩენისთანავე მიიღებთ შეტყობინებას."
    )

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN არ არის მითითებული!")

    # Flask გაშვება
    threading.Thread(target=run_flask, daemon=True).start()

    # Application აწყობა
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()

