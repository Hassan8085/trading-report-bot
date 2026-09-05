"""
ربات پست خودکار روزانه تریدینگ به کانال تلگرام
منابع داده:
  - قیمت/کندل روزانه: Twelve Data (رایگان) - هم کریپتو هم فارکس
  - تقویم اقتصادی: فید عمومی ForexFactory
ارسال پیام: API رسمی تلگرام (Bot API)
"""

import os
import sys
import datetime
import requests

# ---------------------- تنظیمات ----------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY")

CRYPTO_SYMBOLS = ["BTC/USD", "ETH/USD", "XRP/USD", "SOL/USD"]
FOREX_SYMBOLS  = ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]

REQUIRED_ENV = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    "TWELVEDATA_API_KEY": TWELVEDATA_API_KEY,
}
missing = [k for k, v in REQUIRED_ENV.items() if not v]
if missing:
    print(f"متغیرهای محیطی زیر تنظیم نشده‌اند: {missing}")
    sys.exit(1)


# ---------------------- ابزارهای محاسباتی ----------------------
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def fetch_series(symbol):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "1day",
        "outputsize": 60,
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

    values = list(reversed(data["values"]))  # قدیمی -> جدید
    try:
        closes = [float(v["close"]) for v in values]
        highs = [float(v["high"]) for v in values]
        lows = [float(v["low"]) for v in values]
    except (KeyError, ValueError) as e:
        print(f"خطای پارس داده {symbol}: {e}")
        return None

    return {"closes": closes, "highs": highs, "lows": lows}


def analyze_symbol(symbol):
    series = fetch_series(symbol)
    if not series or len(series["closes"]) < 15:
        return None

    closes, highs, lows = series["closes"], series["highs"], series["lows"]
    last_close, prev_close = closes[-1], closes[-2]
    pct_change = (last_close - prev_close) / prev_close * 100

    rsi = calc_rsi(closes)
    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)

    if sma20 and sma50:
        trend = "صعودی 🔼" if sma20 > sma50 else "نزولی 🔽"
    elif sma20:
        trend = "صعودی 🔼" if last_close > sma20 else "نزولی 🔽"
    else:
        trend = "نامشخص"

    lookback = min(20, len(lows))
    support = min(lows[-lookback:])
    resistance = max(highs[-lookback:])

    rsi_note = ""
    if rsi is not None:
        if rsi >= 70:
            rsi_note = " (اشباع خرید)"
        elif rsi <= 30:
            rsi_note = " (اشباع فروش)"

    rsi_txt = f"{rsi:.1f}{rsi_note}" if rsi is not None else "نامشخص"

    return (
        f"🔹 <b>{symbol}</b>: {last_close:,.4f}  ({pct_change:+.2f}%)\n"
        f"   RSI(14): {rsi_txt}\n"
        f"   روند: {trend}\n"
        f"   حمایت: {support:,.4f}  |  مقاومت: {resistance:,.4f}"
    )


# ---------------------- تقویم اقتصادی ----------------------
def fetch_economic_calendar():
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        events = r.json()
    except Exception as e:
        print(f"خطا در دریافت تقویم اقتصادی: {e}")
        return []

    today = datetime.datetime.utcnow().date()
    today_high_impact = []
    for ev in events:
        try:
            ev_date = datetime.datetime.fromisoformat(ev["date"]).date()
        except Exception:
            continue
        if ev_date == today and str(ev.get("impact", "")).lower() == "high":
            today_high_impact.append(ev)

    today_high_impact.sort(key=lambda e: e.get("date", ""))
    return today_high_impact[:8]


def format_calendar(events):
    if not events:
        return "📅 <b>تقویم اقتصادی امروز</b>\nرویداد پراهمیتی برای امروز ثبت نشده."

    lines = ["📅 <b>تقویم اقتصادی امروز (تاثیر بالا)</b>"]
    for ev in events:
        try:
            t = datetime.datetime.fromisoformat(ev["date"]).strftime("%H:%M UTC")
        except Exception:
            t = "--:--"
        title = ev.get("title", "?")
        country = ev.get("country", "?")
        lines.append(f"⏰ {t} | {country} | {title}")
    return "\n".join(lines)


# ---------------------- ارسال تلگرام ----------------------
def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, data=payload, timeout=20)
    if r.status_code != 200:
        print(f"خطا در ارسال به تلگرام: {r.status_code} - {r.text}")
        sys.exit(1)
    print("پیام با موفقیت ارسال شد.")


# ---------------------- ساخت پیام نهایی ----------------------
def build_report():
    today_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    lines = [f"📊 <b>گزارش روزانه بازار</b>  —  {today_str}", ""]

    lines.append("🪙 <b>کریپتو</b>")
    for sym in CRYPTO_SYMBOLS:
        result = analyze_symbol(sym)
        lines.append(result if result else f"🔹 {sym}: داده در دسترس نبود")
    lines.append("")

    lines.append("💱 <b>فارکس</b>")
    for sym in FOREX_SYMBOLS:
        result = analyze_symbol(sym)
        lines.append(result if result else f"🔹 {sym}: داده در دسترس نبود")
    lines.append("")

    events = fetch_economic_calendar()
    lines.append(format_calendar(events))
    lines.append("")
    lines.append("⚠️ این گزارش صرفاً جهت اطلاع‌رسانی است و توصیه سرمایه‌گذاری محسوب نمی‌شود.")

    return "\n".join(lines)


if __name__ == "__main__":
    report = build_report()
    print(report)
    # تلگرام محدودیت 4096 کاراکتر برای هر پیام دارد
    if len(report) > 4000:
        report = report[:3990] + "\n…(کوتاه‌شده)"
    send_to_telegram(report)
