from flask import Flask, jsonify, render_template, request
import requests

app = Flask(__name__)

TWELVE_KEY = "aae8495bdf1444c2b9840062b0ed74e1"
TWELVE_BASE = "https://api.twelvedata.com"

INTERVAL_MAP = {
    "5m":  "5min",
    "15m": "15min",
    "30m": "30min",
    "1h":  "1h",
    "1d":  "1day",
}

OUTPUTSIZE_MAP = {
    "5m":  90,
    "15m": 90,
    "30m": 90,
    "1h":  90,
    "1d":  180,
}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/ohlcv")
def ohlcv():
    ticker   = request.args.get("ticker", "BBRI").upper().strip()
    tf       = request.args.get("tf", "15m")

    if tf not in INTERVAL_MAP:
        return jsonify({"error": f"Timeframe tidak valid: {tf}"}), 400

    symbol   = f"{ticker}:IDX"
    interval = INTERVAL_MAP[tf]
    outputsize = OUTPUTSIZE_MAP[tf]

    try:
        resp = requests.get(f"{TWELVE_BASE}/time_series", params={
            "symbol":     symbol,
            "interval":   interval,
            "outputsize": outputsize,
            "order":      "ASC",
            "apikey":     TWELVE_KEY,
        }, timeout=15)

        data = resp.json()

        if data.get("status") == "error":
            return jsonify({"error": data.get("message", "Error dari Twelve Data")}), 400

        values = data.get("values", [])
        if not values:
            return jsonify({"error": f"Tidak ada data untuk {symbol}"}), 404

        candles = []
        for row in values:
            try:
                from datetime import datetime
                dt = datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S") if " " in row["datetime"] else datetime.strptime(row["datetime"], "%Y-%m-%d")
                candles.append({
                    "time":   int(dt.timestamp()),
                    "open":   float(row["open"]),
                    "high":   float(row["high"]),
                    "low":    float(row["low"]),
                    "close":  float(row["close"]),
                    "volume": int(row.get("volume", 0)),
                })
            except Exception:
                continue

        return jsonify({
            "ticker":  ticker,
            "symbol":  symbol,
            "tf":      tf,
            "candles": candles,
            "count":   len(candles),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/info")
def info():
    ticker = request.args.get("ticker", "BBRI").upper().strip()
    symbol = f"{ticker}:IDX"
    try:
        resp = requests.get(f"{TWELVE_BASE}/quote", params={
            "symbol": symbol,
            "apikey": TWELVE_KEY,
        }, timeout=10)
        data = resp.json()
        if data.get("status") == "error":
            return jsonify({"error": data.get("message")}), 400
        return jsonify({
            "name":   data.get("name", ticker),
            "price":  float(data.get("close", 0)),
            "change": data.get("percent_change", "0"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
