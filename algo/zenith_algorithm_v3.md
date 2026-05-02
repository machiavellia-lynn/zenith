# ZENITH — Algorithm Specification v3.0 (Official)

**Dokumen ini adalah spesifikasi teknis final untuk Zenith v3.0.**
Menggabungkan perbaikan dari kasus ARA (Anti-Pucuk), Supply Gate, dan Fleksibilitas SOS.

---

## 1. Filosofi Sistem
Zenith v3.0 dirancang untuk menjadi sistem navigasi pasar yang lebih konservatif namun adaptif. Fokus utama versi ini adalah **Capital Preservation** (menghindari pembelian di harga yang sudah terlalu mahal) dan **Supply Awareness** (mendeteksi tembok penjual masif).

---

## 2. Input & Metrik Kunci

| Metrik | Deskripsi | Catatan |
| :--- | :--- | :--- |
| **SRI** | SM Relative Intensity | Menggunakan Trimmed Mean (buang 1 outlier tertinggi dari 10 hari). |
| **RSM** | Rasio Smart Money | Persentase nilai SM terhadap total (SM+BM). |
| **RPR** | Relative Price Range | Posisi penutupan dalam rentang hari itu (0-1). |
| **MES** | Market Efficiency Score | $|gain\%| / SRI$. Rendah = Akumulasi diam-diam. |
| **Volx Gap** | SM Modal Gap | $(Close - VWAP\_SM) / Close$. |
| **ATR%** | Volatilitas | Dasar perhitungan semua threshold dinamis. |

---

## 3. Threshold Dinamis (ATR-Based)

Dihitung berdasarkan ATR 14 hari:
- **th_up (Bullish Trigger):** $0.8 \times ATR$
- **th_down (Bearish Trigger):** $0.4 \times ATR$
- **th_flat (Sideways):** $0.5 \times ATR$
- **th_sos_h (Anti-Pucuk):** $MAX(2.0 \times ATR, 5.0)$ (Batas kenaikan harga maksimal untuk BUY)

---

## 4. Logika Klasifikasi Fase (logic.py)

Urutan evaluasi tetap mengikuti prioritas v2.1 dengan pembaruan pada kriteria SOS.

1.  **SOS (Sign of Strength):**
    - Kondisi: `pchg > th_up` AND (`(rsm > 65 AND sri > 3.0)` OR **`(rsm > 60 AND sri > 4.0)`**)
    - *Update v3: Menampung SM agresif meskipun ada perlawanan BM.*
2.  **SPRING:**
    - Kondisi: `rsm > 60` AND `sri > 1.5` AND `pchg < -th_down` AND `rpr > 0.4`
3.  **UPTHRUST:**
    - Kondisi: `rsm < 35` AND `sri > 1.2` AND `pchg > th_up` AND `rpr < 0.4`
4.  **DISTRI (Distribution):**
    - Kondisi: `rsm < 40` AND `pchg < -th_down` AND `rpr > 0.4` AND `bm_gate`
    - Fallback: `rsm < 35` AND `rpr > 0.5` AND `bm_gate`
5.  **ABSORB (Absorption):**
    - Kondisi: `rsm > 65` AND `sri > 2.0` AND $|pchg| < th\_flat$
6.  **ACCUM (Accumulation):**
    - Kondisi: `rsm > 60` AND `sri > 1.0`
7.  **NEUTRAL:** Jika tidak memenuhi kriteria di atas.

---

## 5. Logika Action & Risk Management

Fungsi `get_action()` diperketat dengan sistem "Safety Gate" berlapis:

### **Gate A: Supply Gate (New)**
Jika `bm_val > (bm_sma10 * 3.0)`:
- Action: **HOLD**
- Alasan: Ada "tembok" penjual (distribusi masif) yang berisiko mematikan momentum SM.

### **Gate B: ARB Safety (New)**
Jika `watch_flag == "ARB_SPRING"`:
- Action: **WATCH**
- Alasan: Menghindari "tangkap pisau jatuh". Butuh konfirmasi pantulan di hari berikutnya.

### **Gate C: Global Anti-Pucuk (Standardization)**
Untuk semua fase BUY (**SOS, ACCUM, SPRING, ABSORB**):
- Jika `pchg >= th_sos_h`:
    - Action: **HOLD**
- Else:
    - Action: **BUY**
- Alasan: Mencegah FOMO/HAKA pada saham yang sudah ARA atau naik melampaui volatilitas normal.

---

## 6. Ringkasan Perubahan (v2.1 → v3.0)

| Fitur | v2.1 | v3.0 (Update) |
| :--- | :--- | :--- |
| **SOS Criteria** | RSM > 65% | RSM > 60% jika SRI > 4.0 |
| **Batas Atas BUY** | Hanya di SOS | **Berlaku di Semua Fase BUY** |
| **BM Surge** | Tidak dideteksi | **Supply Gate (3x SMA10)** |
| **ARB Spring** | Action: BUY | **Action: WATCH** |
| **SOP Safety** | Moderat | **Konservatif (Safety First)** |

---

## 7. Instruksi Implementasi (SOP)
1.  Update `logic.py` dengan fungsi `get_action_v3()` yang mencakup Gate A, B, dan C.
2.  Pastikan `scraper_daily.py` mengirimkan `bm_val` dan `bm_sma10` ke fungsi action.
3.  Dashboard harus menampilkan label **"HOLD (Overextended)"** jika tersaring oleh Gate C agar user paham mengapa saham bagus tidak disarankan BUY.

---
**Peringatan:** *Algoritma ini adalah alat bantu analisis. Keputusan investasi sepenuhnya ada di tangan pengguna.*
