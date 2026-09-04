"""D4 — formula-tooling acceptance tests (Backtester + Operators & Zoo).

Exercises ``dashboard.lib.engine`` (``eval_formula`` / ``run_backtest`` and the
D4 helpers) and the ``src`` parsing/zoo surface the two pages rely on.  The
engine helpers are ``@st.cache_data`` — callable directly outside a Streamlit
runtime (they only print a "no runtime" warning).

Needs the real panel (``data/panel/{features,labels}.parquet``) and
``data/prices/ohlcv.parquet``; tests that touch a backtest ``skip`` cleanly if a
panel is absent.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]

from dashboard.lib import engine as eng  # noqa: E402
from src.ast_tools import ParseError, canonical  # noqa: E402
from src.zoo import ZOO_BY_NAME, is_zoo_duplicate  # noqa: E402

_MOM = ZOO_BY_NAME["classical_momentum_12_1"]["formula"]
_METRIC_KEYS = {"rank_ic", "ic", "icir", "t_stat", "sharpe", "ann_return",
                "turnover", "mdd", "n_days", "n_obs", "decay", "sign"}


def _panel_ready() -> bool:
    return (ROOT / "data" / "panel" / "features.parquet").exists() and \
           (ROOT / "data" / "panel" / "labels.parquet").exists() and \
           (ROOT / "data" / "prices" / "ohlcv.parquet").exists()


requires_panel = pytest.mark.skipif(not _panel_ready(), reason="real panel/prices absent")


# --------------------------------------------------------------------------- #
# eval_formula                                                                 #
# --------------------------------------------------------------------------- #
@requires_panel
def test_eval_formula_returns_wide_frame():
    sig = eng.eval_formula(_MOM)
    assert isinstance(sig, pd.DataFrame)
    assert sig.shape[0] > 1000 and sig.shape[1] > 50
    assert str(sig.index.dtype).startswith("datetime64[ns")


@requires_panel
def test_price_panel_has_the_formula_fields():
    panel = eng.price_panel()
    for f in ("open", "high", "low", "close", "volume", "vwap", "returns", "size_proxy"):
        assert f in panel, f
        assert isinstance(panel[f], pd.DataFrame)


@pytest.mark.parametrize("bad", ["__import__('os')", "close.values",
                                 "[x for x in y]", "lambda x: x"])
def test_eval_formula_rejects_unsafe_strings(bad):
    with pytest.raises(ParseError):
        eng.eval_formula(bad)


# --------------------------------------------------------------------------- #
# run_backtest                                                                 #
# --------------------------------------------------------------------------- #
@requires_panel
def test_run_backtest_full_metrics_dict():
    m = eng.run_backtest(_MOM, "val_a", horizon=1)
    assert _METRIC_KEYS <= set(m)
    assert set(m["decay"]) == {1, 2, 3, 5, 10, 21}
    assert m["n_days"] > 100
    assert m["sign"] in (-1, 1)
    assert m["_equity_returns"] and len(m["_equity_returns"]) == m["n_days"]


def test_run_backtest_rejects_holdout():
    with pytest.raises(PermissionError):
        eng.run_backtest(_MOM, "holdout")
    with pytest.raises(PermissionError):
        eng.score_signal("leaky", "holdout")


@requires_panel
def test_run_backtest_cache_hit_is_fast():
    eng.run_backtest(_MOM, "val_b", horizon=2, cost_bps=5.0)      # warm
    t0 = time.perf_counter()
    eng.run_backtest(_MOM, "val_b", horizon=2, cost_bps=5.0)      # hit
    assert (time.perf_counter() - t0) < 0.2


# --------------------------------------------------------------------------- #
# the acceptance-evidence board                                                #
# --------------------------------------------------------------------------- #
@requires_panel
def test_noise_signal_looks_like_noise():
    m = eng.score_signal("noise", "val_a")
    assert abs(m["rank_ic"]) < 0.01, m["rank_ic"]
    assert abs(m["t_stat"]) < 2.0, m["t_stat"]


@requires_panel
def test_leaky_signal_is_caught():
    m = eng.score_signal("leaky", "val_a")
    assert m["rank_ic"] > 0.9, m["rank_ic"]


@requires_panel
def test_negation_flips_rank_ic_exactly():
    pos = eng.run_backtest(_MOM, "val_a", horizon=1)
    neg = eng.run_backtest(f"mul(-1, {_MOM})", "val_a", horizon=1)
    assert np.isclose(pos["rank_ic"], -neg["rank_ic"], atol=1e-9)
    assert pos["sign"] == -neg["sign"]


@requires_panel
def test_cost_sweep_is_monotonically_decreasing():
    sharpes = [eng.run_backtest(_MOM, "val_a", horizon=1, cost_bps=float(c))["sharpe"]
               for c in (0, 5, 15, 30)]
    assert all(a >= b - 1e-9 for a, b in zip(sharpes, sharpes[1:])), sharpes


# --------------------------------------------------------------------------- #
# purge / embargo                                                              #
# --------------------------------------------------------------------------- #
@requires_panel
def test_purge_embargo_demo_widens_with_horizon():
    d1 = eng.purge_embargo_demo(horizon=1)
    d21 = eng.purge_embargo_demo(horizon=21)
    assert d1["n_dropped"] >= 1
    assert d21["n_dropped"] > d1["n_dropped"]
    assert 0 <= d1["dropped_pct"] <= 100
    assert {r["state"] for r in d1["timeline"]} <= {"kept", "purged", "embargo", "test"}


# --------------------------------------------------------------------------- #
# operators & zoo                                                              #
# --------------------------------------------------------------------------- #
def test_zoo_formulas_passthrough():
    z = eng.zoo_formulas()
    assert len(z) == 35
    assert all({"name", "formula", "source"} <= set(e) for e in z)


@pytest.mark.parametrize("name", ["classical_momentum_12_1", "alpha101_006",
                                  "alpha101_029", "classical_beta"])
def test_ast_parse_and_dot_build(name):
    from src.ast_tools import parse
    node = parse(ZOO_BY_NAME[name]["formula"], strict=False)
    # a minimal AST→DOT walk, same shape as the page's _ast_graph
    import graphviz
    g = graphviz.Digraph()
    seen = [0]

    def add(n):
        seen[0] += 1
        nid = f"n{seen[0]}"
        if n[0] in ("const", "field"):
            g.node(nid, str(n[1]))
        else:
            g.node(nid, n[1])
            for c in n[2]:
                g.edge(nid, add(c))
        return nid

    add(node)
    assert "digraph" in g.source and seen[0] >= 3


def test_is_zoo_duplicate_matches_commuted_operands():
    orig = ZOO_BY_NAME["alpha101_014"]["formula"]
    commuted = "mul(correlation(open, volume, 10), mul(-1, rank(delta(returns, 3))))"
    dup, match = is_zoo_duplicate(commuted)
    assert dup and match == "alpha101_014"
    assert canonical(commuted) == canonical(orig)


@requires_panel
def test_zoo_backtest_row_shape():
    row = eng.zoo_backtest("classical_low_volatility", "val_a", 1)
    assert row["name"] == "classical_low_volatility"
    assert {"nodes", "depth", "free_params", "rank_ic", "ok"} <= set(row)
    assert row["ok"] is True and np.isfinite(row["rank_ic"])
