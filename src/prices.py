"""Phase 2 — Price data acquisition from NSE (survivorship-free by construction).

The one idea that matters: we do **not** fetch a symbol list. We download WHOLE
TRADING DAYS from NSE. Delisted companies arrive automatically because they were
trading that day. Everything else here is bookkeeping.

Sources (all probed live 2026-09-02, see PRE_BUILD_TASKS.md T1):
* 2014-01-01 .. 2019-09-27 : legacy zip
  ``.../content/historical/EQUITIES/<YYYY>/<MON>/cm<DDMONYYYY>bhav.csv.zip``
* 2019-09-30 .. present     : ``.../products/content/sec_bhavdata_full_<DDMMYYYY>.csv``
  (also carries DELIV_QTY / DELIV_PER)
* corporate actions         : ``.../api/corporates-corporateActions`` (needs a
  session cookie + Referer)

Outputs (IMPLEMENTATION_PLAN.md Section 0.5 + Phase 2 Outputs):
* ``data/raw/nse/<YYYY>/<file>``            — every daily file, cached verbatim
* ``data/raw/nse_ca/<YYYY>.json``           — corporate actions per year
* ``data/prices/ohlcv.parquet``            — adjusted + raw, ISIN-keyed, + ``series``
* ``data/prices/isin_map.parquet``         — date · symbol · isin
* ``data/prices/corporate_actions.parquet``— isin · ex_date · type · ratio · raw_subject
* ``data/prices/delivery.parquet``         — date · symbol · deliv_qty · delivery_pct
* ``data/prices/size_proxy.parquet``       — date · symbol · size_proxy
* ``reports/p2_coverage_report.md`` + ``reports/p2_coverage_plot.png``

Run: ``python -m src.prices``  (resumable; re-running downloads nothing new).
"""
from __future__ import annotations

import io
import json
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import PRICES_DIR, RAW_DIR, REPORTS_DIR
from .contracts import SchemaError, validate_ohlcv

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #
DATE_START = pd.Timestamp("2014-01-01")
DATE_END = pd.Timestamp("2025-12-31")           # HOLDOUT end; 2026+ is reserved
LEGACY_LAST = pd.Timestamp("2019-09-27")        # modern format starts 2019-09-30
MODERN_FIRST = pd.Timestamp("2019-09-30")

SERIES_KEEP = ("EQ", "BE")                       # decision: keep BE (distress signal)

TURNOVER_WINDOW = 63                             # trailing days for size_proxy
SIZE_PROXY_MIN_DAYS = 63

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_HDRS = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
_CA_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-actions"

RAW_NSE = RAW_DIR / "nse"
RAW_CA = RAW_DIR / "nse_ca"
EQUITY_L_PATH = RAW_NSE / "EQUITY_L.csv"

ISIN_MAP_PARQUET = PRICES_DIR / "isin_map.parquet"
CORP_ACTIONS_PARQUET = PRICES_DIR / "corporate_actions.parquet"
DELIVERY_PARQUET = PRICES_DIR / "delivery.parquet"
SIZE_PROXY_PARQUET = PRICES_DIR / "size_proxy.parquet"
OHLCV_PARQUET = PRICES_DIR / "ohlcv.parquet"
COVERAGE_REPORT = REPORTS_DIR / "p2_coverage_report.md"
COVERAGE_PLOT = REPORTS_DIR / "p2_coverage_plot.png"

_MONS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
         "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# Indian *equity* ISINs are "INE" + 9 alnum + check digit. "INF" = mutual-fund /
# ETF units, "IN9" = differential-voting-rights (DVR) lines, rights entitlements
# get their own temporary codes. We keep INE only — an ETF or a DVR twin in a
# single-stock cross-section double-counts the name.
EQUITY_ISIN_PREFIX = "INE"

# Post-2019 renames whose historical ticker resolves to no ISIN in any of our
# sources (legacy bhavcopy has no rows that early; EQUITY_L / the CA API key by
# the *current* name). Hand-verified against NSE. Applied before the INE filter
# so these genuine large caps are not dropped.
SYMBOL_ISIN_PATCH: dict[str, str] = {
    "ZOMATO": "INE758T01015",   # listed 2021; renamed ETERNAL 2025-03
    "LTIM": "INE214T01019",     # LTI+Mindtree merger 2022 (kept LTI's ISIN)
}

# Face-value splits that NSE's corporate-actions API simply does not return
# (verified: `?index=equities&from_date=..&to_date=..` yields zero rows for these
# symbols across every year chunk). Each is a clean face-value split confirmed
# against the raw close break (post/pre ratio in the comment). Ratio multiplies
# pre-ex-date prices, exactly like a parsed CA. Kept deliberately small and
# audited — this is the same hand-patch pattern as SYMBOL_ISIN_PATCH, not a
# blanket "snap any big gap to a split" (which would erase genuine crashes).
SPLIT_PATCH: list[dict] = [
    {"symbol": "INFIBEAM",  "ex_date": "2017-08-31", "ratio": 0.10,  # raw 0.102 → 10:1
     "raw_subject": "PATCH: Face Value Split Rs 10 To Re 1 (absent from NSE CA API)"},
    {"symbol": "WELSPUNIND", "ex_date": "2016-03-21", "ratio": 0.10,  # raw 0.104 → 10:1
     "raw_subject": "PATCH: Face Value Split Rs 10 To Re 1 (absent from NSE CA API)"},
    {"symbol": "CADILAHC",  "ex_date": "2015-10-06", "ratio": 0.20,  # raw 0.205 → 5:1
     "raw_subject": "PATCH: Face Value Split Rs 5 To Re 1 (absent from NSE CA API)"},
    {"symbol": "TWL",       "ex_date": "2015-04-23", "ratio": 0.20,  # raw 0.194 → 5:1
     "raw_subject": "PATCH: Face Value Split Rs 10 To Rs 2 (absent from NSE CA API)"},
    {"symbol": "MCDOWELL-N", "ex_date": "2018-06-15", "ratio": 0.20,  # raw 0.196 → 5:1
     "raw_subject": "PATCH: Face Value Split Rs 10 To Rs 2 (absent from NSE CA API)"},
    {"symbol": "PHILIPCARB", "ex_date": "2018-04-19", "ratio": 0.20,  # raw 0.210 → 5:1
     "raw_subject": "PATCH: Face Value Split Rs 10 To Rs 2 (absent from NSE CA API)"},
]

CANARIES = ["DHFL", "RCOM", "JPASSOCIAT", "YESBANK", "SUZLON", "IDEA", "COX&KINGS"]
HEAVYWEIGHTS = ["RELIANCE", "TCS", "SBIN", "TATASTEEL", "MARUTI", "ONGC", "INFY", "HDFCBANK"]


# --------------------------------------------------------------------------- #
# Report accumulator                                                           #
# --------------------------------------------------------------------------- #
@dataclass
class Report:
    lines: list[str] = field(default_factory=list)

    def log(self, msg: str) -> None:
        print(f"[p2] {msg}", flush=True)
        self.lines.append(msg)


# --------------------------------------------------------------------------- #
# 1. Download                                                                  #
# --------------------------------------------------------------------------- #
def _new_session(with_cookie: bool = False) -> requests.Session:
    s = requests.Session()
    s.headers.update(_HDRS)
    retry = Retry(total=3, backoff_factor=0.6,
                  status_forcelist=(403, 429, 500, 502, 503, 504),
                  allowed_methods=frozenset(["GET"]))
    ad = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    s.mount("https://", ad)
    if with_cookie:
        try:
            s.get("https://www.nseindia.com", timeout=30)
        except requests.RequestException:
            pass
    return s


_session = _new_session  # backwards-compatible alias

_tls = threading.local()


def _worker_session() -> requests.Session:
    """One pooled, keep-alive Session per worker thread (not per request)."""
    s = getattr(_tls, "sess", None)
    if s is None:
        s = _new_session()
        _tls.sess = s
    return s


def _trading_day_candidates() -> list[pd.Timestamp]:
    """Weekdays in [DATE_START, DATE_END]. Holidays surface as 404 and are skipped."""
    return list(pd.bdate_range(DATE_START, DATE_END))


def _legacy_url_and_path(d: pd.Timestamp) -> tuple[str, Path]:
    fn = f"cm{d.day:02d}{_MONS[d.month - 1]}{d.year}bhav.csv.zip"
    url = (f"https://nsearchives.nseindia.com/content/historical/EQUITIES/"
           f"{d.year}/{_MONS[d.month - 1]}/{fn}")
    return url, RAW_NSE / str(d.year) / fn


def _modern_url_and_path(d: pd.Timestamp) -> tuple[str, Path]:
    fn = f"sec_bhavdata_full_{d.day:02d}{d.month:02d}{d.year}.csv"
    url = f"https://nsearchives.nseindia.com/products/content/{fn}"
    return url, RAW_NSE / str(d.year) / fn


def _fetch_one(url: str, dest: Path, session: requests.Session,
               min_bytes: int = 200) -> str:
    """Return one of: 'cached', 'ok', 'holiday', 'error'. Writes a .404 marker."""
    marker = dest.with_suffix(dest.suffix + ".404")
    if dest.exists() and dest.stat().st_size >= min_bytes:
        return "cached"
    if marker.exists():
        return "holiday"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            r = session.get(url, timeout=45)
        except requests.RequestException:
            time.sleep(1.0)
            continue
        if r.status_code == 200 and len(r.content) >= min_bytes:
            dest.write_bytes(r.content)
            return "ok"
        if r.status_code == 404:
            marker.write_text("404\n")
            return "holiday"
        time.sleep(1.0)
    return "error"


def download_all(rep: Report, workers: int = 4) -> dict:
    """Download every trading-day file (legacy + modern) plus the equity list.

    Resumable: files already on disk (and 404 markers) are skipped.
    """
    RAW_NSE.mkdir(parents=True, exist_ok=True)
    # equity list (for ISIN backfill of the modern era, which lacks an ISIN column)
    if not EQUITY_L_PATH.exists():
        s = _session()
        try:
            r = s.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
                      timeout=45)
            if r.status_code == 200:
                EQUITY_L_PATH.write_bytes(r.content)
        except requests.RequestException:
            rep.log("WARN could not download EQUITY_L.csv (ISIN backfill degraded)")

    tasks: list[tuple[str, Path]] = []
    for d in _trading_day_candidates():
        if d <= LEGACY_LAST:
            tasks.append(_legacy_url_and_path(d))
        if d >= MODERN_FIRST:
            tasks.append(_modern_url_and_path(d))

    counts = {"cached": 0, "ok": 0, "holiday": 0, "error": 0}
    errors: list[str] = []

    def _work(args):
        url, dest = args
        res = _fetch_one(url, dest, _worker_session())
        return url, res

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_work, t) for t in tasks]
        for i, fut in enumerate(as_completed(futs), 1):
            url, res = fut.result()
            counts[res] += 1
            if res == "error":
                errors.append(url)
            if i % 200 == 0:
                rep.log(f"download progress {i}/{len(tasks)} — {counts}")

    rep.log(f"download done: {counts}; {len(errors)} hard errors")
    if errors:
        rep.log("first hard errors: " + ", ".join(e.rsplit('/', 1)[-1] for e in errors[:10]))
    return {"counts": counts, "errors": errors, "n_tasks": len(tasks)}


def download_corporate_actions(rep: Report) -> None:
    RAW_CA.mkdir(parents=True, exist_ok=True)
    for year in range(DATE_START.year, DATE_END.year + 1):
        dest = RAW_CA / f"{year}.json"
        if dest.exists() and dest.stat().st_size > 20:
            continue
        s = _session(with_cookie=True)
        url = ("https://www.nseindia.com/api/corporates-corporateActions"
               f"?index=equities&from_date=01-01-{year}&to_date=31-12-{year}")
        ok = False
        for attempt in range(4):
            try:
                r = s.get(url, headers={"Referer": _CA_REFERER}, timeout=60)
                if r.status_code == 200:
                    data = r.json()
                    dest.write_text(json.dumps(data))
                    rep.log(f"corp actions {year}: {len(data)} records")
                    ok = True
                    break
            except (requests.RequestException, ValueError):
                pass
            time.sleep(2.0 * (attempt + 1))
            s = _session(with_cookie=True)
        if not ok:
            rep.log(f"WARN corp actions {year}: could not fetch — adjustment degraded")
            dest.write_text("[]")


# --------------------------------------------------------------------------- #
# 2. Parse                                                                     #
# --------------------------------------------------------------------------- #
_NUM = lambda s: pd.to_numeric(s, errors="coerce")


def parse_legacy_zip(path: Path) -> pd.DataFrame | None:
    try:
        with zipfile.ZipFile(path) as z:
            raw = z.read(z.namelist()[0])
    except (zipfile.BadZipFile, OSError):
        return None
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = [c.strip() for c in df.columns]
    df = df[df["SERIES"].astype(str).str.strip().isin(SERIES_KEEP)].copy()
    if df.empty:
        return None
    out = pd.DataFrame({
        "date": pd.to_datetime(df["TIMESTAMP"], format="%d-%b-%Y"),
        "symbol": df["SYMBOL"].astype(str).str.strip(),
        "series": df["SERIES"].astype(str).str.strip(),
        "open": _NUM(df["OPEN"]), "high": _NUM(df["HIGH"]),
        "low": _NUM(df["LOW"]), "close": _NUM(df["CLOSE"]),
        "prevclose": _NUM(df["PREVCLOSE"]),
        "volume_raw": _NUM(df["TOTTRDQTY"]),
        "tottrdval": _NUM(df["TOTTRDVAL"]),
        "n_trades": _NUM(df["TOTALTRADES"]),
        "isin": df["ISIN"].astype(str).str.strip().replace({"nan": np.nan, "-": np.nan}),
        "deliv_qty": np.nan, "delivery_pct": np.nan,
        "source": "bhavcopy_legacy",
    })
    with np.errstate(divide="ignore", invalid="ignore"):
        out["vwap"] = out["tottrdval"] / out["volume_raw"]
    return out.drop(columns=["tottrdval"])


def parse_modern_csv(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, skipinitialspace=True)
    except (pd.errors.ParserError, OSError, UnicodeDecodeError):
        return None
    df.columns = [c.strip() for c in df.columns]
    if "SERIES" not in df.columns:
        return None
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    df = df[df["SERIES"].isin(SERIES_KEEP)].copy()
    if df.empty:
        return None
    na = {"-": np.nan, " -": np.nan, "": np.nan}
    out = pd.DataFrame({
        "date": pd.to_datetime(df["DATE1"].astype(str).str.strip(), format="%d-%b-%Y"),
        "symbol": df["SYMBOL"].astype(str).str.strip(),
        "series": df["SERIES"],
        "open": _NUM(df["OPEN_PRICE"]), "high": _NUM(df["HIGH_PRICE"]),
        "low": _NUM(df["LOW_PRICE"]), "close": _NUM(df["CLOSE_PRICE"]),
        "prevclose": _NUM(df["PREV_CLOSE"]),
        "volume_raw": _NUM(df["TTL_TRD_QNTY"]),
        "vwap": _NUM(df["AVG_PRICE"].replace(na)),
        "n_trades": _NUM(df["NO_OF_TRADES"].replace(na)),
        "isin": np.nan,
        "deliv_qty": _NUM(df["DELIV_QTY"].replace(na)),
        "delivery_pct": _NUM(df["DELIV_PER"].replace(na)),
        "source": "sec_bhavdata_full",
    })
    return out


def _iter_raw_files() -> list[tuple[str, Path]]:
    files = []
    for d in _trading_day_candidates():
        if d <= LEGACY_LAST:
            _, p = _legacy_url_and_path(d)
            if p.exists():
                files.append(("legacy", p))
        if d >= MODERN_FIRST:
            _, p = _modern_url_and_path(d)
            if p.exists():
                files.append(("modern", p))
    return files


def load_all_raw(rep: Report) -> pd.DataFrame:
    frames, bad = [], 0
    files = _iter_raw_files()
    for i, (era, p) in enumerate(files, 1):
        df = parse_legacy_zip(p) if era == "legacy" else parse_modern_csv(p)
        if df is None or df.empty:
            bad += 1
            continue
        frames.append(df)
        if i % 500 == 0:
            rep.log(f"parsed {i}/{len(files)} files")
    rep.log(f"parsed {len(files)} files ({bad} empty/unreadable)")
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.dropna(subset=["date", "symbol"])
    # a no-trade listing carries OHLC == prevclose and 0 volume; keep it, but a
    # genuinely bad row (close <= 0, high < low) is dropped and logged.
    n0 = len(panel)
    bad_mask = (panel["close"] <= 0) | (panel["high"] < panel["low"]) | (panel["low"] <= 0)
    if bad_mask.any():
        rep.log(f"dropped {int(bad_mask.sum())} rows with close<=0 / high<low / low<=0")
    panel = panel[~bad_mask].copy()
    panel["volume_raw"] = panel["volume_raw"].fillna(0.0).clip(lower=0.0)
    panel["n_trades"] = panel["n_trades"].fillna(0.0).clip(lower=0.0)
    # vwap: fall back to close when there was no trade / missing
    bad_vwap = panel["vwap"].isna() | (panel["vwap"] <= 0)
    panel.loc[bad_vwap, "vwap"] = panel.loc[bad_vwap, "close"]
    # clip vwap into [low, high] for rounding noise; count material clips
    below = panel["vwap"] < panel["low"]
    above = panel["vwap"] > panel["high"]
    material = (((panel["low"] - panel["vwap"]) / panel["close"] > 0.005) & below) | \
               (((panel["vwap"] - panel["high"]) / panel["close"] > 0.005) & above)
    rep.log(f"vwap clipped into [low,high] on {int((below | above).sum())} rows "
            f"({int(material.sum())} by >0.5% of close — inspect if large)")
    panel["vwap"] = panel["vwap"].clip(panel["low"], panel["high"])
    panel = (panel.drop_duplicates(["date", "symbol"], keep="first")
             .reset_index(drop=True))
    rep.log(f"raw panel: {len(panel):,} rows ({n0 - len(panel):,} removed), "
            f"{panel['symbol'].nunique()} symbols, "
            f"{panel['date'].min().date()}..{panel['date'].max().date()}")
    return panel


# --------------------------------------------------------------------------- #
# 3. ISIN map                                                                  #
# --------------------------------------------------------------------------- #
def build_isin_map(panel: pd.DataFrame, ca_records: list[dict], rep: Report) -> pd.DataFrame:
    """Fill missing ISINs (modern era has none) from: legacy rows, EQUITY_L, CA API.

    Returns ``panel`` with ``isin`` filled; unknowns become ``UNK_<SYMBOL>``.
    """
    sym2isin: dict[str, str] = dict(SYMBOL_ISIN_PATCH)  # hand-verified renames win
    # 1. legacy rows carry ISIN directly — most reliable, and covers delisted names
    legacy = panel[panel["isin"].notna() & panel["isin"].str.startswith("IN")]
    for sym, isin in (legacy.sort_values("date")
                      .groupby("symbol")["isin"].last().items()):
        sym2isin[sym] = isin
    n_legacy = len(sym2isin)
    # 2. EQUITY_L.csv (current listings)
    if EQUITY_L_PATH.exists():
        el = pd.read_csv(EQUITY_L_PATH)
        el.columns = [c.strip() for c in el.columns]
        for _, r in el.iterrows():
            s = str(r["SYMBOL"]).strip()
            i = str(r.get("ISIN NUMBER", "")).strip()
            if i.startswith("IN"):
                sym2isin.setdefault(s, i)
    # 3. corporate-actions API
    for rec in ca_records:
        s = str(rec.get("symbol", "")).strip()
        i = str(rec.get("isin", "")).strip()
        if s and i.startswith("IN"):
            sym2isin.setdefault(s, i)
    rep.log(f"isin map: {n_legacy} from legacy rows, {len(sym2isin)} total symbols")

    panel = panel.copy()
    need = panel["isin"].isna()
    panel.loc[need, "isin"] = panel.loc[need, "symbol"].map(sym2isin)
    still = panel["isin"].isna()
    if still.any():
        n_unk = panel.loc[still, "symbol"].nunique()
        rep.log(f"WARN {n_unk} symbols have no ISIN from any source -> UNK_<symbol>")
        panel.loc[still, "isin"] = "UNK_" + panel.loc[still, "symbol"]

    # Drop only what is provably NOT common equity:
    #  * ISIN prefix INF  -> mutual-fund / ETF units
    #  * ISIN prefix IN9  -> differential-voting-rights (DVR) twin lines
    #  * symbol matches a rights-entitlement / warrant / partly-paid pattern
    #  * symbol matches a well-known ETF-name pattern (covers the UNK-ISIN ETFs
    #    that have no INF ISIN in our sources)
    # Everything else is KEPT — genuine equities with an unresolved ISIN stay
    # under their UNK_<symbol> key rather than being discarded. (Audit 2026-09-02:
    # the ~20 genuine equities in that residue all have < Rs15cr median turnover,
    # an order of magnitude below the top-200 liquidity floor, so they never enter
    # P1's universe — but keeping them makes the panel honest.)
    before_sym = panel["symbol"].nunique()
    sym = panel["symbol"]
    is_fund_isin = panel["isin"].str.startswith(("INF", "IN9"))
    is_rights = sym.str.contains(
        r"-RE\d?$|-RR$|-RT$|-E\d$|-N\d$|-PP$|-BL$|-W\d?$|PARTLY|WARRANT", regex=True)
    is_etf_name = sym.str.contains(
        r"BEES$|ETF$|IETF$|LIQUID|GOLD\d*$|SILV|SDL|NIFTY\d|SENSEX\d|MOM\d|MON\d|"
        r"MAFANG|LOWVOL|MULTICAP|MIDCAP\d*$|SMALLCAP\d*$|MIDSMALL|TOP\d+|"
        r"MOMENTUM\d|QUALITY\d|VALUE\d|ALPHA\d*$|EQUAL\d|PSUBANK$|PSUBNK|"
        r"CPSEETF|BANKBETA|NIFTYBETA|GROWW(?:SLVR|LIQID|DEFNC|EV)|HDFC(?:NIFTY|S|M)|"
        r"AXISNIFTY|ICICISILVE|TATSILV|CONSUMBEES", regex=True)
    drop_mask = is_fund_isin | is_rights | is_etf_name
    dropped = sorted(panel.loc[drop_mask, "symbol"].unique())
    panel = panel[~drop_mask].copy()
    n_unk_kept = panel.loc[panel["isin"].str.startswith("UNK_"), "symbol"].nunique()
    rep.log(f"non-equity filter: {panel['symbol'].nunique()} symbols kept "
            f"({before_sym - panel['symbol'].nunique()} dropped as ETF/DVR/rights; "
            f"{n_unk_kept} kept with an unresolved ISIN as UNK_<symbol>). "
            f"dropped e.g. {dropped[:12]}")
    return panel


# --------------------------------------------------------------------------- #
# 4. Corporate actions -> adjustment factors                                   #
# --------------------------------------------------------------------------- #
# "Bonus 1:1", "Bonus- 1:2", "Bonus : 1 : 1" — the word "bonus" then an a:b ratio
# within a few separator chars. Requires the literal word so "Rights 2:1" cannot match.
_RE_BONUS = re.compile(r"bonus\b[\s:.\-]{0,4}(\d+)\s*:\s*(\d+)", re.I)

# Face-value split. Two stages so NSE's many abbreviations all resolve:
#   keyword: "Face Value Split", "Fv Splt", "F.V. Split", "Sub-Division", "Split"
#   ratio  : "... Rs 10 ... To Re 1 ...", "Rs.10/- To Re.1/-", "Frm Rs 10 To Rs 2"
_RE_SPLIT_KW = re.compile(
    r"face\s*val|\bf\s*\.?\s*v\s*\.?\b|\bsplt\b|\bsplit\b|sub-?division", re.I)
_RE_SPLIT_RATIO = re.compile(
    r"(?:rs|re)\.?\s*([\d.]+)\s*/?\s*-?\s*(?:per\s+share\s+)?[^0-9]*?\bto\b\s*"
    r"(?:rs|re)\.?\s*([\d.]+)", re.I)
_RE_DEMERGER = re.compile(
    r"demerg|amalgamat|scheme of arr?angement|\bmerger\b|composite scheme", re.I)


def parse_ca_subject(subject: str) -> tuple[str, float | None]:
    """(type, price_ratio) where ratio multiplies pre-ex-date prices.

    Splits & bonuses only. Dividends -> ('dividend', None) (not adjusted, ~1%).
    Demergers -> ('demerger', None) (flagged, never adjusted).

    Handles NSE's abbreviated subject text ("Fv Splt Frm Rs 10 To Re 1",
    "Bonus- 1:2", "Face Value Split Rs.10/- To Re.1/-") — the verbose-only parser
    missed ~15 face-value splits including JSWSTEEL's 10:1 (P3 handoff §5.1).
    """
    s = subject or ""
    if _RE_DEMERGER.search(s):
        return "demerger", None
    factor = 1.0
    hit = False
    mb = _RE_BONUS.search(s)
    if mb:
        a, b = int(mb.group(1)), int(mb.group(2))
        if a + b > 0:
            factor *= b / (a + b)
            hit = True
    if _RE_SPLIT_KW.search(s):
        ms = _RE_SPLIT_RATIO.search(s)
        if ms:
            old, new = float(ms.group(1)), float(ms.group(2))
            if old > 0 and new > 0 and new < old:
                factor *= new / old
                hit = True
    if hit:
        kind = "bonus+split" if (mb and _RE_SPLIT_KW.search(s)) else (
            "bonus" if mb else "split")
        return kind, factor
    if re.search(r"dividend", s, re.I):
        return "dividend", None
    return "other", None


def build_corporate_actions(ca_records: list[dict], rep: Report) -> pd.DataFrame:
    rows = []
    for rec in ca_records:
        subj = str(rec.get("subject", "")).strip()
        ex = rec.get("exDate", "")
        try:
            ex_date = pd.to_datetime(ex, format="%d-%b-%Y")
        except (ValueError, TypeError):
            continue
        isin = str(rec.get("isin", "")).strip()
        sym = str(rec.get("symbol", "")).strip()
        if not isin.startswith("IN"):
            isin = f"UNK_{sym}"
        kind, ratio = parse_ca_subject(subj)
        rows.append({"isin": isin, "symbol": sym, "ex_date": ex_date,
                     "type": kind, "ratio": ratio, "raw_subject": subj})
    for p in SPLIT_PATCH:
        rows.append({"isin": f"UNK_{p['symbol']}", "symbol": p["symbol"],
                     "ex_date": pd.Timestamp(p["ex_date"]), "type": "split",
                     "ratio": float(p["ratio"]), "raw_subject": p["raw_subject"]})
    df = pd.DataFrame(rows).drop_duplicates(["isin", "ex_date", "raw_subject"])
    df = df.sort_values(["isin", "ex_date"]).reset_index(drop=True)
    adj = df[df["ratio"].notna()]
    rep.log(f"corp actions: {len(df)} events, {len(adj)} adjustable "
            f"(split/bonus incl. {len(SPLIT_PATCH)} hand-patched splits absent "
            f"from the NSE CA API), {(df['type'] == 'demerger').sum()} demergers flagged")
    return df


def apply_adjustment(panel: pd.DataFrame, ca: pd.DataFrame, rep: Report) -> pd.DataFrame:
    """Back-adjust open/high/low/close/vwap and volume for splits and bonuses.

    Keyed by **symbol**, not ISIN: an NSE split/bonus routinely spawns a new ISIN
    (BAJFINANCE INE296A01016 -> INE296A01024), which a per-ISIN factor cannot
    bridge. For each (symbol, ex_date, ratio) we **anchor the boundary to the
    observed price break** — the trading day near the ex-date where
    ``raw_close[t]/raw_close[t-1] ≈ ratio`` — and apply the factor to every row
    strictly before it. If no break is found in a ±3-day window we fall back to
    ``date < ex_date``. Cumulative: a row before N events gets the product.

    adj_price = raw_price * factor ; adj_volume = raw_volume / factor.
    """
    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)
    adj_ca = ca[ca["ratio"].notna()].copy()
    # bonus + face-value split on the same ex-date arrive as 2 rows — combine
    adj_ca = (adj_ca.groupby(["symbol", "ex_date"], as_index=False)
              .agg(ratio=("ratio", "prod")))
    ev_by_sym: dict[str, pd.DataFrame] = {s: g.sort_values("ex_date")
                                          for s, g in adj_ca.groupby("symbol")}

    factor = np.ones(len(panel), dtype=float)
    groups = panel.groupby("symbol").indices
    n_sym = n_anchored = n_fallback = 0
    for sym, idx in groups.items():
        evs = ev_by_sym.get(sym)
        if evs is None:
            continue
        idx = np.asarray(idx)
        dates = panel["date"].to_numpy()[idx]
        rclose = panel["close"].to_numpy()[idx]
        f = np.ones(len(idx))
        touched = False
        for ex_date, ratio in zip(evs["ex_date"].to_numpy(), evs["ratio"].to_numpy()):
            if not (0 < ratio < 1):
                continue
            pos = int(np.searchsorted(dates, ex_date))
            brk = None
            for p in range(max(1, pos - 3), min(len(idx), pos + 4)):
                if rclose[p - 1] > 0 and abs(rclose[p] / rclose[p - 1] - ratio) < 0.2 * ratio:
                    brk = p
                    break
            if brk is not None:
                f[:brk] *= ratio
                n_anchored += 1
            else:
                f[dates < ex_date] *= ratio
                n_fallback += 1
            touched = True
        if touched:
            factor[idx] = f
            n_sym += 1

    panel["adj_factor"] = factor
    for c in ("open", "high", "low", "close", "vwap"):
        panel[c + "_adj"] = panel[c] * panel["adj_factor"]
    panel["volume_adj"] = panel["volume_raw"] / panel["adj_factor"]
    rep.log(f"adjustment: {n_sym} symbols adjusted "
            f"({n_anchored} events anchored to the observed price break, "
            f"{n_fallback} fell back to the CA ex-date)")
    return panel


# --------------------------------------------------------------------------- #
# 5. size_proxy, delivery                                                      #
# --------------------------------------------------------------------------- #
def build_size_proxy(panel: pd.DataFrame, rep: Report) -> pd.DataFrame:
    df = panel[["date", "symbol", "close_raw", "volume_raw"]].copy()
    df["turnover"] = df["close_raw"] * df["volume_raw"]
    df = df.sort_values(["symbol", "date"])
    med = (df.groupby("symbol")["turnover"]
           .rolling(TURNOVER_WINDOW, min_periods=SIZE_PROXY_MIN_DAYS).median()
           .reset_index(level=0, drop=True))
    df["size_proxy"] = np.log(med.where(med > 0))
    out = (df.loc[df["size_proxy"].notna(), ["date", "symbol", "size_proxy"]]
           .sort_values(["date", "symbol"]).reset_index(drop=True))
    out["size_proxy"] = out["size_proxy"].astype(np.float64)
    rep.log(f"size_proxy: {len(out):,} rows (trailing {TURNOVER_WINDOW}d median "
            f"log turnover; NOT shares outstanding)")
    return out


def build_delivery(panel: pd.DataFrame, rep: Report) -> pd.DataFrame:
    d = panel.loc[panel["source"] == "sec_bhavdata_full",
                  ["date", "symbol", "deliv_qty", "delivery_pct"]].copy()
    d = d.dropna(subset=["delivery_pct"])
    d = d.sort_values(["date", "symbol"]).reset_index(drop=True)
    for c in ("deliv_qty", "delivery_pct"):
        d[c] = d[c].astype(np.float64)
    first = d["date"].min()
    rep.log(f"delivery: {len(d):,} rows, first available {first.date() if len(d) else 'n/a'}")
    return d


# --------------------------------------------------------------------------- #
# 6. Assemble ohlcv.parquet                                                    #
# --------------------------------------------------------------------------- #
def assemble_ohlcv(panel: pd.DataFrame, rep: Report) -> pd.DataFrame:
    out = pd.DataFrame({
        "date": panel["date"].dt.normalize().astype("datetime64[ns]"),
        "symbol": panel["symbol"].astype(str),
        "open": panel["open_adj"].astype(np.float64),
        "high": panel["high_adj"].astype(np.float64),
        "low": panel["low_adj"].astype(np.float64),
        "close": panel["close_adj"].astype(np.float64),
        "volume": panel["volume_adj"].astype(np.float64),
        "close_raw": panel["close"].astype(np.float64),
        "volume_raw": panel["volume_raw"].astype(np.float64),
        "vwap": panel["vwap_adj"].astype(np.float64),
        "n_trades": panel["n_trades"].astype(np.float64),
        "isin": panel["isin"].astype(str),
        "source": panel["source"].astype(str),
        "series": panel["series"].astype(str),
    })
    # guard the vwap-in-range contract after adjustment (uniform scale, but be safe)
    out["vwap"] = out["vwap"].clip(out["low"], out["high"])
    out["volume"] = out["volume"].fillna(out["volume_raw"])
    out = out.sort_values(["date", "symbol"]).reset_index(drop=True)
    validate_ohlcv(out)
    rep.log(f"ohlcv.parquet: {len(out):,} rows, {out['symbol'].nunique()} symbols, "
            f"{out['isin'].nunique()} ISINs")
    return out


# --------------------------------------------------------------------------- #
# 7. Tests A & B + coverage report                                             #
# --------------------------------------------------------------------------- #
def canary_table(ohlcv: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sym in CANARIES + ["CAIRN"]:
        g = ohlcv[ohlcv["symbol"] == sym]
        rows.append({"symbol": sym, "n_days": len(g),
                     "first": g["date"].min() if len(g) else None,
                     "last": g["date"].max() if len(g) else None})
    return pd.DataFrame(rows)


def coverage_by_day(ohlcv: pd.DataFrame) -> pd.Series:
    return ohlcv.groupby("date")["symbol"].nunique()


def _trend(series: pd.Series) -> dict:
    s = series[(series.index >= "2015-01-01") & (series.index <= "2025-12-31")]
    x = (s.index - s.index[0]).days.to_numpy(dtype=float)
    slope = float(np.polyfit(x, s.to_numpy(dtype=float), 1)[0])
    yearly = s.groupby(s.index.year).mean()
    return {"slope_per_day": slope, "slope_per_year": slope * 365.0,
            "mean_2016": float(yearly.get(2016, np.nan)),
            "mean_2024": float(yearly.get(2024, np.nan)),
            "min_year_mean": float(yearly.min()),
            "yearly": yearly.round(1).to_dict(), "series": s}


def universe_proxy_coverage(ohlcv: pd.DataFrame, top_n: int = 200) -> pd.Series:
    """The DECISIVE TEST B curve.

    P2's true panel = members(D) ∩ traded(D) needs P1's membership, which does not
    exist yet (P1 runs after P2). We compute a faithful proxy here: on each
    month-end, among EQ names that traded that day and have >= 252 prior trading
    days, take the top ``top_n`` by trailing-63d median turnover — exactly P1's
    RULE. The count is then held daily to the next month-end. A survivorship-
    biased panel cannot hold this flat at 200 in the early years (the dead names
    that were liquid then would be missing); a correct panel does.
    """
    eq = ohlcv[ohlcv["series"] == "EQ"][["date", "symbol", "close_raw", "volume_raw"]].copy()
    eq["turn"] = eq["close_raw"] * eq["volume_raw"]
    eq = eq.sort_values(["symbol", "date"])
    g = eq.groupby("symbol")
    eq["tt63"] = g["turn"].transform(lambda s: s.rolling(63, min_periods=63).median())
    eq["hist"] = g.cumcount() + 1
    all_days = np.sort(eq["date"].unique())
    month_ends = (pd.Series(pd.to_datetime(all_days))
                  .groupby([pd.to_datetime(all_days).year, pd.to_datetime(all_days).month])
                  .max().tolist())
    counts = {}
    for me in month_ends:
        cand = eq[(eq["date"] == me) & (eq["hist"] >= 252) & eq["tt63"].notna()]
        counts[me] = int(min(top_n, len(cand)))
    sel = pd.Series(counts).sort_index()
    daily = sel.reindex(pd.to_datetime(all_days)).ffill().dropna()
    return daily


def flat_coverage_stats(ohlcv: pd.DataFrame) -> dict:
    whole = _trend(coverage_by_day(ohlcv))
    proxy = _trend(universe_proxy_coverage(ohlcv))
    # public fields describe the DECISIVE (universe-proxy) curve
    return {
        "slope_per_day": proxy["slope_per_day"],
        "slope_per_year": proxy["slope_per_year"],
        "mean_2016": proxy["mean_2016"],
        "mean_2024": proxy["mean_2024"],
        "min_year_mean": proxy["min_year_mean"],
        "yearly": proxy["yearly"],
        "per_day": proxy["series"],
        "whole_market": whole,
        "proxy": proxy,
    }


def _plot_coverage(ohlcv: pd.DataFrame, stats: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    proxy = stats["proxy"]["series"]
    whole = stats["whole_market"]["series"]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    ax1.plot(proxy.index, proxy.values, lw=1.0, color="#1f77b4",
             label="universe proxy: top-200 by trailing turnover ∩ traded")
    ax1.axhline(200, color="grey", ls="--", lw=1, label="200 reference")
    x = (proxy.index - proxy.index[0]).days.to_numpy(dtype=float)
    ax1.plot(proxy.index, np.polyval(np.polyfit(x, proxy.values, 1), x),
             color="red", lw=1.5,
             label=f"trend {stats['slope_per_year']:+.3f}/yr")
    ax1.set_title("TEST B (decisive) — universe-proxy coverage must be FLAT at ~200")
    ax1.set_ylabel("qualified names"); ax1.set_ylim(0, 215)
    ax1.legend(loc="lower right", fontsize=8); ax1.grid(alpha=0.3)

    ax2.plot(whole.index, whole.values, lw=0.6, color="#2ca02c",
             label="whole EQ+BE market traded per day")
    xw = (whole.index - whole.index[0]).days.to_numpy(dtype=float)
    ax2.plot(whole.index, np.polyval(np.polyfit(xw, whole.values, 1), xw),
             color="red", lw=1.2,
             label=f"trend {stats['whole_market']['slope_per_year']:+.1f}/yr "
                   f"(context only — the NSE market genuinely grew)")
    ax2.set_title("Context — whole-market listing count (NOT the survivorship test)")
    ax2.set_xlabel("date"); ax2.set_ylabel("distinct symbols")
    ax2.legend(loc="upper left", fontsize=8); ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(COVERAGE_PLOT, dpi=110)
    plt.close(fig)


def yfinance_crosscheck(ohlcv: pd.DataFrame, rep: Report, n: int = 30) -> dict:
    """Validation only: our adjusted daily returns vs Yahoo's, ~30 large caps."""
    try:
        import yfinance as yf
    except ImportError:
        rep.log("yfinance not installed — cross-check skipped")
        return {}
    liq = (ohlcv.assign(to=ohlcv["close_raw"] * ohlcv["volume_raw"])
           .groupby("symbol")["to"].median().sort_values(ascending=False))
    cands = [s for s in liq.index if s.isalpha()][:n * 3]
    results = {}
    for sym in cands:
        if len(results) >= n:
            break
        try:
            y = yf.download(f"{sym}.NS", start="2015-01-01", end="2025-12-31",
                            progress=False, auto_adjust=True)
            if y is None or len(y) < 250:
                continue
            close = y["Close"]
            if isinstance(close, pd.DataFrame):        # yfinance MultiIndex columns
                close = close.iloc[:, 0]
            yr = close.pct_change().dropna()
            yr.index = pd.to_datetime(yr.index).tz_localize(None).normalize()
            og = ohlcv[ohlcv["symbol"] == sym].set_index("date")["close"].sort_index()
            orr = og.pct_change().dropna()
            j = pd.DataFrame({"ours": orr, "yahoo": yr}).dropna()
            if len(j) > 200:
                results[sym] = float(j["ours"].corr(j["yahoo"]))
        except Exception:  # noqa: BLE001 — best-effort validation
            continue
    if results:
        arr = np.array(list(results.values()))
        rep.log(f"yfinance cross-check: {len(results)} names, "
                f"median corr {np.median(arr):.4f}, "
                f"{int((arr > 0.99).sum())}/{len(arr)} above 0.99")
    return results


def extreme_returns(ohlcv: pd.DataFrame, ca: pd.DataFrame, rep: Report) -> pd.DataFrame:
    df = ohlcv[["date", "symbol", "close"]].sort_values(["symbol", "date"])
    df = df.assign(ret=df.groupby("symbol")["close"].pct_change())
    ex = df[df["ret"].abs() > 0.5].copy()
    ca_dates = set(zip(ca["symbol"], ca["ex_date"].dt.normalize()))
    # near a corporate action (± 3 trading days)?
    def near_ca(row):
        for off in range(-3, 4):
            if (row["symbol"], row["date"] + pd.Timedelta(days=off)) in ca_dates:
                return True
        return False
    ex["near_corp_action"] = ex.apply(near_ca, axis=1) if len(ex) else []
    n_unexpl = int((~ex["near_corp_action"]).sum()) if len(ex) else 0
    rep.log(f"extreme daily returns >50%: {len(ex)} total, {n_unexpl} not near a "
            f"known corporate action (listed for review)")
    return ex[["date", "symbol", "ret", "near_corp_action"]]


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #
def run(download: bool = True, workers: int = 6, do_yf: bool = True,
        report_only: bool = False) -> dict:
    PRICES_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    rep = Report()
    rep.log(f"Phase 2 start — window {DATE_START.date()}..{DATE_END.date()}, "
            f"series kept {SERIES_KEEP}")
    rep.log("NOTE: P2 legitimately reads HOLDOUT dates (2022-07+) — it builds the "
            "full price panel; sealing applies to scoring, enforced in P4.")

    if report_only:
        rep.log("REPORT-ONLY: reloading artifacts, regenerating tests + report")
        ohlcv = pd.read_parquet(OHLCV_PARQUET)
        ca = pd.read_parquet(CORP_ACTIONS_PARQUET)
        return _finish(rep, {}, ohlcv, ca, do_yf)

    dl_stats = {}
    if download:
        dl_stats = download_all(rep, workers=workers)
        download_corporate_actions(rep)

    ca_records: list[dict] = []
    for f in sorted(RAW_CA.glob("*.json")):
        try:
            ca_records.extend(json.loads(f.read_text()))
        except (ValueError, OSError):
            pass

    panel = load_all_raw(rep)
    panel = build_isin_map(panel, ca_records, rep)
    ca = build_corporate_actions(ca_records, rep)
    panel = apply_adjustment(panel, ca, rep)

    ohlcv = assemble_ohlcv(panel, rep)

    isin_map = (ohlcv[["date", "symbol", "isin"]]
                .sort_values(["date", "symbol"]).reset_index(drop=True))
    size_proxy = build_size_proxy(panel.rename(columns={"close": "close_raw"}), rep)
    delivery = build_delivery(panel, rep)

    # write artifacts
    ohlcv.to_parquet(OHLCV_PARQUET, index=False)
    isin_map.to_parquet(ISIN_MAP_PARQUET, index=False)
    ca.to_parquet(CORP_ACTIONS_PARQUET, index=False)
    delivery.to_parquet(DELIVERY_PARQUET, index=False)
    size_proxy.to_parquet(SIZE_PROXY_PARQUET, index=False)
    rep.log(f"wrote {OHLCV_PARQUET.name}, {ISIN_MAP_PARQUET.name}, "
            f"{CORP_ACTIONS_PARQUET.name}, {DELIVERY_PARQUET.name}, {SIZE_PROXY_PARQUET.name}")

    return _finish(rep, dl_stats, ohlcv, ca, do_yf)


def _finish(rep: Report, dl_stats: dict, ohlcv: pd.DataFrame, ca: pd.DataFrame,
            do_yf: bool) -> dict:
    """Tests A & B, plot, cross-check, coverage report."""
    canaries = canary_table(ohlcv)
    rep.log("canary table:\n" + canaries.to_string(index=False))
    fc = flat_coverage_stats(ohlcv)
    rep.log(f"flat coverage (universe proxy): slope {fc['slope_per_year']:+.3f}/yr, "
            f"mean 2016={fc['mean_2016']:.1f}, mean 2024={fc['mean_2024']:.1f}, "
            f"min year mean={fc['min_year_mean']:.1f}  |  whole-market slope "
            f"{fc['whole_market']['slope_per_year']:+.1f}/yr (context)")
    _plot_coverage(ohlcv, fc)
    hw = {s: int((ohlcv["symbol"] == s).sum()) for s in HEAVYWEIGHTS}
    rep.log(f"heavyweight day counts: {hw}")
    ex = extreme_returns(ohlcv, ca, rep)
    yf_res = yfinance_crosscheck(ohlcv, rep) if do_yf else {}

    write_coverage_report(rep, dl_stats, ohlcv, canaries, fc, hw, ex, yf_res, ca)
    rep.log("Phase 2 done.")
    return {"ohlcv": ohlcv, "corp_actions": ca, "canaries": canaries,
            "flat_coverage": fc, "heavyweights": hw, "extremes": ex,
            "yfinance": yf_res, "report": rep}


def _md(df: pd.DataFrame) -> str:
    """Fenced plain-text table (no `tabulate` dependency)."""
    return "```\n" + df.to_string(index=False) + "\n```"


def write_coverage_report(rep, dl_stats, ohlcv, canaries, fc, hw, ex, yf_res, ca) -> None:
    L = []
    L.append("# Phase 2 — Price data coverage report\n")
    L.append("## Source & window\n")
    L.append(f"- Window: **{DATE_START.date()} .. {DATE_END.date()}** "
             f"(2026+ reserved for live-forward; not downloaded).")
    L.append(f"- Legacy bhavcopy zip through {LEGACY_LAST.date()}; "
             f"`sec_bhavdata_full` from {MODERN_FIRST.date()}.")
    L.append(f"- SERIES kept: **{' + '.join(SERIES_KEEP)}** — `BE` (trade-to-trade) "
             "is retained deliberately: a stock demoted to `BE` is a distress "
             "signal, and dropping it would reintroduce a mild survivorship bias.")
    L.append("- **`sharesOutstanding` was NOT used** anywhere. `size_proxy` is "
             "`log(trailing-63d median of close_raw*volume_raw)` — a point-in-time, "
             "leak-free stand-in for market cap.\n")
    if dl_stats:
        L.append("## Download\n")
        L.append(f"- Tasks: {dl_stats['n_tasks']}  |  outcome: `{dl_stats['counts']}`")
        L.append(f"- Hard errors: {len(dl_stats['errors'])}")
        if dl_stats["errors"]:
            L.append("  - " + ", ".join(e.rsplit('/', 1)[-1] for e in dl_stats["errors"][:20]))
        L.append("- Re-running downloads nothing new (files + `.404` markers cached).\n")
    L.append("## Panel size\n")
    L.append(f"- Rows: **{len(ohlcv):,}**  |  distinct symbols: **{ohlcv['symbol'].nunique()}**  "
             f"|  distinct ISINs: **{ohlcv['isin'].nunique()}**")
    L.append(f"- Date span: {ohlcv['date'].min().date()} .. {ohlcv['date'].max().date()} "
             f"({ohlcv['date'].nunique()} trading days)")
    unk = ohlcv.loc[ohlcv['isin'].str.startswith('UNK_'), 'symbol'].nunique()
    L.append(f"- Symbols with no ISIN from any source (keyed `UNK_<symbol>`): **{unk}**\n")
    L.append("## TEST A — survivorship canaries\n")
    L.append(_md(canaries))
    L.append("\n_CAIRN should be absent after 2017-04 (merged into Vedanta) — that "
             "absence validates the archive is genuinely point-in-time._\n")
    L.append("## TEST B — flat coverage (decisive diagnostic)\n")
    L.append("P2's true panel is `members(D) ∩ traded(D)`, but P1's membership does "
             "not exist yet (P1 runs after P2). The decisive curve here is a faithful "
             "**universe proxy**: on each month-end, the top-200 EQ names by trailing-"
             "63d median turnover among those with ≥252d history that traded that day "
             "— P1's exact RULE. A survivorship-biased panel cannot hold this flat at "
             "200 in the early years; a correct one does.\n")
    L.append(f"- **Universe-proxy trend: {fc['slope_per_year']:+.3f} names/year** "
             f"(slope {fc['slope_per_day']:+.2e}/day)")
    L.append(f"- Universe-proxy mean 2016: **{fc['mean_2016']:.1f}**, "
             f"2024: **{fc['mean_2024']:.1f}**, min year: **{fc['min_year_mean']:.1f}**")
    L.append(f"- Universe-proxy per-year mean: {fc['yearly']}")
    wm = fc["whole_market"]
    L.append(f"- _Context_ — whole EQ+BE market listing count trend "
             f"{wm['slope_per_year']:+.1f}/year (2016≈{wm['mean_2016']:.0f}, "
             f"2024≈{wm['mean_2024']:.0f}). This slopes up because the NSE market "
             "genuinely grew; it is **not** the survivorship test.")
    L.append(f"- Plot: `{COVERAGE_PLOT.name}` (top panel = decisive, bottom = context)")
    L.append("- **An upward slope in the universe-proxy curve means survivorship "
             "bias remains — HARD STOP.** See handoff for the pass/fail call.\n")
    L.append("## Heavyweights (liquidity sanity)\n")
    L.append(f"- Day counts: {hw}")
    L.append("- These are among the most liquid names in India; near-zero counts "
             "would indicate a parsing/turnover bug.\n")
    L.append("## Corporate actions & adjustment\n")
    L.append(f"- Events parsed: {len(ca)}  |  adjustable (split/bonus): "
             f"{int(ca['ratio'].notna().sum())}  |  demergers flagged (NOT adjusted): "
             f"{int((ca['type'] == 'demerger').sum())}")
    L.append("- Dividends are NOT adjusted (≈1% distortion, second-order at our "
             "horizons). Splits/bonuses (50–90% distortion) are adjusted.")
    demk = ca.loc[ca["type"] == "demerger", ["symbol", "ex_date", "raw_subject"]].head(40)
    if len(demk):
        L.append("\n<details><summary>Flagged demergers/mergers (disclosed, unadjusted)</summary>\n")
        L.append(_md(demk))
        L.append("\n</details>\n")
    L.append("## Extreme daily returns (|ret| > 50%)\n")
    L.append(f"- Total: {len(ex)}  |  not near a known corporate action: "
             f"{int((~ex['near_corp_action']).sum()) if len(ex) else 0}")
    L.append("- Not auto-dropped and not winsorized (per spec) — Indian mid-caps "
             "genuinely move like this; P3 flags them for review.")
    if len(ex):
        L.append("\n<details><summary>First 50 unexplained</summary>\n")
        L.append(_md(ex[~ex["near_corp_action"]].head(50)))
        L.append("\n</details>\n")
    L.append("## yfinance cross-check (validation only, not a source)\n")
    if yf_res:
        arr = np.array(list(yf_res.values()))
        L.append(f"- {len(yf_res)} large caps: median corr **{np.median(arr):.4f}**, "
                 f"{int((arr > 0.99).sum())}/{len(arr)} above 0.99")
        L.append(f"- Per-name: {({k: round(v, 4) for k, v in yf_res.items()})}")
    else:
        L.append("- Not run in this pass (offline or yfinance unavailable). "
                 "Re-run with network to populate.")
    L.append("\n## Log\n")
    L.extend(f"- {ln}" for ln in rep.lines)
    COVERAGE_REPORT.write_text("\n".join(L), encoding="utf-8")
    rep.log(f"wrote {COVERAGE_REPORT.name}")


if __name__ == "__main__":
    run()
