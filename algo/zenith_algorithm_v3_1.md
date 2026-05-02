# ZENITH — Algorithm Specification v3.1 (Official)
**Dokumen ini adalah spesifikasi teknis final untuk Zenith v3.1.**
Menggabungkan stabilitas klasifikasi v2.1 dengan Action Gate baru dari v3.0.
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
- `classify_zenith_v3_1(...)` — phase classification (v2.1 + SOS upgrade)
- `get_action(phase, pchg, atr_pct, bm_val, bm_sma10, watch_flag)` — action dengan Gate A/B/C
- `get_watch_flag(phase, pchg, atr_pct)` — ARB watch flag

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
**Urutan tetap sama dengan v2.1.** Satu-satunya perubahan pada klasifikasi: SOS diperluas dengan OR clause.

```python
def classify_zenith_v3_1(sri, rsm, rpr, pchg, bm_val, bm_sma10, atr_pct=None):
    """
    Single source of truth untuk phase classification Zenith v3.1.
    Phase logic murni dari v2.1. Satu perubahan: SOS tambah OR clause.
    """
    atr      = atr_pct if atr_pct and atr_pct > 0 else 2.5
    th_up    = max(atr * 0.8, 1.0)
    th_down  = max(atr * 0.4, 0.5)
    th_flat  = atr * 0.5

    # BM Gate: pastikan BM hari ini bukan sekadar noise dibanding historynya
    bm_gate = True if bm_sma10 == 0 else (bm_val > bm_sma10 * 0.5)

    if pchg is None:
        return "NEUTRAL"

    # 1. SOS — Sign of Strength
    # v3.1: OR clause — jika SM sangat agresif (SRI > 4.0), RSM dilonggarkan ke > 60%
    # Menampung kasus "SM agresif meski ada perlawanan BM"
    if pchg > th_up and ((rsm > 65 and sri > 3.0) or (rsm > 60 and sri > 4.0)):
        return "SOS"

    # 2. UPTHRUST — Trap naik, big player buang di harga tinggi
    # Tidak ada syarat SRI — jebakan paling maut justru saat SM diam tapi BM jual
    if pchg > th_up and rsm < 40 and rpr > 0.6:
        return "UPTHRUST"

    # 3. ABSORB — Akumulasi diam-diam, harga flat
    # pchg > -th_down: memastikan tidak overlap dengan zona SPRING
    if sri > 2.0 and rsm > 65 and pchg > -th_down and abs(pchg) < th_flat:
        return "ABSORB"

    # 4. SPRING — Harga turun tapi SM aktif akumulasi
    if pchg < -th_down and rsm > 60 and sri > 1.5:
        return "SPRING"

    # 5. DISTRI — Distribusi aktif
    # bm_gate dipertahankan: mencegah DISTRI firing saat BM cuma noise
    if rsm < 40 and pchg < -(th_down * 0.5) and rpr > 0.4 and bm_gate:
        return "DISTRI"

    # 6. ACCUM — Akumulasi bertahap, SM dominan
    if rsm > 60 and sri > 1.0:
        return "ACCUM"

    # 7. DISTRI Fallback — BM sangat dominan dari sisi transaksi
    if rsm < 35 and rpr > 0.5 and bm_gate:
        return "DISTRI"

    return "NEUTRAL"


def get_action(phase, pchg, atr_pct=None, bm_val=0, bm_sma10=0, watch_flag=None):
    """
    Action signal dengan 3 Gate keamanan berlapis (v3.1).

    Gate A — Supply Gate:
        Jika bm_val > bm_sma10 * 3.0 → HOLD
        Ada tekanan jual masif (3x rata-rata), momentum SM berisiko terhenti.

    Gate B — ARB Safety:
        Jika watch_flag == "ARB_SPRING" → HOLD
        Action tetap HOLD di sistem; frontend tampilkan sebagai "WATCH" via watch_flag.
        Tidak membuat string action baru agar tidak break existing code.

    Gate C — Global Anti-Pucuk:
        Jika pchg >= th_sos_h untuk semua fase BUY → HOLD
        Mencegah FOMO/HAKA di semua fase, bukan hanya SOS.
    """
    atr      = atr_pct if atr_pct and atr_pct > 0 else 2.5
    th_sos_h = max(atr * 2.0, 5.0)

    BUY_PHASES  = ("SOS", "SPRING", "ABSORB", "ACCUM")
    SELL_PHASES = ("UPTHRUST", "DISTRI")

    if phase in SELL_PHASES:
        return "SELL"

    if phase not in BUY_PHASES:
        return "HOLD"

    # ── Gate A: Supply Gate ──
    # BM hari ini 3x lipat rata-rata normalnya = ada tembok penjual masif
    if bm_sma10 > 0 and bm_val > bm_sma10 * 3.0:
        return "HOLD"

    # ── Gate B: ARB Safety ──
    # SPRING dengan penurunan ekstrim → HOLD (frontend tampilkan sebagai WATCH via watch_flag)
    if watch_flag == "ARB_SPRING":
        return "HOLD"

    # ── Gate C: Global Anti-Pucuk ──
    # Semua fase BUY: jika harga sudah terlalu tinggi hari ini → HOLD
    if pchg is not None and pchg >= th_sos_h:
        return "HOLD"

    return "BUY"
```

### Catatan implementasi `get_action`:
- **Gate B**: `watch_flag` dipass dari `get_watch_flag()`. Action tetap `"HOLD"` di sistem — tidak ada string `"WATCH"`. Frontend menampilkan label `"⚠️ WATCH"` hanya berdasarkan `watch_flag == "ARB_SPRING"`, bukan dari action string. Ini memastikan tidak ada yang break di existing code.
- **Signature baru**: `bm_val` dan `bm_sma10` perlu di-pass dari caller (sudah tersedia di `compute_analytics_for_date` dan `/api/flow`).

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

ARB_SPRING **bukan phase baru** — phase tetap SPRING. Di v3.1, `get_action()` Gate B
akan return `"HOLD"` untuk kondisi ini. Frontend menampilkan `"⚠️ WATCH"` berdasarkan
`watch_flag == "ARB_SPRING"`, bukan dari action string — agar tidak ada string baru
yang perlu dihandle di seluruh codebase.

---

## 8. Perubahan Database Schema

`eod_summary` ditambah 3 kolom baru (v3.1, hapus `suggested_sl` yang ada di v2.1):

| Kolom | Type | Keterangan |
|-------|------|------------|
| `sm_sma10` | REAL | Trimmed mean SM 10 hari (untuk kolom "SM Avg" di UI) |
| `bm_sma10` | REAL | Simple mean BM 10 hari (untuk DISTRI gate + Supply Gate) |
| `watch` | TEXT | "ARB_SPRING" atau NULL |

```sql
ALTER TABLE eod_summary ADD COLUMN sm_sma10 REAL;
ALTER TABLE eod_summary ADD COLUMN bm_sma10 REAL;
ALTER TABLE eod_summary ADD COLUMN watch    TEXT;
```

`trade_journal` — tabel baru untuk live position tracker:

| Kolom | Type | Keterangan |
|-------|------|------------|
| `id` | INTEGER PK | Auto increment |
| `ticker` | TEXT | Kode saham |
| `entry_phase` | TEXT | SOS / SPRING / ABSORB / ACCUM |
| `entry_date` | TEXT | DD-MM-YYYY |
| `buy_price` | REAL | Harga entry |
| `status` | TEXT | `open` atau `closed` |
| `exit_date` | TEXT | DD-MM-YYYY, NULL jika open |
| `sell_price` | REAL | Harga exit, NULL jika open |
| `gain_pct` | REAL | NULL jika open |
| `hold_days` | INTEGER | NULL jika open |
| `exit_reason` | TEXT | `SELL Signal` / `Stop Loss (-10%)` / NULL |
ALTER TABLE eod_summary ADD COLUMN sm_sma10 REAL;
ALTER TABLE eod_summary ADD COLUMN bm_sma10 REAL;
ALTER TABLE eod_summary ADD COLUMN watch TEXT;
```

Atau via `ensure_summary_table()` dengan DROP + recreate jika schema mismatch.

⚠️ **Sebelum ALTER/recreate: backup DB dulu via `/admin/backup-db`**
agar tidak perlu backfill ulang `price_close` dari Yahoo Finance.

---

## 9. Perubahan `compute_analytics_for_date()` — scraper_daily.py

```python
from logic import classify_zenith_v3_1, get_action, get_watch_flag

# ... SRI dan BM_SMA10 computation sama seperti v2.1 ...

# Phase, Action, Watch — v3.1: get_action sekarang perlu bm_val dan bm_sma10
watch  = get_watch_flag(phase, pchg, atr_pct)
phase  = classify_zenith_v3_1(sri, rsm_val, rpr, pchg, bm, bm_sma10, atr_pct)
action = get_action(phase, pchg, atr_pct, bm_val=bm, bm_sma10=bm_sma10, watch_flag=watch)

# UPDATE DB — suggested_sl dihapus
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
```

---

## 10. Perubahan `_compute_phase_action()` — scraper_daily.py (Backtest Engine)

```python
from logic import classify_zenith_v3_1, get_action

def _compute_phase_action(sm, bm, sri, gain, tx_sm, tx_bm, bm_sma10=0, atr_pct=None):
    total_val = sm + bm
    rsm = (sm / total_val * 100) if total_val > 0 else 50
    ttx = tx_sm + tx_bm
    rpr = tx_bm / ttx if ttx > 0 else 0.5

    phase  = classify_zenith_v3_1(sri, rsm, rpr, gain, bm, bm_sma10, atr_pct)
    watch  = get_watch_flag(phase, gain, atr_pct)
    action = get_action(phase, gain, atr_pct, bm_val=bm, bm_sma10=bm_sma10, watch_flag=watch)
    return phase, action
```

---

## 11. Perubahan `/api/flow` — app.py

```python
from logic import classify_zenith_v3_1, get_action, get_watch_flag

# Query: ambil bm_sma10 dari eod_summary latest date
a_rows = conn.execute("""
    SELECT ticker, price_close, sri, volx_gap, vwap_sm, vwap_bm,
           atr_pct, sm_sma10, bm_sma10, watch
    FROM eod_summary WHERE date = ?
""", [latest_date]).fetchall()

# Dalam loop ticker:
bm_sma10 = a.get("bm_sma10") or 0
bm_raw   = d.get("bm_val") or 0

phase  = classify_zenith_v3_1(sri, rsm, rpr_val, gain, bm_raw, bm_sma10, atr_pct)
watch  = get_watch_flag(phase, gain, atr_pct)
action = get_action(phase, gain, atr_pct, bm_val=bm_raw, bm_sma10=bm_sma10, watch_flag=watch)
```

### API Response:
```python
{
    # ... existing fields ...
    "watch":    watch,    # "ARB_SPRING" atau null
    "sm_sma10": sm_sma10, # untuk kolom "SM Avg" di UI
    "bm_sma10": bm_sma10, # untuk debug/cross-check
}
```

---

## 12. Frontend `flow.html`

### ARB Watch Flag:
```html
<!-- Jika watch == "ARB_SPRING", tampilkan dot kuning sebelum teks phase -->
<!-- Action = HOLD, tapi label ditampilkan sebagai WATCH oleh frontend -->
<span class="phase-cell">
  <span
    class="watch-dot"
    title="Peringatan: Penurunan > 1.5x ATR — Risiko ARB, butuh konfirmasi"
  >●</span>
  SPRING
</span>
```

Action badge untuk kondisi ini:
```javascript
// Jika action == "HOLD" DAN watch == "ARB_SPRING" → tampilkan sebagai WATCH
const actionLabel = (r.action === 'HOLD' && r.watch === 'ARB_SPRING')
  ? '⚠️ WATCH'
  : r.action === 'BUY' ? '🚀 BUY'
  : r.action === 'SELL' ? '⚠️ SELL'
  : '⌛ HOLD';
```

---

## 13. Keputusan yang Sengaja Tidak Diimplementasi

| Item | Alasan |
|------|--------|
| Minimum tx_bm absolute | Tidak semua saham IDX terdeteksi SM/BM oleh Joker — angka absolut tidak fair antar saham |
| Filter saham baru (history < N hari) | ATR 14 hari belum tersedia = natural filter sudah cukup |
| Phase "CONTEST" untuk SM vs BM sama-sama aktif | Out of scope Wyckoff — jika RSM < 40 maka BM dominan by value, DISTRI tetap correct walau SRI tinggi |
| Multi-day range phase accuracy | Dideferral — butuh diskusi tersendiri tentang pendekatan optimal |
| `suggested_sl` | Dihapus di v3.1 — trade journal pakai -10% flat dari entry price |
| `floor_to_fraction` | Dihapus bersama suggested_sl |

---

## 14. Ringkasan Perubahan v2.1 → v3.1

| Aspek | v2.1 | v3.1 |
|-------|------|-------|
| **SOS Criteria** | `rsm > 65 AND sri > 3.0` | Tambah OR: `rsm > 60 AND sri > 4.0` |
| **Anti-Pucuk** | Hanya di SOS | **Gate C: semua fase BUY** |
| **Supply Gate** | Tidak ada | **Gate A: `bm_val > bm_sma10 × 3.0` → HOLD** |
| **ARB Spring Action** | BUY | **Gate B: HOLD** (frontend tampil WATCH) |
| **get_action signature** | `(phase, pchg, atr_pct)` | `(phase, pchg, atr_pct, bm_val, bm_sma10, watch_flag)` |
| **Function name** | `classify_zenith_v2_1` | `classify_zenith_v3_1` |
| **suggested_sl** | Ada | **Dihapus** |
| **Phase logic** | v2.1 | **Tetap v2.1** (tidak ada regresi) |
