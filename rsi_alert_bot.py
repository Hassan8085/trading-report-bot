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
import matplotlib.patches as patches

# ---------------------- تنظیمات ----------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY")

# لیست نمادها برای رصد - هر تعداد که بخوای می‌تونی اضافه/کم کنی
# (فقط حواست باشه با محدودیت رایگان Twelve Data هماهنگ باشه)
SYMBOLS = [
    "BTC/USD", "ETH/USD", "XRP/USD", "SOL/USD",
    "GALA/USD", "ETC/USD", "DOGE/USD", "BNB/USD",
    "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD",
    "LTC/USD", "TRX/USD", "POL/USD", "SHIB/USD",
    "UNI/USD", "ATOM/USD", "NEAR/USD", "FIL/USD",
    "XLM/USD", "ALGO/USD", "SAND/USD", "ICP/USD",
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
    n = len(plot_df)

    bg = "#0d1117"
    grid_color = "#1c2333"
    text_color = "#d7dee8"
    up_color = "#1fae6b"
    down_color = "#e04b4b"
    gold = "#f2b705"

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9, 6), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
        facecolor=bg,
    )

    ax1.set_facecolor(bg)
    for i, (_, row) in enumerate(plot_df.iterrows()):
        color = up_color if row["close"] >= row["open"] else down_color
        ax1.plot([i, i], [row["low"], row["high"]], color=color, linewidth=1, zorder=2)
        body_bottom = min(row["open"], row["close"])
        body_height = abs(row["close"] - row["open"])
        if body_height == 0:
            body_height = (row["high"] - row["low"]) * 0.01 or 0.0001
        ax1.add_patch(patches.Rectangle(
            (i - 0.3, body_bottom), 0.6, body_height,
            facecolor=color, edgecolor=color, zorder=3,
        ))
    ax1.set_xlim(-1, n)
    ax1.grid(color=grid_color, linestyle=":", linewidth=0.6, alpha=0.6)
    ax1.set_title(symbol, color=text_color, fontsize=13, fontweight="bold")
    ax1.tick_params(colors=text_color, labelbottom=False)
    for spine in ax1.spines.values():
        spine.set_color(grid_color)

    ax2.set_facecolor(bg)
    ax2.plot(range(len(rsi_tail)), rsi_tail.values, color=gold, linewidth=1.6)
    ax2.axhline(OVERBOUGHT, color=down_color, linestyle="--", linewidth=0.9, alpha=0.8)
    ax2.axhline(OVERSOLD, color=up_color, linestyle="--", linewidth=0.9, alpha=0.8)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI", color=text_color)
    ax2.tick_params(colors=text_color)
    ax2.grid(color=grid_color, linestyle=":", linewidth=0.6, alpha=0.6)
    for spine in ax2.spines.values():
        spine.set_color(grid_color)

    channel_handle = TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID.startswith("@") else f"@{TELEGRAM_CHAT_ID}"
    fig.text(0.985, 0.012, channel_handle, color=text_color, alpha=0.55,
              fontsize=10, fontweight="bold", ha="right", va="bottom")

    fig.tight_layout()

    filename = f"/tmp/{symbol.replace('/', '')}_chart.png"
    fig.savefig(filename, dpi=130, facecolor=bg)
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
    tv_link = f"https://www.tradingview.com/symbols/{coin}USD/"
    channel_handle = TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID.startswith("@") else f"@{TELEGRAM_CHAT_ID}"

    if direction == "overbought":
        return (
            f"ارز #{coin} وارد محدوده اشباع خرید شده است. ✔️\n\n"
            f'📊 تحلیل: <a href="{tv_link}">tradingview</a>\n'
            f"🔴 نوع واگرایی: نزولی\n"
            f"⏰ تایم فریم: 30 دقیقه\n"
            f"📉 مقدار RSI: {rsi_value:.2f}\n\n"
            f"{channel_handle}"
        )
    else:
        return (
            f"ارز #{coin} وارد محدوده اشباع فروش شده است. ✔️\n\n"
            f'📊 تحلیل: <a href="{tv_link}">tradingview</a>\n'
            f"🟢 نوع واگرایی: صعودی\n"
            f"⏰ تایم فریم: 30 دقیقه\n"
            f"📈 مقدار RSI: {rsi_value:.2f}\n\n"
            f"{channel_handle}"
        )


# ---------------------- اجرای اصلی ----------------------
def main():
    state = load_state()

    for symbol in SYMBOLS:
        df = fetch_ohlc(symbol)
        if df is None or len(df) < RSI_PERIOD + 5:
            time.sleep(8)
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

        time.sleep(8)  # فاصله بین درخواست‌ها برای رعایت محدودیت نرخ API (8 ارز در دقیقه مجاز است)

    save_state(state)


if __name__ == "__main__":
    main()
