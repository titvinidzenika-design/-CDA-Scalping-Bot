import os
import time
import asyncio
import pandas as pd
import numpy as np
import ccxt
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

# --- Fetch Data ---
def fetch_ohlcv(symbol, timeframe='5m', limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Error fetching {symbol} ({timeframe}): {e}")
        return None

# --- Advanced Candlestick Patterns ---
def detect_candlestick_patterns(df):
    if len(df) < 4:
        return []
    
    patterns = []
    c0 = df.iloc[-1]  # Current candle
    c1 = df.iloc[-2]  # Previous candle
    c2 = df.iloc[-3]  # 2 candles ago

    # Helper calculations
    body0 = abs(c0['close'] - c0['open'])
    range0 = c0['high'] - c0['low']
    body1 = abs(c1['close'] - c1['open'])
    range1 = c1['high'] - c1['low']
    body2 = abs(c2['close'] - c2['open'])

    if range0 == 0:
        return []

    upper_wick0 = c0['high'] - max(c0['open'], c0['close'])
    lower_wick0 = min(c0['open'], c0['close']) - c0['low']

    # --- 1-Candle Patterns ---
    if body0 <= (range0 * 0.1):
        if lower_wick0 >= (2.5 * body0) and upper_wick0 <= (body0 * 0.5):
            patterns.append("🐉 Dragonfly Doji")
        elif upper_wick0 >= (2.5 * body0) and lower_wick0 <= (body0 * 0.5):
            patterns.append("🪦 Gravestone Doji")
        else:
            patterns.append("⚖️ Doji")
    elif body0 >= (range0 * 0.85):
        if c0['close'] > c0['open']:
            patterns.append("🟩 Bullish Marubozu")
        else:
            patterns.append("🟥 Bearish Marubozu")
    else:
        if lower_wick0 >= (2 * body0) and upper_wick0 <= (body0 * 0.5):
            if c0['close'] > c0['open']:
                patterns.append("🔨 Hammer")
            else:
                patterns.append("🩸 Hanging Man")
        elif upper_wick0 >= (2 * body0) and lower_wick0 <= (body0 * 0.5):
            if c0['close'] > c0['open']:
                patterns.append("📐 Inverted Hammer")
            else:
                patterns.append("🌠 Shooting Star")

    # --- 2-Candle Patterns ---
    # Engulfing
    if c1['close'] < c1['open'] and c0['close'] > c0['open']:
        if c0['close'] >= c1['open'] and c0['open'] <= c1['close']:
            patterns.append("🟢 Bullish Engulfing")
    elif c1['close'] > c1['open'] and c0['close'] < c0['open']:
        if c0['close'] <= c1['open'] and c0['open'] >= c1['close']:
            patterns.append("🔴 Bearish Engulfing")

    # Piercing Line & Dark Cloud Cover
    if c1['close'] < c1['open'] and c0['close'] > c0['open']:
        if c0['open'] < c1['low'] and c0['close'] > (c1['open'] + c1['close']) / 2:
            patterns.append("🌅 Piercing Line")
    elif c1['close'] > c1['open'] and c0['close'] < c0['open']:
        if c0['open'] > c1['high'] and c0['close'] < (c1['open'] + c1['close']) / 2:
            patterns.append("🌩 Dark Cloud Cover")

    # Tweezers
    if abs(c0['low'] - c1['low']) <= (range0 * 0.05) and lower_wick0 > body0:
        patterns.append("🧲 Tweezer Bottom")
    elif abs(c0['high'] - c1['high']) <= (range0 * 0.05) and upper_wick0 > body0:
        patterns.append("🧲 Tweezer Top")

    # --- 3-Candle Patterns ---
    # Morning Star & Evening Star
    if c2['close'] < c2['open'] and body1 < (abs(c2['close'] - c2['open']) * 0.3) and c0['close'] > c0['open'] and c0['close'] > ((c2['open'] + c2['close']) / 2):
        patterns.append("🌄 Morning Star")
    elif c2['close'] > c2['open'] and body1 < (abs(c2['close'] - c2['open']) * 0.3) and c0['close'] < c0['open'] and c0['close'] < ((c2['open'] + c2['close']) / 2):
        patterns.append("🌇 Evening Star")

    # Three White Soldiers & Three Black Crows
    if c2['close'] > c2['open'] and c1['close'] > c1['open'] and c0['close'] > c0['open']:
        if c0['close'] > c1['close'] > c2['close']:
            patterns.append("⚔️ Three White Soldiers")
    elif c2['close'] < c2['open'] and c1['close'] < c1['open'] and c0['close'] < c0['open']:
        if c0['close'] < c1['close'] < c2['close']:
            patterns.append("🦅 Three Black Crows")

    return patterns

# --- Chart Pattern Recognition (M, W, Head & Shoulders, Flag) ---
def detect_chart_patterns(df):
    if len(df) < 40:
        return []

    chart_patterns = []

    # Find Swing Highs and Swing Lows
    highs = []
    lows = []
    
    for i in range(2, len(df) - 2):
        if df['high'].iloc[i] > df['high'].iloc[i-1] and df['high'].iloc[i] > df['high'].iloc[i-2] and \
           df['high'].iloc[i] > df['high'].iloc[i+1] and df['high'].iloc[i] > df['high'].iloc[i+2]:
            highs.append((i, df['high'].iloc[i]))
            
        if df['low'].iloc[i] < df['low'].iloc[i-1] and df['low'].iloc[i] < df['low'].iloc[i-2] and \
           df['low'].iloc[i] < df['low'].iloc[i+1] and df['low'].iloc[i] < df['low'].iloc[i+2]:
            lows.append((i, df['low'].iloc[i]))

    # Double Bottom (W Pattern) & Double Top (M Pattern)
    if len(lows) >= 2:
        l1, l2 = lows[-2][1], lows[-1][1]
        if abs(l1 - l2) / l1 < 0.005:  # Lows within 0.5%
            chart_patterns.append("🇼 Double Bottom (W ფიგურა)")

    if len(highs) >= 2:
        h1, h2 = highs[-2][1], highs[-1][1]
        if abs(h1 - h2) / h1 < 0.005:  # Highs within 0.5%
            chart_patterns.append("🇲 Double Top (M ფიგურა)")

    # Head and Shoulders / Inverse Head and Shoulders
    if len(highs) >= 3:
        h1, h2, h3 = highs[-3][1], highs[-2][1], highs[-1][1]
        if h2 > h1 and h2 > h3 and abs(h1 - h3) / h1 < 0.01:
            chart_patterns.append("👤 Head & Shoulders (თავი და მხრები)")

    if len(lows) >= 3:
        l1, l2, l3 = lows[-3][1], lows[-2][1], lows[-1][1]
        if l2 < l1 and l2 < l3 and abs(l1 - l3) / l1 < 0.01:
            chart_patterns.append("🙃 Inverse Head & Shoulders")

    # Flag Patterns (Consolidation after a move)
    recent = df.tail(15)
    move = (recent['close'].iloc[-1] - recent['close'].iloc[0]) / recent['close'].iloc[0]
    volatility = (recent['high'].max() - recent['low'].min()) / recent['close'].mean()

    if move > 0.02 and volatility < 0.015:
        chart_patterns.append("🚩 Bullish Flag (ხარის დროშა)")
    elif move < -0.02 and volatility < 0.015:
        chart_patterns.append("🏴 Bearish Flag (დათვის დროშა)")

    return chart_patterns

# --- Indicators & Strategy Core ---
def calculate_indicators(df):
    if df is None or len(df) < 50:
        return df

    # EMA 50 / 200
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # Bollinger Bands (20, 2)
    df['bb_middle'] = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_middle'] + (std * 2)
    df['bb_lower'] = df['bb_middle'] - (std * 2)

    # ATR (14)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()

    return df

def analyze_market(symbol):
    df_5m = fetch_ohlcv(symbol, timeframe='5m', limit=100)
    df_1h = fetch_ohlcv(symbol, timeframe='1h', limit=60)

    if df_5m is None or df_1h is None:
        return None

    df_5m = calculate_indicators(df_5m)
    df_1h = calculate_indicators(df_1h)

    curr_5m = df_5m.iloc[-1]
    curr_1h = df_1h.iloc[-1]

    candle_patterns = detect_candlestick_patterns(df_5m)
    chart_patterns = detect_chart_patterns(df_5m)

    all_patterns = candle_patterns + chart_patterns
    patterns_str = ", ".join(all_patterns) if all_patterns else "🔍 არ არის აქტიური ფიგურა"

    price = curr_5m['close']
    rsi = curr_5m['rsi']
    macd_hist = curr_5m['macd_hist']
    atr = curr_5m['atr']
    bb_lower = curr_5m['bb_lower']
    bb_upper = curr_5m['bb_upper']

    main_trend = "BULLISH 🟢" if curr_1h['close'] > curr_1h['ema200'] else "BEARISH 🔴"

    # Signal Confluence Logic
    signal = None
    if main_trend == "BULLISH 🟢":
        if (rsi < 42 or price <= bb_lower or "🇼 Double Bottom (W ფიგურა)" in chart_patterns or "🟢 Bullish Engulfing" in candle_patterns) and macd_hist > 0:
            signal = "BUY (LONG)"

    elif main_trend == "BEARISH 🔴":
        if (rsi > 58 or price >= bb_upper or "🇲 Double Top (M ფიგურა)" in chart_patterns or "🔴 Bearish Engulfing" in candle_patterns) and macd_hist < 0:
            signal = "SELL (SHORT)"

    sl = price - (1.5 * atr) if signal == "BUY (LONG)" else price + (1.5 * atr)
    tp = price + (3.0 * atr) if signal == "BUY (LONG)" else price - (3.0 * atr)

    return {
        'symbol': symbol,
        'price': price,
        'main_trend': main_trend,
        'rsi': rsi,
        'macd_hist': macd_hist,
        'patterns': patterns_str,
        'signal': signal,
        'sl': sl,
        'tp': tp
    }

# --- Telegram Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_ids.add(chat_id)
    await update.message.reply_text("🚀 Pro Pattern & Technical Analysis Bot აქტიურია!\n\nბრძანებები:\n/btc\n/sol\n/status")

async def btc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    data = analyze_market("BTC/USDT")
    if not data:
        await update.message.reply_text("❌ შეცდომა მონაცემების წამოღებისას.")
        return
    
    res = (
        f"📊 BTC/USDT სრული ტექნიკური ანალიზი\n\n"
        f"🔹 ფასი: ${data['price']:.2f}\n"
        f"📈 1H მთავარი ტრენდი: {data['main_trend']}\n"
        f"🔹 RSI (5M): {data['rsi']:.1f}\n"
        f"🔹 MACD Hist: {data['macd_hist']:.2f}\n"
        f"🕯 პატერნები & ფიგურები:\n  └ {data['patterns']}\n\n"
        f"💡 სიგნალი: {data['signal'] if data['signal'] else 'HOLD (მოლოდინი)'}\n"
    )
    if data['signal']:
        res += f"🎯 TP: ${data['tp']:.2f}\n🛑 SL: ${data['sl']:.2f}"
    
    await update.message.reply_text(res)

async def sol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    data = analyze_market("SOL/USDT")
    if not data:
        await update.message.reply_text("❌ შეცდომა მონაცემების წამოღებისას.")
        return
    
    res = (
        f"📊 SOL/USDT სრული ტექნიკური ანალიზი\n\n"
        f"🔹 ფასი: ${data['price']:.2f}\n"
        f"📈 1H მთავარი ტრენდი: {data['main_trend']}\n"
        f"🔹 RSI (5M): {data['rsi']:.1f}\n"
        f"🔹 MACD Hist: {data['macd_hist']:.2f}\n"
        f"🕯 პატერნები & ფიგურები:\n  └ {data['patterns']}\n\n"
        f"💡 სიგნალი: {data['signal'] if data['signal'] else 'HOLD (მოლოდინი)'}\n"
    )
    if data['signal']:
        res += f"🎯 TP: ${data['tp']:.2f}\n🛑 SL: ${data['sl']:.2f}"
    
    await update.message.reply_text(res)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text("✅ ბოტი აქტიურია და ფიგურებს სკანირებს!")

# --- 24/7 Scanner Loop ---
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
                        f"📈 1H ტრენდი: {data['main_trend']}\n"
                        f"🕯 ფიგურები: {data['patterns']}\n"
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
    app.add_handler(CommandHandler("status", status_command))

    print("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
