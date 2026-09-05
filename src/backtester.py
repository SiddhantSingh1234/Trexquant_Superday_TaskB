"""Phase 4 — the backtester engine.

**One** deterministic, parameterized function, :func:`backtest`, scores a daily
cross-sectional signal against the Phase-3 label panel and returns the
``Metrics`` dict from IMPLEMENTATION_PLAN.md Section 0.5.  Every downstream phase
(quick screening, fresh-fold confirmation, the full battery, marginal-IC, the
rationed holdout peek, red-team stress tests, portfolio combination, the
ablation study) calls this same function with different switches — it is built
once, parameterized, never forked.

This engine only **measures**.  It never decides accept/reject, never calls an
LLM, and does not implement Deflated Sharpe / PBO / CSCV / the trial ledger —
those are Phase 6.

Key contracts
-------------
* ``split == "holdout"`` raises unless ``i_have_a_peek_token=True`` is passed
  explicitly.  Phase 6 owns token issuance; this is a tripwire.
* Purge + embargo is a reusable function (:func:`purge_embargo_mask`) — Phase 6's
  CSCV calls it too.
* Determinism: no RNG is used here; two identical calls are bit-identical.

The panel is read from ``data/panel/{features,labels}.parquet`` if present,
otherwise the Phase-0 synthetic fixtures are used (their fake ``mom_21`` carries a
planted RankIC of ~0.04).  :func:`use_panel` overrides the source in-process —
used by the tests and by Phase 6 when it needs to score a data subset.
"""
from __future__ import annotations

import random
from typing import Any

import numpy as np
import pandas as pd

from . import contracts as _contracts
from .config import (
    FEATURES_PARQUET,
    HOLDOUT_START,
    LABELS_PARQUET,
    RANDOM_SEED,
    VALID_REGIONS,
    split_mask,
)
from .contracts import HORIZONS, validate_features, validate_labels

# Determinism — nothing here samples, but seed defensively per Section 0.6.
np.random.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)

TRADING_DAYS_PER_YEAR = 252
MIN_STOCKS_PER_DAY = 20          # a rank corr on < 20 names is noise (step 1)
QUANTILE = 0.2                   # top / bottom quintile for the L/S book (step 4)

# The exact Metrics key order (Section 0.5).  Used to assert the returned shape.
_METRIC_KEYS = (
    "rank_ic", "ic", "icir", "t_stat",
    "sharpe", "ann_return", "turnover", "mdd",
    "n_days", "n_obs", "decay", "sign",
)

# --------------------------------------------------------------------------- #
# Panel source                                                                 #
# --------------------------------------------------------------------------- #
_PANEL_OVERRIDE: tuple[pd.DataFrame, pd.DataFrame] | None = None


def use_panel(features: pd.DataFrame, labels: pd.DataFrame) -> None:
    """Override the on-disk panel for the rest of the process.

    Validates both frames on the way in (fail loudly, Section 0.6).  Intended for
    tests and for Phase 6 (which scores data subsets).  Call :func:`clear_panel`
    to restore the disk/fixture source.
    """
    validate_features(features)
    validate_labels(labels)
    global _PANEL_OVERRIDE
    _PANEL_OVERRIDE = (features.copy(), labels.copy())


def clear_panel() -> None:
    """Undo :func:`use_panel`."""
    global _PANEL_OVERRIDE
    _PANEL_OVERRIDE = None


def _load_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(features, labels)`` — override, then disk, then fixtures."""
    if _PANEL_OVERRIDE is not None:
        return _PANEL_OVERRIDE

    if FEATURES_PARQUET.exists() and LABELS_PARQUET.exists():
        feats = pd.read_parquet(FEATURES_PARQUET)
        labs = pd.read_parquet(LABELS_PARQUET)
    else:  # no upstream data — build the planted fixture (IC ~ 0.04 in mom_21)
        feats = _contracts.make_fake_features()
        labs = _contracts.make_fake_labels()

    validate_features(feats)
    validate_labels(labs)
    return feats, labs


# --------------------------------------------------------------------------- #
# Purge + embargo — reusable (Phase 6's CSCV calls this too)                    #
# --------------------------------------------------------------------------- #
def purge_embargo_mask(
    train_dates,
    test_dates,
    horizon: int,
    embargo_days: int,
    calendar,
) -> np.ndarray:
    """Boolean mask over ``train_dates`` — ``True`` == keep, ``False`` == drop.

    A training row is dropped when its label window overlaps a test block
    (**purge**) or when it falls within ``embargo_days`` trading days *after* a
    test block (**embargo**).

    ``calendar`` is the ordered set of all trading days; purge/embargo distances
    are counted in trading days on it, never calendar days.

    Label-window logic: a signal row at trading-day position ``p`` earns its
    return over ``open[p+1] -> open[p+1+horizon]``, i.e. it consumes calendar
    positions ``p+1 .. p+1+horizon``.  It overlaps a test block starting at
    position ``a`` iff ``p + 1 + horizon >= a``  ->  ``p >= a - horizon - 1``.
    """
    cal = pd.DatetimeIndex(pd.to_datetime(calendar)).unique().sort_values()
    pos = {d: i for i, d in enumerate(cal)}

    train = pd.DatetimeIndex(pd.to_datetime(train_dates))
    test = pd.DatetimeIndex(pd.to_datetime(test_dates)).unique().sort_values()

    keep = np.ones(len(train), dtype=bool)
    if len(test) == 0:
        return keep

    test_pos = np.array([pos[d] for d in test])
    # contiguous runs of test positions
    breaks = np.where(np.diff(test_pos) != 1)[0]
    starts = np.concatenate([[0], breaks + 1])
    ends = np.concatenate([breaks, [len(test_pos) - 1]])

    train_pos = np.array([pos.get(d, -1) for d in train])
    for s, e in zip(starts, ends):
        a, b = test_pos[s], test_pos[e]
        lo = a - horizon - 1
        hi = b + embargo_days
        keep &= ~((train_pos >= lo) & (train_pos <= hi) & (train_pos >= 0))
    return keep


# --------------------------------------------------------------------------- #
# Internal helpers                                                             #
# --------------------------------------------------------------------------- #
def _signal_to_long(signal: pd.DataFrame) -> pd.DataFrame:
    """Accept a wide ``date x symbol`` signal, return long ``date,symbol,sig``."""
    if not isinstance(signal, pd.DataFrame):
        raise TypeError(f"signal must be a DataFrame, got {type(signal)!r}")

    if {"date", "symbol"}.issubset(signal.columns):
        others = [c for c in signal.columns if c not in ("date", "symbol")]
        if len(others) != 1:
            raise ValueError(
                "long signal must have exactly one value column besides "
                f"(date, symbol); got {others}"
            )
        out = signal[["date", "symbol", others[0]]].rename(columns={others[0]: "sig"})
    else:
        wide = signal.copy()
        wide.index = pd.DatetimeIndex(pd.to_datetime(wide.index)).normalize()
        wide.index.name = "date"
        out = (
            wide.stack(future_stack=True)
            .rename_axis(["date", "symbol"])
            .rename("sig")
            .reset_index()
        )

    out["date"] = pd.to_datetime(out["date"]).dt.normalize().astype("datetime64[ns]")
    out["symbol"] = out["symbol"].astype(str)
    out["sig"] = pd.to_numeric(out["sig"], errors="coerce").astype(np.float64)
    return out.dropna(subset=["sig"])


def _shift_signal(long_sig: pd.DataFrame, extra_lag: int, calendar) -> pd.DataFrame:
    """Move every signal value forward ``extra_lag`` trading days (red-team #5).

    ``extra_lag=1`` means: on day *t* we act on the signal computed for day
    *t-1*.  Implemented by re-stamping each row's date to ``calendar[pos+lag]``.
    """
    if extra_lag == 0:
        return long_sig
    if extra_lag < 0:
        raise ValueError("extra_lag must be >= 0")

    cal = pd.DatetimeIndex(pd.to_datetime(calendar)).unique().sort_values()
    pos = pd.Series(np.arange(len(cal)), index=cal)
    p = long_sig["date"].map(pos)
    new_p = p + extra_lag
    # ``p`` is NaN for any signal date outside ``cal`` (e.g. a full-history
    # price panel has warmup dates the label calendar does not) -- those rows
    # never belong in the output, and once excluded ``new_p`` is a whole-number
    # float Series that must be cast back to int before it can index ``cal``.
    ok = new_p.notna() & (new_p < len(cal))
    out = long_sig.loc[ok].copy()
    out["date"] = cal[new_p[ok].to_numpy().astype(np.int64)]
    return out


def _rank_scale(s: pd.Series) -> pd.Series:
    """Rank ``s`` within its group and linearly map to ``[-1, 1]`` (step 2)."""
    r = s.rank(method="average")
    n = r.notna().sum()
    if n <= 1:
        return pd.Series(0.0, index=s.index)
    return 2.0 * (r - 1.0) / (n - 1.0) - 1.0


def _daily_ic(df: pd.DataFrame, xcol: str, ycol: str, spearman: bool) -> pd.Series:
    """Per-day correlation of ``xcol`` vs ``ycol``; Spearman if requested.

    Vectorized: Pearson r on per-day standardized columns (``ddof=1``).  For
    Spearman the columns are replaced by their per-day ranks first.  Days where
    either column has zero cross-sectional variance yield NaN and are dropped by
    the caller's ``.mean()``.
    """
    d = df[["date", xcol, ycol]].dropna()
    g = d.groupby("date", sort=True)
    x = g[xcol].rank() if spearman else d[xcol]
    y = g[ycol].rank() if spearman else d[ycol]
    d = d.assign(_x=x, _y=y)
    g = d.groupby("date", sort=True)
    zx = (d["_x"] - g["_x"].transform("mean")) / g["_x"].transform("std")
    zy = (d["_y"] - g["_y"].transform("mean")) / g["_y"].transform("std")
    prod = (zx * zy).groupby(d["date"], sort=True).sum()
    cnt = g.size()
    return (prod / (cnt - 1)).replace([np.inf, -np.inf], np.nan).dropna()


#: Regimes selectable via ``subsample={"regime": ...}``.  ``highvol`` is the
#: expanding top-tercile band the red-team (Phase 9) stresses.
VALID_REGIMES = ("bull", "bear", "calm", "volatile", "highvol")


def _expanding_quantile(v: np.ndarray, q: float, min_obs: int) -> np.ndarray:
    """``out[i]`` = the ``q``-quantile of the finite values in ``v[:i+1]``.

    A tight prefix loop — ``pandas`` ``Expanding.quantile`` is O(n²) with
    crippling per-window overhead.  Strictly expanding: ``out[i]`` never sees
    ``v[i+1:]``, so truncating the future cannot move a past value.
    """
    out = np.full(len(v), np.nan)
    seen: list[float] = []
    for i, x in enumerate(v):
        if np.isfinite(x):
            seen.append(x)
        if len(seen) >= min_obs:
            out[i] = float(np.quantile(seen, q))
    return out


def _regime_labels(labels: pd.DataFrame) -> pd.DataFrame:
    """Per-date market-regime flags — **EXPANDING WINDOW ONLY**.

    Market proxy = equal-weight mean of ``fwd_ret_1`` across the in-panel names
    that day.  Every flag at date *d* uses only market history up to and
    including *d*, so truncating the future never changes a past label (a
    full-sample threshold would be look-ahead — see
    ``tests/test_p4_backtester.py::test_regime_labels_are_expanding_window_only``).

    * ``bull`` / ``bear`` — trailing 63-day **compounded** market return
      ``> +5%`` / ``< -5%`` (the band between the two is neither).
    * ``calm`` / ``volatile`` — trailing 21-day realized vol ``<=`` / ``>`` its
      own **expanding median**.
    * ``highvol`` — trailing 21-day realized vol ``>=`` its own **expanding
      top tercile**.  (Phase 9's red-team regime-split test consumes this one.)
    """
    mkt = labels.groupby("date")["fwd_ret_1"].mean().sort_index()
    mkt.index = pd.DatetimeIndex(pd.to_datetime(mkt.index)).normalize()

    cum63 = (1.0 + mkt).rolling(63, min_periods=40).apply(np.prod, raw=True) - 1.0
    vol21 = mkt.rolling(21, min_periods=10).std(ddof=1)
    med = pd.Series(_expanding_quantile(vol21.to_numpy(), 0.5, 40), index=mkt.index)
    ter = pd.Series(_expanding_quantile(vol21.to_numpy(), 2.0 / 3.0, 40), index=mkt.index)

    return pd.DataFrame(
        {
            "bull": (cum63 > 0.05).fillna(False),
            "bear": (cum63 < -0.05).fillna(False),
            "calm": (vol21 <= med).fillna(False),
            "volatile": (vol21 > med).fillna(False),
            "highvol": (vol21 >= ter).fillna(False),
        },
        index=mkt.index,
    )


def _regime_mask(labels: pd.DataFrame, regime: str) -> pd.Series:
    """Boolean Series over dates — ``True`` where ``regime`` holds that day."""
    if regime not in VALID_REGIMES:
        raise ValueError(f"unknown regime {regime!r}; valid: {list(VALID_REGIMES)}")
    return _regime_labels(labels)[regime]


def _apply_subsample(
    panel: pd.DataFrame, labels: pd.DataFrame, feats: pd.DataFrame, subsample: dict
) -> pd.DataFrame:
    """Filter the aligned ``(date, symbol)`` panel per the ``subsample`` dict."""
    allowed = {"years", "size_tercile", "regime", "min_turnover", "exclude_symbols"}
    unknown = set(subsample) - allowed
    if unknown:
        raise ValueError(f"unknown subsample keys: {sorted(unknown)}")
    p = panel

    if "years" in subsample:
        yrs = set(int(y) for y in subsample["years"])
        p = p[p["date"].dt.year.isin(yrs)]

    if "exclude_symbols" in subsample:
        bad = set(map(str, subsample["exclude_symbols"]))
        p = p[~p["symbol"].isin(bad)]

    if "size_tercile" in subsample:
        want = subsample["size_tercile"]
        if want not in ("small", "mid", "large"):
            raise ValueError(f"size_tercile must be small|mid|large, got {want!r}")
        sz = feats[["date", "symbol", "size_proxy"]]
        p = p.merge(sz, on=["date", "symbol"], how="left")
        lab = p.groupby("date")["size_proxy"].transform(
            lambda s: pd.qcut(s, 3, labels=["small", "mid", "large"], duplicates="drop")
            if s.notna().sum() >= 3 else pd.Series(np.nan, index=s.index)
        )
        p = p[lab == want].drop(columns="size_proxy")

    if "min_turnover" in subsample:
        thr = float(subsample["min_turnover"])
        to = feats[["date", "symbol", "turnover_21"]].copy()
        to["turnover_rupees"] = np.exp(to["turnover_21"])  # P3 stores log(mean turnover)
        p = p.merge(to[["date", "symbol", "turnover_rupees"]], on=["date", "symbol"], how="left")
        p = p[p["turnover_rupees"] >= thr].drop(columns="turnover_rupees")

    if "regime" in subsample:
        flag = _regime_mask(labels, subsample["regime"])   # bool Series by date
        keep = set(flag.index[flag.to_numpy()])
        p = p[p["date"].isin(keep)]

    return p


def _empty_metrics() -> dict[str, Any]:
    return {
        "rank_ic": float("nan"), "ic": float("nan"), "icir": float("nan"),
        "t_stat": float("nan"), "sharpe": float("nan"), "ann_return": float("nan"),
        "turnover": float("nan"), "mdd": float("nan"), "n_days": 0, "n_obs": 0,
        "decay": {h: float("nan") for h in HORIZONS}, "sign": 0,
    }


# --------------------------------------------------------------------------- #
# The engine                                                                   #
# --------------------------------------------------------------------------- #
def backtest(
    signal: pd.DataFrame,
    split: str,
    horizon: int = 1,
    extra_lag: int = 0,
    cost_bps: float = 0.0,
    neutralize: str | None = None,
    subsample: dict | None = None,
    purge_days: int | None = None,
    embargo_days: int = 5,
    *,
    i_have_a_peek_token: bool = False,
) -> dict[str, Any]:
    """Score a ``date x symbol`` signal on ``split`` and return the Metrics dict.

    Parameters
    ----------
    signal        wide ``date x symbol`` frame, one score per stock per day
                  (a long ``date,symbol,<value>`` frame is also accepted).
    split         ``"train" | "val_a" | "val_b" | "holdout" | "train+val_a"``.
    horizon       forward-return horizon *h* for the headline ``rank_ic`` / ``ic``.
    extra_lag     shift the whole signal forward *N* extra trading days.
    cost_bps      transaction cost in basis points, charged on every unit of
                  absolute weight change (both legs of the book).
    neutralize    ``None`` or ``"sector"`` (demean the signal within sector first).
    subsample     optional filter: ``{"years":[...]}``, ``{"size_tercile":...}``,
                  ``{"regime": "bull"|"bear"|"calm"|"volatile"|"highvol"}``
                  (expanding-window labels — see :func:`_regime_labels`),
                  ``{"min_turnover":...}``, ``{"exclude_symbols":[...]}``.
    purge_days    label-overlap purge distance; defaults to ``horizon``.
    embargo_days  embargo distance after the eval window (trading days).
    i_have_a_peek_token
                  MUST be ``True`` to score ``split="holdout"``.  Tripwire —
                  Phase 6 owns issuance.

    Returns the dict shaped exactly per Section 0.5.
    """
    # ---- guards -----------------------------------------------------------
    if split not in VALID_REGIONS:
        raise ValueError(f"unknown split {split!r}; valid: {sorted(VALID_REGIONS)}")
    if split == "holdout" and not i_have_a_peek_token:
        raise PermissionError(
            "split='holdout' requires i_have_a_peek_token=True. HOLDOUT is sealed "
            "— only Phase 6's rationed-peek API may issue that token."
        )
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {HORIZONS}, got {horizon}")
    if neutralize not in (None, "sector"):
        raise ValueError(f"neutralize must be None or 'sector', got {neutralize!r}")
    if purge_days is None:
        purge_days = horizon

    feats, labels = _load_panel()
    calendar = np.sort(labels["date"].unique())

    # ---- signal: long, lag, restrict to split window ---------------------
    sig = _signal_to_long(signal)
    sig = _shift_signal(sig, extra_lag, calendar)
    sig = sig[split_mask(sig["date"], split)]
    if len(sig) == 0:
        return _empty_metrics()

    # ---- align to labels ------------------------------------------------
    dem_cols = [f"fwd_ret_{h}_demeaned" for h in HORIZONS]
    lab = labels[["date", "symbol", "fwd_ret_1", *dem_cols]]
    panel = sig.merge(lab, on=["date", "symbol"], how="inner")

    if subsample:
        panel = _apply_subsample(panel, labels, feats, subsample)
    if len(panel) == 0:
        return _empty_metrics()

    # ---- HOLDOUT-boundary tail purge ---------------------------------
    # P3 computed fwd_ret_h across every split boundary ("sealing is enforced at
    # scoring time" — P3 handoff §6.3).  So val_b's last ~h rows carry labels P3
    # derived from HOLDOUT-period opens (2022-06-30 fwd_ret_21 reads an Aug-2022
    # open).  Drop exactly those rows, so no non-holdout split's metrics depend
    # on sealed-HOLDOUT prices.  Rows past the panel end are NaN and drop on
    # their own; train/test fold purging is purge_embargo_mask() (Phase 6's CSCV).
    if split != "holdout":
        eval_days = np.sort(panel["date"].unique())
        keep_days = _purge_holdout_tail(eval_days, calendar, purge_days)
        panel = panel[panel["date"].isin(keep_days)]
        if len(panel) == 0:
            return _empty_metrics()

    # ---- drop thin days (step 1) --------------------------------------
    day_n = panel.groupby("date")["sig"].transform("size")
    panel = panel[day_n >= MIN_STOCKS_PER_DAY]
    if len(panel) == 0:
        return _empty_metrics()

    # ---- cross-sectional standardization (step 2) --------------------
    if neutralize == "sector":
        sec = feats[["date", "symbol", "sector"]]
        panel = panel.merge(sec, on=["date", "symbol"], how="left")
        panel["sector"] = panel["sector"].fillna("__NA__")
        panel["sig"] = panel["sig"] - panel.groupby(["date", "sector"])["sig"].transform("mean")

    panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)
    panel["sig_scaled"] = panel.groupby("date")["sig"].transform(_rank_scale)

    # ---- core metrics (step 3) -------------------------------------
    y = f"fwd_ret_{horizon}_demeaned"
    rank_ic_daily = _daily_ic(panel, "sig_scaled", y, spearman=True)
    ic_daily = _daily_ic(panel, "sig_scaled", y, spearman=False)

    n_days = int(rank_ic_daily.shape[0])
    rank_ic = float(rank_ic_daily.mean())
    ic = float(ic_daily.mean()) if len(ic_daily) else float("nan")
    sd = float(rank_ic_daily.std(ddof=1)) if n_days > 1 else float("nan")
    icir = float(rank_ic / sd) if sd and np.isfinite(sd) and sd > 0 else float("nan")
    t_stat = (
        float(rank_ic / (sd / np.sqrt(n_days)))
        if sd and np.isfinite(sd) and sd > 0 and n_days > 0 else float("nan")
    )
    sign = 1 if rank_ic > 0 else -1

    # ---- decay curve (step 5) ------------------------------------
    decay: dict[int, float] = {}
    for h in HORIZONS:
        s = _daily_ic(panel, "sig_scaled", f"fwd_ret_{h}_demeaned", spearman=True)
        decay[h] = float(s.mean()) if len(s) else float("nan")

    # ---- long-short book (step 4) -------------------------------
    port = _long_short(panel, cost_bps)

    metrics = {
        "rank_ic": rank_ic,
        "ic": ic,
        "icir": icir,
        "t_stat": t_stat,
        "sharpe": port["sharpe"],
        "ann_return": port["ann_return"],
        "turnover": port["turnover"],
        "mdd": port["mdd"],
        "n_days": n_days,
        "n_obs": int(len(panel)),
        "decay": decay,
        "sign": sign,
    }
    assert tuple(metrics) == _METRIC_KEYS, "Metrics dict shape drifted from Section 0.5"
    return metrics


def _purge_holdout_tail(eval_days, calendar, purge_days) -> pd.DatetimeIndex:
    """Drop eval days whose ``fwd_ret_horizon`` window reaches into sealed HOLDOUT.

    ``fwd_ret_h`` at calendar position ``p`` reads ``open`` at positions ``p+1``
    and ``p+1+h``; with ``purge_days`` (== ``horizon`` by default) the row is
    dropped unless ``p + 1 + purge_days`` is still strictly before the first
    HOLDOUT trading day.  This is the *only* tail purge the single-split engine
    applies — its scope is exactly the one hard rule ("HOLDOUT is sacred").
    Non-holdout boundaries (val_a → val_b, train → val_a) are left intact: those
    splits' return windows may overlap the next region, which is standard in
    out-of-sample evaluation and not a sealing concern.  Rows past the panel end
    carry NaN labels and are dropped downstream.

    Embargo is not applied here (no train block in a single-split score); Phase
    6's CSCV calls :func:`purge_embargo_mask` for train/test fold purging.
    """
    cal = pd.DatetimeIndex(pd.to_datetime(calendar)).unique().sort_values()
    after = cal[cal >= HOLDOUT_START]
    eval_days = pd.DatetimeIndex(pd.to_datetime(eval_days)).unique().sort_values()
    if len(after) == 0:                            # panel never reaches HOLDOUT
        return eval_days

    pos = {d: i for i, d in enumerate(cal)}
    boundary = pos[after[0]]
    return pd.DatetimeIndex(
        [d for d in eval_days if pos[d] + 1 + purge_days < boundary]
    )


def _long_short(panel: pd.DataFrame, cost_bps: float) -> dict[str, float]:
    """Dollar-neutral top/bottom-quintile equal-weight book, rebalanced daily.

    Daily P&L uses the 1-day forward return (``fwd_ret_1``); ``horizon`` drives
    the IC/decay metrics, not the book's holding period (documented judgement
    call — overlapping multi-day tranches are not part of the Metrics contract).
    Cost = ``cost_bps * 1e-4 * sum_i |w_{t,i} - w_{t-1,i}|`` (charged on both the
    open and the close of every position change).
    """
    d = panel[["date", "symbol", "sig_scaled", "fwd_ret_1"]].dropna(
        subset=["sig_scaled", "fwd_ret_1"]
    )
    g = d.groupby("date", sort=True)["sig_scaled"]
    pct = g.rank(pct=True, method="first")
    n = g.transform("size")

    is_long = pct > (1.0 - QUANTILE)
    is_short = pct <= QUANTILE
    n_long = is_long.groupby(d["date"]).transform("sum")
    n_short = is_short.groupby(d["date"]).transform("sum")

    w = pd.Series(0.0, index=d.index)
    w[is_long] = 1.0 / n_long[is_long]
    w[is_short] = -1.0 / n_short[is_short]
    d = d.assign(w=w)

    # days with a complete book (enough names, both wings populated)
    good = (n >= MIN_STOCKS_PER_DAY) & (n_long > 0) & (n_short > 0)
    d = d[good]
    if d.empty:
        return dict(sharpe=float("nan"), ann_return=float("nan"),
                    turnover=float("nan"), mdd=float("nan"))

    gross = (d["w"] * d["fwd_ret_1"]).groupby(d["date"], sort=True).sum()

    # turnover: |w_t - w_{t-1}| summed across symbols, via a compact wide matrix
    wmat = d.pivot(index="date", columns="symbol", values="w").fillna(0.0)
    dw = wmat.diff().abs().sum(axis=1)
    dw.iloc[0] = wmat.iloc[0].abs().sum()        # day 1 establishes the book
    cost = cost_bps * 1e-4 * dw

    net = (gross - cost).dropna()
    if len(net) < 2 or net.std(ddof=1) == 0:
        return dict(sharpe=float("nan"), ann_return=float("nan"),
                    turnover=float(dw.mean() * 0.5), mdd=float("nan"))

    sharpe = float(net.mean() / net.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
    ann_return = float(net.mean() * TRADING_DAYS_PER_YEAR)
    curve = (1.0 + net).cumprod()
    mdd = float((curve / curve.cummax() - 1.0).min())
    turnover = float(dw.mean() * 0.5)            # one-way turnover
    return dict(sharpe=sharpe, ann_return=ann_return, turnover=turnover, mdd=mdd)


# --------------------------------------------------------------------------- #
# Manual smoke check                                                           #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":  # pragma: no cover
    feats, labs = _load_panel()
    sig = feats.pivot_table(index="date", columns="symbol", values="mom_126")
    m = backtest(sig, "val_a", horizon=5)
    for k in _METRIC_KEYS:
        print(f"{k:>12}: {m[k]}")
