# ZENITH — Algoritma Phase & Signal v2
## Panduan Teknis untuk Developer & SOP Trading

> Dokumen ini menjelaskan seluruh algoritma perhitungan phase (fase Wyckoff) dan signal (BUY/HOLD/SELL) yang digunakan di Zenith Dashboard.
> **Update v2:** ATR Dynamic Thresholds, Profit Factor, Multi-Entry Backtest, VWAP BM.
> Last updated: April 2026

---

## 1. Sumber Data

### 1.1 Raw Data dari Telegram Bot "Joker"

Bot Joker memposting transaksi big player di 4 topik Telegram:

| Topik | Channel | Arti |
|-------|---------|------|
| SM (Smart Money) | `"smart"` | Big player yang **BELI** saham |
| BM (Bad Money) | `"bad"` | Big player yang **JUAL** saham |
| MF+ | `"mf_plus"` | Money Flow masuk |
| MF- | `"mf_minus"` | Money Flow keluar |

**Field kunci yang disimpan:**
- `ticker` — kode saham (BRRC, BBRI, dll)
- `price` — harga **saat transaksi** (BUKAN harga penutupan)
- `gain_pct` — persentase gain saat itu (dari Joker, bukan dari kita)
- `mf_delta_numeric` — **nilai SM/BM VAL** (dalam Juta). Ini sumber utama untuk menghitung aliran uang.
- `date` — format DD-MM-YYYY
- `channel` — "smart" atau "bad"

### 1.2 Data Harga (Close Price)

- **Close price** di-fetch dari Yahoo Finance (`query1.finance.yahoo.com`)
- **Bulk backfill:** `backfill_prices()` — 1 request per ticker, covers 30 hari. Stored di `eod_summary.price_close`
- **Daily auto:** `enrich_daily_prices()` jam 17:00 WIB simpan close price hari itu
- **Fallback:** Kalau DB gak punya, request Yahoo on-demand (hanya untuk ticker yang missing)

**⚠️ PENTING:**
- `raw_messages.price` BUKAN close price. Itu harga saat signal muncul (bisa jam 10 pagi). Jangan gunakan untuk menghitung gain%.
- Single-day view di dashboard: gain% di-fetch via Yahoo (bukan DB comparison) karena prev trading day di DB bisa minggu lalu → gain salah.

---

## 2. Agregasi Data (eod_summary)

Setiap hari, raw data di-agregasi ke tabel `eod_summary`:

```sql
-- Per ticker per hari:
sm_val   = SUM(mf_delta_numeric) WHERE channel = 'smart'
bm_val   = SUM(ABS(mf_delta_numeric)) WHERE channel = 'bad'
tx_sm    = COUNT(*) WHERE channel = 'smart'
tx_bm    = COUNT(*) WHERE channel = 'bad'
tx_count = tx_sm + tx_bm

-- VWAP SM (harga rata-rata tertimbang pembelian SM):
vwap_sm  = SUM(price × |mf_delta_numeric|) / SUM(|mf_delta_numeric|)
           WHERE channel = 'smart' AND price > 0

-- VWAP BM (harga rata-rata tertimbang penjualan BM):  [NEW v2]
vwap_bm  = SUM(price × |mf_delta_numeric|) / SUM(|mf_delta_numeric|)
           WHERE channel = 'bad' AND price > 0
```

### 2.1 Derived Values

```
CM  (Clean Money) = sm_val - bm_val
    Positif = net buying. Negatif = net selling.

RSM (SM Ratio %) = sm_val / (sm_val + bm_val) × 100
    SIZE-AGNOSTIC: 65% untuk BBRI (trilyunan) dan saham kecil (jutaan) artinya sama.
    Ini kunci dari seluruh system — kita tidak peduli seberapa besar uangnya,
    tapi seberapa dominan SM vs BM.
```

### 2.2 Hover Tooltips di Dashboard

| Cell | Hover info |
|------|-----------|
| SM VAL | "Avg buy price: {vwap_sm}" |
| BM VAL | "Avg sell price: {vwap_bm}" |
| CM | "Avg SM: {vwap_sm} | Avg BM: {vwap_bm} | ATR: {atr_pct}%" |

**Kenapa penting:** Saat SPRING (harga turun, SM beli), hover SM VAL menunjukkan di harga berapa SM masuk. Kalau avg SM price jauh di atas current price → SM yakin harga akan naik.

---

## 3. Metrik Analitik

### 3.1 SRI — SM Relative Intensity

**Mengukur:** Seberapa agresif SM hari ini dibanding rata-rata historisnya.

```
SRI = sm_val_today / SMA(sm_val, 10 hari)
```

| SRI | Arti |
|-----|------|
| > 3.0 | SM **SANGAT** agresif (3× dari biasanya) — trigger SOS |
| > 2.0 | SM agresif (2× lipat) — trigger ABSORB |
| > 1.5 | SM cukup aktif — trigger SPRING |
| > 1.0 | SM di atas rata-rata — trigger ACCUM |
| < 0.5 | SM hampir tidak ada aktivitas |

### 3.2 RPR — Rasio Tekanan Jual

```
RPR = tx_bm / (tx_sm + tx_bm)
```

**BM = Big player yang JUAL.** BUKAN partisipasi retail.

| RPR | Arti |
|-----|------|
| > 0.6 | Big player lebih banyak JUAL → trigger UPTHRUST |
| 0.5 | Seimbang |
| < 0.35 | Big player lebih banyak BELI |

### 3.3 MES — Market Efficiency Score

```
MES = |gain%| / SRI
```

MES rendah + SRI tinggi = absorption (akumulasi diam-diam).
MES tinggi + SRI tinggi = SM efektif menggerakkan harga.

### 3.4 Volx Gap

```
Volx Gap = (price_close - vwap_sm) / price_close × 100
```

| Volx Gap | Arti |
|----------|------|
| < -1.5% | SM beli di atas close → harga bisa naik catch up |
| > +1.5% | SM beli di bawah close → SM sudah untung |

### 3.5 ATR% — Average True Range (NEW v2)

```
ATR% = AVG(|daily_change_%|) over last 14 days
```

**Stored di:** `eod_summary.atr_pct`

| Saham | ATR% khas | Arti |
|-------|-----------|------|
| BBCA, BBRI (blue chip) | 0.8 - 1.5% | Sangat stabil |
| ANTM, BRMS (mid cap) | 2.0 - 3.5% | Moderat |
| PADI, GOTO (volatile) | 4.0 - 8.0% | Sangat volatile |

**Kenapa penting:** Kenaikan 3% di BBCA itu **luar biasa** (≈ 3× ATR), tapi 3% di PADI itu **biasa aja** (< 1× ATR). Tanpa ATR, keduanya terdeteksi sama.

---

## 4. Algoritma Phase Classification (ATR-Adjusted)

### 4.1 Dynamic Thresholds

Semua threshold gain% sekarang **dihitung per saham** berdasarkan ATR:

```python
atr = atr_pct or 2.5  # fallback kalau belum ada data

th_up    = max(atr × 0.8, 1.0%)    # "kenaikan signifikan"
th_down  = max(atr × 0.4, 0.5%)    # "penurunan signifikan"
th_flat  = atr × 0.5               # "flat" (untuk ABSORB)
th_sos_h = max(atr × 2.0, 5.0%)   # "SOS terlalu tinggi → HOLD"
```

**Contoh threshold per saham:**

| Saham | ATR% | th_up (SOS/UPTHRUST) | th_down (SPRING) | th_flat (ABSORB) | th_sos_h |
|-------|------|---------------------|------------------|-----------------|----------|
| BBCA | 1.2% | 1.0% | 0.5% | 0.6% | 5.0% |
| ANTM | 2.5% | 2.0% | 1.0% | 1.25% | 5.0% |
| PADI | 5.0% | 4.0% | 2.0% | 2.5% | 10.0% |

Artinya: BBCA cuma perlu naik 1% untuk SOS, tapi PADI harus naik 4%.

### 4.2 Decision Tree (urutan prioritas PENTING)

Phase dievaluasi **dari atas ke bawah**. Phase pertama yang match = phase yang dipakai.

```
INPUT: rsm, sri, gain, rpr, atr_pct

// Compute dynamic thresholds
atr = atr_pct or 2.5
th_up    = max(atr × 0.8, 1.0)
th_down  = max(atr × 0.4, 0.5)
th_flat  = atr × 0.5
th_sos_h = max(atr × 2.0, 5.0)

1. SOS (Sign of Strength)
   IF gain > th_up AND rsm > 65% AND sri > 3.0
   THEN → SOS
   ACTION → BUY if gain < th_sos_h, HOLD if gain ≥ th_sos_h

2. SPRING
   IF gain < -th_down AND rsm > 60% AND sri > 1.5
   THEN → SPRING, BUY

3. UPTHRUST
   IF gain > th_up AND rsm < 40% AND rpr > 0.6
   THEN → UPTHRUST, SELL

4. DISTRI (Distribution)
   IF rsm < 40% AND gain < -(th_down × 0.5) AND sri > 1.0
   THEN → DISTRI, SELL

5. ABSORB (Absorption)
   IF sri > 2.0 AND rsm > 65% AND |gain| < th_flat
   THEN → ABSORB, BUY

6. ACCUM (Accumulation)
   IF rsm > 60% AND sri > 1.0
   THEN → ACCUM, BUY

7. DISTRI fallback
   IF rsm < 35% AND sri > 0.8
   THEN → DISTRI, SELL

8. NEUTRAL
   Semua yang tidak masuk kategori di atas
   → NEUTRAL, HOLD
```

### 4.3 Penjelasan Setiap Phase

#### 🟢 SOS — Sign of Strength
**Kondisi:** Harga naik > th_up + SM dominasi > 65% + SM 3× lebih aktif dari biasa.
**Artinya:** Kenaikan harga **DIDUKUNG** oleh pembelian besar SM. Momentum kuat.
**Action:** BUY kalau gain masih di bawah 2× ATR. HOLD kalau sudah terlalu tinggi.
**ATR Impact:** BBCA naik 1.2% = SOS. PADI naik 1.2% = belum cukup (perlu 4%).

#### 🟢 SPRING — Pegas Siap Mantul
**Kondisi:** Harga TURUN > th_down + SM masih dominan > 60% + SM cukup aktif.
**Artinya:** Harga jatuh tapi big player justru beli. Seperti pegas ditekan.
**Insight:** Cek hover SM VAL → lihat avg buy price SM. Kalau jauh di atas harga sekarang, SM yakin harga akan recovery.

#### 🟠 UPTHRUST — Jebakan Naik
**Kondisi:** Harga naik > th_up + BM dominan > 60% + big player lebih banyak jual (RPR > 0.6).
**Artinya:** Harga naik TANPA dukungan big player. Trap.

#### 🔴 DISTRI — Distribusi
**Kondisi:** BM dominan > 60% + harga turun > th_down/2 + SM masih aktif.
**Artinya:** Big player sedang buang barang.

#### 🔵 ABSORB — Absorpsi
**Kondisi:** SM SANGAT aktif (SRI > 2.0) + SM dominan > 65% + harga FLAT (|gain| < th_flat).
**Artinya:** SM belanja besar tapi harga tidak bergerak. Akumulasi diam-diam.
**Insight:** MES akan rendah di sini. Fase sebelum breakout.

#### 🟢 ACCUM — Akumulasi
**Kondisi:** SM dominan > 60% + SM di atas rata-rata (SRI > 1.0).
**Artinya:** Ada pembelian SM yang jelas tapi belum se-agresif ABSORB/SOS.

#### ⚪ NEUTRAL
**Kondisi:** RSM 35-60% atau SRI terlalu rendah.
**Artinya:** Tidak ada sinyal arah yang jelas.

---

## 5. Action Signal

| Phase | Action | Kondisi Tambahan |
|-------|--------|-----------------|
| SOS | BUY | gain < th_sos_h (masih affordable) |
| SOS | HOLD | gain ≥ th_sos_h (sudah lari jauh) |
| SPRING | BUY | — |
| ABSORB | BUY | — |
| ACCUM | BUY | — |
| UPTHRUST | SELL | — |
| DISTRI | SELL | — |
| NEUTRAL | HOLD | — |

---

## 6. Di Mana Phase Dihitung (HARUS SYNC)

Phase dihitung di **3 lokasi** yang HARUS identik:

| Lokasi | File | Fungsi | Kapan |
|--------|------|--------|-------|
| Flow API | `app.py` `/api/flow` | Inline code | On-the-fly, setiap user request |
| Daily analytics | `scraper_daily.py` | `_classify_phase()` + `_get_action()` | 17:00 WIB daily |
| Backtest engine | `scraper_daily.py` | `_compute_phase_action()` | Saat backtest dijalankan |

**⚠️ Kalau ubah threshold di satu tempat, UBAH DI KETIGA TEMPAT.**

Semua 3 fungsi sekarang menerima `atr_pct` parameter dan menghitung dynamic thresholds secara identik.

---

## 7. Backtest Engine v2

### 7.1 Multi-Entry Pair-Based Backtest

Tidak mengukur signal individual, tapi **pasangan BUY→SELL** dengan support **duplicate BUY**:

```
Untuk setiap ticker, scan signal kronologis:
  Hari 1: ACCUM (BUY)  → Buka posisi A di OPEN hari 2
  Hari 3: NEUTRAL (HOLD) → hold
  Hari 5: SPRING (BUY) → Buka posisi B di OPEN hari 6 (TIDAK skip)
  Hari 8: DISTRI (SELL) → Tutup SEMUA posisi di OPEN hari 9

  Trade 1: ACCUM→DISTRI, entry=OPEN hari 2, exit=OPEN hari 9, durasi 7 hari
  Trade 2: SPRING→DISTRI, entry=OPEN hari 6, exit=OPEN hari 9, durasi 3 hari
```

**Rules:**
- Entry price = OPEN hari setelah BUY signal (realistis: trader lihat signal malam, beli pagi)
- Exit price = OPEN hari setelah SELL signal
- **Setiap BUY membuka posisi baru** — tidak skip duplicate
- SELL menutup **SEMUA** posisi terbuka sekaligus
- HOLD/NEUTRAL = tidak buka/tutup posisi
- Setiap trade dicatat di combo entry_phase → exit_phase masing-masing

**Kenapa multi-entry adil:**
Setiap entry signal dihitung di combo-nya sendiri. ACCUM→DISTRI dan SPRING→DISTRI masuk leaderboard row berbeda. Lebih banyak data = statistik lebih reliable.

### 7.2 Yahoo OHLCV Range

```python
# Hitung range berdasarkan tanggal data aktual, bukan hardcode
d_earliest = datetime.strptime(use_dates[0], "%d-%m-%Y")
d_today = datetime.now()
calendar_span = min((d_today - d_earliest).days + 10, 730)
# 1 request per ticker, covers semua tanggal
```

### 7.3 Metrik Leaderboard

| Metrik | Formula |
|--------|---------|
| Win Rate | `wins / total_trades × 100` |
| Avg Profit | `SUM(profit%) / total_trades` |
| Avg Win | `SUM(profit% where > 0) / wins` |
| Avg Loss | `SUM(profit% where ≤ 0) / losses` |
| Avg Duration | `SUM(duration_days) / total_trades` |
| **Profit Factor** | `Σ(gross_profit) / |Σ(gross_loss)|` |

### 7.4 Profit Factor (Menggantikan Expectancy)

```
Profit Factor = Gross Profit / |Gross Loss|
```

| PF | Warna | Interpretasi |
|----|-------|-------------|
| ≥ 2.0× | 🟢 Hijau | Sangat bagus — profit 2× lipat dari loss |
| ≥ 1.0× | 🟡 Kuning | Profitable — profit > loss |
| < 1.0× | 🔴 Merah | Rugi — loss lebih besar dari profit |
| 99.0× | 🟢 | Tidak ada loss sama sekali |

**Kenapa ganti Expectancy:**
Profit Factor lebih intuitif — "untuk setiap Rp1 yang hilang, berapa Rp yang dihasilkan?" PF 2.5× artinya setiap Rp1 loss menghasilkan Rp2.50 profit.

### 7.5 Backtest Results Reference (30 hari, April 2026, ATR-adjusted)

| Entry | Exit | Trades | Win Rate | Avg Profit | PF |
|-------|------|--------|----------|------------|-----|
| ACCUM | UPTHRUST | 76 | 63.2% | +4.64% | High |
| SOS | UPTHRUST | 3 | 100% | +4.32% | ∞ |
| SPRING | UPTHRUST | 16 | 75% | +3.8% | High |
| ACCUM | DISTRI | 63 | 44.4% | +0.7% | ~1.2× |
| ABSORB | DISTRI | 10 | 30% | -2.95% | < 1× |

**Key insight:** Exit di UPTHRUST konsisten lebih profitable dari DISTRI.

### 7.6 Trade Detail Drill-Down

Klik row di leaderboard → modal menunjukkan semua trade individual:

| TICKER | ENTRY SIGNAL | EXIT SIGNAL | ENTRY PRICE | EXIT PRICE | DAYS | PROFIT |
|--------|-------------|------------|-------------|------------|------|--------|
| PADI | 10-03-2026 | 15-03-2026 | 100 | 115 | 5d | +15% |
| DSSA | 12-03-2026 | 18-03-2026 | 5.200 | 4.900 | 6d | -5.77% |

Sorted by profit desc. Ticker search bar tersedia untuk filter.

---

## 8. Price & Gain% Architecture

### 8.1 Sumber Data Harga

| Situasi | Sumber | Yahoo Request? |
|---------|--------|---------------|
| 30 hari terakhir | `eod_summary.price_close` (pre-stored) | Tidak |
| Lebih dari 30 hari (range mode) | Yahoo on-demand fallback | Ya, hanya missing |
| Single day view | Yahoo via `get_gains_batch()` | Ya, karena DB prev bisa salah |
| Ke depan (otomatis) | `enrich_daily_prices()` 17:00 WIB | Ya, sekali/hari |

### 8.2 Gain% Computation

**Multi-day range:**
```
gain = (price_close_latest - price_close_prev_day) / price_close_prev_day × 100
```
Dimana `prev_day` = hari trading SEBELUM tanggal awal range (dari DB).

**Single day:**
Yahoo langsung (karena DB comparison bisa off — prev row bisa 3 hari lalu kalau libur).

### 8.3 Bulk Price Backfill

```python
backfill_prices(conn, days=30)
# 1 request per ticker (bukan per tanggal)
# 750 tickers × 1 request = 750 requests total
# Overwrite existing (bukan WHERE IS NULL)
# Jalankan via: /admin/backfill-prices?secret=zenith2026&days=30
```

---

## 9. Database Schema v3

```sql
eod_summary (
    date, ticker,                              -- PK: UNIQUE(date, ticker)
    sm_val REAL DEFAULT 0,                     -- Total SM (Juta)
    bm_val REAL DEFAULT 0,                     -- Total BM (Juta)
    tx_count INTEGER DEFAULT 0,
    tx_sm INTEGER DEFAULT 0,                   -- For RPR
    tx_bm INTEGER DEFAULT 0,                   -- For RPR
    mf_plus REAL,                              -- NULL not 0!
    mf_minus REAL,                             -- NULL not 0!
    vwap_sm REAL,                              -- Avg SM buy price
    vwap_bm REAL,                              -- Avg BM sell price [NEW v2]
    price_close REAL,                          -- Yahoo close price
    price_change_pct REAL,
    sri REAL,
    mes REAL,
    volx_gap REAL,
    rpr REAL,
    atr_pct REAL,                              -- ATR% 14-day [NEW v2]
    phase TEXT,
    action TEXT
)
```

**⚠️ KRITIS:** `mf_plus, mf_minus, vwap_sm, vwap_bm, price_close, sri, mes` harus **NULL** (bukan DEFAULT 0). Code cek `IS NOT NULL`.

---

## 10. Pseudocode Lengkap (v2, ATR-Adjusted)

```python
def classify(ticker_data, atr_pct=None):
    # Derived
    rsm = sm_val / (sm_val + bm_val) * 100
    rpr = tx_bm / (tx_sm + tx_bm)
    sri = sm_val_latest / SMA(sm_val, 10 days)
    gain = (close_latest - close_prev) / close_prev * 100

    # Dynamic thresholds
    atr = atr_pct or 2.5
    th_up    = max(atr * 0.8, 1.0)
    th_down  = max(atr * 0.4, 0.5)
    th_flat  = atr * 0.5
    th_sos_h = max(atr * 2.0, 5.0)

    # Decision tree (ORDER MATTERS)
    if gain > th_up and rsm > 65 and sri > 3.0:
        return "SOS", "BUY" if gain < th_sos_h else "HOLD"

    if gain < -th_down and rsm > 60 and sri > 1.5:
        return "SPRING", "BUY"

    if gain > th_up and rsm < 40 and rpr > 0.6:
        return "UPTHRUST", "SELL"

    if rsm < 40 and gain < -(th_down * 0.5) and sri > 1.0:
        return "DISTRI", "SELL"

    if sri > 2.0 and rsm > 65 and abs(gain) < th_flat:
        return "ABSORB", "BUY"

    if rsm > 60 and sri > 1.0:
        return "ACCUM", "BUY"

    if rsm < 35 and sri > 0.8:
        return "DISTRI", "SELL"

    return "NEUTRAL", "HOLD"
```

---

## 11. Tabel Referensi Cepat

### Phase → Kondisi (ATR-Adjusted)

| Phase | RSM | SRI | Gain | RPR | Threshold |
|-------|-----|-----|------|-----|-----------|
| SOS | > 65% | > 3.0 | > th_up | — | th_up = max(ATR×0.8, 1%) |
| SPRING | > 60% | > 1.5 | < -th_down | — | th_down = max(ATR×0.4, 0.5%) |
| UPTHRUST | < 40% | — | > th_up | > 0.6 | th_up = max(ATR×0.8, 1%) |
| DISTRI | < 40% | > 1.0 | < -(th_down×0.5) | — | — |
| ABSORB | > 65% | > 2.0 | |gain| < th_flat | — | th_flat = ATR×0.5 |
| ACCUM | > 60% | > 1.0 | — | — | Catch setelah 5 di atas |
| DISTRI fb | < 35% | > 0.8 | — | — | — |
| NEUTRAL | 35-60% | — | — | — | Default |

### Contoh Real: BBCA (ATR 1.2%) vs PADI (ATR 5%)

| Threshold | BBCA | PADI |
|-----------|------|------|
| SOS trigger (th_up) | > 1.0% | > 4.0% |
| SPRING trigger (th_down) | < -0.5% | < -2.0% |
| ABSORB flat (th_flat) | < 0.6% | < 2.5% |
| SOS → HOLD (th_sos_h) | > 5.0% | > 10.0% |

---

## 12. Kelemahan & Area Improvement

### Sudah Diperbaiki (v1 → v2)
- ✅ Threshold statis → ATR Dynamic Thresholds
- ✅ Expectancy → Profit Factor (lebih intuitif)
- ✅ Single-entry backtest → Multi-entry (setiap BUY dihitung)
- ✅ Tidak ada VWAP BM → vwap_bm ditambahkan
- ✅ Yahoo per-user request → DB-stored prices + bulk backfill


