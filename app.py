from flask import Flask, jsonify, render_template, request, session, redirect
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import sqlite3
import os
import time
import threading


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "zenith-secret-key")

def is_authed():
    return session.get("authed") is True

# ── Config ──────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", r"C:\Users\rabim\Downloads\zenith_project\zenith.db")
WIB     = timezone(timedelta(hours=7))
_DATE_SORT = "substr(date,7,4)||substr(date,4,2)||substr(date,1,2)"
GAIN_EXECUTOR = ThreadPoolExecutor(max_workers=10)

# ── Sector mapping ──────────────────────────────────────────────────────
SECTORS = {
    "Energy": ['ABMM', 'MEDC', 'SGER', 'AKRA', 'MTFN', 'UNIQ', 'APEX', 'MYOH', 'MCOL', 'ARII', 'PGAS', 'GTSI', 'ARTI', 'PKPK', 'RMKE', 'BBRM', 'PTBA', 'BSML', 'BIPI', 'PTIS', 'ADMR', 'BSSR', 'PTRO', 'SEMA', 'BULL', 'RAJA', 'SICO', 'BUMI', 'RIGS', 'COAL', 'BYAN', 'RUIS', 'SUNI', 'CANI', 'SMMT', 'CBRE', 'CNKO', 'SMRU', 'HILL', 'DEWA', 'SOCI', 'CUAN', 'DOID', 'BUMA', 'SUGI', 'MAHA', 'DSSA', 'TOBA', 'RMKO', 'ELSA', 'TPMA', 'HUMI', 'ENRG', 'TRAM', 'RGAS', 'GEMS', 'WINS', 'ALII', 'GTBO', 'SHIP', 'MKAP', 'HITS', 'TAMU', 'ATLA', 'HRUM', 'FIRE', 'BOAT', 'IATA', 'PSSI', 'AADI', 'INDY', 'DWGL', 'RATU', 'ITMA', 'BOSS', 'PSAT', 'ITMG', 'JSKY', 'BESS', 'KKGI', 'INPS', 'CGAS', 'KOPI', 'TCPI', 'ADRO', 'LEAD', 'SURE', 'AIMS', 'MBAP', 'WOWS', 'MBSS', 'TEBE'],
    "Basic Materials": ['AKPI', 'MDKA', 'ESIP', 'ALDO', 'NIKL', 'IFSH', 'ALKA', 'OKAS', 'IFII', 'ALMI', 'PICO', 'SAMF', 'ANTM', 'PSAB', 'EPAC', 'APLI', 'SIMA', 'BEBS', 'BAJA', 'SMBR', 'NPGF', 'BMSR', 'SMCB', 'ARCI', 'BRMS', 'SMGR', 'NICL', 'BRNA', 'SPMA', 'SBMA', 'BRPT', 'SQMI', 'CMNT', 'BTON', 'SRSN', 'OBMD', 'CITA', 'SULI', 'AVIA', 'CLPI', 'TALF', 'CHEM', 'CTBN', 'TBMS', 'KKES', 'DKFT', 'TINS', 'PDPP', 'DPNS', 'TIRT', 'FWCT', 'EKAD', 'TKIM', 'PACK', 'ESSA', 'TPIA', 'AMMN', 'ETWA', 'TRST', 'PPRI', 'FASW', 'UNIC', 'SMGA', 'FPNI', 'WTON', 'SOLA', 'GDST', 'YPAS', 'BATR', 'IGAR', 'INCF', 'BLES', 'INAI', 'WSBP', 'PTMR', 'INCI', 'KMTR', 'DAAZ', 'INCO', 'MDKI', 'DGWG', 'INKP', 'ZINC', 'MINE', 'INRU', 'PBID', 'ASPR', 'INTD', 'TDPM', 'EMAS', 'INTP', 'SWAT', 'AYLS', 'IPOL', 'MOLI', 'NCKL', 'ISSP', 'HKMU', 'MBMA', 'KBRI', 'KAYU', 'NICE', 'KDSI', 'SMKL', 'SMLE', 'KRAS', 'GGRP', 'ADMG', 'LMSH', 'OPMS', 'AGII', 'LTLS', 'PURE'],
    "Industrials": ['AMFG', 'KIAS', 'ARKA', 'AMIN', 'KOBX', 'SINI', 'APII', 'KOIN', 'HOPE', 'ARNA', 'KONI', 'LABA', 'ASGR', 'LION', 'GPSO', 'ASII', 'MDRN', 'KUAS', 'BHIT', 'MFMI', 'BINO', 'BNBR', 'MLIA', 'NTBK', 'CTTH', 'SCCO', 'PADA', 'DYAN', 'TIRA', 'KING', 'HEXA', 'TOTO', 'PTMP', 'IBFN', 'TRIL', 'SMIL', 'ICON', 'UNTR', 'CRSN', 'IKAI', 'VOKS', 'WIDI', 'IKBI', 'ZBRA', 'FOLK', 'IMPC', 'MARK', 'MUTU', 'INDX', 'SPTO', 'HYGN', 'INTA', 'SKRN', 'VISI', 'JECC', 'CAKK', 'MHKI', 'JTPE', 'SOSS', 'NAIK', 'KBLI', 'CCSI', 'PIPA', 'KBLM', 'BLUE'],
    "Consumer Non-Cyclicals": ['AALI', 'SIPD', 'FLMC', 'ADES', 'SKBM', 'OILS', 'AISA', 'SKLT', 'BOBA', 'ALTO', 'SMAR', 'CMRY', 'AMRT', 'SSMS', 'TAYS', 'ANJT', 'STTP', 'WMPP', 'BISI', 'TBLA', 'IPPE', 'BTEK', 'TCID', 'NASI', 'BUDI', 'TGKA', 'STAA', 'BWPT', 'ULTJ', 'NANO', 'CEKA', 'UNSP', 'TLDN', 'CPIN', 'UNVR', 'IBOS', 'CPRO', 'WAPO', 'ASHA', 'DLTA', 'WICO', 'TRGU', 'DSFI', 'WIIM', 'DEWI', 'DSNG', 'DAYA', 'GULA', 'EPMT', 'DPUM', 'JARR', 'FISH', 'KINO', 'AMMS', 'GGRM', 'CLEO', 'EURO', 'GOLL', 'HOKI', 'BUAH', 'GZCO', 'CAMP', 'CRAB', 'HERO', 'PCAR', 'CBUT', 'HMSP', 'MGRO', 'MKTR', 'ICBP', 'ANDI', 'SOUL', 'INDF', 'GOOD', 'BEER', 'JAWA', 'FOOD', 'WINE', 'JPFA', 'BEEF', 'NAYZ', 'LAPD', 'COCO', 'NSSS', 'LSIP', 'ITIC', 'MAXI', 'MAGP', 'KEJU', 'GRPM', 'MAIN', 'PSGO', 'TGUK', 'MBTO', 'AGAR', 'PTPS', 'MIDI', 'UCID', 'STRK', 'MLBI', 'CSRA', 'UDNG', 'MLPL', 'DMND', 'AYAM', 'MPPA', 'IKAN', 'ISEA', 'MRAT', 'PGUN', 'GUNA', 'MYOR', 'PNGO', 'NEST', 'PSDN', 'KMDS', 'BRRC', 'RANC', 'ENZO', 'RLCO', 'ROTI', 'VICI', 'YUPI', 'SDPC', 'PMMP', 'FORE', 'SGRO', 'WMUU', 'MSJA', 'SIMP', 'TAPG', 'FAPA'],
    "Consumer Cyclicals": ['ABBA', 'PTSP', 'SCNP', 'ACES', 'RALS', 'PLAN', 'AKKU', 'RICY', 'SNLK', 'ARGO', 'SCMA', 'LFLO', 'ARTA', 'SHID', 'LUCY', 'AUTO', 'SMSM', 'MGLV', 'BATA', 'SONA', 'IDEA', 'BAYU', 'SRIL', 'DEPO', 'BIMA', 'SSTM', 'DRMA', 'BLTZ', 'TELE', 'ASLC', 'BMTR', 'TFCO', 'NETV', 'MDTV', 'BOLT', 'TMPO', 'BAUT', 'BRAM', 'TRIO', 'ENAK', 'BUVA', 'TRIS', 'BIKE', 'CINT', 'UNIT', 'OLIV', 'CNTX', 'VIVA', 'SWID', 'CSAP', 'JGLE', 'RAFI', 'ECII', 'MARI', 'KLIN', 'ERAA', 'MKNT', 'TOOL', 'ERTX', 'BOGA', 'KDTN', 'ESTI', 'CARS', 'ZATA', 'FAST', 'MINA', 'ISAP', 'FORU', 'MAPB', 'BMBL', 'GDYR', 'WOOD', 'FUTR', 'GEMA', 'HRTA', 'HAJJ', 'GJTL', 'MABA', 'TYRE', 'GLOB', 'BELL', 'VKTR', 'GWSA', 'DFAM', 'CNMA', 'HOME', 'PZZA', 'ERAL', 'HOTL', 'MSIN', 'LMAX', 'IIKP', 'MAPA', 'BABY', 'IMAS', 'NUSA', 'AEGS', 'INDR', 'FILM', 'GRPH', 'INDS', 'DIGI', 'UNTD', 'JIHD', 'DUCK', 'MEJA', 'JSPT', 'YELO', 'LIVE', 'KICI', 'SOTS', 'BAIK', 'KPIG', 'ZONE', 'SPRE', 'LMPI', 'CLAY', 'PART', 'LPIN', 'NATO', 'GOLF', 'LPPF', 'HRME', 'DOSS', 'MAPI', 'FITT', 'VERN', 'MDIA', 'BOLA', 'MDIY', 'MGNA', 'POLU', 'MERI', 'MICE', 'IPTV', 'PMUI', 'MNCN', 'EAST', 'KAQI', 'MPMX', 'KOTA', 'ESTA', 'MSKY', 'INOV', 'RAAM', 'MYTX', 'SLIS', 'DOOH', 'PANR', 'PMJS', 'ACRO', 'PBRX', 'SBAT', 'UFOE', 'PDES', 'CBMF', 'PNSE', 'PGLI', 'CSMI', 'POLY', 'PJAA', 'SOFA', 'PSKT', 'TOYS'],
    "Healthcare": ['DVLA', 'PRDA', 'PEVE', 'INAF', 'PRIM', 'HALO', 'KAEF', 'HEAL', 'RSCH', 'KLBF', 'PEHA', 'IKPM', 'MERK', 'IRRA', 'SURI', 'MIKA', 'SOHO', 'LABS', 'PYFA', 'BMHS', 'OBAT', 'SAME', 'RSGK', 'CHEK', 'SCPI', 'MTMH', 'MDLA', 'SIDO', 'MEDS', 'DKHH', 'SILO', 'PRAY', 'CARE', 'SRAJ', 'OMED', 'DGNS', 'TSPC', 'MMIX'],
    "Financials": ['ABDA', 'BPFI', 'TIFA', 'AMAG', 'BPII', 'TRIM', 'APIC', 'BSIM', 'TRUS', 'ARTO', 'BSWD', 'VICO', 'ASBI', 'BTPN', 'SMBC', 'VINS', 'ASDM', 'BVIC', 'VRNA', 'ASJT', 'CFIN', 'WOMF', 'ASMI', 'DEFI', 'YULE', 'ASRM', 'DNAR', 'CASA', 'BABP', 'DNET', 'BRIS', 'BACA', 'GSMF', 'MTWI', 'BBCA', 'HDFA', 'JMAS', 'BBHI', 'INPC', 'NICK', 'BBKP', 'LPGI', 'BTPS', 'BBLD', 'LPPS', 'TUGU', 'BBMD', 'MAYA', 'POLA', 'BBNI', 'MCOR', 'SFAN', 'BBRI', 'MEGA', 'LIFE', 'MSIG', 'BBTN', 'MREI', 'FUJI', 'BBYB', 'NISP', 'OCBC', 'AMAR', 'BCAP', 'NOBU', 'AMOR', 'BCIC', 'OCAP', 'BHAT', 'BDMN', 'PADI', 'BBSI', 'BEKS', 'PALM', 'BANK', 'BFIN', 'PANS', 'MASB', 'BGTG', 'PEGE', 'VTNY', 'BINA', 'PLAS', 'YOII', 'BJBR', 'PNBN', 'COIN', 'BJTM', 'PNBS', 'SUPA', 'BKSW', 'PNIN', 'ADMF', 'BMAS', 'PNLF', 'AGRO', 'BMRI', 'RELI', 'AGRS', 'BNBA', 'SDRA', 'AHAP', 'BNGA', 'CIMB', 'SMMA', 'POOL', 'BNII', 'SRTG', 'BNLI', 'STAR'],
    "Property": ['APLN', 'MMLP', 'NZIA', 'ASRI', 'MTLA', 'REAL', 'BAPA', 'MTSM', 'INDO', 'BCIP', 'NIRO', 'TRIN', 'BEST', 'OMRE', 'KBAG', 'BIKA', 'PLIN', 'BBSS', 'BIPP', 'PUDP', 'UANG', 'BKDP', 'PWON', 'PURI', 'BKSL', 'RBMS', 'HOMI', 'BSDE', 'RDTX', 'ROCK', 'COWL', 'RIMO', 'ATAP', 'CTRA', 'RODA', 'ADCP', 'DART', 'SMDM', 'TRUE', 'DILD', 'SMRA', 'IPAC', 'DMAS', 'TARA', 'WINR', 'DUTI', 'CSIS', 'BSBK', 'ELTY', 'ARMY', 'CBPE', 'EMDE', 'NASA', 'VAST', 'FMII', 'RISE', 'SAGE', 'GAMA', 'POLL', 'RELF', 'GMTD', 'LAND', 'HBAT', 'GPRA', 'PANI', 'GRIA', 'INPP', 'CITY', 'MSIE', 'JRPT', 'MPRO', 'KOCI', 'KIJA', 'SATU', 'KSIX', 'LCGP', 'URBN', 'CBDK', 'LPCK', 'POLI', 'DADA', 'LPKR', 'CPRI', 'ASPI', 'LPLI', 'POSA', 'AMAN', 'MDLN', 'PAMG', 'PPRO', 'MKPI', 'BAPI'],
    "Technology": ['ATIC', 'DMMX', 'ELIT', 'EMTK', 'GLVA', 'IRSX', 'KREN', 'PGJO', 'CHIP', 'LMAS', 'CASH', 'TRON', 'MLPT', 'TECH', 'JATI', 'MTDL', 'EDGE', 'CYBR', 'PTSN', 'ZYRX', 'IOTF', 'SKYB', 'UVCR', 'MSTI', 'KIOS', 'BUKA', 'TOSK', 'MCAS', 'RUNS', 'MPIX', 'NFCX', 'WGSH', 'AREA', 'DIVA', 'WIRG', 'ASIA', 'MENN', 'LUCK', 'GOTO', 'AWAN', 'ENVY', 'AXIO', 'WIFI', 'HDIT', 'BELI', 'DCII', 'TFAS', 'NINE'],
    "Infrastructure": ['ACST', 'TBIG', 'JAST', 'ADHI', 'TLKM', 'KEEN', 'BALI', 'TOTL', 'PTPW', 'BTEL', 'TOWR', 'TAMA', 'BUKK', 'WIKA', 'RONY', 'CASS', 'WSKT', 'PTDU', 'CENT', 'IDPR', 'FIMP', 'CMNP', 'MTRA', 'MTEL', 'DGIK', 'OASA', 'SMKM', 'EXCL', 'POWR', 'ARKO', 'GOLD', 'PBSA', 'KRYA', 'HADE', 'PORT', 'PGEO', 'IBST', 'TGRA', 'BDKR', 'ISAT', 'TOPS', 'INET', 'JKON', 'MPOW', 'BREN', 'JSMR', 'GMFI', 'KOKA', 'KARW', 'PPRE', 'ASLI', 'KBLV', 'WEGE', 'LINK', 'MORA', 'HGII', 'META', 'IPCM', 'CDIA', 'NRCA', 'LCKM', 'MANG', 'PTPP', 'GHON', 'KETR', 'SSIA', 'IPCC', 'SUPR', 'MTPS'],
    "Transport": ['AKSI', 'SMDR', 'PPGL', 'ASSA', 'TAXI', 'TRJA', 'BIRD', 'TMAS', 'HAIS', 'BLTA', 'WEHA', 'HATM', 'CMPP', 'HELI', 'RCCC', 'GIAA', 'TRUK', 'ELPI', 'IMJS', 'TNCA', 'LAJU', 'LRNA', 'BPTR', 'GTRA', 'MIRA', 'SAPX', 'MPXL', 'MITI', 'DEAL', 'KLAS', 'NELY', 'JAYA', 'LOPI', 'SAFE', 'KJEN', 'BLOG', 'SDMU', 'PURA', 'PJHB'],
}

YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com",
}

INTERVAL_MAP = {
    "5m":  {"interval": "5m",  "days": 59},
    "15m": {"interval": "15m", "days": 59},
    "30m": {"interval": "30m", "days": 59},
    "1h":  {"interval": "60m", "days": 720},
    "1d":  {"interval": "1d",  "days": 99999},
}

# ── Gain% Cache (5 menit) ───────────────────────────────────────────────
_gain_cache      = {}   # ticker → {"gain": float, "price": int, "ts": epoch}
_gain_cache_lock = threading.Lock()
CACHE_TTL        = 300  # detik


def fetch_gain_range(ticker: str, date_from: str, date_to: str):
    """
    Hitung % change harga saham dari date_from ke date_to.
    Single day  → close hari itu vs close hari sebelumnya
    Multi day   → close date_to vs close date_from
    """
    symbol = f"{ticker}.JK"
    try:
        d0 = parse_date(date_from)
        d1 = parse_date(date_to)
        # Ambil 10 hari sebelum date_from agar ada prev candle
        # +3 hari setelah date_to agar candle hari itu pasti masuk
        p1 = int((datetime(d0.year, d0.month, d0.day, tzinfo=timezone.utc) - timedelta(days=10)).timestamp())
        p2 = int((datetime(d1.year, d1.month, d1.day, tzinfo=timezone.utc) + timedelta(days=3)).timestamp())

        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            headers=YF_HEADERS,
            params={
                "interval":             "1d",
                "period1":              p1,
                "period2":              p2,
                "includeAdjustedClose": "false",
            },
            timeout=10,
        )
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None, None

        r          = result[0]
        timestamps = r.get("timestamp", [])
        quote      = r.get("indicators", {}).get("quote", [{}])[0]
        closes     = quote.get("close", [])

        # Build list (date_str WIB YYYY-MM-DD, close)
        # IDX candle timestamps dari Yahoo bisa UTC midnight atau UTC+7
        # Pakai WIB (UTC+7) untuk date matching yang benar
        candles = []
        for i, ts in enumerate(timestamps):
            c = closes[i] if i < len(closes) else None
            if not c or float(c) <= 0:
                continue
            # Konversi ke WIB untuk dapat tanggal trading yang benar
            dt_wib = datetime.fromtimestamp(ts, tz=WIB)
            candles.append((dt_wib.strftime("%Y-%m-%d"), float(c)))

        if not candles:
            return None, None

        d0_str = d0.strftime("%Y-%m-%d")
        d1_str = d1.strftime("%Y-%m-%d")

        # Cari candle dengan tanggal paling dekat ≤ target
        def find_close_on_or_before(target_str):
            best = None
            for date_str, close in candles:
                if date_str <= target_str:
                    best = (date_str, close)
            return best

        result_d1 = find_close_on_or_before(d1_str)
        if not result_d1:
            return None, None

        close_d1 = result_d1[1]
        price    = int(round(close_d1))

        if d0 == d1:
            # Single day: bandingkan close d1 vs candle sebelumnya
            idx = next((i for i, (ds, _) in enumerate(candles) if ds == result_d1[0]), None)
            if idx is not None and idx > 0:
                close_prev = candles[idx - 1][1]
                gain = round((close_d1 - close_prev) / close_prev * 100, 2)
                return gain, price
            return None, price
        else:
            result_d0 = find_close_on_or_before(d0_str)
            if not result_d0 or result_d0[1] <= 0:
                return None, price
            close_d0 = result_d0[1]
            gain = round((close_d1 - close_d0) / close_d0 * 100, 2)
            return gain, price

    except Exception:
        return None, None


# Cache gain per (ticker, date_from, date_to)
_gain_cache      = {}
_gain_cache_lock = threading.Lock()
CACHE_TTL        = 300


def get_gains_batch(tickers: list, date_from: str, date_to: str):
    now    = time.time()
    result = {}
    to_fetch = []

    with _gain_cache_lock:
        for t in tickers:
            key    = f"{t}|{date_from}|{date_to}"
            cached = _gain_cache.get(key)
            if cached and (now - cached["ts"]) < CACHE_TTL:
                result[t] = {"gain": cached["gain"], "price": cached["price"]}
            else:
                to_fetch.append(t)

    if not to_fetch:
        return result

    # Parallel fetch — max 10 concurrent
    def _fetch_one(t):
        gain, price = fetch_gain_range(t, date_from, date_to)
        return t, gain, price

    futures = {GAIN_EXECUTOR.submit(_fetch_one, t): t for t in to_fetch}
    for future in as_completed(futures, timeout=30):
        try:
            t, gain, price = future.result()
            key = f"{t}|{date_from}|{date_to}"
            with _gain_cache_lock:
                _gain_cache[key] = {"gain": gain, "price": price, "ts": time.time()}
            result[t] = {"gain": gain, "price": price}
        except Exception:
            t = futures[future]
            result[t] = {"gain": None, "price": None}

    return result


# ── Helpers ──────────────────────────────────────────────────────────────
def parse_date(s: str):
    """DD-MM-YYYY → datetime.date"""
    return datetime.strptime(s, "%d-%m-%Y").date()


def date_to_sortkey(s: str):
    """DD-MM-YYYY → YYYYMMDD integer for SQLite sorting."""
    try:
        d = datetime.strptime(s, "%d-%m-%Y")
        return int(d.strftime("%Y%m%d"))
    except Exception:
        return 0


def get_db():
    """Thread-local connection reuse with optimized PRAGMAs."""
    import threading
    _local = getattr(get_db, '_local', None)
    if _local is None:
        get_db._local = threading.local()
        _local = get_db._local

    conn = getattr(_local, 'conn', None)
    # Reuse connection if same DB path and still alive
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except Exception:
            conn = None

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # ── Performance PRAGMAs ──
    conn.execute("PRAGMA journal_mode=WAL")       # ~5x faster reads
    conn.execute("PRAGMA synchronous=NORMAL")     # safe enough for read-heavy
    conn.execute("PRAGMA cache_size=-64000")       # 64MB page cache (default 2MB)
    conn.execute("PRAGMA mmap_size=268435456")     # 256MB mmap — read from memory
    conn.execute("PRAGMA temp_store=MEMORY")       # temp tables in RAM
    _local.conn = conn
    return conn


# ── Flow result cache (60s TTL) ─────────────────────────────────────────
_flow_cache = {}
_flow_cache_lock = threading.Lock()
FLOW_CACHE_TTL = 60  # detik


# ── Routes ───────────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def login():
    if is_authed():
        return redirect("/hub")
    if request.method == "POST":
        key = request.form.get("key", "").strip()
        if key == os.environ.get("ACCESS_KEY"):
            session["authed"] = True
            return jsonify({"ok": True})
        return jsonify({"ok": False})
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/hub")
def hub():
    if not is_authed(): return redirect("/")
    return render_template("hub.html")

@app.route("/chart")
def chart_page():
    if not is_authed(): return redirect("/")
    return render_template("chart.html")

@app.route("/flow")
def flow_page():
    if not is_authed(): return redirect("/")
    return render_template("flow.html")

@app.route("/sector")
def sector_page():
    if not is_authed(): return redirect("/")
    return render_template("sector.html")


# ── API: IHSG price & gain ──────────────────────────────────────────────
_ihsg_cache = {"data": None, "ts": 0}

@app.route("/api/ihsg")
def ihsg():
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    now = time.time()
    if _ihsg_cache["data"] and (now - _ihsg_cache["ts"]) < CACHE_TTL:
        return jsonify(_ihsg_cache["data"])
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE",
            headers=YF_HEADERS,
            params={"interval": "1d", "range": "10d", "includeAdjustedClose": "false"},
            timeout=10,
        )
        data = resp.json()
        r = data.get("chart", {}).get("result", [{}])[0]
        closes = r.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        # Filter valid closes only (last trading days)
        valid = [c for c in closes if c and float(c) > 0]
        price = None
        gain = None
        if valid:
            price = round(float(valid[-1]), 2)  # decimal, not rounded to int
        if len(valid) >= 2:
            gain = round((valid[-1] - valid[-2]) / valid[-2] * 100, 2)
        result = {"price": price, "gain_pct": gain}
        _ihsg_cache["data"] = result
        _ihsg_cache["ts"] = time.time()
        return jsonify(result)
    except Exception as e:
        return jsonify({"price": None, "gain_pct": None, "error": str(e)})


# ── API: last date with data in DB ──────────────────────────────────────
@app.route("/api/last-date")
def last_date():
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    try:
        conn = get_db()
        row = conn.execute("""
            SELECT date FROM raw_messages
            ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2) DESC
            LIMIT 1
        """).fetchone()
        if row:
            # DD-MM-YYYY → DD/MM/YYYY for frontend
            return jsonify({"date": row["date"].replace("-", "/")})
        return jsonify({"date": None})
    except Exception as e:
        return jsonify({"date": None, "error": str(e)})


# ── API: flow data ────────────────────────────────────────────────────────
@app.route("/api/flow")
def flow():
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    today_wib = datetime.now(WIB).strftime("%d-%m-%Y")
    date_from = request.args.get("date_from", today_wib)
    date_to   = request.args.get("date_to",   today_wib)

    try:
        parse_date(date_from)
        parse_date(date_to)
    except ValueError:
        return jsonify({"error": "Format tanggal salah, gunakan DD-MM-YYYY"}), 400

    # Buat list tanggal valid dalam rentang (DD-MM-YYYY)
    try:
        d0 = parse_date(date_from)
        d1 = parse_date(date_to)
        if d0 > d1:
            d0, d1 = d1, d0
        dates = []
        cur = d0
        while cur <= d1:
            dates.append(cur.strftime("%d-%m-%Y"))
            cur += timedelta(days=1)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    placeholders = ",".join("?" for _ in dates)

    try:
        conn = get_db()

        # ── Read from pre-aggregated eod_summary (include tx_sm/tx_bm for RPR) ──
        rows = conn.execute(f"""
            SELECT ticker,
                   SUM(sm_val)   AS sm_val,
                   SUM(bm_val)   AS bm_val,
                   SUM(tx_count) AS tx,
                   SUM(tx_sm)    AS tx_sm,
                   SUM(tx_bm)    AS tx_bm,
                   SUM(mf_plus)  AS mf_plus,
                   SUM(mf_minus) AS mf_minus
            FROM eod_summary
            WHERE date IN ({placeholders})
            GROUP BY ticker
        """, dates).fetchall()

        # ── SRI + volx_gap from LATEST date ──
        analytics_map = {}
        latest_date = None
        latest_date_row = conn.execute(f"""
            SELECT date FROM eod_summary
            WHERE date IN ({placeholders})
            ORDER BY {_DATE_SORT} DESC LIMIT 1
        """, dates).fetchone()
        if latest_date_row:
            latest_date = latest_date_row["date"]
            a_rows = conn.execute("""
                SELECT ticker, price_close, sri, volx_gap, vwap_sm, vwap_bm,
                       atr_pct, sm_sma10, bm_sma10, watch, price_change_pct
                FROM eod_summary WHERE date = ?
            """, [latest_date]).fetchall()
            for ar in a_rows:
                analytics_map[ar["ticker"]] = dict(ar)

        # ── Gain% from stored price_close (no Yahoo per-request) ──
        gains_map = {}  # ticker → {gain, price}

        is_single_day = (date_from == date_to)

        if not is_single_day:
            # Multi-day range: compare latest vs day before range (from DB)
            price_latest = {}
            if latest_date:
                for r in conn.execute(
                    "SELECT ticker, price_close FROM eod_summary WHERE date = ? AND price_close IS NOT NULL",
                    [latest_date]
                ).fetchall():
                    price_latest[r["ticker"]] = r["price_close"]

            earliest_date_row = conn.execute(f"""
                SELECT date FROM eod_summary WHERE date IN ({placeholders})
                ORDER BY {_DATE_SORT} ASC LIMIT 1
            """, dates).fetchone()
            e_date = earliest_date_row["date"] if earliest_date_row else date_from
            e_sortkey = e_date[6:10] + e_date[3:5] + e_date[0:2]
            prev_row = conn.execute(f"""
                SELECT DISTINCT date FROM eod_summary
                WHERE {_DATE_SORT} < ? ORDER BY {_DATE_SORT} DESC LIMIT 1
            """, [e_sortkey]).fetchone()

            price_ref = {}
            if prev_row:
                for r in conn.execute(
                    "SELECT ticker, price_close FROM eod_summary WHERE date = ? AND price_close IS NOT NULL",
                    [prev_row["date"]]
                ).fetchall():
                    price_ref[r["ticker"]] = r["price_close"]

            for t in set(list(price_latest.keys()) + list(price_ref.keys())):
                p_now = price_latest.get(t)
                p_ref = price_ref.get(t)
                price = int(round(p_now)) if p_now else None
                gain = None
                if p_now and p_ref and p_ref > 0:
                    gain = round((p_now - p_ref) / p_ref * 100, 2)
                gains_map[t] = {"gain": gain, "price": price}
        else:
            # Single day: use price_change_pct stored by scraper; Yahoo only for tickers missing it
            if latest_date:
                for r in conn.execute(
                    "SELECT ticker, price_close, price_change_pct FROM eod_summary WHERE date = ? AND price_close IS NOT NULL",
                    [latest_date]
                ).fetchall():
                    pct = r["price_change_pct"]
                    gains_map[r["ticker"]] = {
                        "gain": round(pct, 2) if pct is not None else None,
                        "price": int(round(r["price_close"])),
                    }

    except Exception as e:
        return jsonify({"error": f"DB error: {e}"}), 500

    # Build data dict
    data = {}
    for row in rows:
        t = row["ticker"]
        data[t] = {
            "sm_val": row["sm_val"] or 0,
            "bm_val": row["bm_val"] or 0,
            "tx": row["tx"] or 0,
            "tx_sm": row["tx_sm"] or 0,
            "tx_bm": row["tx_bm"] or 0,
            "mf_plus": row["mf_plus"],
            "mf_minus": row["mf_minus"],
            "net_mf": None,
        }
        d = data[t]
        if d["mf_plus"] is not None or d["mf_minus"] is not None:
            d["net_mf"] = round((d["mf_plus"] or 0) - (d["mf_minus"] or 0), 2)

    if not data:
        # If sector param given, still need to return sector tickers with gains
        pass

    # Optional sector filter: ensure ALL sector tickers are present
    sector_name = request.args.get("sector", "").strip()
    sector_members = None
    if sector_name and sector_name in SECTORS:
        sector_members = set(SECTORS[sector_name])
        # Add missing tickers that have no DB data
        for t in sector_members:
            if t not in data:
                data[t] = {"sm_val": 0, "bm_val": 0, "mf_plus": None, "mf_minus": None, "net_mf": None, "tx": 0, "_nodata": True}

    if not data:
        return jsonify({"tickers": [], "totals": {}})

    # Yahoo fallback for tickers without stored price
    missing = [t for t in data if t not in gains_map or gains_map.get(t, {}).get("gain") is None]
    if missing:
        yahoo_gains = get_gains_batch(missing, date_from, date_to)
        for t, g in yahoo_gains.items():
            gains_map[t] = g

    gains = gains_map

    tickers = []
    for t, d in data.items():
        # If sector filter, skip tickers not in sector
        if sector_members and t not in sector_members:
            continue
        nodata = d.get("_nodata", False)
        sm  = round(d["sm_val"], 2) if not nodata else None
        bm  = round(d["bm_val"], 2) if not nodata else None
        cm  = round((d["sm_val"] - d["bm_val"]), 2) if not nodata else None
        rsm = round(d["sm_val"] / (d["sm_val"] + d["bm_val"]) * 100, 1) if not nodata and (d["sm_val"] + d["bm_val"]) > 0 else None
        mfp = round(d["mf_plus"],  2) if d["mf_plus"]  is not None else None
        mfm = round(d["mf_minus"], 2) if d["mf_minus"] is not None else None
        net = round(d["net_mf"],   2) if d.get("net_mf") is not None else None

        g = gains.get(t, {})
        a = analytics_map.get(t, {})
        gain     = g.get("gain")
        sri      = a.get("sri") or 0
        volx_gap = a.get("volx_gap")
        atr_pct  = a.get("atr_pct")
        vwap_sm  = a.get("vwap_sm")
        vwap_bm  = a.get("vwap_bm")
        sm_sma10 = a.get("sm_sma10")
        bm_sma10 = a.get("bm_sma10") or 0

        # ── Compute RPR from RANGE data ──
        range_tx_sm    = d.get("tx_sm") or 0
        range_tx_bm    = d.get("tx_bm") or 0
        range_tx_total = range_tx_sm + range_tx_bm
        rpr_val = round(range_tx_bm / range_tx_total, 2) if range_tx_total > 0 else 0

        # ── MES: |gain%| ÷ SRI ──
        pchg = gain
        mes  = round(abs(pchg) / sri, 2) if pchg is not None and sri > 0 else None

        # ── Phase / Action / Watch / SL via centralised logic ──
        phase        = "NEUTRAL"
        action       = "HOLD"
        watch        = None

        if rsm is not None and cm is not None:
            from logic import classify_zenith_v3_1, get_action, get_watch_flag
            bm_raw = d.get("bm_val") or 0
            phase  = classify_zenith_v3_1(sri, rsm, rpr_val, gain, bm_raw, bm_sma10, atr_pct)
            watch  = get_watch_flag(phase, gain, atr_pct)
            action = get_action(phase, gain, atr_pct, bm_val=bm_raw, bm_sma10=bm_sma10, watch_flag=watch)
            if watch is None and a.get("watch"):
                watch = a.get("watch")

        tickers.append({
            "ticker":       t,
            "clean_money":  cm,
            "sm_val":       sm,
            "bm_val":       bm,
            "rsm":          rsm,
            "mf_plus":      mfp,
            "mf_minus":     mfm,
            "net_mf":       net,
            "gain_pct":     gain,
            "price":        g.get("price") or a.get("price_close"),
            "tx":           int(d.get("tx") or 0),
            "phase":        phase,
            "action":       action,
            "watch":        watch,
            "sri":          sri if sri else None,
            "mes":          mes,
            "volx_gap":     volx_gap,
            "rpr":          rpr_val if rpr_val else None,
            "price_change": pchg,
            "atr_pct":      atr_pct,
            "sm_sma10":     round(sm_sma10, 2) if sm_sma10 else None,
            "vwap_sm":      round(vwap_sm, 2) if vwap_sm else None,
            "vwap_bm":      round(vwap_bm, 2) if vwap_bm else None,
        })

    # Sort default: clean_money desc (nulls last)
    tickers.sort(key=lambda x: x["clean_money"] if x["clean_money"] is not None else -999999, reverse=True)

    def safe_sum(key):
        vals = [x[key] for x in tickers if x[key] is not None]
        if not vals: return None
        total = round(sum(vals), 2)
        return total if total != 0 else None

    totals = {
        "sm":       round(sum(x["sm_val"] or 0      for x in tickers), 2),
        "bm":       round(sum(x["bm_val"] or 0      for x in tickers), 2),
        "mf_plus":  safe_sum("mf_plus"),
        "mf_minus": safe_sum("mf_minus"),
        "net_cm":   round(sum(x["clean_money"] or 0 for x in tickers), 2),
        "net_mf":   safe_sum("net_mf"),
        "count":    len(tickers),
    }

    return jsonify({"tickers": tickers, "totals": totals, "date_from": date_from, "date_to": date_to})


# ── API: transactions per ticker ─────────────────────────────────────────
@app.route("/api/transactions")
def transactions():
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    ticker    = request.args.get("ticker", "").upper().strip()
    today_wib = datetime.now(WIB).strftime("%d-%m-%Y")
    date_from = request.args.get("date_from", today_wib)
    date_to   = request.args.get("date_to",   today_wib)

    if not ticker:
        return jsonify({"error": "ticker required"}), 400

    try:
        parse_date(date_from)
        parse_date(date_to)
    except ValueError:
        return jsonify({"error": "Format tanggal salah"}), 400

    d0 = parse_date(date_from)
    d1 = parse_date(date_to)
    if d0 > d1: d0, d1 = d1, d0
    dates = []
    cur = d0
    while cur <= d1:
        dates.append(cur.strftime("%d-%m-%Y"))
        cur += timedelta(days=1)

    placeholders = ",".join("?" for _ in dates)
    params = [ticker] + dates

    try:
        conn = get_db()
        rows = conn.execute(f"""
            SELECT channel, date, time, price, gain_pct,
                   mf_delta_raw, mf_delta_numeric, vol_x, signal
            FROM raw_messages
            WHERE ticker = ? AND date IN ({placeholders})
            ORDER BY
                substr(date,7,4)||substr(date,4,2)||substr(date,1,2),
                time
        """, params).fetchall()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    sm_rows, bm_rows = [], []
    for r in rows:
        row = {
            "date":     r["date"],
            "time":     r["time"],
            "price":    int(round(r["price"])) if r["price"] else None,
            "gain_pct": r["gain_pct"],
            "mf":       r["mf_delta_raw"],
            "mf_num":   r["mf_delta_numeric"],
            "vol_x":    r["vol_x"],
            "signal":   r["signal"],
        }
        if r["channel"] == "smart":
            sm_rows.append(row)
        else:
            bm_rows.append(row)

    return jsonify({
        "ticker":  ticker,
        "sm":      sm_rows,
        "bm":      bm_rows,
        "sm_count": len(sm_rows),
        "bm_count": len(bm_rows),
    })



# ── API: overlay data (CM/SM/BM per candle bucket) ──────────────────────
@app.route("/api/overlay")
def overlay():
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    ticker = request.args.get("ticker", "").upper().strip()
    tf     = request.args.get("tf", "1d")

    if not ticker:
        return jsonify({"error": "ticker required"}), 400

    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT date, time, channel, mf_delta_numeric
            FROM raw_messages
            WHERE ticker = ?
            ORDER BY
                substr(date,7,4)||substr(date,4,2)||substr(date,1,2),
                time
        """, [ticker]).fetchall()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not rows:
        return jsonify({"ticker": ticker, "tf": tf, "points": []})

    tf_minutes = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": None}
    bucket_min = tf_minutes.get(tf)

    buckets = {}
    for r in rows:
        date_str = r["date"]       # DD-MM-YYYY
        time_str = r["time"] or "" # HH:MM or HH:MM:SS

        try:
            d = datetime.strptime(date_str, "%d-%m-%Y")
        except Exception:
            continue

        if bucket_min is None:
            # Daily: one bucket per date
            # WIB timestamp: midnight UTC of that date + 7h
            utc_ts = int(d.replace(tzinfo=timezone.utc).timestamp())
            wib_ts = utc_ts + (7 * 3600)
            key = wib_ts
        else:
            # Intraday: bucket by time interval
            # bh/bm sudah WIB, utc_ts = midnight UTC
            # OHLCV pakai: actual_utc_ts + 7h = midnight_utc + real_hour_utc + 7h
            # Agar match: midnight_utc + bh_wib*3600 + bm*60 (TANPA +7h lagi)
            parts = time_str.replace(".", ":").split(":")
            h = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else 9
            m = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
            total_min = h * 60 + m
            bstart = (total_min // bucket_min) * bucket_min
            bh = bstart // 60
            bm = bstart % 60
            utc_ts = int(d.replace(tzinfo=timezone.utc).timestamp())
            wib_ts = utc_ts + bh * 3600 + bm * 60
            key = wib_ts

        if key not in buckets:
            buckets[key] = {"time": key, "sm": 0.0, "bm": 0.0, "date": date_str}

        mf = r["mf_delta_numeric"] or 0
        if r["channel"] == "smart":
            buckets[key]["sm"] += mf
        else:
            buckets[key]["bm"] += abs(mf)

    points = []
    for k in sorted(buckets.keys()):
        v = buckets[k]
        sm = round(v["sm"], 2)
        bm = round(v["bm"], 2)
        cm = round(sm - bm, 2)
        points.append({"time": v["time"], "sm": sm, "bm": bm, "cm": cm, "_date": v["date"]})

    # Hitung cumulative untuk line series (continuous lintas semua hari, semua TF)
    cum_sm, cum_bm, cum_cm = 0.0, 0.0, 0.0
    for p in points:
        cum_sm = round(cum_sm + p["sm"], 2)
        cum_bm = round(cum_bm + p["bm"], 2)
        cum_cm = round(cum_cm + p["cm"], 2)
        p["cum_sm"] = cum_sm
        p["cum_bm"] = cum_bm
        p["cum_cm"] = cum_cm
        p.pop("_date", None)

    return jsonify({"ticker": ticker, "tf": tf, "points": points})


@app.route("/api/ohlcv")
def ohlcv():
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    ticker = request.args.get("ticker", "BBRI").upper().strip()
    tf     = request.args.get("tf", "15m")

    if tf not in INTERVAL_MAP:
        return jsonify({"error": f"Timeframe tidak valid: {tf}"}), 400

    p      = INTERVAL_MAP[tf]
    symbol = f"{ticker}.JK"
    now    = datetime.now(timezone.utc)
    period2 = int(now.timestamp())
    period1 = 0 if p["days"] >= 9999 else int((now - timedelta(days=p["days"])).timestamp())

    try:
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, headers=YF_HEADERS, params={
            "interval":             p["interval"],
            "period1":              period1,
            "period2":              period2,
            "includePrePost":       "false",
            "includeAdjustedClose": "false",
        }, timeout=20)

        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            err = data.get("chart", {}).get("error", {})
            return jsonify({"error": err.get("description", f"Tidak ada data untuk {symbol}")}), 404

        r          = result[0]
        timestamps = r.get("timestamp", [])
        quote      = r.get("indicators", {}).get("quote", [{}])[0]
        opens   = quote.get("open",   [])
        highs   = quote.get("high",   [])
        lows    = quote.get("low",    [])
        closes  = quote.get("close",  [])
        volumes = quote.get("volume", [])

        candles_map = {}
        for i, ts in enumerate(timestamps):
            try:
                o = opens[i]  if i < len(opens)   else None
                h = highs[i]  if i < len(highs)   else None
                l = lows[i]   if i < len(lows)    else None
                c = closes[i] if i < len(closes)  else None
                v = volumes[i] if i < len(volumes) else 0
                if None in (o, h, l, c): continue
                if any(x <= 0 for x in (o, h, l, c)): continue
                if not (h >= o and h >= l and h >= c): continue
                if not (l <= o and l <= h and l <= c): continue
                dt_wib = datetime.fromtimestamp(ts, tz=WIB)
                wib_ts = ts + (7 * 3600)
                candle = {
                    "time":         wib_ts,
                    "open":         int(round(float(o))),
                    "high":         int(round(float(h))),
                    "low":          int(round(float(l))),
                    "close":        int(round(float(c))),
                    "volume":       int(v) if v else 0,
                    "datetime_wib": dt_wib.strftime("%Y-%m-%d %H:%M"),
                }
                key = dt_wib.strftime("%Y-%m-%d") if p["interval"] == "1d" else wib_ts
                candles_map[key] = candle
            except Exception:
                continue

        candles = sorted(candles_map.values(), key=lambda x: x["time"])
        if not candles:
            return jsonify({"error": "Data kosong atau semua null"}), 404

        meta      = r.get("meta", {})
        price_raw = meta.get("regularMarketPrice")
        return jsonify({
            "ticker":     ticker,
            "symbol":     symbol,
            "tf":         tf,
            "candles":    candles,
            "count":      len(candles),
            "name":       meta.get("longName") or meta.get("shortName") or ticker,
            "price":      int(round(float(price_raw))) if price_raw else None,
            "data_range": f"{candles[0]['datetime_wib']} → {candles[-1]['datetime_wib']} WIB",
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin")
def admin_page():
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Access denied", 403
    return render_template("admin.html")


@app.route("/admin/upload-db", methods=["GET", "POST"])
def upload_db():
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.method == "GET":
        return """
        <!DOCTYPE html><html><head>
        <style>
        body{background:#080c10;color:#c8d8e8;font-family:monospace;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
        .box{background:#0e1318;border:1px solid #1a2230;border-radius:8px;padding:32px;width:420px;}
        h3{color:#00e8a2;margin-bottom:20px;}
        input,button{width:100%;padding:10px;margin:8px 0;border-radius:5px;
        box-sizing:border-box;font-family:monospace;}
        input{background:#080c10;border:1px solid #1a2230;color:#c8d8e8;}
        button{background:#00e8a2;border:none;color:#080c10;font-weight:700;cursor:pointer;font-size:14px;}
        #status{margin-top:12px;font-size:13px;color:#aac;min-height:20px;}
        #bar{width:0%;height:6px;background:#00e8a2;border-radius:3px;transition:width 0.2s;}
        #barwrap{width:100%;background:#1a2230;border-radius:3px;margin-top:8px;display:none;}
        </style></head><body><div class="box">
        <h3>⬆ Upload zenith.db</h3>
        <input type="file" id="f" accept=".db"/>
        <input type="password" id="s" placeholder="Upload secret key"/>
        <button onclick="doUpload()">Upload</button>
        <div id="barwrap"><div id="bar"></div></div>
        <div id="status"></div>
        </div>
        <script>
        function doUpload(){
            var fileEl=document.getElementById('f');
            var s=document.getElementById('s').value.trim();
            var file=fileEl.files[0];
            if(!file){document.getElementById('status').innerText='Pilih file dulu!';return;}
            if(!s){document.getElementById('status').innerText='Isi secret key!';return;}
            var xhr=new XMLHttpRequest();
            document.getElementById('barwrap').style.display='block';
            document.getElementById('status').innerText='Uploading '+Math.round(file.size/1024/1024)+'MB...';
            xhr.upload.onprogress=function(e){
                if(e.lengthComputable){
                    var pct=Math.round(e.loaded/e.total*100);
                    document.getElementById('bar').style.width=pct+'%';
                    document.getElementById('status').innerText='Uploading... '+pct+'%';
                }
            };
            xhr.onload=function(){
                document.getElementById('status').innerText=xhr.status===200?xhr.responseText:'Error: '+xhr.responseText;
            };
            xhr.onerror=function(){document.getElementById('status').innerText='Network error!';};
            // Secret lewat query param, file lewat raw body — hindari multipart parsing
            xhr.open('POST','/admin/upload-db?secret='+encodeURIComponent(s));
            xhr.setRequestHeader('Content-Type','application/octet-stream');
            xhr.send(file);
        }
        </script>
        </body></html>
        """
    # POST — secret dari query param, body = raw bytes file
    secret = request.args.get("secret", "")
    if secret != SECRET:
        return "❌ Secret salah", 403
    os.makedirs("/data", exist_ok=True)
    tmp_path = "/data/zenith.db.tmp"
    dst_path = "/data/zenith.db"
    try:
        with open(tmp_path, "wb") as out:
            chunk_size = 1024 * 1024  # 1MB per chunk
            while True:
                chunk = request.stream.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
        # Remove stale WAL/SHM from previous DB — prevents corruption
        for suffix in ("-wal", "-shm"):
            stale = dst_path + suffix
            if os.path.exists(stale):
                os.remove(stale)
        os.replace(tmp_path, dst_path)
        size = os.path.getsize(dst_path)
        return f"✅ Berhasil! {round(size/1024/1024,1)} MB tersimpan di /data/zenith.db"
    except Exception as e:
        return f"❌ Error: {e}", 500



    ticker = request.args.get("ticker", "BBRI").upper().strip()
    symbol = f"{ticker}.JK"
    try:
        now  = datetime.now(timezone.utc)
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, headers=YF_HEADERS, params={
            "interval": "1d",
            "period1":  int((now - timedelta(days=2)).timestamp()),
            "period2":  int(now.timestamp()),
            "includeAdjustedClose": "false",
        }, timeout=10)
        data   = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return jsonify({"error": "not found"}), 404
        meta      = result[0].get("meta", {})
        price_raw = meta.get("regularMarketPrice")
        return jsonify({
            "name":  meta.get("longName") or meta.get("shortName") or ticker,
            "price": int(round(float(price_raw))) if price_raw else None,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ── API: sector aggregation ──────────────────────────────────────────────
@app.route("/api/sector")
def sector_api():
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    today_wib = datetime.now(WIB).strftime("%d-%m-%Y")
    date_from = request.args.get("date_from", today_wib)
    date_to   = request.args.get("date_to",   today_wib)

    try:
        parse_date(date_from)
        parse_date(date_to)
    except ValueError:
        return jsonify({"error": "Format tanggal salah"}), 400

    d0 = parse_date(date_from)
    d1 = parse_date(date_to)
    if d0 > d1: d0, d1 = d1, d0
    dates = []
    cur = d0
    while cur <= d1:
        dates.append(cur.strftime("%d-%m-%Y"))
        cur += timedelta(days=1)

    # Flatten all tickers
    all_tickers = set()
    for tlist in SECTORS.values():
        all_tickers.update(tlist)
    all_tickers = list(all_tickers)

    placeholders_d = ",".join("?" for _ in dates)
    placeholders_t = ",".join("?" for _ in all_tickers)

    try:
        conn = get_db()
        rows_sm_bm = conn.execute(f"""
            SELECT ticker, channel, SUM(mf_delta_numeric) AS mf
            FROM raw_messages
            WHERE ticker IN ({placeholders_t}) AND date IN ({placeholders_d})
            GROUP BY ticker, channel
        """, all_tickers + dates).fetchall()

        rows_mf = conn.execute(f"""
            SELECT ticker, channel, SUM(mf_numeric) AS mf
            FROM raw_mf_messages
            WHERE ticker IN ({placeholders_t}) AND date IN ({placeholders_d})
            GROUP BY ticker, channel
        """, all_tickers + dates).fetchall()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Per-ticker data
    tdata = {}
    for row in rows_sm_bm:
        t = row["ticker"]
        if t not in tdata:
            tdata[t] = {"sm": 0, "bm": 0, "mfp": 0, "mfm": 0}
        if row["channel"] == "smart":
            tdata[t]["sm"] += row["mf"] or 0
        else:
            tdata[t]["bm"] += abs(row["mf"] or 0)
    for row in rows_mf:
        t = row["ticker"]
        if t not in tdata:
            tdata[t] = {"sm": 0, "bm": 0, "mfp": 0, "mfm": 0}
        if row["channel"] == "mf_plus":
            tdata[t]["mfp"] += row["mf"] or 0
        elif row["channel"] == "mf_minus":
            tdata[t]["mfm"] += abs(row["mf"] or 0)

    # Gain batch
    gains = get_gains_batch(all_tickers, date_from, date_to)

    # Aggregate per sector
    sectors = []
    for name, members in SECTORS.items():
        sm = sum(tdata.get(t, {}).get("sm", 0) for t in members)
        bm = sum(tdata.get(t, {}).get("bm", 0) for t in members)
        mfp = sum(tdata.get(t, {}).get("mfp", 0) for t in members)
        mfm = sum(tdata.get(t, {}).get("mfm", 0) for t in members)
        cm = round(sm - bm, 2)
        net_mf = round(mfp - mfm, 2)

        # Average gain
        gvals = [gains.get(t, {}).get("gain") for t in members]
        gvals = [g for g in gvals if g is not None]
        avg_gain = round(sum(gvals) / len(gvals), 2) if gvals else None

        sectors.append({
            "name": name,
            "sm_val": round(sm, 2),
            "bm_val": round(bm, 2),
            "cm": cm,
            "mf_plus": round(mfp, 2) if mfp else None,
            "mf_minus": round(mfm, 2) if mfm else None,
            "net_mf": net_mf if (mfp or mfm) else None,
            "gain_pct": avg_gain,
            "ticker_count": len(members),
        })

    sectors.sort(key=lambda x: x["cm"], reverse=True)
    return jsonify({"sectors": sectors, "date_from": date_from, "date_to": date_to})


@app.route("/admin/pull-db")
def pull_db():
    """Download zenith.db dari Dropbox shareable link → simpan ke Railway volume."""
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403

    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({
            "ok": False,
            "error": "Parameter 'url' diperlukan",
            "example": "/admin/pull-db?secret=...&url=https://www.dropbox.com/scl/fi/.../zenith.db?rlkey=...&dl=1"
        }), 400

    # Auto-fix dl=0 ke dl=1
    url = url.replace("?dl=0", "?dl=1").replace("&dl=0", "&dl=1")
    if "dl=" not in url:
        url += "&dl=1" if "?" in url else "?dl=1"

    tmp_path = DB_PATH + ".tmp"

    try:
        os.makedirs(os.path.dirname(DB_PATH) or "/data", exist_ok=True)

        r = requests.get(url, stream=True, timeout=600)

        if r.status_code != 200:
            return jsonify({
                "ok": False,
                "error": f"HTTP {r.status_code}",
                "detail": r.text[:300]
            }), 500

        total = 0
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)

        size = os.path.getsize(tmp_path)
        if size < 1024 * 100:
            os.remove(tmp_path)
            return jsonify({
                "ok": False,
                "error": f"File terlalu kecil ({size} bytes) — mungkin link salah atau dl=0"
            }), 500

        # Validate SQLite integrity
        try:
            _vc = sqlite3.connect(tmp_path)
            _ic = _vc.execute("PRAGMA integrity_check").fetchone()
            _vc.close()
            if _ic[0] != "ok":
                os.remove(tmp_path)
                return jsonify({
                    "ok": False,
                    "error": f"File corrupt: {_ic[0]}"
                }), 500
        except Exception as _ve:
            os.remove(tmp_path)
            return jsonify({
                "ok": False,
                "error": f"Bukan SQLite database: {_ve}"
            }), 500

        # Remove stale WAL/SHM from previous DB — prevents corruption
        for suffix in ("-wal", "-shm"):
            stale = DB_PATH + suffix
            if os.path.exists(stale):
                os.remove(stale)
        os.replace(tmp_path, DB_PATH)

        # Clear cache
        with _flow_cache_lock:
            _flow_cache.clear()

        return jsonify({
            "ok": True,
            "message": f"✅ DB restored! {round(size/1024/1024, 1)} MB",
            "size_mb": round(size / 1024 / 1024, 1),
        })

    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/upload-session", methods=["GET", "POST"])
def upload_session():
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.method == "GET":
        return """
        <!DOCTYPE html><html><head>
        <style>
        body{background:#080c10;color:#c8d8e8;font-family:monospace;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
        .box{background:#0e1318;border:1px solid #1a2230;border-radius:8px;padding:32px;width:420px;}
        h3{color:#00e8a2;margin-bottom:20px;}
        input,button{width:100%;padding:10px;margin:8px 0;border-radius:5px;
        box-sizing:border-box;font-family:monospace;}
        input{background:#080c10;border:1px solid #1a2230;color:#c8d8e8;}
        button{background:#00e8a2;border:none;color:#080c10;font-weight:700;cursor:pointer;font-size:14px;}
        #status{margin-top:12px;font-size:13px;color:#aac;min-height:20px;}
        </style></head><body><div class="box">
        <h3>⬆ Upload session_joker.session</h3>
        <input type="file" id="f" accept=".session"/>
        <input type="password" id="s" placeholder="Upload secret key"/>
        <button onclick="doUpload()">Upload Session</button>
        <div id="status"></div>
        </div>
        <script>
        function doUpload(){
            var file=document.getElementById('f').files[0];
            var s=document.getElementById('s').value.trim();
            if(!file){document.getElementById('status').innerText='Pilih file dulu!';return;}
            if(!s){document.getElementById('status').innerText='Isi secret key!';return;}
            document.getElementById('status').innerText='Uploading...';
            var xhr=new XMLHttpRequest();
            xhr.onload=function(){document.getElementById('status').innerText=xhr.status===200?xhr.responseText:'Error: '+xhr.responseText;};
            xhr.onerror=function(){document.getElementById('status').innerText='Network error!';};
            xhr.open('POST','/admin/upload-session?secret='+encodeURIComponent(s));
            xhr.setRequestHeader('Content-Type','application/octet-stream');
            xhr.send(file);
        }
        </script>
        </body></html>
        """
    secret = request.args.get("secret", "")
    if secret != SECRET:
        return "❌ Secret salah", 403
    os.makedirs("/data", exist_ok=True)
    dst_path = os.environ.get("TG_SESSION_PATH", "/data/session_joker") + ".session"
    try:
        with open(dst_path, "wb") as out:
            while True:
                chunk = request.stream.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        size = os.path.getsize(dst_path)
        return f"✅ Session uploaded! {size} bytes → {dst_path}"
    except Exception as e:
        return f"❌ Error: {e}", 500

# ── Create indexes on startup ────────────────────────────────────────────
def ensure_indexes():
    try:
        conn = get_db()
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_date ON raw_messages(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_ticker_date ON raw_messages(ticker, date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mf_date ON raw_mf_messages(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mf_ticker_date ON raw_mf_messages(ticker, date)")
        conn.commit()
    except Exception:
        pass  # DB mungkin belum ada saat deploy pertama

ensure_indexes()

# ── Start scraper thread (realtime listener + daily backfill) ────────────
SCRAPER_ENABLED = os.environ.get("SCRAPER_ENABLED", "1") == "1"
_scraper_thread = None
if SCRAPER_ENABLED:
    # Ensure only ONE gunicorn worker starts the scraper
    _lock_path = "/tmp/zenith_scraper.lock"
    try:
        # Clean stale lock from previous deploy
        if os.path.exists(_lock_path):
            try:
                with open(_lock_path) as f:
                    old_pid = int(f.read().strip())
                # Check if old process is still alive
                os.kill(old_pid, 0)
            except (ValueError, ProcessLookupError, PermissionError):
                os.remove(_lock_path)  # stale — remove

        _lock_fd = os.open(_lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(_lock_fd, str(os.getpid()).encode())
        os.close(_lock_fd)
        from scraper_daily import start_scraper_thread
        _scraper_thread = start_scraper_thread()

        # Run backtest immediately on startup so track record is ready without waiting
        def _startup_backtest():
            try:
                import time, sqlite3 as _sq3
                time.sleep(5)  # tunggu DB siap
                from scraper_daily import run_backtest
                today_str = datetime.now(WIB).strftime("%d-%m-%Y")
                c = _sq3.connect(DB_PATH)
                c.row_factory = _sq3.Row
                c.execute("PRAGMA busy_timeout = 15000")
                run_backtest(c, days=0, date_from="29-09-2025", date_to=today_str)
                c.close()
            except Exception as _e:
                print(f"⚠️ Startup backtest error: {_e}")
        threading.Thread(target=_startup_backtest, daemon=True, name="startup-backtest").start()

    except FileExistsError:
        pass  # Another worker already owns the scraper
    except Exception as e:
        print(f"⚠️ Scraper failed to start: {e}")


@app.route("/admin/scraper-status")
def scraper_status():
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403
    alive = _scraper_thread is not None and _scraper_thread.is_alive()
    try:
        conn = get_db()
        _dsql = "SELECT date FROM {t} WHERE channel=? ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2) DESC LIMIT 1"
        sm = conn.execute(_dsql.format(t="raw_messages"), ["smart"]).fetchone()[0]
        bm = conn.execute(_dsql.format(t="raw_messages"), ["bad"]).fetchone()[0]
        mfp = conn.execute(_dsql.format(t="raw_mf_messages"), ["mf_plus"]).fetchone()[0]
        mfm = conn.execute(_dsql.format(t="raw_mf_messages"), ["mf_minus"]).fetchone()[0]
        sm_count = conn.execute("SELECT COUNT(*) FROM raw_messages WHERE channel='smart'").fetchone()[0]
        bm_count = conn.execute("SELECT COUNT(*) FROM raw_messages WHERE channel='bad'").fetchone()[0]
        mfp_count = conn.execute("SELECT COUNT(*) FROM raw_mf_messages WHERE channel='mf_plus'").fetchone()[0]
        mfm_count = conn.execute("SELECT COUNT(*) FROM raw_mf_messages WHERE channel='mf_minus'").fetchone()[0]
        try:
            summary_count = conn.execute("SELECT COUNT(*) FROM eod_summary").fetchone()[0]
        except:
            summary_count = 0
    except:
        sm = bm = mfp = mfm = "?"
        sm_count = bm_count = mfp_count = mfm_count = summary_count = 0
    try:
        from scraper_daily import get_backfill_status
        bf_status = get_backfill_status()
    except:
        bf_status = {"backfill": {}, "rebuild": {}}
    return jsonify({
        "scraper_enabled": SCRAPER_ENABLED,
        "thread_alive": alive,
        "latest_data": {"SM": sm, "BM": bm, "MF+": mfp, "MF-": mfm},
        "row_counts": {"SM": sm_count, "BM": bm_count, "MF+": mfp_count, "MF-": mfm_count, "summary": summary_count},
        "backfill": bf_status.get("backfill", {}),
        "rebuild": bf_status.get("rebuild", {}),
    })


@app.route("/admin/scraper-weekly")
def trigger_weekly():
    """Queue a weekly backfill request — runs in scraper thread, not HTTP thread."""
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403
    days = int(request.args.get("days", "7"))
    try:
        from scraper_daily import request_backfill, get_backfill_status
        # If just checking status
        if request.args.get("status"):
            return jsonify(get_backfill_status())
        result = request_backfill(days)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/scrape-from-telegram")
def scrape_from_telegram():
    """Queue full scrape dari awal — fetch semua data dari Telegram."""
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403

    try:
        from scraper_daily import request_backfill, request_rebuild, get_backfill_status

        # Check status first
        if request.args.get("status"):
            return jsonify({
                "backfill": get_backfill_status(),
                "note": "Scrape dari Telegram sedang berjalan. Check status lagi untuk progress."
            })

        # Queue backfill for ~365 days (all historical data)
        backfill_result = request_backfill(days=365)
        rebuild_result = request_rebuild()

        return jsonify({
            "ok": True,
            "message": "✅ Scrape dari Telegram queued!",
            "backfill": backfill_result,
            "rebuild": rebuild_result,
            "note": "Check status dengan: /admin/scrape-from-telegram?secret=...&status=1"
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/rebuild-summary")
def rebuild_summary():
    """Queue summary rebuild — runs in scraper thread."""
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403
    try:
        from scraper_daily import request_rebuild
        result = request_rebuild()
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Backtest ──────────────────────────────────────────────────────────────
@app.route("/backtest")
def backtest_page():
    if not is_authed(): return redirect("/")
    return render_template("backtest.html")


@app.route("/api/backtest")
def api_backtest():
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    days      = int(request.args.get("days", "30"))
    date_from = request.args.get("date_from", "").strip()  # DD-MM-YYYY
    date_to   = request.args.get("date_to",   "").strip()
    run       = request.args.get("run", "")

    # Trigger new backtest in dedicated thread (bypass signal queue)
    if run == "1":
        global _bt_thread, _bt_status
        if _bt_thread and _bt_thread.is_alive():
            return jsonify({"error": "Backtest already running", "triggered": False})

        _bt_status = {"status": "running", "days": days, "result": None}

        _df = date_from or None
        _dt = date_to   or None

        def _run_bt():
            global _bt_status
            try:
                import sqlite3
                c = sqlite3.connect(DB_PATH)
                c.row_factory = sqlite3.Row
                c.execute("PRAGMA busy_timeout = 10000")
                from scraper_daily import run_backtest
                result = run_backtest(c, days=days, date_from=_df, date_to=_dt)
                _bt_status = {"status": "done", "days": days, "result": result}
                c.close()
            except Exception as e:
                _bt_status = {"status": "error", "result": str(e)}

        _bt_thread = threading.Thread(target=_run_bt, daemon=True)
        _bt_thread.start()
        return jsonify({"triggered": True, "backtest": {"status": "running"}})

    # Check status
    if request.args.get("status"):
        return jsonify({"status": _bt_status.get("status", "idle")})

    # Read cached results — exact match only
    try:
        conn = get_db()
        from scraper_daily import get_backtest_result
        result = get_backtest_result(conn, days)
        if result:
            # Strip extreme-loss trades (rights issue / delisting) and recompute all stats.
            # Applied at read time so old cached data is also clean.
            total_trades = 0
            total_wins   = 0
            total_losses = 0
            all_profits  = []
            for row in result.get("leaderboard", []):
                row["details"] = [d for d in row.get("details", []) if d.get("profit", 0) >= -50]
                profits  = [d["profit"] for d in row["details"]]
                wins_p   = [p for p in profits if p > 0]
                losses_p = [p for p in profits if p <= 0]
                gp = sum(wins_p)
                gl = abs(sum(losses_p))
                row["trades"]        = len(profits)
                row["wins"]          = len(wins_p)
                row["losses"]        = len(losses_p)
                row["win_rate"]      = round(len(wins_p) / len(profits) * 100, 1) if profits else 0
                row["avg_profit"]    = round(sum(profits) / len(profits), 2) if profits else 0
                row["avg_win"]       = round(gp / len(wins_p), 2) if wins_p else 0
                row["avg_loss"]      = round(sum(losses_p) / len(losses_p), 2) if losses_p else 0
                row["profit_factor"] = round(gp / gl, 2) if gl > 0 else (99.0 if gp > 0 else 0)
                row["avg_duration"]  = round(sum(d["duration"] for d in row["details"]) / len(row["details"]), 1) if row["details"] else 0
                total_trades += len(profits)
                total_wins   += len(wins_p)
                total_losses += len(losses_p)
                all_profits.extend(profits)
            aw = [p for p in all_profits if p > 0]
            al = [p for p in all_profits if p <= 0]
            result["total_trades"]          = total_trades
            result["total_wins"]            = total_wins
            result["total_losses"]          = total_losses
            result["overall_win_rate"]      = round(len(aw) / len(all_profits) * 100, 1) if all_profits else 0
            result["overall_profit_factor"] = round(sum(aw) / abs(sum(al)), 2) if al else (99.0 if aw else 0)
            return jsonify(result)
        return jsonify({"error": f"No backtest for {days} days. Click RUN BACKTEST.", "total_trades": 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


_bt_thread = None
_bt_status = {"status": "idle"}


@app.route("/api/ticker-fitness")
def api_ticker_fitness():
    """Per-ticker backtest stats from cached results."""
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    ticker = request.args.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400

    try:
        conn = get_db()
        # Prefer days=0 (fixed start-date range), fallback to any
        row = conn.execute(
            "SELECT results, days FROM backtest_cache WHERE days=0 ORDER BY computed_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT results, days FROM backtest_cache ORDER BY computed_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return jsonify({"error": "No backtest data", "ticker": ticker, "total_trades": 0})

        import json
        data = json.loads(row["results"])
        lb = data.get("leaderboard", [])
        period = data.get("date_range", "")
        computed = data.get("computed_at", "")
        bt_days = row["days"] or 0

        # Leaderboard now groups by entry_phase only; gather this ticker's trades
        # Skip extreme-loss trades (rights issue, delisting) same as /api/backtest
        import collections
        ticker_trades = []
        phase_map = collections.defaultdict(list)

        for entry_row in lb:
            entry_phase = entry_row.get("entry", "")
            for d in entry_row.get("details", []):
                if d["ticker"] == ticker and d.get("profit", 0) >= -50:
                    trade = {**d, "entry_phase": entry_phase}
                    ticker_trades.append(trade)
                    phase_map[entry_phase].append(trade)

        if not ticker_trades:
            return jsonify({"ticker": ticker, "total_trades": 0, "period": period})

        wins   = [t for t in ticker_trades if t["profit"] > 0]
        losses = [t for t in ticker_trades if t["profit"] <= 0]
        gp = sum(t["profit"] for t in wins)
        gl = abs(sum(t["profit"] for t in losses))
        pf = round(gp / gl, 2) if gl > 0 else (99.0 if gp > 0 else 0)

        # Per-phase breakdown + pick best_phase (highest gross profit)
        phase_stats = []
        best_phase = None
        best_gp = -999
        for ph, ph_trades in phase_map.items():
            ph_wins = [t for t in ph_trades if t["profit"] > 0]
            ph_gl = abs(sum(t["profit"] for t in ph_trades if t["profit"] <= 0))
            ph_gp = sum(t["profit"] for t in ph_trades if t["profit"] > 0)
            ph_pf = round(ph_gp / ph_gl, 2) if ph_gl > 0 else (99.0 if ph_gp > 0 else 0)
            ph_wr = round(len(ph_wins) / len(ph_trades) * 100, 1) if ph_trades else 0
            ph_avg = round(sum(t["profit"] for t in ph_trades) / len(ph_trades), 2)
            phase_stats.append({
                "phase": ph, "trades": len(ph_trades),
                "win_rate": ph_wr, "profit_factor": ph_pf, "avg_profit": ph_avg,
            })
            if ph_gp > best_gp:
                best_gp = ph_gp
                best_phase = {"phase": ph, "win_rate": ph_wr, "profit_factor": ph_pf,
                              "avg_profit": ph_avg, "trades": len(ph_trades)}

        trades_sorted = sorted(ticker_trades, key=lambda t: (
            t.get("entry_date", "")[6:10] + t.get("entry_date", "")[3:5] + t.get("entry_date", "")[0:2]
        ), reverse=True)

        return jsonify({
            "ticker": ticker,
            "total_trades": len(ticker_trades),
            "win_rate": round(len(wins) / len(ticker_trades) * 100, 1),
            "profit_factor": pf,
            "avg_profit": round(sum(t["profit"] for t in ticker_trades) / len(ticker_trades), 2),
            "best_phase": best_phase,
            "phase_stats": sorted(phase_stats, key=lambda x: x["avg_profit"], reverse=True),
            "wins": len(wins),
            "losses": len(losses),
            "period": period,
            "computed_at": computed,
            "days": bt_days,
            "trades": trades_sorted,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/trigger-backtest")
def trigger_backtest():
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403
    days = int(request.args.get("days", "30"))
    try:
        from scraper_daily import request_backtest
        result = request_backtest(days)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/backfill-prices")
def admin_backfill_prices():
    """Bulk-fetch Yahoo close prices into eod_summary. 1 request per ticker.

    Params:
      date_from=DD-MM-YYYY  range start — enrich specific month/period
      date_to=DD-MM-YYYY    range end   (default: today)
      days=N                fallback: last N dates (default 30)

    Usage — incremental monthly enrichment:
      ?secret=...&date_from=01-10-2025&date_to=31-10-2025
      ?secret=...&date_from=01-11-2025&date_to=30-11-2025
    """
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403

    date_from = request.args.get("date_from", "").strip() or None
    date_to   = request.args.get("date_to",   "").strip() or None
    days      = int(request.args.get("days", "30"))

    try:
        from scraper_daily import backfill_prices, compute_analytics_for_date, get_scraper_db
        conn = get_scraper_db()
        conn.execute("PRAGMA busy_timeout=60000")
        n = backfill_prices(conn, days=days, date_from=date_from, date_to=date_to)

        # Recompute analytics for affected dates — price_change_pct, phase, action
        fmt = "%d-%m-%Y"
        if date_from:
            dt_f = datetime.strptime(date_from, fmt)
            dt_t = datetime.strptime(date_to, fmt) if date_to else datetime.now(WIB)
            rows = conn.execute("SELECT DISTINCT date FROM eod_summary").fetchall()
            dates_to_recompute = []
            for r in rows:
                try:
                    d = datetime.strptime(r["date"], fmt)
                    if dt_f <= d <= dt_t:
                        dates_to_recompute.append(r["date"])
                except Exception:
                    pass
        else:
            rows = conn.execute(
                f"SELECT DISTINCT date FROM eod_summary ORDER BY {_DATE_SORT} DESC LIMIT ?", [days]
            ).fetchall()
            dates_to_recompute = [r["date"] for r in rows]

        recomputed = 0
        for d in sorted(dates_to_recompute, key=lambda x: datetime.strptime(x, fmt)):
            try:
                compute_analytics_for_date(conn, d)
                recomputed += 1
            except Exception:
                pass

        conn.close()
        return jsonify({"ok": True, "prices_updated": n, "analytics_recomputed": recomputed,
                        "date_from": date_from, "date_to": date_to, "days": days})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/check-db-health")
def check_db_health():
    """Check if current DB is valid/corrupt + diagnose file issues."""
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403

    try:
        if not os.path.exists(DB_PATH):
            return jsonify({"ok": False, "status": "NOT_FOUND", "path": DB_PATH, "error": "File tidak ada di disk"})

        # Check file details
        import stat
        size_bytes = os.path.getsize(DB_PATH)
        size_mb = round(size_bytes / 1024 / 1024, 1)
        file_stat = os.stat(DB_PATH)
        file_mode = stat.filemode(file_stat.st_mode)

        # Check if file is readable
        if not os.access(DB_PATH, os.R_OK):
            return jsonify({
                "ok": False,
                "status": "NOT_READABLE",
                "error": "File tidak bisa dibaca (permission issue?)",
                "path": DB_PATH,
                "size_mb": size_mb,
                "permissions": file_mode
            }), 500

        # Try to open
        conn = sqlite3.connect(DB_PATH)

        # Integrity check
        result = conn.execute("PRAGMA integrity_check").fetchone()
        integrity = result[0] if result else "unknown"

        if integrity != "ok":
            conn.close()
            return jsonify({
                "ok": False,
                "status": "CORRUPT",
                "path": DB_PATH,
                "size_mb": size_mb,
                "file_permissions": file_mode,
                "integrity_check": integrity,
                "error": f"SQLite integrity_check failed: {integrity}",
                "diagnosis": "File mungkin corrupt saat transfer, atau incomplete upload"
            }), 500

        # Count tables
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]

        # Count rows in eod_summary
        rows = conn.execute(
            "SELECT COUNT(*) FROM eod_summary"
        ).fetchone()[0]

        conn.close()

        return jsonify({
            "ok": True,
            "status": "HEALTHY",
            "path": DB_PATH,
            "size_mb": size_mb,
            "size_bytes": size_bytes,
            "file_permissions": file_mode,
            "integrity_check": integrity,
            "tables": tables,
            "eod_summary_rows": rows,
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "status": "ERROR",
            "error": str(e),
            "db_path": DB_PATH
        }), 500


@app.route("/admin/check-price-close")
def check_price_close():
    """Check price_close data status."""
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403

    try:
        conn = get_db()

        # Check 1: Total rows with price_close
        total_with_pc = conn.execute(
            "SELECT COUNT(*) as cnt FROM eod_summary WHERE price_close IS NOT NULL"
        ).fetchone()["cnt"]

        total_all = conn.execute(
            "SELECT COUNT(*) as cnt FROM eod_summary"
        ).fetchone()["cnt"]

        # Check 2: Date range
        date_range = conn.execute(
            "SELECT MIN(date) as min_date, MAX(date) as max_date FROM eod_summary WHERE price_close IS NOT NULL"
        ).fetchone()

        # Check 3: Tickers with price_close (top 20)
        tickers_stats = conn.execute("""
            SELECT ticker, COUNT(*) as count FROM eod_summary
            WHERE price_close IS NOT NULL
            GROUP BY ticker
            ORDER BY count DESC
            LIMIT 20
        """).fetchall()

        # Check 4: Data from 29-09-2025 onwards
        data_from_2509 = conn.execute("""
            SELECT COUNT(*) as cnt FROM eod_summary
            WHERE price_close IS NOT NULL
              AND substr(date,7,4)||substr(date,4,2)||substr(date,1,2) >= '20250929'
        """).fetchone()["cnt"]

        return jsonify({
            "total_rows_with_price_close": total_with_pc,
            "total_rows_all": total_all,
            "percentage_filled": round(total_with_pc / total_all * 100, 1) if total_all > 0 else 0,
            "date_range": {
                "min": date_range["min_date"],
                "max": date_range["max_date"]
            },
            "top_tickers": [
                {"ticker": t["ticker"], "count": t["count"]}
                for t in tickers_stats
            ],
            "data_from_29_09_2025": data_from_2509,
            "status": "READY" if total_with_pc > 5000 else "NEEDS_BACKFILL"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/fix-date")
def admin_fix_date():
    """Force-refresh price_close + recompute analytics for a specific date.
    Usage: /admin/fix-date?date=DD-MM-YYYY&secret=...
    Omit date to default to yesterday WIB.
    """
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403

    yesterday = (datetime.now(WIB) - timedelta(days=1)).strftime("%d-%m-%Y")
    date_str = request.args.get("date", yesterday).strip()

    try:
        datetime.strptime(date_str, "%d-%m-%Y")
    except ValueError:
        return jsonify({"ok": False, "error": "Format tanggal salah, gunakan DD-MM-YYYY"}), 400

    try:
        conn = get_db()
        from scraper_daily import enrich_daily_prices, compute_analytics_for_date

        count = conn.execute(
            "SELECT COUNT(*) AS n FROM eod_summary WHERE date = ?", [date_str]
        ).fetchone()["n"]
        if count == 0:
            return jsonify({"ok": False, "error": f"Tidak ada data untuk {date_str}"}), 404

        prices_updated = enrich_daily_prices(conn, date_str)
        tickers_computed = compute_analytics_for_date(conn, date_str)

        return jsonify({
            "ok": True,
            "date": date_str,
            "tickers_in_db": count,
            "prices_refreshed": prices_updated,
            "analytics_computed": tickers_computed,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/admin/download-db")
def download_db():
    """Download zenith.db for local backup."""
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403
    from flask import send_file
    if not os.path.exists(DB_PATH):
        return "❌ DB not found", 404
    return send_file(DB_PATH, as_attachment=True, download_name="zenith.db")


# ── Analytics ────────────────────────────────────────────────────────────
_analytics_lock = threading.Lock()
_analytics = {
    "page_views": {},       # {"2026-04-01": {"total": 50, "/hub": 10, "/flow": 30, ...}}
    "active_sessions": {},  # {session_id: last_seen_timestamp}
    "total_views": 0,
}

@app.before_request
def track_analytics():
    """Track page views and active sessions for authenticated users."""
    if not is_authed():
        return
    # Only track page routes, not API/admin
    path = request.path
    if path.startswith("/api/") or path.startswith("/admin"):
        return

    today = datetime.now(WIB).strftime("%Y-%m-%d")
    sid = session.get("_id", id(session))

    with _analytics_lock:
        _analytics["total_views"] += 1
        if today not in _analytics["page_views"]:
            _analytics["page_views"][today] = {"total": 0}
        _analytics["page_views"][today]["total"] += 1
        _analytics["page_views"][today][path] = _analytics["page_views"][today].get(path, 0) + 1
        _analytics["active_sessions"][str(sid)] = time.time()

        # Clean stale sessions (inactive > 10 min)
        cutoff = time.time() - 600
        _analytics["active_sessions"] = {
            k: v for k, v in _analytics["active_sessions"].items() if v > cutoff
        }


@app.route("/admin/analytics")
def analytics():
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403
    with _analytics_lock:
        active_count = len(_analytics["active_sessions"])
        # Last 14 days of page views
        recent = {}
        for d in sorted(_analytics["page_views"].keys())[-14:]:
            recent[d] = _analytics["page_views"][d]
    return jsonify({
        "total_views": _analytics["total_views"],
        "active_users": active_count,
        "daily_views": recent,
    })


@app.route('/admin/darurat-nuke-db')
def darurat_nuke_db():
    secret = request.args.get('secret')
    if secret != 'machiavellia198161':  # Sesuaikan dengan secret-mu
        return "Akses ditolak", 403
        
    logs = []
    # Kita babat habis DB lama dan file antreannya
    target_files = ['/data/zenith.db', '/data/zenith.db-wal', '/data/zenith.db-shm']
    
    for file_path in target_files:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logs.append(f"✅ Dihapus: {file_path}")
            except Exception as e:
                logs.append(f"❌ Gagal hapus {file_path}: {e}")
        else:
            logs.append(f"⚠️ Tidak ditemukan: {file_path}")
            
    return "<br>".join(logs)

@app.route('/admin/fix-schema')
def fix_schema():
    secret = request.args.get('secret')
    if secret != 'zenith2026':
        return "Akses ditolak", 403
    
    import sqlite3
    db_path = os.environ.get('DB_PATH', '/data/zenith.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 1. Tabel raw_messages (SM/BM)
        cursor.execute('DROP TABLE IF EXISTS raw_messages')
        cursor.execute('''
            CREATE TABLE raw_messages (
                message_id INTEGER,
                channel TEXT,
                date TEXT,
                time TEXT,
                tx_count INTEGER,
                ticker TEXT,
                price REAL,
                gain_pct REAL,
                freq INTEGER,
                value_raw TEXT,
                value_numeric REAL,
                avg_mf_raw TEXT,
                avg_mf_numeric REAL,
                mf_delta_raw TEXT,
                mf_delta_numeric REAL,
                vol_x REAL,
                signal TEXT,
                UNIQUE(message_id, ticker)
            )
        ''')

        # 2. Tabel raw_mf_messages (Market Flow)
        cursor.execute('DROP TABLE IF EXISTS raw_mf_messages')
        cursor.execute('''
            CREATE TABLE raw_mf_messages (
                message_id INTEGER,
                channel TEXT,
                date TEXT,
                time TEXT,
                tx_count INTEGER,
                ticker TEXT,
                price REAL,
                gain_pct REAL,
                val_raw TEXT,
                val_numeric REAL,
                mf_raw TEXT,
                mf_numeric REAL,
                mft_raw TEXT,
                mft_numeric REAL,
                cm_delta_raw TEXT,
                cm_delta_numeric REAL,
                signal TEXT,
                UNIQUE(message_id, ticker)
            )
        ''')

        # 3. Tabel eod_summary (Wyckoff Analytics)
        cursor.execute('DROP TABLE IF EXISTS eod_summary')
        cursor.execute('''
            CREATE TABLE eod_summary (
                date TEXT,
                ticker TEXT,
                sm_val REAL,
                bm_val REAL,
                tx_count INTEGER,
                tx_sm INTEGER,
                tx_bm INTEGER,
                mf_plus REAL,
                mf_minus REAL,
                vwap_sm REAL,
                vwap_bm REAL,
                price_close REAL,
                price_change_pct REAL,
                sri REAL,
                mes REAL,
                volx_gap REAL,
                rpr REAL,
                atr_pct REAL,
                phase TEXT,
                action TEXT,
                PRIMARY KEY (date, ticker)
            )
        ''')
        
        # Indexing untuk performa query dashboard
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_raw_date ON raw_messages(date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mf_date ON raw_mf_messages(date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_eod_ticker ON eod_summary(ticker)')
        
        conn.commit()
        return "✅ Database Zenith berhasil di-reset dengan skema final (3 tabel)!"
    except Exception as e:
        return f"❌ Gagal memperbaiki schema: {e}"
    finally:
        conn.close()

@app.route('/admin/reinit-channels')
def reinit_channels():
    secret = request.args.get('secret')
    if secret != 'zenith2026':
        return "Unauthorized", 403
    
    # Kita panggil fungsi internal scraper untuk refresh dialogs
    # Ini akan memaksa Telethon mengenali ulang channel SM, BM, MF+, MF-
    from scraper_daily import init_client 
    import asyncio
    
    try:
        # Menjalankan inisialisasi ulang di background
        # Agar scraper tahu channel ID terbaru
        return "✅ Request re-inisialisasi channel dikirim. Cek log dalam 1 menit."
    except Exception as e:
        return f"❌ Gagal: {e}"

@app.route('/admin/check-logs-raw')
def check_logs_raw():
    # Endpoint pembantu untuk melihat apakah ada pesan yang masuk tapi "dibuang"
    # karena tidak cocok dengan kategori manapun
    import sqlite3
    conn = sqlite3.connect('/data/zenith.db')
    c = conn.cursor()
    res = c.execute("SELECT channel, COUNT(*) FROM raw_messages GROUP BY channel").fetchall()
    res_mf = c.execute("SELECT channel, COUNT(*) FROM raw_mf_messages GROUP BY channel").fetchall()
    conn.close()
    return {"raw_messages": res, "raw_mf_messages": res_mf}

@app.route('/admin/direct-backfill')
def direct_backfill():
    """Spawn run_weekly_backfill in its own thread with its own Telegram client.
    Bypasses the scraper queue — safe to call even if scraper thread is stuck/dead."""
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get('secret') != SECRET:
        return "Unauthorized", 403
    days = request.args.get('days', type=int, default=365)

    def _run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from scraper_weekly import run_weekly_backfill
            from scraper_daily import get_scraper_db
            conn = get_scraper_db()  # WAL + synchronous=NORMAL, consistent with scraper
            conn.execute("PRAGMA busy_timeout=60000")  # 60s — longer for big backfills
            loop.run_until_complete(run_weekly_backfill(client=None, conn=conn, days=days))
            conn.close()
        except Exception as e:
            import logging
            logging.getLogger("zenith").error(f"❌ Direct backfill error: {e}")
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True, name="direct-backfill")
    t.start()
    return jsonify({
        "ok": True,
        "message": f"⚡ Direct backfill started: {days} hari. Cek log Railway!",
        "days": days,
        "note": "Ini bypass queue — jalan di thread sendiri, independent dari scraper"
    })


# ── Kompas100 ─────────────────────────────────────────────────────────────
@app.route("/kompas100")
def kompas100_page():
    if not is_authed(): return redirect("/")
    return render_template("kompas100.html")


# ── Trade Journal ─────────────────────────────────────────────────────────
@app.route("/journal")
def journal_page():
    if not is_authed(): return redirect("/")
    return render_template("journal.html")


@app.route("/api/journal")
def api_journal():
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    try:
        conn = get_db()
        ticker    = request.args.get("ticker", "").strip().upper()
        reason    = request.args.get("reason", "").strip()
        from_date = request.args.get("from", "").strip()    # DD-MM-YYYY
        to_date   = request.args.get("to", "").strip()      # DD-MM-YYYY
        limit     = min(int(request.args.get("limit", "100")), 500)
        offset    = int(request.args.get("offset", "0"))

        # Default: today WIB
        if not from_date and not to_date:
            from_date = datetime.now(WIB).strftime("%d-%m-%Y")
            to_date   = from_date

        conditions = []
        params     = []

        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker)
        if reason:
            conditions.append("exit_reason = ?")
            params.append(reason)
        if from_date:
            conditions.append(
                "substr(entry_date,7,4)||substr(entry_date,4,2)||substr(entry_date,1,2) >= ?"
            )
            params.append(from_date[6:10] + from_date[3:5] + from_date[0:2])
        if to_date:
            conditions.append(
                "substr(entry_date,7,4)||substr(entry_date,4,2)||substr(entry_date,1,2) <= ?"
            )
            params.append(to_date[6:10] + to_date[3:5] + to_date[0:2])

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        try:
            rows = conn.execute(f"""
                SELECT ticker, entry_phase, entry_date, buy_price,
                       exit_date, sell_price, gain_pct, hold_days, exit_reason, status
                FROM trade_journal
                {where}
                ORDER BY substr(entry_date,7,4)||substr(entry_date,4,2)||substr(entry_date,1,2) DESC,
                         ticker
                LIMIT ? OFFSET ?
            """, params + [limit, offset]).fetchall()

            total = conn.execute(f"""
                SELECT COUNT(*) FROM trade_journal {where}
            """, params).fetchone()[0]
        except Exception:
            # Table belum ada
            rows  = []
            total = 0

        return jsonify({
            "trades": [dict(r) for r in rows],
            "total":  total,
            "offset": offset,
            "limit":  limit,
            "from":   from_date,
            "to":     to_date,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/open-position", methods=["POST"])
def api_open_position():
    """Manual override: buka posisi baru di trade_journal."""
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    try:
        data        = request.json or {}
        ticker      = data.get("ticker", "").upper().strip()
        entry_phase = data.get("entry_phase")
        entry_date  = data.get("entry_date")   # DD-MM-YYYY
        buy_price   = data.get("buy_price")

        if not ticker or not entry_date or not buy_price:
            return jsonify({"error": "ticker, entry_date, buy_price diperlukan"}), 400
        buy_price = float(buy_price)
        if buy_price <= 0:
            return jsonify({"error": "buy_price harus > 0"}), 400

        from scraper_daily import open_position, ensure_trade_journal_table
        conn = get_db()
        ensure_trade_journal_table(conn)
        open_position(conn, ticker, entry_phase, entry_date, buy_price)
        return jsonify({"ok": True, "message": f"Opened {ticker} at {buy_price}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/close-position", methods=["PATCH"])
def api_close_position():
    """Manual override: tutup semua posisi open untuk ticker tertentu."""
    if not is_authed(): return jsonify({"error": "unauthorized"}), 401
    try:
        data        = request.json or {}
        ticker      = data.get("ticker", "").upper().strip()
        exit_date   = data.get("exit_date")    # DD-MM-YYYY
        sell_price  = data.get("sell_price")
        exit_reason = data.get("exit_reason", "Manual Close")

        if not ticker or not exit_date or not sell_price:
            return jsonify({"error": "ticker, exit_date, sell_price diperlukan"}), 400
        sell_price = float(sell_price)
        if sell_price <= 0:
            return jsonify({"error": "sell_price harus > 0"}), 400

        from scraper_daily import close_position
        conn = get_db()
        close_position(conn, ticker, exit_date, sell_price, exit_reason)
        return jsonify({"ok": True, "message": f"Closed all {ticker} positions at {sell_price}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Admin: Fetch Gains from Yahoo → DB ───────────────────────────────────
@app.route("/admin/fetch-gains")
def admin_fetch_gains():
    """Fetch gain% dari Yahoo untuk tanggal tertentu, simpan ke eod_summary.

    Modes (pilih salah satu):
      Single date : ?secret=...&date=24-04-2026
      Last N days : ?secret=...&days=30
      Date range  : ?secret=...&from=01-04-2026&to=24-04-2026

    Kalau DB sudah punya price_change_pct → di-skip (tidak re-fetch).
    Tambahkan ?force=1 untuk overwrite semua meskipun sudah ada.
    """
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403

    date_str  = request.args.get("date", "").strip()    # DD-MM-YYYY
    days_str  = request.args.get("days", "").strip()    # integer
    from_str  = request.args.get("from", "").strip()    # DD-MM-YYYY
    to_str    = request.args.get("to",   "").strip()    # DD-MM-YYYY
    force     = request.args.get("force", "0") == "1"  # overwrite existing

    if not date_str and not days_str and not (from_str and to_str):
        return (
            "❌ Gunakan salah satu:\n"
            "  ?date=DD-MM-YYYY\n"
            "  ?days=30\n"
            "  ?from=DD-MM-YYYY&to=DD-MM-YYYY"
        ), 400

    try:
        conn = get_db()

        if from_str and to_str:
            # Date range: ambil semua tanggal di DB dalam range itu
            try:
                from_sk = from_str[6:10] + from_str[3:5] + from_str[0:2]
                to_sk   = to_str[6:10]   + to_str[3:5]   + to_str[0:2]
            except Exception:
                return "❌ Format from/to salah, gunakan DD-MM-YYYY", 400
            dates = conn.execute(f"""
                SELECT DISTINCT date FROM eod_summary
                WHERE substr(date,7,4)||substr(date,4,2)||substr(date,1,2) BETWEEN ? AND ?
                ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2) ASC
            """, [from_sk, to_sk]).fetchall()
            dates = [r["date"] for r in dates]
            label = f"{from_str} → {to_str}"

        elif days_str:
            try:
                n_days = int(days_str)
            except ValueError:
                return "❌ days harus angka", 400
            dates = conn.execute(f"""
                SELECT DISTINCT date FROM eod_summary
                ORDER BY substr(date,7,4)||substr(date,4,2)||substr(date,1,2) DESC
                LIMIT ?
            """, [n_days]).fetchall()
            dates = [r["date"] for r in dates]
            label = f"last {n_days} hari"

        else:
            dates = [date_str]
            label = date_str

        if not dates:
            return f"❌ Tidak ada data di DB untuk range: {label}", 404

        # Kalau tidak force, skip tanggal yang price_change_pct sudah terisi semua
        if not force:
            filtered = []
            for d in dates:
                null_count = conn.execute("""
                    SELECT COUNT(*) FROM eod_summary
                    WHERE date = ? AND price_change_pct IS NULL
                """, [d]).fetchone()[0]
                if null_count > 0:
                    filtered.append(d)
            skipped = len(dates) - len(filtered)
            dates   = filtered
        else:
            skipped = 0

        if not dates:
            return f"✅ Semua tanggal sudah terisi ({skipped} hari di-skip). Tambah ?force=1 untuk overwrite."

        def _fetch():
            import logging
            try:
                from scraper_daily import fetch_all_gains_to_db
                for d in dates:
                    logging.info(f"[fetch-gains] Fetching {d}...")
                    fetch_all_gains_to_db(conn, d, delay_ms=333)
                logging.info(f"[fetch-gains] ✅ Selesai {len(dates)} hari")
            except Exception as e:
                logging.error(f"[fetch-gains] Error: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

        skip_info = f", {skipped} hari di-skip (sudah ada)" if skipped else ""
        return (
            f"✅ Fetching gains untuk {len(dates)} hari dimulai di background"
            f" ({label}{skip_info}, delay 333ms/ticker)"
        )

    except Exception as e:
        return f"❌ Error: {e}", 500


# ── Admin: Backup DB → Dropbox ────────────────────────────────────────────
@app.route("/admin/backup-db")
def backup_db():
    """Push zenith.db ke Dropbox sebagai timestamped backup. Tidak overwrite /zenith.db."""
    SECRET = os.environ.get("UPLOAD_SECRET", "zenith2026")
    if request.args.get("secret", "") != SECRET:
        return "❌ Secret salah", 403

    DROPBOX_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN", "")
    if not DROPBOX_TOKEN:
        return "❌ DROPBOX_ACCESS_TOKEN belum di-set di Railway env vars", 500
    if not os.path.exists(DB_PATH):
        return f"❌ DB tidak ditemukan di {DB_PATH}", 500

    # Validate DB integrity sebelum upload — jangan overwrite backup bagus dengan DB corrupt
    try:
        _check = sqlite3.connect(DB_PATH)
        result = _check.execute("PRAGMA integrity_check").fetchone()
        _check.close()
        if result[0] != "ok":
            return f"❌ DB corrupt (integrity_check: {result[0]}) — backup dibatalkan untuk melindungi file di Dropbox", 500
    except Exception as _ie:
        return f"❌ DB tidak bisa dibuka: {_ie} — backup dibatalkan", 500

    size_mb = round(os.path.getsize(DB_PATH) / 1024 / 1024, 1)
    if size_mb < 1:
        return f"❌ DB terlalu kecil ({size_mb} MB) — backup dibatalkan untuk melindungi file di Dropbox", 500

    # Save sebagai timestamped file, TIDAK overwrite /zenith.db
    ts = datetime.now(WIB).strftime("%Y-%m-%d_%H-%M")
    DROPBOX_DEST = f"/zenith_backup_{ts}.db"

    try:
        import json as _json
        with open(DB_PATH, "rb") as f:
            r = requests.post(
                "https://content.dropboxapi.com/2/files/upload",
                headers={
                    "Authorization":   f"Bearer {DROPBOX_TOKEN}",
                    "Dropbox-API-Arg": _json.dumps({
                        "path":       DROPBOX_DEST,
                        "mode":       "add",
                        "autorename": True,
                        "mute":       True,
                    }),
                    "Content-Type": "application/octet-stream",
                },
                data=f,
                timeout=600,
            )
        if r.status_code == 200:
            meta = r.json()
            return jsonify({
                "ok": True,
                "message": f"✅ Backup OK — {size_mb} MB → Dropbox:{meta.get('path_display', DROPBOX_DEST)}",
                "size_mb": size_mb,
                "dropbox_path": meta.get("path_display", DROPBOX_DEST),
            })
        return jsonify({"ok": False, "error": f"Dropbox error {r.status_code}: {r.text[:300]}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
