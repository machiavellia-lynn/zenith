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


# ── MA Structure Classifier ───────────────────────────────────────────────────

def get_ma_structure(price, ma5, ma13, ma34, ma200=None) -> str:
    """
    Classify MA alignment.
    Strong Uptrend : price > ma5 > ma13 > ma34
    Downtrend      : price < ma5 < ma13 < ma34
    Sideways       : ma5/13/34 within 2.5% spread
    Transitional   : everything else (mixed / converging)
    """
    if price is None:
        return "N/A"
    if ma5 is None and ma13 is None:
        return "N/A"

    if ma5 is not None and ma13 is not None and ma34 is not None:
        if price > ma5 > ma13 > ma34:
            return "Strong Uptrend"
        if price < ma5 < ma13 < ma34:
            return "Downtrend"
        spread_pct = (max(ma5, ma13, ma34) - min(ma5, ma13, ma34)) / max(ma5, ma13, ma34) * 100
        if spread_pct < 2.5:
            return "Sideways"
        return "Transitional"

    if ma5 is not None and ma13 is not None:
        if price > ma5 > ma13:
            return "Strong Uptrend"
        if price < ma5 < ma13:
            return "Downtrend"
    return "Transitional"


# ── Phase × MA Structure Narrative ───────────────────────────────────────────

_PHASE_NARRATIVE: dict = {
    ("SOS",      "Strong Uptrend"):  "Momentum kuat — SM mendorong dengan konfirmasi MA penuh. Probabilitas kelanjutan naik tinggi.",
    ("SOS",      "Transitional"):    "SM agresif saat MA belum stack — watchlist konfirmasi golden cross atau MA13 > MA34.",
    ("SOS",      "Sideways"):        "Breakout potensial dari konsolidasi — SM menekan harga keluar range. Konfirmasi volume kunci.",
    ("SOS",      "Downtrend"):       "Counter-trend rally — SM melawan tren utama. Manajemen risiko ketat, ukuran posisi kecil.",
    ("SPRING",   "Strong Uptrend"):  "Pullback sehat dalam uptrend — entry ideal sebelum kelanjutan naik. Risk/reward optimal.",
    ("SPRING",   "Transitional"):    "SM akumulasi saat koreksi — tunggu konfirmasi bounce dari support MA13 atau MA34.",
    ("SPRING",   "Sideways"):        "SM masuk di batas bawah range — potensi reversal dari support konsolidasi.",
    ("SPRING",   "Downtrend"):       "SPRING dalam downtrend — SM melawan tekanan jual besar. Butuh konfirmasi volume kuat dan MA reversal.",
    ("ABSORB",   "Strong Uptrend"):  "SM akumulasi diam-diam dalam uptrend — persiapan sebelum push berikutnya.",
    ("ABSORB",   "Transitional"):    "Akumulasi tersembunyi saat MA konvergen — potensi breakout jika MA stack mulai terbentuk.",
    ("ABSORB",   "Sideways"):        "SM terakumulasi di zona konsolidasi — tunggu breakout dari range dengan volume konfirmasi.",
    ("ABSORB",   "Downtrend"):       "SM menyerap tekanan jual dalam downtrend — potensi reversal, tapi butuh konfirmasi MA turn.",
    ("ACCUM",    "Strong Uptrend"):  "Akumulasi bertahap dalam tren kuat — SM support harga di setiap koreksi kecil.",
    ("ACCUM",    "Transitional"):    "SM bertahap mengakumulasi saat MA belum aligned — risiko moderat, monitor perkembangan MA.",
    ("ACCUM",    "Sideways"):        "Akumulasi bertahap di zona sideways — potensi breakout ke atas jika volume meningkat.",
    ("ACCUM",    "Downtrend"):       "Akumulasi dalam downtrend — too early. Tunggu konfirmasi MA reversal sebelum masuk.",
    ("UPTHRUST", "Strong Uptrend"):  "Jebakan naik meski uptrend — distribusi di resistance atas. Waspadai reversal mendadak.",
    ("UPTHRUST", "Transitional"):    "Upthrust di MA konvergen — false breakout klasik. BM dominasi di harga tinggi, hindari.",
    ("UPTHRUST", "Sideways"):        "Upthrust di batas atas range — distribusi klasik. Target penurunan ke support bawah range.",
    ("UPTHRUST", "Downtrend"):       "Jebakan naik dalam downtrend — distribusi agresif. Hindari atau pertimbangkan short.",
    ("DISTRI",   "Strong Uptrend"):  "Distribusi meski MA bullish — SM jual ke retail yang masih optimis. Waspadai reversal cepat.",
    ("DISTRI",   "Transitional"):    "Distribusi aktif saat MA belum confirmed — momentum jual mendahului penurunan MA.",
    ("DISTRI",   "Sideways"):        "Distribusi di zona sideways — BM jual ke support. Potensi breakdown dari bawah range.",
    ("DISTRI",   "Downtrend"):       "Distribusi dalam downtrend — konfirmasi bearish penuh. Hindari posisi baru.",
    ("NEUTRAL",  "Strong Uptrend"):  "Sinyal lemah dalam uptrend — SM tidak aktif hari ini. Hold dan pantau apakah SM kembali.",
    ("NEUTRAL",  "Transitional"):    "Tidak ada sinyal jelas dan MA belum aligned — tunggu sinyal yang lebih kuat.",
    ("NEUTRAL",  "Sideways"):        "Konsolidasi tanpa SM aktif — tunggu breakout dari range dengan SM participation.",
    ("NEUTRAL",  "Downtrend"):       "Tidak ada SM aktif dalam downtrend — hindari posisi baru, pantau dari jarak aman.",
}


def get_phase_narrative(phase: str, ma_structure: str) -> str:
    """Return Phase × MA Structure narrative."""
    return _PHASE_NARRATIVE.get((phase, ma_structure), f"Phase {phase} dalam {ma_structure}.")
