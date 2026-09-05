"""
ربات هشدار RSI (اشباع خرید/فروش) با چارت کندل‌استیک
هر بار اجرا می‌شه، وضعیت RSI هر نماد رو با اجرای قبلی مقایسه می‌کنه
و فقط موقع «ورود تازه» به منطقه اشباع خرید/فروش، عکس+توضیح پست می‌کنه.
"""

import os
import sys
import json
import time
import datetime
import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf

# ---------------------- تنظیمات ----------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY")

# لیست نمادها برای رصد - هر تعداد که بخوای می‌تونی اضافه/کم کنی
# (فقط حواست باشه با محدودیت رایگان Twelve Data هماهنگ باشه)
SYMBOLS = [
    "BTC/USD", "ETH/USD", "XRP/USD", "SOL/USD",
    "GALA/USD", "ETC/USD", "DOGE/USD", "BNB/USD",
]

INTERVAL = "30min"     # تایم فریم بررسی
RSI_PERIOD = 14
OVERBOUGHT = 70
OVERSOLD = 30
STATE_FILE = "state.json"

for k, v in {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    "TWELVEDATA_API_KEY": TWELVEDATA_API_KEY,
}.items():
    if not v:
        print(f"متغیر محیطی {k} تنظیم نشده است.")
        sys.exit(1)


# ---------------------- وضعیت (برای جلوگیری از پست تکراری) ----------------------
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------- دریافت داده ----------------------
def fetch_ohlc(symbol, outputsize=100):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "outputsize": outputsize,
        "apikey": TWELVEDATA_API_KEY,
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        data = r.json()
    except Exception as e:
        print(f"خطا در دریافت {symbol}: {e}")
        return None

    if "values" not in data:
        print(f"داده نامعتبر برای {symbol}: {data.get('message', data)}")
        return None

    values = list(reversed(data["values"]))
    try:
        df = pd.DataFrame(values)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.set_index("datetime", inplace=True)
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
    except Exception as e:
        print(f"خطای پارس داده {symbol}: {e}")
        return None

    return df


# ---------------------- محاسبه RSI ----------------------
def calc_rsi_series(closes, period=14):
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def zone_of(rsi_value):
    if rsi_value is None or pd.isna(rsi_value):
        return "unknown"
    if rsi_value >= OVERBOUGHT:
        return "overbought"
    if rsi_value <= OVERSOLD:
        return "oversold"
    return "neutral"


# ---------------------- ساخت چارت ----------------------
def make_chart(df, rsi_series, symbol):
    plot_df = df.tail(60)
    rsi_tail = rsi_series.reindex(plot_df.index)

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9, 6), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    mpf.plot(plot_df, type="candle", style="charles", ax=ax1, volume=False)

    ax2.plot(range(len(rsi_tail)), rsi_tail.values, color="green", linewidth=1.3)
    ax2.axhline(OVERBOUGHT, color="red", linestyle="--", linewidth=0.8)
    ax2.axhline(OVERSOLD, color="green", linestyle="--", linewidth=0.8)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI")

    ax1.set_title(symbol)
    fig.tight_layout()

    filename = f"/tmp/{symbol.replace('/', '')}_chart.png"
    fig.savefig(filename, dpi=120)
    plt.close(fig)
    return filename


# ---------------------- ارسال به تلگرام ----------------------
def send_photo(path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(path, "rb") as photo:
        files = {"photo": photo}
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
        r = requests.post(url, data=data, files=files, timeout=30)
    if r.status_code != 200:
        print(f"خطا در ارسال عکس: {r.status_code} - {r.text}")
    else:
        print("عکس با موفقیت ارسال شد.")


def build_caption(symbol, direction, rsi_value):
    coin = symbol.split("/")[0]
    if direction == "overbought":
        return (
            f"ارز #{coin} وارد محدوده اشباع خرید شده است. ✔️\n\n"
            f"📊 تحلیل: tradingview\n"
            f"🔴 نوع واگرایی: نزولی\n"
            f"⏰ تایم فریم: 30 دقیقه\n"
            f"📉 مقدار RSI: {rsi_value:.2f}"
        )
    else:
        return (
            f"ارز #{coin} وارد محدوده اشباع فروش شده است. ✔️\n\n"
            f"📊 تحلیل: tradingview\n"
            f"🟢 نوع واگرایی: صعودی\n"
            f"⏰ تایم فریم: 30 دقیقه\n"
            f"📈 مقدار RSI: {rsi_value:.2f}"
        )


# ---------------------- اجرای اصلی ----------------------
def main():
    state = load_state()

    for symbol in SYMBOLS:
        df = fetch_ohlc(symbol)
        if df is None or len(df) < RSI_PERIOD + 5:
            time.sleep(1)
            continue

        rsi_series = calc_rsi_series(df["close"], RSI_PERIOD)
        last_rsi = rsi_series.iloc[-1]
        zone = zone_of(last_rsi)
        prev_zone = state.get(symbol, "neutral")

        print(f"{symbol}: RSI={last_rsi:.2f} | وضعیت قبلی={prev_zone} | وضعیت الان={zone}")

        if zone in ("overbought", "oversold") and zone != prev_zone:
            try:
                chart_path = make_chart(df, rsi_series, symbol)
                caption = build_caption(symbol, zone, last_rsi)
                send_photo(chart_path, caption)
            except Exception as e:
                print(f"خطا در ساخت/ارسال چارت {symbol}: {e}")

        if zone != "unknown":
            state[symbol] = zone

        time.sleep(1)  # فاصله بین درخواست‌ها برای رعایت محدودیت نرخ API

    save_state(state)


if __name__ == "__main__":
    main()
