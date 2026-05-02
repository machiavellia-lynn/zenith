# ZENITH — Algoritma Phase & Signal v2.1

**Panduan Teknis untuk Developer & SOP Trading**

Dokumen ini menjelaskan seluruh algoritma perhitungan phase (fase Wyckoff) dan signal (BUY/HOLD/SELL) yang digunakan di Zenith Dashboard.

> **Update v2.1:** Perbaikan logic DISTRI (menggunakan RPR), pemindahan prioritas ABSORB di atas SPRING, dan optimalisasi deteksi "Blind Spot" Smart Money.
>
> _Last updated: April 2026_

---

## 1. Sumber Data

### 1.1 Raw Data dari Telegram Bot "Joker"

Bot Joker memposting transaksi big player di 4 topik Telegram:

- **SM (Smart Money):** Big player yang BELI saham.
- **BM (Bad Money):** Big player yang JUAL saham.
- **MF+/-:** Aliran dana (Money Flow) masuk atau keluar.

### 1.2 Data Harga (Close Price)

Close price di-fetch dari Yahoo Finance. Daily auto: disimpan setiap jam 17:00 WIB.

---

## 2. Metrik Analitik Utama

### 2.1 SRI — SM Relative Intensity

Mengukur seberapa agresif Smart Money (SM) hari ini dibanding rata-rata 10 hari terakhir.

```
SRI = sm_val_today / SMA(sm_val, 10 hari)
```

Digunakan hanya untuk fase Akumulasi (SOS, ABSORB, SPRING, ACCUM).

### 2.2 RPR — Rasio Tekanan Jual

Mengukur dominasi jumlah transaksi jual oleh big player.

```
RPR = tx_bm / (tx_sm + tx_bm)
```

Digunakan khusus untuk fase Kelemahan/Distribusi (UPTHRUST, DISTRI).

### 2.3 ATR% — Average True Range

Digunakan sebagai basis Dynamic Threshold untuk menyesuaikan volatilitas tiap saham.

---

## 3. Algoritma Phase Classification (Logic v2.1)

### 3.1 Dynamic Thresholds

Threshold dihitung otomatis berdasarkan `atr_pct` saham:

```
th_up    = max(atr * 0.8, 1.0%)
th_down  = max(atr * 0.4, 0.5%)
th_flat  = atr * 0.5
th_sos_h = max(atr * 2.0, 5.0%)
```

### 3.2 Decision Tree (Urutan Prioritas v2.1)

Evaluasi dilakukan dari atas ke bawah. Fase pertama yang terpenuhi akan dipilih.

| # | Phase | Syarat | Action |
|---|-------|--------|--------|
| 1 | **SOS** (Sign of Strength) | `gain > th_up` AND `rsm > 65%` AND `sri > 3.0` | **BUY** (jika `gain < th_sos_h`) atau **HOLD** (jika sudah lari) |
| 2 | **UPTHRUST** (Trap) | `gain > th_up` AND `rsm < 40%` AND `rpr > 0.6` | **SELL** |
| 3 | **ABSORB** (Absorption) | `sri > 2.0` AND `rsm > 65%` AND `abs(gain) < th_flat` | **BUY** — Akumulasi diam-diam saat harga flat |
| 4 | **SPRING** | `gain < -th_down` AND `rsm > 60%` AND `sri > 1.5` | **BUY** — Harga turun tapi SM belanja agresif |
| 5 | **DISTRI** (Distribution) | `rsm < 40%` AND `gain < -(th_down * 0.5)` | **SELL** — SRI dihapus agar distribusi masif tetap terdeteksi |
| 6 | **ACCUM** (Accumulation) | `rsm > 60%` AND `sri > 1.0` | **BUY** |
| 7 | **DISTRI Fallback** | `rsm < 35%` AND `rpr > 0.5` | **SELL** |
| 8 | **NEUTRAL** | Kondisi lainnya | **HOLD** |

---

## 4. Pseudocode (v2.1)

```python
def classify_v2_1(ticker_data, atr_pct=None):
    # Dynamic thresholds calculation
    atr      = atr_pct or 2.5
    th_up    = max(atr * 0.8, 1.0)
    th_down  = max(atr * 0.4, 0.5)
    th_flat  = atr * 0.5
    th_sos_h = max(atr * 2.0, 5.0)

    # 1. SOS
    if gain > th_up and rsm > 65 and sri > 3.0:
        return "SOS", "BUY" if gain < th_sos_h else "HOLD"

    # 2. UPTHRUST (Prioritaskan deteksi trap jual)
    if gain > th_up and rsm < 40 and rpr > 0.6:
        return "UPTHRUST", "SELL"

    # 3. ABSORB (Prioritas lebih tinggi dari SPRING untuk volatilitas)
    if sri > 2.0 and rsm > 65 and abs(gain) < th_flat:
        return "ABSORB", "BUY"

    # 4. SPRING
    if gain < -th_down and rsm > 60 and sri > 1.5:
        return "SPRING", "BUY"

    # 5. DISTRI (SRI dihapus untuk menghindari blind spot)
    if rsm < 40 and gain < -(th_down * 0.5):
        return "DISTRI", "SELL"

    # 6. ACCUM
    if rsm > 60 and sri > 1.0:
        return "ACCUM", "BUY"

    # 7. DISTRI Fallback
    if rsm < 35 and rpr > 0.5:
        return "DISTRI", "SELL"

    return "NEUTRAL", "HOLD"
```

---

## 5. Tabel Referensi Threshold Dinamis Saham

| Saham | ATR% | th_up (SOS/UT) | th_down (SPRING) | th_flat (ABSORB) |
|-------|------|----------------|------------------|------------------|
| BBCA (Blue Chip) | 1.2% | > 1.0% | < -0.5% | < 0.6% |
| ANTM (Mid Cap) | 2.5% | > 2.0% | < -1.0% | < 1.25% |
| PADI (Volatile) | 5.0% | > 4.0% | < -2.0% | < 2.5% |

---

## 6. Perubahan Utama vs v2.0

- **Eliminasi SRI pada DISTRI:** Menghapus risiko fase turun yang terdeteksi "NEUTRAL" hanya karena Smart Money tidak melakukan transaksi (Blind Spot).
- **RPR as Key Indicator:** Menggunakan Rasio Tekanan Jual untuk memvalidasi UPTHRUST dan DISTRI agar lebih akurat melihat aksi Big Player buang barang.
- **ABSORB Priority Upgrade:** Mencegah fase akumulasi tenang di saham volatil terdeteksi sebagai SPRING secara keliru.
