"""
logic.py — Zenith Phase Classification Engine v3.1
====================================================
Single source of truth for all phase/action/watch computation.
Imported by app.py, scraper_daily.py, and backtest engine.

DO NOT duplicate this logic elsewhere. If thresholds change, change here only.
"""


# ── Phase Classification ──────────────────────────────────────────────────────

def classify_zenith_v3_1(
    sri: float,
    rsm: float,
    rpr: float,
    pchg,           # float or None
    bm_val: float,
    bm_sma10: float,
    atr_pct=None,
) -> str:
    """
    Classify Wyckoff phase using Zenith v3.1 logic.

    Parameters
    ----------
    sri      : SM Relative Intensity (trimmed mean based)
    rsm      : SM % of total value  (0–100)
    rpr      : Sell pressure ratio  (tx_bm / total_tx)
    pchg     : Daily price change % (None = unknown)
    bm_val   : Today's BM value (Juta)
    bm_sma10 : Simple mean BM last 10 days (0 = no history)
    atr_pct  : Average True Range % (None = use default 2.5)

    Returns
    -------
    str : phase label
    """
    atr      = atr_pct if atr_pct and atr_pct > 0 else 2.5
    th_up    = max(atr * 0.8, 1.0)   # significant up   (min 1%)
    th_down  = max(atr * 0.4, 0.5)   # significant down (min 0.5%)
    th_flat  = atr * 0.5             # flat zone

    # BM activity gate: BM today must be ≥50% of its own 10-day avg
    # Prevents DISTRI firing on days SM is absent but BM is just noise
    # If no BM history → gate is open (new/inactive ticker)
    if bm_sma10 == 0:
        bm_gate = True
    else:
        bm_gate = bm_val > bm_sma10 * 0.5

    if pchg is None:
        return "NEUTRAL"

    # 1. SOS — Sign of Strength
    # v3.1: OR clause — jika SM sangat agresif (SRI > 4.0), RSM dilonggarkan ke > 60%
    if pchg > th_up and ((rsm > 65 and sri > 3.0) or (rsm > 60 and sri > 4.0)):
        return "SOS"

    # 2. UPTHRUST — Trap: price up but big players distributing
    if pchg > th_up and rsm < 40 and rpr > 0.6:
        return "UPTHRUST"

    # 3. ABSORB — Stealth accumulation: SM very active, price flat
    #    pchg > -th_down: prevents overlap with SPRING zone
    if sri > 2.0 and rsm > 65 and pchg > -th_down and abs(pchg) < th_flat:
        return "ABSORB"

    # 4. SPRING — Price drops but SM accumulating aggressively
    if pchg < -th_down and rsm > 60 and sri > 1.5:
        return "SPRING"

    # 5. DISTRI — Active distribution
    if rsm < 40 and pchg < -(th_down * 0.5) and rpr > 0.4 and bm_gate:
        return "DISTRI"

    # 6. ACCUM — Steady accumulation, SM dominant
    if rsm > 60 and sri > 1.0:
        return "ACCUM"

    # 7. DISTRI Fallback — BM overwhelmingly dominant by tx count
    if rsm < 35 and rpr > 0.5 and bm_gate:
        return "DISTRI"

    return "NEUTRAL"


# ── Action Signal ─────────────────────────────────────────────────────────────

def get_action(
    phase: str,
    pchg,
    atr_pct=None,
    bm_val: float = 0,
    bm_sma10: float = 0,
    watch_flag=None,
) -> str:
    """
    Derive trading action from phase with 3 safety gates (v3.1).

    Gate A — Supply Gate   : bm_val > bm_sma10 × 3.0  → HOLD
    Gate B — ARB Safety    : watch_flag == "ARB_SPRING" → HOLD
    Gate C — Anti-Pucuk    : pchg >= threshold per phase → HOLD
                             SOS: max(atr × 3.5, 7.0)  — SOS allowed to run higher
                             Others: max(atr × 2.0, 5.0)
    """
    atr       = atr_pct if atr_pct and atr_pct > 0 else 2.5
    th_sos_h  = max(atr * 3.5, 7.0)   # SOS: more room to run
    th_buy_h  = max(atr * 2.0, 5.0)   # SPRING / ABSORB / ACCUM

    BUY_PHASES  = ("SOS", "SPRING", "ABSORB", "ACCUM")
    SELL_PHASES = ("UPTHRUST", "DISTRI")

    if phase in SELL_PHASES:
        return "SELL"

    if phase not in BUY_PHASES:
        return "HOLD"

    # Gate A: Supply Gate — BM hari ini 3x rata-rata normal = tembok penjual masif
    if bm_sma10 > 0 and bm_val > bm_sma10 * 3.0:
        return "HOLD"

    # Gate B: ARB Safety — SPRING dengan penurunan ekstrim
    if watch_flag == "ARB_SPRING":
        return "HOLD"

    # Gate C: Anti-Pucuk — SOS gets higher ceiling, other BUY phases stricter
    limit = th_sos_h if phase == "SOS" else th_buy_h
    if pchg is not None and pchg >= limit:
        return "HOLD"

    return "BUY"


# ── ARB Watch Flag ────────────────────────────────────────────────────────────

def get_watch_flag(phase: str, pchg, atr_pct=None):
    """
    Return "ARB_SPRING" if SPRING occurs during extreme drop (>1.5× ATR).
    Phase remains SPRING; frontend displays ⚠️ WATCH when action == HOLD && watch == ARB_SPRING.
    """
    atr = atr_pct if atr_pct and atr_pct > 0 else 2.5
    if phase == "SPRING" and pchg is not None and pchg < -(atr * 1.5):
        return "ARB_SPRING"
    return None


# ── Gate Condition Detector (for Trade Detail) ────────────────────────────────

def detect_trade_detail_gate(
    phase: str,
    pchg,
    bm_val: float,
    bm_sma10: float,
    atr_pct=None,
    action: str = None,
) -> str:
    """
    Detect which (if any) Gate condition is active for Trade Detail display.

    Gate A: Supply Gate — BM today > BM SMA10 × 3.0 (abnormal selling pressure)
    Gate B: Extreme Panic — SPRING phase with pchg < -(ATR × 1.5) (ARB risk)
    Gate C: Profit Taking — BUY action (SOS/SPRING/ABSORB/ACCUM) with pchg > ATR × 2.0

    Returns: "Gate A", "Gate B", "Gate C", or None
    """
    atr = atr_pct if atr_pct and atr_pct > 0 else 2.5

    # Gate A: Abnormal supply (BM spike)
    if bm_sma10 > 0 and bm_val > bm_sma10 * 3.0:
        return "Gate A"

    # Gate B: Extreme panic (SPRING with massive drop)
    if phase == "SPRING" and pchg is not None and pchg < -(atr * 1.5):
        return "Gate B"

    # Gate C: Profit taking (entry signal but price has run too far)
    if action == "BUY" and pchg is not None and pchg > atr * 2.0:
        return "Gate C"

    return None


# ── Technical Indicator Helpers (pure, no DB) ────────────────────────────────

def compute_ma(closes: list, period: int):
    """Simple Moving Average. closes = chronological list (oldest first)."""
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def compute_rsi14(closes: list):
    """Wilder RSI-14. closes = chronological (oldest first), needs ≥ 15 values."""
    if len(closes) < 15:
        return None
    relevant = closes[-15:]
    diffs = [relevant[i] - relevant[i - 1] for i in range(1, 15)]
    gains  = [max(d, 0)   for d in diffs]
    losses = [abs(min(d, 0)) for d in diffs]
    avg_gain = sum(gains)  / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def compute_cm_streak(closes: list, ma5):
    """Consecutive Momentum: days close above (+N) or below (-N) MA5.
    Returns None if insufficient data."""
    if ma5 is None or not closes:
        return None
    above = closes[-1] > ma5
    streak = 0
    for c in reversed(closes):
        if (c > ma5) == above:
            streak += 1
        else:
            break
    return streak if above else -streak


# ── MA Structure Classifier (v3.1 — 6 types) ──────────────────────────────────

def get_ma_structure(price, ma5, ma13, ma34, ma200=None) -> str:
    """
    Classify MA alignment into 6 structure types.

    1. Strong Uptrend:      price > ma5 > ma13 > ma34 > ma200
    2. Transitional Uptrend: price > ma5 > ma13 > ma34, but ma34 < ma200
    3. Bullish Messy:       price > ma200, but ma5/13/34 are misaligned
    4. Sideways:            all MA within 2.5% spread (consolidated)
    5. Strong Downtrend:    price < ma5 < ma13 < ma34 < ma200
    6. Transitional Downtrend: price < ma5 < ma13 < ma34, but ma34 > ma200
    """
    if price is None or (ma5 is None and ma13 is None):
        return "N/A"

    # ── Strong Uptrend: full bullish stack ──
    if (ma5 is not None and ma13 is not None and ma34 is not None and
        ma200 is not None and price > ma5 > ma13 > ma34 > ma200):
        return "Strong Uptrend"

    # ── Strong Downtrend: full bearish stack ──
    if (ma5 is not None and ma13 is not None and ma34 is not None and
        ma200 is not None and price < ma5 < ma13 < ma34 < ma200):
        return "Strong Downtrend"

    # ── Sideways: all MA clustered (< 2.5% spread) ──
    if ma5 is not None and ma13 is not None and ma34 is not None:
        ma_max = max(ma5, ma13, ma34)
        ma_min = min(ma5, ma13, ma34)
        spread_pct = (ma_max - ma_min) / ma_max * 100
        if spread_pct < 2.5:
            return "Sideways"

    # ── Transitional Uptrend: bullish but ma34 above ma200 ──
    if (ma5 is not None and ma13 is not None and ma34 is not None and
        ma200 is not None and price > ma5 > ma13 > ma34 and ma34 < ma200):
        return "Transitional Uptrend"

    # ── Transitional Downtrend: bearish but ma34 below ma200 ──
    if (ma5 is not None and ma13 is not None and ma34 is not None and
        ma200 is not None and price < ma5 < ma13 < ma34 and ma34 > ma200):
        return "Transitional Downtrend"

    # ── Bullish Messy: price above ma200 but MA stack broken ──
    if price is not None and ma200 is not None and price > ma200:
        return "Bullish Messy"

    # Fallback
    return "Transitional"


# ── Phase × MA Structure Narrative (6 structures × 7 phases = 42 combinations) ──

_PHASE_NARRATIVE: dict = {
    # 1. STRONG UPTREND (MA5 > MA13 > MA34 > MA200)
    ("SOS",      "Strong Uptrend"):  "Strongest Momentum: Smart Money sangat agresif melakukan markup di tengah tren yang sudah solid. Conviction sangat tinggi.",
    ("ACCUM",    "Strong Uptrend"):  "Trend Support: Akumulasi bertahap terus berlanjut guna memperkuat struktur kenaikan harga.",
    ("ABSORB",   "Strong Uptrend"):  "High-Level Base: Smart Money menyerap pasokan di harga atas tanpa membiarkan harga terkoreksi.",
    ("SPRING",   "Strong Uptrend"):  "Buying the Dip: Koreksi sesaat yang langsung disambar Smart Money. ⚠️ Cek volume saat koreksi — jika volume besar, waspada: bisa jadi distribusi terselubung, bukan spring valid.",
    ("UPTHRUST", "Strong Uptrend"):  "The Trap: Waspada! Meskipun tren terlihat kuat, Smart Money mulai melakukan exit di harga pucuk.",
    ("DISTRI",   "Strong Uptrend"):  "Major Reversal: Distribusi aktif di tengah tren naik. Sinyal kuat bahwa tren segera berakhir.",
    ("NEUTRAL",  "Strong Uptrend"):  "Retail Drive: Harga naik hanya karena dorongan retail. Tanpa partisipasi Big Player, tren ini rapuh.",

    # 2. TRANSITIONAL UPTREND (MA5 > MA13 > MA34 < MA200)
    ("SOS",      "Transitional Uptrend"):  "Breakout Attempt: Smart Money mencoba menembus resistensi MA200 dengan agresivitas tinggi.",
    ("ACCUM",    "Transitional Uptrend"):  "Reversal Loading: Persiapan mengubah tren besar. Akumulasi stabil di bawah area MA200.",
    ("ABSORB",   "Transitional Uptrend"):  "Under Resistance Absorb: Smart Money menahan harga agar tidak jatuh sambil menyerap barang di bawah MA200.",
    ("SPRING",   "Transitional Uptrend"):  "Bottom Shakeout: Upaya terakhir mengusir retail sebelum harga dipacu menembus MA200. ⚠️ Cek volume saat koreksi — jika volume besar, waspada: bisa jadi distribusi terselubung, bukan spring valid.",
    ("UPTHRUST", "Transitional Uptrend"):  "Failed Breakout: Upaya naik gagal. Big Player justru jualan masif saat harga mendekati MA200.",
    ("DISTRI",   "Transitional Uptrend"):  "Rejected: Harga tertolak dari MA200 disertai aksi jual masif oleh Big Player.",
    ("NEUTRAL",  "Transitional Uptrend"):  "Wait & See: Harga mendekati resistensi besar tanpa ada pergerakan signifikan dari Smart Money.",

    # 3. BULLISH MESSY (Price > MA200 but MA5/13/34 berantakan)
    ("SOS",      "Bullish Messy"):  "Clarity Seeking: Smart Money masuk untuk mengakhiri fase konsolidasi dan memulai tren naik baru.",
    ("ACCUM",    "Bullish Messy"):  "Choppy Accum: Meskipun struktur MA berantakan, Smart Money konsisten menambah posisi.",
    ("ABSORB",   "Bullish Messy"):  "Volatility Absorption: Smart Money menenangkan market yang liar dengan menyerap setiap tekanan jual.",
    ("SPRING",   "Bullish Messy"):  "Technical Washout: Membersihkan antrean jual retail di tengah struktur MA yang membingungkan. ⚠️ Cek volume saat koreksi — jika volume besar, waspada: bisa jadi distribusi terselubung, bukan spring valid.",
    ("UPTHRUST", "Bullish Messy"):  "Churning Trap: Harga terlihat ingin naik dari kekacauan MA, tapi ternyata hanya jebakan jual.",
    ("DISTRI",   "Bullish Messy"):  "Structural Decay: Big Player memanfaatkan kekacauan harga untuk keluar perlahan dari posisi mereka.",
    ("NEUTRAL",  "Bullish Messy"):  "No Direction: Market bergerak acak tanpa penggerak utama. Hindari sampai struktur MA rapi.",

    # 4. SIDEWAYS (Semua MA berhimpit)
    ("SOS",      "Sideways"):  "Early Breakout: Ledakan volume dan agresivitas Smart Money untuk keluar dari zona konsolidasi.",
    ("ACCUM",    "Sideways"):  "Base Building: Pengumpulan barang secara rapi di area harga yang sama dalam waktu lama.",
    ("ABSORB",   "Sideways"):  "The Coil: Energi sedang dikumpulkan. Smart Money menyerap semua barang tanpa menggerakkan harga.",
    ("SPRING",   "Sideways"):  "Final Shakeout: Harga ditarik turun sebentar untuk memicu stop loss retail sebelum dilesatkan naik. ⚠️ Cek volume saat koreksi — jika volume besar, waspada: bisa jadi distribusi terselubung, bukan spring valid.",
    ("UPTHRUST", "Sideways"):  "False Start: Harga sempat naik dari zona sideways namun segera dibanting kembali. ⚠️ Cek transaksi BM hari ini — jika BM spike jauh di atas SMA10, ini manipulasi aktif (buang barang). Jika BM normal, cukup tekanan supply biasa.",
    ("DISTRI",   "Sideways"):  "Silent Exit: Big Player keluar perlahan di saat market sedang membosankan.",
    ("NEUTRAL",  "Sideways"):  "Dead Zone: Belum ada tanda-tanda kehidupan dari Smart Money. Market sedang tidur.",

    # 5. STRONG DOWNTREND (MA5 < MA13 < MA34 < MA200)
    ("SOS",      "Strong Downtrend"):  "V-Shape Rebound: Spekulasi tinggi! SM masuk agresif melawan arus. ⚠️ Cek struktur MA — apakah mulai merata/konvergen? Jika masih divergen bearish penuh, SM masuk belum berarti reversal confirmed.",
    ("ACCUM",    "Strong Downtrend"):  "Bottom Fishing: Mulai terjadi penumpukan barang di harga bawah meski tren belum berbalik.",
    ("ABSORB",   "Strong Downtrend"):  "Floor Building: Smart Money mencoba menghentikan kejatuhan harga dengan menyerap semua tekanan jual.",
    ("SPRING",   "Strong Downtrend"):  "Classic Spring: Harga jatuh tajam ke area baru, namun langsung diborong habis oleh Smart Money. ⚠️ Cek volume saat koreksi — jika volume besar, waspada: bisa jadi distribusi terselubung, bukan spring valid.",
    ("UPTHRUST", "Strong Downtrend"):  "Dead Cat Bounce: Kenaikan semu. Big Player justru menambah posisi jual saat harga naik sedikit.",
    ("DISTRI",   "Strong Downtrend"):  "Panic Continuous: Distribusi terus berlanjut. Tidak ada tanda-tanda dasar harga sudah terbentuk.",
    ("NEUTRAL",  "Strong Downtrend"):  "Drift Down: Harga turun perlahan tanpa pendorong jelas dari kedua pihak. Hindari entry — tren belum berakhir meski tidak ada tekanan besar.",

    # 6. TRANSITIONAL DOWNTREND (MA5 < MA13 < MA34 > MA200)
    ("SOS",      "Transitional Downtrend"):  "Defense of the Line: Smart Money masuk agresif untuk menjaga agar harga tidak tembus ke bawah MA200.",
    ("ACCUM",    "Transitional Downtrend"):  "Support Loading: Akumulasi dilakukan tepat di area dukungan jangka panjang (MA200).",
    ("ABSORB",   "Transitional Downtrend"):  "Dynamic Support: Tekanan jual di area MA200 berhasil diredam oleh akumulasi Smart Money.",
    ("SPRING",   "Transitional Downtrend"):  "Support Shakeout: Harga sengaja dibuat menembus MA200 sesaat untuk memicu panik sebelum ditarik kembali. ⚠️ Cek volume saat koreksi — jika volume besar, waspada: bisa jadi distribusi terselubung, bukan spring valid.",
    ("UPTHRUST", "Transitional Downtrend"):  "Structural Failure: Upaya kembali ke jalur Bullish gagal karena Big Player justru jualan masif.",
    ("DISTRI",   "Transitional Downtrend"):  "Breaking the Floor: Sinyal bahaya besar. Big Player membuang barang dan menekan harga ke bawah MA200.",
    ("NEUTRAL",  "Transitional Downtrend"):  "Testing Support: Harga sedang menguji MA200 tanpa partisipasi aktif dari Smart Money.",
}


# ── Gate Condition Overrides ──────────────────────────────────────────────────

_GATE_NARRATIVES = {
    "Gate A": "⚠️ Gate A — Abnormal Supply: Meskipun fase akumulasi, tekanan jual (Bad Money) hari ini 3× lipat rata-rata. Area ini sangat berisiko.",
    "Gate B": "⚠️ Gate B — Extreme Panic: Terdeteksi fase SPRING, namun penurunan harga terlalu ekstrim (>1.5× ATR). Risiko ARB tinggi.",
    "Gate C": "⚠️ Gate C — Profit Taking Zone: Sinyal BUY valid, namun harga naik terlalu tinggi hari ini (>2× ATR). Tunggu koreksi ke area MA5.",
}


def get_phase_narrative(phase: str, ma_structure: str, gate: str = None) -> str:
    """Return Phase × MA Structure narrative, with optional Gate override."""
    if gate and gate in _GATE_NARRATIVES:
        return _GATE_NARRATIVES[gate]
    return _PHASE_NARRATIVE.get((phase, ma_structure), f"Phase {phase} dalam {ma_structure}.")
