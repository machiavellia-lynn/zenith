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
    Single day  → close hari itu vs close hari sebelumnya
    Multi day   → close date_to vs close date_from
    """
    symbol = f"{ticker}.JK"
    try:
        d0 = parse_date(date_from)
        d1 = parse_date(date_to)
        # Ambil 10 hari sebelum date_from agar ada prev candle
        # +3 hari setelah date_to agar candle hari itu pasti masuk
        p1 = int((datetime(d0.year, d0.month, d0.day, tzinfo=timezone.utc) - timedelta(days=10)).timestamp())
        p2 = int((datetime(d1.year, d1.month, d1.day, tzinfo=timezone.utc) + timedelta(days=3)).timestamp())

        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            headers=YF_HEADERS,
            params={
                "interval":             "1d",
                "period1":              p1,
                "period2":              p2,
                "includeAdjustedClose": "false",
            },
            timeout=10,
        )
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None, None

        r          = result[0]
        timestamps = r.get("timestamp", [])
        quote      = r.get("indicators", {}).get("quote", [{}])[0]
        closes     = quote.get("close", [])

        # Build list (date_str WIB YYYY-MM-DD, close)
        # IDX candle timestamps dari Yahoo bisa UTC midnight atau UTC+7
        # Pakai WIB (UTC+7) untuk date matching yang benar
        candles = []
        for i, ts in enumerate(timestamps):
            c = closes[i] if i < len(closes) else None
            if not c or float(c) <= 0:
                continue
            # Konversi ke WIB untuk dapat tanggal trading yang benar
            dt_wib = datetime.fromtimestamp(ts, tz=WIB)
            candles.append((dt_wib.strftime("%Y-%m-%d"), float(c)))

        if not candles:
            return None, None

        d0_str = d0.strftime("%Y-%m-%d")
        d1_str = d1.strftime("%Y-%m-%d")

        # Cari candle dengan tanggal paling dekat ≤ target
        def find_close_on_or_before(target_str):
            best = None
            for date_str, close in candles:
                if date_str <= target_str:
                    best = (date_str, close)
            return best

        result_d1 = find_close_on_or_before(d1_str)
        if not result_d1:
            return None, None

        close_d1 = result_d1[1]
        price    = int(round(close_d1))

        if d0 == d1:
            # Single day: bandingkan close d1 vs candle sebelumnya
            idx = next((i for i, (ds, _) in enumerate(candles) if ds == result_d1[0]), None)
            if idx is not None and idx > 0:
                close_prev = candles[idx - 1][1]
                gain = round((close_d1 - close_prev) / close_prev * 100, 2)
                return gain, price
            return None, price
        else:
            result_d0 = find_close_on_or_before(d0_str)
            if not result_d0 or result_d0[1] <= 0:
                return None, price
            close_d0 = result_d0[1]
            gain = round((close_d1 - close_d0) / close_d0 * 100, 2)
            return gain, price

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

        # Query SM/BM dari raw_messages
        rows_sm_bm = conn.execute(f"""
            SELECT
                ticker,
                channel,
                SUM(mf_delta_numeric) AS mf
            FROM raw_messages
            WHERE date IN ({placeholders})
            GROUP BY ticker, channel
        """, dates).fetchall()

        # Query MF+/MF- dari raw_mf_messages
        rows_mf = conn.execute(f"""
            SELECT
                ticker,
                channel,
                SUM(mf_numeric)       AS mf,
                SUM(mft_numeric)      AS mft,
                SUM(cm_delta_numeric) AS cm_delta
            FROM raw_mf_messages
            WHERE date IN ({placeholders})
            GROUP BY ticker, channel
        """, dates).fetchall()

        conn.close()
    except Exception as e:
        return jsonify({"error": f"DB error: {e}"}), 500

    # Agregasi SM/BM per ticker
    data = {}
    for row in rows_sm_bm:
        t = row["ticker"]
        if t not in data:
            data[t] = {"sm_val": 0, "bm_val": 0, "mf_plus": None, "mf_minus": None, "net_mf": None}
        if row["channel"] == "smart":
            data[t]["sm_val"] += row["mf"] or 0
        else:
            data[t]["bm_val"] += abs(row["mf"] or 0)

    # Agregasi MF+/MF- per ticker dari raw_mf_messages
    for row in rows_mf:
        t = row["ticker"]
        if t not in data:
            data[t] = {"sm_val": 0, "bm_val": 0, "mf_plus": None, "mf_minus": None, "net_mf": None}
        if row["channel"] == "mf_plus":
            data[t]["mf_plus"] = (data[t]["mf_plus"] or 0) + (row["mf"] or 0)
        elif row["channel"] == "mf_minus":
            data[t]["mf_minus"] = (data[t]["mf_minus"] or 0) + abs(row["mf"] or 0)

    # Hitung net_mf per ticker
    for t, d in data.items():
        if d["mf_plus"] is not None or d["mf_minus"] is not None:
            mfp = d["mf_plus"]  or 0
            mfm = d["mf_minus"] or 0
            data[t]["net_mf"] = round(mfp - mfm, 2)

    if not data:
        return jsonify({"tickers": [], "totals": {}})

    gains = get_gains_batch(list(data.keys()), date_from, date_to)

    tickers = []
    for t, d in data.items():
        sm  = round(d["sm_val"], 2)
        bm  = round(d["bm_val"], 2)
        cm  = round(sm - bm, 2)
        rsm = round(sm / (sm + bm) * 100, 1) if (sm + bm) > 0 else 0
        mfp = round(d["mf_plus"],  2) if d["mf_plus"]  is not None else None
        mfm = round(d["mf_minus"], 2) if d["mf_minus"] is not None else None
        net = round(d["net_mf"],   2) if d["net_mf"]   is not None else None

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

    def safe_sum(key):
        total = round(sum(x[key] or 0 for x in tickers), 2)
        return total if total != 0 else None

    totals = {
        "sm":       round(sum(x["sm_val"]      for x in tickers), 2),
        "bm":       round(sum(x["bm_val"]      for x in tickers), 2),
        "mf_plus":  safe_sum("mf_plus"),
        "mf_minus": safe_sum("mf_minus"),
        "net_cm":   round(sum(x["clean_money"] for x in tickers), 2),
        "net_mf":   safe_sum("net_mf"),
        "count":    len(tickers),
    }

    return jsonify({"tickers": tickers, "totals": totals, "date_from": date_from, "date_to": date_to})


# ── API: transactions per ticker ─────────────────────────────────────────
@app.route("/api/transactions")
def transactions():
    ticker    = request.args.get("ticker", "").upper().strip()
    today_wib = datetime.now(WIB).strftime("%d-%m-%Y")
    date_from = request.args.get("date_from", today_wib)
    date_to   = request.args.get("date_to",   today_wib)

    if not ticker:
        return jsonify({"error": "ticker required"}), 400

    try:
        parse_date(date_from)
        parse_date(date_to)
    except ValueError:
        return jsonify({"error": "Format tanggal salah"}), 400

    d0 = parse_date(date_from)
    d1 = parse_date(date_to)
    if d0 > d1: d0, d1 = d1, d0
    dates = []
    cur = d0
    while cur <= d1:
        dates.append(cur.strftime("%d-%m-%Y"))
        cur += timedelta(days=1)

    placeholders = ",".join("?" for _ in dates)
    params = [ticker] + dates

    try:
        conn = get_db()
        rows = conn.execute(f"""
            SELECT channel, date, time, price, gain_pct,
                   mf_delta_raw, mf_delta_numeric, vol_x, signal
            FROM raw_messages
            WHERE ticker = ? AND date IN ({placeholders})
            ORDER BY
                substr(date,7,4)||substr(date,4,2)||substr(date,1,2),
                time
        """, params).fetchall()
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    sm_rows, bm_rows = [], []
    for r in rows:
        row = {
            "date":     r["date"],
            "time":     r["time"],
            "price":    int(round(r["price"])) if r["price"] else None,
            "gain_pct": r["gain_pct"],
            "mf":       r["mf_delta_raw"],
            "mf_num":   r["mf_delta_numeric"],
            "vol_x":    r["vol_x"],
            "signal":   r["signal"],
        }
        if r["channel"] == "smart":
            sm_rows.append(row)
        else:
            bm_rows.append(row)

    return jsonify({
        "ticker":  ticker,
        "sm":      sm_rows,
        "bm":      bm_rows,
        "sm_count": len(sm_rows),
        "bm_count": len(bm_rows),
    })



# ── API: overlay data (CM/SM/BM per candle bucket) ──────────────────────
@app.route("/api/overlay")
def overlay():
    ticker = request.args.get("ticker", "").upper().strip()
    tf     = request.args.get("tf", "1d")

    if not ticker:
        return jsonify({"error": "ticker required"}), 400

    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT date, time, channel, mf_delta_numeric
            FROM raw_messages
            WHERE ticker = ?
            ORDER BY
                substr(date,7,4)||substr(date,4,2)||substr(date,1,2),
                time
        """, [ticker]).fetchall()
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not rows:
        return jsonify({"ticker": ticker, "tf": tf, "points": []})

    tf_minutes = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": None}
    bucket_min = tf_minutes.get(tf)

    buckets = {}
    for r in rows:
        date_str = r["date"]       # DD-MM-YYYY
        time_str = r["time"] or "" # HH:MM or HH:MM:SS

        try:
            d = datetime.strptime(date_str, "%d-%m-%Y")
        except Exception:
            continue

        if bucket_min is None:
            # Daily: one bucket per date
            # WIB timestamp: midnight UTC of that date + 7h
            utc_ts = int(d.replace(tzinfo=timezone.utc).timestamp())
            wib_ts = utc_ts + (7 * 3600)
            key = wib_ts
        else:
            # Intraday: bucket by time interval
            # bh/bm sudah WIB, utc_ts = midnight UTC
            # OHLCV pakai: actual_utc_ts + 7h = midnight_utc + real_hour_utc + 7h
            # Agar match: midnight_utc + bh_wib*3600 + bm*60 (TANPA +7h lagi)
            parts = time_str.replace(".", ":").split(":")
            h = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else 9
            m = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
            total_min = h * 60 + m
            bstart = (total_min // bucket_min) * bucket_min
            bh = bstart // 60
            bm = bstart % 60
            utc_ts = int(d.replace(tzinfo=timezone.utc).timestamp())
            wib_ts = utc_ts + bh * 3600 + bm * 60
            key = wib_ts

        if key not in buckets:
            buckets[key] = {"time": key, "sm": 0.0, "bm": 0.0, "date": date_str}

        mf = r["mf_delta_numeric"] or 0
        if r["channel"] == "smart":
            buckets[key]["sm"] += mf
        else:
            buckets[key]["bm"] += abs(mf)

    points = []
    for k in sorted(buckets.keys()):
        v = buckets[k]
        sm = round(v["sm"], 2)
        bm = round(v["bm"], 2)
        cm = round(sm - bm, 2)
        points.append({"time": v["time"], "sm": sm, "bm": bm, "cm": cm, "_date": v["date"]})

    # Hitung cumulative untuk line series (terpisah dari per-bucket value)
    # Intraday: reset cumulative setiap hari baru
    # Daily: cumulative lintas semua hari
    cum_sm, cum_bm, cum_cm = 0.0, 0.0, 0.0
    prev_date = None
    for p in points:
        if bucket_min is not None and p.get("_date") != prev_date:
            # Intraday: reset di hari baru
            cum_sm, cum_bm, cum_cm = 0.0, 0.0, 0.0
            prev_date = p.get("_date")
        cum_sm = round(cum_sm + p["sm"], 2)
        cum_bm = round(cum_bm + p["bm"], 2)
        cum_cm = round(cum_cm + p["cm"], 2)
        p["cum_sm"] = cum_sm
        p["cum_bm"] = cum_bm
        p["cum_cm"] = cum_cm
        # Hapus internal field sebelum return
        p.pop("_date", None)

    return jsonify({"ticker": ticker, "tf": tf, "points": points})


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
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.method == "GET":
        return """
        <!DOCTYPE html><html><head>
        <style>
        body{background:#080c10;color:#c8d8e8;font-family:monospace;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
        .box{background:#0e1318;border:1px solid #1a2230;border-radius:8px;padding:32px;width:420px;}
        h3{color:#00e8a2;margin-bottom:20px;}
        input,button{width:100%;padding:10px;margin:8px 0;border-radius:5px;
        box-sizing:border-box;font-family:monospace;}
        input{background:#080c10;border:1px solid #1a2230;color:#c8d8e8;}
        button{background:#00e8a2;border:none;color:#080c10;font-weight:700;cursor:pointer;font-size:14px;}
        #status{margin-top:12px;font-size:13px;color:#aac;min-height:20px;}
        #bar{width:0%;height:6px;background:#00e8a2;border-radius:3px;transition:width 0.2s;}
        #barwrap{width:100%;background:#1a2230;border-radius:3px;margin-top:8px;display:none;}
        </style></head><body><div class="box">
        <h3>⬆ Upload zenith.db</h3>
        <input type="file" id="f" accept=".db"/>
        <input type="password" id="s" placeholder="Upload secret key"/>
        <button onclick="doUpload()">Upload</button>
        <div id="barwrap"><div id="bar"></div></div>
        <div id="status"></div>
        </div>
        <script>
        function doUpload(){
            var fileEl=document.getElementById('f');
            var s=document.getElementById('s').value.trim();
            var file=fileEl.files[0];
            if(!file){document.getElementById('status').innerText='Pilih file dulu!';return;}
            if(!s){document.getElementById('status').innerText='Isi secret key!';return;}
            var xhr=new XMLHttpRequest();
            document.getElementById('barwrap').style.display='block';
            document.getElementById('status').innerText='Uploading '+Math.round(file.size/1024/1024)+'MB...';
            xhr.upload.onprogress=function(e){
                if(e.lengthComputable){
                    var pct=Math.round(e.loaded/e.total*100);
                    document.getElementById('bar').style.width=pct+'%';
                    document.getElementById('status').innerText='Uploading... '+pct+'%';
                }
            };
            xhr.onload=function(){
                document.getElementById('status').innerText=xhr.status===200?xhr.responseText:'Error: '+xhr.responseText;
            };
            xhr.onerror=function(){document.getElementById('status').innerText='Network error!';};
            // Secret lewat query param, file lewat raw body — hindari multipart parsing
            xhr.open('POST','/admin/upload-db?secret='+encodeURIComponent(s));
            xhr.setRequestHeader('Content-Type','application/octet-stream');
            xhr.send(file);
        }
        </script>
        </body></html>
        """
    # POST — secret dari query param, body = raw bytes file
    secret = request.args.get("secret", "")
    if secret != SECRET:
        return "❌ Secret salah", 403
    os.makedirs("/data", exist_ok=True)
    tmp_path = "/data/zenith.db.tmp"
    dst_path = "/data/zenith.db"
    try:
        with open(tmp_path, "wb") as out:
            chunk_size = 1024 * 1024  # 1MB per chunk
            while True:
                chunk = request.stream.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp_path, dst_path)
        size = os.path.getsize(dst_path)
        return f"✅ Berhasil! {round(size/1024/1024,1)} MB tersimpan di /data/zenith.db"
    except Exception as e:
        return f"❌ Error: {e}", 500



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



@app.route("/admin/pull-db")
def pull_db():
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403

    DROPBOX_URL = "https://www.dropbox.com/scl/fi/62frlur8c81juwm27m4o2/zenith.db?rlkey=t5mubroonjnkqjsh8zogj9blj&dl=1"

    try:
        os.makedirs("/data", exist_ok=True)
        tmp_path = DB_PATH + ".tmp"

        r = requests.get(DROPBOX_URL, stream=True, timeout=300)
        total = 0
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)

        size = os.path.getsize(tmp_path)
        if size < 1024 * 100:
            return f"❌ File terlalu kecil ({size} bytes)", 500

        os.replace(tmp_path, DB_PATH)
        return f"✅ Done! {round(size/1024/1024, 1)} MB tersimpan di {DB_PATH}"
    except Exception as e:
        return f"❌ Error: {e}", 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
