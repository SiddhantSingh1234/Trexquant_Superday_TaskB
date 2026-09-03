"""Phase 9 — the Red-Team falsification menu.

The Red-Team's job is to **destroy** the candidate.  An LLM agent (Phase 8,
``src/agents/redteam.py``) decides *which* of these eleven attacks fit a given
signal; **the attacks themselves are the pre-written, parameterized backtests in
this module.**  The agent never writes free-form code — that is what keeps every
attack reproducible.

All eleven are **REJECTION-ONLY**: they can kill a candidate but can never
promote one.  A filter that only rejects cannot raise the false-discovery rate,
so every backtest fired here is recorded in the ledger with
``counts_as_trial=0``.  This is the answer to *"doesn't running 11 backtests per
candidate blow up your trial count?"* — it does not, by construction.

The eleven tests
----------------
====  ==================  ===========================================  ==========
 #    name                what it does                                 kind
====  ==================  ===========================================  ==========
 1    subsample_year      one backtest per calendar year               decisive
 2    regime_split        bull / bear / high-vol subsamples            decisive
 3    size_tercile        by ``size_proxy`` tercile (trailing          diagnostic
                          turnover, NOT market cap)
 4    cost_sweep          ``cost_bps in {5, 15, 30}``                   decisive
 5    extra_lag           ``extra_lag=1`` (global one-day shift)        decisive
 6    delivery_lag        shift ONLY ``delivery_pct`` by one day        diagnostic
 7    sector_neutral      ``neutralize="sector"``                       diagnostic
 8    liquidity_filter    ``min_turnover`` floor                        diagnostic
 9    decay_curve         RankIC at h in {1,2,3,5,10,21}                diagnostic
 10   sign_stability      sign of RankIC per fold                       decisive
 11   universe_edge       drop the names ranked 150-200 by liquidity   diagnostic
                          that month
====  ==================  ===========================================  ==========

Survive rule (IMPLEMENTATION_PLAN.md Phase 9).  Survives **iff**:

* RankIC stays positive and significant across tests **1, 2, 5**;
* does not collapse (> 50 % degradation) under test **4** at 15 bps or test **5**;
* test **10** shows a consistent sign in >= 70 % of folds.

Tests 3, 6, 7, 8, 9, 11 are **diagnostic** — they are run and their flags are
reported in ``flagged_diagnostics``, but they do not by themselves flip the
verdict.  (Test 6 is the more *diagnostic* half of the look-ahead probe: if
RankIC survives a global one-day lag but collapses when only ``delivery_pct``
moves, the dependency has been **localized** to the one field whose availability
timing is genuinely ambiguous.)

Regime labels (test 2) come from the backtester's ``_regime_labels`` —
**EXPANDING-window only** (a full-sample volatility threshold is look-ahead; the
one that used to live in P4 was fixed at source).  The red-team just calls
``backtest(subsample={"regime": "bull"|"bear"|"highvol"})``.

Test 11 (``universe_edge``) reads P1's
``data/universe/liquidity_ranks.parquet`` to find the names ranked 150-200 by
trailing liquidity that month; it recomputes the ranking from the price panel
only when that file is absent or its symbols don't match the signal.

Two implementation notes for the slides / plan:
* The five :data:`DECISIVE_TESTS` (1, 2, 4, 5, 10) **always run**, unioned with
  whatever the agent selected — a falsification gate a candidate can opt out of
  is not one.  ``forced_decisive_tests`` in the result names any the agent skipped.
* Test 4's kill rule is *"net book unprofitable at 15 bps, OR Sharpe cut > 50 %
  AND the surviving Sharpe < 0.5"* — a strong signal that merely halves its
  Sharpe under cost is still tradeable; the red-team culls false discoveries,
  not legitimate turnover.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from . import backtester as _bt
from .config import (
    LIQUIDITY_RANKS_PARQUET,
    OHLCV_PARQUET,
    RANDOM_SEED,
    split_mask,
)
from .contracts import HORIZONS

# Determinism (Section 0.6).  Nothing here samples, but seed defensively.
np.random.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)

# --------------------------------------------------------------------------- #
# The fixed menu                                                               #
# --------------------------------------------------------------------------- #
REDTEAM_MENU: tuple[str, ...] = (
    "subsample_year", "regime_split", "size_tercile", "cost_sweep", "extra_lag",
    "delivery_lag", "sector_neutral", "liquidity_filter", "decay_curve",
    "sign_stability", "universe_edge",
)

#: The tests the survive/kill rule is defined over.  These are always run — a
#: red-team you can opt out of is not a red-team — even when the agent's
#: selection omits one (documented judgement call, reports/p9_handoff.md §7).
DECISIVE_TESTS: tuple[str, ...] = (
    "subsample_year", "regime_split", "cost_sweep", "extra_lag", "sign_stability",
)

# Thresholds.  The full-sample statistical bar is T_STAT_BAR = 3.0; red-team
# sub-samples are smaller, so a softer significance floor is used and disclosed.
RT_SIG_T: float = 1.5           # |t| floor for a sub-sample RankIC to "count"
COLLAPSE: float = 0.5           # > 50 % degradation == "collapse"
MIN_FOLD_DAYS: int = 40         # a year / regime fold below this is "insufficient"
MIN_REGIME_DAYS: int = 60       # bull & bear both need this many days to be decisive
SIGN_CONSISTENCY_MIN: float = 0.70
MIN_UNIVERSE_FOR_150_200: int = 200   # else use a proportional bottom band

# Regime labels for test 2 come from the backtester's ``_regime_labels`` —
# EXPANDING-window only (the look-ahead in P4's old full-sample-median threshold
# was fixed at source; see tests/test_p4_backtester.py::
# test_regime_labels_are_expanding_window_only).  The red-team no longer keeps
# its own copy.
REGIME_TESTS: tuple[str, ...] = ("bull", "bear", "highvol")


# --------------------------------------------------------------------------- #
# Context + ledger-recording backtest runner                                   #
# --------------------------------------------------------------------------- #
@dataclass
class _Runner:
    """Wraps ``backtester.backtest`` and logs every call as a non-trial."""

    split: str
    horizon: int
    ledger: Any = None
    thesis_id: str | None = None
    formula_hash: str | None = None
    canonical_ast: str | None = None
    n_calls: int = 0

    def run(self, signal: pd.DataFrame, *, reason: str, **kw: Any) -> dict:
        m = _bt.backtest(signal, self.split, horizon=self.horizon, **kw)
        self.n_calls += 1
        if self.ledger is not None:
            self.ledger.record_trial(
                self.thesis_id, self.formula_hash, self.canonical_ast,
                self.split, m.get("rank_ic"), m.get("sharpe"), m.get("t_stat"),
                m.get("n_days"),
                0,                       # counts_as_trial — REJECTION-ONLY, always 0
                f"redteam:{reason}",
            )
        return m


@dataclass
class RedTeamContext:
    signal: pd.DataFrame                       # wide date x symbol (already oriented)
    split: str = "val_a"
    horizon: int = 5
    sign: int = 1
    formula: str | None = None
    panel: dict[str, pd.DataFrame] | None = None       # for test 6
    prices: pd.DataFrame | None = None                 # ohlcv-like, test 11 fallback
    liquidity_ranks: pd.DataFrame | None = None        # P1 rank frame, test 11
    runner: _Runner = field(default=None)              # type: ignore[assignment]
    baseline: dict = field(default_factory=dict)


def _wide(signal: pd.DataFrame) -> pd.DataFrame:
    """Coerce a long ``date,symbol,<v>`` or wide frame to a wide date x symbol."""
    if {"date", "symbol"}.issubset(signal.columns):
        val = [c for c in signal.columns if c not in ("date", "symbol")][0]
        w = signal.pivot_table(index="date", columns="symbol", values=val)
    else:
        w = signal.copy()
    w.index = pd.DatetimeIndex(pd.to_datetime(w.index)).normalize()
    return w.sort_index()


_RANKING_CACHE: dict[tuple, dict] = {}


def _fringe_from_ranks(ranks: pd.DataFrame, sig_syms: set[str]):
    """``(bounds ndarray sorted, [fringe set per bound])`` from a P1-shaped
    ``month_end · symbol · liquidity_rank`` frame — ranks 150-200 that month
    (or a proportional bottom band when the month has < 200 names)."""
    bounds, fringes = [], []
    for me, grp in ranks.sort_values("liquidity_rank").groupby("month_end"):
        syms = grp["symbol"].tolist()               # already rank-ordered
        n = len(syms)
        if n >= MIN_UNIVERSE_FOR_150_200:
            fr = set(syms[149:200])
        else:
            cut = int(round(n * (150 / 200)))
            fr = set(syms[cut:])
        bounds.append(np.datetime64(pd.Timestamp(me)))
        fringes.append(fr & sig_syms)
    order = np.argsort(bounds)
    return np.array(bounds)[order], [fringes[i] for i in order]


def _liquidity_fringe(ctx: "RedTeamContext"):
    """Per-governing-month fringe (names ranked 150-200 by trailing liquidity).

    Source order:
      1. ``ctx.liquidity_ranks`` (a P1-shaped frame passed in), or
      2. ``data/universe/liquidity_ranks.parquet`` on disk (P1's output),
         when its symbols overlap the signal;
      3. otherwise recompute from the price panel via ``universe.compute_selection``
         (fixture / no-P1 fallback).

    Returns ``(bounds, fringes, source_str)`` or ``None`` if nothing is available.
    """
    sig_syms = set(map(str, ctx.signal.columns))

    ranks = ctx.liquidity_ranks
    if ranks is None and LIQUIDITY_RANKS_PARQUET.exists():
        ranks = pd.read_parquet(LIQUIDITY_RANKS_PARQUET)
    if ranks is not None and not sig_syms.isdisjoint(set(map(str, ranks["symbol"]))):
        b, f = _fringe_from_ranks(ranks, sig_syms)
        return b, f, ("data/universe/liquidity_ranks.parquet — P1's per-symbol "
                      "monthly trailing-liquidity rank (the ranking behind "
                      "universe_stats.parquet's turnover_cutoff_200)")

    prices = _load_prices(ctx.prices)
    if prices is None:
        return None
    col = "close_raw" if "close_raw" in prices.columns else prices.columns[-1]
    key = (len(prices), str(prices["date"].min()), str(prices["date"].max()),
           int(prices["symbol"].nunique()),
           round(float(pd.to_numeric(prices[col], errors="coerce").sum()), 3))
    if key not in _RANKING_CACHE:
        from . import universe as _uni

        _RANKING_CACHE[key] = _uni.compute_selection(prices)
    sels = [s for s in _RANKING_CACHE[key]["selections"] if s["n_members"] > 0]
    if not sels:
        return None
    bounds, fringes = [], []
    for s in sels:
        syms = s["symbols"]                          # rank-ordered, turnover-desc
        if len(syms) >= MIN_UNIVERSE_FOR_150_200:
            fr = set(syms[149:200])
        else:
            cut = int(round(len(syms) * (150 / 200)))
            fr = set(syms[cut:])
        bounds.append(np.datetime64(pd.Timestamp(s["month_end"])))
        fringes.append(fr & sig_syms)
    return (np.array(bounds), fringes,
            "universe.compute_selection(prices) [fallback: P1 rank file "
            "unavailable or symbol-mismatched — same trailing-63d-median-turnover "
            "rule]")


def _load_prices(prices: pd.DataFrame | None) -> pd.DataFrame | None:
    if prices is not None:
        return prices
    if OHLCV_PARQUET.exists():
        return pd.read_parquet(
            OHLCV_PARQUET, columns=["date", "symbol", "close_raw", "volume_raw"]
        )
    return None


def _sig_dates_in_split(ctx: RedTeamContext) -> pd.DatetimeIndex:
    idx = ctx.signal.index
    return idx[split_mask(idx, ctx.split)]


# --------------------------------------------------------------------------- #
# The eleven tests                                                             #
# --------------------------------------------------------------------------- #
def _fold_years(ctx: RedTeamContext) -> list[int]:
    yrs = sorted({d.year for d in _sig_dates_in_split(ctx)})
    return yrs


def test_subsample_year(ctx: RedTeamContext) -> dict:
    """#1 — 'it was one lucky year'.  Kill if dropping the single best year
    collapses the RankIC (> 50 %) or destroys its significance."""
    base_ic = ctx.baseline["rank_ic"]
    years = _fold_years(ctx)
    per_year = {}
    for y in years:
        m = ctx.runner.run(ctx.signal, reason=f"subsample_year:{y}",
                           subsample={"years": [y]})
        per_year[y] = {"rank_ic": m["rank_ic"], "t_stat": m["t_stat"],
                       "n_days": m["n_days"]}
    usable = {y: v for y, v in per_year.items() if v["n_days"] >= MIN_FOLD_DAYS}
    detail: dict[str, Any] = {"per_year": per_year, "base_rank_ic": base_ic,
                              "n_usable_years": len(usable)}
    if len(usable) < 3 or base_ic <= 0:
        detail["reason"] = "insufficient usable years" if len(usable) < 3 \
            else "baseline RankIC not positive"
        detail["flag"] = base_ic <= 0
        return detail

    best_y = max(usable, key=lambda y: usable[y]["rank_ic"])
    keep = [y for y in usable if y != best_y]
    m_ex = ctx.runner.run(ctx.signal, reason="subsample_year:drop_best",
                          subsample={"years": keep})
    detail["dropped_year"] = best_y
    detail["rank_ic_without_best_year"] = m_ex["rank_ic"]
    detail["t_stat_without_best_year"] = m_ex["t_stat"]
    collapsed = m_ex["rank_ic"] < COLLAPSE * base_ic or m_ex["rank_ic"] <= 0
    lost_sig = abs(m_ex["t_stat"]) < RT_SIG_T
    n_pos = sum(1 for v in usable.values() if v["rank_ic"] > 0)
    detail["frac_positive_years"] = n_pos / len(usable)
    detail["flag"] = bool(collapsed and lost_sig) or detail["frac_positive_years"] < 0.5
    return detail


def test_regime_split(ctx: RedTeamContext) -> dict:
    """#2 — 'only works in a bull market'.  Score the signal inside each regime
    via the backtester's ``subsample={"regime": ...}`` (EXPANDING-window labels,
    fixed at P4 source).  Kill if RankIC is <= 0 in bull or in bear when each has
    enough days."""
    base_ic = ctx.baseline["rank_ic"]
    out: dict[str, Any] = {
        "base_rank_ic": base_ic, "regimes": {},
        "labeller": "backtester._regime_labels — expanding-window "
        "(63d compounded return +/-5%; vol21 vs expanding tercile/median)",
    }
    for name in REGIME_TESTS:
        m = ctx.runner.run(ctx.signal, reason=f"regime_split:{name}",
                           subsample={"regime": name})
        out["regimes"][name] = {"rank_ic": m["rank_ic"], "t_stat": m["t_stat"],
                                "n_days": m["n_days"]}

    bull, bear = out["regimes"]["bull"], out["regimes"]["bear"]
    both_ok = (bull["n_days"] >= MIN_REGIME_DAYS and bear["n_days"] >= MIN_REGIME_DAYS)
    out["decisive_comparable"] = both_ok
    if not both_ok:
        out["reason"] = "bull and/or bear regime has too few days to be decisive"
        out["flag"] = False
        return out
    out["flag"] = bool(bull["rank_ic"] <= 0 or bear["rank_ic"] <= 0)
    return out


def test_size_tercile(ctx: RedTeamContext) -> dict:
    """#3 — 'it's a small-cap artefact'.  Uses the trailing-turnover
    ``size_proxy`` tercile, NOT market cap (current shares outstanding applied to
    2015 is a look-ahead — P2 step 4c)."""
    base_ic = ctx.baseline["rank_ic"]
    terc = {}
    for t in ("small", "mid", "large"):
        m = ctx.runner.run(ctx.signal, reason=f"size_tercile:{t}",
                           subsample={"size_tercile": t})
        terc[t] = {"rank_ic": m["rank_ic"], "t_stat": m["t_stat"],
                   "n_obs": m["n_obs"]}
    small, mid, large = terc["small"], terc["mid"], terc["large"]
    concentrated = (
        small["rank_ic"] > 0 and abs(small["t_stat"]) >= RT_SIG_T
        and large["rank_ic"] <= 0
        and mid["rank_ic"] < COLLAPSE * small["rank_ic"]
    )
    return {"terciles": terc, "base_rank_ic": base_ic,
            "flag": bool(concentrated), "kind": "size_proxy (trailing turnover)"}


def test_cost_sweep(ctx: RedTeamContext) -> dict:
    """#4 — 'great gross, loses money net'.  Kill if net Sharpe at 15 bps is <= 0
    or collapses > 50 % from the gross Sharpe."""
    s0 = ctx.baseline["sharpe"]
    sweep = {0: {"sharpe": s0, "ann_return": ctx.baseline["ann_return"]}}
    for c in (5, 15, 30):
        m = ctx.runner.run(ctx.signal, reason=f"cost_sweep:{c}bps", cost_bps=float(c))
        sweep[c] = {"sharpe": m["sharpe"], "ann_return": m["ann_return"],
                    "turnover": m["turnover"]}
    s15 = sweep[15]["sharpe"]
    ann15 = sweep[15]["ann_return"]
    # "great gross, loses money net": kill if the net book is unprofitable at
    # 15 bps, OR the Sharpe is cut > 50 % AND what survives is itself weak
    # (< 0.5).  A strong signal that merely halves is still tradeable — the
    # red-team taxes false discoveries, not legitimate turnover (judgement call,
    # reports/p9_handoff.md §7).
    collapsed = (
        (not np.isfinite(s15)) or s15 <= 0 or ann15 <= 0
        or (np.isfinite(s0) and s0 > 0 and s15 < COLLAPSE * s0 and s15 < 0.5)
    )
    return {"sweep": sweep, "gross_sharpe": s0, "net_sharpe_15bps": s15,
            "net_ann_return_15bps": ann15, "flag": bool(collapsed)}


def test_extra_lag(ctx: RedTeamContext) -> dict:
    """#5 — hidden look-ahead.  Kill if a global one-day lag drives RankIC to
    <= 0, kills its significance, or collapses it > 50 %."""
    base_ic = ctx.baseline["rank_ic"]
    m = ctx.runner.run(ctx.signal, reason="extra_lag:1", extra_lag=1)
    ic_lag = m["rank_ic"]
    collapsed = (
        ic_lag <= 0
        or abs(m["t_stat"]) < RT_SIG_T
        or (base_ic > 0 and ic_lag < COLLAPSE * base_ic)
    )
    return {"base_rank_ic": base_ic, "rank_ic_lagged": ic_lag,
            "t_stat_lagged": m["t_stat"],
            "degradation": None if base_ic == 0 else 1.0 - ic_lag / base_ic,
            "flag": bool(collapsed)}


def test_delivery_lag(ctx: RedTeamContext) -> dict:
    """#6 — which field is the edge leaning on?  Shift ONLY ``delivery_pct`` by
    one trading day, re-evaluate the formula, re-score.  More diagnostic than
    #5: if the signal survives a global lag but dies here, the dependency is
    **localized** to ``delivery_pct``."""
    if not ctx.formula or ctx.panel is None:
        return {"ran": False, "reason": "no formula / panel supplied", "flag": False}
    fields = _formula_fields(ctx.formula)
    if "delivery_pct" not in fields:
        return {"ran": False, "reason": "formula does not use delivery_pct",
                "flag": False, "fields_used": fields}

    from .ast_tools import evaluate

    panel2 = dict(ctx.panel)
    dp = _wide(_panel_frame(ctx.panel["delivery_pct"]))
    panel2["delivery_pct"] = dp.shift(1)             # value available one day late
    try:
        new_sig = ctx.sign * _wide(_panel_frame(evaluate(ctx.formula, panel2, strict=False)))
    except Exception as exc:  # noqa: BLE001
        return {"ran": False, "reason": f"re-evaluation failed: {exc}", "flag": False}

    m = ctx.runner.run(new_sig, reason="delivery_lag:1")
    base_ic = ctx.baseline["rank_ic"]
    ic = m["rank_ic"]
    collapsed = ic <= 0 or (base_ic > 0 and ic < COLLAPSE * base_ic)
    return {"ran": True, "base_rank_ic": base_ic, "rank_ic_delivery_lagged": ic,
            "t_stat": m["t_stat"], "flag": bool(collapsed),
            # "localized" is finalized in run_redteam: collapsed HERE but NOT under
            # the global one-day lag (test 5) => the dependency is on delivery_pct
            # specifically, not a diffuse look-ahead.
            "localized": None}


def test_sector_neutral(ctx: RedTeamContext) -> dict:
    """#7 — 'it's one industry bet'.  Re-score with the signal demeaned within
    sector."""
    base_ic = ctx.baseline["rank_ic"]
    m = ctx.runner.run(ctx.signal, reason="sector_neutral", neutralize="sector")
    ic = m["rank_ic"]
    collapsed = ic <= 0 or (base_ic > 0 and ic < COLLAPSE * base_ic)
    return {"base_rank_ic": base_ic, "rank_ic_sector_neutral": ic,
            "t_stat": m["t_stat"], "flag": bool(collapsed)}


def test_liquidity_filter(ctx: RedTeamContext) -> dict:
    """#8 — 'untradeable names'.  Impose a trailing-turnover floor and re-score."""
    feats, _ = _bt._load_panel()
    in_split = feats[split_mask(feats["date"], ctx.split)]
    to = np.exp(pd.to_numeric(in_split["turnover_21"], errors="coerce").dropna())
    if to.empty:
        return {"ran": False, "reason": "no turnover_21 in panel", "flag": False}
    thr = float(np.percentile(to, 40))
    base_ic = ctx.baseline["rank_ic"]
    m = ctx.runner.run(ctx.signal, reason="liquidity_filter",
                       subsample={"min_turnover": thr})
    ic = m["rank_ic"]
    collapsed = ic <= 0 or (base_ic > 0 and ic < COLLAPSE * base_ic)
    return {"min_turnover_rupees": thr, "pctile": 40, "base_rank_ic": base_ic,
            "rank_ic_liquid_only": ic, "n_obs": m["n_obs"], "flag": bool(collapsed)}


def test_decay_curve(ctx: RedTeamContext) -> dict:
    """#9 — 'the claimed horizon is fiction'.  The baseline backtest already
    returns the full RankIC decay curve; check the claimed horizon is where the
    edge actually lives."""
    decay = {int(k): float(v) for k, v in ctx.baseline["decay"].items()}
    claimed = ctx.horizon
    peak_h = max(decay, key=lambda h: decay[h])
    peak = decay[peak_h]
    at_claimed = decay.get(claimed, float("nan"))
    fiction = (
        not np.isfinite(at_claimed) or at_claimed <= 0
        or (peak > 0 and at_claimed < COLLAPSE * peak)
    )
    return {"decay": decay, "claimed_horizon": claimed, "peak_horizon": peak_h,
            "rank_ic_at_claimed": at_claimed, "rank_ic_at_peak": peak,
            "flag": bool(fiction)}


def test_sign_stability(ctx: RedTeamContext) -> dict:
    """#10 — 'the direction flips around'.  Kill if the modal sign of the
    per-fold RankIC does not hold in >= 70 % of folds."""
    years = _fold_years(ctx)
    signs = {}
    for y in years:
        m = ctx.runner.run(ctx.signal, reason=f"sign_stability:{y}",
                           subsample={"years": [y]})
        if m["n_days"] >= MIN_FOLD_DAYS and np.isfinite(m["rank_ic"]) and m["rank_ic"] != 0:
            signs[y] = int(np.sign(m["rank_ic"]))
    detail: dict[str, Any] = {"per_fold_sign": signs, "n_folds": len(signs)}
    if len(signs) < 3:
        detail["reason"] = "fewer than 3 usable folds"
        detail["flag"] = False
        return detail
    vals = list(signs.values())
    modal = 1 if vals.count(1) >= vals.count(-1) else -1
    frac = vals.count(modal) / len(vals)
    detail["modal_sign"] = modal
    detail["consistency"] = frac
    detail["flag"] = bool(frac < SIGN_CONSISTENCY_MIN)
    return detail


def test_universe_edge(ctx: RedTeamContext) -> dict:
    """#11 — 'it only works on the illiquid fringe'.  Drop the names ranked
    150-200 by trailing liquidity **that month** and re-score.

    The fringe comes from P1's ``data/universe/liquidity_ranks.parquet`` (per
    :func:`_liquidity_fringe`), never a hard-coded symbol list.
    """
    fr = _liquidity_fringe(ctx)
    if fr is None:
        return {"ran": False,
                "reason": "no liquidity ranking (P1 rank file absent and no price "
                          "panel to recompute from)", "flag": False}
    bounds, fringes, source = fr

    sig = ctx.signal.copy()
    dates = sig.index.to_numpy()
    k = np.clip(np.searchsorted(bounds, dates, side="left") - 1, 0, len(bounds) - 1)
    n_masked = 0
    all_fringe: set[str] = set()
    col_ix = {c: i for i, c in enumerate(sig.columns)}
    for row, ki in enumerate(k):
        f = fringes[ki]
        if f:
            sig.iloc[row, [col_ix[s] for s in f]] = np.nan
            n_masked += len(f)
            all_fringe |= f

    base_ic = ctx.baseline["rank_ic"]
    m = ctx.runner.run(sig, reason="universe_edge")
    ic = m["rank_ic"]
    collapsed = ic <= 0 or (base_ic > 0 and ic < COLLAPSE * base_ic)
    return {"ran": True, "fringe_source": source,
            "n_fringe_names": len(all_fringe), "n_cell_masks": n_masked,
            "base_rank_ic": base_ic, "rank_ic_without_fringe": ic,
            "flag": bool(collapsed)}


_TESTS = {
    "subsample_year": test_subsample_year,
    "regime_split": test_regime_split,
    "size_tercile": test_size_tercile,
    "cost_sweep": test_cost_sweep,
    "extra_lag": test_extra_lag,
    "delivery_lag": test_delivery_lag,
    "sector_neutral": test_sector_neutral,
    "liquidity_filter": test_liquidity_filter,
    "decay_curve": test_decay_curve,
    "sign_stability": test_sign_stability,
    "universe_edge": test_universe_edge,
}


# --------------------------------------------------------------------------- #
# Helpers for the formula-re-evaluation test (#6)                              #
# --------------------------------------------------------------------------- #
def _panel_frame(x) -> pd.DataFrame:
    if isinstance(x, pd.DataFrame):
        return x
    raise TypeError(f"expected a wide DataFrame, got {type(x)!r}")


def _formula_fields(formula: str) -> list[str]:
    try:
        from .ast_tools import _leaf_fields, parse

        return sorted(_leaf_fields(parse(formula, strict=False), set()))
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------- #
# The public entry point                                                       #
# --------------------------------------------------------------------------- #
def run_redteam(
    signal: pd.DataFrame,
    tests: list[str] | None = None,
    *,
    split: str = "val_a",
    horizon: int | None = None,
    sign: int = 1,
    thesis: dict | None = None,
    formula: str | None = None,
    panel: dict[str, pd.DataFrame] | None = None,
    prices: pd.DataFrame | None = None,
    liquidity_ranks: pd.DataFrame | None = None,
    ledger: Any = None,
    thesis_id: str | None = None,
    formula_hash: str | None = None,
    canonical_ast: str | None = None,
) -> dict:
    """Run the selected red-team tests and return the survive/kill verdict.

    Parameters
    ----------
    signal      wide ``date x symbol`` (or long) score panel.
    tests       names from :data:`REDTEAM_MENU` the agent picked; ``None`` runs
                all eleven.  The five :data:`DECISIVE_TESTS` are always run
                regardless (a red-team you can opt out of is not a red-team).
    split       backtest region — ``"val_a"`` (search playground) or ``"val_b"``.
    horizon     forward-return horizon; defaults to ``thesis["horizon_days"]``
                (snapped into :data:`HORIZONS`) or 1.
    sign        pre-registered sign; the signal is oriented ``sign * signal`` so
                "positive RankIC == good" holds for every check.
    formula/panel  needed only by test 6 (``delivery_lag``).
    liquidity_ranks  P1's ``month_end · symbol · liquidity_rank`` frame for test
                11 (``universe_edge``).  Falls back to
                ``data/universe/liquidity_ranks.parquet``, then to recomputing
                the ranking from ``prices`` / ``data/prices/ohlcv.parquet``.
    prices      ohlcv-like ``date,symbol,close_raw,volume_raw`` — the test-11
                fallback only (regime labels, test 2, come from the backtester).
    ledger      a :class:`ledger.Ledger`; every backtest fired here is recorded
                with ``counts_as_trial=0``.

    Returns
    -------
    ``{"verdict": "survives"|"killed", "failed_tests": [...],
       "flagged_diagnostics": [...], "tests_run": [...], "results": {...},
       "baseline": {...}, "n_backtests": int, "counts_as_trial": 0}``
    """
    if horizon is None:
        h = (thesis or {}).get("horizon_days", 1)
        horizon = min(HORIZONS, key=lambda x: abs(x - int(h)))
    if horizon not in HORIZONS:
        raise ValueError(f"horizon {horizon} not in {HORIZONS}")

    want = list(REDTEAM_MENU) if tests is None else [t for t in tests if t in _TESTS]
    # decisive tests are non-negotiable
    run_order = [t for t in REDTEAM_MENU if t in set(want) | set(DECISIVE_TESTS)]
    forced = sorted(set(DECISIVE_TESTS) - set(want))

    wide_sig = sign * _wide(signal)
    runner = _Runner(split=split, horizon=horizon, ledger=ledger,
                     thesis_id=thesis_id, formula_hash=formula_hash,
                     canonical_ast=canonical_ast)
    ctx = RedTeamContext(signal=wide_sig, split=split, horizon=horizon, sign=sign,
                         formula=formula, panel=panel, prices=prices,
                         liquidity_ranks=liquidity_ranks, runner=runner)
    ctx.baseline = runner.run(wide_sig, reason="baseline")

    results: dict[str, dict] = {}
    for name in run_order:
        results[name] = _TESTS[name](ctx)

    # finalize test 6's "localized" verdict now that test 5's result is known
    if results.get("delivery_lag", {}).get("ran"):
        global_lag_flagged = results.get("extra_lag", {}).get("flag", False)
        results["delivery_lag"]["localized"] = bool(
            results["delivery_lag"]["flag"] and not global_lag_flagged
        )

    failed = [t for t in run_order
              if t in DECISIVE_TESTS and results[t].get("flag")]
    diags = [t for t in run_order
             if t not in DECISIVE_TESTS and results[t].get("flag")]

    return {
        "verdict": "killed" if failed else "survives",
        "failed_tests": failed,
        "flagged_diagnostics": diags,
        "tests_run": run_order,
        "forced_decisive_tests": forced,
        "results": results,
        "baseline": {k: ctx.baseline[k] for k in
                     ("rank_ic", "t_stat", "sharpe", "n_days", "n_obs")},
        "n_backtests": runner.n_calls,
        "counts_as_trial": 0,
    }
