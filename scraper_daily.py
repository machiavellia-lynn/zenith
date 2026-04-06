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

TX_EMOJI = r"[💦🌟💧🔥🥵]"

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
#  EOD SUMMARY — pre-aggregated data per ticker per date
# ══════════════════════════════════════════════════════════════════════════════

def ensure_summary_table(conn):
    """Create eod_summary table if not exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eod_summary (
            date        TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            sm_val      REAL DEFAULT 0,
            bm_val      REAL DEFAULT 0,
            tx_count    INTEGER DEFAULT 0,
            mf_plus     REAL,
            mf_minus    REAL,
            UNIQUE(date, ticker)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eod_date ON eod_summary(date)")
    conn.commit()


def rebuild_summary_for_date(conn, date_str: str):
    """Re-aggregate raw data for a single date into eod_summary."""
    # SM/BM from raw_messages
    rows_sm_bm = conn.execute("""
        SELECT ticker, channel,
               SUM(mf_delta_numeric) AS mf,
               COUNT(*) AS tx
        FROM raw_messages
        WHERE date = ?
        GROUP BY ticker, channel
    """, [date_str]).fetchall()

    # MF+/MF- from raw_mf_messages
    rows_mf = conn.execute("""
        SELECT ticker, channel,
               SUM(mf_numeric) AS mf
        FROM raw_mf_messages
        WHERE date = ?
        GROUP BY ticker, channel
    """, [date_str]).fetchall()

    # Aggregate per ticker
    tickers = {}
    for r in rows_sm_bm:
        t = r["ticker"]
        if t not in tickers:
            tickers[t] = {"sm": 0, "bm": 0, "tx": 0, "mfp": None, "mfm": None}
        if r["channel"] == "smart":
            tickers[t]["sm"] += r["mf"] or 0
        else:
            tickers[t]["bm"] += abs(r["mf"] or 0)
        tickers[t]["tx"] += r["tx"] or 0

    for r in rows_mf:
        t = r["ticker"]
        if t not in tickers:
            tickers[t] = {"sm": 0, "bm": 0, "tx": 0, "mfp": None, "mfm": None}
        if r["channel"] == "mf_plus":
            tickers[t]["mfp"] = (tickers[t]["mfp"] or 0) + (r["mf"] or 0)
        elif r["channel"] == "mf_minus":
            tickers[t]["mfm"] = (tickers[t]["mfm"] or 0) + abs(r["mf"] or 0)

    # Delete old summary for this date, then insert fresh
    conn.execute("DELETE FROM eod_summary WHERE date = ?", [date_str])
    for t, d in tickers.items():
        conn.execute("""
            INSERT INTO eod_summary (date, ticker, sm_val, bm_val, tx_count, mf_plus, mf_minus)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (date_str, t, round(d["sm"], 2), round(d["bm"], 2), d["tx"], 
              round(d["mfp"], 2) if d["mfp"] is not None else None,
              round(d["mfm"], 2) if d["mfm"] is not None else None))
    conn.commit()
    return len(tickers)


def rebuild_all_summaries(conn):
    """Rebuild eod_summary for ALL dates in raw data. Used for initial migration."""
    ensure_summary_table(conn)
    
    # Get all unique dates from both tables
    dates_sm = conn.execute(
        "SELECT DISTINCT date FROM raw_messages ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2)"
    ).fetchall()
    dates_mf = conn.execute(
        "SELECT DISTINCT date FROM raw_mf_messages ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2)"
    ).fetchall()
    
    all_dates = sorted(set(r["date"] for r in dates_sm) | set(r["date"] for r in dates_mf))
    
    log.info(f"📊 Rebuilding summary for {len(all_dates)} dates...")
    total_tickers = 0
    for i, d in enumerate(all_dates):
        n = rebuild_summary_for_date(conn, d)
        total_tickers += n
        if (i + 1) % 50 == 0:
            log.info(f"  ... {i+1}/{len(all_dates)} dates processed")
    
    log.info(f"✅ Summary rebuild complete: {len(all_dates)} dates, {total_tickers} ticker-rows")
    return {"dates": len(all_dates), "ticker_rows": total_tickers}


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

    # Update summary for today
    try:
        rebuild_summary_for_date(conn, today_wib)
    except Exception as e:
        log.warning(f"Summary update failed: {e}")
    log.info(f"✅ BACKFILL complete: scanned={total_scanned}, new_rows={total_saved}")


# ══════════════════════════════════════════════════════════════════════════════
#  BACKFILL REQUEST QUEUE (signalled from HTTP thread)
# ══════════════════════════════════════════════════════════════════════════════

_backfill_request = {"days": None, "status": "idle", "result": None}
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


def get_backfill_status():
    """Called from HTTP thread to check backfill progress."""
    with _backfill_lock:
        return dict(_backfill_request)


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
