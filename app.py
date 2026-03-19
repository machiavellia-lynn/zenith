from flask import Flask, jsonify, render_template, request
import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd

app = Flask(__name__)

INTERVAL_MAP = {
    "5m":  {"period": "5d",  "interval": "5m"},
    "15m": {"period": "5d",  "interval": "15m"},
    "30m": {"period": "5d",  "interval": "30m"},
    "1h":  {"period": "30d", "interval": "1h"},
    "1d":  {"period": "180d","interval": "1d"},
}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/ohlcv")
def ohlcv():
    ticker = request.args.get("ticker", "BBRI").upper()
    tf     = request.args.get("tf", "15m")

    if tf not in INTERVAL_MAP:
        return jsonify({"error": "Invalid timeframe"}), 400

    params  = INTERVAL_MAP[tf]
    symbol  = f"{ticker}.JK"

    try:
        raw = yf.download(
            symbol,
            period=params["period"],
            interval=params["interval"],
            auto_adjust=True,
            progress=False,
        )

        if raw.empty:
            return jsonify({"error": f"No data for {symbol}"}), 404

        # Flatten MultiIndex columns if present
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        raw = raw.dropna()
        candles = []
        for ts, row in raw.iterrows():
            t = int(ts.timestamp())
            candles.append({
                "time":   t,
                "open":   round(float(row["Open"]),   2),
                "high":   round(float(row["High"]),   2),
                "low":    round(float(row["Low"]),    2),
                "close":  round(float(row["Close"]),  2),
                "volume": int(row["Volume"]),
            })

        return jsonify({
            "ticker":   ticker,
            "symbol":   symbol,
            "tf":       tf,
            "candles":  candles,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/info")
def info():
    ticker = request.args.get("ticker", "BBRI").upper()
    symbol = f"{ticker}.JK"
    try:
        t    = yf.Ticker(symbol)
        inf  = t.info
        return jsonify({
            "name":     inf.get("longName", ticker),
            "sector":   inf.get("sector", "—"),
            "currency": inf.get("currency", "IDR"),
            "price":    inf.get("currentPrice") or inf.get("regularMarketPrice"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
