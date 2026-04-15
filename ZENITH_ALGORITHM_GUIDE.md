# ZENITH — Algoritma Phase & Signal
## Panduan Teknis untuk Developer

> Dokumen ini menjelaskan seluruh algoritma perhitungan phase (fase Wyckoff) dan signal (BUY/HOLD/SELL) yang digunakan di Zenith Dashboard.
> Tujuannya agar developer lain dapat memahami, mereproduksi, dan meng-improve akurasi sistem ini.

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

Setiap pesan mengandung data per saham per transaksi:

```
Tx  |Name |Price|Gain| Freq|Value  | avg MF  |    MF+   |  Vol x🚦
1⭐️ BRRC    79 -2.47  45   128Jt   14.6Jt  +125.9Jt    5.5x🟢
```

**Field kunci yang disimpan:**
- `ticker` — kode saham (BRRC, BBRI, dll)
- `price` — harga **saat transaksi** (BUKAN harga penutupan)
- `gain_pct` — persentase gain saat itu (dari Joker, bukan dari kita)
- `mf_delta_numeric` — **nilai SM/BM VAL** (dalam Juta). Ini sumber utama untuk menghitung aliran uang.
- `date` — format DD-MM-YYYY
- `channel` — "smart" atau "bad"

### 1.2 Data Harga

- **Close price** di-fetch dari Yahoo Finance (`query1.finance.yahoo.com`)
- Disimpan di `eod_summary.price_close` saat daily backfill jam 17:00 WIB
- Bulk backfill 30 hari terakhir via `backfill_prices()`
- **PENTING:** `raw_messages.price` BUKAN close price. Itu harga saat signal muncul (bisa jam 10 pagi, bisa jam 2 siang). Jangan gunakan untuk menghitung gain%.

---

## 2. Agregasi Data (eod_summary)

Setiap hari, raw data di-agregasi ke tabel `eod_summary`:

```sql
-- Per ticker per hari:
sm_val   = SUM(mf_delta_numeric) WHERE channel = 'smart'     -- Total rupiah SM beli
bm_val   = SUM(ABS(mf_delta_numeric)) WHERE channel = 'bad'  -- Total rupiah BM jual
tx_sm    = COUNT(*) WHERE channel = 'smart'                   -- Jumlah signal SM
tx_bm    = COUNT(*) WHERE channel = 'bad'                     -- Jumlah signal BM
tx_count = tx_sm + tx_bm                                      -- Total signal

-- VWAP SM (harga rata-rata tertimbang pembelian SM):
vwap_sm  = SUM(price × |mf_delta_numeric|) / SUM(|mf_delta_numeric|)
           WHERE channel = 'smart' AND price > 0
```

### 2.1 Derived Values (dihitung dari agregat)

```
CM  (Clean Money) = sm_val - bm_val
    Positif = lebih banyak beli. Negatif = lebih banyak jual.

RSM (SM Ratio %) = sm_val / (sm_val + bm_val) × 100
    65% = SM 65% dari total. BM 35%.
    SIZE-AGNOSTIC: 65% untuk BBRI (trilyunan) dan saham kecil (jutaan) artinya sama.
```

---

## 3. Metrik Analitik

### 3.1 SRI — SM Relative Intensity

**Mengukur:** Seberapa agresif SM hari ini dibanding rata-rata historisnya.

```
SRI = sm_val_today / SMA(sm_val, 10 hari)
```

**Cara hitung:**
1. Ambil 10 record terakhir ticker dari eod_summary (ORDER BY date DESC LIMIT 10)
2. Filter hanya yang `sm_val > 0`
3. `SMA = sum(sm_val) / count`
4. `SRI = sm_val_hari_ini / SMA`

**Interpretasi:**
| SRI | Arti |
|-----|------|
| > 3.0 | SM **SANGAT** agresif (3× lipat dari biasanya) |
| > 2.0 | SM agresif (2× lipat) |
| > 1.0 | SM di atas rata-rata |
| 1.0 | Normal |
| < 0.5 | SM hampir tidak ada aktivitas |

**Catatan penting:**
- Pembagi menggunakan `n` (jumlah record yang ada), bukan selalu 10
- Kalau ticker baru (< 3 hari data), SRI tidak reliable
- SRI = 0 jika SMA = 0 (tidak ada histori SM)

---

### 3.2 RPR — Rasio Tekanan Jual

**Mengukur:** Proporsi **aktivitas jual** big player terhadap total.

```
RPR = tx_bm / (tx_sm + tx_bm)
```

**PENTING:** BM = Big player yang JUAL/buang barang. BUKAN partisipasi retail.

**Interpretasi:**
| RPR | Arti |
|-----|------|
| > 0.65 | Big player lebih banyak JUAL dari beli |
| 0.5 | Seimbang |
| < 0.35 | Big player lebih banyak BELI dari jual |

---

### 3.3 MES — Market Efficiency Score

**Mengukur:** Apakah effort SM menghasilkan pergerakan harga yang setara.

```
MES = |gain%| / SRI
```

**Interpretasi:**

MES harus dibaca BERSAMA SRI:

| MES | SRI | Arti |
|-----|-----|------|
| < 0.5 | > 2.0 | SM belanja besar tapi harga flat → **absorption** (akumulasi diam-diam) |
| Tinggi | > 2.0 | SM aktif DAN harga bergerak → SM **efektif** |
| Tinggi | < 0.5 | Harga bergerak TANPA SM → gerakan spekulatif/ritel |

**JANGAN** interpret MES tinggi sebagai "tanpa dukungan big player" — cek SRI dulu.

---

### 3.4 Volx Gap

**Mengukur:** Selisih harga penutupan vs harga rata-rata belanja SM.

```
Volx Gap = (price_close - vwap_sm) / price_close × 100
```

**Interpretasi:**
| Volx Gap | Arti |
|----------|------|
| < -1.5% | SM beli di atas close → **discount** (harga bisa naik untuk catch up) |
| > +1.5% | SM beli di bawah close → **premium** (SM sudah untung) |

---

## 4. Algoritma Phase Classification

### 4.1 Input Variables

Semua phase dihitung dari variabel ini:

| Variable | Sumber | Scope |
|----------|--------|-------|
| `rsm` | SUM(sm_val) / SUM(sm_val + bm_val) × 100 | Range tanggal yang dipilih |
| `sri` | sm_val / SMA(sm_val, 10) | Latest date only (butuh histori) |
| `gain` | (close_latest - close_prev) / close_prev × 100 | Range tanggal |
| `rpr` | SUM(tx_bm) / SUM(tx_sm + tx_bm) | Range tanggal |
| `cm` | SUM(sm_val) - SUM(bm_val) | Range tanggal |

### 4.2 Decision Tree (urutan prioritas PENTING)

Phase dievaluasi **dari atas ke bawah**. Phase pertama yang match = phase yang dipakai.

```
INPUT: rsm, sri, gain, rpr, cm

1. SOS (Sign of Strength)
   IF gain > 2%
   AND rsm > 65%
   AND sri > 3.0
   THEN → SOS

2. SPRING
   IF gain < -1%
   AND rsm > 60%
   AND sri > 1.5
   THEN → SPRING

3. UPTHRUST
   IF gain > 2%
   AND rsm < 40%
   AND rpr > 0.6
   THEN → UPTHRUST

4. DISTRI (Distribution)
   IF rsm < 40%
   AND gain < -0.5%
   AND sri > 1.0
   THEN → DISTRI

5. ABSORB (Absorption)
   IF sri > 2.0
   AND rsm > 65%
   AND |gain| < 1.5%
   THEN → ABSORB

6. ACCUM (Accumulation)
   IF rsm > 60%
   AND sri > 1.0
   THEN → ACCUM

7. DISTRI fallback
   IF rsm < 35%
   AND sri > 0.8
   THEN → DISTRI

8. NEUTRAL
   Semua yang tidak masuk kategori di atas
   THEN → NEUTRAL
```

### 4.3 Penjelasan Setiap Phase

#### 🟢 SOS — Sign of Strength
**Kondisi:** Harga sudah naik >2% + SM mendominasi >65% + SM 3× lebih aktif dari biasa.
**Artinya:** Kenaikan harga DIDUKUNG oleh pembelian besar. Momentum kuat.
**Kenapa threshold ketat (SRI > 3.0):** Sebelumnya SRI > 1.0 → terlalu banyak false positive. Backtest menunjukkan SRI > 3.0 lebih akurat.

#### 🟢 SPRING — Pegas Siap Mental
**Kondisi:** Harga TURUN >1% + tapi SM masih dominan >60% + SM cukup aktif.
**Artinya:** Harga jatuh tapi big player justru beli. Seperti pegas ditekan → siap mental ke atas.
**Catatan:** Ini contrarian signal — beli saat harga turun. Win rate historis tinggi, reward besar.

#### 🟠 UPTHRUST — Jebakan Naik
**Kondisi:** Harga naik >2% + tapi BM dominan >60% + big player lebih banyak jual (RPR > 0.6).
**Artinya:** Harga naik TANPA dukungan big player. Big player malah manfaatkan kenaikan untuk jualan. Harga kemungkinan reversal turun.
**Kenapa RSM < 40%:** Sebelumnya pakai RPR > 0.5 → terlalu longgar (hampir semua saham masuk). RSM < 40% memastikan BM benar-benar dominan.

#### 🔴 DISTRI — Distribusi
**Kondisi:** BM dominan >60% + harga turun >0.5% + SM masih aktif (jual, bukan diam).
**Artinya:** Big player sedang buang barang secara aktif.
**Fallback (no gain data):** Kalau gain% tidak tersedia tapi RSM < 35% dan SRI > 0.8 → tetap DISTRI.

#### 🔵 ABSORB — Absorpsi
**Kondisi:** SM SANGAT aktif (SRI > 2.0) + SM dominan >65% + harga FLAT (|gain| < 1.5%).
**Artinya:** SM belanja besar-besaran tapi harga tidak bergerak. Mereka sengaja beli pelan-pelan di harga yang sama supaya tidak menaikkan harga. Fase sebelum breakout.
**Insight:** MES di sini akan rendah (< 0.5) karena effort tinggi tapi result rendah.

#### 🟢 ACCUM — Akumulasi
**Kondisi:** SM dominan >60% + SM di atas rata-rata (SRI > 1.0) + tidak memenuhi kriteria phase lain.
**Artinya:** Ada pembelian SM yang jelas tapi belum se-agresif ABSORB atau se-eksplosif SOS.
**Kenapa bukan catch-all:** Sebelumnya ACCUM = CM > 0 (semua yang positif). Ini menghasilkan 16,000+ signal palsu. Sekarang butuh RSM > 60% + SRI > 1.0.

#### ⚪ NEUTRAL
**Kondisi:** RSM antara 35-60% atau SRI terlalu rendah.
**Artinya:** Tidak ada sinyal arah yang jelas. SM dan BM seimbang.

---

## 5. Algoritma Action Signal

### 5.1 Decision Tree

```
INPUT: phase, gain

IF phase = SOS:
    IF gain < 5% → BUY    (masih awal, harga belum lari jauh)
    IF gain ≥ 5% → HOLD   (sudah naik signifikan, jangan kejar)

IF phase = SPRING → BUY
IF phase = ABSORB → BUY
IF phase = ACCUM  → BUY

IF phase = UPTHRUST → SELL
IF phase = DISTRI   → SELL

IF phase = NEUTRAL → HOLD
```

### 5.2 Interpretasi Action

| Action | Untuk yang BELUM punya posisi | Untuk yang SUDAH punya posisi |
|--------|-------------------------------|-------------------------------|
| 🚀 BUY | Entry (beli) | Tambah posisi / hold |
| ⌛ HOLD | Wait & see, belum entry | Tahan, jangan jual dulu |
| ⚠️ SELL | Jangan beli | Take profit / cut loss |

---

## 6. Di Mana Phase Dihitung

**KRITIS:** Phase dihitung di **3 lokasi** yang HARUS identik:

### 6.1 `app.py` → `/api/flow` (PRIMARY)
- Dihitung **on-the-fly** dari range data yang dipilih user
- RSM, RPR dari SUM seluruh range (bukan single day)
- SRI dari latest date (butuh 10-day history)
- Gain% dari stored `price_close` di DB
- **Ini yang ditampilkan di dashboard**

### 6.2 `scraper_daily.py` → `_classify_phase()`
- Dihitung saat `compute_analytics_for_date()` run (daily 17:00 WIB)
- Disimpan di `eod_summary.phase` dan `eod_summary.action`
- Digunakan sebagai **fallback** kalau on-the-fly computation gagal
- **Signature:** `_classify_phase(sri, rsm, rpr, pchg, price, low5, volx_gap)`

### 6.3 `scraper_daily.py` → `_compute_phase_action()`
- Digunakan oleh **backtest engine**
- Input: sm, bm, sri, gain, tx_sm, tx_bm
- Hitung RSM dan RPR internal lalu apply decision tree yang sama
- **HARUS sync dengan #6.1**

### ⚠️ Kalau ubah threshold di satu tempat, UBAH DI KETIGA TEMPAT.

---

## 7. Backtest Engine

### 7.1 Pair-Based Backtest (Versi Terbaru)

Tidak mengukur signal individual, tapi **pasangan BUY→SELL**:

```
Untuk setiap ticker, scan signal kronologis:
  Hari 1: ACCUM (BUY)  → Buka posisi di OPEN hari 2
  Hari 3: NEUTRAL (HOLD) → hold, tidak ngapa-ngapain
  Hari 5: ACCUM (BUY)  → sudah punya posisi, SKIP
  Hari 8: DISTRI (SELL) → Tutup posisi di OPEN hari 9
           → Entry = OPEN hari 2
           → Exit  = OPEN hari 9
           → Profit = (exit - entry) / entry × 100%
           → Duration = 7 hari
           → Dicatat sebagai trade: ACCUM → DISTRI
```

**Rules:**
- Entry price = OPEN hari setelah BUY signal (realistis: trader lihat signal malam, beli pagi)
- Exit price = OPEN hari setelah SELL signal
- Duplicate BUY saat sudah punya posisi = SKIP
- HOLD/NEUTRAL = tidak buka/tutup posisi

### 7.2 Metrik Leaderboard

| Metrik | Formula |
|--------|---------|
| Win Rate | `wins / total_trades × 100` |
| Avg Profit | `SUM(profit%) / total_trades` |
| Avg Win | `SUM(profit% where > 0) / wins` |
| Avg Loss | `SUM(profit% where ≤ 0) / losses` |
| Avg Duration | `SUM(duration_days) / total_trades` |
| **Expectancy** | `(Win% × Avg Win) − (Loss% × |Avg Loss|)` |

**Expectancy > 0 = strategi menguntungkan dalam jangka panjang.**

### 7.3 Hasil Backtest Terakhir (30 hari, April 2026)

| Entry | Exit | Trades | Win Rate | Avg Profit | Expectancy |
|-------|------|--------|----------|------------|------------|
| ACCUM | UPTHRUST | 76 | 63.2% | +4.64% | +4.64% |
| SOS | UPTHRUST | 3 | 100% | +4.32% | +4.32% |
| SPRING | UPTHRUST | 16 | 75% | +3.8% | +3.8% |
| ABSORB | UPTHRUST | 3 | 66.7% | +2.22% | +2.22% |
| ACCUM | DISTRI | 63 | 44.4% | +0.7% | +0.7% |
| ABSORB | DISTRI | 10 | 30% | -2.95% | -2.95% |

**Insight:** Exit di UPTHRUST konsisten lebih baik dari DISTRI.

---

## 8. Kelemahan & Area Improvement

### 8.1 Threshold Statis
Semua threshold (RSM > 65%, SRI > 3.0, gain > 2%) adalah angka tetap. Saham dengan volatilitas tinggi butuh threshold berbeda dari saham blue chip. 

**Improvement:** Gunakan ATR (Average True Range) untuk normalize gain threshold per saham.

### 8.2 SRI Butuh Histori
SRI membutuhkan minimal 10 hari data. Saham yang baru muncul di data akan memiliki SRI tidak akurat.

**Improvement:** Fallback ke RSM saja kalau histori < 5 hari.

### 8.3 Single-Day Phase vs Multi-Day
Phase di dashboard dihitung dari **range** yang dipilih user. Kalau user pilih 30 hari, RSM dihitung dari total 30 hari. Ini bisa misleading karena:
- Minggu 1-3: ACCUM (SM dominan)
- Minggu 4: DISTRI (BM dominan)
- Total 30 hari: RSM mungkin masih > 60% → tampil ACCUM padahal sekarang sudah DISTRI.

**Improvement:** Tampilkan juga phase hari terakhir sebagai indikator trend terbaru.

### 8.4 Gain% Dari Yahoo
Close price di-fetch dari Yahoo Finance. Kalau Yahoo down atau rate-limited, gain% = NULL → phase yang butuh gain (SOS, SPRING, UPTHRUST) tidak bisa terdeteksi.

**Improvement:** Gunakan data close price dari broker API yang lebih reliable (kalau ada).

### 8.5 MF Data Tidak Digunakan
MF+/MF- (Money Flow) saat ini TIDAK masuk perhitungan phase. Hanya ditampilkan di tabel. Padahal MF negatif besar + CM positif bisa jadi red flag.

**Improvement:** Tambahkan MF sebagai sanity check. Misalnya: kalau NET MF < -1B dan phase BUY → downgrade ke HOLD.

### 8.6 HOLD Setelah SOS
Dari backtest: SOS+HOLD (gain ≥ 5%) punya return -3.86%. Saham yang sudah naik >5% cenderung reversal.

**Improvement:** Pertimbangkan ubah SOS+HOLD (gain ≥ 5%) menjadi SELL atau tambah threshold berdasarkan RSM saat itu.

### 8.7 Volume Konfirmasi
Dalam teori Wyckoff, volume harus mengkonfirmasi pergerakan. Saat ini kita hanya pakai TX count, bukan value transaksi × volume.

**Improvement:** Integrasikan `vol_x` (volume multiplier) ke dalam phase classification.

---

## 9. Pseudocode Lengkap

```python
def classify(ticker_data_for_range):
    # Input
    sm_val = SUM of all SM transactions in range
    bm_val = SUM of all BM transactions in range  
    tx_sm  = COUNT of SM signals in range
    tx_bm  = COUNT of BM signals in range
    
    # Derived
    cm  = sm_val - bm_val
    rsm = sm_val / (sm_val + bm_val) * 100    # percentage
    rpr = tx_bm / (tx_sm + tx_bm)              # ratio 0-1
    
    # From latest day (needs history)
    sri = sm_val_latest / SMA(sm_val, 10 days)
    
    # From Yahoo close prices
    gain = (close_latest - close_prev) / close_prev * 100
    
    # Decision tree (ORDER MATTERS)
    if gain > 2 and rsm > 65 and sri > 3.0:
        phase = "SOS"
        action = "BUY" if gain < 5 else "HOLD"
    
    elif gain < -1 and rsm > 60 and sri > 1.5:
        phase = "SPRING"
        action = "BUY"
    
    elif gain > 2 and rsm < 40 and rpr > 0.6:
        phase = "UPTHRUST"
        action = "SELL"
    
    elif rsm < 40 and gain < -0.5 and sri > 1.0:
        phase = "DISTRI"
        action = "SELL"
    
    elif sri > 2.0 and rsm > 65 and abs(gain) < 1.5:
        phase = "ABSORB"
        action = "BUY"
    
    elif rsm > 60 and sri > 1.0:
        phase = "ACCUM"
        action = "BUY"
    
    elif rsm < 35 and sri > 0.8:
        phase = "DISTRI"
        action = "SELL"
    
    else:
        phase = "NEUTRAL"
        action = "HOLD"
    
    return phase, action
```

---

## 10. Tabel Referensi Cepat

### Phase → Kondisi

| Phase | RSM | SRI | Gain% | RPR | Lainnya |
|-------|-----|-----|-------|-----|---------|
| SOS | > 65% | > 3.0 | > 2% | - | - |
| SPRING | > 60% | > 1.5 | < -1% | - | - |
| UPTHRUST | < 40% | - | > 2% | > 0.6 | - |
| DISTRI | < 40% | > 1.0 | < -0.5% | - | - |
| ABSORB | > 65% | > 2.0 | |gain| < 1.5% | - | - |
| ACCUM | > 60% | > 1.0 | - | - | Catch setelah 5 di atas |
| DISTRI (fallback) | < 35% | > 0.8 | - | - | - |
| NEUTRAL | 35-60% | - | - | - | Default |

### Phase → Action

| Phase | Action | Kondisi Tambahan |
|-------|--------|-----------------|
| SOS | BUY | gain < 5% |
| SOS | HOLD | gain ≥ 5% |
| SPRING | BUY | - |
| ABSORB | BUY | - |
| ACCUM | BUY | - |
| UPTHRUST | SELL | - |
| DISTRI | SELL | - |
| NEUTRAL | HOLD | - |

---

*Dokumen ini di-generate berdasarkan kode aktual di `app.py` dan `scraper_daily.py` per April 2026.*
*Untuk meng-improve akurasi, jalankan backtest dengan threshold baru lalu bandingkan expectancy.*


### improvement in the future
- backtest for each indeX 
- 