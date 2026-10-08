import os
import time
import threading
import requests
import pandas as pd
import ccxt
import xml.etree.ElementTree as ET
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Configuration & Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# Cooldown Tracker: { 'BTC/USDT': timestamp, 'SOL/USDT': timestamp }
last_signal_time = {}

# --- CCXT Exchange Setup ---
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# --- Helper Functions for Data & Indicators ---
def fetch_ohlcv_pd(symbol, timeframe='5m', limit=100):
    """ითვლის OHLCV მონაცემებს და აბრუნებს Pandas DataFrame-ს"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Error fetching OHLCV for {symbol} ({timeframe}): {e}")
        return None

def calculate_indicators(df):
    """ითვლის EMA200, RSI, ATR და Volume SMA-ს"""
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

    # ATR 14 (Average True Range)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()

    # Volume SMA 20
    df['vol_sma20'] = df['volume'].rolling(window=20).mean()

    return df

# --- Free News Fetcher (CoinTelegraph RSS) ---
def get_crypto_news():
    """იღებს უახლეს სიახლეებს CoinTelegraph RSS-იდან სრულიად უფასოდ"""
    url = "https://cointelegraph.com/rss"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            items = root.findall('.//item')
            
            news_list = []
            for item in items[:5]: # იღებს ბოლო 5 სიახლეს
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                if title:
                    news_list.append(f"• [{title}]({link})")
            
            return "\n\n".join(news_list)
        else:
            return "❌ სიახლეების წამოღება ვერ მოხერხდა."
    except Exception as e:
        print(f"News RSS error: {e}")
        return "❌ სიახლეების სერვერთან კავშირი ვერ დამყარდა."

# --- Multi-Timeframe Strategy Logic ---
def analyze_market(symbol):
    """სრული ტექნიკური ანალიზი (MTF + ATR + Volume)"""
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

    # Signals Setup
    signal = None
    
    # Volume Spike Filter (Volume > 1.3 * SMA20)
    vol_spike = vol_5m > (vol_sma_5m * 1.3)

    # MTF Filter: 5m & 1h Trend Alignment
    # BUY: Price > EMA200 on 5m AND 1h, RSI < 65, Volume Spike
    if price > ema200_5m and price > ema200_1h and rsi_5m < 65 and vol_spike:
        if curr_5m['rsi'] > 45: # Momentum direction
            signal = "BUY (LONG)"

    # SELL: Price < EMA200 on 5m AND 1h, RSI > 35, Volume Spike
    elif price < ema200_5m and price < ema200_1h and rsi_5m > 35 and vol_spike:
        if curr_5m['rsi'] < 55:
            signal = "SELL (SHORT)"

    # ATR-based Dynamic Stop Loss and Take Profit
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
    msg = (
        "🚀 **24/7 AI Crypto Monitor 2.0 (High Winrate) ჩართულია!**\n\n"
        "📜 **ხელმისაწვდომი ბრძანებები:**\n"
        "▶ `/btc` – BTC/USDT-ის MTF + ATR ანალიზი\n"
        "▶ `/sol` – SOL/USDT-ის MTF + ATR ანალიზი\n"
        "▶ `/news` – უახლესი გლობალური სიახლეები\n"
        "▶ `/status` – ბოტის აქტიური სტატუსი"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def btc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ითვლება BTC/USDT სიღრმისეული ანალიზი...")
    data = analyze_market("BTC/USDT")
    if not data:
        await update.message.reply_text("❌ მონაცემების წამოღება ვერ მოხერხდა.")
        return
    
    res = (
        f"📊 **BTC/USDT ანალიზი (MTF + ATR)**\n\n"
        f"🔹 **ფასი:** ${data['price']:.2f}\n"
        f"🔹 **RSI (5m):** {data['rsi_5m']:.1f}\n"
        f"🔹 **EMA 200 (5m):** ${data['ema200_5m']:.2f}\n"
        f"🔹 **EMA 200 (1h):** ${data['ema200_1h']:.2f}\n"
        f"🔹 **Volume Spike:** {'✅ კი' if data['vol_spike'] else '❌ არა'}\n\n"
        f"💡 **სიგნალი:** {data['signal'] if data['signal'] else 'HOLD (მოოდინში)'}\n"
    )
    if data['signal']:
        res += f"🎯 **Take Profit:** ${data['tp']:.2f}\n🛑 **Stop Loss:** ${data['sl']:.2f}\n"
    await update.message.reply_text(res, parse_mode="Markdown")

async def sol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ითვლება SOL/USDT სიღრმისეული ანალიზი...")
    data = analyze_market("SOL/USDT")
    if not data:
        await update.message.reply_text("❌ მონაცემების წამოღება ვერ მოხერხდა.")
        return

    res = (
        f"📊 **SOL/USDT ანალიზი (MTF + ATR)**\n\n"
        f"🔹 **ფასი:** ${data['price']:.2f}\n"
        f"🔹 **RSI (5m):** {data['rsi_5m']:.1f}\n"
        f"🔹 **EMA 200 (5m):** ${data['ema200_5m']:.2f}\n"
        f"🔹 **EMA 200 (1h):** ${data['ema200_1h']:.2f}\n"
        f"🔹 **Volume Spike:** {'✅ კი' if data['vol_spike'] else '❌ არა'}\n\n"
        f"💡 **სიგნალი:** {data['signal'] if data['signal'] else 'HOLD (მოოდინში)'}\n"
    )
    if data['signal']:
        res += f"🎯 **Take Profit:** ${data['tp']:.2f}\n🛑 **Stop Loss:** ${data['sl']:.2f}\n"
    await update.message.reply_text(res, parse_mode="Markdown")

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ იტვირთება უახლესი კრიპტო სიახლეები...")
    news_text = get_crypto_news()
    res = f"📰 **უახლესი გლობალური კრიპტო სიახლეები (CoinTelegraph):**\n\n{news_text}"
    await update.message.reply_text(res, parse_mode="Markdown", disable_web_page_preview=True)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ **ბოტი აქტიურია და 24/7 მონიტორინგი ჩართულია!**", parse_mode="Markdown")

# --- Flask Server for Render Keep-Alive ---
app = Flask(__name__)

@app.route('/')
def home():
    return "CDA Scalping Bot 2.0 is Alive and Running!"

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# --- 24/7 Automated Signal Monitoring Loop ---
def auto_market_scanner():
    """ყოველი 3 წუთის ინტერვალით ამოწმებს ბაზარს"""
    symbols = ["BTC/USDT", "SOL/USDT"]
    
    while True:
        try:
            for symbol in symbols:
                data = analyze_market(symbol)
                if data and data['signal']:
                    now = time.time()
                    # Cooldown check: 15 mins (900 seconds)
                    if symbol in last_signal_time and (now - last_signal_time[symbol]) < 900:
                        continue

                    last_signal_time[symbol] = now
                    print(f"ALERT: {symbol} -> {data['signal']}")

            time.sleep(180) # Check every 3 minutes
        except Exception as e:
            print(f"Auto scanner error: {e}")
            time.sleep(60)

# --- Main Application Start ---
def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is missing!")
        return

    # Start Web Server in Background
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=auto_market_scanner, daemon=True).start()

    # Telegram Application Setup
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

