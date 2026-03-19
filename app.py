from flask import Flask, jsonify, render_template, request
from datetime import datetime, timedelta, timezone
import requests

app = Flask(__name__)

YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com",
}

WIB = timezone(timedelta(hours=7))

INTERVAL_MAP = {
    "5m":  {"interval": "5m",  "days": 59},
    "15m": {"interval": "15m", "days": 59},
    "30m": {"interval": "30m", "days": 59},
    "1h":  {"interval": "60m", "days": 720},
    "1d":  {"interval": "1d",  "days": 99999},  # sejak IPO
}

# Yahoo Finance max intraday limits (hard limit dari API mereka)
INTRADAY_MAX_DAYS = {
    "5m": 60, "15m": 60, "30m": 60, "60m": 60,
}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/ohlcv")
def ohlcv():
    ticker = request.args.get("ticker", "BBRI").upper().strip()
    tf     = request.args.get("tf", "15m")

    if tf not in INTERVAL_MAP:
        return jsonify({"error": f"Timeframe tidak valid: {tf}"}), 400

    p      = INTERVAL_MAP[tf]
    symbol = f"{ticker}.JK"

    now     = datetime.now(timezone.utc)
    period2 = int(now.timestamp())
    # Untuk daily: period1=0 → Yahoo return data sejak IPO / awal tersedia
    # Untuk intraday: Yahoo hard limit ~60 hari
    if p["days"] >= 9999:
        period1 = 0
    else:
        period1 = int((now - timedelta(days=p["days"])).timestamp())

    try:
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, headers=YF_HEADERS, params={
            "interval":             p["interval"],
            "period1":              period1,
            "period2":              period2,
            "includePrePost":       "false",
            "includeAdjustedClose": "true",
        }, timeout=15)

        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            err = data.get("chart", {}).get("error", {})
            return jsonify({"error": err.get("description", f"Tidak ada data untuk {symbol}")}), 404

        r          = result[0]
        timestamps = r.get("timestamp", [])
        quote      = r.get("indicators", {}).get("quote", [{}])[0]

        opens   = quote.get("open",   [])
        highs   = quote.get("high",   [])
        lows    = quote.get("low",    [])
        closes  = quote.get("close",  [])
        volumes = quote.get("volume", [])

        candles_map = {}  # key=date string untuk dedup daily, key=timestamp untuk intraday
        for i, ts in enumerate(timestamps):
            try:
                o = opens[i]; h = highs[i]; l = lows[i]; c = closes[i]
                if None in (o, h, l, c):
                    continue

                # Konversi UTC → WIB (+7 jam) untuk display yang benar
                dt_wib = datetime.fromtimestamp(ts, tz=WIB)

                candle = {
                    "time":   int(dt_wib.timestamp()),
                    "open":   round(float(o), 2),
                    "high":   round(float(h), 2),
                    "low":    round(float(l), 2),
                    "close":  round(float(c), 2),
                    "volume": int(volumes[i]) if i < len(volumes) and volumes[i] else 0,
                    "datetime_wib": dt_wib.strftime("%Y-%m-%d %H:%M"),
                }

                # Untuk daily: dedup pakai tanggal (keep yang terakhir = lebih lengkap)
                # Untuk intraday: pakai full timestamp
                if p["interval"] == "1d":
                    key = dt_wib.strftime("%Y-%m-%d")
                else:
                    key = int(dt_wib.timestamp())

                candles_map[key] = candle
            except Exception:
                continue

        candles = sorted(candles_map.values(), key=lambda x: x["time"])

        if not candles:
            return jsonify({"error": "Data kosong atau semua null"}), 404

        meta = r.get("meta", {})
        return jsonify({
            "ticker":     ticker,
            "symbol":     symbol,
            "tf":         tf,
            "candles":    candles,
            "count":      len(candles),
            "name":       meta.get("longName", ticker),
            "price":      meta.get("regularMarketPrice"),
            "data_range": f"{candles[0]['datetime_wib']} → {candles[-1]['datetime_wib']} WIB",
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/info")
def info():
    ticker = request.args.get("ticker", "BBRI").upper().strip()
    symbol = f"{ticker}.JK"
    try:
        now     = datetime.now(timezone.utc)
        period1 = int((now - timedelta(days=2)).timestamp())
        period2 = int(now.timestamp())

        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, headers=YF_HEADERS, params={
            "interval": "1d", "period1": period1, "period2": period2
        }, timeout=10)
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return jsonify({"error": "not found"}), 404
        meta = result[0].get("meta", {})
        return jsonify({
            "name":  meta.get("longName") or meta.get("shortName") or ticker,
            "price": meta.get("regularMarketPrice"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
