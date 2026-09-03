"""Phase 9 acceptance tests — plain pytest, no network.

The eleven red-team falsification tests + the survive/kill rule.  Every backtest
fired by the red-team must be recorded with ``counts_as_trial=0`` (rejection-only)
and no test may promote a candidate.

The fixture panel plants an **AR(1) latent** (slow-moving), so a genuine signal
built from it *keeps* predictive content across a one-day lag — the standard
Phase-0 fixture uses an IID latent, where every signal dies under ``extra_lag``
and no "survivor" case is expressible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import backtester as bt
from src import contracts as C
from src import redteam as RT
from src.contracts import HORIZONS, NSE_SECTORS
from src.ledger import Ledger

N_DAYS = 1200          # 2015-01 .. ~2019-08 on the b-day calendar
N_SYMBOLS = 50
SEED = 42
SPLIT = "train+val_a"
AR_PHI = 0.9           # latent autocorrelation — a 1-day lag costs ~10%, not 100%


# --------------------------------------------------------------------------- #
# Fixture panel                                                                #
# --------------------------------------------------------------------------- #
def _persistent_panel(n_days=N_DAYS, n_syms=N_SYMBOLS, seed=SEED):
    rng = np.random.default_rng(seed)
    dates = pd.DatetimeIndex(pd.bdate_range("2015-01-01", periods=n_days).normalize()
                             ).as_unit("ns")
    syms = [f"SYM{i:03d}" for i in range(n_syms)]

    # AR(1) latent
    z = rng.standard_normal((n_days, n_syms))
    lat = np.empty_like(z)
    lat[0] = z[0]
    for t in range(1, n_days):
        lat[t] = AR_PHI * lat[t - 1] + np.sqrt(1 - AR_PHI**2) * z[t]
    latd = pd.DataFrame(lat, index=dates, columns=syms)
    latz = latd.sub(latd.mean(axis=1), axis=0).div(latd.std(axis=1, ddof=0), axis=0)

    def _long(frame, name):
        return (frame.stack(future_stack=True).rename_axis(["date", "symbol"])
                .rename(name).reset_index())

    # ---- features ----
    feats = _long(latz, "mom_21")
    styled = lambda s, nz: latz * s + nz * rng.standard_normal((n_days, n_syms))  # noqa: E731
    feat_cols = {
        "mom_126": styled(0.3, 0.9),
        "rev_5": styled(0.1, 1.0),
        "vol_21": np.abs(styled(0.2, 0.5)) + 0.05,
        "beta_63": 1.0 + styled(0.4, 0.7),
        "amihud_21": np.abs(styled(1.0, 0.9)) + 0.01,
        "turnover_21": 15.0 + styled(1.5, 0.8),
        "max_ret_21": np.abs(styled(0.04, 0.7)) + 0.005,
        "delivery_pct": np.clip(45.0 + styled(15.0, 0.9), 1.0, 99.0),
    }
    for name, arr in feat_cols.items():
        feats = feats.merge(_long(pd.DataFrame(arr, index=dates, columns=syms), name),
                            on=["date", "symbol"])
    feats = feats.merge(_long(pd.DataFrame(-np.abs(styled(0.2, 0.7)), index=dates,
                                           columns=syms), "dist_52wh"),
                        on=["date", "symbol"])
    # size_proxy: a persistent per-symbol level (spreads the size terciles)
    size_lvl = pd.DataFrame(np.tile(rng.normal(18, 1.5, n_syms), (n_days, 1)),
                            index=dates, columns=syms)
    feats = feats.merge(_long(size_lvl, "size_proxy"), on=["date", "symbol"])
    sec_rng = np.random.default_rng(seed + 1)
    sect = {s: NSE_SECTORS[int(sec_rng.integers(len(NSE_SECTORS)))] for s in syms}
    feats["sector"] = feats["symbol"].map(sect).astype(str)
    feats["date"] = feats["date"].astype("datetime64[ns]")
    for c in ("mom_21", "mom_126", "rev_5", "vol_21", "beta_63", "amihud_21",
              "turnover_21", "dist_52wh", "max_ret_21", "delivery_pct", "size_proxy"):
        feats[c] = feats[c].astype(np.float64)
    feats = feats.sort_values(["date", "symbol"]).reset_index(drop=True)

    # ---- labels: dem_h = k_h * latz + noise ~ N(0, sqrt(h)); peak IC at h=1 ----
    # A market cycle is added to the RAW returns only (it cancels under the
    # cross-sectional demean, so the target / RankIC are untouched) so the
    # equal-weight market proxy sweeps real bull / bear / high-vol regimes.
    t = np.arange(n_days)
    mkt_cycle = 0.004 * np.sin(2 * np.pi * t / 240.0)
    lab = None
    for h in HORIZONS:
        noise = rng.normal(0.0, np.sqrt(h), size=(n_days, n_syms))
        dem = 0.02 * (0.04 * latz.to_numpy() + noise)
        dem_df = pd.DataFrame(dem, index=dates, columns=syms)
        dem_df = dem_df.sub(dem_df.mean(axis=1), axis=0)
        raw_df = dem_df.add(pd.Series(mkt_cycle, index=dates), axis=0)
        for frame, col in ((raw_df, f"fwd_ret_{h}"), (dem_df, f"fwd_ret_{h}_demeaned")):
            piece = _long(frame, col)
            lab = piece if lab is None else lab.merge(piece, on=["date", "symbol"])
    for c in [f"fwd_ret_{h}" for h in HORIZONS] + [f"fwd_ret_{h}_demeaned" for h in HORIZONS]:
        lab[c] = lab[c].astype(np.float64)
    lab["date"] = lab["date"].astype("datetime64[ns]")
    lab = lab.sort_values(["date", "symbol"]).reset_index(drop=True)

    return feats, lab, latz


@pytest.fixture(scope="module", autouse=True)
def _panel():
    feats, labs, latz = _persistent_panel()
    C.validate_features(feats)
    C.validate_labels(labs)
    bt.use_panel(feats, labs)
    yield feats, labs, latz
    bt.clear_panel()


@pytest.fixture(scope="module")
def latz(_panel):
    return _panel[2]


@pytest.fixture(scope="module")
def prices():
    # ohlcv-like panel with matching symbols for tests 2 & 11
    return C.make_fake_ohlcv(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED)


@pytest.fixture(scope="module")
def persistent_signal(latz):
    return latz.copy()


@pytest.fixture(scope="module")
def leaky_signal(_panel):
    _, labs, _ = _panel
    return labs.pivot_table(index="date", columns="symbol", values="fwd_ret_1")


@pytest.fixture(scope="module")
def noise_signal(latz):
    rng = np.random.default_rng(SEED + 5)
    return pd.DataFrame(rng.standard_normal(latz.shape), index=latz.index,
                        columns=latz.columns)


def _fresh_ledger():
    return Ledger(":memory:")


# --------------------------------------------------------------------------- #
# 1 — all eleven run and return the documented shape                           #
# --------------------------------------------------------------------------- #
def test_all_eleven_run_and_return_shape(persistent_signal, prices, latz):
    panel = {"close": latz, "volume": latz.abs() + 1.0, "delivery_pct": latz}
    out = RT.run_redteam(
        persistent_signal, tests=list(RT.REDTEAM_MENU), split=SPLIT, horizon=1,
        formula="delivery_pct", panel=panel, prices=prices, ledger=_fresh_ledger(),
        thesis_id="th_p9", formula_hash="h", canonical_ast="delivery_pct",
    )
    assert set(out["results"]) == set(RT.REDTEAM_MENU)
    for name, r in out["results"].items():
        assert "flag" in r, (name, r)
    assert out["verdict"] in ("survives", "killed")
    assert out["counts_as_trial"] == 0
    assert set(out["failed_tests"]).issubset(set(RT.DECISIVE_TESTS))
    assert isinstance(out["n_backtests"], int) and out["n_backtests"] > 10


# --------------------------------------------------------------------------- #
# 5 — every red-team backtest is recorded with counts_as_trial = 0             #
# --------------------------------------------------------------------------- #
def test_every_backtest_is_recorded_as_non_trial(persistent_signal, prices):
    lg = _fresh_ledger()
    out = RT.run_redteam(persistent_signal, split=SPLIT, horizon=1, prices=prices,
                         ledger=lg, thesis_id="th_x")
    rows = lg.trial_records(counts_only=False)
    assert len(rows) == out["n_backtests"] > 0
    assert all(r["counts_as_trial"] == 0 for r in rows)
    assert all(str(r["rejection_reason"]).startswith("redteam:") for r in rows)
    assert lg.n_trials() == 0                    # nothing counted toward the DSR


# --------------------------------------------------------------------------- #
# 2 — a deliberately leaky signal is killed by test 5 (extra_lag)              #
# --------------------------------------------------------------------------- #
def test_leaky_signal_killed_by_extra_lag(leaky_signal, prices):
    out = RT.run_redteam(leaky_signal, split=SPLIT, horizon=1, prices=prices,
                         ledger=_fresh_ledger())
    assert out["results"]["extra_lag"]["flag"] is True
    assert "extra_lag" in out["failed_tests"]
    assert out["verdict"] == "killed"
    # baseline RankIC of fwd_ret_1 vs itself is ~1; lagged is near 0
    assert out["results"]["extra_lag"]["base_rank_ic"] > 0.9
    assert out["results"]["extra_lag"]["rank_ic_lagged"] < 0.3


# --------------------------------------------------------------------------- #
# 3 — a signal that works in only one year is killed by test 1                 #
# --------------------------------------------------------------------------- #
def test_one_year_signal_killed_by_subsample_year(persistent_signal, noise_signal, prices):
    good_year = 2019
    sig = noise_signal.copy()
    yr = sig.index.year
    sig.loc[yr == good_year] = persistent_signal.loc[yr == good_year]
    out = RT.run_redteam(sig, split=SPLIT, horizon=1, prices=prices,
                         ledger=_fresh_ledger())
    r = out["results"]["subsample_year"]
    assert r["flag"] is True, r
    assert "subsample_year" in out["failed_tests"]
    assert out["verdict"] == "killed"
    assert r["dropped_year"] == good_year


# --------------------------------------------------------------------------- #
# 4 — a high-turnover, thin-gross-edge signal is killed by test 4              #
# --------------------------------------------------------------------------- #
def test_high_turnover_thin_edge_killed_by_cost_sweep(persistent_signal, noise_signal, prices):
    rng = np.random.default_rng(SEED + 9)
    churn = pd.DataFrame(rng.standard_normal(persistent_signal.shape),
                         index=persistent_signal.index, columns=persistent_signal.columns)
    thin = 0.05 * persistent_signal + churn        # tiny edge, reshuffles daily
    out = RT.run_redteam(thin, split=SPLIT, horizon=1, prices=prices,
                         ledger=_fresh_ledger())
    r = out["results"]["cost_sweep"]
    assert r["flag"] is True, r
    assert "cost_sweep" in out["failed_tests"]
    assert r["net_sharpe_15bps"] <= 0 or r["net_sharpe_15bps"] < 0.5 * r["gross_sharpe"]


# --------------------------------------------------------------------------- #
# 6 — test 11 reads P1's liquidity ranking, never a hard-coded symbol list      #
# --------------------------------------------------------------------------- #
def _fixture_liquidity_ranks(prices):
    """A P1-shaped ``month_end · symbol · liquidity_rank · trailing_turnover``
    frame built from the fixture price panel (same rule P1 uses)."""
    from src import universe as U

    sel = U.compute_selection(prices)
    return U.build_liquidity_ranks(sel)


def test_universe_edge_reads_the_liquidity_rank_file(persistent_signal, prices):
    import re
    with open(RT.__file__, encoding="utf-8") as fh:
        code = re.sub(r'"""(.*?)"""', "",
                      "\n".join(ln for ln in fh.read().splitlines()
                                if not ln.lstrip().startswith("#")), flags=re.S)
    tickers = re.findall(r"['\"][A-Z]{3,}[A-Z0-9&.\-]*['\"]", code)
    assert tickers == [], f"hard-coded ticker-like literals in redteam.py: {tickers}"

    ranks = _fixture_liquidity_ranks(prices)
    assert list(ranks.columns) == ["month_end", "symbol", "liquidity_rank",
                                   "trailing_turnover"]
    out = RT.run_redteam(persistent_signal, tests=["universe_edge"], split=SPLIT,
                         horizon=1, liquidity_ranks=ranks, ledger=_fresh_ledger())
    r = out["results"]["universe_edge"]
    assert r["ran"] is True
    assert r["n_fringe_names"] > 0
    assert "liquidity_ranks.parquet" in r["fringe_source"]


def test_universe_edge_falls_back_to_recomputing_when_no_rank_file(persistent_signal, prices):
    """With no matching rank frame, the fringe is recomputed from the price panel
    via the same trailing-turnover rule."""
    out = RT.run_redteam(persistent_signal, tests=["universe_edge"], split=SPLIT,
                         horizon=1, prices=prices, ledger=_fresh_ledger())
    r = out["results"]["universe_edge"]
    assert r["ran"] is True
    assert r["n_fringe_names"] > 0
    assert "compute_selection" in r["fringe_source"]


# --------------------------------------------------------------------------- #
# 7 — regime labels (test 2) use expanding-window thresholds only              #
#     The look-ahead was fixed at P4 source; the red-team just consumes it.    #
# --------------------------------------------------------------------------- #
def test_regime_labels_are_expanding_only(_panel):
    _, labs, _ = _panel
    full = bt._regime_labels(labs)
    assert full["bull"].sum() > 20 and full["bear"].sum() > 20   # cycle populates them
    assert full["highvol"].sum() > 20

    months = np.sort(labs["date"].unique())
    cut = months[: int(len(months) * 0.55)]
    trunc = bt._regime_labels(labs[labs["date"].isin(cut)])
    # truncating the future must not move a single past regime label
    assert full.loc[trunc.index].equals(trunc)


def test_full_sample_threshold_would_be_detectable():
    """A full-sample volatility quantile *does* flip early labels when the future
    is truncated — proof the invariance check above is not vacuous."""
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2015-01-01", periods=400)
    mkt = pd.Series(np.r_[rng.normal(0, 0.004, 250), rng.normal(0, 0.02, 150)],
                    index=idx)

    def _leaky(m):
        v = m.rolling(21, min_periods=15).std()
        thr = v.quantile(2.0 / 3.0)                    # FULL-sample: look-ahead
        return (v >= thr).rename("highvol")

    a = _leaky(mkt)
    b = _leaky(mkt.iloc[:250])
    assert not a.loc[b.index].equals(b)


# --------------------------------------------------------------------------- #
# survive/kill rule — the clean persistent signal survives everything          #
# --------------------------------------------------------------------------- #
def test_clean_persistent_signal_survives(persistent_signal, prices):
    out = RT.run_redteam(persistent_signal, split=SPLIT, horizon=1, prices=prices,
                         ledger=_fresh_ledger())
    assert out["verdict"] == "survives", (out["failed_tests"], out["results"])
    assert out["failed_tests"] == []
    b = out["baseline"]
    assert b["rank_ic"] > 0 and abs(b["t_stat"]) >= RT.RT_SIG_T


def test_sign_flipping_signal_killed_by_sign_stability(persistent_signal, prices):
    sig = persistent_signal.copy()
    flip = np.where(sig.index.year % 2 == 0, 1.0, -1.0)
    sig = sig.mul(flip, axis=0)
    out = RT.run_redteam(sig, split=SPLIT, horizon=1, prices=prices,
                         ledger=_fresh_ledger())
    r = out["results"]["sign_stability"]
    assert r["flag"] is True, r
    assert "sign_stability" in out["failed_tests"]
    assert r["consistency"] < RT.SIGN_CONSISTENCY_MIN


def test_delivery_lag_collapses_a_delivery_pct_signal(prices):
    """Test 6: on an IID panel whose edge lives entirely in the current day's
    ``delivery_pct``, shifting ONLY that field by a day collapses the RankIC —
    the mechanic that lets the red-team name the culprit field."""
    feats = C.make_fake_features(n_days=900, n_symbols=N_SYMBOLS, seed=7)
    labs = C.make_fake_labels(n_days=900, n_symbols=N_SYMBOLS, seed=7)
    # plant the (IID) predictive latent into delivery_pct
    planted = feats.pivot_table(index="date", columns="symbol", values="mom_21")
    feats = feats.merge(
        planted.stack(future_stack=True).rename_axis(["date", "symbol"])
        .rename("delivery_pct").reset_index(), on=["date", "symbol"],
        suffixes=("", "_new"))
    feats["delivery_pct"] = feats.pop("delivery_pct_new").astype(np.float64)
    feats["date"] = feats["date"].astype("datetime64[ns]")
    bt.clear_panel()
    bt.use_panel(feats, labs)
    try:
        panel = {"delivery_pct": planted,
                 "close": planted.abs() + 1.0, "volume": planted.abs() + 1.0}
        out = RT.run_redteam(planted, tests=["delivery_lag"], split=SPLIT, horizon=1,
                             formula="delivery_pct", panel=panel, prices=prices,
                             ledger=_fresh_ledger())
    finally:
        bt.clear_panel()
        f, la, _ = _persistent_panel()
        bt.use_panel(f, la)
    d = out["results"]["delivery_lag"]
    assert d["ran"] is True
    assert d["base_rank_ic"] > 0.02
    assert d["flag"] is True
    assert d["rank_ic_delivery_lagged"] < 0.5 * d["base_rank_ic"]


def test_horizon_defaults_from_thesis(persistent_signal, prices):
    out = RT.run_redteam(persistent_signal, tests=["decay_curve"], split=SPLIT,
                         thesis={"horizon_days": 5}, prices=prices,
                         ledger=_fresh_ledger())
    assert out["results"]["decay_curve"]["claimed_horizon"] == 5


def test_decisive_tests_are_always_run_even_if_not_selected(persistent_signal, prices):
    out = RT.run_redteam(persistent_signal, tests=["sector_neutral"], split=SPLIT,
                         horizon=1, prices=prices, ledger=_fresh_ledger())
    for t in RT.DECISIVE_TESTS:
        assert t in out["tests_run"]
    assert set(out["forced_decisive_tests"]) == set(RT.DECISIVE_TESTS)


def test_run_is_deterministic(persistent_signal, prices):
    kw = dict(split=SPLIT, horizon=1, prices=prices)
    a = RT.run_redteam(persistent_signal, ledger=_fresh_ledger(), **kw)
    b = RT.run_redteam(persistent_signal, ledger=_fresh_ledger(), **kw)
    assert a["results"]["extra_lag"] == b["results"]["extra_lag"]
    assert a["baseline"] == b["baseline"]
    assert a["verdict"] == b["verdict"]
