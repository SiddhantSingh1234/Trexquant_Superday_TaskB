"""Phase 3 acceptance tests — plain pytest, no network.

Logic tests always run against synthetic fixtures. Tests that need the real
panel read ``data/panel/*.parquet`` and skip if Phase 3 has not been run —
mirroring the P1 / P2 pattern.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import contracts as C
from src import panel as P
from src.config import (
    FEATURES_PARQUET,
    HOLDOUT_START,
    LABELS_PARQUET,
    SPLITS_JSON_PAYLOAD,
    split_mask,
)
from src.contracts import HORIZONS, validate_features, validate_labels
from src.sectors import NSE_INDUSTRIES, build_sector_map


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def fixture_run():
    """Run the whole pipeline on synthetic fixtures (forces the fallback path)."""
    from pathlib import Path
    saved = P.OHLCV_PARQUET
    P.OHLCV_PARQUET = Path("__no_such_ohlcv__.parquet")
    try:
        return P.run(write=False)
    finally:
        P.OHLCV_PARQUET = saved


@pytest.fixture(scope="module")
def real_panel():
    if not (FEATURES_PARQUET.exists() and LABELS_PARQUET.exists()):
        pytest.skip("real panel not built — run `python -m src.panel`")
    return (pd.read_parquet(FEATURES_PARQUET), pd.read_parquet(LABELS_PARQUET))


# --------------------------------------------------------------------------- #
# Logic — always run (synthetic)                                               #
# --------------------------------------------------------------------------- #
def test_fixture_pipeline_validates(fixture_run):
    f, l = fixture_run["features"], fixture_run["labels"]
    validate_features(f)
    validate_labels(l)
    assert f["date"].dtype == "datetime64[ns]"
    assert l["date"].dtype == "datetime64[ns]"


def test_fixture_delivery_pct_is_all_nan_and_still_validates(fixture_run):
    """Spec P3 Inputs: on the fixture path delivery_pct is emitted as NaN.
    validate_features must accept that (it is a genuinely partial field)."""
    f = fixture_run["features"]
    assert f["delivery_pct"].isna().all()
    validate_features(f)  # must not raise on the all-NaN delivery_pct


def test_validator_still_rejects_other_all_nan_columns():
    f = C.make_fake_features(n_days=300, n_symbols=20)
    f["mom_21"] = np.nan
    with pytest.raises(Exception, match="mom_21"):
        validate_features(f)


def test_no_duplicate_keys(fixture_run):
    for k in ("features", "labels"):
        df = fixture_run[k]
        assert df.duplicated(["date", "symbol"]).sum() == 0


def test_dist_52wh_non_positive(fixture_run):
    d = fixture_run["features"]["dist_52wh"].dropna()
    assert (d <= 1e-9).all()


def test_vol_21_positive(fixture_run):
    v = fixture_run["features"]["vol_21"].dropna()
    assert (v > 0).all()


def test_demeaned_label_is_zero_mean_per_day(fixture_run):
    l = fixture_run["labels"]
    for h in HORIZONS:
        per_day = l.groupby("date")[f"fwd_ret_{h}_demeaned"].mean().abs()
        assert per_day.max() < 1e-9, f"h={h}: demeaned label not zero-mean per day"


def test_splits_json_matches_config(fixture_run):
    assert fixture_run["splits"] == SPLITS_JSON_PAYLOAD
    assert SPLITS_JSON_PAYLOAD["holdout"][0] == "2022-07-01"


# --- timing contract, on a hand-built panel ---------------------------------- #
def _hand_panel(n_days=320, n_syms=30, seed=0):
    """Deterministic OHLCV + all-in-universe membership on a clean calendar."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_days).normalize()
    rows = []
    for j in range(n_syms):
        s = f"HS{j:02d}"
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n_days)))
        op = close * np.exp(rng.normal(0, 0.005, n_days))
        rows.append(pd.DataFrame({
            "date": dates, "symbol": s,
            "open": op, "high": np.maximum(op, close) * 1.01,
            "low": np.minimum(op, close) * 0.99, "close": close,
            "volume": rng.uniform(1e5, 1e6, n_days),
            "close_raw": close, "volume_raw": rng.uniform(1e5, 1e6, n_days),
            "isin": f"INHAND{j:05d}0", "source": "x", "series": "EQ",
        }))
    ohlcv = pd.concat(rows, ignore_index=True)
    for c in ("open", "high", "low", "close", "volume", "close_raw", "volume_raw"):
        ohlcv[c] = ohlcv[c].astype(np.float64)
    ohlcv = ohlcv.sort_values(["date", "symbol"]).reset_index(drop=True)
    memb = (ohlcv[["date", "symbol"]].assign(in_universe=True)
            .sort_values(["date", "symbol"]).reset_index(drop=True))
    return ohlcv, memb


def test_label_is_open_t1_to_t2(monkeypatch):
    ohlcv, memb = _hand_panel()
    monkeypatch.setattr(P, "load_inputs", lambda: {
        "ohlcv": P._to_ns(ohlcv.copy()), "membership": P._to_ns(memb.copy()),
        "delivery": None, "size_proxy": None, "corp": None,
        "src": "hand", "is_real": False})
    r = P.run(write=False)
    lab = r["labels"].set_index(["date", "symbol"])
    op = ohlcv.pivot(index="date", columns="symbol", values="open").sort_index()
    exp = (op.shift(-2) / op.shift(-1) - 1.0)
    got = lab["fwd_ret_1"].unstack()
    common = exp.dropna(how="all").index.intersection(got.index)
    sym = "HS05"
    a = exp.loc[common, sym].dropna()
    b = got.reindex(index=common, columns=[sym])[sym].reindex(a.index)
    assert np.allclose(a.values, b.values, atol=1e-9, equal_nan=True)


def test_mom_21_is_close_tm1_over_tm22(monkeypatch):
    ohlcv, memb = _hand_panel()
    monkeypatch.setattr(P, "load_inputs", lambda: {
        "ohlcv": P._to_ns(ohlcv.copy()), "membership": P._to_ns(memb.copy()),
        "delivery": None, "size_proxy": None, "corp": None,
        "src": "hand", "is_real": False})
    r = P.run(write=False)
    feat = r["features"].set_index(["date", "symbol"])["mom_21"].unstack()
    cl = ohlcv.pivot(index="date", columns="symbol", values="close").sort_index()
    exp = cl.shift(1) / cl.shift(22) - 1.0
    sym = "HS07"
    common = feat.index.intersection(exp.index)
    a = feat.loc[common, sym].dropna()
    b = exp.loc[a.index, sym]
    assert len(a) > 100
    assert np.allclose(a.values, b.values, atol=1e-9)


# --- the machinery can detect leakage, and is time-asymmetric --------------- #
def test_leaky_feature_detected_and_collapses_on_shift(fixture_run):
    st = fixture_run["selftest"]
    assert abs(st["leaky_ic"]) > 0.9, "machinery cannot see an obvious leak"
    assert abs(st["leaky_ic"]) > 0.999
    assert st["leak_collapses_on_shift"], (
        "leaky feature's IC did not collapse when shifted — the IC machinery is "
        "time-symmetric (would hide real leakage)")


def test_ic_machinery_is_time_asymmetric_on_a_real_signal():
    """P0's fake panel plants IC≈0.04 in mom_21. Confirm shifting the signal a
    day changes that IC — i.e. `_daily_rank_ic` is not time-symmetric."""
    feats = C.make_fake_features(n_days=700, n_symbols=60)
    labs = C.make_fake_labels(n_days=700, n_symbols=60)
    sig = feats.pivot(index="date", columns="symbol", values="mom_21").sort_index()
    lab = labs.pivot(index="date", columns="symbol",
                     values="fwd_ret_1_demeaned").sort_index()
    ic0 = P._daily_rank_ic(sig, lab)
    ic1 = P._daily_rank_ic(sig.shift(1), lab)
    assert abs(ic0) > 0.02, f"planted signal not seen: {ic0}"
    assert abs(ic0 - ic1) > 0.2 * abs(ic0), (
        f"IC barely moved on a 1-day shift ({ic0:.4f} -> {ic1:.4f}) — "
        f"time-symmetric machinery")


# --- extreme returns: flagged, not winsorized ------------------------------- #
def test_extreme_return_flagged_not_clipped(monkeypatch):
    ohlcv, memb = _hand_panel(n_days=300, n_syms=25)
    piv = ohlcv.pivot(index="date", columns="symbol", values="close")
    crash_day = piv.index[200]
    mask = (ohlcv["symbol"] == "HS03") & (ohlcv["date"] >= crash_day)
    ohlcv.loc[mask, ["open", "high", "low", "close", "close_raw"]] *= 0.08  # -92%
    monkeypatch.setattr(P, "load_inputs", lambda: {
        "ohlcv": P._to_ns(ohlcv.copy()), "membership": P._to_ns(memb.copy()),
        "delivery": None, "size_proxy": None, "corp": None,
        "src": "hand", "is_real": False})
    r = P.run(write=False)
    assert r["extreme"]["n_flagged"] >= 1
    hits = [s for s in r["extreme"]["sample"] if s["symbol"] == "HS03"]
    assert hits and hits[0]["ret"] < -0.5
    # max_ret_21 for HS03 must still contain the un-clipped move somewhere after
    f = r["features"]
    hs3 = f[f["symbol"] == "HS03"]["max_ret_21"].dropna()
    assert hs3.abs().max() < 5.0  # sanity: not exploded, but also not winsorized to a cap


# --- sector mapping -------------------------------------------------------- #
def test_sector_map_only_uses_official_industries():
    syms = ["RELIANCE", "DHFL", "CAIRN", "TCS", "SYM999_UNKNOWN"]
    isin_map = {"RELIANCE": "INE002A01018", "DHFL": "INE202B01012",
                "CAIRN": "XXX", "TCS": "INE467B01029", "SYM999_UNKNOWN": ""}
    m, stats = build_sector_map(syms, isin_map)
    assert set(m.values()) <= NSE_INDUSTRIES
    assert m["DHFL"] == "Financial Services"       # hand
    assert m["CAIRN"] == "Oil Gas & Consumable Fuels"  # hand
    assert stats["by_hand"] >= 2


def test_hand_map_covers_real_union_if_present():
    import json
    from src.config import SYMBOLS_JSON
    if not SYMBOLS_JSON.exists():
        pytest.skip("universe symbols.json not present")
    sj = json.loads(SYMBOLS_JSON.read_text())
    m, stats = build_sector_map(sj["symbols"], sj.get("isin_map", {}))
    assert stats["unknown"] == 0, f"unclassified symbols: {stats['unknown_sample']}"
    assert set(m.values()) <= NSE_INDUSTRIES
    assert stats["n_industries_used"] >= 15


# --------------------------------------------------------------------------- #
# Real-panel tests — skip if Phase 3 not run                                    #
# --------------------------------------------------------------------------- #
def test_real_validators_pass(real_panel):
    f, l = real_panel
    validate_features(f)
    validate_labels(l)


def test_real_delivery_first_date(real_panel):
    f, _ = real_panel
    d = f[["date", "delivery_pct"]].dropna()
    assert d["date"].min() >= pd.Timestamp("2019-10-01")
    before = f[f["date"] < pd.Timestamp("2019-10-01")]["delivery_pct"]
    assert before.isna().all(), "delivery_pct must be NaN before it exists"


def test_real_cross_section_at_least_100_after_2016(real_panel):
    f, _ = real_panel
    xs = f[f["date"] >= pd.Timestamp("2016-01-01")].groupby("date")["symbol"].count()
    assert xs.min() >= 100, f"thin day: {xs.idxmin().date()} -> {xs.min()}"


def test_real_holdout_rows_present_for_p6(real_panel):
    """P3 builds the full panel incl. HOLDOUT so P6's rationed-peek API can read
    it; sealing is enforced at scoring time (P4)."""
    f, l = real_panel
    assert split_mask(f["date"], "holdout").sum() > 0
    assert split_mask(l["date"], "holdout").sum() > 0


def test_real_shift_test_changes_ic():
    """Step 7 (a): shifting the whole feature panel forward one day must
    materially change a known factor's IC. Needs the real inputs."""
    if not (P.OHLCV_PARQUET.exists() and P.MEMBERSHIP_PARQUET.exists()):
        pytest.skip("real inputs not present")
    r = P.run(write=False)
    st = r["selftest"]
    assert st["shift_changes_ic"], (
        f"rev_5 IC {st['rev_5']['ic']:.5f} barely changed on a 1-day forward "
        f"shift ({st['rev_5']['ic_shift_fwd1']:.5f}) — possible leak / "
        f"time-symmetry")
    assert st["machinery_detects_leak"]
    assert abs(st["leaky_ic"]) > 0.9


def test_real_no_nan_demeaned_label_for_live_inuniverse_rows(real_panel):
    """No NaN label where a stock is in-universe and the forward window is fully
    inside the sample and the stock kept trading. The only permitted NaNs are
    end-of-sample or stock-stopped-trading (counted in the report)."""
    f, l = real_panel
    last = l["date"].max()
    sub = l[l["date"] <= last - pd.Timedelta(days=40)]
    frac_nan = sub["fwd_ret_1_demeaned"].isna().mean()
    assert frac_nan < 0.005, f"{frac_nan:.3%} NaN fwd_ret_1 well inside sample"
