import os
import time
import asyncio
import pandas as pd
import ccxt
import feedparser
from textblob import TextBlob
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

last_signal_time = {}
user_chat_ids = set()

exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# --- News Analysis (Global Headlines Only) ---
def get_global_news_summary():
    rss_urls = [
        "https://www.cryptoglobe.com/latest/feed/",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss"
    ]
    
    news_lines = []
    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                title = entry.get('title', '').strip()
                if title:
                    polarity = TextBlob(title).sentiment.polarity
                    
                    if polarity > 0.05:
                        signal = "🟢 BUY"
                    elif polarity < -0.05:
                        signal = "🔴 SELL"
                    else:
                        signal = "⚪ NEUTRAL"

                    news_lines.append(f"• {title}\n  └ სიგნალი: {signal}")
            if len(news_lines) >= 5:
                break
        except Exception as e:
            print(f"Error parsing RSS {url}: {e}")

    return "\n\n".join(news_lines[:5]) if news_lines else "❌ სიახლეების წამოღება ვერ მოხერხდა."

# --- Candlestick Patterns & Indicators ---
def fetch_ohlcv_pd(symbol, timeframe='5m', limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Error fetching OHLCV for {symbol}: {e}")
        return None

def detect_candlestick_patterns(df):
    if len(df) < 2:
        return "אין პატერნი"
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    body_curr = abs(curr['close'] - curr['open'])
    range_curr = curr['high'] - curr['low']
    
    if range_curr == 0:
        return "⚪ ნეიტრალური"

    patterns = []
    
    # Engulfing
    if prev['close'] < prev['open'] and curr['close'] > curr['open']:
        if curr['close'] >= prev['open'] and curr['open'] <= prev['close']:
            patterns.append("🟢 Bullish Engulfing")
            
    if prev['close'] > prev['open'] and curr['close'] < curr['open']:
        if curr['close'] <= prev['open'] and curr['open'] >= prev['close']:
            patterns.append("🔴 Bearish Engulfing")
            
    # Hammer / Shooting Star
    lower_wick = min(curr['open'], curr['close']) - curr['low']
    upper_wick = curr['high'] - max(curr['open'], curr['close'])
    
    if lower_wick >= (2 * body_curr) and upper_wick <= (body_curr * 0.5):
        patterns.append("🔨 Hammer")
        
    if upper_wick >= (2 * body_curr) and lower_wick <= (body_curr * 0.5):
        patterns.append("🌠 Shooting Star")

    if body_curr <= (range_curr * 0.1):
        patterns.append("⚖️ Doji")

    return ", ".join(patterns) if patterns else "🔍 სტანდარტული სანთელი"

def calculate_indicators(df):
    if df is None or len(df) < 50:
        return df

    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()

    return df

def analyze_market(symbol):
    df = fetch_ohlcv_pd(symbol, timeframe='5m', limit=100)
    if df is None:
        return None

    df = calculate_indicators(df)
    pattern = detect_candlestick_patterns(df)
    curr = df.iloc[-1]

    price = curr['close']
    ema200 = curr['ema200']
    rsi = curr['rsi']
    atr = curr['atr']

    signal = None
    if price > ema200 and rsi < 65:
        signal = "BUY (LONG)"
    elif price < ema200 and rsi > 35:
        signal = "SELL (SHORT)"

    sl = price - (1.5 * atr) if signal == "BUY (LONG)" else price + (1.5 * atr)
    tp = price + (3.0 * atr) if signal == "BUY (LONG)" else price - (3.0 * atr)

    return {
        'symbol': symbol,
        'price': price,
        'rsi': rsi,
        'ema200': ema200,
        'pattern': pattern,
        'signal': signal,
        'sl': sl,
        'tp': tp
    }

# --- Telegram Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_ids.add(chat_id)
    await update.message.reply_text("🚀 Crypto Bot აქტიურია!\n\nბრძანებები:\n/btc\n/sol\n/news\n/status")

async def btc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    data = analyze_market("BTC/USDT")
    if not data:
        await update.message.reply_text("❌ შეცდომა მონაცემების წამოღებისას.")
        return
    res = (
        f"📊 BTC/USDT ანალიზი\n\n"
        f"🔹 ფასი: ${data['price']:.2f}\n"
        f"🔹 RSI: {data['rsi']:.1f}\n"
        f"🔹 EMA200: ${data['ema200']:.2f}\n"
        f"🕯 პატერნი: {data['pattern']}\n\n"
        f"💡 სიგნალი: {data['signal'] if data['signal'] else 'HOLD'}\n"
    )
    if data['signal']:
        res += f"🎯 TP: ${data['tp']:.2f} | 🛑 SL: ${data['sl']:.2f}"
    await update.message.reply_text(res)

async def sol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    data = analyze_market("SOL/USDT")
    if not data:
        await update.message.reply_text("❌ შეცდომა მონაცემების წამოღებისას.")
        return
    res = (
        f"📊 SOL/USDT ანალიზი\n\n"
        f"🔹 ფასი: ${data['price']:.2f}\n"
        f"🔹 RSI: {data['rsi']:.1f}\n"
        f"🔹 EMA200: ${data['ema200']:.2f}\n"
        f"🕯 პატერნი: {data['pattern']}\n\n"
        f"💡 სიგნალი: {data['signal'] if data['signal'] else 'HOLD'}\n"
    )
    if data['signal']:
        res += f"🎯 TP: ${data['tp']:.2f} | 🛑 SL: ${data['sl']:.2f}"
    await update.message.reply_text(res)

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text("⏳ იტვირთება გლობალური სიახლეები...")
    news_text = get_global_news_summary()
    await update.message.reply_text(f"📰 გლობალური სიახლეები & სიგნალები:\n\n{news_text}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text("✅ ბოტი მუშაობს!")

# --- Background Task ---
async def market_scanner_loop(app):
    await asyncio.sleep(5)
    while True:
        try:
            for symbol in ["BTC/USDT", "SOL/USDT"]:
                data = analyze_market(symbol)
                if data and data['signal']:
                    now = time.time()
                    if symbol in last_signal_time and (now - last_signal_time[symbol]) < 900:
                        continue
                    last_signal_time[symbol] = now
                    
                    alert = (
                        f"🚨 ავტომატური სიგნალი: {data['symbol']}\n"
                        f"💡 {data['signal']}\n"
                        f"🕯 {data['pattern']}\n"
                        f"🔹 ფასი: ${data['price']:.2f}\n"
                        f"🎯 TP: ${data['tp']:.2f} | 🛑 SL: ${data['sl']:.2f}"
                    )
                    for cid in list(user_chat_ids):
                        try:
                            await app.bot.send_message(chat_id=cid, text=alert)
                        except Exception:
                            pass
        except Exception as e:
            print(f"Scanner error: {e}")
        await asyncio.sleep(180)

async def post_init(app):
    asyncio.create_task(market_scanner_loop(app))

# --- Entry Point ---
def main():
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN missing!")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("btc", btc_command))
    app.add_handler(CommandHandler("sol", sol_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("status", status_command))

    print("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
