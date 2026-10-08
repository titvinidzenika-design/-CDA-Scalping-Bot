import os
import time
import threading
import requests
import pandas as pd
import ccxt
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Configuration & Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")
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

# --- CryptoPanic News & Sentiment Fetcher ---
def get_cryptopanic_news(symbol=""):
    """იღებს უახლეს სიახლეებს და აფასებს განწყობას (Sentiment)"""
    if not CRYPTOPANIC_API_KEY:
        return {"text": "CryptoPanic API key არ არის მითითებული.", "sentiment": "NEUTRAL"}
    
    currencies = "BTC" if "BTC" in symbol else ("SOL" if "SOL" in symbol else "")
    url = f"
