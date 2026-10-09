import os
import time
import threading
import requests
import pandas as pd
import numpy as np
import ccxt
import feedparser
from deep_translator import GoogleTranslator
from textblob import TextBlob
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Configuration & Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# Cooldown Tracker
last_signal_time = {}

# --- CCXT Exchange Setup ---
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# --- Helper Functions for Data & Indicators ---
def fetch_ohlcv_pd(symbol, timeframe='5m', limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Error fetching OHLCV for {symbol} ({timeframe}): {e}")
        return None

def calculate_indicators(df):
    if df is None or len(df) < 50:
        return df

    # EMA 200
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    # RSI 14
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # ATR 14
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()

    # Volume SMA 20
    df['vol_sma20'] = df['volume'].rolling(window=20).mean()

    return df

# --- Candlestick Patterns Detector (1, 2, 3 Candles) ---
def detect_candlestick_patterns(df):
    if df is None or len(df) < 4:
        return []
    
    patterns = []
    c0 = df.iloc[-1]  # მიმდინარე
    c1 = df.iloc[-2]  # წინა
    c2 = df.iloc[-3]  # 2 სანთლის წინ

    body0 = abs(c0['close'] - c0['open'])
    range0 = c0['high'] - c0['low']
    body1 = abs(c1['close'] - c1['open'])
    body2 = abs(c2['close'] - c2['open'])

    if range0 == 0:
        return []

    upper_wick0 = c0['high'] - max(c0['open'], c0['close'])
    lower_wick0 = min(c0['open'], c0['close']) - c0['low']

    # --- 1-Candle ---
    if body0 <= (range0 * 0.1):
        patterns.append("⚖️ Doji")
    elif lower_wick0 >= (2 * body0) and upper_wick0 <= (body0 * 0.5):
        patterns.append("🔨 Hammer" if c0['close'] > c0['open'] else "🩸 Hanging Man")
    elif upper_wick0 >= (2 * body0) and lower_wick0 <= (body0 * 0.5):
        patterns.append("📐 Inverted Hammer" if c0['close'] > c0['open'] else "🌠 Shooting Star")

    # --- 2-Candle ---
    if c1['close'] < c1['open'] and c0['close'] > c0['open'] and c0['close'] >= c1['open'] and c0['open'] <= c1['close']:
        patterns.append("🟢 Bullish Engulfing")
    elif c1['close'] > c1['open'] and c0['close'] < c0['open'] and c0['close'] <= c1['open'] and c0['open'] >= c1['close']:
        patterns.append("🔴 Bearish Engulfing")

    # --- 3-Candle ---
    if c2['close'] < c2['open'] and body1 < (abs(c2['close'] - c2['open']) * 0.3) and c0['close'] > c0['open']:
        patterns.append("🌄 Morning Star")
    elif c2['close'] > c2['open'] and body1 < (abs(c2['close'] - c2['open']) * 0.3) and c0['close'] < c0['open']:
        patterns.append("🌇 Evening Star")

    return patterns

# --- Chart Patterns (M, W, Head & Shoulders, Flags) ---
def detect_chart_patterns(df):
    if df is None or len(df) < 30:
        return []

    patterns = []
    highs, lows = [], []

    for i in range(2, len(df) - 2):
        if df['high'].iloc[i] > df['high'].iloc[i-1] and df['high'].iloc[i] > df['high'].iloc[i+1]:
            highs.append(df['high'].iloc[i])
        if df['low'].iloc[i] < df['low'].iloc[i-1] and df['low'].iloc[i] < df['low'].iloc[i+1]:
            lows.append(df['low'].iloc[i])

    # W (Double Bottom) / M (Double Top)
    if len(lows) >= 2 and abs(lows[-1] - lows[-2]) / lows[-2] < 0.005:
        patterns.append("🇼 Double Bottom (W)")
    if len(highs) >= 2 and abs(highs[-1] - highs[-2]) / highs[-2] < 0.005:
        patterns.append("🇲 Double Top (M)")

    # Head & Shoulders
    if len(highs) >= 3 and highs[-2] > highs[-3] and highs[-2] > highs[-1]:
        patterns.append("👤 Head & Shoulders")

    # Flags
    recent = df.tail(10)
    move = (recent['close'].iloc[-1] - recent['close'].iloc[0]) / recent['close'].iloc[0]
    if move > 0.015:
        patterns.append("🚩 Bullish Flag")
    elif move < -0.015:
        patterns.append("🏴 Bearish Flag")

    return patterns

# --- Fibonacci Calculation ---
def calculate_fibonacci(df):
    if df is None or len(df) < 50:
        return {}

    high_price = df['high'].tail(50).max()
    low_price = df['low'].tail(50).min()
    diff = high_price - low_price

    return {
        'fib_0': high_price,
        'fib_0.236': high_price - 0.236 * diff,
        'fib_0.382': high_price - 0.382 * diff,
        'fib_0.500': high_price - 0.500 * diff,
        'fib_0.618': high_price - 0.618 * diff,
        'fib_0.786': high_price - 0.786 * diff,
        'fib_1': low_price
    }

# --- Free News Fetcher ---
def get_crypto_news():
    rss_urls = [
        "https://www.cryptoglobe.com/latest/feed/",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss"
    ]
    news_list = []
    translator = GoogleTranslator(source='en', target='ka')
    
    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                if title and link:
                    polarity = TextBlob(title).sentiment.polarity
                    signal = "🟢 <b>BUY (LONG)</b>" if polarity > 0.05 else ("🔴 <b>SELL (SHORT)</b>" if polarity < -0.05 else "⚪ <b>NEUTRAL</b>")

                    try:
                        translated_title = translator.translate(title)
                    except Exception:
                        translated_title = title

                    news_list.append(f"• <a href='{link}'>{translated_title}</a>\n  └ <b>სიგნალი:</b> {signal}")
            if len(news_list) >= 5:
                break
        except Exception as e:
            print(f"Error parsing RSS {url}: {e}")

    return "\n\n".join(news_list[:5]) if news_list else "❌ სიახლეების წამოღება ვერ მოხერხდა."

# --- Multi-Timeframe & Complete Technical Analysis ---
def analyze_market(symbol):
    df_5m = fetch_ohlcv_pd(symbol, timeframe='5m', limit=200)
    df_1h = fetch_ohlcv_pd(symbol, timeframe='1h', limit=200)

    if df_5m is None or df_1h is None:
        return None

    df_5m = calculate_indicators(df_5m)
    df_1h = calculate_indicators(df_1h)

    curr_5m = df_5m.iloc[-1]
    curr_1h = df_1h.iloc[-1]

    price = curr_5m['close']
    ema200_5m = curr_5m['ema200']
    rsi_5m = curr_5m['rsi']
    atr_5m = curr_5m['atr']
    vol_5m = curr_5m['volume']
    vol_sma_5m = curr_5m['vol_sma20']
    ema200_1h = curr_1h['ema200']

    # Detect Patterns & Fibonacci
    candle_patterns = detect_candlestick_patterns(df_5m)
    chart_patterns = detect_chart_patterns(df_5m)
    fib = calculate_fibonacci(df_5m)

    all_patterns = candle_patterns + chart_patterns
    patterns_text = ", ".join(all_patterns) if all_patterns else "🔍 არ არის აქტიური ფიგურა"

    signal = None
    vol_spike = vol_5m > (vol_sma_5m * 1.3)

    # Combined Strategy Logic
    if price > ema200_5m and price > ema200_1h and rsi_5m < 65 and vol_spike:
        signal = "BUY (LONG)"
    elif price < ema200_5m and price < ema200_1h and rsi_5m > 35 and vol_spike:
        signal = "SELL (SHORT)"

    # TP & SL calculation with Fibonacci & ATR
    if signal == "BUY (LONG)":
        sl = min(price - (1.5 * atr_5m), fib.get('fib_0.618', price * 0.98))
        tp = max(price + (3.0 * atr_5m), fib.get('fib_0.236', price * 1.04))
    elif signal == "SELL (SHORT)":
        sl = max(price + (1.5 * atr_5m), fib.get('fib_0.382', price * 1.02))
        tp = min(price - (3.0 * atr_5m), fib.get('fib_0.786', price * 0.96))
    else:
        sl, tp = 0.0, 0.0

    return {
        'symbol': symbol,
        'price': price,
        'rsi_5m': rsi_5m,
        'ema200_5m': ema200_5m,
        'ema200_1h': ema200_1h,
        'vol_spike': vol_spike,
        'patterns': patterns_text,
        'fib': fib,
        'signal': signal,
        'sl': sl,
        'tp': tp
    }

# --- Telegram Bot Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚀 <b>24/7 AI Crypto & Technical Pattern Monitor ჩართულია!</b>\n\n"
        "📜 <b>ხელმისაწვდომი ბრძანებები:</b>\n"
        "▶ /btc – BTC/USDT სრული ანალიზი (Patterns + Fib + TP/SL)\n"
        "▶ /sol – SOL/USDT სრული ანალიზი (Patterns + Fib + TP/SL)\n"
        "▶ /news – უახლესი სიახლეები ქართულად + სიგნალი\n"
        "▶ /status – ბოტის სტატუსი"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def btc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ითვლება BTC/USDT სრული ტექნიკური ანალიზი...")
    data = analyze_market("BTC/USDT")
    if not data:
        await update.message.reply_text("❌ მონაცემების წამოღება ვერ მოხერხდა.")
        return
    
    res = (
        f"📊 <b>BTC/USDT სრული ტექნიკური ანალიზი</b>\n\n"
        f"🔹 <b>ფასი:</b> ${data['price']:.2f}\n"
        f"🔹 <b>RSI (5m):</b> {data['rsi_5m']:.1f}\n"
        f"🔹 <b>EMA 200 (5m):</b> ${data['ema200_5m']:.2f}\n"
        f"🔹 <b>EMA 200 (1h):</b> ${data['ema200_1h']:.2f}\n"
        f"🔹 <b>Volume Spike:</b> {'✅ კი' if data['vol_spike'] else '❌ არა'}\n"
        f"🕯 <b>პატერნები / ფიგურები:</b>\n  └ {data['patterns']}\n\n"
        f"📐 <b>Fibonacci დონეები (50 bars):</b>\n"
        f"  └ 0.382: ${data['fib'].get('fib_0.382', 0):.2f}\n"
        f"  └ 0.500: ${data['fib'].get('fib_0.500', 0):.2f}\n"
        f"  └ 0.618: ${data['fib'].get('fib_0.618', 0):.2f}\n\n"
        f"💡 <b>სიგნალი:</b> {data['signal'] if data['signal'] else 'HOLD (მოლოდინში)'}\n"
    )
    if data['signal']:
        res += f"🎯 <b>Take Profit:</b> ${data['tp']:.2f}\n🛑 <b>Stop Loss:</b> ${data['sl']:.2f}\n"
    await update.message.reply_text(res, parse_mode="HTML")

async def sol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ითვლება SOL/USDT სრული ტექნიკური ანალიზი...")
    data = analyze_market("SOL/USDT")
    if not data:
        await update.message.reply_text("❌ მონაცემების წამოღება ვერ მოხერხდა.")
        return

    res = (
        f"📊 <b>SOL/USDT სრული ტექნიკური ანალიზი</b>\n\n"
        f"🔹 <b>ფასი:</b> ${data['price']:.2f}\n"
        f"🔹 <b>RSI (5m):</b> {data['rsi_5m']:.1f}\n"
        f"🔹 <b>EMA 200 (5m):</b> ${data['ema200_5m']:.2f}\n"
        f"🔹 <b>EMA 200 (1h):</b> ${data['ema200_1h']:.2f}\n"
        f"🔹 <b>Volume Spike:</b> {'✅ კი' if data['vol_spike'] else '❌ არა'}\n"
        f"🕯 <b>პატერნები / ფიგურები:</b>\n  └ {data['patterns']}\n\n"
        f"📐 <b>Fibonacci დონეები (50 bars):</b>\n"
        f"  └ 0.382: ${data['fib'].get('fib_0.382', 0):.2f}\n"
        f"  └ 0.500: ${data['fib'].get('fib_0.500', 0):.2f}\n"
        f"  └ 0.618: ${data['fib'].get('fib_0.618', 0):.2f}\n\n"
        f"💡 <b>სიგნალი:</b> {data['signal'] if data['signal'] else 'HOLD (მოლოდინში)'}\n"
    )
    if data['signal']:
        res += f"🎯 <b>Take Profit:</b> ${data['tp']:.2f}\n🛑 <b>Stop Loss:</b> ${data['sl']:.2f}\n"
    await update.message.reply_text(res, parse_mode="HTML")

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ იტვირთება და ითარგმნება სიახლეები...")
    news_text = get_crypto_news()
    res = f"📰 <b>უახლესი კრიპტო სიახლეები:</b>\n\n{news_text}"
    await update.message.reply_text(res, parse_mode="HTML", disable_web_page_preview=True)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ <b>ბოტი აქტიურია და 24/7 მონიტორინგი ჩართულია!</b>", parse_mode="HTML")

# --- Flask Server ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Crypto Scalping Bot with Patterns & Fibonacci is Alive!"

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# --- Automated Scanner ---
def auto_market_scanner():
    symbols = ["BTC/USDT", "SOL/USDT"]
    while True:
        try:
            for symbol in symbols:
                data = analyze_market(symbol)
                if data and data['signal']:
                    now = time.time()
                    if symbol in last_signal_time and (now - last_signal_time[symbol]) < 900:
                        continue

                    last_signal_time[symbol] = now
                    print(f"ALERT: {symbol} -> {data['signal']} | TP: {data['tp']} | SL: {data['sl']}")

            time.sleep(180)
        except Exception as e:
            print(f"Auto scanner error: {e}")
            time.sleep(60)

# --- Main Application Start ---
def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is missing!")
        return

    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=auto_market_scanner, daemon=True).start()

    tg_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    tg_app.add_handler(CommandHandler("start", start_command))
    tg_app.add_handler(CommandHandler("btc", btc_command))
    tg_app.add_handler(CommandHandler("sol", sol_command))
    tg_app.add_handler(CommandHandler("news", news_command))
    tg_app.add_handler(CommandHandler("status", status_command))

    print("Bot is up and running...")
    tg_app.run_polling()

if __name__ == "__main__":
    main()
