"""
scraper_weekly.py — Zenith Weekly Backfill
==========================================
Scrape all messages from the past 7 days across all 4 topics.
INSERT OR IGNORE ensures no duplicates.

Usage:
    python scraper_weekly.py

Can also be triggered via:
    GET /admin/scraper-weekly?secret=zenith2026
"""

import asyncio
import re
import sqlite3
import os
import logging
from datetime import datetime, timedelta, timezone

# Reuse all parsers and DB functions from scraper_daily
from scraper_daily import (
    parse_joker_message, parse_mf_message,
    save_sm_bm_rows, save_mf_rows,
    get_scraper_db, get_message_topic_id,
    rebuild_summary_for_date, ensure_summary_table,
    GROUP_ID, ALL_TOPICS, SM_BM_TOPICS, MF_TOPICS,
    TOPIC_LABELS, TOPIC_CHANNELS,
    API_ID, API_HASH, SESSION_PATH, WIB,
)

log = logging.getLogger("zenith.weekly")
log.setLevel(logging.INFO)
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(asctime)s] WEEKLY %(levelname)s — %(message)s", "%H:%M:%S"))
    log.addHandler(h)

DAYS_BACK = 7


async def run_weekly_backfill(client=None, conn=None, days=DAYS_BACK):
    """Scrape messages from the past N days. Skips duplicates via INSERT OR IGNORE."""

    own_client = client is None
    own_conn = conn is None

    if own_conn:
        conn = get_scraper_db()

    if own_client:
        from telethon import TelegramClient
        client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            log.error("❌ Session not authorized")
            return
        await client.get_dialogs()

    # Build set of valid dates (DD-MM-YYYY)
    now_wib = datetime.now(WIB)
    valid_dates = set()
    for i in range(days):
        d = now_wib - timedelta(days=i)
        valid_dates.add(d.strftime("%d-%m-%Y"))

    date_range = f"{(now_wib - timedelta(days=days-1)).strftime('%d-%m-%Y')} → {now_wib.strftime('%d-%m-%Y')}"
    log.info(f"🔄 WEEKLY BACKFILL: {days} days ({date_range})")

    total_scanned = 0
    total_saved = 0

    for topic_id in ALL_TOPICS:
        label = TOPIC_LABELS[topic_id]
        channel = TOPIC_CHANNELS[topic_id]
        scanned = 0
        saved = 0
        consecutive_old = 0  # count messages older than our range

        async for message in client.iter_messages(GROUP_ID, reply_to=topic_id, limit=None):
            if not message.text:
                continue

            # Extract date from message text
            text_clean = message.text.replace("```", "").replace("`", "")
            date_match = re.search(r"(\d{2}-\d{2}-\d{4})", text_clean)
            if not date_match:
                continue

            msg_date = date_match.group(1)
            scanned += 1

            if msg_date in valid_dates:
                consecutive_old = 0
                # Parse and save
                msg_id = message.id
                if topic_id in SM_BM_TOPICS:
                    rows = parse_joker_message(message.text, channel)
                    if rows:
                        n = save_sm_bm_rows(conn, msg_id, rows)
                        saved += n
                        if n:
                            log.info(f"  ✅ {label} msg={msg_id} ({msg_date}) → {n} row(s)")
                else:
                    rows = parse_mf_message(message.text, channel)
                    if rows:
                        n = save_mf_rows(conn, msg_id, rows)
                        saved += n
                        if n:
                            log.info(f"  ✅ {label} msg={msg_id} ({msg_date}) → {n} row(s)")
            else:
                consecutive_old += 1
                # If we see 100 consecutive messages outside our date range, stop
                if consecutive_old > 100:
                    break

            if scanned % 200 == 0:
                log.info(f"  {label}: scanned={scanned}, new={saved}...")

        log.info(f"  {label}: scanned={scanned}, new_rows={saved}")
        total_scanned += scanned
        total_saved += saved

    log.info(f"✅ WEEKLY BACKFILL complete: scanned={total_scanned}, new_rows={total_saved}")

    # Rebuild summaries for all backfilled dates
    if total_saved > 0:
        log.info(f"📊 Rebuilding summaries for {len(valid_dates)} dates...")
        ensure_summary_table(conn)
        for d in valid_dates:
            try:
                rebuild_summary_for_date(conn, d)
            except Exception:
                pass
        log.info(f"✅ Summaries rebuilt")

    if own_client:
        await client.disconnect()
    if own_conn:
        conn.close()

    return {"scanned": total_scanned, "saved": total_saved}


async def main():
    """Standalone CLI entry point."""
    from telethon import TelegramClient

    conn = get_scraper_db()
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

    async with client:
        log.info("🔗 Connected to Telegram")
        await client.get_dialogs()
        log.info("✅ Dialog cache loaded")
        await run_weekly_backfill(client, conn)

    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
