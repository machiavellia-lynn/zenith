# ZENITH — Smart Money Intelligence Platform

> Complete Technical Documentation v3
> Last updated: April 2026

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [File Structure](#3-file-structure)
4. [Authentication System](#4-authentication-system)
5. [Database — Schema & Tables](#5-database--schema--tables)
6. [Database — Memory Management & Performance](#6-database--memory-management--performance)
7. [Scraper System — Realtime + Backfill](#7-scraper-system--realtime--backfill)
8. [EOD Summary — Pre-Aggregation Layer](#8-eod-summary--pre-aggregation-layer)
9. [API Endpoints](#9-api-endpoints)
10. [Admin Endpoints](#10-admin-endpoints)
11. [Frontend Pages](#11-frontend-pages)
12. [Overlay System (CM/SM/BM)](#12-overlay-system-cmsmbm)
13. [Chart Technical Details](#13-chart-technical-details)
14. [Metric Formatting](#14-metric-formatting)
15. [Sector Dictionary](#15-sector-dictionary)
16. [Telegram Source Configuration](#16-telegram-source-configuration)
17. [Railway Deployment](#17-railway-deployment)
18. [Analytics System](#18-analytics-system)
19. [Responsive Design](#19-responsive-design)
20. [Key Bug Fixes & Lessons Learned](#20-key-bug-fixes--lessons-learned)
21. [Pending / Future](#21-pending--future)

---

## 1. Project Overview

Zenith is a **personal trading intelligence dashboard** for the Indonesian Stock Exchange (IDX/BEI). It tracks Smart Money (SM), Bad Money (BM), and Money Flow (MF) data scraped from a private Telegram group, stores it in SQLite, and visualizes it via a Flask web application with Lightweight Charts v4.

**Core methodology:** Bandarmologi — tracking broker-level smart money flows to identify institutional accumulation and distribution patterns before price moves.

**Key capabilities:**
- Realtime Telegram scraping (SM/BM/MF+ /MF-)
- Pre-aggregated daily summaries for instant page loads (~5-10ms)
- Fullscreen candlestick charts with cumulative overlay lines
- Flow table with 11 sortable columns + modal popup charts
- Sector rotation analysis across 11 IDX sectors (962 tickers)
- Admin panel with mascot character, scraper controls, and analytics

**Tech stack:** Python Flask, SQLite (WAL mode), Telethon, Lightweight Charts v4, Pikaday, Yahoo Finance, Railway (Hobby tier)

**Live URL:** `zenith-production-bbb6.up.railway.app`

---

## 2. Architecture

```
Railway Server (single service, 1GB RAM)
├── Gunicorn (main process)
│   └── Flask worker thread — serves web UI + API
├── Scraper daemon thread (started by app.py on boot)
│   ├── Telethon client — connected to Telegram 24/7
│   ├── Realtime listener — NewMessage on 4 topics
│   ├── Daily backfill — 17:00 WIB auto-scan
│   └── Signal queue — picks up manual backfill/rebuild requests
└── SQLite DB (/data/zenith.db) — shared via WAL mode
    ├── raw_messages — SM/BM transaction data
    ├── raw_mf_messages — MF+/MF- data
    └── eod_summary — pre-aggregated per ticker per date (fast reads)
```

**Critical design pattern — Signal Queue:**
All long-running operations (weekly backfill, summary rebuild) are NOT run in the HTTP thread. Instead:
1. HTTP endpoint sets a flag (`_backfill_request["status"] = "pending"`)
2. Returns instantly to browser
3. Scraper thread checks flag every 5 seconds
4. Picks up request → runs with its own Telethon client + DB connection
5. Updates status to "done" with result

This prevents:
- **Database lock conflicts** (only one thread writes at a time)
- **Gunicorn timeout kills** (HTTP response returns instantly)

---

## 3. File Structure

```
zenith_project/
├── app.py                  (1232 lines) — Flask backend, all routes + APIs
├── scraper_daily.py         (815 lines) — Telethon listener + daily backfill + parsers + summary functions
├── scraper_weekly.py        (162 lines) — N-day backfill, reuses scraper_daily parsers
├── requirements.txt                     — flask, gunicorn, telethon, requests, etc.
├── Procfile                             — web: gunicorn app:app
└── templates/
    ├── login.html            (82 lines) — Access key gate
    ├── hub.html             (319 lines) — Landing dashboard + onboarding spotlight
    ├── chart.html           (543 lines) — Fullscreen candlestick + overlay + transactions
    ├── flow.html           (1714 lines) — Flow table + modal popup chart
    ├── sector.html         (1799 lines) — Sector grid + detail + modal popup chart
    └── admin.html           (459 lines) — Admin control panel + mascot + analytics
```

---

## 4. Authentication System

- **Method:** Flask session cookie (expires on browser close, not persistent)
- **Env vars:** `ACCESS_KEY` (default: `zenith2026`), `FLASK_SECRET`
- **Login flow:** User visits `/` → enters access key → POST → `session["authed"] = True` → redirect `/hub`
- **Protection:** Every route and API endpoint calls `is_authed()`. Unauthorized API calls return `{"error": "unauthorized"}` with 401.
- **Admin endpoints** use a separate `UPLOAD_SECRET` passed as `?secret=` query param (server-side check).

---

## 5. Database — Schema & Tables

**File:** `/data/zenith.db` (SQLite, ~120MB+, persistent volume on Railway)

### Table: `raw_messages` (SM/BM transactions)

Source: Telegram bot Joker, topics SM (192528) and BM (219042).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| message_id | INTEGER | Telegram message ID |
| channel | TEXT | `"smart"` or `"bad"` |
| date | TEXT | `DD-MM-YYYY` format |
| time | TEXT | `HH:MM:SS` (WIB) |
| tx_count | INTEGER | Micro-transaction count per signal message |
| ticker | TEXT | Stock code (e.g. `BBRI`, `EMAS`) |
| price | REAL | Price at signal time |
| gain_pct | REAL | Gain % at signal time |
| freq | INTEGER | Frequency (Format A messages only, else NULL) |
| value_raw | TEXT | Raw value string (e.g. `"539Jt"`, `"4M"`) |
| value_numeric | REAL | Converted to Juta (millions IDR) |
| avg_mf_raw / avg_mf_numeric | TEXT/REAL | Average money flow |
| mf_delta_raw / mf_delta_numeric | TEXT/REAL | MF delta (+/-), key field for SM/BM VAL |
| vol_x | REAL | Volume multiplier |
| signal | TEXT | Signal emoji (`🟢`, `🔴`, etc.) |
| scraped_at | TEXT | Timestamp of scrape |
| **UNIQUE(message_id, ticker)** | | Prevents duplicate inserts |

### Table: `raw_mf_messages` (MF+/MF- data)

Source: Telegram MF+ topic (1025256) and MF- topic (1025260).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| message_id | INTEGER | Telegram message ID |
| channel | TEXT | `"mf_plus"` or `"mf_minus"` |
| date / time / ticker / price / gain_pct | | Same as raw_messages |
| tx_count | INTEGER | Transaction count |
| val_raw / val_numeric | TEXT/REAL | Transaction value |
| mf_raw / mf_numeric | TEXT/REAL | Money Flow value (key field) |
| mft_raw / mft_numeric | TEXT/REAL | Money Flow Total |
| cm_delta_raw / cm_delta_numeric | TEXT/REAL | Clean Money delta |
| signal | TEXT | Signal emoji |
| **UNIQUE(message_id, ticker)** | | Prevents duplicates |

### Table: `eod_summary` (pre-aggregated daily data)

Built from raw tables. One row per ticker per date. Used by `/api/flow` and `/api/sector` for instant queries.

| Column | Type | Description |
|--------|------|-------------|
| date | TEXT | `DD-MM-YYYY` |
| ticker | TEXT | Stock code |
| sm_val | REAL | Total Smart Money value (Juta) |
| bm_val | REAL | Total Bad Money value (Juta) |
| tx_count | INTEGER | Number of signals (COUNT(*) from raw_messages) |
| mf_plus | REAL | Total MF+ (Juta, NULL if no data) |
| mf_minus | REAL | Total MF- (Juta, NULL if no data) |
| **UNIQUE(date, ticker)** | | One row per ticker per date |

### Indexes

```sql
idx_raw_date          ON raw_messages(date)
idx_raw_ticker_date   ON raw_messages(ticker, date)
idx_mf_date           ON raw_mf_messages(date)
idx_mf_ticker_date    ON raw_mf_messages(ticker, date)
idx_eod_date          ON eod_summary(date)
```

---

## 6. Database — Memory Management & Performance

### SQLite PRAGMAs (applied per connection)

| PRAGMA | Value | Why |
|--------|-------|-----|
| `journal_mode=WAL` | Write-Ahead Logging | Allows simultaneous reads (Flask) and writes (scraper). Default rollback journal locks entire file. |
| `synchronous=NORMAL` | Reduced fsync | Safe for read-heavy workloads. Only syncs at critical moments. |
| `cache_size=-64000` | 64MB page cache | Default is 2MB. With 120MB+ DB, hot pages stay in memory after first query. |
| `mmap_size=268435456` | 256MB memory-mapped I/O | OS maps DB file to virtual memory. Reads become pointer dereferences, not `read()` syscalls. |
| `temp_store=MEMORY` | Temp tables in RAM | GROUP BY / ORDER BY intermediates use RAM, not disk. |
| `busy_timeout=10000` | 10s wait on lock | Scraper connection waits up to 10s if Flask is reading. |

### Connection Architecture

| Thread | Connection | Purpose |
|--------|-----------|---------|
| Flask worker | `get_db()` — thread-local, reused, never closed | Serve API responses |
| Scraper daemon | `get_scraper_db()` — dedicated, `row_factory=sqlite3.Row` | Insert raw data, build summaries |

PRAGMAs are set once per connection lifetime (not per query).

### Performance Timeline

| Phase | /api/flow Response Time | How |
|-------|------------------------|-----|
| Initial (raw GROUP BY) | ~500ms+ | `SELECT ... FROM raw_messages GROUP BY` on 200k+ rows |
| + Flow cache (60s TTL) | ~200ms first, 0ms cached | Python dict cache, bypasses DB entirely |
| + Async gain loading | ~200ms (DB) + gains fill later | `skip_gains=1`, frontend calls `/api/gains` separately |
| + EOD Summary table | **~5-10ms** | `SELECT ... FROM eod_summary` on ~500 rows per day |

### Memory Budget (1GB Railway)

| Component | Memory |
|-----------|--------|
| SQLite mmap | Up to 256MB (OS-managed, virtual — only accessed pages loaded) |
| SQLite page cache | 64MB per worker |
| Flask + Python + Telethon | ~150MB |
| Gain/IHSG caches | ~10-15MB |
| **Effective total** | **~200-300MB** |

---

## 7. Scraper System — Realtime + Backfill

### Files

| File | Lines | Role |
|------|-------|------|
| `scraper_daily.py` | 815 | All parsers, DB functions, realtime listener, daily backfill, signal queue, EOD summary builder |
| `scraper_weekly.py` | 162 | N-day backfill function, imports everything from `scraper_daily` |

### Startup

```python
# app.py on boot:
if SCRAPER_ENABLED:
    from scraper_daily import start_scraper_thread
    _scraper_thread = start_scraper_thread()
```

Creates a daemon thread with its own asyncio event loop → TelegramClient connects → registers listener → enters loop.

### Realtime Listener

```python
@client.on(events.NewMessage(chats=GROUP_ID))
async def on_new_message(event):
    n = process_message(conn, event.message)
    # Also rebuilds eod_summary for that date
```

Every new message in the group is:
1. Filtered by topic ID (SM/BM/MF+/MF-)
2. Parsed by appropriate parser
3. Inserted via `INSERT OR IGNORE` (UNIQUE constraint prevents duplicates)
4. Triggers `rebuild_summary_for_date()` for that date

### Daily Backfill (17:00 WIB)

Scans all messages from today in all 4 topics. Catches anything missed by the realtime listener (e.g., network hiccup). Same `INSERT OR IGNORE` logic.

### Weekly/Manual Backfill

Triggered via `/admin/scraper-weekly?secret=...&days=N`. Signal queue pattern — runs in scraper thread. Scans N days back, stops after 100 consecutive messages outside date range.

### Parser Support

**SM/BM Messages (3 formats):**

| Format | Era | Structure | Key difference |
|--------|-----|-----------|----------------|
| A | Nov 2025+ | Tx·emoji Ticker Price Gain **Freq** Value AvgMF MF±delta Volx Signal | Has Freq column |
| B | Earlier | Tx·emoji Ticker Price Gain Value AvgMF MF±delta Volx Signal | No Freq |
| C | Oldest | Tx**x** Ticker Price Gain Value AvgMF MF±delta 💣Volx Signal | Uses `x` marker instead of emoji |

Format auto-detected from header: `"Freq"` → A, `"Tx|Ticker"` → C, else → B.

**MF Messages (1 format):**

```
Tx·emoji Ticker Price Gain Val MF+/- MFT CM±delta Signal
```

### Value Parser (unified)

All values in messages use mixed units. `parse_value()` converts everything to **Juta (millions IDR)**:

| Unit | Multiplier | Example | Result |
|------|-----------|---------|--------|
| `Jt` | ×1 | `539Jt` | 539.0 |
| `M` | ×1000 | `4M` | 4000.0 |
| `T` | ×1000000 | `1.2T` | 1200000.0 |
| `rb` | ÷1000 | `500rb` | 0.5 |

Handles `+/-` signs. Comma → dot conversion for decimals.

---

## 8. EOD Summary — Pre-Aggregation Layer

### Problem

`/api/flow` originally ran `SELECT ... FROM raw_messages WHERE date IN (...) GROUP BY ticker, channel` on 200k+ rows. Even with indexes, this took ~200ms+.

### Solution

Pre-aggregated table `eod_summary` with one row per ticker per date. Built by:

| Event | Action |
|-------|--------|
| Realtime message insert | `rebuild_summary_for_date(conn, date)` for that day |
| Daily backfill (17:00) | Rebuild summary for today |
| Weekly backfill | Rebuild summary for all backfilled dates |
| Manual rebuild | `/admin/rebuild-summary` → rebuild ALL dates (one-time migration) |

### How it works

`rebuild_summary_for_date(conn, date)`:
1. `DELETE FROM eod_summary WHERE date = ?`
2. Query `raw_messages` for SM/BM aggregates (SUM mf_delta, COUNT rows)
3. Query `raw_mf_messages` for MF+/MF- aggregates
4. Merge per ticker
5. `INSERT` fresh rows

Not incremental — full delete+reinsert ensures accuracy.

### Result

```
BEFORE: /api/flow → GROUP BY on raw_messages (200k+ rows) → ~200ms
AFTER:  /api/flow → SELECT from eod_summary (~500 rows/day) → ~5-10ms
```

---

## 9. API Endpoints

All require authentication (`is_authed()` check).

### `/api/ihsg`
Returns IHSG composite index price and gain%. Yahoo Finance, cached 5 minutes.
```json
{"price": 7026.78, "gain_pct": -2.19}
```

### `/api/last-date`
Returns the most recent date with data in DB.
```json
{"date": "02-04-2026"}
```

### `/api/flow?date_from=DD-MM-YYYY&date_to=DD-MM-YYYY&sector=Technology`
Main flow data endpoint. Reads from `eod_summary`. Returns per-ticker SM/BM/CM/RSM/MF/TX + totals. Optional sector filter includes all sector tickers (even those without DB data).
```json
{
  "tickers": [
    {"ticker": "BBRI", "sm_val": 150.5, "bm_val": 80.2, "clean_money": 70.3,
     "rsm": 65.2, "mf_plus": 200.3, "mf_minus": 120.1, "net_mf": 80.2,
     "gain_pct": -1.5, "price": 3320, "tx": 12}
  ],
  "totals": {"sm": 934.4, "bm": 1967.2, ...},
  "date_from": "02-04-2026", "date_to": "02-04-2026"
}
```

### `/api/gains?tickers=BBRI,EMAS,...&date_from=...&date_to=...`
Batch Yahoo Finance gain/price fetch. Called async by frontend after table render. Cached 5 min per ticker. Uses `ThreadPoolExecutor(max_workers=10)`.

### `/api/transactions?ticker=BBRI&date_from=...&date_to=...`
Raw SM/BM transaction rows for a single ticker. Used by chart transaction panel.

### `/api/overlay?ticker=BBRI&tf=1h`
Cumulative CM/SM/BM overlay data per candle bucket. Used for overlay lines on chart.

### `/api/ohlcv?ticker=BBRI&tf=1D`
Yahoo Finance OHLCV candlestick data. Direct HTTP to Yahoo (not yfinance library — blocked on Railway).

### `/api/sector?date_from=...&date_to=...`
Sector-level aggregation. Reads from `eod_summary`, groups by sector via Python SECTORS dict.

---

## 10. Admin Endpoints

All require `?secret=zenith2026` query param.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin` | GET | Admin control panel page |
| `/admin/upload-db` | GET/POST | Browser UI to upload zenith.db |
| `/admin/download-db` | GET | Download zenith.db for local backup |
| `/admin/pull-db` | GET | Pull DB from Dropbox URL |
| `/admin/upload-session` | GET/POST | Browser UI to upload session_joker.session |
| `/admin/scraper-status` | GET | JSON: thread alive, latest dates, row counts, backfill/rebuild status |
| `/admin/scraper-weekly?days=7` | GET | Queue N-day backfill (signal-based, non-blocking) |
| `/admin/rebuild-summary` | GET | Queue full EOD summary rebuild (signal-based) |
| `/admin/analytics` | GET | JSON: active users, total views, daily views (14 days) |

---

## 11. Frontend Pages

### Design System (all pages)

```css
--bg: #080c10          /* Background */
--surface: #0e1318     /* Cards, panels */
--surface2: #121920    /* Nested surfaces */
--border: #1a2230      /* Subtle borders */
--border2: #243040     /* Stronger borders */
--accent: #00e8a2      /* Primary green */
--accent2: #4d9fff     /* Secondary blue */
--danger: #ff4d6a      /* Red/negative */
--text: #c8d8e8        /* Body text */
--muted: #4a6070       /* Secondary text */
Fonts: Space Mono (monospace, data), DM Sans (body text)
```

### login.html (82 lines)
- Terminal dark theme with CSS scanline background
- Password input → POST → `"ACCESS GRANTED"` animation → redirect `/hub`
- `"ACCESS DENIED"` with shake animation on wrong key
- Enter key support

### hub.html (319 lines)
- ZENITH logo + "Smart Money Intelligence Platform" tagline
- Stats bar: IHSG (price + gain%), WIB clock (live, updates every second), Total SM (latest date)
- 3 navigation cards: Chart, Flow (highlighted), Sector
- **Onboarding spotlight:** First visit → overlay dims page, `?` button highlighted with pulse animation, chat bubble invites user to read the guide. Stored in `localStorage('zenith_onboarded')`.
- Info modal (`?` button) with full Smart Money guide

### chart.html (543 lines)
- Fullscreen candlestick chart (Lightweight Charts v4)
- Dynamic height: `max(600px, calc(100vh - 280px))`
- Ticker search input + Load button
- Control bar layout: `[5m][15m][30m][1h][1D] [CM][SM][BM] ── [L][A]`
  - TF: timeframe buttons
  - CM/SM/BM: overlay toggle buttons (CM default ON)
  - L/A: log scale / auto scale
- OHLCV hover tooltip with Yahoo-style gain%
- Overlay value panel (top-left corner, shows per-bucket values on hover)
- Transactions panel below chart: SM and BM tables with Pikaday date picker
- URL param: `/chart?ticker=EMAS` auto-loads that ticker
- Chart is destroyed+recreated on every TF switch (guarantees clean state)

### flow.html (1714 lines)
- **Flow table columns:** TICKER | PRICE | TX | CLEAN MONEY | SM VAL | BM VAL | RSM | MF+ | MF- | NET MF | GAIN%
- Multi-column sort (click header, shift+click for secondary)
- CM bar visualization (bidirectional green/red bar)
- RSM gradient coloring (red → yellow → green)
- Sector filter via URL param `?sector=Technology`
- Stats bar: SM | BM | MF+ | MF- | NET CM | NET MF | Tickers | IHSG
- Ticker search filter (instant, client-side)
- Modal popup chart (click any ticker row → fullscreen chart modal identical to chart.html)
- **Async gain loading:** Table renders instantly with SM/BM/CM data, gains fill in progressively

### sector.html (1799 lines)
- Sector grid: 11 cards (3 columns desktop, 2 tablet, 1 mobile)
- Each card: sector name, gain%, SM/BM/CM/MF+/MF-/NET MF, ticker count
- Gain% loads async per sector
- Click card → inline detail view (replaces grid, no page nav)
- Detail: stats bar + sortable table with ALL sector tickers (including those without DB data)
- Modal popup chart (identical to flow.html modal)
- Date picker changes reload current view

### admin.html (459 lines)
- 4 cards: Database, Session, Scraper Control, Analytics
- **Database card:** Upload DB (XHR + progress bar), Pull from Dropbox (indeterminate bar), Download backup button
- **Session card:** Upload session_joker.session
- **Scraper card:** Live status panel (auto-refresh 5s) — thread alive/dead, latest dates, row counts, EOD summary count, backfill/rebuild status. Manual backfill (N days input + trigger). Rebuild Summary button.
- **Analytics card:** Active users, total views, daily page views bar chart (canvas, 14 days)
- **Mascot:** Anime character image (base64 embedded), fixed bottom-right, bounce animation. Chat bubble changes based on action status. Click → random quote.
- All admin operations use `?secret=` from URL param

### Info Modal (all pages except login and admin)
`?` button in navbar → scrollable modal with:
- Glossary: SM/BM/CM/RSM/MF+/MF-/NET MF/TX definitions
- Smart Money explanation + Clean Money formula
- 4 reading scenarios (accumulation, repeated, breakout, distribution)
- Real vs Fake SM signals comparison
- Common trader mistakes
- Important SM timing windows (09:30-10:30, 13:30-15:00 WIB)
- Summary rules

---

## 12. Overlay System (CM/SM/BM)

### Backend (`/api/overlay`)

1. Queries `raw_messages` for all transactions of a ticker
2. Buckets by timeframe (5m/15m/30m/1h intervals, or daily)
3. Per bucket: `sm` (smart mf_delta sum), `bm` (bad mf_delta abs sum), `cm` (sm - bm)
4. Cumulative: `cum_sm`, `cum_bm`, `cum_cm` — running totals

### Cumulative Mode: Daily Reset (default)

For intraday TFs (5m/15m/30m/1h): cumulative resets to 0 at each new day. Shows intraday flow pattern within each day.

### Frontend Rendering

- 3 `LineSeries` on a hidden `priceScale('overlay')` — separate Y axis from price
- **Carry-forward fill:** Every candle timestamp gets a data point. If no transaction at that time → carry forward the last cumulative value. This prevents gaps in the line.
- Snap: overlay timestamps are snapped to nearest candle timestamp
- Toggle buttons: CM (green, default ON), SM (blue, default OFF), BM (orange, default OFF)
- Value panel: top-left overlay showing per-bucket non-cumulative values on crosshair hover

---

## 13. Chart Technical Details

### Gain% Calculation (Yahoo-style)

```
gain% = (close - prevClose) / prevClose × 100
```

NOT `(close - open) / open` because open price can gap from previous close.

`prevCloseMap` built when candles load:
```javascript
for (let i = 0; i < candles.length; i++)
    prevCloseMap[candles[i].time] = i > 0 ? candles[i-1].close : candles[i].open;
```

### 150 Bar Visible Range

After loading candles: `setVisibleLogicalRange` with double `requestAnimationFrame` to ensure chart is fully rendered before setting range.

### TF Switch

Chart is completely destroyed and recreated on TF change (not reused). LWC internal state persists between `setData` calls, causing visual artifacts — destroy+recreate guarantees clean state.

### Emiten Name Fallback

Yahoo Finance `longName` is null for some tickers (e.g. AYAM). Fallback chain:
```python
name = meta.get("longName") or meta.get("shortName") or ticker
```

### TX Column

Uses `COUNT(*)` from `raw_messages` per ticker — counts number of signal messages, NOT `SUM(tx_count)` which would count micro-transactions within each signal.

---

## 14. Metric Formatting

All values stored in **Juta** (millions IDR). Display format:

| Range | Format | Example |
|-------|--------|---------|
| < 1 Juta | K (ribu) | 500K |
| 1-999 Juta | M (Juta) | 52.2M |
| ≥ 1000 Juta | B (Miliar) | 1.5B |

Two JS functions:
- `fmtM(v)` — unsigned: `52.2M`, `1.5B`, `500K`
- `fmtMf(v)` — signed: `+52.2M`, `-1.5B` (for overlay panel)

---

## 15. Sector Dictionary

11 sectors, 962 tickers total. Defined identically in `app.py` (Python) and `flow.html` (JS for sector filter).

```
Energy:                92 tickers  (ADRO, PTBA, ITMG, BYAN, HRUM, ELSA, ...)
Basic Materials:      113 tickers  (TPIA, BRPT, INKP, TKIM, INTP, SMGR, ...)
Industrials:           65 tickers  (ASII, UNTR, IMAS, SMSM, INDS, ...)
Consumer Non-Cycl.:   132 tickers  (UNVR, ICBP, INDF, MYOR, ULTJ, ...)
Consumer Cyclicals:   164 tickers  (ACES, AUTO, ERAA, MAPI, MNCN, ...)
Healthcare:            38 tickers  (KLBF, SIDO, KAEF, MIKA, HEAL, ...)
Financials:           110 tickers  (BBCA, BBRI, BMRI, BBNI, BRIS, ...)
Property:              92 tickers  (BSDE, SMRA, CTRA, PWON, LPKR, ...)
Technology:            48 tickers  (GOTO, BUKA, EMTK, DMMX, MTDL, ...)
Infrastructure:        69 tickers  (JSMR, WIKA, WSKT, ADHI, PTPP, ...)
Transport:             39 tickers  (TLKM, EXCL, ISAT, GIAA, BIRD, ...)
```

---

## 16. Telegram Source Configuration

| Parameter | Value |
|-----------|-------|
| Group | Tools Smart Trader |
| Group ID | `-1002717915373` |
| Topic SM | `192528` |
| Topic BM | `219042` |
| Topic MF+ | `1025256` |
| Topic MF- | `1025260` |
| API ID | `31708652` |
| API Hash | `052aedc345c0d8dd864febaafae8eb93` |
| Session file | `/data/session_joker.session` |

Session uploaded via `/admin/upload-session` browser UI.

---

## 17. Railway Deployment

### Environment Variables

```
ACCESS_KEY=zenith2026
FLASK_SECRET=<random-secret>
DB_PATH=/data/zenith.db
UPLOAD_SECRET=zenith2026
SCRAPER_ENABLED=1
TG_API_ID=31708652
TG_API_HASH=052aedc345c0d8dd864febaafae8eb93
TG_SESSION_PATH=/data/session_joker
```

### Persistent Volume

Mount point: `/data/`
Contains: `zenith.db`, `session_joker.session`

### DB Update Methods

1. **Automatic:** Scraper inserts data in realtime + daily backfill
2. **Manual upload:** `/admin/upload-db` browser UI
3. **Dropbox pull:** `/admin/pull-db` (downloads from hardcoded Dropbox URL, atomic `os.replace`)
4. **Backup download:** `/admin/download-db` (Flask `send_file`)

### First Deploy Checklist

1. Set env vars
2. Deploy (auto-builds from GitHub)
3. Upload `session_joker.session` via `/admin/upload-session`
4. Restart service (picks up session)
5. Verify: `/admin/scraper-status?secret=zenith2026` → `thread_alive: true`
6. Run once: `/admin/rebuild-summary?secret=zenith2026` → builds EOD summary from all historical data
7. Monitor rebuild: `/admin/scraper-status` → `rebuild.status: "done"`

---

## 18. Analytics System

### Tracking

`before_request` middleware in Flask tracks:
- **Page views:** Per day, per route. Only authenticated users, only page routes (not API/admin).
- **Active sessions:** Session ID + last seen timestamp. Auto-cleanup: sessions inactive >10 minutes are removed.

### Storage

In-memory Python dict `_analytics`. Resets on deploy/restart. Not persisted to DB.

```python
_analytics = {
    "page_views": {"2026-04-01": {"total": 50, "/hub": 10, "/flow": 30}},
    "active_sessions": {"session_id": timestamp},
    "total_views": 1234,
}
```

### Admin Display

Analytics card in admin.html:
- Active Users count (green)
- Total Views count
- Bar chart (HTML canvas, no library) showing daily views for last 14 days
- Auto-refresh every 5 seconds

---

## 19. Responsive Design

All pages responsive with two breakpoints:

| Breakpoint | Target |
|------------|--------|
| `768px` | Tablet / phone landscape |
| `420px` | Phone portrait (1080×2340 class screens, ~390px CSS width) |

Key responsive behaviors:
- **Header:** Wraps, nav divider hidden, buttons compact, logo `/page` text hidden on smallest screens
- **Stats bar (flow/sector):** Switches from flex to CSS grid (3 col → 2 col on phone)
- **Tables (flow/sector):** Horizontal scroll with `-webkit-overflow-scrolling: touch`, `min-width: 920px`
- **Modals:** Fullscreen on mobile (no border-radius, 100vh)
- **Chart:** Height reduces to `360px` (phone) / `420px` (tablet)
- **Sector grid:** 3 col → 2 col → 1 col
- **Admin mascot:** Smaller on mobile (50px)

---

## 20. Key Bug Fixes & Lessons Learned

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Chart X axis labels cut off | `autoSize:true` miscalculates in flex containers | Explicit `getBoundingClientRect()` + `ResizeObserver` |
| Chart 150 bar view broken on TF switch | LWC internal state persists between `setData` | Destroy + recreate chart on every TF switch |
| Overlay lines have gaps | Only transaction-time candles had data points | Carry-forward fill: every candle time gets a point |
| IHSG shows 0% gain | `regularMarketPrice` returns current day (market closed = same as close) | Use last 2 valid closes from `range=10d` |
| Gain% differs from Yahoo | Used `(close-open)/open` | Changed to `(close-prevClose)/prevClose` |
| Slow 5-10s page load | Yahoo gain fetch blocks entire HTTP response | Split: DB instant via `skip_gains=1`, gains async via `/api/gains` |
| Emiten name empty (e.g. AYAM) | Yahoo `longName` is null for some tickers | Fallback: `longName → shortName → ticker` |
| TX count too high | `SUM(tx_count)` counts micro-transactions | Changed to `COUNT(*)` for signal count |
| `latest_data` shows wrong date | `MAX(date)` on `DD-MM-YYYY` sorts lexicographically wrong (`31 > 26`) | `ORDER BY substr(date,7,4)\|\|substr(date,4,2)\|\|substr(date,1,2) DESC LIMIT 1` |
| Database locked on backfill | HTTP thread (weekly backfill) + scraper thread both write | Signal queue: all writes in scraper thread only |
| Gunicorn timeout kills worker | Long backfill in HTTP handler (>30s) | Non-blocking signal → scraper thread picks up |
| `eod_summary` wrong schema | Old table from `db_setup.py` had different columns | `DROP TABLE IF EXISTS` + recreate if schema mismatch |
| `tuple indices not str` | `get_scraper_db()` missing `row_factory = sqlite3.Row` | Added `conn.row_factory = sqlite3.Row` |

### Key Principles

- **`mf_delta_numeric`, not `value_numeric`**, is the correct field for SM/BM VAL — `value_numeric` captures all transaction volume, not just smart money
- **DD-MM-YYYY strings sort incorrectly** with `MAX()`/`ORDER BY` — must use `substr()` reordering to YYYYMMDD
- **TX count must use `COUNT(*)`**, not `SUM(tx_count)`, to count signals not micro-transactions
- **Weighted average price** requires `SUM(price * tx_count) / SUM(tx_count)`, not `AVG(price)`
- **Telegram rate limits are the real bottleneck** — not DB speed or parsing. Batch insert optimizations triggered FloodWait.
- **Overlay cumulative logic requires carry-forward fill** across all candle timestamps, not just timestamps where transactions exist
- **`flow.html` and `sector.html` share modal popup chart code** — changes must be applied to both simultaneously

---

## 21. Pending / Future

1. **Overlay mode toggle** — UI button to switch between daily-reset and continuous cumulative
2. **Market cap weighting** — For accurate sector gain% (currently simple average of member gains)
3. **MF sub-channel integration** — MF+/MF- columns reserved in dashboard; dedicated MF topic not fully integrated
4. **Zenith Bot (Kei)** — Custom Node.js Telegram bot with Groq AI, GCoS screening, syariah filter
5. **Zenith Linux** — Local NixOS + Hyprland version with keyboard copilot hardware key
6. **Profile site integration** — machiavellia-lynn.github.io/mylink with Zenith AI chat sidebar
