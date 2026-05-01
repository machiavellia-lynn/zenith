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
import time
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

BACKFILL_HOUR = 15   # 15:30 WIB first pass
BACKFILL_MINUTE = 30
RECOMPUTE_HOUR = 16  # 16:30 WIB second pass (new data after 15:30)
RECOMPUTE_MINUTE = 30

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
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")  # wait up to 30s on lock
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


# ── Analytics recompute throttle (realtime listener only) ────────────────────
# Prevents compute_analytics_for_date from running on EVERY incoming message.
# Recomputes at most once every 60 seconds per date.
_analytics_throttle: dict = {}          # date_str → last_run epoch
_analytics_throttle_lock = threading.Lock()
ANALYTICS_THROTTLE_SECS = 60


def _should_recompute_analytics(date_str: str) -> bool:
    """Return True if analytics for date_str should be recomputed now."""
    now = time.time()
    with _analytics_throttle_lock:
        last = _analytics_throttle.get(date_str, 0)
        if now - last > ANALYTICS_THROTTLE_SECS:
            _analytics_throttle[date_str] = now
            return True
    return False


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
                    if _should_recompute_analytics(rows[0]["date"]):
                        compute_analytics_for_date(conn, rows[0]["date"])
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
                    if _should_recompute_analytics(rows[0]["date"]):
                        compute_analytics_for_date(conn, rows[0]["date"])
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
    """Create eod_summary v4. Drops and recreates if base schema missing,
    otherwise adds new columns via ALTER TABLE (safe for existing data)."""
    # Check base schema exists (vwap_bm was added in v3)
    try:
        conn.execute("SELECT vwap_bm FROM eod_summary LIMIT 1")
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
            vwap_bm          REAL,
            price_close      REAL,
            price_change_pct REAL,
            sri              REAL,
            mes              REAL,
            volx_gap         REAL,
            rpr              REAL,
            atr_pct          REAL,
            phase            TEXT,
            action           TEXT,
            sm_sma10         REAL,
            bm_sma10         REAL,
            watch            TEXT,
            UNIQUE(date, ticker)
        )
    """)

    # Safely add v4 columns if upgrading from older schema
    for col, typedef in [
        ("sm_sma10", "REAL"),
        ("bm_sma10", "REAL"),
        ("watch",    "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE eod_summary ADD COLUMN {col} {typedef}")
        except Exception:
            pass  # column already exists

    conn.execute("CREATE INDEX IF NOT EXISTS idx_eod_date ON eod_summary(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eod_ticker ON eod_summary(ticker, date)")
    conn.commit()
    ensure_trade_journal_table(conn)


def rebuild_summary_for_date(conn, date_str: str, full_reset: bool = False):
    """Aggregate raw data for a date into eod_summary (flow fields only).

    full_reset=False (default): upsert — only overwrites flow columns,
        preserves analytics (price_close, sri, phase, action, etc.).
        Used by the realtime listener so analytics aren't wiped on every message.

    full_reset=True: DELETE first, then INSERT fresh rows.
        Used by rebuild_all_summaries (admin full rebuild).
    """
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
    vwap_sm_map = {r["ticker"]: r["vwap"] for r in rows_vwap if r["vwap"]}

    rows_vwap_bm = conn.execute("""
        SELECT ticker,
               SUM(price * ABS(mf_delta_numeric)) / NULLIF(SUM(ABS(mf_delta_numeric)), 0) AS vwap
        FROM raw_messages
        WHERE date = ? AND channel = 'bad' AND price > 0 AND mf_delta_numeric IS NOT NULL
        GROUP BY ticker
    """, [date_str]).fetchall()
    vwap_bm_map = {r["ticker"]: r["vwap"] for r in rows_vwap_bm if r["vwap"]}

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

    if full_reset:
        conn.execute("DELETE FROM eod_summary WHERE date = ?", [date_str])
        for t, d in tickers.items():
            conn.execute("""
                INSERT INTO eod_summary (date,ticker,sm_val,bm_val,tx_count,tx_sm,tx_bm,mf_plus,mf_minus,vwap_sm,vwap_bm)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (date_str, t, round(d["sm"], 2), round(d["bm"], 2), d["tx"],
                  d["tx_sm"], d["tx_bm"],
                  round(d["mfp"], 2) if d["mfp"] is not None else None,
                  round(d["mfm"], 2) if d["mfm"] is not None else None,
                  round(vwap_sm_map.get(t, 0), 2) if vwap_sm_map.get(t) else None,
                  round(vwap_bm_map.get(t, 0), 2) if vwap_bm_map.get(t) else None))
    else:
        # Upsert: update only flow columns, leave analytics columns (price_close,
        # price_change_pct, sri, mes, volx_gap, rpr, atr_pct, phase, action) intact.
        for t, d in tickers.items():
            conn.execute("""
                INSERT INTO eod_summary (date,ticker,sm_val,bm_val,tx_count,tx_sm,tx_bm,mf_plus,mf_minus,vwap_sm,vwap_bm)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(date, ticker) DO UPDATE SET
                    sm_val   = excluded.sm_val,
                    bm_val   = excluded.bm_val,
                    tx_count = excluded.tx_count,
                    tx_sm    = excluded.tx_sm,
                    tx_bm    = excluded.tx_bm,
                    mf_plus  = excluded.mf_plus,
                    mf_minus = excluded.mf_minus,
                    vwap_sm  = excluded.vwap_sm,
                    vwap_bm  = excluded.vwap_bm
            """, (date_str, t, round(d["sm"], 2), round(d["bm"], 2), d["tx"],
                  d["tx_sm"], d["tx_bm"],
                  round(d["mfp"], 2) if d["mfp"] is not None else None,
                  round(d["mfm"], 2) if d["mfm"] is not None else None,
                  round(vwap_sm_map.get(t, 0), 2) if vwap_sm_map.get(t) else None,
                  round(vwap_bm_map.get(t, 0), 2) if vwap_bm_map.get(t) else None))
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
    """Fetch Yahoo close prices for all tickers on this date (always refreshes)."""
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM eod_summary WHERE date = ?", [date_str]
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


def _fetch_close_history(ticker, days=45):
    """Fetch daily close prices for last N calendar days. Returns {DD-MM-YYYY: close}."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.JK?range={days}d&interval=1d"
        r = requests.get(url, headers=_YAHOO_HEADERS, timeout=15)
        data = r.json()["chart"]["result"][0]
        timestamps = data.get("timestamp", [])
        closes = data["indicators"]["quote"][0]["close"]
        result = {}
        for ts, c in zip(timestamps, closes):
            if c is not None:
                d = datetime.fromtimestamp(ts, tz=WIB).strftime("%d-%m-%Y")
                result[d] = round(c, 2)
        return ticker, result
    except Exception:
        return ticker, {}


def backfill_prices(conn, days=30):
    """Bulk-fetch Yahoo close prices for last N days. One request per ticker."""
    log.info(f"💰 PRICE BACKFILL: fetching {days} days of close prices...")

    # Get all tickers that have data in recent N dates
    all_dates = conn.execute(f"""
        SELECT DISTINCT date FROM eod_summary ORDER BY {_DATE_SORT} DESC LIMIT ?
    """, [days]).fetchall()
    recent_dates = set(r["date"] for r in all_dates)

    if not recent_dates:
        log.info("  No dates to backfill")
        return 0

    tickers = conn.execute("""
        SELECT DISTINCT ticker FROM eod_summary
        WHERE date IN ({})
    """.format(",".join("?" for _ in recent_dates)), list(recent_dates)).fetchall()
    ticker_list = [r["ticker"] for r in tickers]
    log.info(f"  Tickers: {len(ticker_list)}, Dates: {len(recent_dates)}")

    # Fetch in parallel — 1 request per ticker covers all dates
    cal_days = int(days * 1.6) + 10
    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(lambda t: _fetch_close_history(t, cal_days), ticker_list))

    # Bulk update
    updated = 0
    for tk, prices in results:
        for date_str, close in prices.items():
            if date_str in recent_dates and close:
                conn.execute(
                    "UPDATE eod_summary SET price_close=? WHERE date=? AND ticker=?",
                    [close, date_str, tk]
                )
                updated += 1
    conn.commit()
    log.info(f"✅ PRICE BACKFILL: {updated} cells updated for {len(ticker_list)} tickers")
    return updated


def fetch_all_gains_to_db(conn_ignored, date_str: str, delay_ms: int = 333):
    """Fetch gain% + price dari Yahoo untuk semua ticker di date_str.
    Simpan ke eod_summary.price_change_pct dan price_close.
    delay_ms = jeda antar request (333ms ≈ 180 req/jam, aman dari rate limit).

    PENTING: Selalu buka connection SENDIRI agar tidak lock scraper thread.
    """
    import time as _time
    import sqlite3 as _sqlite3

    DB_PATH = os.environ.get("DB_PATH", "/data/zenith.db")

    def _open_conn():
        c = _sqlite3.connect(DB_PATH, timeout=60, check_same_thread=False)
        c.row_factory = _sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    # Read tickers — quick read, release immediately
    _c = _open_conn()
    tickers = _c.execute(
        "SELECT DISTINCT ticker FROM eod_summary WHERE date = ?", [date_str]
    ).fetchall()
    tickers = [r["ticker"] for r in tickers]
    _c.close()

    if not tickers:
        log.info(f"[fetch-gains] Tidak ada ticker untuk {date_str}")
        return {"success": 0, "failed": 0, "total": 0}

    log.info(f"[fetch-gains] {len(tickers)} ticker untuk {date_str}, delay={delay_ms}ms")

    success = 0
    failed  = 0

    from app import fetch_gain_range

    for i, tk in enumerate(tickers):
        try:
            gain, price = fetch_gain_range(tk, date_str, date_str)

            if gain is not None or price is not None:
                # Open fresh connection per write — commit immediately, release lock
                _wc = _open_conn()
                _wc.execute("""
                    UPDATE eod_summary
                    SET price_change_pct = COALESCE(?, price_change_pct),
                        price_close      = COALESCE(?, price_close)
                    WHERE date = ? AND ticker = ?
                """, [gain, price, date_str, tk])
                _wc.commit()
                _wc.close()
                success += 1
            else:
                failed += 1

        except Exception as e:
            log.warning(f"[fetch-gains] {tk}: {e}")
            failed += 1

        if i < len(tickers) - 1:
            _time.sleep(delay_ms / 1000.0)

    log.info(f"[fetch-gains] ✅ {date_str}: {success} ok, {failed} failed")
    return {"success": success, "failed": failed, "total": len(tickers)}


# ── Trade Journal ─────────────────────────────────────────────────────────

def ensure_trade_journal_table(conn):
    """Create trade_journal table — live position tracker."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT NOT NULL,
            entry_phase  TEXT,
            entry_date   TEXT NOT NULL,
            buy_price    REAL NOT NULL,
            status       TEXT NOT NULL DEFAULT 'open',
            exit_date    TEXT,
            sell_price   REAL,
            gain_pct     REAL,
            hold_days    INTEGER,
            exit_reason  TEXT,
            created_at   TEXT,
            updated_at   TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_journal_ticker_status ON trade_journal(ticker, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_journal_entry_date ON trade_journal(entry_date)"
    )
    conn.commit()


def open_position(conn, ticker: str, entry_phase: str, entry_date: str, buy_price: float):
    """Insert new open position ke trade_journal."""
    now = datetime.now(WIB).isoformat()
    conn.execute("""
        INSERT INTO trade_journal
            (ticker, entry_phase, entry_date, buy_price, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'open', ?, ?)
    """, [ticker, entry_phase, entry_date, buy_price, now, now])
    conn.commit()


def close_position(conn, ticker: str, exit_date: str, sell_price: float, exit_reason: str):
    """Tutup SEMUA open position untuk ticker ini."""
    open_rows = conn.execute("""
        SELECT id, buy_price, entry_date FROM trade_journal
        WHERE ticker = ? AND status = 'open'
    """, [ticker]).fetchall()

    if not open_rows:
        return 0

    now = datetime.now(WIB).isoformat()
    closed = 0
    for row in open_rows:
        gain_pct = round((sell_price - row["buy_price"]) / row["buy_price"] * 100, 2)
        try:
            d_entry   = datetime.strptime(row["entry_date"], "%d-%m-%Y")
            d_exit    = datetime.strptime(exit_date, "%d-%m-%Y")
            hold_days = (d_exit - d_entry).days
        except Exception:
            hold_days = None

        conn.execute("""
            UPDATE trade_journal
            SET status     = 'closed',
                exit_date  = ?,
                sell_price = ?,
                gain_pct   = ?,
                hold_days  = ?,
                exit_reason= ?,
                updated_at = ?
            WHERE id = ?
        """, [exit_date, sell_price, gain_pct, hold_days, exit_reason, now, row["id"]])
        closed += 1

    conn.commit()
    return closed


def check_stop_loss(conn, date_str: str, threshold_pct: float = -10.0):
    """Cek semua open position — close jika loss >= threshold vs harga close hari ini."""
    open_rows = conn.execute("""
        SELECT id, ticker, buy_price FROM trade_journal WHERE status = 'open'
    """).fetchall()

    if not open_rows:
        return 0

    closed = 0
    for row in open_rows:
        price_row = conn.execute("""
            SELECT price_close FROM eod_summary
            WHERE ticker = ? AND date = ? AND price_close IS NOT NULL
        """, [row["ticker"], date_str]).fetchone()

        if not price_row or not price_row["price_close"]:
            continue

        current_price = price_row["price_close"]
        loss_pct = (current_price - row["buy_price"]) / row["buy_price"] * 100

        if loss_pct <= threshold_pct:
            close_position(conn, row["ticker"], date_str, current_price, "Stop Loss (-10%)")
            closed += 1

    return closed

# Import centralised logic — single source of truth
from logic import classify_zenith_v3_1, get_action, get_watch_flag


def compute_analytics_for_date(conn, date_str: str):
    """Compute SRI/MES/VolxGap/RPR/Phase/Action/Watch for all tickers on date_str."""
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

    # Dry spell cutoff: ~20 trading days = 28 calendar days
    cutoff_date = (datetime.now(WIB) - timedelta(days=28)).strftime("%d-%m-%Y")

    computed = 0
    for row in rows:
        tk    = row["ticker"]
        sm    = row["sm_val"] or 0
        bm    = row["bm_val"] or 0
        tx_sm = row["tx_sm"] or 0
        tx_bm = row["tx_bm"] or 0
        pc    = row["price_close"]
        vwap  = row["vwap_sm"]

        # Fallback price from raw data
        rp = raw_price_map.get(tk, {})
        if not pc and rp.get("price"):
            pc = rp["price"]

        # History query with dry-spell cutoff (~20 trading days)
        hist = conn.execute(f"""
            SELECT sm_val, bm_val, price_close FROM eod_summary
            WHERE ticker = ?
              AND {_DATE_SORT} >= substr(?,7,4)||substr(?,4,2)||substr(?,1,2)
            ORDER BY {_DATE_SORT} DESC LIMIT 14
        """, [tk, cutoff_date, cutoff_date, cutoff_date]).fetchall()

        # ── SM_SMA10: Trimmed Mean (drop highest outlier) ──
        sm_h = [h["sm_val"] or 0 for h in hist if (h["sm_val"] or 0) > 0]
        if len(sm_h) >= 3:
            trimmed = sorted(sm_h[:10])[:-1]  # drop 1 highest
        else:
            trimmed = sm_h[:10]
        sm_sma10 = round(sum(trimmed) / len(trimmed), 2) if trimmed else 0
        sri = round(sm / sm_sma10, 2) if sm_sma10 > 0 else 0

        # ── BM_SMA10: Simple Mean ──
        bm_h = [h["bm_val"] or 0 for h in hist[:10]]
        bm_sma10 = round(sum(bm_h) / len(bm_h), 2) if bm_h else 0

        # ── RPR ──
        ttx = tx_sm + tx_bm
        rpr = round(tx_bm / ttx, 2) if ttx > 0 else 0

        # ── Price change % ──
        prices = [h["price_close"] for h in hist if h["price_close"]]
        pchg = None
        if pc and len(prices) >= 2 and prices[1] and prices[1] > 0:
            pchg = round((pc - prices[1]) / prices[1] * 100, 2)
        if pchg is None and rp.get("gain") is not None:
            pchg = round(rp["gain"], 2)

        # ── ATR% ──
        atr_pct = None
        if len(prices) >= 3:
            daily_changes = [
                abs((prices[j] - prices[j+1]) / prices[j+1] * 100)
                for j in range(len(prices) - 1)
                if prices[j] and prices[j+1] and prices[j+1] > 0
            ]
            if daily_changes:
                atr_pct = round(sum(daily_changes) / len(daily_changes), 2)

        # ── MES ──
        mes = round(abs(pchg) / sri, 2) if pchg is not None and sri > 0 else None

        # ── Volx Gap ──
        vg = round((pc - vwap) / pc * 100, 2) if pc and vwap and pc > 0 else 0

        # ── RSM ──
        total_val = sm + bm
        rsm_val = round(sm / total_val * 100, 1) if total_val > 0 else 50

        # ── Phase / Action / Watch ──
        phase  = classify_zenith_v3_1(sri, rsm_val, rpr, pchg, bm, bm_sma10, atr_pct)
        watch  = get_watch_flag(phase, pchg, atr_pct)
        action = get_action(phase, pchg, atr_pct, bm_val=bm, bm_sma10=bm_sma10, watch_flag=watch)

        conn.execute("""
            UPDATE eod_summary
            SET price_change_pct=?, sri=?, mes=?, volx_gap=?, rpr=?,
                atr_pct=?, sm_sma10=?, bm_sma10=?, phase=?, action=?,
                watch=?
            WHERE date=? AND ticker=?
        """, [pchg, sri, mes, vg, rpr,
              atr_pct, sm_sma10, bm_sma10, phase, action,
              watch,
              date_str, tk])

        # ── Auto-populate trade_journal ──
        if action == "BUY" and pc:
            open_position(conn, tk, phase, date_str, pc)
        elif action == "SELL":
            if pc:
                close_position(conn, tk, date_str, pc, "SELL Signal")

        computed += 1

    # Check stop loss untuk semua open positions hari ini
    sl_hits = check_stop_loss(conn, date_str)
    if sl_hits:
        log.info(f"  🛑 Stop loss triggered: {sl_hits} positions closed ({date_str})")

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
        total += rebuild_summary_for_date(conn, d, full_reset=True)
        if (i + 1) % 50 == 0:
            log.info(f"  ... {i+1}/{len(all_dates)} dates done")
    log.info(f"✅ Summary: {len(all_dates)} dates, {total} rows")

    recent = all_dates[-15:]
    log.info(f"📈 Enriching analytics for {len(recent)} recent dates...")
    for d in recent:
        try:
            compute_analytics_for_date(conn, d)
        except Exception as e:
            log.warning(f"  Analytics failed {d}: {e}")

    # Bulk price backfill for last 30 days (1 Yahoo request per ticker)
    try:
        backfill_prices(conn, days=30)
    except Exception as e:
        log.warning(f"  Price backfill failed: {e}")

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
_backtest_request = {"days": None, "status": "idle", "result": None}
_backfill_lock = threading.Lock()
BACKTEST_HOUR = 18  # 18:00 WIB


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
    """Called from HTTP thread to check backfill/rebuild/backtest progress."""
    with _backfill_lock:
        return {
            "backfill": dict(_backfill_request),
            "rebuild": dict(_rebuild_request),
            "backtest": dict(_backtest_request),
        }


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
        log.info(f"⏰ Daily: first pass {BACKFILL_HOUR:02d}:{BACKFILL_MINUTE:02d}, recompute {RECOMPUTE_HOUR:02d}:{RECOMPUTE_MINUTE:02d} WIB")

        # ── Scheduled backfill loop ───────────────────────────────────────
        first_pass_done = False
        second_pass_done = False
        backtest_done_today = False
        last_check_date = None

        while True:
            now_wib = datetime.now(WIB)
            today_str = now_wib.strftime("%Y-%m-%d")

            # Reset flags at midnight
            if today_str != last_check_date:
                first_pass_done = False
                second_pass_done = False
                backtest_done_today = False
                last_check_date = today_str

            # First pass at 15:30 — early signal
            if (not first_pass_done
                    and now_wib.hour >= BACKFILL_HOUR
                    and now_wib.minute >= BACKFILL_MINUTE):
                try:
                    log.info("🔔 FIRST PASS (15:30) — generating early signals...")
                    await run_backfill(client, conn)
                    first_pass_done = True
                except Exception as e:
                    log.error(f"❌ First pass error: {e}")
                    first_pass_done = True

            # Second pass at 16:30 — recompute with new data
            if (not second_pass_done
                    and first_pass_done
                    and now_wib.hour >= RECOMPUTE_HOUR
                    and now_wib.minute >= RECOMPUTE_MINUTE):
                try:
                    log.info("🔄 SECOND PASS (16:30) — recomputing with updated data...")
                    await run_backfill(client, conn)
                    second_pass_done = True
                except Exception as e:
                    log.error(f"❌ Second pass error: {e}")
                    second_pass_done = True

            # Run backtest after second pass — fixed start date for track record
            if (not backtest_done_today
                    and second_pass_done):
                try:
                    today_wib_str = datetime.now(WIB).strftime("%d-%m-%Y")
                    run_backtest(conn, days=0, date_from="29-09-2025", date_to=today_wib_str)
                    backtest_done_today = True
                except Exception as e:
                    log.error(f"❌ Nightly backtest error: {e}")
                    backtest_done_today = True

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

            # Check for manual backtest request
            with _backfill_lock:
                bt_days = None
                if _backtest_request["status"] == "pending":
                    bt_days = _backtest_request["days"]
                    _backtest_request["status"] = "running"
                    log.info(f"📋 Backtest request picked up: {bt_days} days")

            if bt_days:
                try:
                    result = run_backtest(conn, days=bt_days)
                    with _backfill_lock:
                        _backtest_request["status"] = "done"
                        _backtest_request["result"] = {"ok": True, "total_trades": result.get("total_trades", 0)}
                except Exception as e:
                    log.error(f"❌ Backtest error: {e}")
                    with _backfill_lock:
                        _backtest_request["status"] = "error"
                        _backtest_request["result"] = str(e)

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


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════════════════

import json

def request_backtest(days: int):
    with _backfill_lock:
        if _backtest_request["status"] == "running":
            return {"ok": False, "error": "Backtest already running"}
        _backtest_request["days"] = days
        _backtest_request["status"] = "pending"
        _backtest_request["result"] = None
        return {"ok": True, "message": f"Backtest {days} days queued."}


def get_backtest_result(conn, days=None):
    """Read latest cached backtest result from DB."""
    try:
        if days is not None:
            row = conn.execute(
                "SELECT results FROM backtest_cache WHERE days=? ORDER BY computed_at DESC LIMIT 1", [days]
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT results FROM backtest_cache ORDER BY computed_at DESC LIMIT 1"
            ).fetchone()
        if row:
            return json.loads(row["results"])
    except Exception:
        pass
    return None


def _fetch_price_history(ticker, days=90):
    """Fetch daily OHLCV from Yahoo for a ticker. Returns {date: {o,h,l,c}}."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.JK?range={days}d&interval=1d"
        r = requests.get(url, headers=_YAHOO_HEADERS, timeout=15)
        data = r.json()["chart"]["result"][0]
        timestamps = data.get("timestamp", [])
        q = data["indicators"]["quote"][0]
        opens = q.get("open", [])
        highs = q.get("high", [])
        lows = q.get("low", [])
        closes = q.get("close", [])
        prices = {}
        for i, ts in enumerate(timestamps):
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            l = lows[i] if i < len(lows) else None
            c = closes[i] if i < len(closes) else None
            if c is not None:
                d = datetime.fromtimestamp(ts, tz=WIB).strftime("%d-%m-%Y")
                prices[d] = {
                    "o": round(o, 2) if o else c,
                    "h": round(h, 2) if h else c,
                    "l": round(l, 2) if l else c,
                    "c": round(c, 2),
                }
        return ticker, prices
    except Exception:
        return ticker, {}


def _compute_phase_action(sm, bm, sri, gain, tx_sm, tx_bm, bm_sma10=0, atr_pct=None):
    """Compute phase+action for backtest engine. Uses centralised logic.py."""
    total_val = sm + bm
    rsm = (sm / total_val * 100) if total_val > 0 else 50
    ttx = tx_sm + tx_bm
    rpr = tx_bm / ttx if ttx > 0 else 0.5
    phase  = classify_zenith_v3_1(sri, rsm, rpr, gain, bm, bm_sma10, atr_pct)
    watch  = get_watch_flag(phase, gain, atr_pct)
    action = get_action(phase, gain, atr_pct, bm_val=bm, bm_sma10=bm_sma10, watch_flag=watch)
    return phase, action


def run_backtest(conn, days=30, date_from=None, date_to=None):
    """Pair-based backtest: BUY signal opens position, SELL signal closes it.
    Entry = OPEN D+1 after BUY. Exit = OPEN D+1 after SELL or close price if SL -10%.
    Profit = (exit - entry) / entry × 100."""
    log.info(f"🧪 BACKTEST (pair-based) started: {days} days")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            computed_at TEXT NOT NULL,
            days INTEGER NOT NULL,
            results TEXT NOT NULL
        )
    """)
    conn.commit()

    # 1. Get all dates chronologically
    all_dates = conn.execute(f"""
        SELECT DISTINCT date FROM eod_summary ORDER BY {_DATE_SORT}
    """).fetchall()
    all_dates = [r["date"] for r in all_dates]

    if len(all_dates) < 3:
        return {"error": "Not enough data", "total_trades": 0}

    # Use date_from/date_to range if provided, else last N dates
    if date_from and date_to:
        df_sk = date_from[6:10] + date_from[3:5] + date_from[0:2]
        dt_sk = date_to[6:10]   + date_to[3:5]   + date_to[0:2]
        use_dates = [d for d in all_dates if df_sk <= d[6:10]+d[3:5]+d[0:2] <= dt_sk]
    else:
        use_dates = all_dates[-days:] if len(all_dates) > days else all_dates
    date_idx = {d: i for i, d in enumerate(all_dates)}

    log.info(f"  Dates: {len(use_dates)} ({use_dates[0]} → {use_dates[-1]})")

    # 2. Get all tickers in range
    ph = ",".join("?" for _ in use_dates)
    ticker_rows = conn.execute(f"""
        SELECT DISTINCT ticker FROM eod_summary WHERE date IN ({ph})
    """, use_dates).fetchall()
    ticker_list = [r["ticker"] for r in ticker_rows]
    log.info(f"  Tickers: {len(ticker_list)}")

    # 3. Fetch Yahoo OHLCV — calculate exact range from our data dates
    earliest = use_dates[0]  # DD-MM-YYYY
    d_earliest = datetime.strptime(earliest, "%d-%m-%Y")
    d_today = datetime.now()  # naive, matches strptime
    calendar_span = min((d_today - d_earliest).days + 10, 730)  # +10 buffer, max 2yr
    log.info(f"  Fetching OHLCV for {len(ticker_list)} tickers (range={calendar_span}d)...")
    price_map = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(lambda t: _fetch_price_history(t, calendar_span), ticker_list))
    for tk, prices in results:
        if prices:
            price_map[tk] = prices
    log.info(f"  OHLCV fetched for {len(price_map)} tickers")

    # 4. Preload ALL flow data for signal dates
    #    SRI/ATR must be computed on-the-fly: DB columns are only populated for
    #    recent dates (~15 days). Older dates have sri=NULL → all BUY phases fail.
    log.info("  Preloading flow data for on-the-fly SRI/ATR computation...")
    ph = ",".join("?" for _ in use_dates)
    all_flow_rows = conn.execute(f"""
        SELECT date, ticker, sm_val, bm_val, tx_sm, tx_bm
        FROM eod_summary WHERE date IN ({ph})
    """, use_dates).fetchall()

    # Build per-ticker chronological history for SRI window
    # {ticker: [{"date": .., "sm": .., "bm": .., "tx_sm": .., "tx_bm": ..}, ...]}
    ticker_flow_hist = {}
    for r in all_flow_rows:
        tk = r["ticker"]
        if tk not in ticker_flow_hist:
            ticker_flow_hist[tk] = []
        ticker_flow_hist[tk].append({
            "date":  r["date"],
            "sk":    r["date"][6:10] + r["date"][3:5] + r["date"][0:2],  # sort key
            "sm":    r["sm_val"] or 0,
            "bm":    r["bm_val"] or 0,
            "tx_sm": r["tx_sm"] or 0,
            "tx_bm": r["tx_bm"] or 0,
        })
    for tk in ticker_flow_hist:
        ticker_flow_hist[tk].sort(key=lambda x: x["sk"])

    # Build signal timeline per ticker
    log.info("  Building signal timeline...")
    signal_timeline = {}  # ticker → list of (date_idx, date, phase, action)

    for date_str in use_dates:
        d_idx = date_idx.get(date_str)
        if d_idx is None:
            continue
        cur_sk = date_str[6:10] + date_str[3:5] + date_str[0:2]

        # Get tickers active on this date
        date_tickers = {r["ticker"]: r for r in all_flow_rows if r["date"] == date_str}

        for tk, row in date_tickers.items():
            sm    = row["sm_val"] or 0
            bm    = row["bm_val"] or 0
            tx_sm = row["tx_sm"] or 0
            tx_bm = row["tx_bm"] or 0

            tp       = price_map.get(tk, {})
            day_data = tp.get(date_str)
            if not day_data:
                continue

            # ── Gain% from price_map ──
            gain = None
            if d_idx > 0:
                prev_date = all_dates[d_idx - 1]
                prev_data = tp.get(prev_date)
                if prev_data and prev_data["c"] > 0:
                    gain = round((day_data["c"] - prev_data["c"]) / prev_data["c"] * 100, 2)

            # ── SRI: trimmed mean from flow history before current date ──
            tk_hist = ticker_flow_hist.get(tk, [])
            prev_sm_vals = [
                h["sm"] for h in tk_hist
                if h["sk"] < cur_sk and h["sm"] > 0
            ][-10:]
            if len(prev_sm_vals) >= 3:
                trimmed  = sorted(prev_sm_vals)[:-1]
                sm_sma10 = sum(trimmed) / len(trimmed)
            elif prev_sm_vals:
                sm_sma10 = sum(prev_sm_vals) / len(prev_sm_vals)
            else:
                sm_sma10 = 0
            sri = round(sm / sm_sma10, 2) if sm_sma10 > 0 else 0

            # ── BM_SMA10: simple mean from flow history before current date ──
            prev_bm_vals = [h["bm"] for h in tk_hist if h["sk"] < cur_sk][-10:]
            bm_sma10 = sum(prev_bm_vals) / len(prev_bm_vals) if prev_bm_vals else 0

            # ── ATR% from price_map ──
            price_hist = []
            for i in range(1, 15):
                if d_idx - i < 0:
                    break
                pd      = all_dates[d_idx - i]
                pd_data = tp.get(pd)
                if pd_data and pd_data["c"] > 0:
                    price_hist.append(pd_data["c"])
            atr = None
            if len(price_hist) >= 3:
                daily_changes = [
                    abs((price_hist[j] - price_hist[j+1]) / price_hist[j+1] * 100)
                    for j in range(len(price_hist) - 1)
                    if price_hist[j+1] > 0
                ]
                if daily_changes:
                    atr = round(sum(daily_changes) / len(daily_changes), 2)

            phase, action = _compute_phase_action(sm, bm, sri, gain, tx_sm, tx_bm, bm_sma10, atr)

            if tk not in signal_timeline:
                signal_timeline[tk] = []
            signal_timeline[tk].append((d_idx, date_str, phase, action, atr or 2.5))

    # 5. Pair matching: multiple BUY entries, single SELL closes all
    #    Stop loss: ATR-based per position — max(atr*2.0, 5%) floor, 12% ceiling
    #    RI guard : skip SL on days with single-day drop >30% (rights issue / split)
    trades = []

    for tk, timeline in signal_timeline.items():
        tp = price_map.get(tk, {})
        open_positions = []  # list of {entry_date, entry_phase, entry_price, entry_didx, sl_threshold}

        # Build a lookup so we can process signals while iterating ALL trading days
        signal_lookup = {date_str: (phase, action, atr) for _, date_str, phase, action, atr in timeline}

        for date_str in use_dates:
            # Skip days with no open positions AND no signal — nothing to do
            if not open_positions and date_str not in signal_lookup:
                continue

            d_idx       = date_idx.get(date_str)
            day_data    = tp.get(date_str)
            close_price = day_data["c"] if day_data and day_data.get("c") else None

            # ── RI guard: detect corporate action days (rights issue / split) ──
            # Price drop >30% in one day = TERP adjustment, not a real market move.
            ri_day        = False
            prev_ri_price = None
            if close_price and d_idx is not None and d_idx > 0:
                prev_data = tp.get(all_dates[d_idx - 1])
                if prev_data and prev_data.get("c") and prev_data["c"] > 0:
                    if (close_price - prev_data["c"]) / prev_data["c"] * 100 < -30:
                        ri_day        = True
                        prev_ri_price = prev_data["c"]

            # ── Stop loss check every trading day (skipped on RI days) ──
            if close_price and open_positions and not ri_day:
                surviving = []
                for pos in open_positions:
                    entry_p  = pos["entry_price"]
                    loss_pct = (close_price - entry_p) / entry_p * 100
                    if loss_pct <= pos["sl_threshold"]:
                        trades.append({
                            "ticker":       tk,
                            "entry_phase":  pos["entry_phase"],
                            "exit_phase":   "SL",
                            "entry_date":   pos["entry_date"],
                            "exit_date":    date_str,
                            "entry_price":  round(entry_p, 2),
                            "exit_price":   round(close_price, 2),
                            "duration":     d_idx - pos["entry_didx"] if d_idx is not None else 0,
                            "profit":       round(loss_pct, 2),
                        })
                    else:
                        surviving.append(pos)
                open_positions = surviving

            # ── RI day: force-close open positions at pre-RI price ──
            # Exit at H-1 close so the -90% TERP drop doesn't contaminate P&L.
            # Marked RI_SKIP so aggregation can exclude them from stats.
            if ri_day and open_positions and prev_ri_price:
                for pos in open_positions:
                    profit = round((prev_ri_price - pos["entry_price"]) / pos["entry_price"] * 100, 2)
                    trades.append({
                        "ticker":       tk,
                        "entry_phase":  pos["entry_phase"],
                        "exit_phase":   "RI_SKIP",
                        "entry_date":   pos["entry_date"],
                        "exit_date":    date_str,
                        "entry_price":  round(pos["entry_price"], 2),
                        "exit_price":   round(prev_ri_price, 2),
                        "duration":     d_idx - pos["entry_didx"] if d_idx is not None else 0,
                        "profit":       profit,
                    })
                open_positions = []

            # ── Process signal for this day if one exists ──
            if date_str not in signal_lookup:
                continue

            # Skip RI-contaminated signals — price on RI day reflects TERP adjustment,
            # not real SM behavior, so neither BUY entries nor SELL exits are valid.
            if ri_day:
                continue

            phase, action, sig_atr = signal_lookup[date_str]

            if action == "BUY":
                # SL threshold: ATR-based, floor 5%, ceiling 12%
                sl_thresh = -min(max(sig_atr * 2.0, 5.0), 10.0)
                # Open new position at next day's open
                next_idx = d_idx + 1 if d_idx is not None else None
                if next_idx is None or next_idx >= len(all_dates):
                    continue
                next_date = all_dates[next_idx]
                next_data = tp.get(next_date)
                if next_data and next_data["o"] and next_data["o"] > 0:
                    open_positions.append({
                        "entry_date":   date_str,
                        "entry_phase":  phase,
                        "entry_price":  next_data["o"],
                        "entry_didx":   d_idx,
                        "sl_threshold": sl_thresh,
                    })

            elif action == "SELL" and open_positions:
                # Close ALL remaining open positions at next day's open
                next_idx = d_idx + 1 if d_idx is not None else None
                if next_idx is None or next_idx >= len(all_dates):
                    if close_price:
                        exit_price = close_price
                    else:
                        continue
                else:
                    next_date = all_dates[next_idx]
                    next_data = tp.get(next_date)
                    if next_data and next_data["o"] and next_data["o"] > 0:
                        exit_price = next_data["o"]
                    else:
                        continue

                for pos in open_positions:
                    entry_p  = pos["entry_price"]
                    duration = (d_idx - pos["entry_didx"]) if d_idx is not None else 0
                    profit   = round((exit_price - entry_p) / entry_p * 100, 2)
                    trades.append({
                        "ticker":       tk,
                        "entry_phase":  pos["entry_phase"],
                        "exit_phase":   phase,
                        "entry_date":   pos["entry_date"],
                        "exit_date":    date_str,
                        "entry_price":  round(entry_p, 2),
                        "exit_price":   round(exit_price, 2),
                        "duration":     duration,
                        "profit":       profit,
                    })
                open_positions = []

    log.info(f"  Total completed trades: {len(trades)}")

    # 6. Aggregate into leaderboard by Entry phase only (4 combos: SOS/SPRING/ABSORB/ACCUM)
    from collections import defaultdict
    combos = defaultdict(lambda: {"trades": 0, "wins": 0, "profits": [], "durations": [], "details": []})

    for t in trades:
        if t.get("exit_phase") == "RI_SKIP":  # exclude corporate-action force-closes
            continue
        if t.get("profit", 0) < -50:  # exclude extreme losses (rights issue, delisting, etc.)
            continue
        key = t["entry_phase"]
        combos[key]["trades"] += 1
        combos[key]["profits"].append(t["profit"])
        combos[key]["durations"].append(t["duration"])
        combos[key]["details"].append({
            "ticker": t["ticker"],
            "entry_date": t["entry_date"],
            "exit_date": t["exit_date"],
            "exit_phase": t["exit_phase"],
            "entry_price": t["entry_price"],
            "exit_price": t["exit_price"],
            "duration": t["duration"],
            "profit": t["profit"],
        })
        if t["profit"] > 0:
            combos[key]["wins"] += 1

    leaderboard = []
    for entry_phase, data in combos.items():
        profits = data["profits"]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        win_pct = round(data["wins"] / data["trades"] * 100, 1) if data["trades"] > 0 else 0
        avg_profit = round(sum(profits) / len(profits), 2) if profits else 0
        avg_win = round(sum(wins) / len(wins), 2) if wins else 0
        avg_loss = round(sum(losses) / len(losses), 2) if losses else 0
        avg_dur = round(sum(data["durations"]) / len(data["durations"]), 1) if data["durations"] else 0

        gross_profit = sum(p for p in profits if p > 0)
        gross_loss = abs(sum(p for p in profits if p <= 0))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0)

        leaderboard.append({
            "entry": entry_phase,
            "trades": data["trades"],
            "wins": data["wins"],
            "losses": data["trades"] - data["wins"],
            "win_rate": win_pct,
            "avg_profit": avg_profit,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_duration": avg_dur,
            "profit_factor": profit_factor,
            "details": sorted(data["details"], key=lambda x: x["profit"], reverse=True),
        })

    leaderboard.sort(key=lambda x: x.get("profit_factor") or 0, reverse=True)

    # Overall stats across all trades
    all_profits = [t["profit"] for t in trades]
    total_wins  = sum(1 for p in all_profits if p > 0)
    total_losses = len(all_profits) - total_wins
    overall_wr  = round(total_wins / len(all_profits) * 100, 1) if all_profits else 0
    gp_all = sum(p for p in all_profits if p > 0)
    gl_all = abs(sum(p for p in all_profits if p <= 0))
    overall_pf = round(gp_all / gl_all, 2) if gl_all > 0 else (99.0 if gp_all > 0 else 0)

    result = {
        "computed_at": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        "days": days,
        "date_range": f"{use_dates[0]} → {use_dates[-1]}" if use_dates else "",
        "total_trades": len(trades),
        "total_wins": total_wins,
        "total_losses": total_losses,
        "overall_win_rate": overall_wr,
        "overall_profit_factor": overall_pf,
        "tickers_tested": len(set(t["ticker"] for t in trades)),
        "leaderboard": leaderboard,
    }

    conn.execute(
        "INSERT INTO backtest_cache (computed_at, days, results) VALUES (?, ?, ?)",
        [result["computed_at"], days, json.dumps(result)]
    )
    conn.execute("DELETE FROM backtest_cache WHERE id NOT IN (SELECT id FROM backtest_cache ORDER BY id DESC LIMIT 10)")
    conn.commit()

    log.info(f"✅ BACKTEST complete: {len(trades)} trades, {len(leaderboard)} combos")
    return result
