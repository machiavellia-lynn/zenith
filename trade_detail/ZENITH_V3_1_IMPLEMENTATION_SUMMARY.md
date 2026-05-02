# ZENITH v3.1 — Complete Implementation Summary

**Project:** Zenith IDX Trading Platform (Bandarmologi + Wyckoff Analysis)  
**Status:** Algorithm finalized (v3.1), Ready for implementation  
**Tech Stack:** Python Flask, SQLite, Railway, Node.js Telegram Bot  
**Date:** May 2026

---

## 📋 Executive Summary

Zenith v3.1 adalah upgrade dari v2.1 yang menambahkan:
1. **Action Safety Gates** (Supply Gate, ARB Safety, Anti-Pucuk) — 3 layer protection
2. **Moving Average Technical Analysis** (MA 5/13/34/200) — multi-timeframe confluence
3. **MA Cross Detection** (Golden Cross / Death Cross) — trend confirmation
4. **Weak Breakout Warning** — volume confirmation untuk avoid false breaks

**Core Philosophy:** 
- Preserve v2.1 phase classification (SOS, SPRING, ABSORB, ACCUM, UPTHRUST, DISTRI)
- Add conservative action gates based on market microstructure
- Multi-timeframe validation dengan MA alignment + volume confirmation
- Non-fundamental — pure market structure (Smart Money tracking + price action)

---

## 🎯 Phase 1: Algorithm Specification (v3.1)

### A. Phase Classification (v2.1 with SOS upgrade)

```python
def classify_zenith_v3_1(sri, rsm, rpr, pchg, bm_val, bm_sma10, atr_pct=None):
    """
    Wyckoff phase detection. Pure v2.1 logic dengan 1 upgrade: SOS lebih fleksibel.
    
    Inputs:
      sri        : Smart Money Relative Intensity (trimmed mean SM 10 hari)
      rsm        : Ratio Smart Money (% nilai SM dari total)
      rpr        : Relative Price Range (% posisi close dalam candle range)
      pchg       : Price change % hari ini
      bm_val     : Bad Money value hari ini
      bm_sma10   : Simple mean BM 10 hari (untuk gate)
      atr_pct    : ATR % volatilitas
    
    Returns: "SOS" | "SPRING" | "UPTHRUST" | "ABSORB" | "ACCUM" | "DISTRI" | "NEUTRAL"
    """
    atr      = atr_pct if atr_pct and atr_pct > 0 else 2.5
    th_up    = max(atr * 0.8, 1.0)
    th_down  = max(atr * 0.4, 0.5)
    th_flat  = atr * 0.5

    # BM Gate: BM hari ini bukan sekadar noise vs historical average
    bm_gate = True if bm_sma10 == 0 else (bm_val > bm_sma10 * 0.5)

    if pchg is None:
        return "NEUTRAL"

    # 1. SOS — Sign of Strength (v3.1: OR clause untuk SM agresif)
    # Standard: RSM > 65% AND SRI > 3.0
    # NEW: OR RSM > 60% AND SRI > 4.0 (SM sangat intensif, RSM bisa lebih rendah)
    if pchg > th_up and ((rsm > 65 and sri > 3.0) or (rsm > 60 and sri > 4.0)):
        return "SOS"

    # 2. UPTHRUST — Jebakan naik, BM dominan jual saat harga tinggi
    # Tidak ada syarat SRI — jebakan paling berbahaya saat SM diam
    if pchg > th_up and rsm < 40 and rpr > 0.6:
        return "UPTHRUST"

    # 3. ABSORB — Akumulasi diam-diam, harga flat
    # pchg > -th_down: mencegah overlap dengan SPRING
    if sri > 2.0 and rsm > 65 and pchg > -th_down and abs(pchg) < th_flat:
        return "ABSORB"

    # 4. SPRING — Harga turun tapi SM aktif akumulasi
    if pchg < -th_down and rsm > 60 and sri > 1.5:
        return "SPRING"

    # 5. DISTRI — Distribusi aktif, BM dominan
    # bm_gate: pastikan BM aktif, bukan sekadar noise
    if rsm < 40 and pchg < -(th_down * 0.5) and rpr > 0.4 and bm_gate:
        return "DISTRI"

    # 6. ACCUM — Akumulasi bertahap, SM dominan
    if rsm > 60 and sri > 1.0:
        return "ACCUM"

    # 7. DISTRI Fallback — BM overwhelmingly dominant
    if rsm < 35 and rpr > 0.5 and bm_gate:
        return "DISTRI"

    return "NEUTRAL"
```

### B. Action Signal dengan 3 Safety Gates

```python
def get_action(phase, pchg, atr_pct=None, bm_val=0, bm_sma10=0, watch_flag=None):
    """
    Action signal dengan 3 gate keamanan berlapis.
    
    Gate A — Supply Gate:
      Jika bm_val > bm_sma10 * 3.0 → HOLD
      Ada "tembok" penjual (3x rata-rata), momentum SM berisiko terhenti.
    
    Gate B — ARB Safety:
      Jika watch_flag == "ARB_SPRING" → HOLD
      SPRING saat tekanan jual ekstrem (ARB) — tunggu konfirmasi.
      Action tetap HOLD di sistem; frontend tampil "WATCH".
    
    Gate C — Global Anti-Pucuk:
      Jika pchg >= th_sos_h untuk semua fase BUY → HOLD
      Semua BUY signal (SOS, SPRING, ABSORB, ACCUM) di-gate jika harga sudah terlalu tinggi.
      Mencegah FOMO/HAKA setelah momentum sudah terpakai.
    
    Inputs:
      phase       : Hasil dari classify_zenith_v3_1()
      pchg        : Price change % hari ini
      atr_pct     : ATR %
      bm_val      : Bad Money value hari ini (untuk Gate A)
      bm_sma10    : BM 10-day average (untuk Gate A)
      watch_flag  : Output dari get_watch_flag() (untuk Gate B)
    
    Returns: "BUY" | "SELL" | "HOLD"
    """
    atr      = atr_pct if atr_pct and atr_pct > 0 else 2.5
    th_sos_h = max(atr * 2.0, 5.0)

    BUY_PHASES  = ("SOS", "SPRING", "ABSORB", "ACCUM")
    SELL_PHASES = ("UPTHRUST", "DISTRI")

    # SELL phases langsung return SELL
    if phase in SELL_PHASES:
        return "SELL"

    # Non-BUY, non-SELL → HOLD
    if phase not in BUY_PHASES:
        return "HOLD"

    # ── Gate A: Supply Gate ──
    # BM hari ini 3x lipat rata-rata = tembok penjual masif
    if bm_sma10 > 0 and bm_val > bm_sma10 * 3.0:
        return "HOLD"

    # ── Gate B: ARB Safety ──
    # SPRING ekstrem (ARB) → tunggu konfirmasi esok hari
    if watch_flag == "ARB_SPRING":
        return "HOLD"

    # ── Gate C: Global Anti-Pucuk ──
    # Semua BUY phase: jika harga naik >= 2x ATR hari ini → sudah overextended
    if pchg is not None and pchg >= th_sos_h:
        return "HOLD"

    # Semua gate clear → BUY
    return "BUY"
```

### C. Watch Flag (ARB Detection)

```python
def get_watch_flag(phase, pchg, atr_pct=None):
    """
    Deteksi SPRING di kondisi penurunan ekstrem (ARB — Auto Rejection Bawah).
    
    Kondisi:
      - Phase = SPRING
      - Penurunan > 1.5x ATR (melampaui range normal)
    
    Implikasi:
      SPRING di ARB zone lebih berisiko — momentum recovery bisa tertunda.
      Action akan di-gate ke HOLD, tapi user dapat warning.
      Frontend tampilkan sebagai "⚠️ WATCH" (bukan action string baru).
    
    Returns: "ARB_SPRING" | None
    """
    atr = atr_pct if atr_pct and atr_pct > 0 else 2.5
    
    if phase == "SPRING" and pchg is not None and pchg < -(atr * 1.5):
        return "ARB_SPRING"
    
    return None
```

---

## 📊 Phase 2: Moving Average Technical Analysis

### Database Schema Addition

```sql
-- Existing columns dari v2.1 (tidak berubah):
-- sri, rsm, rpr, pchg, atr_pct, phase, action, watch, bm_sma10, sm_sma10

-- NEW in v3.1:
ALTER TABLE eod_summary ADD COLUMN ma_5   REAL;    -- Momentum (5-day MA)
ALTER TABLE eod_summary ADD COLUMN ma_13  REAL;    -- Short trend (13-day MA, Fibonacci)
ALTER TABLE eod_summary ADD COLUMN ma_34  REAL;    -- Mid trend (34-day MA, Fibonacci)
ALTER TABLE eod_summary ADD COLUMN ma_200 REAL;    -- Macro trend (200-day MA, institusional)
ALTER TABLE eod_summary ADD COLUMN ma_cross TEXT;  -- "GOLDEN_CROSS" | "DEATH_CROSS" | NULL
```

### A. Moving Average Computation

```python
def compute_moving_averages(conn, ticker, date_str):
    """
    Hitung MA 5, 13, 34, 200 dari price_close history.
    
    Input:
      ticker   : Kode saham
      date_str : Tanggal hari ini (DD-MM-YYYY)
    
    Output:
      {
        "ma_5": float,
        "ma_13": float,
        "ma_34": float,
        "ma_200": float
      }
    
    Note: Jika history kurang dari periode yang diminta, return None untuk MA tersebut.
    """
    hist = conn.execute("""
        SELECT price_close FROM eod_summary
        WHERE ticker = ? AND price_close IS NOT NULL
        ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2) DESC
        LIMIT 200
    """, [ticker]).fetchall()
    
    if not hist:
        return {"ma_5": None, "ma_13": None, "ma_34": None, "ma_200": None}
    
    closes = [r["price_close"] for r in hist[::-1]]  # reverse ke chronological order
    
    mas = {}
    for period in [5, 13, 34, 200]:
        if len(closes) >= period:
            ma = sum(closes[-period:]) / period
            mas[f"ma_{period}"] = round(ma, 2)
        else:
            mas[f"ma_{period}"] = None
    
    return mas
```

### B. Golden Cross / Death Cross Detection

```python
def detect_ma_cross(conn, ticker, date_str):
    """
    Deteksi apakah hari ini MA 13 cross MA 34.
    
    Input:
      ticker   : Kode saham
      date_str : Tanggal hari ini (DD-MM-YYYY)
    
    Output:
      "GOLDEN_CROSS"  : MA 13 baru break DI ATAS MA 34 (bullish confirmation)
      "DEATH_CROSS"   : MA 13 baru break DI BAWAH MA 34 (bearish warning)
      None            : Tidak ada cross hari ini
    
    Logic:
      - Ambil MA 13 & MA 34 untuk hari ini dan kemarin
      - Cek apakah ada perubahan posisi relatif
      - Jika kemarin MA13 <= MA34 dan hari ini MA13 > MA34 → GOLDEN_CROSS
      - Jika kemarin MA13 >= MA34 dan hari ini MA13 < MA34 → DEATH_CROSS
    """
    hist = conn.execute("""
        SELECT date, ma_13, ma_34 FROM eod_summary
        WHERE ticker = ? AND ma_13 IS NOT NULL AND ma_34 IS NOT NULL
        ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2) DESC
        LIMIT 2
    """, [ticker]).fetchall()
    
    if len(hist) < 2:
        return None
    
    today = hist[0]   # Most recent (hari ini)
    yest  = hist[1]   # Previous day (kemarin)
    
    # Golden Cross
    if yest["ma_13"] <= yest["ma_34"] and today["ma_13"] > today["ma_34"]:
        return "GOLDEN_CROSS"
    
    # Death Cross
    if yest["ma_13"] >= yest["ma_34"] and today["ma_13"] < today["ma_34"]:
        return "DEATH_CROSS"
    
    return None
```

### C. Weak Breakout Warning

```python
def detect_weak_breakout(conn, ticker, date_str, pchg, atr_pct):
    """
    Deteksi breakout tipis tanpa volume confirmation.
    
    Weak Breakout = harga naik, TAPI:
      1. Pergerakan < 1.0x ATR (tipis, masih dalam range normal)
      2. Volume SM+BM hari ini < 70% dari rata-rata 10 hari (kurang confirmation)
    
    Implikasi:
      Breakout tanpa volume = likely false breakout.
      Perlu wait konfirmasi hari berikutnya atau kembali ke support.
    
    Input:
      ticker   : Kode saham
      date_str : Tanggal hari ini (DD-MM-YYYY)
      pchg     : Price change % hari ini
      atr_pct  : ATR %
    
    Output:
      True     : Weak breakout terdeteksi ⚠️
      False    : Breakout confirm / tidak ada breakout
    """
    
    # Jika tidak naik, bukan breakout
    if pchg is None or pchg <= 0:
        return False
    
    atr = atr_pct if atr_pct and atr_pct > 0 else 2.5
    
    # Gate 1: Harga naik, tapi < 1x ATR?
    if pchg < atr:  # Naik, tapi tipis
        
        # Gate 2: Cek volume SM/BM hari ini vs rata-rata 10 hari
        eod = conn.execute("""
            SELECT sm_val, bm_val FROM eod_summary
            WHERE ticker = ? AND date = ?
        """, [ticker, date_str]).fetchone()
        
        if not eod:
            return False
        
        sm, bm = eod["sm_val"] or 0, eod["bm_val"] or 0
        today_vol = sm + bm
        
        # Ambil rata-rata volume 10 hari (dari 11 hari terakhir, exclude hari ini)
        cutoff_date = (datetime.strptime(date_str, "%d-%m-%Y") - timedelta(days=11)).strftime("%d-%m-%Y")
        
        avg_hist = conn.execute("""
            SELECT AVG(sm_val + bm_val) as avg_vol FROM eod_summary
            WHERE ticker = ? 
              AND substr(date,7,4)||substr(date,4,2)||substr(date,1,2)
                  BETWEEN ? AND ?
        """, [
            ticker,
            cutoff_date[6:10] + cutoff_date[3:5] + cutoff_date[0:2],
            date_str[6:10] + date_str[3:5] + date_str[0:2]
        ]).fetchone()
        
        if not avg_hist or not avg_hist["avg_vol"] or avg_hist["avg_vol"] == 0:
            return False
        
        avg_vol = avg_hist["avg_vol"]
        
        # Jika volume hari ini < 70% rata-rata = weak volume
        if today_vol < avg_vol * 0.7:
            return True  # ⚠️ Weak breakout
    
    return False  # Breakout confirm atau tidak ada breakout
```

---

## 🔧 Phase 3: Implementation in scraper_daily.py

### Integration Point: compute_analytics_for_date()

```python
from logic import classify_zenith_v3_1, get_action, get_watch_flag

def compute_analytics_for_date(conn, date_str: str):
    """
    Compute phase, action, watch, MA untuk setiap ticker pada date_str.
    """
    
    # ... existing SRI/RSM/RPR/ATR computation ...
    
    for tk in tickers:
        # Existing v2.1 computation
        # sri, rsm_val, rpr, pchg, atr_pct already computed
        # sm, bm, bm_sma10 already available
        
        # ── NEW v3.1: Moving Averages ──
        ma_dict = compute_moving_averages(conn, tk, date_str)
        ma_5   = ma_dict["ma_5"]
        ma_13  = ma_dict["ma_13"]
        ma_34  = ma_dict["ma_34"]
        ma_200 = ma_dict["ma_200"]
        
        # ── NEW v3.1: MA Cross Detection ──
        ma_cross = detect_ma_cross(conn, tk, date_str)
        
        # ── v3.1: Phase Classification (dengan SOS upgrade) ──
        phase = classify_zenith_v3_1(sri, rsm_val, rpr, pchg, bm, bm_sma10, atr_pct)
        
        # ── v3.1: Watch Flag (ARB Detection) ──
        watch = get_watch_flag(phase, pchg, atr_pct)
        
        # ── v3.1: Action dengan 3 Safety Gates ──
        # get_action signature baru: tambah bm_val, bm_sma10, watch_flag
        action = get_action(phase, pchg, atr_pct, bm_val=bm, bm_sma10=bm_sma10, watch_flag=watch)
        
        # ── NEW: Weak Breakout Warning (on-the-fly, tidak disimpan) ──
        weak_breakout = detect_weak_breakout(conn, tk, date_str, pchg, atr_pct)
        
        # UPDATE eod_summary dengan semua kolom baru
        conn.execute("""
            UPDATE eod_summary
            SET price_change_pct=?, sri=?, mes=?, volx_gap=?, rpr=?,
                atr_pct=?, sm_sma10=?, bm_sma10=?, phase=?, action=?,
                watch=?, ma_5=?, ma_13=?, ma_34=?, ma_200=?, ma_cross=?
            WHERE date=? AND ticker=?
        """, [
            pchg, sri, mes, vg, rpr,
            atr_pct, sm_sma10, bm_sma10, phase, action,
            watch, ma_5, ma_13, ma_34, ma_200, ma_cross,
            date_str, tk
        ])
    
    conn.commit()
```

---

## 📡 Phase 4: API & Frontend Integration

### /api/flow Response

```json
{
  "ticker": "ACES",
  "date": "01-05-2026",
  "phase": "SPRING",
  "action": "BUY",
  "watch": "ARB_SPRING",
  "sri": 2.4,
  "rsm": 68.5,
  "rpr": 0.42,
  "pchg": -4.2,
  "atr_pct": 2.8,
  "sm_sma10": 125_000_000,
  "bm_sma10": 45_000_000,
  "ma_5": 2850.50,
  "ma_13": 2875.25,
  "ma_34": 2900.00,
  "ma_200": 2950.75,
  "ma_cross": null,
  "clean_money": 80_000_000,
  "price": 2840,
  "comment": "SPRING phase, SM akumulasi saat penurunan. Warning: ARB zone (turun > 1.5x ATR). MA alignment 3/3 bullish, tapi MA200 masih above. Weak breakout: perhatikan volume."
}
```

### Frontend Modal Detail — Technical Analysis Section

```html
<section class="technical-analysis">
  <!-- Moving Averages -->
  <div class="ma-section">
    <h4>📈 MOVING AVERAGES</h4>
    
    <div class="ma-grid">
      <div class="ma-card">
        <span class="label">MA 5</span>
        <span class="value">2,850.50</span>
        <span class="status {{#if ma_5 > ma_13}}up{{else}}down{{/if}}">
          {{#if ma_5 > ma_13}}↗{{else}}↙{{/if}}
        </span>
        <span class="desc">Momentum</span>
      </div>
      
      <div class="ma-card">
        <span class="label">MA 13</span>
        <span class="value">2,875.25</span>
        <span class="status {{#if ma_13 > ma_34}}up{{else}}down{{/if}}">
          {{#if ma_13 > ma_34}}↗{{else}}↙{{/if}}
        </span>
        <span class="desc">Short Trend</span>
      </div>
      
      <div class="ma-card">
        <span class="label">MA 34</span>
        <span class="value">2,900.00</span>
        <span class="status {{#if ma_34 > ma_200}}up{{else}}down{{/if}}">
          {{#if ma_34 > ma_200}}↗{{else}}↙{{/if}}
        </span>
        <span class="desc">Mid Trend</span>
      </div>
      
      <div class="ma-card {{#if ma_200 < price}}bearish{{else}}bullish{{/if}}">
        <span class="label">MA 200</span>
        <span class="value">2,950.75</span>
        <span class="status {{#if ma_200 > price}}up{{else}}down{{/if}}">
          {{#if ma_200 > price}}↗{{else}}↙{{/if}}
        </span>
        <span class="desc">Macro</span>
      </div>
    </div>

    <!-- Alignment Score -->
    <div class="alignment-score">
      <strong>Alignment Status:</strong>
      <span class="badge">3/3 Short-term Bullish</span>
      <span class="badge bearish">MA200 above price (Bearish LT)</span>
      <p>Short-medium momentum bagus, tapi tren besar masih bearish. Risiko: pullback jika harga tidak break MA200.</p>
    </div>
  </div>

  <!-- MA Cross Signals -->
  {{#if ma_cross}}
  <div class="ma-cross-signal">
    <h4>🔀 MOVING AVERAGE CROSS</h4>
    {{#if ma_cross === 'GOLDEN_CROSS'}}
      <div class="badge bullish">🟢 GOLDEN CROSS</div>
      <p><strong>Hari ini:</strong> MA 13 break DI ATAS MA 34 — confirmation bullish dari MA.</p>
      <p><em>Implikasi:</em> Tren pendek turn bullish, confluence dengan SPRING signal.</p>
    {{else if ma_cross === 'DEATH_CROSS'}}
      <div class="badge bearish">🔴 DEATH CROSS</div>
      <p><strong>Hari ini:</strong> MA 13 break DI BAWAH MA 34 — warning bearish.</p>
      <p><em>Implikasi:</em> Tren pendek turn bearish, re-evaluate bullish signal.</p>
    {{/if}}
  </div>
  {{/if}}

  <!-- Weak Breakout Warning -->
  {{#if action === 'BUY' && weak_breakout}}
  <div class="warning-box weak-breakout">
    <h4>⚠️ WEAK BREAKOUT WARNING</h4>
    <p><strong>Harga naik {{pchg}}% tapi volume rendah.</strong></p>
    <p>
      Breakout dipenuhi syarat 1: naik, tapi hanya {{pchg}}% 
      (< {{atr_pct}}% ATR — dalam range normal).
    </p>
    <p>
      Breakout gagal syarat 2: volume SM+BM hari ini 
      < 70% rata-rata 10 hari — kurang confirmation dari big players.
    </p>
    <p><strong>Risiko:</strong> Bisa false breakout. Perlu wait konfirmasi esok hari atau lihat support level berikutnya.</p>
  </div>
  {{/if}}
</section>

<style>
.ma-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin: 16px 0;
}

.ma-card {
  padding: 12px;
  border: 1px solid #333;
  border-radius: 6px;
  background: #1a1a1a;
  border-left: 3px solid #00e8a2;
}

.ma-card.bearish {
  border-left-color: #ff6b6b;
}

.ma-card .label {
  display: block;
  font-size: 12px;
  color: #999;
  margin-bottom: 4px;
}

.ma-card .value {
  display: block;
  font-size: 16px;
  font-weight: bold;
  margin-bottom: 4px;
}

.ma-card .status {
  font-size: 14px;
  margin-right: 4px;
}

.ma-card .desc {
  font-size: 11px;
  color: #666;
}

.alignment-score {
  padding: 12px;
  background: #222;
  border-radius: 6px;
  margin-top: 12px;
}

.alignment-score .badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 4px;
  background: #00e8a2;
  color: #000;
  font-size: 12px;
  margin-right: 8px;
  margin-top: 4px;
}

.alignment-score .badge.bearish {
  background: #ff6b6b;
  color: #fff;
}

.ma-cross-signal {
  padding: 12px;
  background: #1a2a1a;
  border: 1px solid #00e8a2;
  border-radius: 6px;
  margin-top: 12px;
}

.ma-cross-signal .badge {
  display: inline-block;
  padding: 6px 12px;
  border-radius: 4px;
  margin-top: 8px;
}

.weak-breakout {
  background: #2a1a1a;
  border: 1px solid #ff6b6b;
  padding: 12px;
  border-radius: 6px;
  margin-top: 12px;
}

.weak-breakout h4 {
  color: #ff9999;
  margin-top: 0;
}
</style>
```

---

## 📝 Example Cases

### Case 1: SPRING + GOLDEN CROSS + Strong Volume = High Confidence BUY

```
Ticker: ACES (01-05-2026)
─────────────────────────

PHASE ANALYSIS:
  Phase: SPRING (harga turun, SM akumulasi)
  RSM: 68.5% (SM dominan)
  SRI: 2.4x (intensitas sedang-tinggi)
  RPR: 0.42 (transaksi seimbang)
  Action: BUY

MOVING AVERAGE:
  MA 5:   2,850.50 ↗
  MA 13:  2,875.25 ↗
  MA 34:  2,900.00 ↗
  MA 200: 2,950.75 ↗
  
  MA Cross: GOLDEN_CROSS (MA 13 baru break atas MA 34)
  Alignment: 3/3 short-term bullish

VOLUME:
  SM+BM Hari Ini: 125M (vs avg 10d: 110M)
  Status: Strong volume ✓

GATES:
  Gate A (Supply): OK — BM 35M < BM avg 3x (105M)
  Gate B (ARB):    OK — pchg -2.8% (> -1.5x ATR, no ARB)
  Gate C (Pucuk):  OK — pchg 2.8% < th_sos_h 5.6%

RESULT: ✅ HIGH CONFIDENCE BUY
  - SPRING = valid entry zone
  - Golden Cross = confirmation dari MA
  - Volume strong = big players confirm
  - Semua gate clear
  - REKOMENDASI: Buy dengan confidence tinggi
```

### Case 2: SPRING + ARB_SPRING + Weak Volume = Warning HOLD

```
Ticker: BBRI (02-05-2026)
─────────────────────────

PHASE ANALYSIS:
  Phase: SPRING (harga turun, SM akumulasi)
  RSM: 65.2%
  SRI: 1.8x
  RPR: 0.38
  Action: HOLD (Gate B triggered)
  Watch: ARB_SPRING

MOVING AVERAGE:
  MA 5:   4,250.00 ↙
  MA 13:  4,280.50 ↙
  MA 34:  4,320.00 ↗
  MA 200: 4,400.00 ↗
  
  MA Cross: None (MA 13 masih di bawah MA 34)
  Alignment: 1/3 short-term bullish (only MA 5 naik)

VOLUME:
  SM+BM Hari Ini: 45M (vs avg 10d: 65M)
  Status: Weak volume ⚠️
  Weak Breakout: YES

PRICE ACTION:
  pchg: -5.2%
  ATR: 2.8%
  ARB Condition: pchg -5.2% < -(ATR * 1.5) = -4.2% → YES, ARB ZONE

GATES:
  Gate A (Supply): OK — BM 20M < threshold
  Gate B (ARB):    FAIL — watch_flag = "ARB_SPRING" → HOLD
  Gate C (Pucuk):  OK — tidak naik

RESULT: ⚠️ WATCH / HOLD
  - SPRING di ARB zone (penurunan ekstrem)
  - Weak volume — big players tidak confirm
  - MA alignment jelek (hanya MA 5 naik)
  - REKOMENDASI: HOLD, tunggu konfirmasi esok hari. Jika bounce, baru pertimbangkan entry.
```

### Case 3: ACCUM + All MA Bullish + Golden Cross = Upgrade Signal

```
Ticker: UNTR (03-05-2026)
─────────────────────────

PHASE ANALYSIS:
  Phase: ACCUM (akumulasi bertahap, SM dominan)
  RSM: 62%
  SRI: 1.6x
  pchg: +0.5% (sideways)
  Action: BUY

MOVING AVERAGE:
  MA 5:   15,250 ↗ (naik)
  MA 13:  15,200 ↗ (naik)
  MA 34:  15,100 ↗ (naik)
  MA 200: 14,900 ↗ (naik)
  
  Price: 15,300 (semua MA di bawah harga, semua naik)
  MA Cross: GOLDEN_CROSS (MA 13 baru cross atas MA 34)
  Alignment: 4/4 bullish (all MA aligned)

GATES:
  All gates clear

RESULT: ✅ VERY HIGH CONFIDENCE BUY
  - ACCUM phase = early accumulation
  - Perfect MA alignment (4/4)
  - Golden Cross = trend turn bullish
  - Price above all MA = bull trend
  - REKOMENDASI: Strong buy, potential multi-day uptrend
```

### Case 4: SOS (v3.1 upgrade) — RSM 62% tapi SRI Tinggi

```
Ticker: BMRI (04-05-2026)
─────────────────────────

PRICE ACTION:
  pchg: +6.2% (naik signifikan)
  ATR: 2.8%
  Kondisi: th_up = 2.24% → pchg 6.2% > th_up ✓

SMART MONEY:
  SM_val: 250M
  BM_val: 160M
  Total: 410M
  RSM: 250/410 = 61% (kurang dari 65%, tidak qualify v2.1 SOS)
  
  SRI: SM_SMA10 = 60M
       SRI = 250 / 60 = 4.17x (sangat tinggi!)

PHASE CLASSIFICATION (v3.1):
  Kondisi v2.1: pchg > th_up AND rsm > 65 AND sri > 3.0
    → 6.2% > 2.24% ✓, tapi 61% < 65% ✗ → NOT SOS
  
  Kondisi v3.1 NEW: pchg > th_up AND (rsm > 65 AND sri > 3.0) OR (rsm > 60 AND sri > 4.0)
    → 6.2% > 2.24% ✓, 61% > 60% ✓, 4.17 > 4.0 ✓ → SOS ✓

RESULT: ✅ SOS SIGNAL (v3.1 upgrade)
  - v2.1 would miss ini (RSM 61% tidak qualify)
  - v3.1 detect ini (SM sangat agresif, SRI 4.17x)
  - Implikasi: SM push agresif meski ada perlawanan BM
  - REKOMENDASI: BUY, confluence dari high SRI intensity
```

---

## 🔄 Implementation Checklist

- [ ] **logic.py**
  - [ ] Rename `classify_zenith_v2_1` → `classify_zenith_v3_1` (add SOS OR clause)
  - [ ] Update `get_action` signature (add bm_val, bm_sma10, watch_flag params)
  - [ ] Implement 3 gates (Supply, ARB, Anti-Pucuk)
  - [ ] `get_watch_flag` (unchanged)
  - [ ] Add: `compute_moving_averages()`, `detect_ma_cross()`, `detect_weak_breakout()`

- [ ] **scraper_daily.py**
  - [ ] Add MA columns to `ensure_summary_table()`
  - [ ] Call `compute_moving_averages()` in `compute_analytics_for_date()`
  - [ ] Call `detect_ma_cross()` in `compute_analytics_for_date()`
  - [ ] Update `get_action()` call signature
  - [ ] Update UPDATE query to include ma_5, ma_13, ma_34, ma_200, ma_cross
  - [ ] Remove `suggested_sl` computation (if not already done)

- [ ] **app.py**
  - [ ] Update `/api/flow` to pass bm_val, bm_sma10, watch_flag to get_action()
  - [ ] Query MA columns dari eod_summary
  - [ ] Compute weak_breakout on-the-fly (optional storage)
  - [ ] Return MA data + weak_breakout flag di response

- [ ] **flow.html**
  - [ ] Add MA technical section ke modal detail
  - [ ] Display MA 5/13/34/200 dengan status up/down
  - [ ] Display MA cross signal (GOLDEN/DEATH)
  - [ ] Display alignment score (X/3 atau X/4 aligned)
  - [ ] Add weak breakout warning box jika triggered

- [ ] **Database**
  - [ ] Backup DB via `/admin/backup-db`
  - [ ] ALTER table untuk ma_5, ma_13, ma_34, ma_200, ma_cross
  - [ ] Run `/admin/rebuild-summary` untuk recompute semua tanggal

---

## 🎓 Key Concepts

### Why v3.1 > v2.1

| Aspek | v2.1 | v3.1 | Manfaat |
|-------|------|------|---------|
| Action Gates | 0 (hanya berdasarkan phase) | 3 (Supply, ARB, Anti-Pucuk) | Reduce false signals, capital preservation |
| MA Analysis | 0 (tidak ada) | 5 (MA 5/13/34/200 + cross) | Multi-timeframe confluence, trend confirmation |
| Weak Breakout | 0 (tidak terdeteksi) | Volume check + ATR check | Avoid false breakouts |
| SOS Flexibility | rsm > 65 fixed | rsm > 60 jika sri > 4 | Catch SM aggressiveness |

### Why This Matters for IDX Trading

1. **Smart Money Tracking** — Zenith mengikuti aksi big players (SM), bukan retail
2. **Wyckoff Phases** — Mekanistik; tidak ada fundamental bias
3. **Confluence** — Phase + MA + Volume semua harus align untuk high confidence
4. **Capital Preservation** — Gates dirancang untuk avoid catastrophic losses, bukan maximize profits

---

## 📞 Handoff Notes

- Algoritma v3.1 sudah final (reviewed & approved)
- Phase logic v2.1 tetap as-is (no regression risk)
- Implementation linear: logic.py → scraper_daily.py → app.py → frontend
- Test dengan backtest data (01-05-2026 onwards) sebelum production
- Jika ada edge cases, jangan change core logic — escalate untuk discussion

---

**Document Version:** v3.1-handoff  
**Date:** 01-05-2026  
**Next Steps:** Implementation + Testing in Claude Code session

