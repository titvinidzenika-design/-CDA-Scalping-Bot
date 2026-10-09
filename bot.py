import os
import time
import asyncio
import pandas as pd
import ccxt
import feedparser
from textblob import TextBlob
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

# --- Configuration & Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# Cooldown Tracker & Chat ID Storage
last_signal_time = {}
user_chat_ids = set()
tg_app_global = None

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

# --- News Fetcher ---
def get_crypto_news():
    rss_urls = [
        "https://www.cryptoglobe.com/latest/feed/",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss"
    ]
    
    news_list = []
    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                if title and link:
                    title_lower = title.lower()
                    has_btc = 'btc' in title_lower or 'bitcoin' in title_lower
                    has_sol = 'sol' in title_lower or 'solana' in title_lower
                    
                    if has_btc and has_sol:
                        coin_tag = "🟡 BTC & 🟣 SOL"
                    elif has_btc:
                        coin_tag = "🟡 BTC (Bitcoin)"
                    elif has_sol:
                        coin_tag = "🟣 SOL (Solana)"
                    else:
                        coin_tag = "🌐 ALL CRYPTO (BTC & SOL)"

                    analysis = TextBlob(title)
                    polarity = analysis.sentiment.polarity
                    
                    if polarity > 0.05:
                        signal = "🟢 BUY (LONG / მოსალოდნელია ზრდა)"
                    elif polarity < -0.05:
                        signal = "🔴 SELL (SHORT / მოსალოდნელია ვარდნა)"
                    else:
                        signal = "⚪ NEUTRAL (ნეიტრალური)"

                    news_list.append(
                        f"• {title}\n"
                        f"  ├ აქტივი: {coin_tag}\n"
                        f"  └ სიგნალი: {signal}\n"
                        f"  🔗 {link}"
                    )
            if len(news_list) >= 5:
                break
        except Exception as e:
            print(f"Error parsing RSS {url}: {e}")

    if news_list:
        return "\n\n".join(news_list[:5])
    else:
        return "❌ სიახლეების წამოღება ვერ მოხერხდა."

# --- Multi-Timeframe Strategy Logic ---
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

    signal = None
    vol_spike = vol_5m > (vol_sma_5m * 1.3)

    if price > ema200_5m and price > ema200_1h and rsi_5m < 65 and vol_spike:
        if curr_5m['rsi'] > 45:
            signal = "BUY (LONG)"

    elif price < ema200_5m and price < ema200_1h and rsi_5m > 35 and vol_spike:
        if curr_5m['rsi'] < 55:
            signal = "SELL (SHORT)"

    sl = price - (1.5 * atr_5m) if signal == "BUY (LONG)" else price + (1.5 * atr_5m)
    tp = price + (3.0 * atr_5m) if signal == "BUY (LONG)" else price - (3.0 * atr_5m)

    return {
        'symbol': symbol,
        'price': price,
        'rsi_5m': rsi_5m,
        'ema200_5m': ema200_5m,
        'ema200_1h': ema200_1h,
        'vol_spike': vol_spike,
        'signal': signal,
        'sl': sl,
        'tp': tp
    }

# --- Telegram Bot Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_ids.add(chat_id)
    
    msg = (
        "🚀 24/7 AI Crypto Monitor ჩართულია!\n\n"
        "📜 ხელმისაწვდომი ბრძანებები:\n"
        "▶ /btc – BTC/USDT-ის მომენტალური ანალიზი\n"
        "▶ /sol – SOL/USDT-ის მომენტალური ანალიზი\n"
        "▶ /news – უახლესი გლობალური სიახლეები\n"
        "▶ /status – ბოტის სტატუსის შემოწმება"
    )
    await update.message.reply_text(msg)

async def btc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text("⏳ ითვლება BTC/USDT ანალიზი...")
    data = analyze_market("BTC/USDT")
    if not data:
        await update.message.reply_text("❌ მონაცემების წამოღება ვერ მოხერხდა.")
        return
    
    res = (
        f"📊 BTC/USDT ანალიზი (MTF + ATR)\n\n"
        f"🔹 ფასი: ${data['price']:.2f}\n"
        f"🔹 RSI (5m): {data['rsi_5m']:.1f}\n"
        f"🔹 EMA 200 (5m): ${data['ema200_5m']:.2f}\n"
        f"🔹 EMA 200 (1h): ${data['ema200_1h']:.2f}\n"
        f"🔹 Volume Spike: {'✅ კი' if data['vol_spike'] else '❌ არა'}\n\n"
        f"💡 სიგნალი: {data['signal'] if data['signal'] else 'HOLD (მოლოდინში)'}\n"
    )
    if data['signal']:
        res += f"🎯 Take Profit: ${data['tp']:.2f}\n🛑 Stop Loss: ${data['sl']:.2f}\n"
    await update.message.reply_text(res)

async def sol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text("⏳ ითვლება SOL/USDT ანალიზი...")
    data = analyze_market("SOL/USDT")
    if not data:
        await update.message.reply_text("❌ მონაცემების წამოღება ვერ მოხერხდა.")
        return

    res = (
        f"📊 SOL/USDT ანალიზი (MTF + ATR)\n\n"
        f"🔹 ფასი: ${data['price']:.2f}\n"
        f"🔹 RSI (5m): {data['rsi_5m']:.1f}\n"
        f"🔹 EMA 200 (5m): ${data['ema200_5m']:.2f}\n"
        f"🔹 EMA 200 (1h): ${data['ema200_1h']:.2f}\n"
        f"🔹 Volume Spike: {'✅ კი' if data['vol_spike'] else '❌ არა'}\n\n"
        f"💡 სიგნალი: {data['signal'] if data['signal'] else 'HOLD (მოლოდინში)'}\n"
    )
    if data['signal']:
        res += f"🎯 Take Profit: ${data['tp']:.2f}\n🛑 Stop Loss: ${data['sl']:.2f}\n"
    await update.message.reply_text(res)

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text("⏳ იტვირთება უახლესი სიახლეები...")
    news_text = get_crypto_news()
    res = f"📰 უახლესი კრიპტო სიახლეები და ბაზარზე გავლენა:\n\n{news_text}"
    await update.message.reply_text(res, disable_web_page_preview=True)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text("✅ სტატუსი: ბოტი აქტიურია და 24/7 მონიტორინგი ჩართულია!")

# --- Flask Server ---
app = Flask(__name__)

@app.route('/')
def home():
    return "CDA Scalping Bot 2.0 is Alive and Running!"

# --- Background Scanner Job ---
def scan_market_job():
    global tg_app_global
    if not tg_app_global:
        return

    symbols = ["BTC/USDT", "SOL/USDT"]
    for symbol in symbols:
        try:
            data = analyze_market(symbol)
            if data and data['signal']:
                now = time.time()
                if symbol in last_signal_time and (now - last_signal_time[symbol]) < 900:
                    continue

                last_signal_time[symbol] = now
                alert_text = (
                    f"🚨 ავტომატური სიგნალი: {data['symbol']}\n\n"
                    f"💡 მოქმედება: {data['signal']}\n"
                    f"🔹 მიმდინარე ფასი: ${data['price']:.2f}\n"
                    f"🎯 Take Profit: ${data['tp']:.2f}\n"
                    f"🛑 Stop Loss: ${data['sl']:.2f}\n"
                )
                for cid in list(user_chat_ids):
                    try:
                        asyncio.run(tg_app_global.bot.send_message(chat_id=cid, text=alert_text))
                    except Exception as e:
                        print(f"Failed to send alert to {cid}: {e}")
        except Exception as e:
            print(f"Error scanning {symbol}: {e}")

# --- Main Application Start ---
def main():
    global tg_app_global
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is missing!")
        return

    # Telegram App setup
    tg_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    tg_app_global = tg_app

    tg_app.add_handler(CommandHandler("start", start_command))
    tg_app.add_handler(CommandHandler("btc", btc_command))
    tg_app.add_handler(CommandHandler("sol", sol_command))
    tg_app.add_handler(CommandHandler("news", news_command))
    tg_app.add_handler(CommandHandler("status", status_command))

    # APScheduler Background Scanner (Every 3 mins)
    scheduler = BackgroundScheduler()
    scheduler.add_job(scan_market_job, 'interval', minutes=3)
    scheduler.start()

    print("Bot is up and running...")
    tg_app.run_polling()

if __name__ == "__main__":
    main()