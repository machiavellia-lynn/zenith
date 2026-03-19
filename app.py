from flask import Flask, jsonify, render_template, request
import requests

app = Flask(__name__)

# Yahoo Finance direct API — no key needed, pakai header browser
YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com",
}

INTERVAL_MAP = {
    "5m":  {"interval": "5m",  "range": "5d"},
    "15m": {"interval": "15m", "range": "5d"},
    "30m": {"interval": "30m", "range": "5d"},
    "1h":  {"interval": "60m", "range": "1mo"},
    "1d":  {"interval": "1d",  "range": "6mo"},
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

    try:
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, headers=YF_HEADERS, params={
            "interval":          p["interval"],
            "range":             p["range"],
            "includePrePost":    "false",
            "includeAdjustedClose": "true",
        }, timeout=15)

        data = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            err = data.get("chart", {}).get("error", {})
            return jsonify({"error": err.get("description", f"Tidak ada data untuk {symbol}")}), 404

        r          = result[0]
        timestamps = r.get("timestamp", [])
        ohlcv      = r.get("indicators", {}).get("quote", [{}])[0]

        opens   = ohlcv.get("open",   [])
        highs   = ohlcv.get("high",   [])
        lows    = ohlcv.get("low",    [])
        closes  = ohlcv.get("close",  [])
        volumes = ohlcv.get("volume", [])

        candles = []
        for i, ts in enumerate(timestamps):
            try:
                o = opens[i];  h = highs[i];  l = lows[i];  c = closes[i]
                if None in (o, h, l, c):
                    continue
                candles.append({
                    "time":   int(ts),
                    "open":   round(float(o), 2),
                    "high":   round(float(h), 2),
                    "low":    round(float(l), 2),
                    "close":  round(float(c), 2),
                    "volume": int(volumes[i]) if volumes[i] else 0,
                })
            except Exception:
                continue

        if not candles:
            return jsonify({"error": "Data kosong atau semua null"}), 404

        meta  = r.get("meta", {})
        return jsonify({
            "ticker":  ticker,
            "symbol":  symbol,
            "tf":      tf,
            "candles": candles,
            "count":   len(candles),
            "name":    meta.get("longName", ticker),
            "price":   meta.get("regularMarketPrice"),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/info")
def info():
    ticker = request.args.get("ticker", "BBRI").upper().strip()
    symbol = f"{ticker}.JK"
    try:
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, headers=YF_HEADERS, params={
            "interval": "1d", "range": "1d"
        }, timeout=10)
        data = resp.json()
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
