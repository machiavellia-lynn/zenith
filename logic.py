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
