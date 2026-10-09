import os
import time
import threading
import requests
import pandas as pd
import ccxt
import feedparser
from deep_translator import GoogleTranslator
from textblob import TextBlob
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Configuration & Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

last_signal_time = {}

# --- CCXT Exchange Setup ---
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# --- Helper Functions ---
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

    df['vol_sma20'] = df['volume'].rolling(window=20).mean()
    return df

def detect_patterns(df):
    if df is None or len(df) < 30:
        return []
    
    patterns = []
    c0, c1, c2 = df.iloc[-1], df.iloc[-2], df.iloc[-3]
    body0 = abs(c0['close'] - c0['open'])
    range0 = c0['high'] - c0['low']
    body1 = abs(c1['close'] - c1['open'])

    if range0 > 0:
        upper_wick = c0['high'] - max(c0['open'], c0['close'])
        lower_wick = min(c0['open'], c0['close']) - c0['low']

        if body0 <= (range0 * 0.1):
            patterns.append("Doji")
        elif lower_wick >= (2 * body0) and upper_wick <= (body0 * 0.5):
            patterns.append("Hammer" if c0['close'] > c0['open'] else "Hanging Man")
        elif upper_wick >= (2 * body0) and lower_wick <= (body0 * 0.5):
            patterns.append("Inverted Hammer" if c0['close'] > c0['open'] else "Shooting Star")

        if c1['close'] < c1['open'] and c0['close'] > c0['open'] and c0['close'] >= c1['open']:
            patterns.append("Bullish Engulfing")
        elif c1['close'] > c1['open'] and c0['close'] < c0['open'] and c0['close'] <= c1['open']:
            patterns.append("Bearish Engulfing")

        if c2['close'] < c2['open'] and body1 < (abs(c2['close'] - c2['open']) * 0.3) and c0['close'] > c0['open']:
            patterns.append("Morning Star")
        elif c2['close'] > c2['open'] and body1 < (abs(c2['close'] - c2['open']) * 0.3) and c0['close'] < c0['open']:
            patterns.append("Evening Star")

    lows = df['low'].tail(20).values
    highs = df['high'].tail(20).values
    if len(lows) >= 10 and abs(min(lows[:5]) - min(lows[-5:])) / min(lows[:5]) < 0.005:
        patterns.append("W Pattern (Double Bottom)")
    if len(highs) >= 10 and abs(max(highs[:5]) - max(highs[-5:])) / max(highs[:5]) < 0.005:
        patterns.append("M Pattern (Double Top)")

    return patterns

def calculate_fibonacci(df):
    if df is None or len(df) < 50:
        return {}
    high = df['high'].tail(50).max()
    low = df['low'].tail(50).min()
    diff = high - low
    return {
        '0.382': high - 0.382 * diff,
        '0.500': high - 0.500 * diff,
        '0.618': high - 0.618 * diff
    }

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
                    analysis = TextBlob(title)
                    polarity = analysis.sentiment.polarity
                    
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

    patterns_found = detect_patterns(df_5m)
    fib_levels = calculate_fibonacci(df_5m)
    patterns_text = ", ".join(patterns_found) if patterns_found else "არ არის აქტიური პატერნი"

    signal = None
    vol_spike = vol_5m > (vol_sma_5m * 1.3)

    if price > ema200_5m and price > ema200_1h and rsi_5m < 65 and vol_spike:
        if curr_5m['rsi'] > 45:
            signal = "BUY (LONG)"
    elif price < ema200_5m and price < ema200_1h and rsi_5m > 35 and vol_spike:
        if curr_5m['rsi'] < 55:
            signal = "SELL (SHORT)"

    entry = price
    sl, tp, sl_pct, tp_pct = 0.0, 0.0, 0.0, 0.0

    if signal == "BUY (LONG)":
        sl = entry - (1.5 * atr_5m)
        tp = entry + (3.0 * atr_5m)
        sl_pct = ((sl - entry) / entry) * 100
        tp_pct = ((tp - entry) / entry) * 100
    elif signal == "SELL (SHORT)":
        sl = entry + (1.5 * atr_5m)
        tp = entry - (3.0 * atr_5m)
        sl_pct = ((entry - sl) / entry) * 100
        tp_pct = ((entry - tp) / entry) * 100

    return {
        'symbol': symbol,
        'price': price,
        'entry': entry,
        'rsi_5m': rsi_5m,
        'vol_spike': vol_spike,
        'patterns': patterns_text,
        'fib': fib_levels,
        'signal': signal,
        'sl': sl,
        'tp': tp,
        'sl_pct': sl_pct,
        'tp_pct': tp_pct
    }

# --- Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚀 <b>24/7 AI Crypto Monitor ჩართულია!</b>\n\n"
        "📜 <b>ბრძანებები:</b>\n"
        "▶ /btc – BTC/USDT ანალიზი & Entry/SL/TP\n"
        "▶ /sol – SOL/USDT ანალიზი & Entry/SL/TP\n"
        "▶ /news – კრიპტო სიახლეები\n"
        "▶ /status – ბოტის სტატუსი"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def btc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ითვლება BTC/USDT...")
    data = analyze_market("BTC/USDT")
    if not data:
        await update.message.reply_text("❌ მონაცემების წამოღება ვერ მოხერხდა.")
        return
    
    res = (
        f"📊 <b>BTC/USDT ანალიზი & ორდერი</b>\n\n"
        f"🔹 <b>მიმდინარე ფასი:</b> ${data['price']:.2f}\n"
        f"🔹 <b>RSI (5m):</b> {data['rsi_5m']:.1f}\n"
        f"🔹 <b>Volume Spike:</b> {'✅ კი' if data['vol_spike'] else '❌ არა'}\n"
        f"🕯 <b>პატერნი:</b> {data['patterns']}\n"
        f"📐 <b>Fib 0.5:</b> ${data['fib'].get('0.500', 0):.2f}\n\n"
        f"💡 <b>სიგნალი:</b> {data['signal'] if data['signal'] else 'HOLD (მოლოდინში)'}\n"
    )
    if data['signal']:
        res += (
            f"\n📥 <b>Entry:</b> ${data['entry']:.2f}\n"
            f"🛑 <b>Stop Loss:</b> ${data['sl']:.2f} ({data['sl_pct']:.2f}%)\n"
            f"🎯 <b>Take Profit:</b> ${data['tp']:.2f} (+{data['tp_pct']:.2f}%)\n"
            f"⚖️ <b>R:R Ratio:</b> 1:2\n"
        )
    await update.message.reply_text(res, parse_mode="HTML")

async def sol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ითვლება SOL/USDT...")
    data = analyze_market("SOL/USDT")
    if not data:
        await update.message.reply_text("❌ მონაცემების წამოღება ვერ მოხერხდა.")
        return

    res = (
        f"📊 <b>SOL/USDT ანალიზი & ორდერი</b>\n\n"
        f"🔹 <b>მიმდინარე ფასი:</b> ${data['price']:.2f}\n"
        f"🔹 <b>RSI (5m):</b> {data['rsi_5m']:.1f}\n"
        f"🔹 <b>Volume Spike:</b> {'✅ კი' if data['vol_spike'] else '❌ არა'}\n"
        f"🕯 <b>პატერნი:</b> {data['patterns']}\n"
        f"📐 <b>Fib 0.5:</b> ${data['fib'].get('0.500', 0):.2f}\n\n"
        f"💡 <b>სიგნალი:</b> {data['signal'] if data['signal'] else 'HOLD (მოლოდინში)'}\n"
    )
    if data['signal']:
        res += (
            f"\n📥 <b>Entry:</b> ${data['entry']:.2f}\n"
            f"🛑 <b>Stop Loss:</b> ${data['sl']:.2f} ({data['sl_pct']:.2f}%)\n"
            f"🎯 <b>Take Profit:</b> ${data['tp']:.2f} (+{data['tp_pct']:.2f}%)\n"
            f"⚖️ <b>R:R Ratio:</b> 1:2\n"
        )
    await update.message.reply_text(res, parse_mode="HTML")

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ იტვირთება სიახლეები...")
    news_text = get_crypto_news()
    await update.message.reply_text(f"📰 <b>უახლესი კრიპტო სიახლეები:</b>\n\n{news_text}", parse_mode="HTML", disable_web_page_preview=True)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ <b>ბოტი აქტიურია!</b>", parse_mode="HTML")

# --- Flask Server ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Scalping Bot is Alive!"

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# --- Force Delete Webhook Helper ---
def reset_webhook():
    if TELEGRAM_BOT_TOKEN:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook?drop_pending_updates=true"
            requests.get(url, timeout=5)
            print("Webhook cleared successfully.")
        except Exception as e:
            print(f"Failed to clear webhook: {e}")

# --- Main Entry Point ---
def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is missing!")
        return

    reset_webhook()

    # Flask background thread
    threading.Thread(target=run_flask, daemon=True).start()

    # Telegram Bot setup
    tg_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    tg_app.add_handler(CommandHandler("start", start_command))
    tg_app.add_handler(CommandHandler("btc", btc_command))
    tg_app.add_handler(CommandHandler("sol", sol_command))
    tg_app.add_handler(CommandHandler("news", news_command))
    tg_app.add_handler(CommandHandler("status", status_command))

    print("Bot is listening for commands...")
    tg_app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
