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
    th_buy_h = max(atr * 2.0, 5.0)
    if action == "BUY" and pchg is not None and pchg >= th_buy_h:
        return "Gate C"

    return None


# ── Technical Indicator Helpers (pure, no DB) ────────────────────────────────

def compute_ma(closes: list, period: int):
    """Simple Moving Average. closes = chronological list (oldest first).
    Returns None if insufficient data (< period required)."""
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


# ── MA Structure Classifier (v3.1 — 8 types) ──────────────────────────────────

def get_ma_structure(price, ma5, ma13, ma34, ma200=None) -> str:
    """
    Classify MA alignment into 8 structure types per Zenith v3.1 catalog.

    gap = (max(MA5,MA13,MA34) - min(MA5,MA13,MA34)) / min(MA5,MA13,MA34) * 100

    gap < 3%:
      Price > MA200 → Cluster on Macro Uptrend
      Price ≤ MA200 → Cluster on Macro Downtrend

    gap ≥ 3%, aligned_up (MA5>MA13>MA34):
      Price > MA200 → Strong Uptrend
      Price ≤ MA200 → Transitional Uptrend

    gap ≥ 3%, aligned_down (MA5<MA13<MA34):
      Price > MA200 → Transitional Correction
      Price ≤ MA200 → Strong Downtrend

    gap ≥ 3%, messy (crossed):
      Price > MA200 → Bullish Messy
      Price ≤ MA200 → Bearish Messy
    """
    if price is None or ma5 is None or ma13 is None or ma34 is None:
        return "N/A"

    ma_max = max(ma5, ma13, ma34)
    ma_min = min(ma5, ma13, ma34)
    if ma_min == 0:
        return "N/A"
    gap = (ma_max - ma_min) / ma_min * 100

    above_ma200 = (ma200 is None) or (price > ma200)

    if gap < 3.0:
        return "Cluster on Macro Uptrend" if above_ma200 else "Cluster on Macro Downtrend"

    aligned_up   = ma5 > ma13 > ma34
    aligned_down = ma5 < ma13 < ma34

    if aligned_up:
        return "Strong Uptrend" if above_ma200 else "Transitional Uptrend"

    if aligned_down:
        return "Transitional Correction" if above_ma200 else "Strong Downtrend"

    return "Bullish Messy" if above_ma200 else "Bearish Messy"


# ── Phase × MA Structure Narrative (8 structures × 7 phases = 56 combinations) ──

_PHASE_NARRATIVE: dict = {
    # 1. STRONG UPTREND
    ("SOS",      "Strong Uptrend"): "Strongest Momentum — Smart Money sangat agresif di tengah tren yang sudah kuat. Konfluensi sempurna antara struktur MA bullish dan aksi SM, ini adalah setup dengan probabilitas tertinggi. Hati-hati FOMO di entry terlambat; pastikan tidak trigger Gate C.",
    ("SPRING",   "Strong Uptrend"): "Pullback Sehat — Harga koreksi sementara di tengah tren bullish yang kuat, dan SM justru akumulasi di zona ini. Ini adalah \"buy the dip\" klasik dalam strong uptrend; setup sangat menarik jika RSM dan SRI confirm. Entry di zona SPRING dengan struktur MA intact adalah opportunity premium.",
    ("ABSORB",   "Strong Uptrend"): "Silent Accumulation in Trend — SM mengakumulasi diam-diam tanpa banyak gerak harga, sementara struktur MA masih fully bullish. Kombinasi ini sering mendahului breakout berikutnya. Volume rendah tapi SM aktif = distribusi tersembunyi yang positif.",
    ("ACCUM",    "Strong Uptrend"): "Steady Climb — SM mengakumulasi secara bertahap dengan tren yang fully aligned. Tidak ada urgency tinggi, tapi ini adalah posisi yang nyaman untuk hold atau tambah posisi secara gradual. Risiko rendah karena struktur makro mendukung penuh.",
    ("UPTHRUST", "Strong Uptrend"): "Trap di Puncak Tren — Harga naik tinggi tapi BM dominan dan RPR lemah, sinyal jebakan distribusi meski struktur MA masih bullish. Ini warning penting: MA bisa lag terhadap perubahan arah. Waspadai potensi reversal jangka pendek meski tren besar masih intact.",
    ("DISTRI",   "Strong Uptrend"): "Distribusi Tersembunyi — BM mulai aktif mendistribusi meski MA masih bullish aligned. Ini adalah early warning sign sebelum tren berbalik; MA biasanya lag beberapa hari. Hold posisi lama dengan trailing stop, hindari entry baru sampai ada konfirmasi.",
    ("NEUTRAL",  "Strong Uptrend"): "Konsolidasi dalam Tren Kuat — Tidak ada aksi SM atau BM yang dominan hari ini, pasar istirahat sejenak. Struktur MA masih bullish penuh; ini bukan sinyal untuk keluar. Hold posisi, tunggu fase berikutnya yang kemungkinan besar masih bullish.",

    # 2. TRANSITIONAL UPTREND
    ("SOS",      "Transitional Uptrend"): "Recovery Agresif — SM masuk besar-besaran dalam fase pemulihan awal, tapi MA200 masih di atas sebagai resistance besar. Sinyal kuat untuk jangka pendek-menengah, tapi harga masih harus membuktikan diri dengan break MA200. Entry menarik dengan awareness bahwa ada resistance signifikan di depan.",
    ("SPRING",   "Transitional Uptrend"): "Dip dalam Recovery — Harga koreksi sementara di tengah fase pemulihan yang belum selesai, SM tetap akumulasi. Double-layered risk: belum break MA200 dan harga turun. Namun jika SRI dan RSM kuat, ini bisa jadi entry second chance yang bagus dalam recovery play.",
    ("ABSORB",   "Transitional Uptrend"): "Akumulasi Diam-diam Sebelum Break — SM mengakumulasi dengan tenang sementara harga flat, membangun energi untuk potensi break MA200. Patience diperlukan; ini adalah setup jangka menengah yang menjanjikan tapi belum ada katalis langsung.",
    ("ACCUM",    "Transitional Uptrend"): "Pemulihan Bertahap — Momentum bullish jangka pendek terbentuk perlahan, SM mulai masuk secara gradual meski MA200 masih jadi ceiling. Cocok untuk akumulasi bertahap dengan position sizing konservatif; avoid all-in karena resistance makro masih ada.",
    ("UPTHRUST", "Transitional Uptrend"): "Fake Recovery — Harga naik tapi BM mendominasi transaksi, membuat rally dalam recovery terlihat seperti jebakan distribusi. Dengan MA200 masih di atas sebagai overhead resistance, ini adalah sinyal sangat berbahaya. Hindari entry, pertimbangkan exit jika sudah punya posisi.",
    ("DISTRI",   "Transitional Uptrend"): "Recovery Terancam — Momentum pemulihan terganggu oleh distribusi aktif BM. Dengan MA200 masih di atas, ini bisa menjadi awal dari kegagalan recovery dan kelanjutan downtrend. Sinyal untuk reduce exposure; tunggu konfirmasi sebelum re-entry.",
    ("NEUTRAL",  "Transitional Uptrend"): "Jeda dalam Recovery — Pasar pause, tidak ada dominasi SM atau BM hari ini. Tren pemulihan masih intact tapi belum ada dorongan baru. Hold, dan tunggu konfirmasi arah berikutnya; MA200 masih jadi target resistance yang perlu diperhatikan.",

    # 3. TRANSITIONAL CORRECTION
    ("SOS",      "Transitional Correction"): "Counter-Rally Kuat — SM masuk agresif di tengah tekanan jual jangka pendek, dengan MA200 masih sebagai support besar di bawah. Ini sinyal reversal jangka pendek yang menarik; potensi bounce dari zona koreksi. Entry kalkulatif dengan target kembali ke area MA34 atau lebih tinggi.",
    ("SPRING",   "Transitional Correction"): "Bounce dari Support Makro — Harga turun lebih dalam tapi SM aktif akumulasi, dengan MA200 di bawah sebagai safety net. Setup SPRING dalam konteks koreksi makro bullish adalah salah satu setup terbaik untuk swing entry; risiko relatif terbatas karena floor makro jelas.",
    ("ABSORB",   "Transitional Correction"): "Akumulasi di Koreksi — SM diam-diam membeli saat harga flat dalam periode koreksi, sinyal bahwa big players tidak panik meski MA jangka pendek bearish. Dengan MA200 masih sebagai safety net, ini setup yang menjanjikan untuk entry gradual.",
    ("ACCUM",    "Transitional Correction"): "Akumulasi Defensif — SM mulai masuk secara perlahan di zona koreksi, meski belum dengan intensitas tinggi. Posisi makro masih mendukung (Price > MA200); ini fase persiapan sebelum potensi reversal. Cocok untuk gradual entry dengan stop di bawah MA200.",
    ("UPTHRUST", "Transitional Correction"): "Dead Cat Bounce — Harga sempat naik tapi BM yang dominan; bounce ini tidak genuine. Dalam konteks koreksi jangka pendek yang sudah berjalan, UPTHRUST menandakan tekanan jual belum selesai. Exit atau hold cash; bukan waktu untuk beli.",
    ("DISTRI",   "Transitional Correction"): "Koreksi Diperdalam — BM aktif mendistribusi di tengah koreksi yang sudah berjalan; tekanan jual bertambah. Meskipun MA200 masih di bawah sebagai support, momentum bearish jangka pendek bisa mendorong harga lebih turun sebelum bounce. Reduce exposure.",
    ("NEUTRAL",  "Transitional Correction"): "Koreksi Tanpa Arah Jelas — Tidak ada dominasi SM atau BM, pasar bergerak sideways dalam zona koreksi. MA200 masih di bawah sebagai safety net. Situasi wait-and-see; pantau apakah SM mulai masuk (SPRING/ACCUM) atau BM semakin dominan (DISTRI).",

    # 4. STRONG DOWNTREND
    ("SOS",      "Strong Downtrend"): "Counter-Rally dalam Downtrend — SM masuk agresif tapi melawan arus tren besar yang sepenuhnya bearish. Ini bisa jadi bounce signifikan tapi bukan reversal; MA200 dan MA34 di atas sebagai resistance berlapis. Trading jangka sangat pendek dengan risk management ketat; jangan hold lama.",
    ("SPRING",   "Strong Downtrend"): "Potensi Capitulation Bottom — Harga turun tajam dengan SM akumulasi di zona yang sangat tertekan. Dalam strong downtrend, SPRING bisa menjadi tanda capitulation (akhir dari tekanan jual besar). Setup sangat high-risk, high-reward; perlu konfirmasi kuat (SRI > 2.5, RSM > 65%) sebelum pertimbangkan entry.",
    ("ABSORB",   "Strong Downtrend"): "Akumulasi Melawan Arus — SM diam-diam membeli di tengah downtrend yang masih kuat. Bisa jadi early signal reversal jangka panjang, tapi premature untuk entry; tren besar masih bearish dan semua MA di atas sebagai resistance. Watch tapi tidak act dulu.",
    ("ACCUM",    "Strong Downtrend"): "Akumulasi Awal di Downtrend Dalam — SM mulai masuk perlahan meski tren besar masih turun. Sinyal terlalu dini untuk action; perlu konfirmasi beberapa hari sebelum struktur MA berubah. Pantau apakah akumulasi ini berkembang menjadi ABSORB atau SOS.",
    ("UPTHRUST", "Strong Downtrend"): "Jebakan Bull dalam Downtrend — Harga sempat naik tapi BM dominan; ini adalah relief rally palsu yang sangat berbahaya. Dalam strong downtrend, UPTHRUST adalah konfirmasi bahwa tekanan jual masih kuat dan banyak yang terjebak di harga tinggi. Sinyal SELL paling meyakinkan.",
    ("DISTRI",   "Strong Downtrend"): "Downtrend Diperkuat — BM aktif mendistribusi dengan semua MA masih bearish; ini adalah konfirmasi downtrend paling kuat. Tidak ada alasan untuk hold, apalagi beli. Jika belum exit, ini momentum terakhir sebelum harga turun lebih dalam.",
    ("NEUTRAL",  "Strong Downtrend"): "Downtrend Tanpa Katalis Baru — Tidak ada aksi dominan hari ini, tapi semua MA masih bearish aligned. Ini bukan tanda reversal; hanya jeda sementara. Jangan terjebak dengan quiet market dalam downtrend; stay out atau pertahankan short position.",

    # 5. CLUSTER ON MACRO UPTREND
    ("SOS",      "Cluster on Macro Uptrend"): "Breakout dari Sideways — SM masuk besar di tengah konsolidasi yang sudah lama, dengan floor makro yang aman (Price > MA200). Setup pre-breakout klasik; jika SRI dan RSM kuat, ini sangat menarik. Harga kemungkinan besar akan keluar dari cluster dengan momentum bullish.",
    ("SPRING",   "Cluster on Macro Uptrend"): "Shakeout dalam Konsolidasi — Harga turun sementara keluar dari cluster tapi SM aktif akumulasi; ini classic shakeout sebelum breakout naik. Dengan MA200 aman di bawah, ini adalah zona entry yang ideal jika RSM dan SRI mendukung. Risiko rendah, reward tinggi jika breakout terjadi.",
    ("ABSORB",   "Cluster on Macro Uptrend"): "Akumulasi Diam-diam dalam Konsolidasi — SM mengumpulkan posisi dengan sabar di tengah sideways yang ketat. Ini adalah fasa sebelum breakout; pasar belum notice tapi big players sudah positioning. Hold atau tambah posisi gradual; tunggu harga keluar dari cluster.",
    ("ACCUM",    "Cluster on Macro Uptrend"): "Fase Akumulasi Cluster — SM masuk perlahan dalam sideways yang didukung makro bullish. Tidak ada urgency breakout segera tapi probabilitas naik lebih tinggi dari turun mengingat MA200 di bawah. Entry gradual dengan sabar; jangan chase jika harga tiba-tiba spike.",
    ("UPTHRUST", "Cluster on Macro Uptrend"): "Fake Breakout di Atas Cluster — Harga sempat keluar cluster ke atas tapi BM dominan; ini false breakout klasik. Berbahaya karena banyak trader retail akan tergoda masuk saat harga tembus sideways. Hindari entry; tunggu retest dan konfirmasi SM sebelum percaya breakout ini.",
    ("DISTRI",   "Cluster on Macro Uptrend"): "Distribusi dalam Konsolidasi — BM aktif mendistribusi meski harga masih di atas MA200; ini warning bahwa cluster ini bukan akumulasi tapi distribusi terselubung. Jika berlanjut, harga berpotensi breakdown dari cluster ke arah bawah. Reduce position; jangan tambah di sini.",
    ("NEUTRAL",  "Cluster on Macro Uptrend"): "Sideways Murni — Tidak ada aksi dominan, harga bergerak datar dalam cluster di atas MA200. Ini adalah fase patience; pasar sedang menentukan arah. Pantau RSM dan SRI hari-hari berikutnya; breakout dari sini biasanya cukup signifikan.",

    # 6. CLUSTER ON MACRO DOWNTREND
    ("SOS",      "Cluster on Macro Downtrend"): "Rally Terbatas di Bawah MA200 — SM masuk agresif dalam sideways yang tertekan secara makro. Menarik sebagai bounce play jangka pendek tapi MA200 di atas sebagai resistance berat. Jangan ekspektasi trending move; target realistis adalah tepi atas cluster atau MA200 sebagai resistance.",
    ("SPRING",   "Cluster on Macro Downtrend"): "Shakeout Berbahaya — Harga turun lebih dalam dari cluster yang sudah di bawah MA200; SM mencoba akumulasi di zona yang sangat tertekan. Double-risk: makro bearish dan harga jatuh dari sideways. Hanya untuk trader dengan risk tolerance tinggi dengan ukuran posisi sangat kecil.",
    ("ABSORB",   "Cluster on Macro Downtrend"): "Akumulasi di Zona Berbahaya — SM diam-diam membeli di cluster yang berada di bawah MA200. Sinyal awal bottom fishing oleh big players, tapi masih terlalu dini. Pantau beberapa hari; jika RSM dan SRI terus naik, bisa jadi awal reversal jangka panjang.",
    ("ACCUM",    "Cluster on Macro Downtrend"): "Akumulasi Sabar di Bawah Makro Bearish — SM mulai masuk perlahan meski kondisi makro tidak mendukung. Ini bisa jadi akumulasi jangka panjang (months), bukan sinyal entry segera. Tidak direkomendasikan untuk swing trader; mungkin relevan untuk investor jangka panjang saja.",
    ("UPTHRUST", "Cluster on Macro Downtrend"): "Jebakan di Zona Merah — False breakout di atas cluster yang sudah tertekan makro; BM mendominasi dan MA200 jauh di atas sebagai ceiling. Salah satu setup paling berbahaya — buyer retail terjebak sementara BM distribusi aktif. SELL atau stay out.",
    ("DISTRI",   "Cluster on Macro Downtrend"): "Silent Exit — BM mendistribusi secara tenang dalam sideways yang sudah di bawah MA200; ini adalah tanda bahwa big players sedang keluar secara halus sebelum breakdown. Konfirmasi bearish paling kuat dalam konteks ini. Segera reduce atau exit posisi.",
    ("NEUTRAL",  "Cluster on Macro Downtrend"): "Dead Zone — Tidak ada aksi apapun dalam cluster yang sudah di bawah MA200. Ini bukan konsolidasi sehat; ini kekosongan minat. Likuiditas rendah, volatilitas rendah, tanpa katalis jelas. Stay away; banyak saham lain yang lebih layak diperhatikan.",

    # 7. BULLISH MESSY
    ("SOS",      "Bullish Messy"): "Momentum Kuat di Struktur Berantakan — SM sangat agresif tapi MA dalam kondisi chaotic. Sinyal SM valid dan menarik, tapi ketidakjelasan struktur MA menciptakan risiko false signal. Entry dengan sizing lebih kecil dari biasa; konfirmasi dengan apakah MA mulai realign dalam 2-3 hari ke depan.",
    ("SPRING",   "Bullish Messy"): "Akumulasi dalam Volatilitas Tinggi — SM masuk di penurunan tajam sementara MA sedang chaotic; tanda big players memanfaatkan ketidakpastian. Setup ini unpredictable tapi sering terjadi sebelum tren yang lebih jelas terbentuk. Entry kecil dengan konfirmasi ketat.",
    ("ABSORB",   "Bullish Messy"): "SM Tenang di Tengah Kekacauan MA — SM mengakumulasi dengan sabar meski struktur MA belum teratur. Ini menarik karena SM tidak terpengaruh oleh noise teknikal. Posisi makro aman (Price > MA200); tunggu MA mulai realign sebelum sizing up.",
    ("ACCUM",    "Bullish Messy"): "Akumulasi Gradual dalam Volatilitas — SM masuk perlahan di struktur MA yang belum teratur tapi makro masih bullish. Setup ini memerlukan patience ekstra; jangan ekspektasi immediate move. Tunggu MA mulai align sebelum sizing up lebih besar.",
    ("UPTHRUST", "Bullish Messy"): "Chaos Trap — Harga naik dengan BM dominan dalam struktur MA yang sudah berantakan; sinyal paling tidak reliable karena ketidakjelasan tren. Bisa jadi reversal awal atau hanya noise volatilitas. Default ke SELL; jangan coba menerka arah di kondisi messy + UPTHRUST.",
    ("DISTRI",   "Bullish Messy"): "Distribusi di Tengah Volatilitas — BM aktif mendistribusi dalam kondisi MA yang sudah chaotic; ini sinyal bahwa volatilitas ini dimanfaatkan big players untuk keluar. Meskipun Price > MA200, tekanan jual bisa cukup kuat untuk menarik harga ke bawah. Exit atau reduce.",
    ("NEUTRAL",  "Bullish Messy"): "Volatilitas Tanpa Arah — MA berantakan dan tidak ada aksi SM atau BM yang dominan; pasar sangat bingung. Dengan Price masih di atas MA200, belum ada alarm besar. Tapi hindari entry baru sampai MA mulai teratur dan ada sinyal phase yang jelas.",

    # 8. BEARISH MESSY
    ("SOS",      "Bearish Messy"): "Sinyal Kontroversial — SM agresif tapi MA chaotic dan Price di bawah MA200; konfluensi sangat buruk. Bisa jadi dead cat bounce atau awal reversal yang sangat dini. Risk sangat tinggi; jika entry, sizing minimal dan stop loss ketat di bawah low hari ini.",
    ("SPRING",   "Bearish Messy"): "Bottom Fishing Ekstrem — Harga jatuh dalam kondisi MA chaotic dan di bawah MA200; SM mencoba akumulasi di zona yang sangat tertekan. Setup paling high-risk dalam katalog ini. Hanya relevan jika SRI > 3.0 dan RSM > 68% sebagai konfirmasi minimum. Ukuran posisi sangat kecil.",
    ("ABSORB",   "Bearish Messy"): "Akumulasi Tersembunyi di Zona Bearish — SM diam-diam membeli di tengah kekacauan MA dan kondisi makro yang bearish. Sinyal yang contradictory dan tidak mudah dibaca. Pantau selama beberapa hari; jika konsisten, bisa jadi awal reversal besar. Belum waktunya entry.",
    ("ACCUM",    "Bearish Messy"): "Sinyal Sangat Prematur — SM mulai masuk tipis-tipis tapi semua kondisi teknikal bertentangan (MA messy, Price < MA200). Terlalu early untuk act; kemungkinan SM sedang testing water. Skip sampai ada konfirmasi lebih kuat; risiko jauh lebih besar dari potensi keuntungan saat ini.",
    ("UPTHRUST", "Bearish Messy"): "Maximum Danger — BM dominan, MA chaotic, Price di bawah MA200; ini adalah triple confirmation bearish. Tidak ada alasan apapun untuk beli. Jika masih punya posisi, ini adalah sinyal exit paling tegas. Prioritas pertama: capital preservation.",
    ("DISTRI",   "Bearish Messy"): "Distribusi Aktif dalam Kekacauan — BM mendistribusi agresif di tengah MA yang chaotic dan di bawah MA200; big players sedang keluar sekencang-kencangnya. Harga berpotensi turun drastis dalam waktu dekat. EXIT IMMEDIATELY jika masih punya posisi.",
    ("NEUTRAL",  "Bearish Messy"): "Limbo Bearish — Tidak ada aksi apapun dalam kondisi MA chaotic dan di bawah MA200. Pasar tidak tahu arah tapi semua indikator struktural bearish. Jangan masuk; ini bukan opportunity. Alihkan perhatian ke saham dengan struktur lebih jelas.",
}


# ── Gate Condition Overrides ──────────────────────────────────────────────────

_GATE_NARRATIVES = {
    "Gate A": "Abnormal Supply — Terdeteksi tekanan jual masif dari Bad Money (BM hari ini 3x+ rata-rata 10 hari), meskipun fase Smart Money menunjukkan akumulasi. Ada \"tembok penjual\" yang dapat mematikan momentum SM secara tiba-tiba. Tahan entry baru sampai supply abnormal ini mereda; risiko false signal sangat tinggi saat kondisi ini aktif.",
    "Gate B": "Extreme Panic / Risiko ARB — Terdeteksi fase SPRING namun penurunan harga melampaui 1.5× volatilitas normal (ATR), mendekati zona Auto Rejection Bawah. SM mungkin benar dalam akumulasi jangka panjang, tapi momentum turun masih sangat kuat hari ini. Tunggu konfirmasi bounce di hari berikutnya sebelum entry; \"tangkap pisau jatuh\" adalah risiko utama di kondisi ini.",
    "Gate C": "Profit Taking Zone — Signal BUY valid dari sisi fase SM, namun harga hari ini sudah naik melampaui batas toleransi volatilitas (≥2× ATR atau ≥5%). Entry di harga ini berarti beli di puncak harian; probabilitas pullback lebih tinggi dari probabilitas kelanjutan. Tunggu koreksi atau entry di hari berikutnya jika struktur masih intact.",
}


def get_phase_narrative(phase: str, ma_structure: str, gate: str = None) -> str:
    """Return Phase × MA Structure narrative, with optional Gate override."""
    if gate and gate in _GATE_NARRATIVES:
        return _GATE_NARRATIVES[gate]
    key = (phase, ma_structure)
    if key in _PHASE_NARRATIVE:
        return _PHASE_NARRATIVE[key]
    return "[NARASI TIDAK DITEMUKAN - HARAP LAMPIRKAN DATABASE TRADE DETAIL]"
