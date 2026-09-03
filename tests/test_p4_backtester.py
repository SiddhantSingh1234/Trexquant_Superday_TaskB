"""Phase 4 acceptance tests — plain pytest, no network.

Every test runs against the Phase-0 synthetic fixtures (installed via
``backtester.use_panel``), whose fake ``mom_21`` carries a planted RankIC of
~0.04 and whose ``fwd_ret_1`` is a perfect leaked predictor of itself.  The real
panel is never required.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import backtester as bt
from src import contracts as C
from src.contracts import PLANTED_IC

N_DAYS = 1400          # 2015-01 .. ~2020-05 on the b-day calendar
N_SYMBOLS = 60
SEED = 42


@pytest.fixture(scope="module", autouse=True)
def _panel():
    feats = C.make_fake_features(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED)
    labs = C.make_fake_labels(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED)
    bt.use_panel(feats, labs)
    yield feats, labs
    bt.clear_panel()


@pytest.fixture(scope="module")
def planted_signal(_panel):
    feats, _ = _panel
    return feats.pivot_table(index="date", columns="symbol", values="mom_21")


@pytest.fixture(scope="module")
def leaky_signal(_panel):
    _, labs = _panel
    return labs.pivot_table(index="date", columns="symbol", values="fwd_ret_1")


@pytest.fixture(scope="module")
def noise_signal(planted_signal):
    rng = np.random.default_rng(SEED)
    arr = rng.standard_normal(planted_signal.shape)
    return pd.DataFrame(arr, index=planted_signal.index, columns=planted_signal.columns)


# --------------------------------------------------------------------------- #
# Acceptance criteria                                                          #
# --------------------------------------------------------------------------- #
def test_random_noise_has_no_signal(noise_signal):
    """Criterion 1: random noise -> |rank_ic| < 0.01 and |t_stat| < 2."""
    m = bt.backtest(noise_signal, "train+val_a")
    assert abs(m["rank_ic"]) < 0.01, m["rank_ic"]
    assert abs(m["t_stat"]) < 2.0, m["t_stat"]


def test_planted_feature_recovers_its_ic(planted_signal):
    """Criterion 2: the known-good fake feature -> rank_ic within 0.01 of 0.04."""
    m = bt.backtest(planted_signal, "train+val_a")
    assert abs(m["rank_ic"] - PLANTED_IC) < 0.01, (m["rank_ic"], PLANTED_IC)


def test_leaky_feature_is_detected(leaky_signal):
    """Criterion 3: fwd_ret_1 as its own signal -> rank_ic > 0.9."""
    m = bt.backtest(leaky_signal, "val_a")
    assert m["rank_ic"] > 0.9, m["rank_ic"]


def test_negating_signal_negates_rank_ic(planted_signal):
    """Criterion 4: negating the signal exactly negates rank_ic and flips sign."""
    pos = bt.backtest(planted_signal, "val_a")
    neg = bt.backtest(-planted_signal, "val_a")
    assert pos["rank_ic"] == pytest.approx(-neg["rank_ic"], abs=1e-12)
    assert pos["ic"] == pytest.approx(-neg["ic"], abs=1e-12)
    assert pos["sign"] == 1 and neg["sign"] == -1


def test_extra_lag_changes_a_short_horizon_signal(leaky_signal):
    """Criterion 5: extra_lag=1 measurably changes a signal with genuine
    short-horizon predictive power (a 1-day-forward return predicting itself)."""
    base = bt.backtest(leaky_signal, "val_a")
    lagged = bt.backtest(leaky_signal, "val_a", extra_lag=1)
    assert base["rank_ic"] > 0.9
    assert abs(base["rank_ic"] - lagged["rank_ic"]) > 0.5, (base["rank_ic"], lagged["rank_ic"])


def test_cost_bps_monotonically_lowers_sharpe(planted_signal):
    """Criterion 6: increasing cost_bps monotonically reduces sharpe."""
    sharpes = [
        bt.backtest(planted_signal, "train+val_a", cost_bps=c)["sharpe"]
        for c in (0, 5, 10, 20, 40, 80)
    ]
    assert all(later < earlier for earlier, later in zip(sharpes, sharpes[1:])), sharpes


def test_holdout_requires_token(planted_signal):
    """Criterion 7: split='holdout' without the token raises; with it, it runs."""
    with pytest.raises(PermissionError):
        bt.backtest(planted_signal, "holdout")
    m = bt.backtest(planted_signal, "holdout", i_have_a_peek_token=True)
    assert set(m) == set(bt._METRIC_KEYS)


def test_purge_embargo_removes_expected_rows():
    """Criterion 8: purge+embargo removes the expected number of rows for h=5.

    Direct test of the reusable helper Phase 6's CSCV will call.  ``train`` spans
    both sides of a 10-day ``test`` block on a 60-day calendar.
    """
    cal = pd.bdate_range("2020-01-01", periods=60)
    train = cal[:40].append(cal[50:])          # 50 train days, test = positions 40..49
    test = cal[40:50]

    # purge only (h=5): label window overlaps -> positions 34..39 dropped = 6
    keep = bt.purge_embargo_mask(train, test, horizon=5, embargo_days=0, calendar=cal)
    assert (~keep).sum() == 6, (~keep).sum()

    # + embargo 5: also positions 50..54 -> 11 total
    keep5 = bt.purge_embargo_mask(train, test, horizon=5, embargo_days=5, calendar=cal)
    assert (~keep5).sum() == 11, (~keep5).sum()

    # h=1, no embargo: only positions 38,39 -> 2
    keep1 = bt.purge_embargo_mask(train, test, horizon=1, embargo_days=0, calendar=cal)
    assert (~keep1).sum() == 2, (~keep1).sum()


def test_holdout_tail_purge_targets_only_the_sealed_boundary():
    """The single-split engine's ONLY tail purge is at the HOLDOUT boundary:
    a val_b-like eval window loses its last ~horizon days; a val_a-like window
    that ends well before HOLDOUT loses nothing."""
    from src.config import HOLDOUT_START
    cal = pd.bdate_range("2022-01-03", "2022-09-30")          # straddles 2022-07-01
    hpos = cal.get_indexer([cal[cal >= HOLDOUT_START][0]])[0]

    vb_eval = cal[cal < HOLDOUT_START]                        # ends 2022-06-30
    keep1 = bt._purge_holdout_tail(vb_eval, cal, purge_days=1)
    keep21 = bt._purge_holdout_tail(vb_eval, cal, purge_days=21)
    assert len(vb_eval) - len(keep1) == 2                     # last 2 days cross
    assert len(vb_eval) - len(keep21) == 22                   # last 22 days cross
    assert keep21[-1] == cal[hpos - 23]

    # an eval window ending 40 trading days before HOLDOUT: untouched even at h=21
    early = cal[:hpos - 40]
    assert list(bt._purge_holdout_tail(early, cal, purge_days=21)) == list(early)


def test_tail_purge_is_a_noop_away_from_holdout(planted_signal):
    """On the fixture (panel ends ~2020, never reaches HOLDOUT) the engine applies
    no tail purge; n_days still falls with horizon purely from NaN-label drop at
    the panel end."""
    n1 = bt.backtest(planted_signal, "val_a", horizon=1)["n_days"]
    n5 = bt.backtest(planted_signal, "val_a", horizon=5)["n_days"]
    n21 = bt.backtest(planted_signal, "val_a", horizon=21)["n_days"]
    assert n1 >= n5 >= n21


def test_real_panel_val_b_does_not_read_holdout():
    """On the real panel, val_b's last `horizon` days (whose fwd_ret_h P3 derived
    from HOLDOUT opens) are purged; val_a is untouched."""
    from src.config import FEATURES_PARQUET, LABELS_PARQUET
    if not (FEATURES_PARQUET.exists() and LABELS_PARQUET.exists()):
        pytest.skip("real panel not built")
    bt.clear_panel()
    try:
        f = pd.read_parquet(FEATURES_PARQUET)
        sig = f.pivot_table(index="date", columns="symbol", values="mom_126")
        vb1 = bt.backtest(sig, "val_b", horizon=1)["n_days"]
        vb21 = bt.backtest(sig, "val_b", horizon=21)["n_days"]
        va1 = bt.backtest(sig, "val_a", horizon=1)["n_days"]
        va21 = bt.backtest(sig, "val_a", horizon=21)["n_days"]
        assert vb1 - vb21 >= 15            # ~20 trailing val_b days purged
        assert abs(va1 - va21) <= 2        # val_a barely moves (only NaN drop)
    finally:
        bt.use_panel(
            C.make_fake_features(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED),
            C.make_fake_labels(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED),
        )


def test_two_identical_calls_are_bit_identical(planted_signal):
    """Criterion 9: determinism."""
    a = bt.backtest(planted_signal, "val_a", horizon=5, cost_bps=15, neutralize="sector")
    b = bt.backtest(planted_signal, "val_a", horizon=5, cost_bps=15, neutralize="sector")
    assert a == b
    assert a["decay"] == b["decay"]


# --------------------------------------------------------------------------- #
# Contract shape / switch coverage                                             #
# --------------------------------------------------------------------------- #
def test_metrics_dict_matches_section_0_5(planted_signal):
    m = bt.backtest(planted_signal, "val_a", horizon=5)
    assert tuple(m) == bt._METRIC_KEYS
    assert list(m["decay"]) == [1, 2, 3, 5, 10, 21]
    assert isinstance(m["n_days"], int) and isinstance(m["n_obs"], int)
    assert isinstance(m["sign"], int) and m["sign"] in (-1, 1)
    assert m["rank_ic"] == pytest.approx(m["decay"][5])      # headline == decay[horizon]


def test_decay_curve_decays_for_the_planted_signal(planted_signal):
    """The fixture's fwd_ret_h = PLANTED_IC*latent + noise, noise ~ N(0, sqrt(h)),
    so corr(latent, fwd_ret_h) = PLANTED_IC / sqrt(PLANTED_IC**2 + h): the decay
    curve should fall monotonically from ~0.04 at h=1 toward ~0 at h=21."""
    d = bt.backtest(planted_signal, "train+val_a")["decay"]
    assert d[1] == pytest.approx(PLANTED_IC, abs=0.01)
    curve = [d[h] for h in (1, 2, 3, 5, 10, 21)]
    assert all(later < earlier for earlier, later in zip(curve, curve[1:])), curve
    assert d[21] < d[1] / 2


@pytest.mark.parametrize("sub", [
    {"years": [2018, 2019]},
    {"size_tercile": "large"},
    {"min_turnover": 1e6},
    {"exclude_symbols": ["SYM001", "SYM002"]},
])
def test_subsample_switches_run_and_shrink_the_panel(planted_signal, sub):
    full = bt.backtest(planted_signal, "val_a")
    m = bt.backtest(planted_signal, "val_a", subsample=sub)
    assert m["n_obs"] <= full["n_obs"]
    assert np.isfinite(m["rank_ic"])


def _trending_labels(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED):
    """`make_fake_labels` with a market cycle added to the *raw* forward returns.

    The demeaned labels (the actual target) are untouched — a common per-day
    term cancels under cross-sectional demeaning — so RankIC behaviour is
    preserved, but the equal-weight market proxy now sweeps through genuine
    bull / bear / high-vol regimes.
    """
    labs = C.make_fake_labels(n_days, n_symbols, seed)
    dates = np.sort(labs["date"].unique())
    t = np.arange(len(dates))
    cycle = dict(zip(dates, 0.004 * np.sin(2 * np.pi * t / 240.0)))
    add = labs["date"].map(cycle).to_numpy()
    for h in (1, 2, 3, 5, 10, 21):
        labs[f"fwd_ret_{h}"] = (labs[f"fwd_ret_{h}"].to_numpy() + add).astype(np.float64)
    return labs


@pytest.mark.parametrize("regime", list(bt.VALID_REGIMES))
def test_regime_subsamples_run_on_a_trending_market(planted_signal, regime):
    """Every regime label populates and shrinks the panel on a market with a
    real cycle (the flat synthetic market rarely crosses +/-5%)."""
    feats = C.make_fake_features(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED)
    bt.use_panel(feats, _trending_labels())
    try:
        full = bt.backtest(planted_signal, "train+val_a")
        m = bt.backtest(planted_signal, "train+val_a", subsample={"regime": regime})
        assert 0 < m["n_obs"] <= full["n_obs"], (regime, m["n_obs"], full["n_obs"])
        assert np.isfinite(m["rank_ic"])
    finally:
        bt.use_panel(
            C.make_fake_features(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED),
            C.make_fake_labels(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED),
        )


def test_unknown_regime_raises(planted_signal):
    with pytest.raises(ValueError):
        bt.backtest(planted_signal, "val_a", subsample={"regime": "sideways"})


def test_regime_labels_are_expanding_window_only():
    """Truncating the future must not move a single past regime label — the
    tripwire against a full-sample volatility / return threshold (a look-ahead)."""
    labs = _trending_labels()
    full = bt._regime_labels(labs)
    cut = np.sort(labs["date"].unique())[: int(labs["date"].nunique() * 0.55)]
    trunc = bt._regime_labels(labs[labs["date"].isin(cut)])
    assert full.loc[trunc.index].equals(trunc)
    # and the labels are actually populated (the test above would pass vacuously
    # on an all-False frame)
    assert full["bull"].sum() > 20 and full["bear"].sum() > 20
    assert full["highvol"].sum() > 20


def test_neutralize_sector_runs(planted_signal):
    m = bt.backtest(planted_signal, "val_a", neutralize="sector")
    assert np.isfinite(m["rank_ic"])
    with pytest.raises(ValueError):
        bt.backtest(planted_signal, "val_a", neutralize="industry")


def test_unknown_split_and_horizon_raise(planted_signal):
    with pytest.raises(ValueError):
        bt.backtest(planted_signal, "nonsense")
    with pytest.raises(ValueError):
        bt.backtest(planted_signal, "val_a", horizon=7)


def test_long_signal_form_is_accepted(_panel):
    feats, _ = _panel
    long_sig = feats[["date", "symbol", "mom_21"]]
    wide_sig = feats.pivot_table(index="date", columns="symbol", values="mom_21")
    assert bt.backtest(long_sig, "val_a") == bt.backtest(wide_sig, "val_a")
