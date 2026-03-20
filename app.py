from flask import Flask, jsonify, render_template, request
from datetime import datetime, timedelta, timezone
import requests
import sqlite3
import os
import time
import threading

app = Flask(__name__)

# ── Config ──────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", r"C:\Users\rabim\Downloads\zenith_project\zenith.db")
WIB     = timezone(timedelta(hours=7))

YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com",
}

INTERVAL_MAP = {
    "5m":  {"interval": "5m",  "days": 59},
    "15m": {"interval": "15m", "days": 59},
    "30m": {"interval": "30m", "days": 59},
    "1h":  {"interval": "60m", "days": 720},
    "1d":  {"interval": "1d",  "days": 99999},
}

# ── Gain% Cache (5 menit) ───────────────────────────────────────────────
_gain_cache      = {}   # ticker → {"gain": float, "price": int, "ts": epoch}
_gain_cache_lock = threading.Lock()
CACHE_TTL        = 300  # detik


def fetch_gain_yf(ticker: str):
    """Fetch % change hari ini dari Yahoo Finance. Return (gain_pct, price)."""
    symbol = f"{ticker}.JK"
    now    = datetime.now(timezone.utc)
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            headers=YF_HEADERS,
            params={
                "interval":             "1d",
                "period1":              int((now - timedelta(days=5)).timestamp()),
                "period2":              int(now.timestamp()),
                "includeAdjustedClose": "false",
            },
            timeout=8,
        )
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None, None
        meta      = result[0].get("meta", {})
        price_raw = meta.get("regularMarketPrice")
        prev_raw  = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price_raw and prev_raw and float(prev_raw) > 0:
            gain = round((float(price_raw) - float(prev_raw)) / float(prev_raw) * 100, 2)
            return gain, int(round(float(price_raw)))
        return None, None
    except Exception:
        return None, None


def get_gains_batch(tickers: list):
    """Return dict ticker → {gain, price} dengan cache 5 menit."""
    now    = time.time()
    result = {}
    to_fetch = []

    with _gain_cache_lock:
        for t in tickers:
            cached = _gain_cache.get(t)
            if cached and (now - cached["ts"]) < CACHE_TTL:
                result[t] = {"gain": cached["gain"], "price": cached["price"]}
            else:
                to_fetch.append(t)

    for t in to_fetch:
        gain, price = fetch_gain_yf(t)
        with _gain_cache_lock:
            _gain_cache[t] = {"gain": gain, "price": price, "ts": time.time()}
        result[t] = {"gain": gain, "price": price}

    return result


# ── Helpers ──────────────────────────────────────────────────────────────
def parse_date(s: str):
    """DD-MM-YYYY → datetime.date"""
    return datetime.strptime(s, "%d-%m-%Y").date()


def date_to_sortkey(s: str):
    """DD-MM-YYYY → YYYYMMDD integer for SQLite sorting."""
    try:
        d = datetime.strptime(s, "%d-%m-%Y")
        return int(d.strftime("%Y%m%d"))
    except Exception:
        return 0


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Routes ───────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


# ── API: flow data ────────────────────────────────────────────────────────
@app.route("/api/flow")
def flow():
    today_wib = datetime.now(WIB).strftime("%d-%m-%Y")
    date_from = request.args.get("date_from", today_wib)
    date_to   = request.args.get("date_to",   today_wib)

    try:
        parse_date(date_from)
        parse_date(date_to)
    except ValueError:
        return jsonify({"error": "Format tanggal salah, gunakan DD-MM-YYYY"}), 400

    # Buat list tanggal valid dalam rentang (DD-MM-YYYY)
    try:
        d0 = parse_date(date_from)
        d1 = parse_date(date_to)
        if d0 > d1:
            d0, d1 = d1, d0
        dates = []
        cur = d0
        while cur <= d1:
            dates.append(cur.strftime("%d-%m-%Y"))
            cur += timedelta(days=1)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    placeholders = ",".join("?" for _ in dates)

    try:
        conn = get_db()
        rows = conn.execute(f"""
            SELECT
                ticker,
                channel,
                SUM(value_numeric)    AS val,
                SUM(mf_delta_numeric) AS mf
            FROM raw_messages
            WHERE date IN ({placeholders})
            GROUP BY ticker, channel
        """, dates).fetchall()
        conn.close()
    except Exception as e:
        return jsonify({"error": f"DB error: {e}"}), 500

    # Agregasi per ticker
    data = {}
    for row in rows:
        t = row["ticker"]
        if t not in data:
            data[t] = {"sm_val": 0, "bm_val": 0, "mf_plus": 0, "mf_minus": 0}
        if row["channel"] == "smart":
            data[t]["sm_val"]  += row["val"]  or 0
            data[t]["mf_plus"] += row["mf"]   or 0
        else:
            data[t]["bm_val"]   += row["val"] or 0
            data[t]["mf_minus"] += row["mf"]  or 0

    if not data:
        return jsonify({"tickers": [], "totals": {}})

    # Fetch gain% batch
    gains = get_gains_batch(list(data.keys()))

    tickers = []
    for t, d in data.items():
        sm   = round(d["sm_val"],  2)
        bm   = round(d["bm_val"],  2)
        mfp  = round(d["mf_plus"], 2)
        mfm  = round(abs(d["mf_minus"]), 2)  # simpan absolut, tanda dari net
        net  = round(mfp - mfm, 2)
        cm   = round(sm - bm, 2)
        rsm  = round(sm / (sm + bm) * 100, 1) if (sm + bm) > 0 else 0

        g    = gains.get(t, {})
        tickers.append({
            "ticker":     t,
            "clean_money": cm,
            "sm_val":     sm,
            "bm_val":     bm,
            "rsm":        rsm,
            "mf_plus":    mfp,
            "mf_minus":   mfm,
            "net_mf":     net,
            "gain_pct":   g.get("gain"),
            "price":      g.get("price"),
        })

    # Sort default: clean_money desc
    tickers.sort(key=lambda x: x["clean_money"], reverse=True)

    # Totals untuk stats bar
    totals = {
        "sm":     round(sum(x["sm_val"]   for x in tickers), 2),
        "bm":     round(sum(x["bm_val"]   for x in tickers), 2),
        "mf_plus":  round(sum(x["mf_plus"]  for x in tickers), 2),
        "mf_minus": round(sum(x["mf_minus"] for x in tickers), 2),
        "net_cm": round(sum(x["clean_money"] for x in tickers), 2),
        "net_mf": round(sum(x["net_mf"]   for x in tickers), 2),
        "count":  len(tickers),
    }

    return jsonify({"tickers": tickers, "totals": totals, "date_from": date_from, "date_to": date_to})


# ── API: OHLCV (chart) ────────────────────────────────────────────────────
@app.route("/api/ohlcv")
def ohlcv():
    ticker = request.args.get("ticker", "BBRI").upper().strip()
    tf     = request.args.get("tf", "15m")

    if tf not in INTERVAL_MAP:
        return jsonify({"error": f"Timeframe tidak valid: {tf}"}), 400

    p      = INTERVAL_MAP[tf]
    symbol = f"{ticker}.JK"
    now    = datetime.now(timezone.utc)
    period2 = int(now.timestamp())
    period1 = 0 if p["days"] >= 9999 else int((now - timedelta(days=p["days"])).timestamp())

    try:
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, headers=YF_HEADERS, params={
            "interval":             p["interval"],
            "period1":              period1,
            "period2":              period2,
            "includePrePost":       "false",
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
                o = opens[i]  if i < len(opens)   else None
                h = highs[i]  if i < len(highs)   else None
                l = lows[i]   if i < len(lows)    else None
                c = closes[i] if i < len(closes)  else None
                v = volumes[i] if i < len(volumes) else 0
                if None in (o, h, l, c): continue
                if any(x <= 0 for x in (o, h, l, c)): continue
                if not (h >= o and h >= l and h >= c): continue
                if not (l <= o and l <= h and l <= c): continue
                dt_wib = datetime.fromtimestamp(ts, tz=WIB)
                wib_ts = ts + (7 * 3600)
                candle = {
                    "time":         wib_ts,
                    "open":         int(round(float(o))),
                    "high":         int(round(float(h))),
                    "low":          int(round(float(l))),
                    "close":        int(round(float(c))),
                    "volume":       int(v) if v else 0,
                    "datetime_wib": dt_wib.strftime("%Y-%m-%d %H:%M"),
                }
                key = dt_wib.strftime("%Y-%m-%d") if p["interval"] == "1d" else wib_ts
                candles_map[key] = candle
            except Exception:
                continue

        candles = sorted(candles_map.values(), key=lambda x: x["time"])
        if not candles:
            return jsonify({"error": "Data kosong atau semua null"}), 404

        meta      = r.get("meta", {})
        price_raw = meta.get("regularMarketPrice")
        return jsonify({
            "ticker":     ticker,
            "symbol":     symbol,
            "tf":         tf,
            "candles":    candles,
            "count":      len(candles),
            "name":       meta.get("longName", ticker),
            "price":      int(round(float(price_raw))) if price_raw else None,
            "data_range": f"{candles[0]['datetime_wib']} → {candles[-1]['datetime_wib']} WIB",
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/info")
def info():
    ticker = request.args.get("ticker", "BBRI").upper().strip()
    symbol = f"{ticker}.JK"
    try:
        now  = datetime.now(timezone.utc)
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
        meta      = result[0].get("meta", {})
        price_raw = meta.get("regularMarketPrice")
        return jsonify({
            "name":  meta.get("longName") or meta.get("shortName") or ticker,
            "price": int(round(float(price_raw))) if price_raw else None,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
