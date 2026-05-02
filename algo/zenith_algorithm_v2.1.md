# ZENITH — Final Implementation Spec v2.1
**Dokumen ini adalah spesifikasi teknis final hasil diskusi.**
Tujuan: menjadi single source of truth sebelum implementasi kode dimulai.
Last updated: April 2026

---

## 1. Konteks Sistem

Zenith adalah platform Bandarmologi untuk IDX (Bursa Efek Indonesia).
Data SM (Smart Money) dan BM (Bad Money) berasal dari bot Telegram "Joker" yang
memposting transaksi big player — **bukan retail**. Ini penting karena:
- SM = institusi/big player yang BELI
- BM = institusi/big player yang JUAL
- Panic buying/selling tidak relevan di konteks ini karena pelakunya adalah big player

**Tech stack:** Python Flask, SQLite, Telethon, Railway

---

## 2. Arsitektur Kode (DRY)

Sebelumnya phase logic ada di **3 tempat terpisah** yang harus selalu disync manual:

| File | Fungsi | Masalah |
|------|--------|---------|
| `scraper_daily.py` | `_classify_phase()` | Logic duplikat |
| `scraper_daily.py` | `_compute_phase_action()` | Logic duplikat |
| `app.py` | `/api/flow` route | Logic duplikat |

**Solusi: Sentralisasi ke `logic.py`**

```
zenith_project/
├── app.py              — import dari logic.py
├── scraper_daily.py    — import dari logic.py
├── logic.py            — NEW: single source of truth untuk semua phase logic
```

`logic.py` berisi:
- `floor_to_fraction(price)` — pembulatan harga ke fraksi IDX
- `classify_zenith_v2_1(...)` — phase classification
- `get_action(phase, pchg, atr_pct)` — action signal
- `get_watch_flag(phase, pchg, atr_pct)` — ARB watch flag
- `get_suggested_sl(price_close, atr_pct)` — stop loss calculation

**Manfaat:** Jika threshold SOS diubah dari 3.0 → 3.5, cukup ubah 1 baris di `logic.py`.
Backtest, dashboard live, dan analytics otomatis sinkron.

---

## 3. Metrik Analitik

### 3.1 RSM — Rasio Smart Money (% value)
```
RSM = sm_val / (sm_val + bm_val) * 100
```
- Fallback: RSM = 50 jika sm_val + bm_val = 0
- Ukuran **proporsi nilai transaksi**, bukan jumlah transaksi

### 3.2 SRI — SM Relative Intensity (Trimmed Mean)
```python
sm_history = 10 hari terakhir sm_val (hanya nilai > 0, dalam window 20 hari bursa)

# Trimmed Mean: buang 1 nilai tertinggi untuk eliminasi outlier event besar
if len(sm_history) >= 3:
    vals = sorted(sm_history)
    trimmed = vals[:-1]  # buang 1 tertinggi
    sm_sma10 = sum(trimmed) / len(trimmed)
else:
    sm_sma10 = sum(sm_history) / len(sm_history) if sm_history else 0

SRI = sm_val_today / sm_sma10 if sm_sma10 > 0 else 0
```

**Kenapa trimmed mean?**
Hari event besar (rights issue, RUPS, rumor) bisa menghasilkan SM 500M di tengah
hari-hari normal 5M. Outlier ini mencemari SMA sehingga SRI hari-hari setelahnya
selalu kecil walau SM tetap aktif. Buang 1 tertinggi = eliminasi 1 hari outlier per window.

**Edge case SRI = 0:**
Jika sm_sma10 = 0 (SM tidak pernah ada dalam window) dan hari ini SM > 0, SRI = 0.
SM yang baru pertama kali masuk tidak akan trigger SOS/ABSORB/SPRING.
Dianggap acceptable — ATR 14 hari juga belum tersedia, sehingga threshold
default 2.5% sudah menjadi natural filter tersendiri.

### 3.3 RPR — Rasio Tekanan Jual
```
RPR = tx_bm / (tx_sm + tx_bm)
```
- Fallback: RPR = 0.5 jika tx_sm + tx_bm = 0
- Mengukur **proporsi jumlah transaksi jual** oleh big player
- **BUKAN** retail participation — BM = big player yang jual
- Minimum tx tidak di-enforce karena tidak semua saham IDX terdeteksi oleh Joker

### 3.4 BM_SMA10 — Baseline Bad Money (Simple Mean)
```python
# Ambil dalam window 20 hari bursa (cutoff ~28 hari kalender)
bm_history = 10 hari terakhir bm_val dalam window (termasuk nilai 0)
bm_sma10 = sum(bm_history) / len(bm_history) if bm_history else 0
```
Pakai simple mean (bukan trimmed) karena BM digunakan sebagai **activity gate**,
bukan basis rasio. Kita ingin baseline yang realistis termasuk hari-hari sepi.

**Edge case bm_sma10 = 0:**
```python
if bm_sma10 == 0:
    bm_gate = True   # tidak ada history = tidak difilter
else:
    bm_gate = bm_val > bm_sma10 * 0.5
```

### 3.5 ATR% — Average True Range
```python
daily_changes = [abs((prices[j] - prices[j+1]) / prices[j+1] * 100)
                 for j in range(len(prices) - 1)
                 if prices[j] and prices[j+1] > 0]
atr_pct = sum(daily_changes) / len(daily_changes) if daily_changes else None
```
- Default: 2.5% jika tidak tersedia
- Dihitung dari price_close history 14 hari
- Tersedia hanya jika ada minimal 3 data price_close

### 3.6 MES — Market Efficiency Score
```
MES = |gain%| / SRI
```
Low MES = SM beli banyak tapi harga tidak bergerak = absorption / stealth accumulation.

### 3.7 Volx Gap
```
Volx Gap = (price_close - vwap_sm) / price_close * 100
```
Positif = harga tutup di atas rata-rata harga beli SM = SM sudah floating profit.

---

## 4. Dry Spell — Batasan Window History

**Masalah:** Jika saham tidak muncul di Joker selama > 10 hari, query `LIMIT 14`
tanpa filter tanggal bisa mengambil data dari 2-3 bulan lalu. SRI dan bm_sma10
yang dihitung dari data lama vs transaksi hari ini menjadi tidak relevan.

**Solusi:** Tambah cutoff waktu pada semua query history:

```python
# ~20 hari bursa = ~28 hari kalender
cutoff_date = (datetime.now(WIB) - timedelta(days=28)).strftime("%d-%m-%Y")

hist = conn.execute("""
    SELECT sm_val, bm_val, price_close FROM eod_summary
    WHERE ticker = ?
      AND substr(date,7,4)||substr(date,4,2)||substr(date,1,2)
          >= substr(?,7,4)||substr(?,4,2)||substr(?,1,2)
    ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2) DESC
    LIMIT 14
""", [tk, cutoff_date, cutoff_date, cutoff_date]).fetchall()

# Jika tidak ada data dalam window → treat as fresh (sama seperti saham baru)
if not hist:
    sm_sma10 = 0
    bm_sma10 = 0
    sri = 0
```

---

## 5. Dynamic Thresholds (ATR-Adjusted)

```python
atr = atr_pct if atr_pct and atr_pct > 0 else 2.5

th_up    = max(atr * 0.8, 1.0)   # kenaikan signifikan (min 1%)
th_down  = max(atr * 0.4, 0.5)   # penurunan signifikan (min 0.5%)
th_flat  = atr * 0.5             # harga dianggap flat
th_sos_h = max(atr * 2.0, 5.0)  # sudah terlalu tinggi untuk BUY SOS
```

### Contoh referensi per tipe saham:
| Saham | ATR% | th_up | th_down | th_flat | th_sos_h |
|-------|------|-------|---------|---------|----------|
| BBCA (blue chip) | 1.2% | 1.0% | 0.5% | 0.6% | 5.0% |
| ANTM (mid cap)   | 2.5% | 2.0% | 1.0% | 1.25% | 5.0% |
| PADI (volatile)  | 5.0% | 4.0% | 2.0% | 2.5% | 10.0% |

---

## 6. Decision Tree Phase Classification v2.1

Evaluasi dari atas ke bawah. Fase pertama yang terpenuhi dipilih.

```python
def classify_zenith_v2_1(sri, rsm, rpr, pchg, bm_val, bm_sma10, atr_pct=None):
    """
    Single source of truth untuk phase classification Zenith v2.1.
    Dipanggil dari logic.py, diimport oleh app.py dan scraper_daily.py.
    """
    atr = atr_pct if atr_pct and atr_pct > 0 else 2.5
    th_up    = max(atr * 0.8, 1.0)
    th_down  = max(atr * 0.4, 0.5)
    th_flat  = atr * 0.5
    th_sos_h = max(atr * 2.0, 5.0)

    # BM Gate: pastikan BM hari ini bukan sekadar noise dibanding historynya
    bm_gate = True if bm_sma10 == 0 else (bm_val > bm_sma10 * 0.5)

    if pchg is None:
        return "NEUTRAL"

    # 1. SOS — Sign of Strength
    if pchg > th_up and rsm > 65 and sri > 3.0:
        return "SOS"

    # 2. UPTHRUST — Trap naik, big player buang di harga tinggi
    if pchg > th_up and rsm < 40 and rpr > 0.6:
        return "UPTHRUST"

    # 3. ABSORB — Akumulasi diam-diam, harga flat
    # gain > -th_down: memastikan tidak overlap dengan zona SPRING
    if sri > 2.0 and rsm > 65 and pchg > -th_down and abs(pchg) < th_flat:
        return "ABSORB"

    # 4. SPRING — Harga turun tapi SM aktif akumulasi
    if pchg < -th_down and rsm > 60 and sri > 1.5:
        return "SPRING"

    # 5. DISTRI — Distribusi aktif
    # rpr > 0.4 : proporsi transaksi BM cukup dominan
    # bm_gate   : BM hari ini bukan sekadar noise vs historynya
    # SRI sengaja TIDAK dipakai — blind spot fix:
    #   SM absen bukan berarti tidak ada distribusi
    if rsm < 40 and pchg < -(th_down * 0.5) and rpr > 0.4 and bm_gate:
        return "DISTRI"

    # 6. ACCUM — Akumulasi bertahap, SM dominan
    if rsm > 60 and sri > 1.0:
        return "ACCUM"

    # 7. DISTRI Fallback — BM sangat dominan dari sisi transaksi
    if rsm < 35 and rpr > 0.5 and bm_gate:
        return "DISTRI"

    return "NEUTRAL"


def get_action(phase, pchg, atr_pct=None):
    atr = atr_pct if atr_pct and atr_pct > 0 else 2.5
    th_sos_h = max(atr * 2.0, 5.0)

    if phase == "SOS":
        return "BUY" if (pchg is not None and pchg < th_sos_h) else "HOLD"
    if phase in ("SPRING", "ABSORB", "ACCUM"):
        return "BUY"
    if phase in ("UPTHRUST", "DISTRI"):
        return "SELL"
    return "HOLD"
```

---

## 7. ARB Watch Flag

```python
def get_watch_flag(phase, pchg, atr_pct=None):
    """Deteksi SPRING yang terjadi di penurunan ekstrem (mendekati ARB)."""
    atr = atr_pct if atr_pct and atr_pct > 0 else 2.5
    if phase == "SPRING" and pchg is not None and pchg < -(atr * 1.5):
        return "ARB_SPRING"
    return None
```

**Kenapa 1.5× ATR?**
ATR mencerminkan volatilitas normal harian. Penurunan > 1.5× ATR berarti tekanan
jual sudah melampaui range normal — mendekati kondisi Auto Rejection Bawah (ARB).
Big player yang masuk di kondisi ini mungkin benar secara Wyckoff, tapi risikonya
lebih tinggi karena ARB bisa berlanjut beberapa hari.

ARB_SPRING **bukan phase baru** — phase tetap SPRING, action tetap BUY,
tapi user mendapat visual warning di dashboard.

---

## 8. Suggested Stop Loss

### Fraksi Harga IDX

Di IDX, harga saham harus mengikuti price tick (fraksi). SL harus dibulatkan
ke fraksi terdekat **di bawahnya** agar valid dipasang di sistem trading.

| Rentang Harga | Fraksi |
|---------------|--------|
| < 200         | 1      |
| 200 – 499     | 2      |
| 500 – 1.999   | 5      |
| 2.000 – 4.999 | 10     |
| ≥ 5.000       | 25     |

```python
def floor_to_fraction(price: float) -> int:
    """Bulatkan harga ke fraksi IDX terdekat di bawahnya."""
    if price < 200:    f = 1
    elif price < 500:  f = 2
    elif price < 2000: f = 5
    elif price < 5000: f = 10
    else:              f = 25
    return int(price // f) * f


def get_suggested_sl(price_close: float, atr_pct: float):
    """
    Hitung Stop Loss otomatis berbasis ATR, dibulatkan ke fraksi IDX.
    Formula: SL = price_close × (1 - ATR% × 2.0)
    """
    if not price_close or not atr_pct:
        return None
    raw_sl = price_close * (1 - (atr_pct / 100) * 2.0)
    return floor_to_fraction(raw_sl)
```

**Contoh ANTM harga 2000, ATR 3%:**
- Raw SL: `2000 × (1 - 0.06) = 1880`
- Fraksi 500–1999 = 5 → `floor(1880 / 5) * 5 = 1880` ✓

**Contoh BBRI harga 4250, ATR 2%:**
- Raw SL: `4250 × (1 - 0.04) = 4080`
- Fraksi 2000–4999 = 10 → `floor(4080 / 10) * 10 = 4080` ✓

**Catatan:** `suggested_sl` dihitung untuk semua phase. Relevansinya paling tinggi
untuk BUY signals (SOS, SPRING, ABSORB, ACCUM).

---

## 9. Perubahan Database Schema

Tambah 4 kolom baru ke `eod_summary`:

| Kolom | Type | Keterangan |
|-------|------|------------|
| `sm_sma10` | REAL | Trimmed mean SM 10 hari (untuk kolom "SM Avg" di UI) |
| `bm_sma10` | REAL | Simple mean BM 10 hari (untuk DISTRI gate) |
| `watch` | TEXT | "ARB_SPRING" atau NULL |
| `suggested_sl` | REAL | Harga SL valid (sudah dibulatkan ke fraksi IDX) atau NULL |

```sql
ALTER TABLE eod_summary ADD COLUMN sm_sma10 REAL;
ALTER TABLE eod_summary ADD COLUMN bm_sma10 REAL;
ALTER TABLE eod_summary ADD COLUMN watch TEXT;
ALTER TABLE eod_summary ADD COLUMN suggested_sl REAL;
```

Atau via `ensure_summary_table()` dengan DROP + recreate jika schema mismatch.

⚠️ **Sebelum ALTER/recreate: backup DB dulu via `/admin/download-db`**
agar tidak perlu backfill ulang `price_close` dari Yahoo Finance.

---

## 10. Perubahan `compute_analytics_for_date()` — scraper_daily.py

```python
from logic import classify_zenith_v2_1, get_action, get_watch_flag, get_suggested_sl

# Cutoff window ~20 hari bursa
cutoff_date = (datetime.now(WIB) - timedelta(days=28)).strftime("%d-%m-%Y")

hist = conn.execute("""
    SELECT sm_val, bm_val, price_close FROM eod_summary
    WHERE ticker = ?
      AND substr(date,7,4)||substr(date,4,2)||substr(date,1,2)
          >= substr(?,7,4)||substr(?,4,2)||substr(?,1,2)
    ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2) DESC
    LIMIT 14
""", [tk, cutoff_date, cutoff_date, cutoff_date]).fetchall()

# SM_SMA10 (Trimmed Mean)
sm_h = [h["sm_val"] or 0 for h in hist if (h["sm_val"] or 0) > 0]
if len(sm_h) >= 3:
    trimmed = sorted(sm_h[:10])[:-1]
else:
    trimmed = sm_h[:10]
sm_sma10 = round(sum(trimmed) / len(trimmed), 2) if trimmed else 0
sri = round(sm / sm_sma10, 2) if sm_sma10 > 0 else 0

# BM_SMA10 (Simple Mean)
bm_h = [h["bm_val"] or 0 for h in hist[:10]]
bm_sma10 = round(sum(bm_h) / len(bm_h), 2) if bm_h else 0

# Phase, Action, Watch, SL
phase        = classify_zenith_v2_1(sri, rsm_val, rpr, pchg, bm, bm_sma10, atr_pct)
action       = get_action(phase, pchg, atr_pct)
watch        = get_watch_flag(phase, pchg, atr_pct)
suggested_sl = get_suggested_sl(pc, atr_pct)

# UPDATE DB
conn.execute("""
    UPDATE eod_summary
    SET price_change_pct=?, sri=?, mes=?, volx_gap=?, rpr=?,
        atr_pct=?, sm_sma10=?, bm_sma10=?, phase=?, action=?,
        watch=?, suggested_sl=?
    WHERE date=? AND ticker=?
""", [pchg, sri, mes, vg, rpr,
      atr_pct, sm_sma10, bm_sma10, phase, action,
      watch, suggested_sl,
      date_str, tk])
```

---

## 11. Perubahan `_compute_phase_action()` — scraper_daily.py (Backtest Engine)

```python
from logic import classify_zenith_v2_1, get_action

def _compute_phase_action(sm, bm, sri, gain, tx_sm, tx_bm, bm_sma10=0, atr_pct=None):
    total_val = sm + bm
    rsm = (sm / total_val * 100) if total_val > 0 else 50
    ttx = tx_sm + tx_bm
    rpr = tx_bm / ttx if ttx > 0 else 0.5

    phase  = classify_zenith_v2_1(sri, rsm, rpr, gain, bm, bm_sma10, atr_pct)
    action = get_action(phase, gain, atr_pct)
    return phase, action
```

Backtest engine perlu pass `bm_sma10` dari kolom `eod_summary` yang sudah tersimpan.

---

## 12. Perubahan `/api/flow` — app.py

```python
from logic import classify_zenith_v2_1, get_action, get_watch_flag, get_suggested_sl

# Query tambahan: ambil bm_sma10 dari eod_summary latest date
a_rows = conn.execute("""
    SELECT ticker, price_close, sri, volx_gap, vwap_sm, vwap_bm,
           atr_pct, sm_sma10, bm_sma10
    FROM eod_summary WHERE date = ?
""", [latest_date]).fetchall()

# Dalam loop ticker:
bm_sma10 = a.get("bm_sma10") or 0

phase        = classify_zenith_v2_1(sri, rsm, rpr_val, gain, bm, bm_sma10, atr_pct)
action       = get_action(phase, gain, atr_pct)
watch        = get_watch_flag(phase, gain, atr_pct)
suggested_sl = get_suggested_sl(g.get("price") or a.get("price_close"), atr_pct)
```

### API Response tambahan:
```python
{
    # ... existing fields ...
    "watch":        watch,           # "ARB_SPRING" atau null
    "suggested_sl": suggested_sl,    # harga int (sudah fraksi IDX) atau null
    "sm_sma10":     sm_sma10,        # untuk kolom "SM Avg" di UI
    "bm_sma10":     bm_sma10,        # untuk debug/cross-check
}
```

---

## 13. Frontend `flow.html`

### ARB Watch Flag:
```html
<!-- Jika watch == "ARB_SPRING", tampilkan dot kuning sebelum teks phase -->
<span class="phase-cell">
  <span
    class="watch-dot"
    title="Peringatan: Penurunan > 1.5x ATR — Risiko ARB, butuh konfirmasi"
  >●</span>
  SPRING
</span>

<style>
.watch-dot {
    color: #f5c518;
    margin-right: 4px;
    cursor: help;
}
</style>
```

### Kolom Baru:
- **"Exit/SL"**: Tampilkan `suggested_sl` sebagai harga integer
- **"SM Avg"** (opsional): Tampilkan `sm_sma10` untuk cross-check aktivitas SM

---

## 14. Keputusan yang Sengaja Tidak Diimplementasi

| Item | Alasan |
|------|--------|
| Minimum tx_bm absolute | Tidak semua saham IDX terdeteksi SM/BM oleh Joker — angka absolut tidak fair antar saham |
| Filter saham baru (history < N hari) | ATR 14 hari belum tersedia = natural filter sudah cukup |
| Phase "CONTEST" untuk SM vs BM sama-sama aktif | Out of scope Wyckoff — jika RSM < 40 maka BM dominan by value, DISTRI tetap correct walau SRI tinggi |
| Multi-day range phase accuracy | Dideferral — butuh diskusi tersendiri tentang pendekatan optimal |

---

## 15. Ringkasan Perbedaan v2.0 → v2.1

| Aspek | v2.0 (lama) | v2.1 (final) |
|-------|-------------|--------------|
| Arsitektur | Logic duplikat di 3 tempat | Terpusat di `logic.py` |
| SRI computation | Simple SMA10 | Trimmed Mean (buang 1 tertinggi) |
| History window | Tidak ada cutoff waktu | Cutoff 28 hari kalender (~20 hari bursa) |
| DISTRI condition | `rsm<40 AND gain<-x AND sri>1.0` | `rsm<40 AND gain<-x AND rpr>0.4 AND bm_gate` |
| DISTRI fallback | `rsm<35 AND sri>0.8` | `rsm<35 AND rpr>0.5 AND bm_gate` |
| BM activity gate | Tidak ada | `bm_val > bm_sma10 * 0.5` |
| ABSORB vs SPRING overlap | Ada overlap di zona tengah | `gain > -th_down` pada ABSORB — mutually exclusive |
| Prioritas urutan | SOS→SPRING→UPTHRUST→DISTRI→ABSORB | SOS→UPTHRUST→ABSORB→SPRING→DISTRI→ACCUM |
| ARB detection | Tidak ada | `watch = "ARB_SPRING"` jika SPRING + gain < -(ATR×1.5) |
| Stop Loss | Tidak ada | `SL = price × (1 - ATR%×2.0)`, dibulatkan ke fraksi IDX |
| Dead parameters | `price, low5, volx_gap` di `_classify_phase` | Dihapus |
| Kolom DB baru | — | `sm_sma10`, `bm_sma10`, `watch`, `suggested_sl` |
