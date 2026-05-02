# ZENITH PROJECT — Complete Handoff Document v4

> Smart Money Intelligence Platform for IDX (Indonesian Stock Exchange)
> Last session: April 12, 2026
> Status: Active development, deployed on Railway

---

## TABLE OF CONTENTS

1. [Project Overview](#1-project-overview)
2. [Architecture & File Structure](#2-architecture--file-structure)
3. [Database Schema](#3-database-schema)
4. [Database Memory Management](#4-database-memory-management)
5. [Scraper System](#5-scraper-system)
6. [EOD Summary & Analytics Pipeline](#6-eod-summary--analytics-pipeline)
7. [Wyckoff Phase & Action System](#7-wyckoff-phase--action-system)
8. [Backtest Engine](#8-backtest-engine)
9. [API Endpoints](#9-api-endpoints)
10. [Admin Endpoints](#10-admin-endpoints)
11. [Frontend Pages](#11-frontend-pages)
12. [Overlay System](#12-overlay-system)
13. [Chart Technical Details](#13-chart-technical-details)
14. [Sector Dictionary](#14-sector-dictionary)
15. [Telegram Configuration](#15-telegram-configuration)
16. [Railway Deployment](#16-railway-deployment)
17. [Key Bug Fixes History](#17-key-bug-fixes-history)
18. [KNOWN BUG — Backtest Not Executing](#18-known-bug--backtest-not-executing)
19. [Development Principles](#19-development-principles)

---

## 1. Project Overview

Zenith tracks Smart Money (SM) and Bad Money (BM) flows scraped from a private Telegram group called "Tools Smart Trader" (BST). Data comes from a Telegram bot called Joker that posts SM/BM/MF+/MF- signals in specific forum topics.

The system applies **Bandarmologi** methodology — tracking institutional/big player activity to detect accumulation and distribution phases using Wyckoff-inspired analytics.

**Tech stack:** Python Flask, SQLite (WAL mode), Telethon, Lightweight Charts v4, Pikaday, Yahoo Finance (direct HTTP, not yfinance), Railway (Hobby tier)

**Live URL:** `zenith-production-bbb6.up.railway.app`

**User:** Machi — CS student at Tamkang University, Taiwan. Active IDX trader. Father originated several of the systematic methodologies. Communicates in mix of Indonesian and English. Prefers surgical edits, minimal-touch changes. Strong opinions on trading logic.

---

## 2. Architecture & File Structure

```
Railway Server (single service, 1GB RAM)
├── Gunicorn (2 workers, only 1 starts scraper via lock file)
│   └── Flask worker — web UI + API
├── Scraper daemon thread (started on boot)
│   ├── Telethon client — connected to Telegram 24/7
│   ├── Realtime listener — NewMessage on 4 topics
│   ├── Daily backfill — 17:00 WIB
│   ├── Nightly backtest — 18:00 WIB (30 days, auto)
│   └── Signal queue — manual backfill/rebuild/backtest from HTTP
└── SQLite DB (/data/zenith.db ~120MB+)
```

### Files

```
zenith_project/
├── app.py                 (1346 lines) — Flask backend, all routes + API + phase computation
├── scraper_daily.py       (1371 lines) — Parsers, DB functions, Telegram listener, backfill,
│                                         EOD summary, Wyckoff analytics, backtest engine
├── scraper_weekly.py       (165 lines) — N-day backfill, imports from scraper_daily
├── requirements.txt                    — flask, gunicorn, telethon, requests
├── Procfile                            — web: gunicorn app:app
└── templates/
    ├── login.html           (82 lines)
    ├── hub.html            (319 lines) — + onboarding spotlight
    ├── chart.html          (543 lines)
    ├── flow.html          (1762 lines) — + phase/action columns + dropdown filter + info modal
    ├── sector.html        (1799 lines)
    ├── admin.html          (459 lines) — + mascot + analytics chart
    └── backtest.html       (299 lines) — leaderboard page
```

### Signal Queue Pattern (CRITICAL ARCHITECTURE)

All long-running operations MUST run in the scraper thread, NOT in HTTP handlers. Pattern:

```python
# HTTP endpoint (returns instantly):
_request = {"status": "idle"}
def request_thing():
    _request["status"] = "pending"
    return {"ok": True, "message": "Queued"}

# Scraper main loop (every 5 seconds):
if _request["status"] == "pending":
    _request["status"] = "running"
    result = do_thing()  # runs with scraper's own DB conn + Telethon client
    _request["status"] = "done"
```

**Why:** Gunicorn timeout (30s) kills HTTP handlers. SQLite locks if two threads write simultaneously. Single scraper thread owns all writes.

### Gunicorn Multi-Worker Fix

Gunicorn spawns 2 workers. Only ONE should start the scraper. Uses lock file:

```python
_lock_path = "/tmp/zenith_scraper.lock"
_lock_fd = os.open(_lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
# Got lock → start scraper. FileExistsError → skip.
```

Stale lock cleanup via PID check on boot.

---

## 3. Database Schema

### Table: `raw_messages` (SM/BM transactions)

| Column | Type | Description |
|--------|------|-------------|
| message_id | INTEGER | Telegram message ID |
| channel | TEXT | `"smart"` or `"bad"` |
| date | TEXT | `DD-MM-YYYY` (WARNING: sorts wrong lexicographically, use substr reorder) |
| time | TEXT | `HH:MM:SS` (WIB) |
| tx_count | INTEGER | Micro-transactions per signal |
| ticker | TEXT | Stock code |
| price | REAL | Price at signal time |
| gain_pct | REAL | Gain % at signal time (from Joker message) |
| freq | INTEGER | Frequency (Format A only) |
| value_raw / value_numeric | TEXT/REAL | Transaction value (converted to Juta) |
| avg_mf_raw / avg_mf_numeric | TEXT/REAL | Average MF |
| mf_delta_raw / mf_delta_numeric | TEXT/REAL | **KEY FIELD for SM/BM VAL** |
| vol_x | REAL | Volume multiplier |
| signal | TEXT | Emoji signal |
| UNIQUE(message_id, ticker) | | Prevents duplicates |

### Table: `raw_mf_messages` (MF+/MF- data)

Same structure principle. Key fields: `mf_numeric`, `mft_numeric`, `cm_delta_numeric`. Channel: `"mf_plus"` or `"mf_minus"`.

### Table: `eod_summary` (pre-aggregated, v2 schema)

| Column | Type | Description |
|--------|------|-------------|
| date | TEXT | DD-MM-YYYY |
| ticker | TEXT | Stock code |
| sm_val | REAL | Total Smart Money (Juta) |
| bm_val | REAL | Total Bad Money (Juta) |
| tx_count | INTEGER | Total signal count |
| tx_sm | INTEGER | SM signal count (for RPR) |
| tx_bm | INTEGER | BM signal count (for RPR) |
| mf_plus | REAL | MF+ total |
| mf_minus | REAL | MF- total |
| vwap_sm | REAL | Volume-weighted avg price of SM (`SUM(price*|mf_delta|)/SUM(|mf_delta|)`) |
| price_close | REAL | Yahoo close price (fetched once, stored) |
| price_change_pct | REAL | Daily change % |
| sri | REAL | SM Relative Intensity |
| mes | REAL | Market Efficiency Score |
| volx_gap | REAL | Close vs VWAP SM gap % |
| rpr | REAL | Retail/Sell Participation Ratio |
| phase | TEXT | Wyckoff phase label |
| action | TEXT | Trading action signal |
| UNIQUE(date, ticker) | | |

Schema detection: startup checks `SELECT phase FROM eod_summary`. If fails → DROP + recreate with v2 schema.

### Table: `backtest_cache`

| Column | Type |
|--------|------|
| id | INTEGER PK |
| computed_at | TEXT |
| days | INTEGER |
| results | TEXT (JSON blob) |

### Indexes

```sql
idx_raw_date          ON raw_messages(date)
idx_raw_ticker_date   ON raw_messages(ticker, date)
idx_mf_date           ON raw_mf_messages(date)
idx_mf_ticker_date    ON raw_mf_messages(ticker, date)
idx_eod_date          ON eod_summary(date)
idx_eod_ticker        ON eod_summary(ticker, date)
```

---

## 4. Database Memory Management

### SQLite PRAGMAs

| PRAGMA | Value | Purpose |
|--------|-------|---------|
| journal_mode=WAL | Write-Ahead Logging | Concurrent read (Flask) + write (scraper) |
| synchronous=NORMAL | Reduced fsync | Safe for read-heavy |
| cache_size=-64000 | 64MB page cache | Hot pages in memory |
| mmap_size=268435456 | 256MB mmap | OS maps DB to virtual memory |
| temp_store=MEMORY | RAM temp tables | GROUP BY in RAM |
| busy_timeout=10000 | 10s wait | Scraper waits if Flask reading |

### Connection Architecture

- Flask: `get_db()` — thread-local, reused, `row_factory=sqlite3.Row`
- Scraper: `get_scraper_db()` — dedicated, `row_factory=sqlite3.Row`, own PRAGMAs

### Performance

| Query | Before | After (eod_summary) |
|-------|--------|---------------------|
| /api/flow | ~200ms (GROUP BY 200k+ rows) | ~5-10ms (SELECT from pre-aggregated) |
| /api/sector | ~300ms | ~10ms |

Yahoo gain/price loaded async: table renders instantly, gains fill in progressively.

---

## 5. Scraper System

### Parser Support

**SM/BM: 3 formats auto-detected**

| Format | Era | Detection | Key diff |
|--------|-----|-----------|----------|
| A | Nov 2025+ | Header has "Freq" | Has Freq column |
| B | Earlier | Default | No Freq |
| C | Oldest | Header has "Tx\|Ticker" | Uses `x` marker not emoji |

**TX_EMOJI pattern:** `[💦🌟💧🔥🥵⭐]\uFE0F?` — Must include ⭐ with variation selector. Previously missing → data loss for tickers using ⭐.

**MF: 1 format**
```
Tx·emoji Ticker Price Gain Val MF+/- MFT CM±delta Signal
```

### Value Parser (unified `parse_value`)

All units → Juta: `Jt` ×1, `M` ×1000, `T` ×1000000, `rb` ÷1000. Handles +/- signs.

### Schedule

| Time | Event |
|------|-------|
| 24/7 | Realtime listener on 4 topics |
| 17:00 WIB | Daily backfill + summary rebuild + price enrich + analytics |
| 18:00 WIB | Nightly backtest (30 days) |
| Manual | Via admin endpoints (signal queue) |

### Telegram Config

- Group: Tools Smart Trader, ID: `-1002717915373`
- Topics: SM `192528`, BM `219042`, MF+ `1025256`, MF- `1025260`
- Session: `/data/session_joker.session`

---

## 6. EOD Summary & Analytics Pipeline

### Pipeline (daily, automatic at 17:00 WIB)

```
1. run_backfill() — scan today's Telegram messages, INSERT OR IGNORE
2. rebuild_summary_for_date(today) — aggregate raw → eod_summary
     └── Also computes VWAP_SM: SUM(price * |mf_delta|) / SUM(|mf_delta|)
3. enrich_daily_prices(today) — fetch Yahoo close prices, store in eod_summary
4. compute_analytics_for_date(today) — compute SRI/MES/VolxGap/RPR/Phase/Action
```

### rebuild_summary_for_date

Deletes old rows for that date, re-aggregates from raw tables. Splits tx_count into tx_sm and tx_bm.

### enrich_daily_prices

Fetches Yahoo close price for each ticker missing `price_close`. Parallel with ThreadPoolExecutor(10). Only runs once per date.

### compute_analytics_for_date

For each ticker on that date:
1. Query 10-day history for SRI computation
2. Compute SRI, RPR, MES, Volx Gap
3. Classify phase + derive action
4. UPDATE eod_summary row

---

## 7. Wyckoff Phase & Action System

### 4 Computed Metrics

| Metric | Formula | Meaning |
|--------|---------|---------|
| **SRI** | `sm_val_today / SMA(sm_val, 10)` | How aggressive is SM today vs its own 10-day avg |
| **MES** | `\|gain%\| / SRI` | Effort vs Result. Low = absorption (price flat despite heavy buying) |
| **Volx Gap** | `(close - vwap_sm) / close × 100` | Is close above or below SM's avg purchase price |
| **RPR** | `tx_bm / (tx_sm + tx_bm)` | Ratio of SELL signals to total. **NOT retail participation** — BM = big players selling |

### Phase Classification (RSM-based, size-agnostic)

**CRITICAL:** Uses RSM (percentage) not absolute CM. This makes thresholds work for both small and large cap stocks.

| Phase | Conditions | Meaning |
|-------|-----------|---------|
| **SOS** | gain > 2% + RSM > 65% + SRI > 3.0 | Sign of Strength — strong up with SM backing |
| **SPRING** | gain < -1% + RSM > 60% + SRI > 1.5 | Price drops but SM accumulating — coiled spring |
| **UPTHRUST** | gain > 2% + RSM < 40% + RPR > 0.6 | Price up but BM dominates — trap |
| **DISTRI** | RSM < 40% + gain < -0.5% + SRI > 1.0 | BM dominates + price falling — distribution |
| **ABSORB** | SRI > 2.0 + RSM > 65% + \|gain\| < 1.5% | SM very active but price flat — stealth accumulation |
| **ACCUM** | RSM > 60% + SRI > 1.0 | SM dominates with activity (lighter than ABSORB) |
| **NEUTRAL** | Everything else | No clear signal |

### Action Signals

| Action | When |
|--------|------|
| 🚀 **BUY** | SOS (gain < 5%), SPRING, ABSORB, ACCUM |
| ⌛ **HOLD** | SOS (gain ≥ 5%), NEUTRAL |
| ⚠️ **SELL** | UPTHRUST, DISTRI |

### Phase Computation Locations (MUST STAY IN SYNC)

Phase is computed in **THREE places** — all must use identical logic:

1. **app.py `/api/flow`** — computed on-the-fly from range-aggregated data. Uses gain% from Yahoo async.
2. **scraper_daily.py `_classify_phase()`** — computed during `compute_analytics_for_date()`, stored in eod_summary.
3. **scraper_daily.py `_compute_phase_action()`** — used by backtest engine.

If you change thresholds, change ALL THREE.

### Phase Refinement in app.py

After reading phase from DB, app.py applies a refinement layer using Yahoo gain%:
```python
# SOS override: if gain > 2% + CM positive + SRI > 1.0
if gain > 2 and rsm > 65 and sri > 3.0:
    phase = "SOS"
```
This catches cases where `price_change_pct` in DB is NULL but Yahoo gain% is available.

---

## 8. Backtest Engine

### Location

`scraper_daily.py` → `run_backtest(conn, days=30)`

### How It Works

1. Get all dates from eod_summary, take last N for signals (reserve 5 for forward returns)
2. Fetch Yahoo OHLCV (open/high/low/close) per ticker — parallel, 10 threads
3. For each ticker on each signal date:
   - Compute gain% from previous day close
   - Run `_compute_phase_action()` → get phase + action
   - Entry price = **OPEN of next day** (realistic: trader sees signal after close, buys at next open)
4. Forward returns:
   - **BUY:** `(max HIGH within D+1..D+N - entry) / entry` → max potential gain
   - **SELL:** `(entry - min LOW within D+1..D+N) / entry` → max potential drop (positive = correct)
   - **HOLD:** `(close D+N - entry) / entry` → period return
5. Hit rate:
   - BUY: hit if return > 0 (price went above entry at any point)
   - SELL: hit if return > 0 (price went below entry at any point)
   - HOLD: hit if return > -2% (didn't crash)
6. Aggregate by phase+action combo → leaderboard
7. Store in `backtest_cache` table as JSON

### Schedule

- Auto: 18:00 WIB daily (after backfill at 17:00)
- Manual: `/api/backtest?days=30&run=1` or `/admin/trigger-backtest?days=30&secret=...`

### ⚠️ KNOWN BUG: Backtest Not Executing

**Status:** The backtest does not run when triggered. Logs show no activity. The signal queue mechanism (`_backtest_request`) is implemented but may have a timing or initialization issue. Needs debugging:

1. Check if `_backtest_request` is being set to "pending" correctly
2. Check if the main loop's backtest check is being reached
3. Possible issue: `_backtest_request` is defined AFTER `get_backfill_status()` in the file — the main loop may not see it if the import order is wrong
4. Possible issue: the nightly auto-backtest condition `backfill_done_today` may never be True if backfill didn't run that day

**To debug:** Add logging in the main loop before the backtest check:
```python
log.info(f"Backtest check: status={_backtest_request['status']}")
```

---

## 9. API Endpoints (auth required)

| Endpoint | Description |
|----------|-------------|
| `/api/ihsg` | IHSG price + gain% (Yahoo, 5min cache) |
| `/api/last-date` | Most recent date with data |
| `/api/flow?date_from=&date_to=&sector=` | SM/BM/MF aggregated per ticker from eod_summary + phase/action on-the-fly |
| `/api/gains?tickers=BBRI,EMAS&date_from=&date_to=` | Batch Yahoo gain/price (async from frontend) |
| `/api/transactions?ticker=BBRI&date_from=&date_to=` | Raw SM/BM rows for a ticker |
| `/api/overlay?ticker=BBRI&tf=1h` | Cumulative CM/SM/BM per candle bucket |
| `/api/ohlcv?ticker=BBRI&tf=1D` | Yahoo OHLCV candlestick data |
| `/api/sector?date_from=&date_to=` | Sector-level aggregation from eod_summary |
| `/api/backtest?days=30` | Read cached backtest results |
| `/api/backtest?days=30&run=1` | Trigger new backtest + return status |
| `/api/backtest?status=1` | Check backtest running status |

---

## 10. Admin Endpoints (secret required)

| Endpoint | Description |
|----------|-------------|
| `/admin` | Admin control panel page |
| `/admin/upload-db` | Browser UI to upload zenith.db |
| `/admin/download-db` | Download DB for local backup |
| `/admin/pull-db` | Pull DB from Dropbox |
| `/admin/upload-session` | Browser UI to upload session_joker.session |
| `/admin/scraper-status` | JSON: thread alive, latest dates, row counts, backfill/rebuild/backtest status |
| `/admin/scraper-weekly?days=7` | Queue N-day backfill (signal-based) |
| `/admin/rebuild-summary` | Queue full EOD summary rebuild (signal-based) |
| `/admin/trigger-backtest?days=30` | Queue backtest (signal-based) |
| `/admin/analytics` | JSON: active users, total views, daily views |

---

## 11. Frontend Pages

### Design System

```css
--bg:#080c10  --surface:#0e1318  --surface2:#121920
--border:#1a2230  --border2:#243040
--accent:#00e8a2  --accent2:#4d9fff  --danger:#ff4d6a
--text:#c8d8e8  --muted:#4a6070
Fonts: Space Mono (data), DM Sans (body)
```

### Pages

**login.html** — Terminal theme, scanline bg, "ACCESS GRANTED" animation

**hub.html** — Landing. IHSG + clock + Total SM. 3 nav cards. Onboarding spotlight on first visit (localStorage).

**chart.html** — Fullscreen Lightweight Charts v4. TF 5m/15m/30m/1h/1D. Overlay CM/SM/BM toggles. L/A scale. Yahoo OHLCV. Transactions panel with Pikaday. Chart destroyed+recreated on TF switch.

**flow.html** — Main data table. 13 columns: TICKER | PRICE | TX | CLEAN MONEY | SM VAL | BM VAL | RSM | MF+ | MF- | NET MF | GAIN% | PHASE | ACTION. Multi-sort. CM bar visualization. RSM gradient. Sector filter. Dropdown FILTER button (checkboxes for phase+action, CLEAR ALL). Modal popup chart. Async gain loading. Info modal with full guide including Wyckoff phase explanations.

**sector.html** — 11 sector cards (3/2/1 col responsive). Click → inline detail. Sortable table. Modal chart.

**admin.html** — 4 cards: Database (upload/pull/download), Session (upload), Scraper (status panel auto-refresh 5s, manual backfill, rebuild summary), Analytics (active users, total views, bar chart). Mascot character (base64 embedded), bounce animation, contextual chat bubbles.

**backtest.html** — Days input + RUN BACKTEST button. Summary strip (signals, tickers, period, computed time). Leaderboard table: # | PHASE | ACTION | SIGNALS | HIT 1D/3D/5D | AVG RET 1D/3D/5D. Sortable. Medal emoji for top 3. Hit rate color coding (green ≥60%, yellow ≥45%, red <45%).

### Responsive

Breakpoints: 768px (tablet) + 420px (phone). Flow/sector tables scroll horizontally. Modals fullscreen on mobile. Stats bars use CSS grid on mobile.

---

## 12. Overlay System

Backend `/api/overlay`: Buckets transactions by TF, cumulative CM/SM/BM. Default: daily reset (intraday resets at new day).

Frontend: 3 LineSeries on hidden priceScale('overlay'). Carry-forward fill (every candle gets a point). Snap to nearest candle timestamp.

---

## 13. Chart Technical Details

- Gain%: Yahoo-style `(close - prevClose) / prevClose` not `(close - open) / open`
- 150 bar view: `setVisibleLogicalRange` with double rAF
- TF switch: destroy + recreate chart (not reuse)
- Name fallback: `longName → shortName → ticker`
- TX: `COUNT(*)` not `SUM(tx_count)` — signal count, not micro-tx
- IHSG: last 2 valid closes from range=10d (not regularMarketPrice)
- Yahoo direct HTTP with browser User-Agent headers (yfinance library blocked on Railway)

---

## 14. Sector Dictionary

11 sectors, 962 tickers. Defined identically in `app.py` (Python) and `flow.html` (JS for sector filter).

```
Energy(92), Basic Materials(113), Industrials(65), Consumer Non-Cyclicals(132),
Consumer Cyclicals(164), Healthcare(38), Financials(110), Property(92),
Technology(48), Infrastructure(69), Transport(39)
```

---

## 15. Telegram Configuration

| Parameter | Value |
|-----------|-------|
| Group ID | `-1002717915373` |
| Topic SM | `192528` |
| Topic BM | `219042` |
| Topic MF+ | `1025256` |
| Topic MF- | `1025260` |
| API ID | `31708652` |
| API Hash | `052aedc345c0d8dd864febaafae8eb93` |
| Session | `/data/session_joker.session` |

---

## 16. Railway Deployment

### Env Vars

```
ACCESS_KEY=zenith2026
FLASK_SECRET=<random>
DB_PATH=/data/zenith.db
UPLOAD_SECRET=zenith2026
SCRAPER_ENABLED=1
TG_API_ID=31708652
TG_API_HASH=052aedc345c0d8dd864febaafae8eb93
TG_SESSION_PATH=/data/session_joker
```

### Persistent Volume: `/data/`

Contains: `zenith.db`, `session_joker.session`

### First Deploy Checklist

1. Set env vars
2. Deploy
3. Upload session via `/admin/upload-session`
4. Restart service
5. Verify: `/admin/scraper-status?secret=zenith2026` → `thread_alive: true`
6. Rebuild summary: `/admin/rebuild-summary?secret=zenith2026`
7. Wait for completion in scraper-status

---

## 17. Key Bug Fixes History

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Chart X axis cutoff | autoSize:true in flex | Explicit size + ResizeObserver |
| 150 bar broken on TF switch | LWC state persists | Destroy + recreate |
| Overlay gaps | Only transaction candles had data | Carry-forward fill |
| IHSG 0% gain | regularMarketPrice = current day | Use last 2 valid closes |
| Gain% differs from Yahoo | (close-open)/open | (close-prevClose)/prevClose |
| Slow 5-10s load | Yahoo blocks response | Async gains via /api/gains |
| Empty emiten name (AYAM) | longName null | Fallback chain |
| TX count too high | SUM(tx_count) | COUNT(*) |
| latest_data wrong date | MAX(date) on DD-MM-YYYY | substr ordering |
| DB locked on backfill | HTTP thread + scraper both write | Signal queue pattern |
| Gunicorn timeout | Long task in HTTP handler | Non-blocking signal |
| eod_summary wrong schema | Old table from db_setup.py | DROP + recreate if mismatch |
| get_scraper_db no row_factory | Missing sqlite3.Row | Added row_factory |
| 2 scraper threads | 2 gunicorn workers each start scraper | Lock file /tmp/ |
| Missing tickers (BRRC) | Emoji ⭐️ not in regex | Added ⭐ + \uFE0F to TX_EMOJI |
| MES always 0 | price_change_pct NULL in DB | Compute on-the-fly from Yahoo gain% |
| PADI wrong phase (ABSORB not SOS) | DB price_change NULL, fallback hit ABSORB | Phase refinement layer in app.py using gain% |
| Phase/action "—" everywhere | catch-all too loose | Tier 3 catch-all for every ticker |
| ACCUM noise (16k signals) | CM > 0 = catch-all | Require RSM > 60% + SRI > 1.0 |
| UPTHRUST noise (18k signals) | RPR > 0.5 too loose | Require RSM < 40% + RPR > 0.6 |
| SOS too easy | SRI > 1.0 | Raised to SRI > 3.0 |
| Backtest returns wrong | Close-to-close return | OHLCV: entry at OPEN D+1, return vs HIGH/LOW |
| RPR description wrong | Called "retail participation" | Corrected to "sell pressure ratio" — BM = big player selling, not retail |

---

## 18. KNOWN BUG — Backtest Not Executing

**Symptom:** User clicks RUN BACKTEST, request appears queued, but nothing happens. No log output from backtest engine.

**Likely causes:**

1. **Import order:** `_backtest_request` dict and `request_backtest()` function are defined at the very end of `scraper_daily.py` (after the backtest engine section). The main loop references them but they may not be visible if the module structure has issues.

2. **Main loop check location:** The backtest check was added inside the `while True` loop but may be after an `await asyncio.sleep(5)` that prevents it from being reached in time.

3. **Signal queue not polled:** The main loop checks `_backtest_request["status"] == "pending"` but if the variable is not properly shared between the HTTP thread and scraper thread, the change may not be visible.

**Debugging steps:**
- Add `log.info(f"Loop tick: bt={_backtest_request['status']}")` at the top of the while loop
- Verify `_backtest_request` is module-level (not inside a function)
- Check if `run_backtest()` itself crashes silently (wrap in try/except with logging)
- Test `run_backtest()` directly: add a `/admin/test-backtest` endpoint that calls it in HTTP thread (just for debugging, will timeout but should produce logs)

---

## 19. Development Principles

- **`mf_delta_numeric`** is the correct source for SM/BM VAL — NOT `value_numeric`
- **DD-MM-YYYY strings sort wrong** — always use `substr(date,7,4)||substr(date,4,2)||substr(date,1,2)`
- **TX = `COUNT(*)`** not `SUM(tx_count)` — count signals not micro-transactions
- **flow.html and sector.html share modal chart code** — changes must be applied to BOTH
- **Phase logic exists in 3 places** — app.py, _classify_phase(), _compute_phase_action() — KEEP IN SYNC
- **Yahoo Finance**: use direct HTTP with browser headers, NOT yfinance library (blocked on Railway)
- **Surgical edits only** — Machi has custom modifications, don't rewrite entire files unless asked
- **Test data formats first** — verify Telegram message format before building parsers
- **Signal queue for everything** — never run long tasks in HTTP handlers
