# Graph Report - .  (2026-05-02)

## Corpus Check
- 36 files · ~332,116 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 329 nodes · 475 edges · 30 communities detected
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 62 edges (avg confidence: 0.81)
- Token cost: 12,000 input · 3,800 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Flask API Route Handlers|Flask API Route Handlers]]
- [[_COMMUNITY_Data Scraping & Analytics Pipeline|Data Scraping & Analytics Pipeline]]
- [[_COMMUNITY_Zenith Signal Metrics|Zenith Signal Metrics]]
- [[_COMMUNITY_Frontend UI Templates|Frontend UI Templates]]
- [[_COMMUNITY_Wyckoff Phase Safety Gates|Wyckoff Phase Safety Gates]]
- [[_COMMUNITY_Phase Classification Engine|Phase Classification Engine]]
- [[_COMMUNITY_Algorithm Documentation v2.1|Algorithm Documentation v2.1]]
- [[_COMMUNITY_Frontend Animation Functions|Frontend Animation Functions]]
- [[_COMMUNITY_KSPM Investment Competition|KSPM Investment Competition]]
- [[_COMMUNITY_Async Job Queue System|Async Job Queue System]]
- [[_COMMUNITY_Character Decryptor Assets|Character Decryptor Assets]]
- [[_COMMUNITY_UI Design System|UI Design System]]
- [[_COMMUNITY_Project Core Concepts|Project Core Concepts]]
- [[_COMMUNITY_Production Architecture|Production Architecture]]
- [[_COMMUNITY_Kompas100 Transactions|Kompas100 Transactions]]
- [[_COMMUNITY_Ticker Fitness API|Ticker Fitness API]]
- [[_COMMUNITY_Graphify Config|Graphify Config]]
- [[_COMMUNITY_Project README|Project README]]
- [[_COMMUNITY_Flask Dependency|Flask Dependency]]
- [[_COMMUNITY_Gunicorn Dependency|Gunicorn Dependency]]
- [[_COMMUNITY_Telethon Dependency|Telethon Dependency]]
- [[_COMMUNITY_Psycopg2 Dependency|Psycopg2 Dependency]]
- [[_COMMUNITY_Gevent Dependency|Gevent Dependency]]
- [[_COMMUNITY_Requests Dependency|Requests Dependency]]
- [[_COMMUNITY_Telegram Scraper System|Telegram Scraper System]]
- [[_COMMUNITY_API Endpoints|API Endpoints]]
- [[_COMMUNITY_Admin Endpoints|Admin Endpoints]]
- [[_COMMUNITY_Railway Deployment|Railway Deployment]]
- [[_COMMUNITY_Lightweight Charts|Lightweight Charts]]
- [[_COMMUNITY_OHLCV Hover Tooltip|OHLCV Hover Tooltip]]

## God Nodes (most connected - your core abstractions)
1. `is_authed()` - 22 edges
2. `get_db()` - 17 edges
3. `compute_analytics_for_date()` - 15 edges
4. `run_weekly_backfill()` - 13 edges
5. `EOD Summary Aggregation Table` - 13 edges
6. `Phase Classification Algorithm v2` - 12 edges
7. `process_message()` - 11 edges
8. `Hub Page (hub.html)` - 10 edges
9. `Zenith v3.1 Implementation Summary` - 9 edges
10. `flow()` - 8 edges

## Surprising Connections (you probably didn't know these)
- `Zenith Algorithm Guide v2 (algo dir)` --semantically_similar_to--> `Phase Classification Algorithm v2`  [INFERRED] [semantically similar]
  algo/zenith_algorithm_v2.md → ZENITH_ALGORITHM_GUIDE_v2.md
- `Handoff v4 (structure dir)` --semantically_similar_to--> `Zenith Project Overview — Handoff v4`  [INFERRED] [semantically similar]
  structure/ZENITH_HANDOFF_v4.md → ZENITH_HANDOFF_v4.md
- `Redesign Prompt (structure dir)` --semantically_similar_to--> `Zenith UI Design System — Dark Terminal Aesthetic`  [INFERRED] [semantically similar]
  structure/zenith_redesign_prompt.md → zenith_redesign_prompt.md
- `flow()` --calls--> `classify_zenith_v3_1()`  [INFERRED]
  app.py → logic.py
- `flow()` --calls--> `get_watch_flag()`  [INFERRED]
  app.py → logic.py

## Hyperedges (group relationships)
- **Zenith Phase Classification Pipeline — metrics to phases to actions** — algo_guide_v2_SRI, algo_guide_v2_RSM, algo_guide_v2_RPR, algo_guide_v2_ATR, algo_guide_v2_phase_classification, algo_v3_1_get_action [INFERRED 0.90]
- **Phase Logic Must Stay In Sync — 3 compute locations** — handoff_v4_eod_pipeline, algo_guide_v2_backtest_engine, handoff_v4_api_endpoints, algo_v3_1_logic_py [EXTRACTED 1.00]
- **Zenith Data Ingestion — Telegram to EOD Summary to Analytics** — algo_guide_v2_telegram_bot_joker, algo_guide_v2_yahoo_finance, algo_guide_v2_eod_summary, handoff_v4_eod_pipeline [EXTRACTED 1.00]
- **Zenith v3.1 Analytics Computation Pipeline** — impl_summary_ComputeAnalytics, impl_summary_ClassifyV31, impl_summary_GetAction, impl_summary_GetWatchFlag, impl_summary_ComputeMovingAverages, impl_summary_DetectMACross, impl_summary_DetectWeakBreakout [EXTRACTED 1.00]
- **3-Layer Action Safety Gates (Supply + ARB + Anti-Pucuk)** — impl_summary_GetAction, impl_summary_SupplyGate, impl_summary_ARBSafetyGate, impl_summary_AntiPucukGate [EXTRACTED 1.00]
- **Modal Chart + Overlay Toggles Pattern (Sector / Kompas100)** — sector_html_SectorModal, kompas100_html_ModalChart, shared_SmartMoneyBadMoneyOverlay, shared_LightweightCharts [INFERRED 0.85]

## Communities

### Community 0 - "Flask API Route Handlers"
Cohesion: 0.05
Nodes (59): admin_fetch_gains(), admin_fix_date(), api_backtest(), api_close_position(), api_journal(), api_open_position(), api_ticker_fitness(), backtest_page() (+51 more)

### Community 1 - "Data Scraping & Analytics Pipeline"
Cohesion: 0.06
Nodes (59): admin_backfill_prices(), admin_recompute_analytics(), Bulk-fetch Yahoo close prices into eod_summary. 1 request per ticker.      Par, Recompute analytics (gain%, phase, action) for date range after price_close fill, backfill_prices(), check_stop_loss(), close_position(), compute_analytics_for_date() (+51 more)

### Community 2 - "Zenith Signal Metrics"
Cohesion: 0.09
Nodes (32): ATR% — Average True Range Metric, CM — Clean Money Derived Value, MES — Market Efficiency Score Metric, RPR — Rasio Tekanan Jual Metric, RSM — SM Ratio Percentage, SRI — SM Relative Intensity Metric, VWAP BM — Volume-Weighted Average BM Sell Price, VWAP SM — Volume-Weighted Average SM Buy Price (+24 more)

### Community 3 - "Frontend UI Templates"
Cohesion: 0.09
Nodes (31): Hub Page (hub.html), Navigation Cards (Chart / Flow / Sector / Backtest), Onboarding Spotlight Overlay, Stats Row — IHSG / WIB / Clean Money, Candlestick + Volume Series (index.html), Chart Preview Page (index.html), loadChart() — Fetch OHLCV and Render, Timeframe Selector (5m/15m/30m/1h/1D) (+23 more)

### Community 4 - "Wyckoff Phase Safety Gates"
Cohesion: 0.2
Nodes (18): Info / Glossary Modal, init() — Fetch IHSG + Clean Money + Clock, ARB Safety Gate (Gate B) — ARB_SPRING Hold, Anti-Pucuk Gate (Gate C) — Overextended Price Block, classify_zenith_v3_1() — Wyckoff Phase Classifier, compute_analytics_for_date() Integration Point, compute_moving_averages() — MA 5/13/34/200, detect_ma_cross() — Golden/Death Cross Detection (+10 more)

### Community 5 - "Phase Classification Engine"
Cohesion: 0.15
Nodes (14): _startup_backtest(), classify_zenith_v3_1(), get_action(), get_watch_flag(), logic.py — Zenith Phase Classification Engine v3.1 ============================, Return "ARB_SPRING" if SPRING occurs during extreme drop (>1.5× ATR).     Phase, Classify Wyckoff phase using Zenith v3.1 logic.      Parameters     ---------, Derive trading action from phase with 3 safety gates (v3.1).      Gate A — Sup (+6 more)

### Community 6 - "Algorithm Documentation v2.1"
Cohesion: 0.14
Nodes (15): Zenith Algorithm Guide v2.1 (algo dir), Phase Classification Algorithm v2.1, ARB_SPRING Watch Flag, BM_SMA10 — Baseline Bad Money Simple Mean, Global Anti-Pucuk Gate — Gate C, classify_zenith_v3_1 Function, get_action Function v3.1, get_watch_flag Function (+7 more)

### Community 7 - "Frontend Animation Functions"
Cohesion: 0.16
Nodes (3): _getTopBar(), topbarDone(), topbarStart()

### Community 8 - "KSPM Investment Competition"
Cohesion: 0.15
Nodes (13): Equity Research Competition, KSPM UMN Investment 101 — Breaking The Limit, KSPM UMN (Kelompok Studi Pasar Modal, Universitas Multimedia Nusantara), Phillip Sekuritas Indonesia, Total Prize 13.5 Juta Rupiah (IDR 13,500,000), Competition Timeline April 1 – May 23, Trading Competition, Breaking The Limit Theme (+5 more)

### Community 9 - "Async Job Queue System"
Cohesion: 0.18
Nodes (12): Queue a weekly backfill request — runs in scraper thread, not HTTP thread., Queue full scrape dari awal — fetch semua data dari Telegram., Queue summary rebuild — runs in scraper thread., rebuild_summary(), scrape_from_telegram(), trigger_weekly(), get_backfill_status(), Called from HTTP thread to request a backfill. Non-blocking. (+4 more)

### Community 10 - "Character Decryptor Assets"
Cohesion: 0.28
Nodes (9): Blue / Purple Eyes, Decryptor Character (Anime-Style Female Figure), Chest-Mounted Technological Device, Cyborg / Sci-Fi Aesthetic, Game / Visual Novel Character Art, Mechanical Head Gear / Audio Modules, Character Decryptor Portrait Image, Long Pink Hair (+1 more)

### Community 11 - "UI Design System"
Cohesion: 0.39
Nodes (8): Frontend Pages — Design System & Templates, Redesign Prompt (structure dir), admin.html Template, backtest.html Template, chart.html Template, flow.html Template, Zenith UI Design System — Dark Terminal Aesthetic, Nav Group Component Pattern

### Community 12 - "Project Core Concepts"
Cohesion: 0.33
Nodes (7): Telegram Bot Joker Data Source, Bandarmologi Methodology, IDX — Indonesian Stock Exchange, Railway Deployment Platform, Wyckoff Phase Analysis, Zenith Project Overview — Handoff v4, Handoff v4 (structure dir)

### Community 13 - "Production Architecture"
Cohesion: 0.5
Nodes (4): Zenith Architecture & File Structure v4, SQLite WAL Mode & PRAGMAs, Gunicorn Multi-Worker Lock File, Signal Queue Pattern — Critical Architecture

### Community 15 - "Kompas100 Transactions"
Cohesion: 1.0
Nodes (2): Kompas100 Transactions Panel (SM/BM), API: /api/transactions

### Community 16 - "Ticker Fitness API"
Cohesion: 1.0
Nodes (2): Ticker Strategy Fitness Card, API: /api/ticker-fitness

### Community 17 - "Graphify Config"
Cohesion: 1.0
Nodes (1): Zenith Graphify Project Config

### Community 18 - "Project README"
Cohesion: 1.0
Nodes (1): Zenith Project README

### Community 19 - "Flask Dependency"
Cohesion: 1.0
Nodes (1): Flask Dependency

### Community 20 - "Gunicorn Dependency"
Cohesion: 1.0
Nodes (1): Gunicorn Dependency

### Community 21 - "Telethon Dependency"
Cohesion: 1.0
Nodes (1): Telethon Dependency

### Community 22 - "Psycopg2 Dependency"
Cohesion: 1.0
Nodes (1): Psycopg2 Dependency

### Community 23 - "Gevent Dependency"
Cohesion: 1.0
Nodes (1): Gevent Dependency

### Community 24 - "Requests Dependency"
Cohesion: 1.0
Nodes (1): Requests Dependency

### Community 25 - "Telegram Scraper System"
Cohesion: 1.0
Nodes (1): Scraper System — Telegram Parser & Schedule

### Community 26 - "API Endpoints"
Cohesion: 1.0
Nodes (1): API Endpoints

### Community 27 - "Admin Endpoints"
Cohesion: 1.0
Nodes (1): Admin Endpoints

### Community 28 - "Railway Deployment"
Cohesion: 1.0
Nodes (1): Railway Deployment Config

### Community 29 - "Lightweight Charts"
Cohesion: 1.0
Nodes (1): Lightweight Charts v4 Integration

### Community 30 - "OHLCV Hover Tooltip"
Cohesion: 1.0
Nodes (1): Hover Tooltip (OHLCV + Volume)

## Knowledge Gaps
- **126 isolated node(s):** `Hitung % change harga saham dari date_from ke date_to.     Single day  → close`, `DD-MM-YYYY → datetime.date`, `DD-MM-YYYY → YYYYMMDD integer for SQLite sorting.`, `Thread-local connection reuse with optimized PRAGMAs.`, `Download zenith.db dari Dropbox shareable link → simpan ke Railway volume.` (+121 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Kompas100 Transactions`** (2 nodes): `Kompas100 Transactions Panel (SM/BM)`, `API: /api/transactions`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Ticker Fitness API`** (2 nodes): `Ticker Strategy Fitness Card`, `API: /api/ticker-fitness`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Graphify Config`** (1 nodes): `Zenith Graphify Project Config`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Project README`** (1 nodes): `Zenith Project README`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Flask Dependency`** (1 nodes): `Flask Dependency`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Gunicorn Dependency`** (1 nodes): `Gunicorn Dependency`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Telethon Dependency`** (1 nodes): `Telethon Dependency`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Psycopg2 Dependency`** (1 nodes): `Psycopg2 Dependency`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Gevent Dependency`** (1 nodes): `Gevent Dependency`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Requests Dependency`** (1 nodes): `Requests Dependency`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Telegram Scraper System`** (1 nodes): `Scraper System — Telegram Parser & Schedule`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `API Endpoints`** (1 nodes): `API Endpoints`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Admin Endpoints`** (1 nodes): `Admin Endpoints`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Railway Deployment`** (1 nodes): `Railway Deployment Config`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Lightweight Charts`** (1 nodes): `Lightweight Charts v4 Integration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OHLCV Hover Tooltip`** (1 nodes): `Hover Tooltip (OHLCV + Volume)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `compute_analytics_for_date()` connect `Data Scraping & Analytics Pipeline` to `Flask API Route Handlers`, `Phase Classification Engine`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Why does `admin_backfill_prices()` connect `Data Scraping & Analytics Pipeline` to `Flask API Route Handlers`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **Why does `Phase Classification Algorithm v2` connect `Zenith Signal Metrics` to `Algorithm Documentation v2.1`?**
  _High betweenness centrality (0.014) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `compute_analytics_for_date()` (e.g. with `admin_backfill_prices()` and `admin_recompute_analytics()`) actually correct?**
  _`compute_analytics_for_date()` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `run_weekly_backfill()` (e.g. with `scraper_main()` and `get_scraper_db()`) actually correct?**
  _`run_weekly_backfill()` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Hitung % change harga saham dari date_from ke date_to.     Single day  → close`, `DD-MM-YYYY → datetime.date`, `DD-MM-YYYY → YYYYMMDD integer for SQLite sorting.` to the rest of the system?**
  _126 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Flask API Route Handlers` be split into smaller, more focused modules?**
  _Cohesion score 0.05 - nodes in this community are weakly interconnected._