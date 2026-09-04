"""The compute bridge to ``src`` (Section 0.4).

This is the ONLY ``lib`` module that imports *compute* from ``src`` (the D0 test
asserts that).  D0 implements:
  * ``ensure_panel()``  — wire ``data/panel/*`` into ``src.backtester``
  * ``dsr`` / ``expected_max_sr``  — thin passthroughs to ``src.gates``
  * ``run_backtest``  — at minimum the ``split == "holdout"`` rejection

D4 fills ``eval_formula`` / ``run_backtest`` / the zoo helpers; D5 fills
``run_redteam_ui``, ``leaky_signal`` and the Gate-B honesty demos
(``oversearching_curve``, ``effective_trial_count_demo``, ``pbo_demo``,
``walk_forward_ui``, ``thresholds``, ``assert_ledger_append_only``,
``redteam_menu``).

Safety rails baked in here (Section 0.8):
  * ``run_backtest`` / ``run_redteam_ui`` reject ``split == "holdout"``.
  * any gate/red-team run uses ``src.ledger.Ledger(":memory:")`` and
    ``do_holdout_peek=False`` — never ``data/ledger.db``.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from src import gates as _gates
from src.config import (
    EMBARGO_DAYS,
    FEATURES_PARQUET,
    LABELS_PARQUET,
    OHLCV_PARQUET,
    RANDOM_SEED,
    split_mask,
)

_HOLDOUT_MSG = (
    "split='holdout' is sealed (IMPLEMENTATION_PLAN.md Section 0.4). No dashboard "
    "page may score a signal on HOLDOUT."
)


@st.cache_resource(show_spinner=False)
def ensure_panel() -> bool:
    """Load ``data/panel/{features,labels}.parquet`` and call
    ``src.backtester.use_panel(...)`` so ``src.backtester`` / ``src.gates`` /
    ``src.redteam`` all see the same panel.  Idempotent.  Returns ``False`` (and
    pages then show ``ui.data_missing``) if the panel is absent."""
    from src import backtester as _bt

    if not (Path(FEATURES_PARQUET).exists() and Path(LABELS_PARQUET).exists()):
        return False
    feats = pd.read_parquet(FEATURES_PARQUET)
    labels = pd.read_parquet(LABELS_PARQUET)
    _bt.use_panel(feats, labels)
    return True


@st.cache_data(show_spinner=False)
def dsr(observed_sr: float, n_trials: int, sr_std: float,
        skew: float, kurt: float, n_obs: int) -> float:
    """P(true per-period Sharpe > 0), deflated.  Passthrough to
    ``src.gates.deflated_sharpe_ratio`` (which takes the SR *variance*)."""
    return float(_gates.deflated_sharpe_ratio(
        observed_sr, int(n_trials), float(sr_std) ** 2, skew, kurt, int(n_obs),
    ))


@st.cache_data(show_spinner=False)
def expected_max_sr(n_trials: int, sr_std: float) -> float:
    """Bailey-Lopez de Prado E[max SR].  Passthrough to
    ``src.gates.expected_max_sharpe``."""
    return float(_gates.expected_max_sharpe(int(n_trials), float(sr_std)))


# --------------------------------------------------------------------------- #
# The formula-evaluation price panel (D4)                                      #
# --------------------------------------------------------------------------- #
#: The bare-name fields a formula may reference (kept in sync with
#: ``src.operators.FIELDS``).  ``eval_formula`` builds a wide ``date x symbol``
#: frame for each one from sliced project data.
_PANEL_FIELDS = (
    "open", "high", "low", "close", "volume", "vwap", "n_trades",
    "close_raw", "volume_raw",
)


@st.cache_data(show_spinner=False)
def _panel_symbols() -> list[str]:
    """Every symbol that appears in the P3 label panel (the backtester's
    universe).  The price panel is sliced to exactly this set so the formula
    signal and the labels merge cleanly and no time is spent evaluating a
    formula over the ~1700 non-universe NSE tickers in ``ohlcv.parquet``."""
    from dashboard.lib import data as _data

    syms = _data.load_features(columns=["symbol"])["symbol"].astype(str).unique()
    return sorted(syms)


@st.cache_resource(show_spinner=False)
def price_panel() -> dict[str, "pd.DataFrame"]:
    """``{field: wide date x symbol frame}`` — the panel a formula string is
    evaluated against (mirrors ``src.loop.build_price_panel``, but sliced to the
    label-panel symbols and sourced through the ``lib.data`` sliced readers).

    ``returns`` is the adjusted-close pct-change; ``delivery_pct`` / ``size_proxy``
    / ``sector`` come from the P3 feature panel.  Empty dict if prices are absent.
    """
    from dashboard.lib import data as _data

    if not OHLCV_PARQUET.exists():
        return {}
    syms = _panel_symbols()
    ohlcv = _data.load_ohlcv(
        symbols=syms, columns=["date", "symbol", *_PANEL_FIELDS],
    )
    fields: dict[str, pd.DataFrame] = {}
    for col in _PANEL_FIELDS:
        w = ohlcv.pivot_table(index="date", columns="symbol", values=col).sort_index()
        w.index = pd.DatetimeIndex(pd.to_datetime(w.index)).normalize()
        fields[col] = w
    fields["returns"] = fields["close"].pct_change()

    try:
        aux = _data.load_features(
            symbols=syms, columns=["date", "symbol", "delivery_pct", "size_proxy", "sector"],
        )
        for col in ("delivery_pct", "size_proxy", "sector"):
            w = aux.pivot_table(index="date", columns="symbol", values=col, aggfunc="first")
            w = w.sort_index()
            w.index = pd.DatetimeIndex(pd.to_datetime(w.index)).normalize()
            fields[col] = w.reindex(fields["close"].index)
    except (FileNotFoundError, KeyError, ValueError):
        pass
    return fields


# --------------------------------------------------------------------------- #
# Compute helpers (D4)                                                         #
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def eval_formula(formula: str) -> pd.DataFrame:
    """Parse ``formula`` under the strict Phase-5 whitelist and evaluate it
    against :func:`price_panel` → a wide ``date x symbol`` signal frame.

    Never ``eval``s anything — the only code path is ``src.ast_tools.parse`` +
    the causal operator registry.  Raises ``ast_tools.ParseError`` for a formula
    that violates the whitelist / names an unknown field or operator, and
    ``ast_tools.EvalError`` if a parsed formula cannot be evaluated on the panel.
    """
    from src.ast_tools import evaluate, parse

    node = parse(formula, strict=True)          # structural + name check
    panel = price_panel()
    if not panel:
        raise FileNotFoundError(
            "price panel unavailable — data/prices/ohlcv.parquet is missing"
        )
    out = evaluate(node, panel, strict=True)
    if not isinstance(out, pd.DataFrame):
        raise ValueError(
            f"formula produced a {type(out).__name__}, not a date x symbol frame "
            "(a constant-only formula has no cross-section)"
        )
    out = out.copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index)).normalize()
    return out.sort_index()


@st.cache_data(show_spinner=False)
def zoo_formulas() -> list[dict]:
    """``src.zoo.ZOO`` as a plain list of ``{name, formula, source, canonical,
    fingerprint}`` dicts — so ``04_Backtester`` gets the formula dropdown without
    importing ``src.zoo`` directly (only pages 05 / 08 may)."""
    from src.zoo import ZOO

    return [dict(e) for e in ZOO]


@st.cache_data(show_spinner=False)
def zoo_backtest(name: str, split: str = "val_a", horizon: int = 1) -> dict:
    """One zoo formula scored on ``split`` — a leaderboard row.  Cached per
    ``(name, split, horizon)`` so the ``05_Operators_and_Zoo`` "compute now"
    progress loop is resumable.  Never raises — an un-evaluable formula comes
    back with ``ok=False``."""
    from src.ast_tools import complexity
    from src.zoo import ZOO_BY_NAME

    e = ZOO_BY_NAME[name]
    cx = complexity(e["formula"])
    row = {
        "name": name, "source": e["source"], "formula": e["formula"],
        "nodes": cx["nodes"], "depth": cx["depth"], "free_params": cx["free_params"],
        "rank_ic": float("nan"), "icir": float("nan"), "t_stat": float("nan"),
        "sharpe": float("nan"), "split": split, "ok": False, "error": "",
    }
    try:
        m = run_backtest(e["formula"], split, horizon=horizon)
        row.update(rank_ic=m["rank_ic"], icir=m["icir"], t_stat=m["t_stat"],
                   sharpe=m["sharpe"], ok=True)
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def _score(signal: pd.DataFrame, split: str, horizon: int, cost_bps: float,
           neutralize: str | None, extra_lag: int) -> dict:
    """Shared scoring path: HOLDOUT tripwire → ``src.backtester.backtest`` →
    Metrics dict, augmented with a reconstructed equity curve and the realised
    long-short daily returns for ``charts.equity_curve``."""
    if split == "holdout":
        raise PermissionError(_HOLDOUT_MSG)
    if not ensure_panel():
        raise FileNotFoundError("data/panel/{features,labels}.parquet is missing")

    from src import backtester as _bt

    metrics = dict(_bt.backtest(
        signal, split, horizon=horizon, cost_bps=cost_bps,
        neutralize=neutralize, extra_lag=extra_lag, embargo_days=EMBARGO_DAYS,
    ))
    dates, net = _ls_daily_returns(signal, split, horizon, cost_bps, neutralize, extra_lag)
    metrics["_equity_dates"] = [d.isoformat() for d in dates]
    metrics["_equity_returns"] = [float(x) for x in net]
    return metrics


@st.cache_data(show_spinner=False)
def run_backtest(formula: str, split: str, horizon: int = 1, cost_bps: float = 0.0,
                 neutralize: str | None = None, extra_lag: int = 0) -> dict:
    """Evaluate ``formula`` and score it on ``split`` → a Metrics dict
    (Section 0.5) plus ``_equity_dates`` / ``_equity_returns`` for the chart.

    ``split == "holdout"`` raises ``PermissionError`` — HOLDOUT is sealed.
    """
    if split == "holdout":
        raise PermissionError(_HOLDOUT_MSG)
    signal = eval_formula(formula)
    return _score(signal, split, horizon, cost_bps, neutralize, extra_lag)


@st.cache_data(show_spinner=False)
def leaky_signal() -> pd.DataFrame:
    """``fwd_ret_1`` as its own signal — a deliberate look-ahead demo.  Not a
    formula (leakage is not expressible in the grammar); injected directly so the
    acceptance board can show the engine catching it (``rank_ic`` ≈ 1)."""
    labels = pd.read_parquet(LABELS_PARQUET, columns=["date", "symbol", "fwd_ret_1"])
    w = labels.pivot_table(index="date", columns="symbol", values="fwd_ret_1").sort_index()
    w.index = pd.DatetimeIndex(pd.to_datetime(w.index)).normalize()
    return w


@st.cache_data(show_spinner=False)
def noise_signal(seed: int | None = None) -> pd.DataFrame:
    """A pure-noise ``date x symbol`` signal (standard normal), shaped like the
    price panel.  Seeded with ``src.config.RANDOM_SEED`` unless overridden."""
    panel = price_panel()
    if not panel:
        raise FileNotFoundError("price panel unavailable")
    close = panel["close"]
    rng = np.random.default_rng(RANDOM_SEED if seed is None else int(seed))
    return pd.DataFrame(
        rng.standard_normal(close.shape), index=close.index, columns=close.columns,
    )


@st.cache_data(show_spinner=False)
def score_signal(kind: str, split: str = "val_a", horizon: int = 1,
                 cost_bps: float = 0.0, seed: int | None = None) -> dict:
    """Score one of the injected (non-formula) acceptance signals.

    ``kind`` ∈ ``{"leaky", "noise"}``.  Same Metrics shape as :func:`run_backtest`.
    """
    if kind == "leaky":
        sig = leaky_signal()
    elif kind == "noise":
        sig = noise_signal(seed)
    else:
        raise ValueError(f"kind must be 'leaky' or 'noise', got {kind!r}")
    return _score(sig, split, horizon, cost_bps, None, 0)


# --------------------------------------------------------------------------- #
# Long-short equity reconstruction (for charts.equity_curve)                   #
# --------------------------------------------------------------------------- #
def _ls_daily_returns(signal: pd.DataFrame, split: str, horizon: int,
                      cost_bps: float, neutralize: str | None,
                      extra_lag: int) -> tuple[list, np.ndarray]:
    """The dollar-neutral top/bottom-quintile book's daily NET return series.

    ``src.backtester.backtest`` returns only the book's *scalars* (sharpe,
    ann_return, …), so the visible equity curve is reconstructed here with the
    identical logic as ``src.backtester._long_short`` (same quintile, same
    per-day rank scaling, same both-legs turnover cost).  Returns
    ``(list[Timestamp], np.ndarray)`` — empty on an empty book.
    """
    from src import backtester as _bt

    feats, labels = _bt._load_panel()
    calendar = np.sort(labels["date"].unique())

    sig = _bt._signal_to_long(signal)
    sig = _bt._shift_signal(sig, extra_lag, calendar)
    sig = sig[split_mask(sig["date"], split)]
    if len(sig) == 0:
        return [], np.array([])

    lab = labels[["date", "symbol", "fwd_ret_1"]]
    panel = sig.merge(lab, on=["date", "symbol"], how="inner").dropna(
        subset=["sig", "fwd_ret_1"]
    )
    if split != "holdout" and len(panel):
        eval_days = np.sort(panel["date"].unique())
        keep = _bt._purge_holdout_tail(eval_days, calendar, horizon)
        panel = panel[panel["date"].isin(keep)]
    if len(panel) == 0:
        return [], np.array([])

    if neutralize == "sector":
        sec = feats[["date", "symbol", "sector"]]
        panel = panel.merge(sec, on=["date", "symbol"], how="left")
        panel["sector"] = panel["sector"].fillna("__NA__")
        panel["sig"] = panel["sig"] - panel.groupby(["date", "sector"])["sig"].transform("mean")

    day_n = panel.groupby("date")["sig"].transform("size")
    panel = panel[day_n >= _bt.MIN_STOCKS_PER_DAY]
    if len(panel) == 0:
        return [], np.array([])
    panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)
    panel["sig_scaled"] = panel.groupby("date")["sig"].transform(_bt._rank_scale)

    d = panel[["date", "symbol", "sig_scaled", "fwd_ret_1"]].dropna()
    g = d.groupby("date", sort=True)["sig_scaled"]
    pct = g.rank(pct=True, method="first")
    n = g.transform("size")
    is_long = pct > (1.0 - _bt.QUANTILE)
    is_short = pct <= _bt.QUANTILE
    n_long = is_long.groupby(d["date"]).transform("sum")
    n_short = is_short.groupby(d["date"]).transform("sum")
    w = pd.Series(0.0, index=d.index)
    w[is_long] = 1.0 / n_long[is_long]
    w[is_short] = -1.0 / n_short[is_short]
    d = d.assign(w=w)
    good = (n >= _bt.MIN_STOCKS_PER_DAY) & (n_long > 0) & (n_short > 0)
    d = d[good]
    if d.empty:
        return [], np.array([])

    gross = (d["w"] * d["fwd_ret_1"]).groupby(d["date"], sort=True).sum()
    wmat = d.pivot(index="date", columns="symbol", values="w").fillna(0.0)
    dw = wmat.diff().abs().sum(axis=1)
    dw.iloc[0] = wmat.iloc[0].abs().sum()
    net = (gross - cost_bps * 1e-4 * dw).dropna()
    return list(pd.to_datetime(net.index)), net.to_numpy()


# --------------------------------------------------------------------------- #
# Purge / embargo visualiser (D4)                                             #
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def purge_embargo_demo(horizon: int = 1, embargo_days: int = EMBARGO_DAYS) -> dict:
    """How many TRAIN rows are dropped near the TRAIN→VAL_A boundary by
    purge (label-window overlap) + embargo, for the given ``horizon``.

    Returns ``{n_train, n_dropped, dropped_pct, boundary, window,
    timeline: list[{date, state}]}`` — ``state`` ∈ ``kept|purged|embargo|test``
    for the ~40 trading days straddling the boundary.
    """
    from src import backtester as _bt

    _, labels = _bt._load_panel()
    calendar = pd.DatetimeIndex(pd.to_datetime(np.sort(labels["date"].unique()))).normalize()
    train_dates = calendar[np.asarray(split_mask(pd.Series(calendar), "train"), dtype=bool)]
    test_dates = calendar[np.asarray(split_mask(pd.Series(calendar), "val_a"), dtype=bool)]
    if len(train_dates) == 0 or len(test_dates) == 0:
        return {"n_train": 0, "n_dropped": 0, "dropped_pct": 0.0,
                "boundary": None, "window": horizon, "timeline": []}

    keep = _bt.purge_embargo_mask(train_dates, test_dates, horizon, embargo_days, calendar)
    n_dropped = int((~keep).sum())

    # a readable ~40-day window around the boundary
    boundary = test_dates[0]
    lo = train_dates[-1] - pd.Timedelta(days=40)
    hi = test_dates[0] + pd.Timedelta(days=15)
    pos = {d: i for i, d in enumerate(calendar)}
    first_test = min(pos[d] for d in test_dates)
    timeline = []
    dropped_train = set(pd.to_datetime(train_dates[~keep]))
    test_set = set(pd.to_datetime(test_dates))
    for d in calendar:
        if d < lo or d > hi:
            continue
        if d in test_set:
            state = "test"
        elif d in dropped_train:
            # a dropped TRAIN row before the test block = purge (its label window
            # reaches into the block); after = embargo.  All train rows here are
            # before the boundary, so this is a purge window.
            state = "purged" if pos[d] < first_test else "embargo"
        else:
            state = "kept"
        timeline.append({"date": d.isoformat(), "state": state})

    return {
        "n_train": int(len(train_dates)),
        "n_dropped": n_dropped,
        "dropped_pct": round(100.0 * n_dropped / max(1, len(train_dates)), 2),
        "boundary": boundary.isoformat(),
        "window": int(horizon),
        "timeline": timeline,
    }


# --------------------------------------------------------------------------- #
# Red-Team demo signals (D5)                                                   #
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def one_lucky_year_signal(seed: int | None = None, lucky_year: int = 2019) -> pd.DataFrame:
    """Pure noise, except during ``lucky_year`` where it is swapped for
    ``fwd_ret_1`` (a deliberate one-year look-ahead) — a synthetic "it was one
    lucky year" candidate for red-team test 1 (``subsample_year``): dropping
    the lucky year should collapse it back to noise.

    Built on the ``fwd_ret_1`` pivot grid (same as :func:`leaky_signal`), not
    :func:`price_panel` — its date index is exactly the backtester's label
    calendar, which ``_shift_signal`` (red-team test 5) requires an exact
    match against.
    """
    w = leaky_signal()          # date x symbol grid == the label calendar
    rng = np.random.default_rng(RANDOM_SEED if seed is None else int(seed))
    sig = pd.DataFrame(rng.standard_normal(w.shape), index=w.index, columns=w.columns)
    mask = sig.index.year == int(lucky_year)
    sig.loc[mask] = w.loc[mask].fillna(0.0)
    return sig


@st.cache_data(show_spinner=False)
def thin_edge_signal(seed: int | None = None, edge: float = 0.06) -> pd.DataFrame:
    """A sliver of real (1-day) reversal buried in mostly day-to-day noise —
    thin gross edge, near-maximal turnover (the noise majority re-ranks every
    day) — the shape red-team test 4 (``cost_sweep``) exists to catch.

    Reindexed onto the ``fwd_ret_1`` label grid (see :func:`one_lucky_year_signal`)
    so its date index matches the backtester's calendar exactly.
    """
    w = leaky_signal()
    panel = price_panel()
    if not panel:
        raise FileNotFoundError("price panel unavailable")
    rev = (-1.0 * panel["returns"]).reindex(index=w.index, columns=w.columns)
    rng = np.random.default_rng(RANDOM_SEED if seed is None else int(seed))
    noise = pd.DataFrame(rng.standard_normal(w.shape), index=w.index, columns=w.columns)
    rev_rank = (rev.rank(axis=1, pct=True) - 0.5).fillna(0.0)
    return edge * rev_rank + (1.0 - edge) * noise


_SPECIAL_SIGNALS = {
    "__leaky__": leaky_signal,
    "__one_lucky_year__": one_lucky_year_signal,
    "__thin_edge__": thin_edge_signal,
}
SPECIAL_SIGNAL_LABELS: dict[str, str] = {
    "__leaky__": "leaky (fwd_ret_1)",
    "__one_lucky_year__": "one-lucky-year (synthetic)",
    "__thin_edge__": "thin-edge high-turnover (synthetic)",
}


def _align_to_label_calendar(signal: pd.DataFrame) -> pd.DataFrame:
    """Restrict a wide date x symbol signal to exactly the backtester's label
    calendar.

    ``src.backtester._shift_signal`` (red-team test 5, ``extra_lag`` — always
    on, decisive) maps each row's date to an *integer position* in
    ``labels["date"].unique()``; a signal carrying dates outside that calendar
    (e.g. :func:`eval_formula`'s price panel spans the pre-label warm-up
    window back to 2014) turns that position Series to ``float64`` and
    ``_shift_signal`` raises ``IndexError`` trying to index with it. This is a
    dashboard-side normalisation only — ``src/backtester.py`` is untouched."""
    from src import backtester as _bt

    _, labels = _bt._load_panel()
    cal = pd.DatetimeIndex(pd.to_datetime(labels["date"].unique())).normalize()
    return signal.reindex(index=signal.index.intersection(cal))


@st.cache_data(show_spinner=False)
def run_redteam_ui(formula: str, split: str = "val_a") -> dict:
    """Run the fixed 11-test red-team menu on ``formula`` — a ZOO/free-text
    formula, or one of the :data:`_SPECIAL_SIGNALS` sentinels (``"__leaky__"``,
    ``"__one_lucky_year__"``, ``"__thin_edge__"``).

    Calls ``src.redteam.run_redteam`` **entirely by keyword** — its ``split``
    is keyword-only and the 2nd positional is ``tests`` (Section 0.5) — with
    ``liquidity_ranks=`` set (test 11 degrades to a no-op without it) and
    ``ledger=Ledger(":memory:")``: ``data/ledger.db`` is never touched.
    """
    if split == "holdout":
        raise PermissionError(_HOLDOUT_MSG)
    if not ensure_panel():
        raise FileNotFoundError("data/panel/{features,labels}.parquet is missing")

    from src.ledger import Ledger
    from src.redteam import run_redteam

    from dashboard.lib import data as _data

    if formula in _SPECIAL_SIGNALS:
        signal = _SPECIAL_SIGNALS[formula]()
        formula_kw = None
    else:
        signal = eval_formula(formula)
        formula_kw = formula
    signal = _align_to_label_calendar(signal)

    ranks = _data.load_liquidity_ranks()
    prices = _data.load_ohlcv(columns=["date", "symbol", "close_raw", "volume_raw"])

    return run_redteam(
        signal,
        tests=None,
        split=split,
        horizon=1,
        formula=formula_kw,
        panel=price_panel(),
        prices=prices,
        liquidity_ranks=ranks,
        ledger=Ledger(":memory:"),
    )


# --------------------------------------------------------------------------- #
# Gate B honesty demos (D5)                                                    #
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def oversearching_curve(draws: int = 4000, seed: int | None = None) -> pd.DataFrame:
    """``N -> {sqrt_2lnN, realised_E_max (seeded MC), bailey_ldp_E_max}`` over a
    fixed grid of ``N`` — the three curves behind "searching harder fools you
    more". Vectorised and cached; a few hundred ms even at ``draws=4000``."""
    rng = np.random.default_rng(RANDOM_SEED if seed is None else int(seed))
    grid = [2, 3, 5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500, 750, 1000]
    rows = []
    for n in grid:
        mc_max = rng.standard_normal((draws, n)).max(axis=1)
        rows.append({
            "N": n,
            "sqrt_2lnN": math.sqrt(2.0 * math.log(n)),
            "realised_E_max": float(mc_max.mean()),
            "bailey_ldp_E_max": _gates.expected_max_sharpe(n, 1.0),
        })
    return pd.DataFrame(rows)


#: The measured P(best-of-N pure-noise t > 3.0) table (200,000 MC draws/row —
#: reports/p6_handoff.md "measured" section, §6 item 1).  Fixed empirical
#: evidence, quoted verbatim — not something a page-load Monte-Carlo can afford
#: to reproduce at that draw count.
MEASURED_P_T_GT_3: dict[int, float] = {5: 0.7, 20: 2.7, 100: 12.6, 200: 23.6, 500: 49.1}


@st.cache_data(show_spinner=False)
def effective_trial_count_demo() -> dict:
    """20 knob-variants of one shape (``div(volume, ts_mean(volume, k))``,
    k=5..24) -> ``src.gates.effective_trial_count`` via return-decorrelation,
    vs. the raw count.  Mirrors reports/p6_handoff.md criterion 5 (raw N=20,
    effective ~2)."""
    from src import gates as _g
    from src.ast_tools import canonical

    if not ensure_panel():
        raise FileNotFoundError("data/panel/{features,labels}.parquet is missing")

    formulas = [f"div(volume, ts_mean(volume, {k}))" for k in range(5, 25)]
    canon = [canonical(f) for f in formulas]
    cols = {f: _g.daily_rank_ic(eval_formula(f), "val_a", horizon=1) for f in formulas}
    mat = pd.DataFrame(cols).dropna()
    if len(mat) >= 2:
        n_eff = _g.effective_trial_count(canon, return_matrix=mat.to_numpy())
    else:
        n_eff = _g.effective_trial_count(canon)
    return {"raw_n": len(formulas), "effective_n": float(n_eff), "n_days": int(len(mat))}


@st.cache_data(show_spinner=False)
def pbo_demo(seed: int | None = None, n_repeats: int = 30) -> dict:
    """``src.gates.cscv_pbo`` on T×8 return matrices, repeated ``n_repeats``
    times with fresh noise draws (a single 8-column CSCV split has high
    variance — ~70 combinatorial splits over ~110-row blocks — so the "~0.5 /
    low" claim needs several draws averaged, not one):

    * **pure noise** — 8 iid columns, no true winner -> mean PBO ~ 0.5.
    * **planted** — one persistently-real column (the daily RankIC of a real
      ZOO momentum formula on VAL_A) against 7 noise columns of the same
      scale -> the real column keeps winning out-of-sample too -> lower mean
      PBO.

    Returns ``{noise_pbo_mean, noise_pbo_draws, planted_pbo_mean,
    planted_pbo_draws, n_days, n_repeats}``.
    """
    from src import gates as _g

    if not ensure_panel():
        raise FileNotFoundError("data/panel/{features,labels}.parquet is missing")

    base_seed = RANDOM_SEED if seed is None else int(seed)
    mom_ic = _g.daily_rank_ic(
        eval_formula("sub(div(delay(close, 21), delay(close, 252)), 1)"),
        "val_a", horizon=1,
    ).dropna()
    T = (len(mom_ic) // 8) * 8
    if T < 40:
        raise ValueError("not enough VAL_A days for an 8-block CSCV")
    real = mom_ic.to_numpy()[:T]
    real_std = float(np.std(real))

    noise_pbos, planted_pbos = [], []
    for i in range(n_repeats):
        rng = np.random.default_rng(base_seed + i)
        noise = rng.standard_normal((T, 8)) * real_std
        noise_pbos.append(_g.cscv_pbo(noise, n_blocks=8)["pbo"])

        rng2 = np.random.default_rng(base_seed + 1000 + i)
        scr = rng2.standard_normal((T, 7)) * real_std
        planted = np.column_stack([real] + [scr[:, i2] for i2 in range(7)])
        planted_pbos.append(_g.cscv_pbo(planted, n_blocks=8)["pbo"])

    return {
        "noise_pbo_mean": float(np.mean(noise_pbos)),
        "noise_pbo_draws": [float(x) for x in noise_pbos],
        "planted_pbo_mean": float(np.mean(planted_pbos)),
        "planted_pbo_draws": [float(x) for x in planted_pbos],
        "n_days": T, "n_repeats": n_repeats,
    }


@st.cache_data(show_spinner=False)
def walk_forward_ui(formula: str, train_years: int = 3, step_months: int = 6,
                    horizon: int = 1) -> dict:
    """``src.gates.walk_forward`` over TRAIN + VAL_A — **dates, not a split
    name** (Section 0.5: no ``split=`` parameter exists).  Returns
    ``{oos_dates, oos_ic, folds}``."""
    from src import gates as _g
    from src.config import SPLITS

    if not ensure_panel():
        raise FileNotFoundError("data/panel/{features,labels}.parquet is missing")

    sig = eval_formula(formula)
    start, end = SPLITS["train"][0], SPLITS["val_a"][1]
    oos, folds = _g.walk_forward(sig, start, end, train_years=train_years,
                                 step_months=step_months, horizon=horizon)
    return {
        "oos_dates": [d.isoformat() for d in oos.index],
        "oos_ic": [float(x) for x in oos.to_numpy()],
        "folds": folds,
    }


@st.cache_data(show_spinner=False)
def thresholds() -> dict:
    """Gate-B / ledger thresholds, read live from ``src.gates`` / ``src.config``
    — never retyped into dashboard code (Section 0.8.1 #4)."""
    from src import gates as _g
    from src.config import HOLDOUT_PEEK_BUDGET, T_STAT_BAR

    return {
        "T_STAT_BAR": T_STAT_BAR,
        "MIN_MARGINAL_IC": _g.MIN_MARGINAL_IC,
        "DSR_MIN": _g.DSR_MIN,
        "PBO_MAX": _g.PBO_MAX,
        "MIN_DSR_SAMPLE": _g.MIN_DSR_SAMPLE,
        "HOLDOUT_PEEK_BUDGET": HOLDOUT_PEEK_BUDGET,
    }


def assert_ledger_append_only() -> tuple[bool, str]:
    """Run ``src.ledger.assert_no_row_removal_sql()`` live — a structural scan
    of ``src/ledger.py``'s source text; no database is touched."""
    from src.ledger import assert_no_row_removal_sql

    try:
        assert_no_row_removal_sql()
        return True, "no DELETE / DROP TABLE / TRUNCATE in src/ledger.py — PASS"
    except AssertionError as exc:
        return False, str(exc)


@st.cache_data(show_spinner=False)
def redteam_menu() -> dict:
    """``{'menu': [...11 names], 'decisive': [...5 names]}`` from
    ``src.redteam`` — read live, never retyped."""
    from src.redteam import DECISIVE_TESTS, REDTEAM_MENU

    return {"menu": list(REDTEAM_MENU), "decisive": list(DECISIVE_TESTS)}
