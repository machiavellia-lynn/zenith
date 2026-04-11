"""
scraper.py — Zenith Unified Scraper
====================================
Runs alongside Flask in a background thread.

Two modes:
  1. Realtime listener — inserts data as Telegram messages arrive
  2. Daily backfill (17:00 WIB) — scans today's messages, fills any gaps

Reuses parser logic from scraper_history.py and scraper_mf_history.py.
"""

import asyncio
import re
import sqlite3
import os
import logging
import threading
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import requests

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger("zenith.scraper")
log.setLevel(logging.INFO)
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(asctime)s] SCRAPER %(levelname)s — %(message)s", "%H:%M:%S"))
    log.addHandler(h)

# ── Config ────────────────────────────────────────────────────────────────────
API_ID   = int(os.environ.get("TG_API_ID", "31708652"))
API_HASH = os.environ.get("TG_API_HASH", "052aedc345c0d8dd864febaafae8eb93")
DB_PATH  = os.environ.get("DB_PATH", "zenith.db")
WIB      = timezone(timedelta(hours=7))

# Session file location — Railway persistent volume at /data/
SESSION_PATH = os.environ.get("TG_SESSION_PATH", "/data/session_joker")

GROUP_ID       = -1002717915373
TOPIC_SMART    = 192528
TOPIC_BAD      = 219042
TOPIC_MF_PLUS  = 1025256
TOPIC_MF_MINUS = 1025260

BACKFILL_HOUR = 17   # 17:00 WIB
BACKFILL_MINUTE = 0

# ── Value parser (unified, handles +/- signs, Jt/M/T/rb units) ───────────────
def parse_value(s: str) -> float | None:
    if not s:
        return None
    s = s.strip()
    sign = 1
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("-"):
        sign = -1
        s = s[1:]
    s = s.replace(",", ".")
    try:
        su = s.upper()
        if su.endswith("T") and not su.endswith("JT"):
            return sign * float(s[:-1]) * 1_000_000   # Triliun → Juta
        elif su.endswith("M"):
            return sign * float(s[:-1]) * 1_000        # Miliar → Juta
        elif su.endswith("JT"):
            return sign * float(s[:-2])                 # Juta
        elif su.endswith("RB"):
            return sign * float(s[:-2]) / 1_000         # Ribu → Juta
        else:
            return sign * float(s)
    except ValueError:
        return None


def parse_freq(s: str) -> int | None:
    s = s.strip().lower()
    try:
        if s.endswith("rb"):
            return int(float(s[:-2]) * 1000)
        return int(s)
    except ValueError:
        return None


def parse_volx(s: str) -> float | None:
    s = s.strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  SM/BM PARSER (from scraper_history.py)
# ══════════════════════════════════════════════════════════════════════════════

TX_EMOJI = r"[💦🌟💧🔥🥵⭐]\uFE0F?"

# FORMAT A: has Freq column (Nov 2025+)
ROW_PATTERN_A = re.compile(
    r"(\d+)" + TX_EMOJI + r"\s+"
    r"([A-Z0-9]+)\s+"
    r"([\d.]+)\s*"
    r"([+-]?[\d.]+)\s+"
    r"(\d+rb|\d+)\s+"
    r"([^\s]+)\s+"
    r"([^\s]+)\s+"
    r"([+-][^\s]+)\s+"
    r"([\d,]+\.?\d*)x"
    r"([^\s]*)"
)

# FORMAT B: no Freq column
ROW_PATTERN_B = re.compile(
    r"(\d+)" + TX_EMOJI + r"\s+"
    r"([A-Z0-9]+)\s+"
    r"([\d.]+)\s*"
    r"([+-]?[\d.]+)\s+"
    r"([^\s]+)\s+"
    r"([^\s]+)\s+"
    r"([+-][^\s]+)\s+"
    r"([\d,]+\.?\d*)x"
    r"([^\s]*)"
)

# FORMAT C: oldest, uses 'x' marker instead of emoji
ROW_PATTERN_C = re.compile(
    r"(\d+)x\s+"
    r"([A-Z0-9]+)\s+"
    r"([\d.]+)\s*"
    r"([+-]?[\d.]+)\s+"
    r"([^\s]+)\s+"
    r"([^\s]+)\s+"
    r"([+-]?[^\s]+)\s+"
    r"[💣]?"
    r"([\d,]+\.?\d*)x"
    r"([^\s]*)"
)


def detect_format(lines: list[str]) -> str:
    for line in lines:
        if "Freq" in line or "freq" in line:
            return "A"
        if "Tx|Ticker" in line or "Tx|ticker" in line:
            return "C"
    return "B"


def parse_joker_message(text: str, channel: str) -> list[dict]:
    """Parse SM/BM message. Returns list of row dicts."""
    text = text.replace("`", "")
    lines = text.strip().splitlines()
    results = []

    date_str, time_str = None, None
    for line in lines:
        m = re.search(r"(\d{2}-\d{2}-\d{4}).*?(\d{2}:\d{2}:\d{2})", line)
        if m:
            date_str = m.group(1)
            time_str = m.group(2)
            break
    if not date_str:
        return []

    # Detect channel from header
    for line in lines:
        if "MF+" in line:
            channel = "smart"
            break
        elif "MF-" in line:
            channel = "bad"
            break

    fmt = detect_format(lines)

    for line in lines:
        if fmt == "A":
            m = ROW_PATTERN_A.search(line)
            if not m:
                continue
            tx_count     = int(m.group(1))
            ticker       = m.group(2)
            price        = float(m.group(3))
            gain_pct     = float(m.group(4))
            freq         = parse_freq(m.group(5))
            value_raw    = m.group(6)
            avg_mf_raw   = m.group(7)
            mf_delta_raw = m.group(8)
            vol_x        = parse_volx(m.group(9))
            signal       = m.group(10).strip().replace("`", "")
        elif fmt == "B":
            m = ROW_PATTERN_B.search(line)
            if not m:
                continue
            tx_count     = int(m.group(1))
            ticker       = m.group(2)
            price        = float(m.group(3))
            gain_pct     = float(m.group(4))
            freq         = None
            value_raw    = m.group(5)
            avg_mf_raw   = m.group(6)
            mf_delta_raw = m.group(7)
            vol_x        = parse_volx(m.group(8))
            signal       = m.group(9).strip().replace("`", "")
        else:
            m = ROW_PATTERN_C.search(line)
            if not m:
                continue
            tx_count     = int(m.group(1))
            ticker       = m.group(2)
            price        = float(m.group(3))
            gain_pct     = float(m.group(4))
            freq         = None
            value_raw    = m.group(5)
            avg_mf_raw   = m.group(6)
            mf_delta_raw = m.group(7)
            vol_x        = parse_volx(m.group(8))
            signal       = m.group(9).strip().replace("`", "")

        results.append({
            "channel":          channel,
            "date":             date_str,
            "time":             time_str,
            "tx_count":         tx_count,
            "ticker":           ticker,
            "price":            price,
            "gain_pct":         gain_pct,
            "freq":             freq,
            "value_raw":        value_raw,
            "value_numeric":    parse_value(value_raw),
            "avg_mf_raw":      avg_mf_raw,
            "avg_mf_numeric":  parse_value(avg_mf_raw),
            "mf_delta_raw":    mf_delta_raw,
            "mf_delta_numeric": parse_value(mf_delta_raw.lstrip("+")),
            "vol_x":           vol_x,
            "signal":          signal,
        })

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  MF PARSER (from scraper_mf_history.py)
# ══════════════════════════════════════════════════════════════════════════════

VAL_TOKEN = r"[\d.]+(?:[Jj][Tt]|[Rr][Bb]|[Mm]|[Tt])"
MF_TOKEN  = r"(?:[+-][\d.]+(?:[Jj][Tt]|[Rr][Bb]|[Mm]|[Tt])|0)"

ROW_PATTERN_MF = re.compile(
    r"(\d+)" + TX_EMOJI + r"\s+"
    r"([A-Z0-9]+)\s+"
    r"([\d.]+)\s*"
    r"([+-]?[\d.]+)\s+"
    r"(" + VAL_TOKEN + r")\s+"
    r"(" + MF_TOKEN  + r")\s+"
    r"(" + MF_TOKEN  + r")\s+"
    r"(" + MF_TOKEN  + r")\s*"
    r"([🟢🔴⚪️]?)",
    re.UNICODE
)


def detect_mf_channel(text: str) -> str:
    if re.search(r"\|\s*MF\+\s*\|", text):
        return "mf_plus"
    elif re.search(r"\|\s*MF-\s*\|", text):
        return "mf_minus"
    return "mf_plus"


def parse_mf_message(text: str, fallback_channel: str) -> list[dict]:
    """Parse MF+/MF- message. Returns list of row dicts."""
    text = text.replace("```", "").replace("`", "")
    lines = text.strip().splitlines()
    results = []

    date_str, time_str = None, None
    for line in lines:
        m = re.search(r"(\d{2}-\d{2}-\d{4}).*?(\d{2}:\d{2}:\d{2})", line)
        if m:
            date_str = m.group(1)
            time_str = m.group(2)
            break
    if not date_str:
        return []

    channel = detect_mf_channel(text) or fallback_channel

    for line in lines:
        m = ROW_PATTERN_MF.search(line)
        if not m:
            continue
        results.append({
            "channel":          channel,
            "date":             date_str,
            "time":             time_str,
            "tx_count":         int(m.group(1)),
            "ticker":           m.group(2),
            "price":            float(m.group(3)),
            "gain_pct":         float(m.group(4)),
            "val_raw":          m.group(5),
            "val_numeric":      parse_value(m.group(5)),
            "mf_raw":           m.group(6),
            "mf_numeric":       parse_value(m.group(6)),
            "mft_raw":          m.group(7),
            "mft_numeric":      parse_value(m.group(7)),
            "cm_delta_raw":     m.group(8),
            "cm_delta_numeric": parse_value(m.group(8)),
            "signal":           m.group(9).strip() if m.group(9) else "",
        })

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE INSERT
# ══════════════════════════════════════════════════════════════════════════════

def get_scraper_db():
    """Dedicated DB connection for scraper thread (separate from Flask)."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")  # wait up to 10s on lock
    return conn


def save_sm_bm_rows(conn, message_id: int, rows: list[dict]) -> int:
    """Insert SM/BM rows. Returns count of new rows inserted."""
    c = conn.cursor()
    saved = 0
    for row in rows:
        try:
            c.execute("""
                INSERT OR IGNORE INTO raw_messages (
                    message_id, channel, date, time,
                    tx_count, ticker, price, gain_pct, freq,
                    value_raw, value_numeric,
                    avg_mf_raw, avg_mf_numeric,
                    mf_delta_raw, mf_delta_numeric,
                    vol_x, signal
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                message_id,
                row["channel"], row["date"], row["time"],
                row["tx_count"], row["ticker"], row["price"],
                row["gain_pct"], row["freq"],
                row["value_raw"], row["value_numeric"],
                row["avg_mf_raw"], row["avg_mf_numeric"],
                row["mf_delta_raw"], row["mf_delta_numeric"],
                row["vol_x"], row["signal"],
            ))
            saved += c.rowcount
        except Exception as e:
            log.warning(f"SM/BM insert fail {row['ticker']} msg={message_id}: {e}")
    conn.commit()
    return saved


def save_mf_rows(conn, message_id: int, rows: list[dict]) -> int:
    """Insert MF+/MF- rows. Returns count of new rows inserted."""
    c = conn.cursor()
    saved = 0
    for row in rows:
        try:
            c.execute("""
                INSERT OR IGNORE INTO raw_mf_messages (
                    message_id, channel, date, time,
                    tx_count, ticker, price, gain_pct,
                    val_raw, val_numeric,
                    mf_raw, mf_numeric,
                    mft_raw, mft_numeric,
                    cm_delta_raw, cm_delta_numeric,
                    signal
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                message_id,
                row["channel"], row["date"], row["time"],
                row["tx_count"], row["ticker"], row["price"], row["gain_pct"],
                row["val_raw"], row["val_numeric"],
                row["mf_raw"], row["mf_numeric"],
                row["mft_raw"], row["mft_numeric"],
                row["cm_delta_raw"], row["cm_delta_numeric"],
                row["signal"],
            ))
            saved += c.rowcount
        except Exception as e:
            log.warning(f"MF insert fail {row['ticker']} msg={message_id}: {e}")
    conn.commit()
    return saved


# ══════════════════════════════════════════════════════════════════════════════
#  TOPIC ID HELPERS
# ══════════════════════════════════════════════════════════════════════════════

SM_BM_TOPICS = {TOPIC_SMART, TOPIC_BAD}
MF_TOPICS    = {TOPIC_MF_PLUS, TOPIC_MF_MINUS}
ALL_TOPICS   = SM_BM_TOPICS | MF_TOPICS

TOPIC_LABELS = {
    TOPIC_SMART:    "SM",
    TOPIC_BAD:      "BM",
    TOPIC_MF_PLUS:  "MF+",
    TOPIC_MF_MINUS: "MF-",
}

TOPIC_CHANNELS = {
    TOPIC_SMART:    "smart",
    TOPIC_BAD:      "bad",
    TOPIC_MF_PLUS:  "mf_plus",
    TOPIC_MF_MINUS: "mf_minus",
}


def get_message_topic_id(message) -> int | None:
    """Extract topic ID from a forum message."""
    if message.reply_to:
        return getattr(message.reply_to, 'reply_to_top_id', None) or \
               getattr(message.reply_to, 'reply_to_msg_id', None)
    return None


def process_message(conn, message) -> int:
    """Parse and save a single Telegram message. Returns rows saved."""
    if not message.text:
        return 0

    topic_id = get_message_topic_id(message)
    if topic_id not in ALL_TOPICS:
        return 0

    msg_id = message.id
    channel = TOPIC_CHANNELS[topic_id]

    if topic_id in SM_BM_TOPICS:
        rows = parse_joker_message(message.text, channel)
        if rows:
            saved = save_sm_bm_rows(conn, msg_id, rows)
            if saved > 0 and rows[0].get("date"):
                try:
                    rebuild_summary_for_date(conn, rows[0]["date"])
                except Exception:
                    pass
            return saved
    else:
        rows = parse_mf_message(message.text, channel)
        if rows:
            saved = save_mf_rows(conn, msg_id, rows)
            if saved > 0 and rows[0].get("date"):
                try:
                    rebuild_summary_for_date(conn, rows[0]["date"])
                except Exception:
                    pass
            return saved

    return 0




# ══════════════════════════════════════════════════════════════════════════════
#  EOD SUMMARY — pre-aggregated data + Wyckoff analytics per ticker per date
# ══════════════════════════════════════════════════════════════════════════════

_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
_DATE_SORT = "substr(date,7,4)||substr(date,4,2)||substr(date,1,2)"


def ensure_summary_table(conn):
    """Create eod_summary v2. Drops old schema if columns don't match."""
    try:
        conn.execute("SELECT phase FROM eod_summary LIMIT 1")
    except Exception:
        conn.execute("DROP TABLE IF EXISTS eod_summary")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eod_summary (
            date             TEXT NOT NULL,
            ticker           TEXT NOT NULL,
            sm_val           REAL DEFAULT 0,
            bm_val           REAL DEFAULT 0,
            tx_count         INTEGER DEFAULT 0,
            tx_sm            INTEGER DEFAULT 0,
            tx_bm            INTEGER DEFAULT 0,
            mf_plus          REAL,
            mf_minus         REAL,
            vwap_sm          REAL,
            price_close      REAL,
            price_change_pct REAL,
            sri              REAL,
            mes              REAL,
            volx_gap         REAL,
            rpr              REAL,
            phase            TEXT,
            action           TEXT,
            UNIQUE(date, ticker)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eod_date ON eod_summary(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eod_ticker ON eod_summary(ticker, date)")
    conn.commit()


def rebuild_summary_for_date(conn, date_str: str):
    """Aggregate raw data for a date into eod_summary (flow fields only)."""
    rows_sm_bm = conn.execute("""
        SELECT ticker, channel, SUM(mf_delta_numeric) AS mf, COUNT(*) AS tx
        FROM raw_messages WHERE date = ? GROUP BY ticker, channel
    """, [date_str]).fetchall()

    rows_vwap = conn.execute("""
        SELECT ticker,
               SUM(price * ABS(mf_delta_numeric)) / NULLIF(SUM(ABS(mf_delta_numeric)), 0) AS vwap
        FROM raw_messages
        WHERE date = ? AND channel = 'smart' AND price > 0 AND mf_delta_numeric IS NOT NULL
        GROUP BY ticker
    """, [date_str]).fetchall()
    vwap_map = {r["ticker"]: r["vwap"] for r in rows_vwap if r["vwap"]}

    rows_mf = conn.execute("""
        SELECT ticker, channel, SUM(mf_numeric) AS mf
        FROM raw_mf_messages WHERE date = ? GROUP BY ticker, channel
    """, [date_str]).fetchall()

    tickers = {}
    for r in rows_sm_bm:
        t = r["ticker"]
        if t not in tickers:
            tickers[t] = {"sm": 0, "bm": 0, "tx": 0, "tx_sm": 0, "tx_bm": 0, "mfp": None, "mfm": None}
        if r["channel"] == "smart":
            tickers[t]["sm"] += r["mf"] or 0
            tickers[t]["tx_sm"] += r["tx"] or 0
        else:
            tickers[t]["bm"] += abs(r["mf"] or 0)
            tickers[t]["tx_bm"] += r["tx"] or 0
        tickers[t]["tx"] += r["tx"] or 0

    for r in rows_mf:
        t = r["ticker"]
        if t not in tickers:
            tickers[t] = {"sm": 0, "bm": 0, "tx": 0, "tx_sm": 0, "tx_bm": 0, "mfp": None, "mfm": None}
        if r["channel"] == "mf_plus":
            tickers[t]["mfp"] = (tickers[t]["mfp"] or 0) + (r["mf"] or 0)
        elif r["channel"] == "mf_minus":
            tickers[t]["mfm"] = (tickers[t]["mfm"] or 0) + abs(r["mf"] or 0)

    conn.execute("DELETE FROM eod_summary WHERE date = ?", [date_str])
    for t, d in tickers.items():
        conn.execute("""
            INSERT INTO eod_summary (date,ticker,sm_val,bm_val,tx_count,tx_sm,tx_bm,mf_plus,mf_minus,vwap_sm)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (date_str, t, round(d["sm"], 2), round(d["bm"], 2), d["tx"],
              d["tx_sm"], d["tx_bm"],
              round(d["mfp"], 2) if d["mfp"] is not None else None,
              round(d["mfm"], 2) if d["mfm"] is not None else None,
              round(vwap_map.get(t, 0), 2) if vwap_map.get(t) else None))
    conn.commit()
    return len(tickers)


# ── Yahoo price enrichment (run once per day after market close) ──────────

def _fetch_close(ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.JK?range=5d&interval=1d"
        r = requests.get(url, headers=_YAHOO_HEADERS, timeout=10)
        closes = r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        for c in reversed(closes):
            if c is not None:
                return ticker, round(c, 2)
    except Exception:
        pass
    return ticker, None


def enrich_daily_prices(conn, date_str: str):
    """Fetch Yahoo close prices for tickers missing price_close on this date."""
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM eod_summary WHERE date = ? AND price_close IS NULL", [date_str]
    ).fetchall()
    tickers = [r["ticker"] for r in rows]
    if not tickers:
        return 0
    log.info(f"  💰 Fetching close prices for {len(tickers)} tickers...")
    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(_fetch_close, tickers))
    n = 0
    for tk, close in results:
        if close:
            conn.execute("UPDATE eod_summary SET price_close=? WHERE date=? AND ticker=?", [close, date_str, tk])
            n += 1
    conn.commit()
    log.info(f"  💰 Prices: {n}/{len(tickers)} enriched")
    return n


# ── Wyckoff analytics computation ────────────────────────────────────────

def _classify_phase(sri, mes, volx_gap, rpr, cm, pchg, price, low5):
    """Classify Wyckoff phase. Every ticker gets a label."""
    # ── Tier 1: Strong signals (with price data) ──
    if price and low5 and price <= low5 and cm > 0 and volx_gap < -1:
        return "SPRING"
    if sri > 1.5 and cm > 0 and pchg is not None and abs(pchg) < 1:
        return "ABSORB"
    if pchg is not None and pchg > 2 and sri > 1.5 and cm > 0:
        return "SOS"
    if pchg is not None and pchg > 2 and cm < 0 and rpr > 0.5:
        return "UPTHRUST"
    if cm < 0 and pchg is not None and pchg < -0.5 and sri > 0.8:
        return "DISTRI"
    # ── Tier 2: Clear signals (without price) ──
    if cm < 0 and sri > 1.0 and rpr > 0.5:
        return "DISTRI"
    if cm < 0 and rpr > 0.65:
        return "UPTHRUST"
    if cm > 0 and sri > 2.0:
        return "ABSORB"
    if cm < 0 and sri > 0.8:
        return "DISTRI"
    # ── Tier 3: Catch-all (every ticker gets a label) ──
    if cm > 0:
        return "ACCUM"
    if cm < 0:
        return "DISTRI"
    return "NEUTRAL"


def _get_action(phase, cm_3d):
    """Derive trading action from phase + 3-day CM trend."""
    if phase in ("SPRING", "ABSORB") and cm_3d > 0:
        return "BUY"
    if phase in ("ABSORB", "SOS"):
        return "HOLD"
    if phase == "ACCUM" and cm_3d > 0:
        return "BUY"
    if phase == "ACCUM":
        return "HOLD"
    if phase in ("UPTHRUST", "DISTRI"):
        return "SELL"
    return "HOLD"


def compute_analytics_for_date(conn, date_str: str):
    """Compute SRI/MES/VolxGap/RPR/Phase/Action for all tickers on date_str."""
    rows = conn.execute(
        "SELECT ticker,sm_val,bm_val,tx_sm,tx_bm,vwap_sm,price_close FROM eod_summary WHERE date=?",
        [date_str]
    ).fetchall()
    if not rows:
        return 0

    # Fallback: get latest price + gain from raw_messages for tickers missing price_close
    raw_prices = conn.execute("""
        SELECT ticker,
               MAX(price) AS last_price,
               AVG(gain_pct) AS avg_gain
        FROM raw_messages
        WHERE date = ? AND price > 0
        GROUP BY ticker
    """, [date_str]).fetchall()
    raw_price_map = {r["ticker"]: {"price": r["last_price"], "gain": r["avg_gain"]} for r in raw_prices}

    computed = 0
    for row in rows:
        tk = row["ticker"]
        sm = row["sm_val"] or 0
        bm = row["bm_val"] or 0
        cm = sm - bm
        tx_sm = row["tx_sm"] or 0
        tx_bm = row["tx_bm"] or 0
        pc = row["price_close"]
        vwap = row["vwap_sm"]

        # Fallback price from raw data
        rp = raw_price_map.get(tk, {})
        if not pc and rp.get("price"):
            pc = rp["price"]

        hist = conn.execute(f"""
            SELECT sm_val, bm_val, price_close FROM eod_summary
            WHERE ticker=? ORDER BY {_DATE_SORT} DESC LIMIT 10
        """, [tk]).fetchall()

        # SRI
        sm_h = [h["sm_val"] or 0 for h in hist if (h["sm_val"] or 0) > 0]
        sma10 = sum(sm_h) / len(sm_h) if sm_h else 0
        sri = round(sm / sma10, 2) if sma10 > 0 else 0

        # RPR
        ttx = tx_sm + tx_bm
        rpr = round(tx_bm / ttx, 2) if ttx > 0 else 0

        # Price change: try DB price_close history, fallback to raw gain_pct
        prices = [h["price_close"] for h in hist if h["price_close"]]
        pchg = None
        if pc and len(prices) >= 2 and prices[1] and prices[1] > 0:
            pchg = round((pc - prices[1]) / prices[1] * 100, 2)
        if pchg is None and rp.get("gain") is not None:
            pchg = round(rp["gain"], 2)

        # MES
        mes = round(abs(pchg) / sri, 2) if pchg is not None and sri > 0 else None

        # Volx Gap
        vg = round((pc - vwap) / pc * 100, 2) if pc and vwap and pc > 0 else 0

        # CM 3d + Low 5d
        cm3 = sum((h["sm_val"] or 0) - (h["bm_val"] or 0) for h in hist[:3])
        p5 = [h["price_close"] for h in hist[:5] if h["price_close"]]
        low5 = min(p5) if p5 else None

        phase = _classify_phase(sri, mes, vg, rpr, cm, pchg, pc, low5)
        action = _get_action(phase, cm3)

        conn.execute("""
            UPDATE eod_summary SET price_change_pct=?,sri=?,mes=?,volx_gap=?,rpr=?,phase=?,action=?
            WHERE date=? AND ticker=?
        """, [pchg, sri, mes, vg, rpr, phase, action, date_str, tk])
        computed += 1

    conn.commit()
    log.info(f"  📊 Analytics: {computed} tickers for {date_str}")
    return computed


def rebuild_all_summaries(conn):
    """Rebuild eod_summary for ALL dates + analytics for recent 15 days."""
    ensure_summary_table(conn)
    dates_sm = conn.execute(f"SELECT DISTINCT date FROM raw_messages ORDER BY {_DATE_SORT}").fetchall()
    dates_mf = conn.execute(f"SELECT DISTINCT date FROM raw_mf_messages ORDER BY {_DATE_SORT}").fetchall()
    all_dates = sorted(
        set(r["date"] for r in dates_sm) | set(r["date"] for r in dates_mf),
        key=lambda d: d[6:10] + d[3:5] + d[0:2]
    )
    log.info(f"📊 Rebuilding summary for {len(all_dates)} dates...")
    total = 0
    for i, d in enumerate(all_dates):
        total += rebuild_summary_for_date(conn, d)
        if (i + 1) % 50 == 0:
            log.info(f"  ... {i+1}/{len(all_dates)} dates done")
    log.info(f"✅ Summary: {len(all_dates)} dates, {total} rows")

    recent = all_dates[-15:]
    log.info(f"📈 Enriching + analytics for {len(recent)} recent dates...")
    for d in recent:
        try:
            enrich_daily_prices(conn, d)
            compute_analytics_for_date(conn, d)
        except Exception as e:
            log.warning(f"  Enrich failed {d}: {e}")
    return {"dates": len(all_dates), "ticker_rows": total}


# ══════════════════════════════════════════════════════════════════════════════
#  BACKFILL — scan all today's messages at 17:00 WIB
# ══════════════════════════════════════════════════════════════════════════════

async def run_backfill(client, conn):
    """Scan all messages from today in all 4 topics, insert missing ones."""
    today_wib = datetime.now(WIB).strftime("%d-%m-%Y")
    log.info(f"🔄 BACKFILL started for {today_wib}")

    total_scanned = 0
    total_saved = 0

    for topic_id in ALL_TOPICS:
        label = TOPIC_LABELS[topic_id]
        channel = TOPIC_CHANNELS[topic_id]
        scanned = 0
        saved = 0

        async for message in client.iter_messages(GROUP_ID, reply_to=topic_id, limit=None):
            if not message.text:
                continue

            # Check if this message is from today (parse date from message text)
            text_clean = message.text.replace("```", "").replace("`", "")
            date_match = re.search(r"(\d{2}-\d{2}-\d{4})", text_clean)
            if not date_match:
                continue

            msg_date = date_match.group(1)

            # Stop iterating if we've gone past today (messages are newest-first)
            if msg_date != today_wib:
                # Could be older — keep checking a few more in case of ordering issues
                scanned += 1
                if scanned > 50 and saved == 0:
                    break  # definitely past today
                continue

            scanned += 1
            n = process_message(conn, message)
            saved += n

        log.info(f"  {label}: scanned={scanned}, new={saved}")
        total_scanned += scanned
        total_saved += saved

    # Update summary + analytics for today
    try:
        rebuild_summary_for_date(conn, today_wib)
        enrich_daily_prices(conn, today_wib)
        compute_analytics_for_date(conn, today_wib)
    except Exception as e:
        log.warning(f"Summary/analytics update failed: {e}")
    log.info(f"✅ BACKFILL complete: scanned={total_scanned}, new_rows={total_saved}")


# ══════════════════════════════════════════════════════════════════════════════
#  BACKFILL REQUEST QUEUE (signalled from HTTP thread)
# ══════════════════════════════════════════════════════════════════════════════

_backfill_request = {"days": None, "status": "idle", "result": None}
_rebuild_request = {"status": "idle", "result": None}
_backfill_lock = threading.Lock()


def request_backfill(days: int):
    """Called from HTTP thread to request a backfill. Non-blocking."""
    with _backfill_lock:
        if _backfill_request["status"] == "running":
            return {"ok": False, "error": "Backfill already running"}
        _backfill_request["days"] = days
        _backfill_request["status"] = "pending"
        _backfill_request["result"] = None
        return {"ok": True, "message": f"Backfill {days} days queued. Check /admin/scraper-status for progress."}


def request_rebuild():
    """Called from HTTP thread to request a full summary rebuild. Non-blocking."""
    with _backfill_lock:
        if _rebuild_request["status"] == "running":
            return {"ok": False, "error": "Rebuild already running"}
        _rebuild_request["status"] = "pending"
        _rebuild_request["result"] = None
        return {"ok": True, "message": "Summary rebuild queued. Check /admin/scraper-status for progress."}


def get_backfill_status():
    """Called from HTTP thread to check backfill progress."""
    with _backfill_lock:
        return {"backfill": dict(_backfill_request), "rebuild": dict(_rebuild_request)}


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN LOOP — realtime listener + scheduled backfill
# ══════════════════════════════════════════════════════════════════════════════

async def scraper_main():
    """Main async loop: connect to Telegram, listen, and schedule backfill."""
    try:
        from telethon import TelegramClient, events
    except ImportError:
        log.error("❌ telethon not installed. Scraper disabled.")
        return

    # Check session file exists
    session_file = SESSION_PATH
    if not os.path.exists(session_file + ".session") and not os.path.exists(session_file):
        log.error(f"❌ Session file not found at {session_file}. Scraper disabled.")
        log.error("  Upload session_joker.session to /data/ on Railway.")
        return

    conn = get_scraper_db()
    ensure_summary_table(conn)
    log.info(f"📦 DB: {DB_PATH}")

    client = TelegramClient(session_file, API_ID, API_HASH)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            log.error("❌ Session not authorized. Re-create session_joker.session locally.")
            return

        log.info("🔗 Connected to Telegram")
        await client.get_dialogs()
        log.info("✅ Dialog cache loaded")

        # ── Realtime listener ─────────────────────────────────────────────
        @client.on(events.NewMessage(chats=GROUP_ID))
        async def on_new_message(event):
            try:
                n = process_message(conn, event.message)
                if n > 0:
                    topic_id = get_message_topic_id(event.message)
                    label = TOPIC_LABELS.get(topic_id, "?")
                    log.info(f"📩 {label} msg={event.message.id} → {n} row(s) saved")
            except Exception as e:
                log.error(f"❌ Listener error: {e}")

        log.info("👂 Realtime listener active on 4 topics")
        log.info(f"⏰ Daily backfill scheduled at {BACKFILL_HOUR:02d}:{BACKFILL_MINUTE:02d} WIB")

        # ── Scheduled backfill loop ───────────────────────────────────────
        backfill_done_today = False
        last_check_date = None

        while True:
            now_wib = datetime.now(WIB)
            today_str = now_wib.strftime("%Y-%m-%d")

            # Reset flag at midnight
            if today_str != last_check_date:
                backfill_done_today = False
                last_check_date = today_str

            # Run backfill at scheduled time
            if (not backfill_done_today
                    and now_wib.hour >= BACKFILL_HOUR
                    and now_wib.minute >= BACKFILL_MINUTE):
                try:
                    await run_backfill(client, conn)
                    backfill_done_today = True
                except Exception as e:
                    log.error(f"❌ Backfill error: {e}")
                    backfill_done_today = True  # don't retry endlessly

            # Check for manual backfill request (from HTTP endpoint)
            with _backfill_lock:
                pending_days = None
                if _backfill_request["status"] == "pending":
                    pending_days = _backfill_request["days"]
                    _backfill_request["status"] = "running"

            if pending_days:
                try:
                    log.info(f"📋 Manual backfill requested: {pending_days} days")
                    from scraper_weekly import run_weekly_backfill
                    result = await run_weekly_backfill(client, conn, days=pending_days)
                    with _backfill_lock:
                        _backfill_request["status"] = "done"
                        _backfill_request["result"] = result
                except Exception as e:
                    log.error(f"❌ Manual backfill error: {e}")
                    with _backfill_lock:
                        _backfill_request["status"] = "error"
                        _backfill_request["result"] = str(e)

            # Check for summary rebuild request (from HTTP endpoint)
            with _backfill_lock:
                do_rebuild = _rebuild_request["status"] == "pending"
                if do_rebuild:
                    _rebuild_request["status"] = "running"

            if do_rebuild:
                try:
                    log.info("📋 Summary rebuild requested")
                    ensure_summary_table(conn)
                    result = rebuild_all_summaries(conn)
                    with _backfill_lock:
                        _rebuild_request["status"] = "done"
                        _rebuild_request["result"] = result
                except Exception as e:
                    log.error(f"❌ Rebuild error: {e}")
                    with _backfill_lock:
                        _rebuild_request["status"] = "error"
                        _rebuild_request["result"] = str(e)

            await asyncio.sleep(5)  # check every 5 seconds

    except Exception as e:
        log.error(f"❌ Scraper fatal error: {e}")
    finally:
        try:
            await client.disconnect()
        except:
            pass
        try:
            conn.close()
        except:
            pass
        log.info("🔌 Scraper disconnected")


# ══════════════════════════════════════════════════════════════════════════════
#  THREAD ENTRY POINT (called from app.py)
# ══════════════════════════════════════════════════════════════════════════════

def start_scraper_thread():
    """Start scraper in a daemon thread with its own asyncio event loop."""

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(scraper_main())
        except Exception as e:
            log.error(f"❌ Scraper thread crashed: {e}")
        finally:
            loop.close()

    t = threading.Thread(target=_run, name="zenith-scraper", daemon=True)
    t.start()
    log.info("🚀 Scraper thread started")
    return t
