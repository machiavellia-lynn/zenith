"""
logic.py — Zenith Phase Classification Engine v2.1
====================================================
Single source of truth for all phase/action/watch/SL computation.
Imported by app.py, scraper_daily.py, and backtest engine.

DO NOT duplicate this logic elsewhere. If thresholds change, change here only.
"""


# ── IDX Price Fraction ────────────────────────────────────────────────────────

def floor_to_fraction(price: float) -> int:
    """Round price DOWN to nearest valid IDX price fraction (tick size)."""
    if price <= 0:
        return 0
    if price < 200:
        f = 1
    elif price < 500:
        f = 2
    elif price < 2000:
        f = 5
    elif price < 5000:
        f = 10
    else:
        f = 25
    return int(price // f) * f


# ── Phase Classification ──────────────────────────────────────────────────────

def classify_zenith_v2_1(
    sri: float,
    rsm: float,
    rpr: float,
    pchg,           # float or None
    bm_val: float,
    bm_sma10: float,
    atr_pct=None,
) -> str:
    """
    Classify Wyckoff phase using Zenith v2.1 logic.

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
    # th_sos_h used in get_action only

    # BM activity gate: BM today must be ≥50% of its own 10-day avg
    # Prevents DISTRI firing on days SM is absent but BM is just noise
    # If no BM history → gate is open (new/inactive ticker)
    if bm_sma10 == 0:
        bm_gate = True
    else:
        bm_gate = bm_val > bm_sma10 * 0.5

    # Primary guard: if price change unknown, cannot classify directional phases
    if pchg is None:
        return "NEUTRAL"

    # 1. SOS — Sign of Strength
    if pchg > th_up and rsm > 65 and sri > 3.0:
        return "SOS"

    # 2. UPTHRUST — Trap: price up but big players distributing
    if pchg > th_up and rsm < 40 and rpr > 0.6:
        return "UPTHRUST"

    # 3. ABSORB — Stealth accumulation: SM very active, price flat
    #    pchg > -th_down: prevents overlap with SPRING zone
    #    Explicit pchg is not None: defense-in-depth (primary guard above handles this)
    if pchg is not None and sri > 2.0 and rsm > 65 and pchg > -th_down and abs(pchg) < th_flat:
        return "ABSORB"

    # 4. SPRING — Price drops but SM accumulating aggressively
    if pchg < -th_down and rsm > 60 and sri > 1.5:
        return "SPRING"

    # 5. DISTRI — Active distribution
    #    SRI intentionally removed: SM absent ≠ no distribution (blind spot fix)
    #    rpr > 0.4: BM transaction proportion is dominant
    #    bm_gate:   BM today is not just noise vs its own history
    #    Explicit pchg is not None: defense-in-depth (primary guard above handles this)
    if pchg is not None and rsm < 40 and pchg < -(th_down * 0.5) and rpr > 0.4 and bm_gate:
        return "DISTRI"

    # 6. ACCUM — Steady accumulation, SM dominant
    if rsm > 60 and sri > 1.0:
        return "ACCUM"

    # 7. DISTRI Fallback — BM overwhelmingly dominant by tx count
    if rsm < 35 and rpr > 0.5 and bm_gate:
        return "DISTRI"

    return "NEUTRAL"


# ── Action Signal ─────────────────────────────────────────────────────────────

def get_action(phase: str, pchg, atr_pct=None) -> str:
    """Derive trading action from phase."""
    atr      = atr_pct if atr_pct and atr_pct > 0 else 2.5
    th_sos_h = max(atr * 2.0, 5.0)  # SOS already ran too high → HOLD

    if phase == "SOS":
        return "BUY" if (pchg is not None and pchg < th_sos_h) else "HOLD"
    if phase in ("SPRING", "ABSORB", "ACCUM"):
        return "BUY"
    if phase in ("UPTHRUST", "DISTRI"):
        return "SELL"
    return "HOLD"  # NEUTRAL


# ── ARB Watch Flag ────────────────────────────────────────────────────────────

def get_watch_flag(phase: str, pchg, atr_pct=None):
    """
    Return "ARB_SPRING" if SPRING occurs during extreme drop (>1.5× ATR).
    This signals elevated risk — the drop may be approaching Auto Rejection Bawah.
    Phase remains SPRING, action remains BUY, but user gets a visual warning.
    """
    atr = atr_pct if atr_pct and atr_pct > 0 else 2.5
    if phase == "SPRING" and pchg is not None and pchg < -(atr * 1.5):
        return "ARB_SPRING"
    return None


# ── Suggested Stop Loss ───────────────────────────────────────────────────────

def get_suggested_sl(price_close, atr_pct):
    """
    Calculate SL = price × (1 − ATR% × 2.0), rounded DOWN to IDX price fraction.
    Returns None if inputs are missing.
    """
    if not price_close or not atr_pct or price_close <= 0 or atr_pct <= 0:
        return None
    raw_sl = price_close * (1.0 - (atr_pct / 100.0) * 2.0)
    if raw_sl <= 0:
        return None
    return floor_to_fraction(raw_sl)
