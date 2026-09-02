"""Phase 6 — the honesty machinery.

Everything here exists to price in **one** fact:

    If you test N worthless signals, the best one's t-statistic is of order
    sqrt(2 * ln N) — purely by chance.  N=20 -> 2.45, N=100 -> 3.03,
    N=200 -> 3.26.  At 200 attempts your best formula clears a "t > 3" bar with
    nothing there at all.

**sqrt(2 ln N) is a CEILING, not the expected value.**  It is the asymptotic
upper bound on the maximum of N standard normals; the *realised* maximum centres
about 0.5 lower (measured, 20k Monte-Carlo draws per N):

    N       realised E[max]   sqrt(2 ln N)   Bailey-LdP E[max]
    5           1.168            1.794            1.193
    20          1.868            2.448            1.901
    200         2.744            3.255            2.766
    500         3.038            3.526            3.053

So the deflator this module uses is the Bailey-Lopez de Prado ``E[max SR]`` term
(right-hand column — it tracks the order statistic to ~0.03), **not**
sqrt(2 ln N).  Deflating by the bound would over-reject genuine signals: a real
signal found in 5 trials with t = 7.07 scores DSR 0.9952 (pass) under Bailey-LdP
and DSR 0.6579 (reject) under a sqrt(2 ln N) deflator.

Public surface
--------------
Statistics
* ``expected_max_sharpe(n_trials, sr_std)``            Bailey-LdP E[max SR]
* ``deflated_sharpe_ratio(sr, n_trials, sr_var, skew, kurt, n)``  -> P(SR_true>0)
* ``dsr_from_ic_series(ic, n_trials, trial_irs=...)``  the composite used in Gate B
* ``walk_forward(signal, start, end, ...)``            expanding-window OOS IC series
* ``cscv_pbo(returns_matrix, n_blocks=8)``             probability of backtest overfitting

Novelty / orthogonalisation
* ``orthogonalize(signal, book)``                      per-day cross-sectional residual
* ``marginal_ic(signal, book, split, horizon)``        RankIC of the residual
* ``effective_trial_count(canonical_asts, return_matrix=...)``
* ``clear_label_cache()``                              drop the bounded label-pivot LRU

Gate
* ``check_sign(pre_registered_sign, realized_sign)``   hard reject on a mismatch
* ``gate_b(card, book, ledger, signal=...)``           runs the load-bearing order:
      1. orthogonalise against the book   -> residual
      2. novelty (marginal IC of residual) -- kill clones HERE (free)
      3. statistics: Deflated Sharpe ON THE RESIDUAL, t > 3, PBO
         (deflated by the run-wide EFFECTIVE trial count)
      4. rationed HOLDOUT peek ON THE RESIDUAL -- only now, and it is counted

Novelty precedes statistics because step 4 spends an irreplaceable HOLDOUT peek
while step 2 is free and already computed.  The DSR is computed on the RESIDUAL,
never the raw signal: the fitness object is one composite thing — "deflated,
holdout-gated, orthogonalised marginal IC".
"""
from __future__ import annotations

import math
from collections import OrderedDict
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import kurtosis as _kurtosis
from scipy.stats import norm
from scipy.stats import rankdata
from scipy.stats import skew as _skew

from . import backtester as _bt
from .config import (
    HOLDOUT_START,
    RANDOM_SEED,
    SPLITS,
    T_STAT_BAR,
    split_mask,
)
from .contracts import HORIZONS
from .ledger import Ledger

# --------------------------------------------------------------------------- #
# Gate-B thresholds (documented judgement calls — see reports/p6_handoff.md)    #
# --------------------------------------------------------------------------- #
MIN_MARGINAL_IC = 0.01      # novelty floor: |residual RankIC| below this == clone
#   0.01 sits ~2x above the sampling noise of a daily-IC mean over a ~3.5y VAL_A
#   window (std ~= 0.13/sqrt(870) ~= 0.004) and well below genuine marginal alpha
#   (~0.02-0.03).  A judgement call the spec leaves open — see reports/p6_handoff.md.
DSR_MIN = 0.95             # P(true SR > 0) the residual must clear
PBO_MAX = 0.50             # probability-of-backtest-overfitting ceiling
MIN_DSR_SAMPLE = 60        # need at least this many scored days for a DSR

EULER_GAMMA = 0.5772156649015329
_TRADING_DAYS = 252


# ======================================================================= #
# 1.  Deflated Sharpe Ratio  (Bailey & Lopez de Prado, 2014)               #
# ======================================================================= #
def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """E[max Sharpe] across ``n_trials`` independent strategies whose true Sharpe
    is zero and whose SR estimates have cross-sectional standard deviation
    ``sr_std`` (same per-period units as the observed SR).

        E[max] ~= sr_std * [ (1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N e)) ]

    with ``g`` the Euler-Mascheroni constant.  ``n_trials <= 1`` -> 0.
    """
    n = int(max(n_trials, 1))
    if n <= 1 or sr_std <= 0 or not np.isfinite(sr_std):
        return 0.0
    g = EULER_GAMMA
    a = norm.ppf(1.0 - 1.0 / n)
    b = norm.ppf(1.0 - 1.0 / (n * math.e))
    return float(sr_std * ((1.0 - g) * a + g * b))


def deflated_sharpe_ratio(
    observed_sr: float,
    n_trials: int,
    sr_variance: float,
    skew: float,
    kurtosis: float,
    n_samples: int,
) -> float:
    """Probability that the strategy's **true** per-period Sharpe exceeds zero,
    after deflating for selection across ``n_trials`` and for non-normal returns.

    Parameters (all per-period, i.e. per scored day here — never annualised):
      observed_sr   mean(r) / std(r, ddof=1) of the chosen strategy
      n_trials      effective number of trials that produced the winner
      sr_variance   variance of the trial SRs (across trials)
      skew          skewness of the return series (0 for normal)
      kurtosis      **non-excess** kurtosis of the return series (3 for normal)
      n_samples     length of the return series

    Returns a probability in [0, 1].  DSR >= ``DSR_MIN`` is a pass.
    """
    T = int(n_samples)
    if T < 2 or not np.isfinite(observed_sr):
        return float("nan")
    sr0 = expected_max_sharpe(n_trials, math.sqrt(max(sr_variance, 0.0)))
    denom = 1.0 - skew * observed_sr + (kurtosis - 1.0) / 4.0 * observed_sr ** 2
    denom = math.sqrt(max(denom, 1e-12))
    z = (observed_sr - sr0) * math.sqrt(T - 1.0) / denom
    return float(norm.cdf(z))


def dsr_from_ic_series(
    ic_series: pd.Series,
    n_trials: int,
    trial_irs: list[float] | np.ndarray | None = None,
) -> dict[str, float]:
    """Deflated Sharpe of a **daily IC series** (the residual's, in Gate B).

    The "Sharpe" here is the daily information ratio ``mean(IC) / std(IC)``; the
    trial-SR sample is the per-day IR of every prior selection trial
    (``ledger.trial_irs()`` -> ``t_stat / sqrt(n_days)``).  The trial-SR variance
    is **floored at ``1 / T``**, the asymptotic sampling variance of a zero-mean
    IR estimate: a sample of trial SRs cannot honestly be *less* dispersed than
    pure estimation noise, and a zero (or near-zero) variance would collapse
    ``E[max SR]`` to 0 and switch the deflation off entirely.  The same ``1 / T``
    is the fallback when fewer than two prior trials are known.

    Returns ``{observed_sr, t_stat, sr0, dsr, n_days, skew, kurtosis, n_trials}``.
    """
    ic = pd.Series(ic_series).dropna().astype(float)
    T = int(ic.shape[0])
    out = {
        "observed_sr": float("nan"), "t_stat": float("nan"), "sr0": float("nan"),
        "dsr": float("nan"), "n_days": T, "skew": float("nan"),
        "kurtosis": float("nan"), "n_trials": int(max(n_trials, 1)),
    }
    if T < 2:
        return out
    sd = float(ic.std(ddof=1))
    if sd == 0 or not np.isfinite(sd):
        return out
    observed_sr = float(ic.mean()) / sd
    sk = float(_skew(ic.to_numpy(), bias=False))
    ku = float(_kurtosis(ic.to_numpy(), fisher=False, bias=False))

    irs = np.asarray(trial_irs, dtype=float) if trial_irs is not None else np.array([])
    irs = irs[np.isfinite(irs)]
    # floor at the sampling variance of a zero-mean IR estimate (see docstring)
    sr_var_floor = 1.0 / T
    sr_var = float(np.var(irs, ddof=1)) if irs.size >= 2 else sr_var_floor
    if not np.isfinite(sr_var) or sr_var < sr_var_floor:
        sr_var = sr_var_floor

    dsr = deflated_sharpe_ratio(
        observed_sr, max(n_trials, 1), sr_var, sk, ku, T
    )
    out.update(
        observed_sr=observed_sr,
        t_stat=observed_sr * math.sqrt(T),
        sr0=expected_max_sharpe(max(n_trials, 1), math.sqrt(sr_var)),
        dsr=dsr,
        skew=sk,
        kurtosis=ku,
    )
    return out


# ======================================================================= #
# 2.  Effective trial count                                               #
# ======================================================================= #
def _structural_key(canonical_ast: str) -> str:
    """Collapse an already-canonical formula string to its *shape*: every numeric
    literal (window sizes, coefficients — the knobs) becomes ``#``.  20 variants
    of ``div(volume, ts_mean(volume, k))`` for k in 5..24 all map to one key.
    """
    import re

    # replace only *standalone* numeric literals (window sizes, coefficients) —
    # never digits that are part of an identifier like ``mom_21`` or ``beta_63``.
    return re.sub(
        r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?(?:[eE]-?\d+)?(?![A-Za-z0-9_.])",
        "#",
        str(canonical_ast),
    )


def effective_trial_count(
    canonical_asts: list[str] | None = None,
    return_matrix: np.ndarray | pd.DataFrame | None = None,
    corr_floor: float = 0.0,
) -> float:
    """Effective (de-duplicated) number of independent bets.

    Raw N over-penalises: 20 near-identical formulas are maybe 3 independent
    bets, not 20.  Two signals collapse together when their **canonical AST
    shapes** match (constants ignored); within such a structural cluster, if a
    ``return_matrix`` (T x M, columns aligned to ``canonical_asts``) is supplied,
    members are split back apart in proportion to how *decorrelated* their return
    series are:  ``1 + (m - 1) * (1 - mean|corr|)`` bets for a cluster of ``m``.

    With neither argument informative, returns ``len(canonical_asts)`` (or 1).
    """
    if not canonical_asts:
        if return_matrix is not None:
            R = np.asarray(return_matrix, dtype=float)
            return float(_corr_effective_n(R))
        return 1.0

    keys = [_structural_key(a) for a in canonical_asts]
    clusters: dict[str, list[int]] = {}
    for i, k in enumerate(keys):
        clusters.setdefault(k, []).append(i)

    R = None
    if return_matrix is not None:
        R = np.asarray(return_matrix, dtype=float)
        if R.ndim != 2 or R.shape[1] != len(canonical_asts):
            R = None

    eff = 0.0
    for members in clusters.values():
        m = len(members)
        if m == 1 or R is None:
            eff += 1.0
            continue
        sub = R[:, members]
        c = np.corrcoef(sub, rowvar=False)
        off = c[~np.eye(m, dtype=bool)]
        mean_abs = float(np.nanmean(np.abs(off))) if off.size else 0.0
        mean_abs = max(mean_abs, corr_floor)
        eff += 1.0 + (m - 1) * (1.0 - mean_abs)
    return float(max(eff, 1.0))


def _corr_effective_n(return_matrix: np.ndarray) -> float:
    """Effective number of independent strategies from a return correlation
    matrix, via the participation ratio of its eigenvalues:
    ``(sum lambda)^2 / sum(lambda^2)``.
    """
    R = np.asarray(return_matrix, dtype=float)
    if R.ndim != 2 or R.shape[1] < 2:
        return float(max(R.shape[1] if R.ndim == 2 else 1, 1))
    R = R[:, ~np.all(np.isnan(R), axis=0)]
    c = np.corrcoef(np.nan_to_num(R, nan=0.0), rowvar=False)
    ev = np.linalg.eigvalsh(c)
    ev = ev[ev > 1e-10]
    if ev.size == 0:
        return 1.0
    return float(ev.sum() ** 2 / np.sum(ev ** 2))


# ======================================================================= #
# 3.  Orthogonalisation / marginal IC                                     #
# ======================================================================= #
def _to_wide(signal: pd.DataFrame) -> pd.DataFrame:
    """Accept wide (date x symbol) or long (date, symbol, value) -> wide, dates
    normalised, sorted."""
    if {"date", "symbol"}.issubset(signal.columns):
        others = [c for c in signal.columns if c not in ("date", "symbol")]
        if len(others) != 1:
            raise ValueError(f"long signal needs exactly one value column, got {others}")
        wide = signal.pivot_table(index="date", columns="symbol", values=others[0])
    else:
        wide = signal.copy()
    wide.index = pd.DatetimeIndex(pd.to_datetime(wide.index)).normalize()
    wide.index.name = "date"
    return wide.sort_index()


def _book_to_frames(book: Any) -> dict[str, pd.DataFrame]:
    """Normalise a factor book to ``{factor_name: wide date x symbol frame}``.

    Accepts: ``None`` / empty -> ``{}``; a dict of wide frames; a long frame with
    ``(date, symbol, factor, value)``; a long frame with ``(date, symbol, <one or
    more factor columns>)``; a single wide frame -> ``{"book_0": frame}``.
    """
    if book is None:
        return {}
    if isinstance(book, dict):
        return {k: _to_wide(v) for k, v in book.items() if v is not None and len(v)}
    if isinstance(book, pd.DataFrame):
        if len(book) == 0:
            return {}
        cols = set(book.columns)
        if {"date", "symbol", "factor", "value"} <= cols:
            out = {}
            for name, grp in book.groupby("factor"):
                out[str(name)] = _to_wide(grp[["date", "symbol", "value"]])
            return out
        if {"date", "symbol"} <= cols:
            facs = [c for c in book.columns if c not in ("date", "symbol")]
            return {c: _to_wide(book[["date", "symbol", c]]) for c in facs}
        # already wide
        return {"book_0": _to_wide(book)}
    raise TypeError(f"unsupported book type: {type(book)!r}")


def orthogonalize(signal: pd.DataFrame, book: Any) -> pd.DataFrame:
    """Per-day cross-sectional residual of ``signal`` after regressing it on
    every factor in ``book`` (plus an intercept).

    An empty book returns the signal unchanged (residual == raw).  Each day is
    an independent OLS on the symbols where the signal and every book factor are
    all non-NaN; symbols missing a regressor that day keep their raw signal value
    (documented judgement call — we never fabricate a book value).
    """
    sig = _to_wide(signal)
    frames = _book_to_frames(book)
    if not frames:
        return sig

    aligned = {name: f.reindex(index=sig.index, columns=sig.columns)
               for name, f in frames.items()}
    resid = sig.copy()
    S = sig.to_numpy()
    stacks = [a.to_numpy() for a in aligned.values()]

    for r in range(S.shape[0]):
        y = S[r]
        X_cols = [st[r] for st in stacks]
        good = np.isfinite(y)
        for xc in X_cols:
            good &= np.isfinite(xc)
        if good.sum() < len(X_cols) + 2:
            continue
        X = np.column_stack([np.ones(good.sum())] + [xc[good] for xc in X_cols])
        beta, *_ = np.linalg.lstsq(X, y[good], rcond=None)
        resid_vals = y[good] - X @ beta
        row = resid.iloc[r].to_numpy(copy=True)
        row[good] = resid_vals
        resid.iloc[r] = row
    return resid


LABEL_CACHE_MAXSIZE = 4
#: ``{(id(labels), horizon): (labels, wide)}`` — a **bounded LRU**.  The value
#: keeps a strong reference to the ``labels`` frame on purpose: that pins the
#: object so CPython cannot recycle its ``id()`` for a *different* panel and
#: hand back a stale pivot.  Bounded because ``backtester._load_panel()`` returns
#: a fresh object on every disk read, so an unbounded dict would add one
#: never-hit entry (~12.5 MB on the real panel) per ``gate_b`` call.
_LABEL_WIDE_CACHE: "OrderedDict[tuple[int, int], tuple[pd.DataFrame, pd.DataFrame]]" = (
    OrderedDict()
)


def clear_label_cache() -> None:
    """Drop the cached label pivots (and the panel references they pin)."""
    _LABEL_WIDE_CACHE.clear()


def _label_wide(labels: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Wide ``date x symbol`` frame of ``fwd_ret_<horizon>_demeaned``.

    Cached by the labels object's identity so repeated scoring of many signals
    against one panel is cheap.  See :data:`_LABEL_WIDE_CACHE` for why the entry
    pins its panel and why the cache is bounded.
    """
    key = (id(labels), horizon)
    hit = _LABEL_WIDE_CACHE.get(key)
    if hit is not None:
        _LABEL_WIDE_CACHE.move_to_end(key)
        return hit[1]

    ycol = f"fwd_ret_{horizon}_demeaned"
    wide = labels.pivot_table(index="date", columns="symbol", values=ycol)
    wide.index = pd.DatetimeIndex(pd.to_datetime(wide.index)).normalize()
    _LABEL_WIDE_CACHE[key] = (labels, wide)
    while len(_LABEL_WIDE_CACHE) > LABEL_CACHE_MAXSIZE:
        _LABEL_WIDE_CACHE.popitem(last=False)
    return wide


def _wide_rank_ic(
    sig_wide: pd.DataFrame, y_wide: pd.DataFrame, min_names: int = 20
) -> pd.Series:
    """Vectorised per-day Spearman IC of two wide frames.

    Ranks each row (average ranks -> exact tie correction, matching
    ``scipy.stats.spearmanr``), demeans, and takes the row-wise correlation.
    Days with fewer than ``min_names`` jointly-valid symbols are dropped.
    """
    s, y = sig_wide.align(y_wide, join="inner")
    if s.shape[0] == 0 or s.shape[1] == 0:
        return pd.Series(dtype=float)
    mask = s.notna() & y.notna()
    n = mask.sum(axis=1)
    s = s.where(mask)
    y = y.where(mask)
    sr = s.rank(axis=1)
    yr = y.rank(axis=1)
    sr = sr.sub(sr.mean(axis=1), axis=0)
    yr = yr.sub(yr.mean(axis=1), axis=0)
    cov = (sr * yr).sum(axis=1, min_count=1)
    denom = np.sqrt((sr ** 2).sum(axis=1) * (yr ** 2).sum(axis=1))
    ic = cov / denom.replace(0.0, np.nan)
    return ic[n >= min_names].dropna()


def daily_rank_ic(
    signal: pd.DataFrame,
    split: str,
    horizon: int = 1,
    *,
    allow_holdout: bool = False,
    panel: tuple[pd.DataFrame, pd.DataFrame] | None = None,
) -> pd.Series:
    """Per-day Spearman IC of ``signal`` vs ``fwd_ret_<horizon>_demeaned`` on
    ``split``.  Thin days (< 20 valid names) are dropped.  Returns a date-indexed
    Series.  Refuses HOLDOUT unless ``allow_holdout=True`` (Gate B's peek path).
    """
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {HORIZONS}")
    if split == "holdout" and not allow_holdout:
        raise PermissionError(
            "daily_rank_ic on HOLDOUT requires allow_holdout=True — only Gate B's "
            "rationed-peek path may pass it."
        )
    _, labels = panel if panel is not None else _bt._load_panel()
    sig = _to_wide(signal)
    sig = sig[split_mask(sig.index, split)]
    if len(sig) == 0:
        return pd.Series(dtype=float)
    return _wide_rank_ic(sig, _label_wide(labels, horizon), _bt.MIN_STOCKS_PER_DAY)


def marginal_ic(
    signal: pd.DataFrame,
    book: Any,
    split: str = "val_a",
    horizon: int = 1,
    *,
    panel: tuple[pd.DataFrame, pd.DataFrame] | None = None,
) -> float:
    """Mean daily RankIC of the residual of ``signal`` after ``book``.

    Empty book -> raw RankIC.  A factor against **itself** as the book -> ~0.
    """
    resid = orthogonalize(signal, book)
    ic = daily_rank_ic(resid, split, horizon, panel=panel)
    return float(ic.mean()) if len(ic) else float("nan")


# ======================================================================= #
# 4.  Walk-forward (the workhorse OOS method — decision C9)                #
# ======================================================================= #
def walk_forward(
    signal: pd.DataFrame,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    train_years: int = 3,
    step_months: int = 6,
    horizon: int = 1,
    purge_days: int | None = None,
    embargo_days: int = 5,
    *,
    book: Any = None,
    panel: tuple[pd.DataFrame, pd.DataFrame] | None = None,
) -> tuple[pd.Series, list[dict]]:
    """Expanding-window walk-forward producing a **sequential OOS IC series**.

    The signal is fixed (no parameters are refit), so each step contributes the
    daily RankIC of its test window; purge+embargo drops the first
    ``purge_days + embargo_days`` test days of every fold, so no test day's label
    window reaches back across the (expanding) train boundary.

    Returns ``(oos_ic_series, per_fold_metrics)`` where ``per_fold_metrics`` is a
    list of ``{fold, train_start, train_end, test_start, test_end, n_days,
    mean_ic, ic_ir, t_stat}``.
    """
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    if end >= HOLDOUT_START:
        raise PermissionError("walk_forward must not span HOLDOUT dates")
    if purge_days is None:
        purge_days = horizon

    resid = orthogonalize(signal, book) if book is not None else signal
    feats, labels = panel if panel is not None else _bt._load_panel()

    # score directly on the requested [start, end] window (not a named split)
    full_ic = _window_daily_ic(resid, start, end, horizon, (feats, labels))

    folds: list[dict] = []
    pieces: list[pd.Series] = []
    test_start = start + pd.DateOffset(years=train_years)
    fold_i = 0
    while test_start < end:
        test_end = min(test_start + pd.DateOffset(months=step_months), end + pd.Timedelta(days=1))
        seg = full_ic[(full_ic.index >= test_start) & (full_ic.index < test_end)]
        if len(seg) == 0:
            test_start = test_end
            continue
        drop = int(purge_days + embargo_days)
        seg_kept = seg.iloc[drop:] if drop < len(seg) else seg.iloc[0:0]
        if len(seg_kept):
            pieces.append(seg_kept)
        sd = float(seg_kept.std(ddof=1)) if len(seg_kept) > 1 else float("nan")
        mean_ic = float(seg_kept.mean()) if len(seg_kept) else float("nan")
        folds.append({
            "fold": fold_i,
            "train_start": start.strftime("%Y-%m-%d"),
            "train_end": (test_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            "test_start": test_start.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
            "n_days": int(len(seg_kept)),
            "mean_ic": mean_ic,
            "ic_ir": float(mean_ic / sd) if sd and np.isfinite(sd) and sd > 0 else float("nan"),
            "t_stat": float(mean_ic / (sd / math.sqrt(len(seg_kept))))
            if sd and np.isfinite(sd) and sd > 0 and len(seg_kept) > 0 else float("nan"),
        })
        fold_i += 1
        test_start = test_end

    oos = pd.concat(pieces).sort_index() if pieces else pd.Series(dtype=float)
    oos = oos[~oos.index.duplicated(keep="first")]
    return oos, folds


def _window_daily_ic(signal, start, end, horizon, panel):
    """daily_rank_ic restricted to an explicit [start, end] date window (both
    inclusive), bypassing the named-split machinery."""
    _, labels = panel
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    sig = _to_wide(signal)
    sig = sig[(sig.index >= start) & (sig.index <= end)]
    if len(sig) == 0:
        return pd.Series(dtype=float)
    return _wide_rank_ic(sig, _label_wide(labels, horizon), _bt.MIN_STOCKS_PER_DAY)


# ======================================================================= #
# 5.  CSCV -> PBO                                                          #
# ======================================================================= #
def cscv_pbo(
    returns_matrix: np.ndarray | pd.DataFrame,
    n_blocks: int = 8,
    purge_days: int = 0,
) -> dict[str, Any]:
    """Combinatorially-Symmetric Cross-Validation probability of backtest
    overfitting (Bailey, Borwein, Lopez de Prado, Zhu 2015).

    ``returns_matrix`` is ``T x M`` — one column per candidate strategy, one row
    per period.  The series is cut into ``n_blocks`` contiguous blocks; for every
    way of choosing ``n_blocks/2`` blocks as in-sample (IS), the IS-best strategy
    is found and its **out-of-sample rank** recorded.  PBO is the fraction of
    splits where that strategy lands below the OOS median (logit < 0).

    ``purge_days`` drops that many rows from the start of every block (a light
    purge — these strategies are not refit, so leakage is limited to label
    overlap at block seams).

    Returns ``{pbo, n_splits, logits, median_oos_rank}``.
    """
    from itertools import combinations

    R = np.asarray(returns_matrix, dtype=float)
    if R.ndim != 2 or R.shape[1] < 2:
        raise ValueError("returns_matrix must be T x M with M >= 2 strategies")
    T, M = R.shape
    if n_blocks % 2 != 0 or n_blocks < 2:
        raise ValueError("n_blocks must be even and >= 2")
    q = T // n_blocks
    if q <= max(purge_days + 1, 2):
        raise ValueError(f"series too short: {T} rows / {n_blocks} blocks")
    R = R[: q * n_blocks]
    blocks = [R[i * q:(i + 1) * q][purge_days:] for i in range(n_blocks)]

    def _sr(a: np.ndarray) -> np.ndarray:
        mu = np.nanmean(a, axis=0)
        sd = np.nanstd(a, axis=0, ddof=1)
        sd = np.where(sd > 0, sd, np.nan)
        return mu / sd

    logits: list[float] = []
    oos_ranks: list[float] = []
    for is_idx in combinations(range(n_blocks), n_blocks // 2):
        oos_idx = [b for b in range(n_blocks) if b not in is_idx]
        IS = np.vstack([blocks[b] for b in is_idx])
        OOS = np.vstack([blocks[b] for b in oos_idx])
        is_sr = _sr(IS)
        oos_sr = _sr(OOS)
        if np.all(np.isnan(is_sr)):
            continue
        n_star = int(np.nanargmax(is_sr))
        ranks = rankdata(np.nan_to_num(oos_sr, nan=-np.inf))  # 1 = worst
        r = ranks[n_star]
        w = r / (M + 1.0)
        w = min(max(w, 1e-9), 1 - 1e-9)
        logits.append(float(math.log(w / (1.0 - w))))
        oos_ranks.append(float(r))

    logits_arr = np.asarray(logits)
    pbo = float(np.mean(logits_arr < 0.0)) if logits_arr.size else float("nan")
    return {
        "pbo": pbo,
        "n_splits": int(logits_arr.size),
        "logits": logits,
        "median_oos_rank": float(np.median(oos_ranks)) if oos_ranks else float("nan"),
    }


def _pbo_from_signal(
    resid_signal: pd.DataFrame,
    split: str,
    horizon: int,
    panel,
    n_surrogates: int = 12,
    seed: int = RANDOM_SEED,
) -> dict[str, Any]:
    """Gate-B PBO for a *single* candidate: build a return matrix from the
    residual's daily-IC series plus ``n_surrogates`` sign/phase-scrambled
    surrogates of the same signal, then run :func:`cscv_pbo`.

    Judgement call (the spec leaves "which strategies enter CSCV for one
    candidate" open): a genuine signal beats its own scrambles in-sample AND
    out-of-sample -> low PBO; noise does not -> PBO ~ 0.5.
    """
    rng = np.random.default_rng(seed)
    real = _window_daily_ic(
        resid_signal, SPLITS[split][0], SPLITS[split][1], horizon, panel
    )
    if len(real) < 40:
        return {"pbo": float("nan"), "n_splits": 0, "logits": [], "median_oos_rank": float("nan")}

    wide = _to_wide(resid_signal)
    cols = [real]
    for _ in range(n_surrogates):
        flip = pd.Series(rng.choice([-1.0, 1.0], size=wide.shape[1]), index=wide.columns)
        perm = rng.permutation(wide.shape[1])
        scr = wide.mul(flip, axis=1)
        scr = scr.iloc[:, perm]
        scr.columns = wide.columns
        s_ic = _window_daily_ic(scr, SPLITS[split][0], SPLITS[split][1], horizon, panel)
        cols.append(s_ic.reindex(real.index))
    mat = pd.concat(cols, axis=1).dropna()
    if len(mat) < 40 or mat.shape[1] < 2:
        return {"pbo": float("nan"), "n_splits": 0, "logits": [], "median_oos_rank": float("nan")}
    return cscv_pbo(mat.to_numpy(), n_blocks=8, purge_days=max(horizon, 1))


# ======================================================================= #
# 6.  Pre-registered sign                                                 #
# ======================================================================= #
def check_sign(pre_registered_sign: int, realized_sign: int) -> bool:
    """``True`` iff the realised direction matches what was committed *before any
    data was touched*.  A mismatch is a **thesis failure** — a hard reject, never
    an invitation to flip the sign and keep the idea.
    """
    return int(np.sign(pre_registered_sign)) == int(np.sign(realized_sign)) != 0


# ======================================================================= #
# 7.  Gate B — the load-bearing order                                     #
# ======================================================================= #
def gate_b(
    card: dict,
    book: Any,
    ledger: Ledger,
    signal: pd.DataFrame | None = None,
    *,
    split: str = "val_a",
    horizon: int | None = None,
    do_holdout_peek: bool = True,
    panel: tuple[pd.DataFrame, pd.DataFrame] | None = None,
) -> tuple[str, list[str], dict]:
    """Run Gate B and return ``(verdict, reasons, audit)``.

    Order (load-bearing — never reversed):
      1. orthogonalise the signal against ``book``          -> residual
      2. novelty: |residual RankIC| >= MIN_MARGINAL_IC      (free; kills clones)
      3. statistics on the RESIDUAL: Deflated Sharpe >= DSR_MIN, t > T_STAT_BAR,
         PBO <= PBO_MAX.  The DSR is deflated by the **effective** trial count
         over the **whole ledger** (within-thesis acts only as a floor).
      4. rationed HOLDOUT peek — only now, it is counted via ``ledger``, and it
         scores the **residual**, the same object steps 2-3 judged.

    ``signal`` is the evaluated ``date x symbol`` score frame.  It may instead be
    supplied as ``card["_signal"]``.  ``horizon`` defaults to
    ``card["thesis"]["horizon_days"]`` clamped to a supported horizon.

    ``verdict`` is ``"accept"`` or ``"reject"``.  ``reasons`` lists every failed
    check (empty on accept).  ``audit`` carries every measured number, shaped for
    the AlphaCard ``audit`` block.
    """
    reasons: list[str] = []
    if signal is None:
        signal = card.get("_signal")
    if signal is None:
        raise ValueError("gate_b needs a signal (arg or card['_signal'])")

    thesis = card.get("thesis", {})
    if horizon is None:
        h = int(thesis.get("horizon_days", 1) or 1)
        horizon = min(HORIZONS, key=lambda x: abs(x - h))
    pre_sign = int(card.get("pre_registered", {}).get("sign", 1) or 1)
    thesis_id = card.get("thesis_id")
    card_id = card.get("card_id", "unknown")

    feats, labels = panel if panel is not None else _bt._load_panel()
    panel = (feats, labels)

    audit: dict[str, Any] = {
        "gate_b_order": ["orthogonalize", "novelty", "statistics", "holdout_peek"],
        "split": split, "horizon": horizon, "pre_registered_sign": pre_sign,
    }

    # -- step 1: orthogonalise -----------------------------------------
    resid = orthogonalize(signal, book)
    book_frames = _book_to_frames(book)
    audit["book_size"] = len(book_frames)

    # -- step 2: novelty (free) --------------------------------------
    resid_ic = daily_rank_ic(resid, split, horizon, panel=panel)
    raw_ic = daily_rank_ic(signal, split, horizon, panel=panel)
    marg = float(resid_ic.mean()) if len(resid_ic) else float("nan")
    audit["marginal_ic"] = marg
    audit["raw_ic"] = float(raw_ic.mean()) if len(raw_ic) else float("nan")
    realized_sign = 1 if marg > 0 else -1
    audit["realized_sign"] = realized_sign

    if not np.isfinite(marg) or abs(marg) < MIN_MARGINAL_IC:
        reasons.append(
            f"novelty: |marginal_ic|={abs(marg):.4f} < {MIN_MARGINAL_IC} "
            f"(clone / no marginal information)"
        )
        return _finish(ledger, "reject", reasons, audit, thesis_id, card, resid_ic,
                       split, horizon)

    # pre-registered sign is checked on the residual's realised direction
    if not check_sign(pre_sign, realized_sign):
        reasons.append(
            f"pre-registered sign {pre_sign:+d} != realised {realized_sign:+d} "
            f"(thesis failure — hard reject)"
        )
        return _finish(ledger, "reject", reasons, audit, thesis_id, card, resid_ic,
                       split, horizon)

    # -- step 3: statistics ON THE RESIDUAL --------------------------
    oriented = resid_ic * pre_sign

    # Multiplicity is priced on the RUN-WIDE ledger, not just this thesis.  P10
    # promotes the best card across every thesis, so the population the winner
    # was maximised over is the global one; deflating only within the thesis
    # gives a brand-new thesis N=1 and therefore *no deflation at all*, however
    # much search preceded it.  The within-thesis count is kept as a floor
    # (PLAN_EXPLAINED C8-UPDATE: "within-thesis, not ONLY global") and both are
    # reported.  The count fed to the DSR is the *effective* one — clustering by
    # canonical-AST shape — never raw N, which is what step 2 of the spec exists
    # to avoid.
    this_ast = card.get("ast_canonical") or card.get("formula") or ""
    n_eff_thesis = effective_trial_count(
        ledger.trial_canonical_asts(thesis_id) + [this_ast]
    )
    n_eff_global = effective_trial_count(
        ledger.trial_canonical_asts(None) + [this_ast]
    )
    n_eff = max(n_eff_thesis, n_eff_global, 1.0)
    audit["n_trials_within_thesis"] = ledger.n_trials(thesis_id)
    audit["n_trials_global"] = ledger.n_trials()
    audit["n_trials_effective_thesis"] = n_eff_thesis
    audit["n_trials_effective_global"] = n_eff_global
    audit["n_trials_effective"] = n_eff

    dsr_block = dsr_from_ic_series(
        oriented, n_trials=n_eff, trial_irs=ledger.trial_irs(),
    )
    audit.update(
        deflated_sharpe=dsr_block["dsr"],
        t_stat=dsr_block["t_stat"],
        expected_max_sr=dsr_block["sr0"],
        ic_skew=dsr_block["skew"],
        ic_kurtosis=dsr_block["kurtosis"],
        n_days_scored=dsr_block["n_days"],
    )

    pbo_block = _pbo_from_signal(resid, split, horizon, panel)
    audit["pbo"] = pbo_block["pbo"]
    audit["pbo_n_splits"] = pbo_block["n_splits"]

    if dsr_block["n_days"] < MIN_DSR_SAMPLE:
        reasons.append(f"statistics: only {dsr_block['n_days']} scored days (< {MIN_DSR_SAMPLE})")
    if not np.isfinite(dsr_block["dsr"]) or dsr_block["dsr"] < DSR_MIN:
        reasons.append(
            f"statistics: deflated_sharpe={dsr_block['dsr']:.3f} < {DSR_MIN} "
            f"(t={dsr_block['t_stat']:.2f}, E[max SR]-adjusted)"
        )
    if not np.isfinite(dsr_block["t_stat"]) or abs(dsr_block["t_stat"]) < T_STAT_BAR:
        reasons.append(f"statistics: |t_stat|={abs(dsr_block['t_stat']):.2f} < {T_STAT_BAR}")
    if np.isfinite(pbo_block["pbo"]) and pbo_block["pbo"] > PBO_MAX:
        reasons.append(f"statistics: PBO={pbo_block['pbo']:.2f} > {PBO_MAX} (overfit)")

    if reasons:
        return _finish(ledger, "reject", reasons, audit, thesis_id, card, oriented,
                       split, horizon)

    # -- step 4: rationed HOLDOUT peek (counted) --------------------
    if do_holdout_peek:
        token = ledger.request_holdout_peek(card_id)
        if token is None:
            audit["holdout_peek_id"] = None
            reasons.append("holdout: peek budget exhausted — cannot confirm on HOLDOUT")
            return _finish(ledger, "reject", reasons, audit, thesis_id, card, oriented,
                           split, horizon)
        audit["holdout_peek_id"] = token["peek_id"]
        # Score the RESIDUAL, not the raw signal.  The fitness object is one
        # composite thing — "deflated, holdout-gated, ORTHOGONALISED marginal
        # IC" — so the confirmation has to be on the same object the novelty and
        # statistics steps judged.  Peeking on the raw signal would let a partial
        # clone be confirmed by the book it was supposed to be measured against,
        # and would leave the collapse check below comparing a raw holdout IC
        # with a residual VAL IC (mixed units, so it could never bite).
        audit["holdout_scored_on"] = "residual"
        try:
            hm = _bt.backtest(
                resid, "holdout", horizon=horizon,
                i_have_a_peek_token=True,
            )
        except Exception as exc:  # noqa: BLE001
            hm = {"rank_ic": float("nan"), "t_stat": float("nan"), "error": str(exc)}
        ledger.finalize_holdout_peek(token, hm)
        audit["holdout_rank_ic"] = hm.get("rank_ic")
        audit["holdout_t_stat"] = hm.get("t_stat")
        h_sign = 1 if (hm.get("rank_ic") or 0) > 0 else -1
        if not np.isfinite(hm.get("rank_ic", float("nan"))):
            reasons.append("holdout: rank_ic not finite")
        elif h_sign != pre_sign:
            reasons.append(
                f"holdout: rank_ic sign {h_sign:+d} != pre-registered {pre_sign:+d}"
            )
        elif abs(hm["rank_ic"]) < 0.3 * abs(audit["marginal_ic"]):
            reasons.append(
                f"holdout: rank_ic={hm['rank_ic']:.4f} collapsed vs val marginal "
                f"{audit['marginal_ic']:.4f}"
            )
    else:
        audit["holdout_peek_id"] = None

    verdict = "reject" if reasons else "accept"
    return _finish(ledger, verdict, reasons, audit, thesis_id, card, oriented,
                   split, horizon)


def _finish(ledger, verdict, reasons, audit, thesis_id, card, ic_series, split, horizon):
    """Record the Gate-B evaluation as ONE selection trial and return the tuple."""
    ic = pd.Series(ic_series).dropna()
    sd = float(ic.std(ddof=1)) if len(ic) > 1 else float("nan")
    mean_ic = float(ic.mean()) if len(ic) else float("nan")
    t_stat = (mean_ic / (sd / math.sqrt(len(ic)))) if sd and np.isfinite(sd) and sd > 0 else float("nan")
    ledger.record_trial(
        thesis_id=thesis_id,
        formula_hash=card.get("pre_registered", {}).get("hash") or card.get("card_id"),
        canonical_ast=card.get("ast_canonical") or card.get("formula"),
        split_used=split,
        rank_ic=mean_ic,
        sharpe=float("nan"),
        t_stat=t_stat,
        n_days=int(len(ic)),
        counts_as_trial=1,
        rejection_reason=None if verdict == "accept" else "; ".join(reasons)[:500],
    )
    audit["verdict"] = verdict
    return verdict, reasons, audit
