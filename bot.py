import os
import time
import threading
import requests
import pandas as pd
import ccxt
from flask import Flask
import telebot

# --- Configuration & Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# Initialize Sync Telegram Bot (Nexus standard)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode="HTML") if TELEGRAM_BOT_TOKEN else None

# Active Chat ID for 1-hour ping
active_chat_id = None

# CCXT Exchange
exchange = ccxt.binance({'enableRateLimit': True})

# --- Market Analysis Engine ---
def analyze_market(symbol):
    try:
        ohlcv_5m = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
        ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)

        df_5m = pd.DataFrame(ohlcv_5m, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df_1h = pd.DataFrame(ohlcv_1h, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])

        # EMA 200
        df_5m['ema200'] = df_5m['close'].ewm(span=200, adjust=False).mean()
        df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()

        # RSI 14
        delta = df_5m['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df_5m['rsi'] = 100 - (100 / (1 + rs))

        # ATR 14
        hl = df_5m['high'] - df_5m['low']
        hc = (df_5m['high'] - df_5m['close'].shift()).abs()
        lc = (df_5m['low'] - df_5m['close'].shift()).abs()
        df_5m['atr'] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()

        # Volume SMA 20
        df_5m['vol_sma20'] = df_5m['volume'].rolling(20).mean()

        curr = df_5m.iloc[-1]
        curr_1h = df_1h.iloc[-1]
        c1 = df_5m.iloc[-2]

        price = curr['close']
        rsi = curr['rsi']
        atr = curr['atr']
        vol_spike = curr['volume'] > (curr['vol_sma20'] * 1.3)

        # Candlestick Patterns
        patterns = []
        body0 = abs(curr['close'] - curr['open'])
        range0 = curr['high'] - curr['low']
        
        if range0 > 0:
            if body0 <= (range0 * 0.1):
                patterns.append("Doji")
            if c1['close'] < c1['open'] and curr['close'] > curr['open'] and curr['close'] >= c1['open']:
                patterns.append("Bullish Engulfing")
            elif c1['close'] > c1['open'] and curr['close'] < curr['open'] and curr['close'] <= c1['open']:
                patterns.append("Bearish Engulfing")

        # Signal Logic
        signal = None
        if price > curr['ema200'] and price > curr_1h['ema200'] and 48 < rsi < 68 and vol_spike:
            signal = "BUY (LONG)"
        elif price < curr['ema200'] and price < curr_1h['ema200'] and 32 < rsi < 52 and vol_spike:
            signal = "SELL (SHORT)"

        entry = price
        sl = entry - (1.5 * atr) if signal == "BUY (LONG)" else (entry + (1.5 * atr) if signal == "SELL (SHORT)" else 0)
        tp = entry + (3.0 * atr) if signal == "BUY (LONG)" else (entry - (3.0 * atr) if signal == "SELL (SHORT)" else 0)

        return {
            'symbol': symbol,
            'price': price,
            'rsi': rsi,
            'vol_spike': vol_spike,
            'patterns': ", ".join(patterns) if patterns else "არ არის",
            'signal': signal,
            'entry': entry,
            'sl': sl,
            'tp': tp
        }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None

# --- Telegram Command Handlers (Sync) ---
if bot:
    @bot.message_handler(commands=['start'])
    def send_start(message):
        global active_chat_id
        active_chat_id = message.chat.id
        msg = (
            "🚀 <b>Nexus Sync Crypto Bot ჩართულია!</b>\n\n"
            "🟢 ბოტი ავტომატურად გაგიფრთხილებთ სავაჭრო სიგნალების დროს.\n"
            "⏱ <b>თუ სიგნალი არ იქნება, ყოველ 1 საათში მოგწერთ სტატუსს!</b>\n\n"
            "📜 <b>ბრძანებები:</b>\n"
            "▶ /btc - BTC/USDT ტექნიკური ანალიზი\n"
            "▶ /sol - SOL/USDT ტექნიკური ანალიზი\n"
            "▶ /status - ბოტის სტატუსი"
        )
        bot.reply_to(message, msg)

    @bot.message_handler(commands=['btc'])
    def send_btc(message):
        bot.reply_to(message, "⏳ ითვლება BTC/USDT...")
        data = analyze_market("BTC/USDT")
        if not data:
            bot.send_message(message.chat.id, "❌ მონაცემების მიღების შეცდომა.")
            return
        
        msg = f"📊 <b>BTC/USDT</b>\nფასი: ${data['price']:.2f}\nRSI: {data['rsi']:.1f}\nპატერნი: {data['patterns']}\nსიგნალი: {data['signal'] if data['signal'] else 'NEUTRAL'}"
        if data['signal']:
            msg += f"\n\n📥 Entry: ${data['entry']:.2f}\n🛑 SL: ${data['sl']:.2f}\n🎯 TP: ${data['tp']:.2f}"
        bot.send_message(message.chat.id, msg)

    @bot.message_handler(commands=['sol'])
    def send_sol(message):
        bot.reply_to(message, "⏳ ითვლება SOL/USDT...")
        data = analyze_market("SOL/USDT")
        if not data:
            bot.send_message(message.chat.id, "❌ მონაცემების მიღების შეცდომა.")
            return
        
        msg = f"📊 <b>SOL/USDT</b>\nფასი: ${data['price']:.2f}\nRSI: {data['rsi']:.1f}\nპატერნი: {data['patterns']}\nსიგნალი: {data['signal'] if data['signal'] else 'NEUTRAL'}"
        if data['signal']:
            msg += f"\n\n📥 Entry: ${data['entry']:.2f}\n🛑 SL: ${data['sl']:.2f}\n🎯 TP: ${data['tp']:.2f}"
        bot.send_message(message.chat.id, msg)

    @bot.message_handler(commands=['status'])
    def send_status(message):
        bot.reply_to(message, "✅ <b>Nexus სინქრონული ბოტი აქტიურია 24/7!</b>")

# --- Hourly Auto Worker ---
def hourly_background_worker():
    while True:
        time.sleep(3600)
        if active_chat_id and bot:
            btc_data = analyze_market("BTC/USDT")
            sol_data = analyze_market("SOL/USDT")
            
            p_btc = f"${btc_data['price']:.2f}" if btc_data else "N/A"
            p_sol = f"${sol_data['price']:.2f}" if sol_data else "N/A"

            msg = (
                f"⏰ <b>საათობრივი მონიტორინგი (Nexus)</b>\n\n"
                f"🟢 <b>კოდი მუშაობს 24/7!</b>\n"
                f"• BTC/USDT: {p_btc} | NEUTRAL\n"
                f"• SOL/USDT: {p_sol} | NEUTRAL\n\n"
                f"<i>ბოტი აგრძელებს ბაზრის სკანირებას!</i>"
            )
            try:
                bot.send_message(active_chat_id, msg)
            except Exception as e:
                print(f"Worker send error: {e}")

# --- Flask Server (Render Web Service Port Listener) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Nexus Crypto Bot is Live!"

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# --- Main Entry Point ---
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN missing!")
    else:
        # 1. Reset Webhook
        try:
            requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
        except Exception as e:
            print(f"Webhook reset error: {e}")

        # 2. Start Flask Web Server Thread (Fixes Render Port requirement)
        threading.Thread(target=run_flask, daemon=True).start()

        # 3. Start Hourly Background Worker Thread
        threading.Thread(target=hourly_background_worker, daemon=True).start()

        print("Nexus Bot is running via pyTelegramBotAPI...")
        # 4. Pure Synchronous Polling (No asyncio conflicts)
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
