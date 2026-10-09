import os
import time
import asyncio
import threading
import requests
import pandas as pd
import ccxt
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# CCXT Binance
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# --- Market Analysis ---
def fetch_and_analyze(symbol):
    try:
        ohlcv_5m = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
        ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)

        df_5m = pd.DataFrame(ohlcv_5m, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df_1h = pd.DataFrame(ohlcv_1h, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])

        df_5m['ema200'] = df_5m['close'].ewm(span=200, adjust=False).mean()
        df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()

        delta = df_5m['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df_5m['rsi'] = 100 - (100 / (1 + rs))

        hl = df_5m['high'] - df_5m['low']
        hc = (df_5m['high'] - df_5m['close'].shift()).abs()
        lc = (df_5m['low'] - df_5m['close'].shift()).abs()
        df_5m['atr'] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()
        df_5m['vol_sma20'] = df_5m['volume'].rolling(20).mean()

        curr = df_5m.iloc[-1]
        curr_1h = df_1h.iloc[-1]
        c1 = df_5m.iloc[-2]

        price = curr['close']
        rsi = curr['rsi']
        atr = curr['atr']
        vol_spike = curr['volume'] > (curr['vol_sma20'] * 1.3)

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

        signal = None
        if price > curr['ema200'] and price > curr_1h['ema200'] and 48 < rsi < 68 and vol_spike:
            signal = "BUY (LONG)"
        elif price < curr['ema200'] and price < curr_1h['ema200'] and 32 < rsi < 52 and vol_spike:
            signal = "SELL (SHORT)"

        entry = price
        sl, tp, sl_pct, tp_pct = 0.0, 0.0, 0.0, 0.0

        if signal == "BUY (LONG)":
            sl = entry - (1.5 * atr)
            tp = entry + (3.0 * atr)
            sl_pct = ((sl - entry) / entry) * 100
            tp_pct = ((tp - entry) / entry) * 100
        elif signal == "SELL (SHORT)":
            sl = entry + (1.5 * atr)
            tp = entry - (3.0 * atr)
            sl_pct = ((entry - sl) / entry) * 100
            tp_pct = ((entry - tp) / entry) * 100

        return {
            'symbol': symbol,
            'price': price,
            'rsi': rsi,
            'vol_spike': vol_spike,
            'patterns': ", ".join(patterns) if patterns else "არ არის",
            'signal': signal,
            'entry': entry,
            'sl': sl,
            'tp': tp,
            'sl_pct': sl_pct,
            'tp_pct': tp_pct
        }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None

# --- Telegram Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data['active_chat_id'] = update.effective_chat.id
    msg = (
        "🚀 <b>24/7 AI Crypto Monitor ჩართულია!</b>\n\n"
        "🟢 ბოტი ავტომატურად გაგიფრთხილებთ სავაჭრო სიგნალების დროს.\n"
        "⏱ <b>თუ სიგნალი არ იქნება, ყოველ 1 საათში მოგწერთ სტატუსს!</b>\n\n"
        "📜 <b>ბრძანებები:</b>\n"
        "▶ /btc - BTC/USDT ტექნიკური ანალიზი\n"
        "▶ /sol - SOL/USDT ტექნიკური ანალიზი\n"
        "▶ /status - ბოტის სტატუსი"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def btc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ითვლება BTC/USDT...")
    data = fetch_and_analyze("BTC/USDT")
    if not data:
        await update.message.reply_text("❌ მონაცემების მიღების შეცდომა.")
        return
    await send_analysis(update.effective_chat.id, context, data)

async def sol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ითვლება SOL/USDT...")
    data = fetch_and_analyze("SOL/USDT")
    if not data:
        await update.message.reply_text("❌ მონაცემების მიღების შეცდომა.")
        return
    await send_analysis(update.effective_chat.id, context, data)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ <b>ბოტი აქტიურია და მუშაობს 24/7 რეჟიმში!</b>", parse_mode="HTML")

async def send_analysis(chat_id, context, data):
    msg = (
        f"📊 <b>{data['symbol']} ტექნიკური ანალიზი</b>\n\n"
        f"🔹 <b>მიმდინარე ფასი:</b> ${data['price']:.2f}\n"
        f"🔹 <b>RSI (5m):</b> {data['rsi']:.1f}\n"
        f"🔹 <b>Volume Spike:</b> {'✅ კი' if data['vol_spike'] else '❌ არა'}\n"
        f"🕯 <b>პატერნი:</b> {data['patterns']}\n\n"
        f"💡 <b>სიგნალი:</b> {data['signal'] if data['signal'] else '⚪ NEUTRAL (მოლოდინში)'}\n"
    )
    if data['signal']:
        msg += (
            f"\n📥 <b>Entry:</b> ${data['entry']:.2f}\n"
            f"🛑 <b>Stop Loss:</b> ${data['sl']:.2f} ({data['sl_pct']:.2f}%)\n"
            f"🎯 <b>Take Profit:</b> ${data['tp']:.2f} (+{data['tp_pct']:.2f}%)\n"
            f"⚖️ <b>Risk/Reward:</b> 1:2\n"
        )
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")

# --- Flask Server (Render Port Binding) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Crypto Scalping Bot is Alive!"

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

def reset_webhook():
    if TELEGRAM_BOT_TOKEN:
        try:
            requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
        except Exception as e:
            print(f"Webhook reset error: {e}")

# --- Main Entry Point ---
def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is missing!")
        return

    reset_webhook()

    # Flask სერვერის გაშვება ცალკე თრედში Render-ისთვის
    threading.Thread(target=run_flask, daemon=True).start()

    # Telegram Bot-ის სტანდარტული გაშვება
    tg_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    tg_app.add_handler(CommandHandler("start", start_command))
    tg_app.add_handler(CommandHandler("btc", btc_command))
    tg_app.add_handler(CommandHandler("sol", sol_command))
    tg_app.add_handler(CommandHandler("status", status_command))

    print("Bot is up and listening for commands...")
    tg_app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
