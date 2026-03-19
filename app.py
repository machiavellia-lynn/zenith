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
    "1d":  {"interval": "1d",  "days": 99999},
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
    period1 = 0 if p["days"] >= 9999 else int((now - timedelta(days=p["days"])).timestamp())

    try:
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, headers=YF_HEADERS, params={
            "interval":             p["interval"],
            "period1":              period1,
            "period2":              period2,
            "includePrePost":       "false",
            # PENTING: false → pakai harga asli tanpa adjustment
            "includeAdjustedClose": "false",
        }, timeout=20)

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

        candles_map = {}
        for i, ts in enumerate(timestamps):
            try:
                o = opens[i] if i < len(opens)   else None
                h = highs[i] if i < len(highs)   else None
                l = lows[i]  if i < len(lows)    else None
                c = closes[i] if i < len(closes) else None
                v = volumes[i] if i < len(volumes) else 0

                # Skip candle yang ada nilai None atau tidak masuk akal
                if None in (o, h, l, c):
                    continue
                if any(x <= 0 for x in (o, h, l, c)):
                    continue
                # Validasi OHLC logic: high harus >= semua, low harus <= semua
                if not (h >= o and h >= l and h >= c):
                    continue
                if not (l <= o and l <= h and l <= c):
                    continue

                dt_wib = datetime.fromtimestamp(ts, tz=WIB)

                # Shift timestamp ke WIB: tambah 7 jam ke Unix ts
                # Sehingga frontend bisa pakai getUTCHours() dan dapat jam WIB
                wib_ts = ts + (7 * 3600)

                # IDX: harga bulat (tidak ada desimal)
                candle = {
                    "time":         wib_ts,
                    "open":         int(round(float(o))),
                    "high":         int(round(float(h))),
                    "low":          int(round(float(l))),
                    "close":        int(round(float(c))),
                    "volume":       int(v) if v else 0,
                    "datetime_wib": dt_wib.strftime("%Y-%m-%d %H:%M"),
                }

                if p["interval"] == "1d":
                    key = dt_wib.strftime("%Y-%m-%d")
                else:
                    key = wib_ts

                candles_map[key] = candle
            except Exception:
                continue

        candles = sorted(candles_map.values(), key=lambda x: x["time"])

        if not candles:
            return jsonify({"error": "Data kosong atau semua null"}), 404

        meta = r.get("meta", {})
        price_raw = meta.get("regularMarketPrice")
        price = int(round(float(price_raw))) if price_raw else None

        return jsonify({
            "ticker":     ticker,
            "symbol":     symbol,
            "tf":         tf,
            "candles":    candles,
            "count":      len(candles),
            "name":       meta.get("longName", ticker),
            "price":      price,
            "data_range": f"{candles[0]['datetime_wib']} → {candles[-1]['datetime_wib']} WIB",
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/info")
def info():
    ticker = request.args.get("ticker", "BBRI").upper().strip()
    symbol = f"{ticker}.JK"
    try:
        now = datetime.now(timezone.utc)
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, headers=YF_HEADERS, params={
            "interval": "1d",
            "period1":  int((now - timedelta(days=2)).timestamp()),
            "period2":  int(now.timestamp()),
            "includeAdjustedClose": "false",
        }, timeout=10)
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return jsonify({"error": "not found"}), 404
        meta  = result[0].get("meta", {})
        price_raw = meta.get("regularMarketPrice")
        return jsonify({
            "name":  meta.get("longName") or meta.get("shortName") or ticker,
            "price": int(round(float(price_raw))) if price_raw else None,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
