"""Phase 5 acceptance tests — operator library, AST tools, alpha zoo.

Plain ``pytest``, no network.  The headline test is
:func:`test_time_series_operators_are_causal` — for every time-series operator,
changing a FUTURE input value must not change any EARLIER output value.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import operators as O
from src import zoo as Z
from src.ast_tools import (
    ParseError,
    canonical,
    complexity,
    evaluate,
    fingerprint,
    parse,
)

# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #
IDX5 = pd.bdate_range("2021-01-04", periods=5)
COLS3 = ["A", "B", "C"]


@pytest.fixture
def P() -> pd.DataFrame:
    """The hand-computed 5x3 panel every unit test reasons about."""
    return pd.DataFrame(
        {"A": [1.0, 2, 3, 4, 5], "B": [5.0, 4, 3, 2, 1], "C": [2.0, 2, 2, 2, 2]},
        index=IDX5,
    )


def _rand_panel(T: int = 40, N: int = 4, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        rng.standard_normal((T, N)),
        index=pd.bdate_range("2020-01-01", periods=T),
        columns=[f"S{i}" for i in range(N)],
    )


# A fixed second operand for the binary time-series operators, independent of
# the panel whose future we perturb in the causality test.
_Y = _rand_panel(seed=99)

TS_CALLS = {
    "delay": lambda x: O.delay(x, 3),
    "delta": lambda x: O.delta(x, 3),
    "ts_mean": lambda x: O.ts_mean(x, 5),
    "ts_std": lambda x: O.ts_std(x, 5),
    "ts_min": lambda x: O.ts_min(x, 5),
    "ts_max": lambda x: O.ts_max(x, 5),
    "ts_rank": lambda x: O.ts_rank(x, 5),
    "ts_sum": lambda x: O.ts_sum(x, 5),
    "ts_argmax": lambda x: O.ts_argmax(x, 5),
    "ts_product": lambda x: O.ts_product(x, 5),
    "decay_linear": lambda x: O.decay_linear(x, 5),
    "correlation": lambda x: O.correlation(x, _Y, 5),
    "covariance": lambda x: O.covariance(x, _Y, 5),
}


# --------------------------------------------------------------------------- #
# THE mandatory causality test                                                 #
# --------------------------------------------------------------------------- #
def test_every_time_series_operator_has_a_causality_case():
    assert set(TS_CALLS) == set(O.TIME_SERIES_OPS), (
        set(O.TIME_SERIES_OPS) ^ set(TS_CALLS)
    )


@pytest.mark.parametrize("name", sorted(TS_CALLS))
def test_time_series_operators_are_causal(name):
    """Changing input row ``p`` must leave every output row < ``p`` untouched."""
    call = TS_CALLS[name]
    x = _rand_panel(seed=1)
    base = call(x)
    n = x.shape[1]
    perturb = np.tile([-1e6, 1e6], n)[:n]     # moves min, max, mean, argmax, ...
    for p in (12, 25, len(x) - 1):
        x2 = x.copy()
        x2.iloc[p] = perturb
        got = call(x2)
        pd.testing.assert_frame_equal(
            base.iloc[:p], got.iloc[:p],
            obj=f"{name}: future row {p} leaked into an earlier output",
        )
    # non-vacuity: perturbing a mid row MUST change some later output
    x3 = x.copy()
    x3.iloc[15] = perturb
    assert not np.array_equal(
        call(x3).to_numpy(), base.to_numpy(), equal_nan=True
    ), f"{name}: perturbation had no effect anywhere — test is vacuous"


def test_if_else_and_ts_product_are_causal():
    """The two operators added for Alpha101 coverage, explicitly."""
    x, c = _rand_panel(seed=2), _rand_panel(seed=3)
    base = O.if_else(O.gt(c, 0.0), x, O.mul(x, -1))
    x2 = x.copy()
    x2.iloc[20] += 1000.0
    got = O.if_else(O.gt(c, 0.0), x2, O.mul(x2, -1))
    pd.testing.assert_frame_equal(base.iloc[:20], got.iloc[:20])

    base_p = O.ts_product(x, 4)
    got_p = O.ts_product(x2, 4)
    pd.testing.assert_frame_equal(base_p.iloc[:20], got_p.iloc[:20])


# --------------------------------------------------------------------------- #
# Per-operator unit tests on the hand-computed 5x3 panel                        #
# --------------------------------------------------------------------------- #
def test_cross_sectional_operators(P):
    np.testing.assert_allclose(O.rank(P).iloc[0], [1 / 3, 1.0, 2 / 3])
    np.testing.assert_allclose(O.demean_cs(P).iloc[0], [1 - 8 / 3, 5 - 8 / 3, 2 - 8 / 3])
    np.testing.assert_allclose(O.scale(P).iloc[0], [1 / 8, 5 / 8, 2 / 8])
    z = O.zscore_cs(P).iloc[0]
    np.testing.assert_allclose(z.to_numpy(), z.to_numpy())  # finite
    assert abs(z.mean()) < 1e-12
    np.testing.assert_allclose(O.zscore_cs(P).iloc[0].std(ddof=0), 1.0)


def test_sector_neutral(P):
    sec = pd.Series({"A": "x", "B": "x", "C": "y"})
    out = O.sector_neutral(P, sec)
    # row 0: x-group [1,5] mean 3 -> [-2, 2]; y-group [2] -> 0
    np.testing.assert_allclose(out.iloc[0].to_numpy(), [-2.0, 2.0, 0.0])


def test_time_series_operators_hand_values(P):
    np.testing.assert_allclose(O.delay(P, 1).iloc[1], [1, 5, 2])
    assert O.delay(P, 1).iloc[0].isna().all()
    np.testing.assert_allclose(O.delta(P, 1).iloc[1], [1, -1, 0])
    np.testing.assert_allclose(O.ts_mean(P, 2).iloc[1], [1.5, 4.5, 2.0])
    np.testing.assert_allclose(O.ts_sum(P, 2).iloc[1], [3, 9, 4])
    np.testing.assert_allclose(O.ts_std(P, 2).iloc[1], [0.5 ** 0.5, 0.5 ** 0.5, 0.0])
    np.testing.assert_allclose(O.ts_min(P, 3).iloc[2], [1, 3, 2])
    np.testing.assert_allclose(O.ts_max(P, 3).iloc[2], [3, 5, 2])
    np.testing.assert_allclose(O.ts_rank(P, 3).iloc[2], [1.0, 1 / 3, 1.0])
    np.testing.assert_allclose(O.ts_argmax(P, 3).iloc[2], [0.0, 2.0, 2.0])
    np.testing.assert_allclose(O.decay_linear(P, 2).iloc[1], [5 / 3, 13 / 3, 2.0])
    np.testing.assert_allclose(O.ts_product(P, 2).iloc[1], [2, 20, 4])


def test_correlation_and_covariance(P):
    y = P * 2 + 1
    np.testing.assert_allclose(O.correlation(P, y, 3).iloc[2], [1.0, 1.0, np.nan])
    np.testing.assert_allclose(O.covariance(P, P, 2).iloc[1], [0.5, 0.5, 0.0])
    c = O.correlation(_rand_panel(seed=4), _rand_panel(seed=5), 10)
    assert (c.abs().to_numpy()[~np.isnan(c.to_numpy())] <= 1.0 + 1e-9).all()


def test_elementwise_operators(P):
    np.testing.assert_allclose(O.add(P, 1).iloc[0], [2, 6, 3])
    np.testing.assert_allclose(O.sub(P, P).iloc[0], [0, 0, 0])
    np.testing.assert_allclose(O.mul(P, 2).iloc[0], [2, 10, 4])
    np.testing.assert_allclose(O.min(P, 3).iloc[0], [1, 3, 2])
    np.testing.assert_allclose(O.max(P, 3).iloc[0], [3, 5, 3])
    np.testing.assert_allclose(O.sign(O.sub(P, 3)).iloc[0], [-1, 1, -1])
    np.testing.assert_allclose(O.abs(O.sub(P, 3)).iloc[0], [2, 2, 1])
    np.testing.assert_allclose(O.signed_power(O.sub(P, 3), 2).iloc[0], [-4, 4, -1])


def test_div_and_log_guards(P):
    assert O.div(P, 0).iloc[0].isna().all()
    assert O.div(P, O.sub(P, P)).iloc[0].isna().all()          # frame of zeros
    assert np.isnan(O.log(O.sub(P, 3)).iloc[0, 0])             # log(-2)
    np.testing.assert_allclose(O.log(P).iloc[0, 0], 0.0)       # log(1)
    assert np.isnan(O.pow(O.sub(P, 3), 0.5).iloc[0, 0])        # (-2) ** 0.5
    np.testing.assert_allclose(O.pow(P, 2).iloc[0], [1, 25, 4])


def test_comparisons_and_if_else(P):
    np.testing.assert_allclose(O.lt(P, 3).iloc[0], [1, 0, 1])
    np.testing.assert_allclose(O.gt(P, 3).iloc[0], [0, 1, 0])
    np.testing.assert_allclose(O.le(P, 2).iloc[0], [1, 0, 1])
    np.testing.assert_allclose(O.ge(P, 2).iloc[0], [0, 1, 1])
    np.testing.assert_allclose(O.eq(P, 2).iloc[0], [0, 0, 1])
    out = O.if_else(O.gt(P, 3), P, O.mul(P, -1))
    np.testing.assert_allclose(out.iloc[0], [-1, 5, -2])
    # NaN in cond propagates
    cond = O.gt(P, 3)
    cond.iloc[0, 0] = np.nan
    assert np.isnan(O.if_else(cond, P, P).iloc[0, 0])


def test_rank_range_and_nan_preservation():
    x = _rand_panel(seed=7)
    x.iloc[3, 1] = np.nan
    r = O.rank(x)
    assert ((r >= 0) & (r <= 1)).to_numpy()[~np.isnan(r.to_numpy())].all()
    assert np.isnan(r.iloc[3, 1])
    assert r.notna().sum().sum() == x.notna().sum().sum()


def test_operators_are_deterministic():
    p = Z.demo_panel(n_days=400, n_symbols=10)
    a = evaluate(Z.ZOO_BY_NAME["alpha101_003"]["formula"], p)
    b = evaluate(Z.ZOO_BY_NAME["alpha101_003"]["formula"], p)
    pd.testing.assert_frame_equal(a, b)


# --------------------------------------------------------------------------- #
# Parser / AST tools                                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [
    "__import__('os')",
    "close.values",
    "[x for x in y]",
    "lambda x: x",
    "close[0]",
    "rank(close); import os",
    "f'{close}'",
])
def test_parser_rejects_unsafe_syntax(bad):
    with pytest.raises(ParseError):
        parse(bad)


def test_parser_rejects_unknown_names():
    with pytest.raises(ParseError):
        parse("frobnicate(close)")
    with pytest.raises(ParseError):
        parse("no_such_field")
    # non-strict keeps the safety whitelist but allows unknown names
    parse("frobnicate(a, b)", strict=False)


def test_parser_accepts_valid_formulas():
    parse("close + volume")
    parse("mul(-1, rank(ts_mean(volume, 5)))")
    parse("rank(close) ** 2")


def test_negative_literal_is_folded():
    assert canonical("-1 * rank(close)") == canonical("mul(rank(close), -1)")
    assert canonical("mul(-1, close)") == "mul(-1,close)"


def test_canonical_sorts_commutative_and_folds_constants():
    assert canonical("a*b") == canonical("b*a")
    assert canonical("add(close, open)") == canonical("add(open, close)")
    assert canonical("mul(2, 3)") == "6"
    assert canonical("add(mul(2, 3), close)") == canonical("add(close, 6)")
    assert canonical("correlation(volume, close, 10)") == \
        canonical("correlation(close, volume, 10)")
    # non-commutative operators are NOT reordered
    assert canonical("sub(a, b)") != canonical("sub(b, a)")


def test_complexity_node_count_on_a_hand_tree():
    c = complexity("mul(rank(close), delta(volume, 5))")
    assert c == {"nodes": 6, "depth": 3, "free_params": 1}
    # free_params counts every numeric literal, window sizes included
    assert complexity("ts_mean(add(close, 1.5), 20)")["free_params"] == 2


def test_fingerprint_discriminates():
    fa = fingerprint("mul(-1, correlation(rank(open), rank(volume), 10))")
    fb = fingerprint("add(open, volume)")
    assert fa != fb
    # same structure, different window -> same fingerprint (escalates to canonical)
    fc = fingerprint("mul(-1, correlation(rank(open), rank(volume), 5))")
    assert fa == fc


# --------------------------------------------------------------------------- #
# The alpha zoo                                                                #
# --------------------------------------------------------------------------- #
def test_zoo_size_and_composition():
    assert len(Z.ZOO) == 35
    alpha = [e for e in Z.ZOO if e["source"].startswith("Kakushadze")]
    classical = [e for e in Z.ZOO if e["source"].startswith("classical")]
    assert len(alpha) == 25
    assert len(classical) == 10
    assert "alpha101_056" in Z.SKIPPED_ALPHA101       # disclosed skip
    assert not any(e["name"] == "alpha101_056" for e in Z.ZOO)


def test_every_zoo_formula_parses_evaluates_and_is_finite():
    panel = Z.demo_panel()
    for e in Z.ZOO:
        node = parse(e["formula"])                    # strict parse
        out = evaluate(node, panel)
        arr = np.asarray(out, dtype=float)
        assert np.isfinite(arr).sum() > 0, e["name"]
        assert e["fingerprint"] == fingerprint(e["formula"])
        assert e["canonical"] == canonical(e["formula"])


def test_is_zoo_duplicate_detects_commuted_operands():
    e = Z.ZOO_BY_NAME["alpha101_003"]
    # commute both the outer mul and the inner correlation's first two args
    commuted = "mul(correlation(rank(volume), rank(open), 10), -1)"
    dup, name = Z.is_zoo_duplicate(commuted)
    assert dup and name == "alpha101_003"


def test_is_zoo_duplicate_false_for_a_different_formula_same_fields():
    # same fields (open, volume) as alpha101_003, genuinely different structure
    dup, name = Z.is_zoo_duplicate("rank(sub(open, ts_mean(volume, 10)))")
    assert not dup and name is None
    # same operators/fields but a different window -> still not an exact dup
    dup2, _ = Z.is_zoo_duplicate(
        "mul(-1, correlation(rank(open), rank(volume), 5))"
    )
    assert not dup2


def test_is_zoo_duplicate_exact_match():
    for e in Z.ZOO:
        dup, name = Z.is_zoo_duplicate(e["formula"])
        assert dup and name == e["name"], e["name"]
