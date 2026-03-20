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


def fetch_gain_range(ticker: str, date_from: str, date_to: str):
    """
    Hitung % change harga saham dari date_from ke date_to.
    date_from & date_to format: DD-MM-YYYY
    Return (gain_pct, close_price_at_date_to)
    """
    symbol = f"{ticker}.JK"
    try:
        d0 = parse_date(date_from)
        d1 = parse_date(date_to)
        # Ambil sedikit lebih lebar agar dapat candle di kedua ujung
        p1 = int((datetime(d0.year, d0.month, d0.day, tzinfo=timezone.utc) - timedelta(days=5)).timestamp())
        p2 = int((datetime(d1.year, d1.month, d1.day, tzinfo=timezone.utc) + timedelta(days=2)).timestamp())

        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            headers=YF_HEADERS,
            params={
                "interval":             "1d",
                "period1":              p1,
                "period2":              p2,
                "includeAdjustedClose": "false",
            },
            timeout=8,
        )
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None, None

        r          = result[0]
        timestamps = r.get("timestamp", [])
        quote      = r.get("indicators", {}).get("quote", [{}])[0]
        closes     = quote.get("close", [])

        # Pasangkan timestamp → close, filter None
        candles = []
        for i, ts in enumerate(timestamps):
            c = closes[i] if i < len(closes) else None
            if c is None or float(c) <= 0:
                continue
            candles.append((ts, float(c)))

        if len(candles) < 1:
            return None, None

        # Kalau single day: pakai prev close dari meta vs close hari itu
        if d0 == d1:
            meta     = r.get("meta", {})
            prev_raw = meta.get("chartPreviousClose") or meta.get("previousClose")
            price_raw = meta.get("regularMarketPrice")
            if prev_raw and price_raw and float(prev_raw) > 0:
                gain = round((float(price_raw) - float(prev_raw)) / float(prev_raw) * 100, 2)
                return gain, int(round(float(price_raw)))
            # fallback: pakai candle pertama open vs terakhir close
            if len(candles) >= 1:
                close_last = candles[-1][1]
                quote_open = quote.get("open", [])
                open_first = None
                for i, ts in enumerate(timestamps):
                    o = quote_open[i] if i < len(quote_open) else None
                    if o and float(o) > 0:
                        open_first = float(o)
                        break
                if open_first:
                    gain = round((close_last - open_first) / open_first * 100, 2)
                    return gain, int(round(close_last))
            return None, None

        # Multi-day: close hari terakhir vs close hari pertama
        close_first = candles[0][1]
        close_last  = candles[-1][1]
        gain = round((close_last - close_first) / close_first * 100, 2)
        return gain, int(round(close_last))

    except Exception:
        return None, None


# Cache gain per (ticker, date_from, date_to)
_gain_cache      = {}
_gain_cache_lock = threading.Lock()
CACHE_TTL        = 300


def get_gains_batch(tickers: list, date_from: str, date_to: str):
    now    = time.time()
    result = {}
    to_fetch = []

    with _gain_cache_lock:
        for t in tickers:
            key    = f"{t}|{date_from}|{date_to}"
            cached = _gain_cache.get(key)
            if cached and (now - cached["ts"]) < CACHE_TTL:
                result[t] = {"gain": cached["gain"], "price": cached["price"]}
            else:
                to_fetch.append(t)

    for t in to_fetch:
        gain, price = fetch_gain_range(t, date_from, date_to)
        key = f"{t}|{date_from}|{date_to}"
        with _gain_cache_lock:
            _gain_cache[key] = {"gain": gain, "price": price, "ts": time.time()}
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

    # Fetch gain% berdasarkan rentang tanggal yang dipilih user
    gains = get_gains_batch(list(data.keys()), date_from, date_to)

    tickers = []
    for t, d in data.items():
        sm  = round(d["sm_val"], 2)
        bm  = round(d["bm_val"], 2)
        cm  = round(sm - bm, 2)
        rsm = round(sm / (sm + bm) * 100, 1) if (sm + bm) > 0 else 0

        # MF: hanya tampilkan kalau ada data (tidak semua 0)
        mfp_raw = d["mf_plus"]
        mfm_raw = abs(d["mf_minus"])
        mfp  = round(mfp_raw, 2) if mfp_raw else None
        mfm  = round(mfm_raw, 2) if mfm_raw else None
        net  = round((mfp_raw - abs(d["mf_minus"])), 2) if (mfp_raw or d["mf_minus"]) else None

        g = gains.get(t, {})
        tickers.append({
            "ticker":      t,
            "clean_money": cm,
            "sm_val":      sm,
            "bm_val":      bm,
            "rsm":         rsm,
            "mf_plus":     mfp,
            "mf_minus":    mfm,
            "net_mf":      net,
            "gain_pct":    g.get("gain"),
            "price":       g.get("price"),
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


@app.route("/admin/upload-db", methods=["GET", "POST"])
def upload_db():
    # HAPUS ROUTE INI setelah zenith.db berhasil diupload!
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.method == "GET":
        return f"""
        <!DOCTYPE html><html><head>
        <style>body{{background:#080c10;color:#c8d8e8;font-family:monospace;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
        .box{{background:#0e1318;border:1px solid #1a2230;border-radius:8px;padding:32px;width:400px;}}
        h3{{color:#00e8a2;margin-bottom:20px;}}
        input,button{{width:100%;padding:10px;margin:8px 0;border-radius:5px;
        box-sizing:border-box;font-family:monospace;}}
        input{{background:#080c10;border:1px solid #1a2230;color:#c8d8e8;}}
        button{{background:#00e8a2;border:none;color:#080c10;font-weight:700;cursor:pointer;}}
        </style></head><body><div class="box">
        <h3>⬆ Upload zenith.db</h3>
        <form method="POST" enctype="multipart/form-data">
          <input type="file" name="dbfile" accept=".db" required/>
          <input type="password" name="secret" placeholder="Upload secret key" required/>
          <button type="submit">Upload ke /data/zenith.db</button>
        </form></div></body></html>
        """
    # POST
    secret = request.form.get("secret", "")
    if secret != SECRET:
        return "❌ Secret salah", 403
    f = request.files.get("dbfile")
    if not f:
        return "❌ File tidak ditemukan", 400
    os.makedirs("/data", exist_ok=True)
    f.save("/data/zenith.db")
    size = os.path.getsize("/data/zenith.db")
    return f"✅ Upload berhasil! zenith.db tersimpan di /data/zenith.db ({size:,} bytes). Sekarang hapus route ini dari app.py"



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
