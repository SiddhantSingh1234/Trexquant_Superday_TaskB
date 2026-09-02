"""Phase 5 — the causal operator library.

Every formula the Coder agent (P8) builds is assembled from the operators in
this module.  It is a **safety feature, not a convenience**:

    Every time-series operator is *strictly trailing*.  Changing a FUTURE input
    value must never change an EARLIER output value.

That property is asserted for every operator in ``tests/test_p5_operators.py``
(the mandatory causality test).  It is what makes formula-level look-ahead
*structurally impossible* rather than *hopefully caught*.  If an operator cannot
pass that test, it does not belong here.

Data model
----------
Operators act on **wide ``date x symbol`` DataFrames** (index = sorted dates,
columns = symbols) — the same shape the P4 backtester consumes — or on plain
Python scalars for the element-wise ops (``mul(volume, close)``, ``add(x, 1)``).

Guards
------
``div`` and ``log`` return ``NaN`` on divide-by-zero / non-positive input and
never raise.  ``pow`` returns ``NaN`` for a negative base with a non-integer
exponent.

Determinism
-----------
No RNG is used anywhere in this module; ``numpy``/``random`` are seeded at import
purely per the Section 0.6 convention.

Derived-field idioms (documented for the Coder agent — not operators)
--------------------------------------------------------------------
* ``adv{d}`` (Alpha101 average daily dollar volume)  ->  ``ts_mean(mul(volume, close), d)``
* ``IndNeutralize(x, IndClass.*)``                    ->  ``sector_neutral(x, sector)``
  (our 22 NSE industries are coarser than Alpha101's sub-industry, but the
  operation is identical and remains valid)
* ``avg_trade_size``                                  ->  ``div(volume, n_trades)``
"""
from __future__ import annotations

import operator as _op
import random

import numpy as np
import pandas as pd

# Section 0.6 — seed defensively even though nothing here samples.
np.random.seed(42)
random.seed(42)

# --------------------------------------------------------------------------- #
# Field table — the only bare names a formula may reference                    #
# --------------------------------------------------------------------------- #
FIELDS: frozenset[str] = frozenset({
    "open", "high", "low", "close", "volume", "vwap", "returns",
    "n_trades", "delivery_pct", "size_proxy", "sector",
    "close_raw", "volume_raw",
})


# --------------------------------------------------------------------------- #
# Internal helpers                                                             #
# --------------------------------------------------------------------------- #
def _is_df(x) -> bool:
    return isinstance(x, pd.DataFrame)


def _binary(a, b, f):
    """Apply ``f(x, y)`` element-wise, aligning two frames on the union axes."""
    if _is_df(a) and _is_df(b):
        if not (a.index.equals(b.index) and a.columns.equals(b.columns)):
            a, b = a.align(b)
    return f(a, b)


def _window(d) -> int:
    d = int(d)
    if d < 1:
        raise ValueError(f"time-series window must be >= 1, got {d}")
    return d


def _roll_apply(x: pd.DataFrame, d, func) -> pd.DataFrame:
    d = _window(d)
    return x.rolling(d, min_periods=d).apply(func, raw=True)


def _sector_frame(sector, like: pd.DataFrame) -> pd.DataFrame:
    """Coerce a sector map (Series symbol->label, or a frame) to ``like``'s shape."""
    if _is_df(sector):
        return sector.reindex(index=like.index, columns=like.columns)
    if isinstance(sector, pd.Series):
        row = sector.reindex(like.columns)
        return pd.DataFrame(
            np.repeat(row.to_numpy()[None, :], len(like.index), axis=0),
            index=like.index, columns=like.columns,
        )
    raise TypeError("sector must be a DataFrame or a Series indexed by symbol")


# --------------------------------------------------------------------------- #
# Cross-sectional operators (same-day; no time axis touched -> causal)         #
# --------------------------------------------------------------------------- #
def rank(x: pd.DataFrame) -> pd.DataFrame:
    """Per-day cross-sectional rank scaled to ``(0, 1]``.  NaN stays NaN."""
    return x.rank(axis=1, pct=True)


def scale(x: pd.DataFrame, a: float = 1.0) -> pd.DataFrame:
    """Rescale each day so ``sum(abs(x)) == a`` (Alpha101 ``scale``)."""
    denom = x.abs().sum(axis=1).replace(0.0, np.nan)
    return x.div(denom, axis=0) * float(a)


def demean_cs(x: pd.DataFrame) -> pd.DataFrame:
    """Subtract the per-day cross-sectional mean."""
    return x.sub(x.mean(axis=1), axis=0)


def zscore_cs(x: pd.DataFrame) -> pd.DataFrame:
    """Per-day cross-sectional z-score (population std)."""
    sd = x.std(axis=1, ddof=0).replace(0.0, np.nan)
    return x.sub(x.mean(axis=1), axis=0).div(sd, axis=0)


def sector_neutral(x: pd.DataFrame, sector) -> pd.DataFrame:
    """Subtract the per-day mean *within each sector* (Alpha101 IndNeutralize)."""
    sec = _sector_frame(sector, x)
    xl = x.stack(future_stack=True)
    sl = sec.stack(future_stack=True)
    grp = xl.groupby([xl.index.get_level_values(0), sl.to_numpy()])
    res = xl - grp.transform("mean")
    return res.unstack()


# --------------------------------------------------------------------------- #
# Time-series operators (STRICTLY TRAILING — this is the safety contract)      #
# --------------------------------------------------------------------------- #
def delay(x: pd.DataFrame, d) -> pd.DataFrame:
    """Value ``d`` trading days ago."""
    return x.shift(_window(d))


def delta(x: pd.DataFrame, d) -> pd.DataFrame:
    """``x_t - x_{t-d}``."""
    return x - x.shift(_window(d))


def ts_mean(x: pd.DataFrame, d) -> pd.DataFrame:
    d = _window(d)
    return x.rolling(d, min_periods=d).mean()


def ts_std(x: pd.DataFrame, d) -> pd.DataFrame:
    d = _window(d)
    return x.rolling(d, min_periods=d).std(ddof=1)


def ts_min(x: pd.DataFrame, d) -> pd.DataFrame:
    d = _window(d)
    return x.rolling(d, min_periods=d).min()


def ts_max(x: pd.DataFrame, d) -> pd.DataFrame:
    d = _window(d)
    return x.rolling(d, min_periods=d).max()


def ts_sum(x: pd.DataFrame, d) -> pd.DataFrame:
    d = _window(d)
    return x.rolling(d, min_periods=d).sum()


def _f_ts_rank(a: np.ndarray) -> float:
    last = a[-1]
    if np.isnan(last):
        return np.nan
    valid = a[~np.isnan(a)]
    if valid.size == 0:
        return np.nan
    return float(np.sum(valid <= last) / valid.size)


def ts_rank(x: pd.DataFrame, d) -> pd.DataFrame:
    """Trailing-window rank of today's value, in ``(0, 1]``."""
    return _roll_apply(x, d, _f_ts_rank)


def _f_ts_argmax(a: np.ndarray) -> float:
    if np.all(np.isnan(a)):
        return np.nan
    return float((len(a) - 1) - int(np.nanargmax(a)))


def ts_argmax(x: pd.DataFrame, d) -> pd.DataFrame:
    """Trading days since the trailing-window maximum (0 == today is the max)."""
    return _roll_apply(x, d, _f_ts_argmax)


def _f_decay_linear(a: np.ndarray) -> float:
    w = np.arange(1, len(a) + 1, dtype=float)  # most-recent day gets weight d
    m = ~np.isnan(a)
    if not m.any():
        return np.nan
    return float(np.sum(a[m] * w[m]) / np.sum(w[m]))


def decay_linear(x: pd.DataFrame, d) -> pd.DataFrame:
    """Linearly-weighted trailing moving average (recent days weigh more)."""
    return _roll_apply(x, d, _f_decay_linear)


def _f_ts_product(a: np.ndarray) -> float:
    m = ~np.isnan(a)
    if not m.any():
        return np.nan
    return float(np.prod(a[m]))


def ts_product(x: pd.DataFrame, d) -> pd.DataFrame:
    """Trailing-window product (Alpha101 ``product`` — unlocks #29)."""
    return _roll_apply(x, d, _f_ts_product)


def correlation(x: pd.DataFrame, y: pd.DataFrame, d) -> pd.DataFrame:
    """Trailing-window Pearson correlation, column-wise."""
    d = _window(d)
    if _is_df(x) and _is_df(y) and not (
        x.index.equals(y.index) and x.columns.equals(y.columns)
    ):
        x, y = x.align(y)
    return x.rolling(d, min_periods=d).corr(y)


def covariance(x: pd.DataFrame, y: pd.DataFrame, d) -> pd.DataFrame:
    """Trailing-window sample covariance, column-wise."""
    d = _window(d)
    if _is_df(x) and _is_df(y) and not (
        x.index.equals(y.index) and x.columns.equals(y.columns)
    ):
        x, y = x.align(y)
    return x.rolling(d, min_periods=d).cov(y)


# --------------------------------------------------------------------------- #
# Element-wise operators (trivially causal — no time axis)                     #
# --------------------------------------------------------------------------- #
def add(a, b):
    return _binary(a, b, _op.add)


def sub(a, b):
    return _binary(a, b, _op.sub)


def mul(a, b):
    return _binary(a, b, _op.mul)


def div(a, b):
    """``a / b`` with a divide-by-zero guard (-> NaN, never raises)."""
    def f(x, y):
        if _is_df(y):
            y = y.replace(0.0, np.nan)
        elif y == 0:
            return (x * np.nan) if _is_df(x) else float("nan")
        with np.errstate(divide="ignore", invalid="ignore"):
            return x / y
    return _binary(a, b, f)


def pow(a, b):  # noqa: A001 - deliberate Alpha101 name
    """``a ** b``; NaN for a negative base with a non-integer exponent."""
    def f(x, y):
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.power(x, y)
        return r
    return _binary(a, b, f)


def log(x):  # noqa: A001
    """Natural log; NaN where ``x <= 0`` (never raises)."""
    if _is_df(x):
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.log(x.where(x > 0))
    return float(np.log(x)) if x is not None and x > 0 else float("nan")


def abs(x):  # noqa: A001
    return np.abs(x)


def sign(x):
    return np.sign(x)


def signed_power(x, a):
    """``sign(x) * abs(x) ** a`` (Alpha101 ``SignedPower``)."""
    return sign(x) * pow(abs(x), a)


def min(a, b):  # noqa: A001 - element-wise pairwise min (NOT ts_min)
    return _binary(a, b, np.minimum)


def max(a, b):  # noqa: A001 - element-wise pairwise max (NOT ts_max)
    return _binary(a, b, np.maximum)


def _cmp(a, b, comp):
    def f(x, y):
        r = comp(x, y)
        if _is_df(x) or _is_df(y):
            valid = pd.notna(x) & pd.notna(y)
            return r.astype(float).where(valid)
        if pd.isna(x) or pd.isna(y):
            return float("nan")
        return 1.0 if r else 0.0
    return _binary(a, b, f)


def lt(a, b):
    return _cmp(a, b, _op.lt)


def gt(a, b):
    return _cmp(a, b, _op.gt)


def le(a, b):
    return _cmp(a, b, _op.le)


def ge(a, b):
    return _cmp(a, b, _op.ge)


def eq(a, b):
    return _cmp(a, b, _op.eq)


def if_else(cond, a, b):
    """Element-wise select: ``a`` where ``cond`` is truthy, else ``b``.

    ``cond`` may be a boolean frame (from ``lt``/``gt``/...), a numeric frame
    (truthy where ``> 0``), or a scalar.  NaN in ``cond`` propagates to NaN.
    Trivially causal — it is element-wise.  Unlocks Alpha101 #1, 7, 9, 10, 21,
    23, 24, 27, 46, 49, 51.
    """
    if not _is_df(cond):
        if pd.isna(cond):
            truthy = False
        elif isinstance(cond, (bool, np.bool_)):
            truthy = bool(cond)
        else:
            truthy = cond > 0
        return a if truthy else b

    frame = cond

    def _bc(v):
        if _is_df(v):
            if v.index.equals(frame.index) and v.columns.equals(frame.columns):
                return v
            return v.reindex(index=frame.index, columns=frame.columns)
        return pd.DataFrame(float(v), index=frame.index, columns=frame.columns)

    A, B = _bc(a), _bc(b)
    if str(cond.to_numpy().dtype) == "bool":
        mask = cond.fillna(False)
        valid = pd.DataFrame(True, index=frame.index, columns=frame.columns)
    else:
        mask = cond > 0
        valid = cond.notna()
    return A.where(mask, B).where(valid)


# --------------------------------------------------------------------------- #
# Registry                                                                     #
# --------------------------------------------------------------------------- #
CROSS_SECTIONAL_OPS: frozenset[str] = frozenset({
    "rank", "scale", "zscore_cs", "demean_cs", "sector_neutral",
})

TIME_SERIES_OPS: frozenset[str] = frozenset({
    "delay", "delta", "ts_mean", "ts_std", "ts_min", "ts_max", "ts_rank",
    "ts_sum", "ts_argmax", "ts_product", "decay_linear",
    "correlation", "covariance",
})

ELEMENTWISE_OPS: frozenset[str] = frozenset({
    "add", "sub", "mul", "div", "pow", "log", "abs", "sign",
    "min", "max", "signed_power", "if_else",
    "lt", "gt", "le", "ge", "eq",
})

OPERATORS: dict = {
    # cross-sectional
    "rank": rank, "scale": scale, "zscore_cs": zscore_cs,
    "demean_cs": demean_cs, "sector_neutral": sector_neutral,
    # time-series
    "delay": delay, "delta": delta, "ts_mean": ts_mean, "ts_std": ts_std,
    "ts_min": ts_min, "ts_max": ts_max, "ts_rank": ts_rank, "ts_sum": ts_sum,
    "ts_argmax": ts_argmax, "ts_product": ts_product, "decay_linear": decay_linear,
    "correlation": correlation, "covariance": covariance,
    # element-wise
    "add": add, "sub": sub, "mul": mul, "div": div, "pow": pow, "log": log,
    "abs": abs, "sign": sign, "min": min, "max": max,
    "signed_power": signed_power, "if_else": if_else,
    "lt": lt, "gt": gt, "le": le, "ge": ge, "eq": eq,
}

# Commutative operators — canonicalization sorts their operands.
COMMUTATIVE_OPS: frozenset[str] = frozenset({"add", "mul", "min", "max", "eq"})
# Symmetric in their first two args only (the trailing window stays last).
SYMMETRIC_HEAD_OPS: frozenset[str] = frozenset({"correlation", "covariance"})
# Pure arithmetic — foldable when every operand is a constant.
ARITH_OPS: frozenset[str] = frozenset({"add", "sub", "mul", "div", "pow"})

assert set(OPERATORS) == CROSS_SECTIONAL_OPS | TIME_SERIES_OPS | ELEMENTWISE_OPS
