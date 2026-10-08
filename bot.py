import os
import asyncio
import threading
import requests
import ccxt
import pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# 1. Flask Web Server (Render-ისთვის)
app_flask = Flask(__name__)

@app_flask.route('/')
def health_check():
    return "Bot is running 24/7!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

# 2. ძირითადი პარამეტრები
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = None

exchange = ccxt.binance({'enableRateLimit': True})
SYMBOLS = ['BTC/USDT', 'SOL/USDT']

# 3. გლობალური სიახლეების ფუნქცია
def get_crypto_news():
    try:
        url = "https://cryptopanic.com/api/v1/posts/?auth_token=free&filter=important"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            if results:
                latest_news = results[0]
                title = latest_news.get('title')
                domain = latest_news.get('domain')
                votes = latest_news.get('votes', {})
                positive = votes.get('positive', 0)
                negative = votes.get('negative', 0)
                
                sentiment = "Neutral 🟡"
                if positive > negative + 5:
                    sentiment = "Bullish 🟢"
                elif negative > positive + 5:
                    sentiment = "Bearish 🔴"

                return f"📰 **გლობალური სიახლე ({domain}):**\n{title}\n\n📊 **განწყობა:** {sentiment}"
    except Exception as e:
        print(f"News API Error: {e}")
    return "❌ სიახლეების წამოღება ვერ მოხერხდა."

# 4. ტექნიკური ანალიზის ფუნქცია
def analyze_market_advanced(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=200)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        df['vol_sma'] = df['volume'].rolling(window=20).mean()

        last = df.iloc[-1]
        close = last['close']
        ema200 = last['ema_200']
        rsi = last['rsi']
        volume = last['volume']
        vol_sma = last['vol_sma']

        if close > ema200 and rsi < 40 and volume > vol_sma * 1.2:
            return {
                'type': '🟢 HIGH-PROBABILITY LONG',
                'symbol': symbol,
                'price': close,
                'sl': round(close * 0.992, 2),
                'tp': round(close * 1.016, 2),
                'rsi': round(rsi, 2),
                'reason': 'EMA-200 მხარდაჭერა + დაბალი RSI + მოცულობის ზრდა'
            }
        elif close < ema200 and rsi > 60 and volume > vol_sma * 1.2:
            return {
                'type': '🔴 HIGH-PROBABILITY SHORT',
                'symbol': symbol,
                'price': close,
                'sl': round(close * 1.008, 2),
                'tp': round(close * 0.984, 2),
                'rsi': round(rsi, 2),
                'reason': 'EMA-200 წინააღმდეგობა + მაღალი RSI + მოცულობის ზრდა'
            }
        else:
            return {
                'type': '⚪ NEUTRAL (მოლოდინის რეჟიმი)',
                'symbol': symbol,
                'price': close,
                'rsi': round(rsi, 2),
                'reason': 'ზუსტი სიგნალის პირობები ჯერ არ დაკმაყოფილებულა'
            }
    except Exception as e:
        print(f"Analysis error for {symbol}: {e}")
    return None

# 5. ფონური მონიტორინგი (24/7)
async def market_monitor(app):
    global CHAT_ID
    news_counter = 0

    while True:
        if CHAT_ID:
            for symbol in SYMBOLS:
                signal = analyze_market_advanced(symbol)
                if signal and 'NEUTRAL' not in signal['type']:
                    msg = (
                        f"🎯 **{signal['type']} ({signal['symbol']})**\n\n"
                        f"💵 **შესვლის ფასი:** ${signal['price']}\n"
                        f"🛑 **Stop-Loss:** ${signal['sl']}\n"
                        f"🎯 **Take-Profit:** ${signal['tp']}\n"
                        f"📉 **RSI:** {signal['rsi']}\n"
                        f"💡 **საფუძველი:** {signal['reason']}"
                    )
                    await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')

            news_counter += 1
            if news_counter >= 30:
                news_msg = get_crypto_news()
                if "❌" not in news_msg:
                    await app.bot.send_message(chat_id=CHAT_ID, text=news_msg, parse_mode='Markdown')
                news_counter = 0

        await asyncio.sleep(60)

async def post_init(app):
    asyncio.create_task(market_monitor(app))

# --- 6. TELEGRAM BOTS COMMAND HANDLERS (ბრძანებები) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    CHAT_ID = update.effective_chat.id
    msg = (
        "🚀 **24/7 AI Crypto Monitor ჩართულია!**\n\n"
        "📜 **ხელმისაწვდომი ბრძანებები:**\n"
        "▶️ /btc — BTC/USDT-ის მომენტალური ანალიზი\n"
        "▶️ /sol — SOL/USDT-ის მომენტალური ანალიზი\n"
        "▶️ /news — უახლესი გლობალური სიახლეები\n"
        "▶️ /status — ბოტის სტატუსის შემოწმება"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ ბოტი აქტიურია და მუშაობს 24/7 რეჟიმში!")

async def btc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ითვლება BTC/USDT ანალიზი...")
    signal = analyze_market_advanced('BTC/USDT')
    if signal:
        msg = (
            f"📊 **BTC/USDT ანალიზის შედეგი:**\n\n"
            f"სტატუსი: {signal['type']}\n"
            f"💵 ფასი: ${signal['price']}\n"
            f"📉 RSI: {signal['rsi']}\n"
            f"💡 დეტალი: {signal['reason']}"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

async def sol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ითვლება SOL/USDT ანალიზი...")
    signal = analyze_market_advanced('SOL/USDT')
    if signal:
        msg = (
            f"📊 **SOL/USDT ანალიზის შედეგი:**\n\n"
            f"სტატუსი: {signal['type']}\n"
            f"💵 ფასი: ${signal['price']}\n"
            f"📉 RSI: {signal['rsi']}\n"
            f"💡 დეტალი: {signal['reason']}"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ იტვირთება უახლესი სიახლეები...")
    news = get_crypto_news()
    await update.message.reply_text(news, parse_mode='Markdown')

# --- 7. MAIN FUNCTION ---

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN არ არის მითითებული!")

    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    # ბრძანებების რეგისტრაცია
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("btc", btc_command))
    app.add_handler(CommandHandler("sol", sol_command))
    app.add_handler(CommandHandler("news", news_command))

    app.run_polling()

if __name__ == "__main__":
    main()
