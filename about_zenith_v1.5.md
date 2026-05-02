# ZENITH v1.5 — Smart Money Intelligence Platform for IDX

**Platform:** Indonesian Stock Exchange (IDX) Smart Money & Bad Money tracking  
**Version:** 1.5 (April 2026)  
**Status:** Active deployment on Railway · Hybrid development  
**Tech Stack:** Python Flask, SQLite (WAL), Telethon, Lightweight Charts v4, Pikaday  
**Live:** `zenith-production-bbb6.up.railway.app`

---

## TABLE OF CONTENTS

1. [Project Definition](#1-project-definition)
2. [System Architecture](#2-system-architecture)
3. [Data Pipeline & Scraper](#3-data-pipeline--scraper)
4. [Core Logic & Algorithms](#4-core-logic--algorithms)
5. [Database Schema](#5-database-schema)
6. [Feature Set](#6-feature-set)
7. [UI/UX Design](#7-uiux-design)
8. [API Reference](#8-api-reference)
9. [Development Guidelines](#9-development-guidelines)

---

## 1. PROJECT DEFINITION

### What is Zenith?

Zenith is a **Bandarmologi-based trading intelligence platform** that tracks institutional/big-player activity on IDX stocks. It applies Wyckoff methodology to detect accumulation (buying), distribution (selling), and neutral phases in real time.

### Core Concept: Smart Money vs Bad Money

- **Smart Money (SM):** Institutional players actively BUYING (accumulating positions)
- **Bad Money (BM):** Institutional players actively SELLING (distributing/exiting)
- **Smart Money Ratio (RSM):** % of transaction value coming from SM vs total
- **Signal:** Daily Wyckoff phase classification + action recommendation (BUY/SELL/HOLD)

### Data Source

Data comes from a **private Telegram group** called "Tools Smart Trader" (BST). A Telegram bot called "Joker" scrapes and posts SM/BM signals from specific forum topics in real time. Zenith listens to these signals 24/7 and processes them into trading insights.

### User Profile

**Machi** — CS student at Tamkang University, Taiwan. Active IDX trader. Father originated several systematic trading methodologies. Prefers surgical code edits, minimal-touch changes, and has strong opinions on trading logic correctness.

---

## 2. SYSTEM ARCHITECTURE

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        ZENITH PLATFORM                          │
├──────────────────────┬──────────────────┬──────────────────────┤
│  TELEGRAM LAYER      │   PROCESSING     │    DISPLAY LAYER     │
├──────────────────────┼──────────────────┼──────────────────────┤
│                      │                  │                      │
│ • Joker Bot          │ • Phase Logic    │ • Flask Web Server   │
│ • Telethon Client    │ • EOD Analytics  │ • RESTful API        │
│ • Real-time Signal   │ • Price History  │ • HTML UI Templates  │
│   Listener           │   Tracking       │ • Chart Visualization│
│                      │ • Backtest Sim   │                      │
└──────────────────────┼──────────────────┼──────────────────────┘
                       │
                   SQLite DB
                  (/data/zenith.db)
```

### Railway Deployment Architecture

```
Railway Service (Single container, 1GB RAM limit)
├── Gunicorn (2 workers)
│   ├── Worker 1: HTTP server (Flask) + Admin functions
│   └── Worker 2: Standby (load balancer ready)
│
├── Scraper Daemon Thread (started on boot)
│   ├── Telethon Client — Persistent connection to Telegram
│   ├── Real-time Listener — Monitors 4 Telegram topics 24/7
│   ├── Daily Backfill — 17:00 WIB EOD summary computation
│   ├── Weekly Backtest — 18:00 WIB (30-day simulation)
│   └── Signal Queue — Accepts manual backfill/rebuild requests via HTTP
│
└── SQLite Database (WAL mode, auto-checkpoint)
    └── ~/data/zenith.db (~120-150 MB with 1+ years history)
```

### File Structure

```
zenith_web/
├── app.py                        (~1400 lines)
│   ├── Authentication (OAuth flow)
│   ├── Flask routes (13 templates + 9 APIs)
│   ├── Real-time API endpoints
│   └── Imports: logic.py (phase classification)
│
├── logic.py                      (~400 lines) ★ CORE LOGIC
│   ├── classify_zenith_v3_1()    — Phase classification (SOHO, SPRING, ABSORB, etc.)
│   ├── get_action()              — Action signal + Gate A/B/C safety gates
│   ├── get_watch_flag()          — ARB panic detection
│   ├── detect_trade_detail_gate()— Trade Detail specific gate logic
│   ├── compute_ma()              — Moving averages (5, 13, 34, 200)
│   ├── compute_rsi14()           — RSI-14 calculation
│   └── compute_cm_streak()       — Consecutive momentum tracker
│
├── scraper_daily.py              (~1550 lines)
│   ├── Telegram parsers (SM/BM/MF+/MF- signals)
│   ├── SQLite schema + migrations
│   ├── EOD summary aggregation (17:00 WIB)
│   ├── Analytics computation (RSM, SRI, RPR, etc.)
│   ├── Price history sync from Yahoo Finance
│   ├── Backtest engine (30-day simulation)
│   ├── Signal queue handlers
│   └── Imports: logic.py (for phase computation)
│
├── scraper_weekly.py             (~165 lines)
│   ├── N-day backfill from Telegram archives
│   └── Weekly reconstruction of historical data
│
├── requirements.txt              (Flask, Telethon, Requests, etc.)
├── Procfile                      (Gunicorn command for Railway)
│
├── templates/
│   ├── login.html                — OAuth login page
│   ├── index.html                — Dashboard hub with spotlight tours
│   ├── chart.html                — Real-time stock chart (Lightweight Charts)
│   ├── flow.html                 — (★) Trade Detail card display
│   ├── sector.html               — Sector grouping + heat map
│   ├── backtest.html             — Backtest results leaderboard
│   ├── kompas100.html            — KOMPAS 100 index view
│   ├── admin.html                — Admin panel (analytics, settings)
│   └── (legacy: trade_detail/)   — Trade Detail UI components
│
├── static/
│   ├── animations.js             — UI animations + transitions
│   └── shortcuts.js              — Keyboard shortcuts
│
├── trade_detail/                 — Trade Detail System
│   ├── TRADE_DETAIL_CATALOG.md   — v3.1 Narrative specification (56 combos)
│   └── (UI components in flow.html)
│
├── algo/
│   ├── zenith_algorithm_v3.md    — Phase classification specs
│   ├── zenith_algorithm_v3_1.md  — Current algorithm + gates
│   └── (historical versions v1, v2, v2.1)
│
└── graphify-out/
    ├── graph.json                — Code knowledge graph
    ├── graph.html                — Graph visualization
    └── GRAPH_REPORT.md           — Community structure analysis
```

---

## 3. DATA PIPELINE & SCRAPER

### Real-Time Telegram Listener

**Trigger:** Signal posted in Telegram "Tools Smart Trader" group → Joker bot posts to 4 topics:
- `#signal-buy` — SM accumulation (SPRING, ABSORB, ACCUM, SOS)
- `#signal-sell` — BM distribution (UPTHRUST, DISTRI)
- `#mf-plus` — Micro-Flow positive (minor buying)
- `#mf-minus` — Micro-Flow negative (minor selling)

**Processing:**
```
Signal arrives → Telethon listener captures → Parse ticker, values, timestamp
→ Check SQLite for existing data → Insert or update tx record
→ Trigger EOD summary recomputation (if after 17:00 WIB)
```

### Daily EOD Summary (17:00 WIB)

**Execution:** Every trading day at 17:00 WIB, `compute_analytics_for_date()` runs:

1. **Aggregation** — Sum all SM/BM transactions for the day
2. **Price sync** — Fetch daily OHLC from Yahoo Finance
3. **Moving Averages** — Compute MA5, MA13, MA34, MA200
4. **Technical Indicators:**
   - RSI-14 (Wilder's method)
   - RSM (Smart Money %)
   - SRI (SM Relative Intensity using trimmed mean)
   - RPR (Sell Pressure Ratio = BM tx count / total tx)
   - ATR % (Average True Range percentage)
5. **Phase Classification** — Call `classify_zenith_v3_1()` from logic.py
6. **Action Signal** — Call `get_action()` with safety gates (Gate A, B, C)
7. **Trade Detail Narrative** — Determine MA structure type (8 types) + narrative (56 combos)
8. **Database update** — Write to `eod_summary` table

### Price History Tracking

**Why?** Backtest needs historical price data. Yahoo Finance may not have real-time granularity.

**Implementation:**
- `price_history` table stores every trading day's OHLC
- Synced daily via Yahoo Finance HTTP requests
- Used for backtest simulations and historical analysis
- Fallback: If Yahoo is unavailable, use previous day's close

### Weekly Backfill (scraper_weekly.py)

**Purpose:** Reconstruct historical SM/BM data from Telegram archives if scraped data is missing.

**Usage:** Manual trigger via `/api/request-backfill` endpoint → Signal queue → Runs in scraper thread

---

## 4. CORE LOGIC & ALGORITHMS

### 4.1 Phase Classification (v3.1)

**Single source of truth:** `logic.py:classify_zenith_v3_1()`

**Inputs:**
- `sri` — SM Relative Intensity (ratio of today's SM to 10-day trimmed mean)
- `rsm` — SM Ratio (% of daily value that is SM)
- `rpr` — Sell Pressure Ratio (BM tx count / total tx)
- `pchg` — Daily price change % (None = unknown)
- `bm_val` — Today's BM value (Juta)
- `bm_sma10` — 10-day average BM value (0 = no history)
- `atr_pct` — Average True Range % (None = use 2.5% default)

**Output:** Phase label (7 phases)

```
SOS     — Sign of Strength (SM surge, price up)
SPRING  — Spring (price down, SM accumulating)
ABSORB  — Absorption (SM high, price flat)
ACCUM   — Accumulation (steady SM buying)
UPTHRUST— Trap (price up, BM dominates = jebakan)
DISTRI  — Distribution (BM surge = exit)
NEUTRAL — No clear signal
```

**Classification Tree:**

```
if pchg = None:
    → NEUTRAL

if pchg > th_up AND (rsm > 65 & sri > 3.0) OR (rsm > 60 & sri > 4.0):
    → SOS (v3.1: OR clause allows lower RSM if SRI extremely high)

if pchg > th_up AND rsm < 40 AND rpr > 0.6:
    → UPTHRUST (price up but BM dominates = trap)

if sri > 2.0 AND rsm > 65 AND pchg > -th_down AND abs(pchg) < th_flat:
    → ABSORB (SM very active, price barely moves)

if pchg < -th_down AND rsm > 60 AND sri > 1.5:
    → SPRING (price down, SM accumulating)

if rsm < 40 AND pchg < -(th_down * 0.5) AND rpr > 0.4 AND bm_gate:
    → DISTRI (BM actively selling)

if rsm > 60 AND sri > 1.0:
    → ACCUM (steady SM presence)

else:
    → NEUTRAL
```

**Thresholds (dynamic based on ATR):**
- `th_up` = max(atr × 0.8, 1.0)    — significant upward move
- `th_down` = max(atr × 0.4, 0.5)  — significant downward move
- `th_flat` = atr × 0.5             — flat zone (no significant move)

### 4.2 Action Signal with Safety Gates

**Function:** `logic.py:get_action(phase, pchg, atr_pct, bm_val, bm_sma10, watch_flag)`

**Output:** BUY, SELL, or HOLD

```
BUY phases:   SOS, SPRING, ABSORB, ACCUM
SELL phases:  UPTHRUST, DISTRI
HOLD phases:  NEUTRAL (and any BUY blocked by gates)
```

**Safety Gates (v3.1):**

| Gate | Trigger | Action | Narrative |
|------|---------|--------|-----------|
| **Gate A** | `bm_val > bm_sma10 × 3.0` | Force HOLD | Abnormal selling pressure (tembok penjual) |
| **Gate B** | `watch_flag == "ARB_SPRING"` | Force HOLD | Extreme panic drop (>1.5× ATR) |
| **Gate C** | `pchg >= max(atr×2.0, 5.0)` | Force HOLD | Price overextended (Profit Taking Zone) |

**Gate Priority:** A > C (if both active, Gate A wins — supply risk is more urgent)

**Gate C Threshold (v3.1):**
- SOS phase allowed higher: `max(atr × 3.5, 7.0)`
- Other BUY phases stricter: `max(atr × 2.0, 5.0)`

### 4.3 Smart Money Intensity (SRI)

**Purpose:** Measure today's SM activity relative to recent history

**Calculation (Trimmed Mean):**
```python
sm_history = [SM values last 10 trading days, only if > 0, in 20-day window]

if len(sm_history) >= 3:
    vals = sorted(sm_history)
    trimmed = vals[:-1]  # remove top outlier
    sm_sma10 = sum(trimmed) / len(trimmed)
else:
    sm_sma10 = sum(sm_history) / len(sm_history) if sm_history else 0

SRI = sm_val_today / sm_sma10 if sm_sma10 > 0 else 0
```

**Why trimmed mean?**
- Eliminates outlier events (rights issue, RUPS, rumor → SM spike)
- Outlier day (500M SM) pollutes 10-day SMA, causing false negatives next days
- Trimmed mean = more stable, realistic intensity baseline

### 4.4 MA Structure Classification (v3.1)

**8 Structure Types** (per Trade Detail Catalog v3.1)

**Algorithm:**
```
gap = (max(MA5,MA13,MA34) - min(MA5,MA13,MA34)) / min(MA5,MA13,MA34) × 100
above_ma200 = (ma200 is None) OR (price > ma200)

if gap < 3%:
    → "Cluster on Macro Uptrend" (if above MA200)
    → "Cluster on Macro Downtrend" (if below MA200)

else if gap ≥ 3% AND MA5 > MA13 > MA34:  # aligned up
    → "Strong Uptrend" (if above MA200)
    → "Transitional Uptrend" (if below MA200)

else if gap ≥ 3% AND MA5 < MA13 < MA34:  # aligned down
    → "Transitional Correction" (if above MA200)
    → "Strong Downtrend" (if below MA200)

else:  # MA5/13/34 are crossed/messy
    → "Bullish Messy" (if above MA200)
    → "Bearish Messy" (if below MA200)
```

### 4.5 Trade Detail Narratives (56 Combinations)

**Source:** `trade_detail/TRADE_DETAIL_CATALOG.md` (v3.1)

**Matrix:** 8 Structures × 7 Phases = 56 narratives + 3 Gate overrides

**Example Entry:**
```
Strong Uptrend + SOS = "Strongest Momentum — Smart Money sangat agresif di tengah tren yang sudah kuat..."

Cluster on Macro Uptrend + SPRING = "Shakeout dalam Konsolidasi — Harga turun sementara keluar dari cluster..."
```

**Anti-Hallucination Rule:**
- If combo not in catalog → return `[NARASI TIDAK DITEMUKAN - HARAP LAMPIRKAN DATABASE TRADE DETAIL]`
- Prevents AI from generating plausible-sounding but wrong narratives

---

## 5. DATABASE SCHEMA

### Main Tables

#### `eod_summary` (Core analytics table)

```sql
CREATE TABLE eod_summary (
    id INTEGER PRIMARY KEY,
    ticker TEXT,
    date TEXT,              -- YYYY-MM-DD
    open_price REAL,
    close_price REAL,
    high_price REAL,
    low_price REAL,
    sm_val REAL,            -- Smart Money value (Juta)
    bm_val REAL,            -- Bad Money value (Juta)
    mf_plus REAL,           -- Micro Flow + (Juta)
    mf_minus REAL,          -- Micro Flow - (Juta)
    rsm REAL,               -- Smart Money % (0-100)
    sri REAL,               -- SM Relative Intensity
    rpr REAL,               -- Sell Pressure Ratio (0-1)
    pchg REAL,              -- Price change %
    atr_pct REAL,           -- ATR as % of price
    ma5 REAL,
    ma13 REAL,
    ma34 REAL,
    ma200 REAL,
    rsi14 REAL,             -- RSI-14
    phase TEXT,             -- SOHO, SPRING, ABSORB, ACCUM, UPTHRUST, DISTRI, NEUTRAL
    action TEXT,            -- BUY, SELL, HOLD
    watch_flag TEXT,        -- ARB_SPRING, etc.
    ma_structure TEXT,      -- 8-type classification
    trade_gate TEXT,        -- Gate A, Gate B, Gate C, or None
    narrative TEXT,         -- Trade Detail narrative
    cm_streak INT,          -- Consecutive Momentum (days above/below MA5)
    UNIQUE(ticker, date)
);
```

#### `transactions` (Raw signal log)

```sql
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    ticker TEXT,
    signal_type TEXT,       -- SM, BM, MF+, MF-
    value REAL,             -- Juta
    timestamp DATETIME,
    source TEXT             -- telegram_signal, backfill, etc.
);
```

#### `price_history` (OHLC data)

```sql
CREATE TABLE price_history (
    ticker TEXT,
    date TEXT,              -- YYYY-MM-DD
    open REAL, high REAL, low REAL, close REAL,
    volume INTEGER,
    PRIMARY KEY (ticker, date)
);
```

#### `backtest_results` (Simulation history)

```sql
CREATE TABLE backtest_results (
    id INTEGER PRIMARY KEY,
    ticker TEXT,
    backtest_date TEXT,     -- when backtest ran
    start_date TEXT,        -- YYYY-MM-DD
    end_date TEXT,
    initial_capital REAL,
    final_balance REAL,
    win_count INT,
    loss_count INT,
    win_rate REAL,
    max_drawdown REAL,
    trades_json TEXT        -- JSON array of trades
);
```

---

## 6. FEATURE SET

### Core Features

#### 1. Real-Time Smart Money Tracking
- Live Telegram signal listener (24/7)
- Instant parsing of SM/BM/MF+/MF- transactions
- Database insert + EOD aggregation

#### 2. Wyckoff Phase Classification
- 7-phase system (SOS, SPRING, ABSORB, ACCUM, UPTHRUST, DISTRI, NEUTRAL)
- Phase + Action + Watch Flag computation
- Safety gates to prevent false signals

#### 3. Trade Detail Intelligence
- 8 MA structure types + price levels
- 56 combination narratives (Catalog v3.1)
- Individual MA trend stamps (Uptrend/Downtrend/Sideways)
- RSI levels (Overbought/Neutral/Oversold)
- Gate-specific override narratives

#### 4. Technical Analysis
- Moving Averages (5, 13, 34, 200)
- RSI-14 (Wilder's method)
- ATR (Average True Range)
- Consecutive Momentum tracker (CM streak)

#### 5. Multi-Stock Dashboard
- Real-time price charts (Lightweight Charts v4)
- Sector grouping + heat maps
- KOMPAS 100 index tracking
- Live search (ticker lookup)

#### 6. Backtest Engine
- 30-day rolling simulations
- Win/loss statistics
- Drawdown analysis
- Trade-by-trade journal

#### 7. Admin Panel
- Manual backfill triggers
- Cached data invalidation
- Analytics dashboard
- Settings management

#### 8. OAuth Authentication
- Login via configured OAuth provider
- Session management
- Admin role separation

### Advanced Features

#### Trade Detail Expansion
- Detailed narrative for each stock
- Gate-specific warnings (Abnormal Supply, Extreme Panic, Profit Taking)
- Individual MA + RSI stamp visualization
- Phase + action tracking

#### Historical Data Replay
- Yahoo Finance price sync
- Telegram archive backfill
- Re-compute phases for past dates
- Forensic analysis capability

#### Mobile-Responsive UI
- Touch-friendly charts
- Responsive layout (tablets, phones)
- Spotlight onboarding tours

---

## 7. UI/UX DESIGN

### Navigation Structure

```
Zenith Dashboard
├── Hub (index.html)
│   ├── Spotlight onboarding tours
│   ├── Recent trades list
│   ├── Today's phase summary
│   └── Quick search (ticker)
│
├── Chart (chart.html)
│   ├── Real-time OHLC chart (Lightweight Charts v4)
│   ├── Overlay system (phase badges, gates, narratives)
│   ├── Date range selector
│   └── Trade Detail card (★ NEW)
│
├── Flow (flow.html)
│   ├── Trade Detail full view
│   ├── Phase + Action columns
│   ├── MA structure + narratives (8×7 matrix)
│   ├── Gate warnings
│   ├── RSI + MA stamps
│   └── Price history table
│
├── Sector (sector.html)
│   ├── Sector grouping (IT, Finance, Energy, etc.)
│   ├── Heat map (green = BUY, red = SELL)
│   ├── Ticker links
│   └── Quick filter
│
├── KOMPAS 100 (kompas100.html)
│   ├── Index chart
│   ├── Constituent ranking
│   └── Sector breakdown
│
├── Backtest (backtest.html)
│   ├── Results leaderboard (top performers)
│   ├── Trade journal (individual trades)
│   ├── Win/loss stats
│   └── Drawdown curves
│
└── Admin (admin.html)
    ├── Backfill triggers
    ├── Analytics dashboard
    ├── Settings
    └── Mascot easter egg
```

### Design System

#### Color Palette
- **Bullish:** Green (#00e8a2 — MA Uptrend highlight)
- **Bearish:** Red (#ff6b6b — MA Downtrend highlight)
- **Neutral:** Gray (#aab — Sideways/Cluster)
- **Warning:** Orange (#ffc850 — Messy structures, Profit Taking)
- **Danger:** Dark Red (#ff5050 — Bearish Messy, extreme risk)

#### Typography
- **Monospace:** "Space Mono" (badges, numbers, code)
- **Sans-serif:** System default (UI text)
- **Size:** 10px (badges), 12px (labels), 14px (body)

#### Component Library
- **Badges:** Phase label, action label, MA structure label (8 types)
- **Cards:** Trade Detail card (responsive, expandable)
- **Tooltips:** Hover for gate explanations, narrative preview
- **Modals:** Settings, confirmation dialogs
- **Charts:** Lightweight Charts v4 (candlestick, volume overlay)

#### Trade Detail UI (flow.html)

**Structure:**
```
┌─────────────────────────────────────────┐
│ Ticker: BBRI | Date: 2026-05-02         │
├─────────────────────────────────────────┤
│ Phase: SOS | Action: BUY | Gate: None   │
├─────────────────────────────────────────┤
│ MA Structure: Strong Uptrend             │
│ Narrative: "Strongest Momentum — SM     │
│ sangat agresif di tengah tren..."      │
├─────────────────────────────────────────┤
│ RSI: 72 (Overbought)                    │
├─────────────────────────────────────────┤
│ MA VALUES (with individual stamps):     │
│ ↑ MA5: 5,100   | ↑ MA13: 5,000         │
│ ↑ MA34: 4,850  | ↑ MA200: 4,600        │
├─────────────────────────────────────────┤
│ Price: 5,200 | pchg: +3.2% | ATR: 2.1% │
└─────────────────────────────────────────┘
```

**Key Design Choices:**
- Individual MA stamps placed LEFT of values (no emoji, just symbols: ↑ ↓ =)
- RSI label ONLY: Overbought (>70), Neutral (30-70), Oversold (<30)
- Gate narratives in expandable section (below main narrative)
- Price history table at bottom (scrollable, last 20 days)

---

## 8. API REFERENCE

### Authentication
- **Endpoint:** `/auth/login`
- **Method:** POST
- **Body:** `{code: oauth_code, state: oauth_state}`
- **Response:** `{ok: true, token: session_id}`

### Real-Time APIs

#### GET `/api/flow/<ticker>/<date_str>`
**Returns:** Full Trade Detail for ticker on date
```json
{
  "ticker": "BBRI",
  "date": "2026-05-02",
  "phase": "SOS",
  "action": "BUY",
  "ma_structure": "Strong Uptrend",
  "narrative": "Strongest Momentum — ...",
  "trade_gate": null,
  "ma_structure_narrative": "...",
  "rsi14": 72,
  "ma5": 5100, "ma13": 5000, "ma34": 4850, "ma200": 4600,
  "price": 5200,
  "pchg": 3.2,
  "atr_pct": 2.1
}
```

#### GET `/api/summary/<ticker>/<date_str>`
**Returns:** EOD summary for date
```json
{
  "ticker": "BBRI",
  "date": "2026-05-02",
  "open": 5150, "high": 5250, "low": 5100, "close": 5200,
  "sm_val": 450, "bm_val": 120,
  "rsm": 79, "sri": 3.8, "rpr": 0.25,
  "phase": "SOS", "action": "BUY"
}
```

#### GET `/api/history/<ticker>?days=20`
**Returns:** Last N days OHLC + phases
```json
[
  {"date": "2026-05-02", "open": 5150, "close": 5200, "phase": "SOS", ...},
  {"date": "2026-05-01", "open": 5080, "close": 5140, "phase": "ACCUM", ...}
]
```

#### GET `/api/backtest/<ticker>`
**Returns:** Last backtest results
```json
{
  "ticker": "BBRI",
  "backtest_date": "2026-05-02T18:00:00",
  "start_date": "2026-04-02",
  "end_date": "2026-05-02",
  "initial_capital": 10000000,
  "final_balance": 10850000,
  "win_rate": 0.65,
  "max_drawdown": 0.12,
  "trades": [...]
}
```

### Admin APIs

#### POST `/api/request-backfill`
**Queues:** Manual Telegram archive backfill
**Body:** `{ticker: "BBRI", from_date: "2026-04-01", to_date: "2026-05-02"}`
**Response:** `{ok: true, queued: true}`

#### POST `/api/request-rebuild`
**Queues:** Full recalculation of analytics (recompute all phases)
**Response:** `{ok: true, status: "running"}`

#### GET `/admin/status`
**Returns:** Scraper daemon status, queue state, last update times

---

## 9. DEVELOPMENT GUIDELINES

### Code Organization Principles

#### Single Source of Truth (DRY)

**CRITICAL:** Phase logic lives in `logic.py` only. Never duplicate.

| Component | Import Source |
|-----------|---------------|
| Phase classification | `logic.classify_zenith_v3_1()` |
| Action signal | `logic.get_action()` |
| Watch flag | `logic.get_watch_flag()` |
| Gate detection | `logic.detect_trade_detail_gate()` |

**Bad Example (❌):**
```python
# scraper_daily.py duplicates phase logic
def compute_phase(sri, rsm, rpr, pchg):
    if pchg > 1.0 and rsm > 65:
        return "SOS"
    # ... duplicate classification tree
```

**Good Example (✓):**
```python
# scraper_daily.py delegates to logic.py
from logic import classify_zenith_v3_1
phase = classify_zenith_v3_1(sri, rsm, rpr, pchg, bm_val, bm_sma10, atr_pct)
```

### Adding New Features

#### 1. Phase Narrative Update
- Edit `logic.py:_PHASE_NARRATIVE` dict
- Regenerate `_GATE_NARRATIVES` if gate logic changes
- Update `trade_detail/TRADE_DETAIL_CATALOG.md` (source of truth)
- Commit + PR

#### 2. New Technical Indicator
- Add function to `logic.py` (compute function)
- Call from `scraper_daily.py:compute_analytics_for_date()`
- Add column to `eod_summary` table
- Backfill historical data

#### 3. UI Component Addition
- Create in `templates/` (HTML + inline JS)
- Link to backend API endpoint
- Add CSS to match design system
- Test responsive layout (mobile, tablet, desktop)

### Testing & QA

#### Backtest Validation
Before deploying phase changes:
1. Run 30-day backtest on 5 major stocks
2. Compare win rate vs previous version
3. Check for regression (↓ win rate = ⚠️)
4. Document changes in commit message

#### Manual Spot Checks
- Verify new narratives match actual market conditions
- Cross-check with trader's own analysis
- Ensure gates activate correctly (no false positives)

### Performance Notes

- **Database:** SQLite WAL mode (fast writes, concurrent reads)
- **Scraper:** Single-threaded Telegram listener (no race conditions)
- **Chart:** Lightweight Charts v4 optimized for <50K candles per view
- **Memory:** 1GB limit on Railway — monitor cache sizes

### Deployment Checklist

- [ ] Code reviewed (logic changes only)
- [ ] Backtest passed (win rate stable or improved)
- [ ] No duplicate logic (search for copy-pasted phase code)
- [ ] Database migrations written (if schema changed)
- [ ] API tested manually (hit endpoints, verify responses)
- [ ] UI responsive on mobile (test on 3 screen sizes)
- [ ] Gate narratives verified (cross-check with catalog)
- [ ] Commit message clear (references issue, explains why)
- [ ] PR created + linked to issue
- [ ] Merge to main (squash if many WIP commits)
- [ ] Railway auto-deploys (watch for errors in logs)

---

## APPENDIX: Glossary

| Term | Definition |
|------|-----------|
| **SM** | Smart Money — Institutional buyers (accumulation) |
| **BM** | Bad Money — Institutional sellers (distribution) |
| **RSM** | Smart Money Ratio — % of daily value from SM |
| **SRI** | SM Relative Intensity — Today's SM vs 10-day avg (trimmed) |
| **RPR** | Sell Pressure Ratio — BM tx count / total tx count |
| **Phase** | Wyckoff market phase (7 types) |
| **Action** | Trading recommendation: BUY, SELL, HOLD |
| **Gate** | Safety condition blocking action (A, B, C) |
| **MA Structure** | 8-type classification of moving average alignment |
| **Narrative** | Human-readable explanation of phase + structure |
| **EOD** | End-of-Day (17:00 WIB) summary aggregation |
| **Backtest** | 30-day simulation of trading rules |
| **ATR** | Average True Range — volatility measure |
| **CM Streak** | Consecutive Momentum — days above/below MA5 |
| **ARB** | Auto Rejection Bawah — extreme panic threshold |

---

**Document Version:** 1.5  
**Last Updated:** May 2, 2026  
**Maintainer:** Development Team (Claude Code)  
**Status:** Active | Repository: github.com/machiavellia-lynn/zenith
