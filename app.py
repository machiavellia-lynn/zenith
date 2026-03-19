from flask import Flask, jsonify, render_template, request
import yfinance as yf
import pandas as pd

app = Flask(__name__)

INTERVAL_MAP = {
    "5m":  {"period": "5d",   "interval": "5m"},
    "15m": {"period": "5d",   "interval": "15m"},
    "30m": {"period": "5d",   "interval": "30m"},
    "1h":  {"period": "30d",  "interval": "1h"},
    "1d":  {"period": "180d", "interval": "1d"},
}

def flatten_columns(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).strip() for c in df.columns]
    return df

def get_col(df, *names):
    col_map = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in col_map:
            return col_map[name.lower()]
    return None

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/ohlcv")
def ohlcv():
    ticker = request.args.get("ticker", "BBRI").upper().strip()
    tf     = request.args.get("tf", "15m")

    if tf not in INTERVAL_MAP:
        return jsonify({"error": f"Timeframe tidak valid: {tf}"}), 400

    params = INTERVAL_MAP[tf]
    symbol = f"{ticker}.JK"

    try:
        raw = yf.download(
            symbol,
            period=params["period"],
            interval=params["interval"],
            auto_adjust=True,
            progress=False,
            actions=False,
        )

        if raw is None or raw.empty:
            return jsonify({"error": f"Tidak ada data untuk {symbol}. Pastikan kode saham benar."}), 404

        raw = flatten_columns(raw)
        raw = raw.dropna(how="all")

        col_open   = get_col(raw, "Open")
        col_high   = get_col(raw, "High")
        col_low    = get_col(raw, "Low")
        col_close  = get_col(raw, "Close", "Adj Close")
        col_volume = get_col(raw, "Volume")

        missing = [n for n, c in [("Open", col_open), ("High", col_high), ("Low", col_low), ("Close", col_close)] if c is None]
        if missing:
            return jsonify({"error": f"Kolom hilang: {missing}. Tersedia: {list(raw.columns)}"}), 500

        candles = []
        for ts, row in raw.iterrows():
            try:
                t = int(pd.Timestamp(ts).timestamp())
                candles.append({
                    "time":   t,
                    "open":   round(float(row[col_open]),  2),
                    "high":   round(float(row[col_high]),  2),
                    "low":    round(float(row[col_low]),   2),
                    "close":  round(float(row[col_close]), 2),
                    "volume": int(row[col_volume]) if col_volume else 0,
                })
            except Exception:
                continue

        if not candles:
            return jsonify({"error": "Data tidak bisa diparse. Coba timeframe lain."}), 500

        return jsonify({"ticker": ticker, "symbol": symbol, "tf": tf, "candles": candles, "count": len(candles)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/info")
def info():
    ticker = request.args.get("ticker", "BBRI").upper().strip()
    symbol = f"{ticker}.JK"
    try:
        t   = yf.Ticker(symbol)
        inf = t.info or {}
        return jsonify({
            "name":     inf.get("longName") or inf.get("shortName") or ticker,
            "sector":   inf.get("sector", "—"),
            "currency": inf.get("currency", "IDR"),
            "price":    inf.get("currentPrice") or inf.get("regularMarketPrice") or inf.get("previousClose"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
