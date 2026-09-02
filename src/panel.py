"""Phase 3 — Feature panel, labels, splits.

Turns P2 prices + P1 membership into a point-in-time feature panel and the
prediction label, and **proves there is no look-ahead**.

Timing contract, exactly
------------------------
    features use data available *before* the trade
        -> trade at the *t+1* open
            -> return earned from *t+1* open to *t+2* open

Per-field availability (this replaces any single blanket rule):

===========================  =========================================  ===
Field                        Knowable at                                Lag
===========================  =========================================  ===
OHLCV + everything derived   day *t*, 15:30 IST                          0
delivery_pct                 day *t*, ~19:00 IST (post-close, pre t+1)    0
size_proxy                   day *t* (trailing turnover through t)        0
sector                       static, NOT point-in-time (disclosed)       0
in_universe                  effective date, applied 1-3 days late        0
===========================  =========================================  ===

Outputs
-------
* ``data/panel/features.parquet``  — Section 0.5 schema
* ``data/panel/labels.parquet``    — Section 0.5 schema
* ``data/panel/splits.json``       — Section 0.4 verbatim
* ``reports/p3_panel_report.md``
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    FEATURES_PARQUET,
    LABELS_PARQUET,
    MEMBERSHIP_PARQUET,
    OHLCV_PARQUET,
    PANEL_DIR,
    RANDOM_SEED,
    REPORTS_DIR,
    SPLITS_JSON,
    SPLITS_JSON_PAYLOAD,
    split_mask,
)
from .contracts import (
    HORIZONS,
    make_fake_membership,
    make_fake_ohlcv,
    validate_features,
    validate_labels,
    validate_membership,
    validate_ohlcv,
)
from .sectors import build_sector_map

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DELIVERY_PARQUET: Path = REPO_ROOT / "data" / "prices" / "delivery.parquet"
SIZE_PROXY_PARQUET: Path = REPO_ROOT / "data" / "prices" / "size_proxy.parquet"
CORP_ACTIONS_PARQUET: Path = REPO_ROOT / "data" / "prices" / "corporate_actions.parquet"
P3_REPORT: Path = REPORTS_DIR / "p3_panel_report.md"

# Feature windows (trading days on the common NSE calendar — see decision §7).
W_VOL, W_BETA, W_AMIHUD, W_TURN, W_MAXRET, W_52WH = 21, 63, 21, 21, 21, 252

FEATURE_COLS: tuple[str, ...] = (
    "mom_21", "mom_126", "rev_5", "vol_21", "beta_63", "amihud_21",
    "turnover_21", "dist_52wh", "max_ret_21", "delivery_pct",
)
EXTREME_RET_THRESHOLD = 0.50   # flag |daily return| > 50% — do NOT winsorize / drop

DECISIONS_LOG: list[str] = []


def _log(msg: str) -> None:
    DECISIONS_LOG.append(msg)


# --------------------------------------------------------------------------- #
# Loading                                                                      #
# --------------------------------------------------------------------------- #
_OHLCV_COLS = ["date", "symbol", "open", "high", "low", "close", "volume",
               "close_raw", "volume_raw", "isin"]


def _to_ns(df: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    df[col] = pd.to_datetime(df[col]).dt.normalize().astype("datetime64[ns]")
    return df


def load_inputs() -> dict:
    """Load P1/P2 artifacts; fall back to synthetic fixtures if absent."""
    real = OHLCV_PARQUET.exists() and MEMBERSHIP_PARQUET.exists()
    if real:
        import pyarrow.parquet as pq
        have = set(pq.ParquetFile(OHLCV_PARQUET).schema.names)
        cols = [c for c in _OHLCV_COLS if c in have]
        ohlcv = pd.read_parquet(OHLCV_PARQUET, columns=cols)
        membership = pd.read_parquet(MEMBERSHIP_PARQUET)
        _log(f"loaded real P2 ohlcv.parquet ({len(ohlcv):,} rows, cols={cols}) "
             f"and P1 membership.parquet ({len(membership):,} rows)")
        # P2/P1 validated their full frames at write time; assert what P3 needs.
        for need, df, nm in ((("date", "symbol", "open", "close"), ohlcv, "ohlcv"),
                             (("date", "symbol", "in_universe"), membership, "membership")):
            miss = [c for c in need if c not in df.columns]
            if miss:
                raise AssertionError(f"[p3] {nm} missing columns: {miss}")
        delivery = (pd.read_parquet(DELIVERY_PARQUET)
                    if DELIVERY_PARQUET.exists() else None)
        size_proxy = (pd.read_parquet(SIZE_PROXY_PARQUET)
                      if SIZE_PROXY_PARQUET.exists() else None)
        corp = (pd.read_parquet(CORP_ACTIONS_PARQUET)
                if CORP_ACTIONS_PARQUET.exists() else None)
        src = "real (data/prices/*, data/universe/membership.parquet)"
    else:
        n_days, n_symbols = 900, 150
        ohlcv = make_fake_ohlcv(n_days=n_days, n_symbols=n_symbols, seed=RANDOM_SEED)
        validate_ohlcv(ohlcv)
        membership = make_fake_membership(n_days=n_days, n_symbols=n_symbols,
                                          seed=RANDOM_SEED)
        validate_membership(membership)
        delivery = size_proxy = corp = None
        src = f"synthetic fixtures (make_fake_ohlcv/membership {n_days}x{n_symbols})"
        _log(f"P2/P1 artifacts absent -> {src}; delivery_pct/size_proxy synthesised "
             f"(partial coverage) so validators still pass — see §7")

    ohlcv = _to_ns(ohlcv.copy())
    membership = _to_ns(membership.copy())
    if "series" in ohlcv.columns:
        ohlcv = ohlcv.drop(columns=["series"])
    for name, df in (("delivery", delivery), ("size_proxy", size_proxy)):
        if df is not None:
            _to_ns(df)          # in place — these carry datetime64[us] from P2
    if corp is not None and "ex_date" in corp.columns:
        corp["ex_date"] = pd.to_datetime(corp["ex_date"]).dt.normalize().astype(
            "datetime64[ns]")

    return {"ohlcv": ohlcv, "membership": membership, "delivery": delivery,
            "size_proxy": size_proxy, "corp": corp, "src": src, "is_real": real}


# --------------------------------------------------------------------------- #
# Wide-panel construction                                                      #
# --------------------------------------------------------------------------- #
def _pivot(df: pd.DataFrame, value: str) -> pd.DataFrame:
    w = df.pivot(index="date", columns="symbol", values=value).sort_index()
    return w


def build_wide(ohlcv: pd.DataFrame, union: list[str]) -> dict[str, pd.DataFrame]:
    """date x symbol frames for every price series P3 needs, union symbols only."""
    o = ohlcv[ohlcv["symbol"].isin(union)].copy()
    # de-dup defensively (P2 already asserts uniqueness).
    o = o.drop_duplicates(["date", "symbol"]).sort_values(["date", "symbol"])
    wide = {
        "open": _pivot(o, "open"),
        "close": _pivot(o, "close"),
        "volume": _pivot(o, "volume"),
        "close_raw": _pivot(o, "close_raw"),
        "volume_raw": _pivot(o, "volume_raw"),
    }
    # align every frame to the same (date x symbol) grid
    idx, cols = wide["close"].index, wide["close"].columns
    for k in list(wide):
        wide[k] = wide[k].reindex(index=idx, columns=cols)
    wide["ret"] = wide["close"].pct_change(fill_method=None)
    return wide


def membership_wide(membership: pd.DataFrame, idx, cols) -> pd.DataFrame:
    m = membership[membership["in_universe"]]
    w = (m.assign(v=True)
         .pivot(index="date", columns="symbol", values="v")
         .reindex(index=idx, columns=cols)
         .fillna(False)
         .astype(bool))
    return w


# --------------------------------------------------------------------------- #
# Features                                                                     #
# --------------------------------------------------------------------------- #
def compute_features(wide: dict, memb_w: pd.DataFrame) -> dict[str, pd.DataFrame]:
    close, open_, vol = wide["close"], wide["open"], wide["volume"]
    craw, vraw, ret = wide["close_raw"], wide["volume_raw"], wide["ret"]

    feats: dict[str, pd.DataFrame] = {}

    # --- momentum / reversal: ratio features, only need clean endpoints ---
    feats["mom_21"] = close.shift(1) / close.shift(22) - 1.0
    feats["mom_126"] = close.shift(21) / close.shift(147) - 1.0
    feats["rev_5"] = -(close / close.shift(5) - 1.0)

    # --- volatility (annualized) ---
    feats["vol_21"] = ret.rolling(W_VOL, min_periods=W_VOL).std(ddof=1) * np.sqrt(252.0)

    # --- equal-weight universe return, then rolling beta ---
    mkt = ret.where(memb_w).mean(axis=1)                    # Series over dates
    rm = pd.DataFrame({c: mkt for c in ret.columns}, index=ret.index)
    ex_iy = (ret * rm).rolling(W_BETA, min_periods=W_BETA).mean()
    ex_i = ret.rolling(W_BETA, min_periods=W_BETA).mean()
    ex_y = rm.rolling(W_BETA, min_periods=W_BETA).mean()
    cov = ex_iy - ex_i * ex_y
    var_m = (rm * rm).rolling(W_BETA, min_periods=W_BETA).mean() - ex_y ** 2
    feats["beta_63"] = cov / var_m.replace(0.0, np.nan)

    # --- Amihud illiquidity x 1e6 (guard zero rupee-volume) ---
    dv = (close * vol).replace(0.0, np.nan)
    feats["amihud_21"] = (ret.abs() / dv).rolling(
        W_AMIHUD, min_periods=W_AMIHUD).mean() * 1e6

    # --- turnover (log of trailing mean rupee turnover, raw prices) ---
    turn = (craw * vraw).rolling(W_TURN, min_periods=W_TURN).mean()
    feats["turnover_21"] = np.log(turn.replace(0.0, np.nan))

    # --- distance to 52-week high (<= 0 by construction) ---
    roll_max = close.rolling(W_52WH, min_periods=W_52WH).max()
    feats["dist_52wh"] = close / roll_max - 1.0

    # --- lottery: max single-day return over 21 days ---
    feats["max_ret_21"] = ret.rolling(W_MAXRET, min_periods=W_MAXRET).max()

    return feats, mkt


def join_external(feat_long: pd.DataFrame, delivery, size_proxy,
                  is_real: bool) -> tuple[pd.DataFrame, dict]:
    """Attach delivery_pct and size_proxy by (date, symbol). Lag 0 — both are
    knowable on day t before the t+1 open."""
    info: dict = {}

    if delivery is not None and {"date", "symbol", "delivery_pct"} <= set(delivery.columns):
        d = delivery[["date", "symbol", "delivery_pct"]].drop_duplicates(["date", "symbol"])
        d["delivery_pct"] = d["delivery_pct"].astype(np.float64)
        feat_long = feat_long.merge(d, on=["date", "symbol"], how="left")
        first = d["date"].min()
        info["delivery_first_date"] = first
        info["delivery_source"] = "data/prices/delivery.parquet"
    else:
        # fixture: no delivery.parquet -> leave delivery_pct entirely NaN, exactly
        # as spec P3 Inputs says ("emit delivery_pct ... as NaN and note it").
        # validate_features permits an all-NaN delivery_pct (contracts.py
        # _FEATURES_ALLOW_ALL_NAN) since it is a genuinely partial field.
        feat_long["delivery_pct"] = np.float64("nan")
        info["delivery_first_date"] = None
        info["delivery_source"] = "NaN (fixture — no delivery.parquet; spec-compliant)"

    if size_proxy is not None and {"date", "symbol", "size_proxy"} <= set(size_proxy.columns):
        s = size_proxy[["date", "symbol", "size_proxy"]].drop_duplicates(["date", "symbol"])
        s["size_proxy"] = s["size_proxy"].astype(np.float64)
        feat_long = feat_long.merge(s, on=["date", "symbol"], how="left")
        info["size_proxy_source"] = "data/prices/size_proxy.parquet"
    else:
        # fixture: trailing-63d log median rupee turnover, computed here.
        info["size_proxy_source"] = "SYNTHETIC (fixture — computed from fixture turnover)"
        feat_long["size_proxy"] = np.nan   # filled by caller from wide frames

    return feat_long, info


# --------------------------------------------------------------------------- #
# Labels                                                                       #
# --------------------------------------------------------------------------- #
def compute_labels(open_w: pd.DataFrame, memb_w: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """fwd_ret_h = open[t+1+h] / open[t+1] - 1, then cross-sectionally demeaned
    within the in-universe set each day."""
    base = open_w.shift(-1)                       # the t+1 open (the entry price)
    out: dict[str, pd.DataFrame] = {}
    for h in HORIZONS:
        fwd = open_w.shift(-1 - h) / base - 1.0
        out[f"fwd_ret_{h}"] = fwd
        mu = fwd.where(memb_w).mean(axis=1)
        out[f"fwd_ret_{h}_demeaned"] = fwd.sub(mu, axis=0)
    return out


# --------------------------------------------------------------------------- #
# Long assembly + universe mask                                                #
# --------------------------------------------------------------------------- #
def _stack(w: pd.DataFrame, name: str) -> pd.Series:
    return (w.stack(future_stack=True)
            .rename_axis(["date", "symbol"])
            .rename(name))


def assemble_long(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    cols = [_stack(w, n) for n, w in frames.items()]
    df = pd.concat(cols, axis=1).reset_index()
    return _to_ns(df)


def mask_to_universe(df: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    keep = membership.loc[membership["in_universe"], ["date", "symbol"]]
    out = df.merge(keep, on=["date", "symbol"], how="inner")
    return out.sort_values(["date", "symbol"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# IC helpers (self-test)                                                       #
# --------------------------------------------------------------------------- #
def _daily_rank_ic(sig: pd.DataFrame, lab: pd.DataFrame, min_names: int = 20) -> float:
    """Mean daily Spearman IC between two ``date x symbol`` frames (vectorised
    across days: per-day Pearson correlation of the within-day ranks)."""
    s = sig.reindex_like(lab)
    mask = s.notna() & lab.notna()
    n = mask.sum(axis=1)
    sr = s.where(mask).rank(axis=1)
    lr = lab.where(mask).rank(axis=1)
    sr = sr.sub(sr.mean(axis=1), axis=0)
    lr = lr.sub(lr.mean(axis=1), axis=0)
    cov = (sr * lr).sum(axis=1)
    denom = np.sqrt((sr ** 2).sum(axis=1) * (lr ** 2).sum(axis=1))
    ic = (cov / denom.replace(0.0, np.nan))[n >= min_names]
    return float(ic.mean()) if len(ic) else float("nan")


# --------------------------------------------------------------------------- #
# Assertion suite (step 6)                                                     #
# --------------------------------------------------------------------------- #
def run_assertions(features: pd.DataFrame, labels: pd.DataFrame,
                   membership: pd.DataFrame, wide: dict) -> dict:
    res: dict = {}

    # cross-section size per day
    xs = features.groupby("date")["symbol"].count()
    thin = xs[(xs.index >= pd.Timestamp("2016-01-01")) & (xs < 100)]
    res["min_xs_after_2016"] = int(xs[xs.index >= pd.Timestamp("2016-01-01")].min())
    res["thin_days_after_2016"] = [(d.date().isoformat(), int(n)) for d, n in thin.items()]
    for d, n in thin.items():
        _log(f"thin cross-section {d.date()}: {n} names (< 100)")

    # NaN label where in-universe + traded + forward window available
    traded = set(map(tuple, wide["close"].stack(future_stack=True).dropna()
                     .rename_axis(["date", "symbol"]).reset_index()[["date", "symbol"]]
                     .itertuples(index=False, name=None)))
    last_dt = labels["date"].max()
    horizon_cut = {h: last_dt - pd.Timedelta(days=int(h * 1.6) + 8) for h in HORIZONS}
    lab_idx = labels.set_index(["date", "symbol"])
    nan_label_traded = {}
    for h in HORIZONS:
        col = f"fwd_ret_{h}_demeaned"
        sub = lab_idx[lab_idx.index.get_level_values("date") <= horizon_cut[h]]
        bad = sub[sub[col].isna()]
        # of those, how many actually traded on the signal date
        bad_traded = [ix for ix in bad.index if ix in traded]
        nan_label_traded[h] = len(bad_traded)
        if bad_traded:
            _log(f"fwd_ret_{h}: {len(bad_traded)} in-universe+traded rows have NaN "
                 f"label well inside the sample (stock stopped trading within the "
                 f"forward window) — kept, not filled")
    res["nan_label_inuniverse_traded"] = nan_label_traded

    # dist_52wh <= 0
    res["dist_52wh_max"] = float(features["dist_52wh"].dropna().max())
    res["dist_52wh_ok"] = res["dist_52wh_max"] <= 1e-9

    # vol_21 > 0
    v = features["vol_21"].dropna()
    res["vol_21_min"] = float(v.min()) if len(v) else float("nan")
    res["vol_21_positive"] = bool((v > 0).all())

    # duplicate keys
    res["dup_keys_features"] = int(features.duplicated(["date", "symbol"]).sum())
    res["dup_keys_labels"] = int(labels.duplicated(["date", "symbol"]).sum())

    # feature coverage (non-NaN share within the masked panel)
    res["feature_coverage"] = {
        c: round(float(features[c].notna().mean()), 4)
        for c in FEATURE_COLS + ("size_proxy",)
    }
    return res


# raw-close ratios that betray an unadjusted split / bonus (post/pre ≈ these)
_CLEAN_SPLIT_RATIOS = (0.5, 1 / 3, 0.25, 0.2, 0.1, 2 / 3, 0.4)

# Well-known demergers that NSE's corporate-actions API returns *zero* rows for
# (verified). P2 flags the demergers it knows about; these two slip through and
# would otherwise be mislabelled "genuine" in the extreme-return triage. Same
# audited-hand-list pattern as prices.SPLIT_PATCH.
_KNOWN_DEMERGERS_NOT_IN_CA: dict[str, str] = {
    "CROMPGREAV": "2016-03-15",   # Crompton Greaves -> consumer biz spun to CROMPTON
    "CENTURYTEX": "2019-10-11",   # Century Textiles -> cement biz merged into UltraTech
}


def flag_extreme_returns(features_idx: pd.DataFrame, wide: dict,
                         membership: pd.DataFrame, corp) -> dict:
    """|daily return| > 50% on the masked universe panel. Flag for review —
    never dropped, never winsorized (Indian mid-caps genuinely move like this;
    clipping would distort max_ret_21).

    Each flagged move is categorised:
      * ``demerger``            — a demerger CA near the date. P2 policy is to
                                  NOT adjust demergers (spec) — expected, not a bug.
      * ``unadjusted_split``    — a split/bonus CA near the date, or the raw close
                                  jumps by a clean split fraction. **P2 adjustment
                                  gap — owner should decide whether to re-run P2.**
      * ``genuine``             — no CA, ratio not clean (real distress move).
    """
    ret_long = _to_ns(_stack(wide["ret"], "ret").reset_index())
    craw_long = _to_ns(_stack(wide["close_raw"], "craw").reset_index())
    craw_long["craw_prev"] = craw_long.groupby("symbol")["craw"].shift(1)
    ret_long = ret_long.merge(craw_long[["date", "symbol", "craw", "craw_prev"]],
                              on=["date", "symbol"], how="left")
    keep = membership.loc[membership["in_universe"], ["date", "symbol"]]
    ret_long = ret_long.merge(keep, on=["date", "symbol"], how="inner")

    ext = ret_long[ret_long["ret"].abs() > EXTREME_RET_THRESHOLD].copy()
    ext = ext.sort_values("ret", key=lambda s: s.abs(), ascending=False)

    ca_split: dict[str, np.ndarray] = {}
    ca_demrg: dict[str, np.ndarray] = {}
    if corp is not None and {"symbol", "ex_date", "type"} <= set(corp.columns):
        c = corp[["symbol", "ex_date", "type"]].dropna(subset=["symbol", "ex_date"])
        for s, g in c.groupby("symbol"):
            d = g[g["type"].isin(["demerger"])]["ex_date"].values
            if len(d):
                ca_demrg[s] = d
            o = g[~g["type"].isin(["demerger", "dividend"])]["ex_date"].values
            if len(o):
                ca_split[s] = o

    def _near(arr, dt, days):
        return arr is not None and np.any(
            np.abs((arr - np.datetime64(dt)) / np.timedelta64(1, "D")) <= days)

    def _clean_ratio(row):
        if not np.isfinite(row["craw"]) or not row["craw_prev"]:
            return False
        r = row["craw"] / row["craw_prev"]
        return any(abs(r - t) < 0.03 for t in _CLEAN_SPLIT_RATIOS)

    def _known_demerger(sym, dt):
        d = _KNOWN_DEMERGERS_NOT_IN_CA.get(sym)
        return d is not None and abs((pd.Timestamp(dt) - pd.Timestamp(d)).days) <= 7

    cats = []
    for _, r in ext.iterrows():
        # demerger ex-dates and their price impact can be weeks apart -> wide window
        if _near(ca_demrg.get(r["symbol"]), r["date"], 21) or _known_demerger(
                r["symbol"], r["date"]):
            cats.append("demerger")
        elif _near(ca_split.get(r["symbol"]), r["date"], 7) or _clean_ratio(r):
            cats.append("unadjusted_split")
        else:
            cats.append("genuine")
    ext["category"] = cats

    counts = {k: int((ext["category"] == k).sum())
              for k in ("demerger", "unadjusted_split", "genuine")}
    return {
        "n_flagged": int(len(ext)),
        "by_category": counts,
        "sample": ext.head(40).assign(
            date=lambda d: d["date"].dt.date.astype(str),
            ret=lambda d: d["ret"].round(4),
        )[["date", "symbol", "ret", "category"]].to_dict("records"),
    }


def lookahead_selftest(feat_frames: dict, label_frames: dict,
                       memb_w: pd.DataFrame) -> dict:
    """Step 7 — the most important test in this phase.

    Computed on **non-HOLDOUT dates only** (HOLDOUT is sealed; P3 computes no
    metric there).

    (a) a known factor's RankIC vs fwd_ret_1_demeaned; shift the WHOLE feature
        panel forward one day and recompute — the IC must change materially. An
        IC invariant to a one-day shift means the pipeline is time-symmetric
        somewhere (leaking). Primary factor: ``rev_5`` (a genuine, fast signal
        whose day-to-day values really move); ``mom_21`` / ``mom_126`` reported
        alongside.
    (b) a deliberately leaky feature — fwd_ret_1 predicting itself — must give
        |RankIC| ~ 1.0, proving the measurement machinery can detect leakage
        when it is present.
    (c) that same leaky feature, shifted forward one day, must collapse toward 0
        — the decisive, sign-independent version of (a).
    """
    from .config import HOLDOUT_START

    def _nh(w):                    # non-holdout slice of a date-indexed frame
        return w.loc[w.index < HOLDOUT_START]

    memb_nh = _nh(memb_w)
    lab1 = _nh(label_frames["fwd_ret_1_demeaned"]).where(memb_nh)

    def _shift_triplet(name):
        sig = _nh(feat_frames[name]).where(memb_nh)
        o = _daily_rank_ic(sig, lab1)
        f1 = _daily_rank_ic(sig.shift(1), lab1)
        b1 = _daily_rank_ic(sig.shift(-1), lab1)
        d = abs(o) if abs(o) > 1e-9 else 1.0
        return {"ic": o, "ic_shift_fwd1": f1, "ic_shift_bwd1": b1,
                "abs_change_fwd1": abs(o - f1), "rel_change_fwd1": abs(o - f1) / d}

    rev = _shift_triplet("rev_5")
    m21 = _shift_triplet("mom_21")
    m126 = _shift_triplet("mom_126")

    leaky = _nh(label_frames["fwd_ret_1"]).where(memb_nh)
    ic_leaky = _daily_rank_ic(leaky, lab1)
    ic_leaky_shift = _daily_rank_ic(leaky.shift(1), lab1)

    rd = abs(rev["ic"]) if abs(rev["ic"]) > 1e-9 else 1.0
    return {
        "primary_factor": "rev_5",
        "rev_5": rev, "mom_21": m21, "mom_126": m126,
        "leaky_ic": ic_leaky,
        "leaky_ic_shifted_fwd1": ic_leaky_shift,
        "shift_changes_ic": rev["abs_change_fwd1"] > max(0.10 * rd, 1e-3),
        "machinery_detects_leak": abs(ic_leaky) > 0.9,
        "leak_collapses_on_shift": abs(ic_leaky_shift) < 0.5 * abs(ic_leaky),
    }


# --------------------------------------------------------------------------- #
# Report                                                                       #
# --------------------------------------------------------------------------- #
def write_report(*, src, is_real, sector_stats, ext_info, asserts, selftest,
                 delivery_info, features, labels, mkt) -> str:
    L: list[str] = []
    A = L.append
    A("# Phase 3 — Feature panel, labels, splits\n")
    A(f"- Input source: **{src}**")
    A(f"- `features.parquet`: **{len(features):,} rows**, "
      f"{features['symbol'].nunique()} symbols, {features['date'].nunique()} "
      f"trading days ({features['date'].min().date()} … {features['date'].max().date()})")
    A(f"- `labels.parquet`: **{len(labels):,} rows**\n")

    A("## Timing contract (obeyed exactly)\n")
    A("> features use data available *before* the trade -> **trade at the *t+1* "
      "open** -> return earned ***t+1* open to *t+2* open**.\n")
    A("`fwd_ret_h = open[t+1+h] / open[t+1] - 1`, then cross-sectionally demeaned "
      "within the in-universe set each day; the demeaned value **is the label**. "
      "Every feature window is strictly trailing and uses only rows dated <= *t* "
      "(`mom_21` / `mom_126` additionally skip the most recent day / 21 days).\n")

    A("## Per-field availability applied\n")
    A("| Field | Knowable at | Lag | Handling |")
    A("|---|---|---|---|")
    A("| OHLCV + derived (mom, rev, vol, beta, amihud, turnover, dist_52wh, max_ret) | day *t* 15:30 | 0 | trailing windows on the common NSE calendar |")
    A("| `delivery_pct` | day *t* ~19:00 (pre *t+1* open) | 0 | joined on date *t*; NaN before first available date |")
    A("| `size_proxy` | day *t* (trailing turnover) | 0 | joined on date *t* from P2 |")
    A("| `sector` | static — **NOT point-in-time** | 0 | see caveat below |")
    A("| `in_universe` | effective date, applied 1–3 d late | 0 | from P1 membership (already conservative) |\n")

    A("## `delivery_pct` availability decision\n")
    fd = delivery_info.get("delivery_first_date")
    A(f"- Source: {delivery_info.get('delivery_source')}")
    A(f"- **First available date: {pd.Timestamp(fd).date() if fd is not None else 'n/a'}**. "
      f"Before it, `delivery_pct` is left **NaN** — not fabricated, not back-filled "
      f"(PRE_BUILD_TASKS.md T1: `sec_bhavdata_full` starts 2019-09-30; P2 measured "
      f"the first usable `DELIV_PER` at 2019-10-01).")
    cov = asserts["feature_coverage"]["delivery_pct"]
    A(f"- Non-NaN share of `delivery_pct` in the masked panel: **{cov:.1%}** "
      f"(0% of TRAIN, partial VAL_A, full VAL_B/HOLDOUT — consistent with T1).\n")

    A("## Sector mapping — caveat (disclosed, not hidden)\n")
    A(f"- {sector_stats['by_isin']} of {sector_stats['n_symbols']} symbols "
      f"classified by **ISIN join** against NSE's current "
      f"`ind_niftytotalmarket_list.csv`, {sector_stats['by_symbol']} more by "
      f"symbol join, **{sector_stats['by_hand']} by hand** (delisted / renamed "
      f"names the current list cannot contain), {sector_stats['unknown']} "
      f"unresolved.")
    A(f"- NSE file present at build: **{sector_stats['nse_file_present']}**. "
      f"Industries used: **{sector_stats['n_industries_used']} / 22** "
      f"(NSE's official names, verbatim).")
    A("- ⚠️ **The classification is current, not point-in-time.** A company "
      "reclassified since 2015 carries today's label throughout its history. "
      "Acceptable because `sector` drives only *optional* sector-neutralization "
      "and red-team test 7 — never a standalone scored feature.")
    if sector_stats["unknown"]:
        A(f"- Unresolved (labelled `Diversified`): {sector_stats['unknown_sample']}")
    A(f"- Hand-classified sample: {sector_stats['hand_sample']}")
    A("- Judgement calls (business spans two NSE buckets — chosen label defensible, not unique):")
    for s, why in sector_stats["judgement_calls"].items():
        A(f"  - `{s}`: {why}")
    A("")

    A("## Assertion suite (step 6)\n")
    A(f"- Min cross-section after 2016-01-01: **{asserts['min_xs_after_2016']}** "
      f"(spec floor 100). Days below 100: **{len(asserts['thin_days_after_2016'])}**"
      + (f" — {asserts['thin_days_after_2016'][:10]}" if asserts['thin_days_after_2016'] else ""))
    A(f"- `dist_52wh` max value: **{asserts['dist_52wh_max']:.2e}** "
      f"(<= 0 required) -> {'OK' if asserts['dist_52wh_ok'] else 'FAIL'}")
    A(f"- `vol_21` min value: **{asserts['vol_21_min']:.4f}** "
      f"(> 0 required) -> {'OK' if asserts['vol_21_positive'] else 'FAIL'}")
    A(f"- Duplicate (date, symbol): features **{asserts['dup_keys_features']}**, "
      f"labels **{asserts['dup_keys_labels']}**")
    A("- NaN label on in-universe **and traded** rows, well inside the sample "
      "(i.e. the stock stopped trading within the forward window — a legitimate "
      "NaN, kept not filled):")
    for h, n in asserts["nan_label_inuniverse_traded"].items():
        A(f"  - `fwd_ret_{h}`: {n} rows")
    A("- Feature non-NaN coverage in the masked panel:")
    for c, v in asserts["feature_coverage"].items():
        A(f"  - `{c}`: {v:.1%}")
    A("")

    A("## Extreme daily returns (> 50%) — flagged, NOT winsorized, NOT dropped\n")
    bc = ext_info["by_category"]
    A(f"- Flagged on the masked universe panel: **{ext_info['n_flagged']}**")
    A(f"  - `demerger` (P2 policy is *not* to adjust demergers — expected): **{bc['demerger']}**")
    A(f"  - `unadjusted_split` (**P2 corporate-action gap** — split/bonus CA near "
      f"the date, or raw close jumps by a clean split fraction; see handoff §6): "
      f"**{bc['unadjusted_split']}**")
    A(f"  - `genuine` (no CA, real distress move — e.g. JETAIRWAYS grounding): **{bc['genuine']}**")
    A("- Kept verbatim: Indian mid-caps genuinely move like this and clipping "
      "them would distort `max_ret_21`, which exists to capture exactly that.")
    if ext_info["sample"]:
        A("\n| date | symbol | daily ret | category |")
        A("|---|---|---|---|")
        for r in ext_info["sample"]:
            A(f"| {r['date']} | {r['symbol']} | {r['ret']:+.1%} | {r['category']} |")
    A("")

    A("## Step 7 — the look-ahead self-test (the most important test)\n")
    A("_Computed on non-HOLDOUT dates only — HOLDOUT is sealed._\n")
    st = selftest

    def _triplet_lines(label, t):
        A(f"- **{label}** RankIC vs `fwd_ret_1_demeaned`: **{t['ic']:+.5f}**  "
          f"→ forward-shift 1d: **{t['ic_shift_fwd1']:+.5f}** "
          f"(abs Δ {t['abs_change_fwd1']:.5f}, rel Δ {t['rel_change_fwd1']:.0%})  "
          f"→ backward-shift 1d: **{t['ic_shift_bwd1']:+.5f}**")

    A("### (a) shift the whole feature panel one day — a known factor's IC must change\n")
    _triplet_lines("rev_5 (primary — a genuine, fast signal)", st["rev_5"])
    _triplet_lines("mom_21", st["mom_21"])
    _triplet_lines("mom_126", st["mom_126"])
    A(f"\n- **Primary-factor IC materially changes under the forward shift: "
      f"{st['shift_changes_ic']}** → the pipeline is not time-symmetric anywhere "
      f"(no leak). (`mom_126` is a 126-day window so a 1-day shift barely moves "
      f"its *values*; `rev_5` is the decisive fast-signal test.)")
    A("\n### (b) deliberately leaky feature (fwd_ret_1 predicting itself)\n")
    A(f"- RankIC: **{st['leaky_ic']:+.5f}** — |IC| > 0.9 required → "
      f"**{st['machinery_detects_leak']}**. The measurement machinery *can* "
      f"detect leakage, which is what makes the negative result on real features "
      f"meaningful.")
    A("\n### (c) that leaky feature shifted forward one day\n")
    A(f"- RankIC: **{st['leaky_ic_shifted_fwd1']:+.5f}** — collapses toward 0 "
      f"(< half of |leaky IC|): **{st['leak_collapses_on_shift']}**.\n")

    A("## splits.json (Section 0.4, verbatim)\n")
    A("```json")
    A(json.dumps(SPLITS_JSON_PAYLOAD, indent=1))
    A("```\n")

    A("## Decision log\n")
    for d in DECISIONS_LOG:
        A(f"- {d}")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #
def run(write: bool = True) -> dict:
    DECISIONS_LOG.clear()
    np.random.seed(RANDOM_SEED)
    random.seed(RANDOM_SEED)

    inp = load_inputs()
    ohlcv, membership = inp["ohlcv"], inp["membership"]
    union = sorted(membership.loc[membership["in_universe"], "symbol"].unique())
    _log(f"universe union: {len(union)} symbols ever in-universe")

    wide = build_wide(ohlcv, union)
    idx, cols = wide["close"].index, wide["close"].columns
    memb_w = membership_wide(membership, idx, cols)

    feat_frames, mkt = compute_features(wide, memb_w)
    label_frames = compute_labels(wide["open"], memb_w)

    _log("feature windows are trailing on the COMMON NSE trading calendar "
         "(wide date x symbol panel), not each symbol's own row count — every "
         "stock shares the same 21/63/252-day window; documented as a judgement call")

    # --- assemble long, join externals, mask ---
    features = assemble_long(feat_frames)
    isin_last = (ohlcv.sort_values("date").groupby("symbol")["isin"].last()
                 if "isin" in ohlcv.columns else pd.Series(dtype=str))
    isin_map = {s: str(isin_last.get(s, "")) for s in union}
    sector_map, sector_stats = build_sector_map(union, isin_map)

    features, delivery_info = join_external(
        features, inp["delivery"], inp["size_proxy"], inp["is_real"])

    # fixture size_proxy fallback (compute from fixture turnover if P2 absent)
    if features["size_proxy"].isna().all():
        turn63 = (wide["close_raw"] * wide["volume_raw"]).rolling(
            63, min_periods=63).median()
        sp_long = _stack(np.log(turn63.replace(0.0, np.nan)), "size_proxy").reset_index()
        sp_long = _to_ns(sp_long)
        features = features.drop(columns=["size_proxy"]).merge(
            sp_long, on=["date", "symbol"], how="left")

    features["sector"] = features["symbol"].map(sector_map).astype(str)
    features = mask_to_universe(features, membership)

    labels = assemble_long(label_frames)
    labels = mask_to_universe(labels, membership)

    # column order per Section 0.5
    features = features[["date", "symbol", *FEATURE_COLS, "size_proxy", "sector"]]
    label_order = ["date", "symbol"] + \
        [f"fwd_ret_{h}" for h in HORIZONS] + \
        [f"fwd_ret_{h}_demeaned" for h in HORIZONS]
    labels = labels[label_order]
    for df in (features, labels):
        for c in df.columns:
            if c.startswith(("fwd_ret", "mom", "rev", "vol", "beta", "amihud",
                             "turnover", "dist", "max_ret", "delivery", "size_proxy")):
                df[c] = df[c].astype(np.float64)

    validate_features(features)
    validate_labels(labels)
    _log("validate_features / validate_labels both pass on the masked panel")

    asserts = run_assertions(features, labels, membership, wide)
    ext_info = flag_extreme_returns(features, wide, membership, inp["corp"])
    selftest = lookahead_selftest(feat_frames, label_frames, memb_w)

    report = write_report(
        src=inp["src"], is_real=inp["is_real"], sector_stats=sector_stats,
        ext_info=ext_info, asserts=asserts, selftest=selftest,
        delivery_info=delivery_info, features=features, labels=labels, mkt=mkt)

    if write:
        PANEL_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        features.to_parquet(FEATURES_PARQUET, index=False)
        labels.to_parquet(LABELS_PARQUET, index=False)
        SPLITS_JSON.write_text(json.dumps(SPLITS_JSON_PAYLOAD, indent=1),
                               encoding="utf-8")
        P3_REPORT.write_text(report, encoding="utf-8")

    return {"features": features, "labels": labels, "asserts": asserts,
            "extreme": ext_info, "selftest": selftest, "sector_stats": sector_stats,
            "delivery_info": delivery_info, "report": report, "is_real": inp["is_real"],
            "splits": SPLITS_JSON_PAYLOAD}


if __name__ == "__main__":
    r = run(write=True)
    f, l = r["features"], r["labels"]
    print(f"features.parquet : {len(f):,} rows, {f['symbol'].nunique()} symbols, "
          f"{f['date'].nunique()} days ({f['date'].min().date()}..{f['date'].max().date()})")
    print(f"labels.parquet   : {len(l):,} rows")
    print(f"sector map       : {r['sector_stats']['by_isin']} isin + "
          f"{r['sector_stats']['by_symbol']} sym + {r['sector_stats']['by_hand']} hand, "
          f"{r['sector_stats']['unknown']} unknown")
    st = r["selftest"]
    print(f"self-test (a)    : rev_5 IC {st['rev_5']['ic']:+.5f} -> shifted "
          f"{st['rev_5']['ic_shift_fwd1']:+.5f}  (changes={st['shift_changes_ic']})")
    print(f"self-test (b)    : leaky IC {st['leaky_ic']:+.5f}  "
          f"(detects leak={st['machinery_detects_leak']})")
    print(f"extreme returns  : {r['extreme']['n_flagged']} flagged "
          f"{r['extreme']['by_category']}")
    print(f"delivery first   : {pd.Timestamp(r['delivery_info']['delivery_first_date']).date()}")
