import os
import asyncio
import threading
import ccxt
import pandas as pd
import pandas_ta as ta
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# 1. Flask სერვერი Render-ის პორტისთვის
app_flask = Flask(__name__)

@app_flask.route('/')
def health_check():
    return "Bot is running perfectly!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

# 2. Telegram Bot Configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = None  # ინახავს მომხმარებლის CHAT ID-ს /start-ზე დაჭერისას

exchange = ccxt.binance()
SYMBOLS = ['BTC/USDT', 'SOL/USDT']

# 3. ტექნიკური ანალიზის და სიგნალის გენერაციის ლოგიკა
def analyze_market(symbol):
    try:
        # იღებს ბოლო 100 სანთელს 5-წუთიან ტაიმფრეიმზე
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # ინდიკატორების დათვლა
        df['RSI'] = ta.rsi(df['close'], length=14)
        df['EMA_20'] = ta.ema(df['close'], length=20)
        df['EMA_50'] = ta.ema(df['close'], length=50)
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)

        last_row = df.iloc[-1]
        close_price = last_row['close']
        rsi = last_row['RSI']
        ema_20 = last_row['EMA_20']
        ema_50 = last_row['EMA_50']
        atr = last_row['ATR']

        # LONG სცენარი
        if rsi < 35 and close_price > ema_20:
            stop_loss = round(close_price - (atr * 1.5), 2)
            take_profit = round(close_price + (atr * 3.0), 2)
            return {
                'type': '🟢 LONG',
                'symbol': symbol,
                'price': close_price,
                'sl': stop_loss,
                'tp': take_profit,
                'rsi': round(rsi, 2)
            }
        
        # SHORT სცენარი
        elif rsi > 65 and close_price < ema_20:
            stop_loss = round(close_price + (atr * 1.5), 2)
            take_profit = round(close_price - (atr * 3.0), 2)
            return {
                'type': '🔴 SHORT',
                'symbol': symbol,
                'price': close_price,
                'sl': stop_loss,
                'tp': take_profit,
                'rsi': round(rsi, 2)
            }
            
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
    
    return None

# 4. ავტომატური მონიტორინგის ციკლი
async def market_monitor(app):
    global CHAT_ID
    while True:
        if CHAT_ID:
            for symbol in SYMBOLS:
                signal = analyze_market(symbol)
                if signal:
                    message = (
                        f"🚨 **SCALPING ALERT ({signal['symbol']})**\n\n"
                        f"📊 **მიმართულება:** {signal['type']}\n"
                        f"💵 **შესვლის ფასი:** ${signal['price']}\n"
                        f"🛑 **Stop-Loss:** ${signal['sl']}\n"
                        f"🎯 **Take-Profit:** ${signal['tp']}\n"
                        f"📉 **RSI:** {signal['rsi']}\n\n"
                        f"⚠️ *მხოლოდ გაფრთხილება — არა ავტომატური ვაჭრობა!*"
                    )
                    await app.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
        
        # შემოწმება ყოველ 60 წამში ერთხელ
        await asyncio.sleep(60)

# 5. ბოტის ბრძანებები
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    CHAT_ID = update.effective_chat.id
    await update.message.reply_text(
        "გამარჯობა! BTC და SOL სკალპინგის მონიტორინგი ჩაირთო.\n"
        "სიგნალის გამოჩენისთანავე მიიღებთ შეტყობინებას."
    )

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN არ არის მითითებული")

    # Flask-ის გაშვება ფონში
    threading.Thread(target=run_flask, daemon=True).start()

    # Telegram ბოტის ინიციალიზაცია
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    # მონიტორინგის გაშვება
    loop = asyncio.get_event_loop()
    loop.create_task(market_monitor(app))

    app.run_polling()

if __name__ == "__main__":
    main()

