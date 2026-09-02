"""Phase 2 acceptance tests — plain pytest, no network.

Logic tests always run (parsers, ratio parsing, adjustment math, the size_proxy
leak test). The data tests read the produced artifacts and skip if Phase 2 has
not been run yet — mirroring the P1 pattern.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import contracts as C
from src import prices as P


# --------------------------------------------------------------------------- #
# Logic — always run                                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("subject,kind,ratio", [
    (" Bonus 1:1", "bonus", 0.5),
    ("Bonus 2:1", "bonus", 1 / 3),
    ("Bonus 3:1", "bonus", 0.25),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 5/- Per Share",
     "split", 0.5),
    ("Face Value Split From Rs10/- Per Share To Re 1/- Per Share", "split", 0.1),
    ("Bonus 1:1 / Face Value Split From Rs 10/- Per Share To Rs 2/- Per Share",
     "bonus+split", 0.5 * 0.2),
    # NSE's abbreviated subject text — the verbose-only parser missed these
    # (P3 handoff §5.1: JSWSTEEL 10:1, INFIBEAM, WELSPUNIND, CADILAHC, …).
    ("Fv Splt Frm Rs 10 To Re 1", "split", 0.1),
    ("Fv Splt Frm Rs 10 To Rs 2", "split", 0.2),
    ("Fv Splt Frm Rs 10 To Rs 5", "split", 0.5),
    ("Face Value Split Rs.10/- To Re.1/- Per Share", "split", 0.1),
    ("Bonus- 1:2", "bonus", 2 / 3),
    ("Rights 2:1 @ Premium Rs 2/-", "other", None),        # rights must NOT parse as bonus
    ("Scheme of Arrangement (Demerger)", "demerger", None),
    (" Interim Dividend Re 0.70 Per Share", "dividend", None),
    (" Buyback", "other", None),
])
def test_parse_ca_subject(subject, kind, ratio):
    k, r = P.parse_ca_subject(subject)
    assert k == kind
    if ratio is None:
        assert r is None
    else:
        assert r == pytest.approx(ratio, rel=1e-6)


def test_apply_adjustment_math():
    dates = pd.bdate_range("2020-01-01", periods=10)
    panel = pd.DataFrame({
        "isin": "INTEST000001", "symbol": "T", "date": dates,
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "vwap": 100.0, "volume_raw": 1000.0,
    })
    ex = dates[5]
    ca = pd.DataFrame([{"isin": "INTEST000001", "symbol": "T", "ex_date": ex,
                        "type": "split", "ratio": 0.5, "raw_subject": "x"}])
    out = P.apply_adjustment(panel, ca, P.Report()).sort_values("date")
    pre, post = out[out["date"] < ex], out[out["date"] >= ex]
    assert np.allclose(pre["close_adj"], 50.0)
    assert np.allclose(post["close_adj"], 100.0)
    assert np.allclose(pre["volume_adj"], 2000.0)      # volume scales inversely
    assert np.allclose(post["volume_adj"], 1000.0)
    assert np.allclose(out["low_adj"] <= out["vwap_adj"], True)


def test_size_proxy_is_trailing_only():
    """Recomputing size_proxy on a panel truncated in the future must not change
    any value on the overlapping (earlier) dates — the leak test."""
    ohlcv = C.make_fake_ohlcv(n_days=400, n_symbols=15)
    ohlcv = ohlcv.rename(columns={})  # already has close_raw/volume_raw
    full = P.build_size_proxy(ohlcv, P.Report())
    cut_date = ohlcv["date"].sort_values().unique()[300]
    trunc = ohlcv[ohlcv["date"] <= cut_date].copy()
    part = P.build_size_proxy(trunc, P.Report())
    merged = full.merge(part, on=["date", "symbol"], suffixes=("_full", "_part"))
    assert len(merged) > 0
    assert np.allclose(merged["size_proxy_full"], merged["size_proxy_part"], equal_nan=True)


def test_fixture_ohlcv_has_series_and_validates():
    df = C.make_fake_ohlcv(n_days=300, n_symbols=20)
    C.validate_ohlcv(df)
    assert "series" in df.columns
    assert set(df["series"].unique()) <= C.OHLCV_SERIES_ALLOWED


def test_validate_ohlcv_rejects_bad_series():
    df = C.make_fake_ohlcv(n_days=120, n_symbols=8)
    df.loc[0, "series"] = "N1"
    with pytest.raises(C.SchemaError, match="series"):
        C.validate_ohlcv(df)


# --------------------------------------------------------------------------- #
# Data — skip until Phase 2 has produced the artifacts                         #
# --------------------------------------------------------------------------- #
_have = P.OHLCV_PARQUET.exists()
data = pytest.mark.skipif(not _have, reason="Phase 2 has not produced ohlcv.parquet yet")


@pytest.fixture(scope="module")
def ohlcv():
    return pd.read_parquet(P.OHLCV_PARQUET)


@data
def test_real_ohlcv_validates(ohlcv):
    C.validate_ohlcv(ohlcv)


@data
def test_no_bad_prices(ohlcv):
    assert (ohlcv["close"] > 0).all()
    assert (ohlcv["high"] >= ohlcv["low"]).all()
    assert (ohlcv["volume_raw"] >= 0).all()
    assert (ohlcv["volume"] >= 0).all()


@data
def test_series_choice(ohlcv):
    vals = set(ohlcv["series"].unique())
    assert vals <= {"EQ", "BE"}
    assert "EQ" in vals


@data
@pytest.mark.parametrize("sym,trading_date", [
    ("DHFL", "2018-03-15"),
    ("RCOM", "2018-03-15"),
    ("JPASSOCIAT", "2018-03-15"),
    ("YESBANK", "2018-03-15"),
    ("SUZLON", "2018-03-15"),
    ("IDEA", "2018-03-15"),
])
def test_canary_present_while_trading(ohlcv, sym, trading_date):
    g = ohlcv[ohlcv["symbol"] == sym]
    assert len(g) > 0, f"{sym} entirely missing from panel"
    d = pd.Timestamp(trading_date)
    near = g[(g["date"] >= d - pd.Timedelta(days=7)) & (g["date"] <= d + pd.Timedelta(days=7))]
    assert len(near) > 0, f"{sym} absent around {trading_date} while it was trading"


@data
def test_canary_absent_after_death(ohlcv):
    # DHFL delisted mid-2021; must not appear in 2023+
    dhfl = ohlcv[ohlcv["symbol"] == "DHFL"]
    assert (dhfl["date"] < pd.Timestamp("2022-06-01")).all(), "DHFL trades after delisting?"
    # CAIRN merged into Vedanta April 2017
    cairn = ohlcv[ohlcv["symbol"] == "CAIRN"]
    if len(cairn):
        assert (cairn["date"] < pd.Timestamp("2017-06-01")).all()


@data
def test_flat_coverage_not_sloping(ohlcv):
    fc = P.flat_coverage_stats(ohlcv)
    assert fc["mean_2016"] >= 185, f"2016 coverage {fc['mean_2016']:.0f} < 185"
    assert fc["mean_2024"] >= 185, f"2024 coverage {fc['mean_2024']:.0f} < 185"
    # near-zero slope: less than ~2 symbols/year drift over a ~200 panel
    assert abs(fc["slope_per_year"]) < 3.0, f"coverage slope {fc['slope_per_year']:+.2f}/yr"


@data
def test_union_symbol_recovery(ohlcv):
    assert ohlcv["symbol"].nunique() >= 300


@data
def test_heavyweights_liquid(ohlcv):
    for s in ["RELIANCE", "TCS", "SBIN", "INFY"]:
        assert (ohlcv["symbol"] == s).sum() > 1000, f"{s} thin — turnover bug?"


@data
def test_isin_continuity_on_rename(ohlcv):
    """CMC was renamed; TCS is continuous. A rename must not split one ISIN."""
    for sym in ["TCS", "RELIANCE"]:
        isins = ohlcv.loc[ohlcv["symbol"] == sym, "isin"].nunique()
        assert isins == 1, f"{sym} has {isins} ISINs"


@data
def test_size_proxy_artifact_and_leak():
    sp = pd.read_parquet(P.SIZE_PROXY_PARQUET)
    assert {"date", "symbol", "size_proxy"} <= set(sp.columns)
    assert sp["size_proxy"].notna().all()
    # leak test on a real slice
    ohlcv = pd.read_parquet(P.OHLCV_PARQUET)
    sub = ohlcv[ohlcv["symbol"].isin(sorted(ohlcv["symbol"].unique())[:20])]
    cut = sub["date"].sort_values().unique()[-200]
    full = P.build_size_proxy(sub, P.Report())
    part = P.build_size_proxy(sub[sub["date"] <= cut], P.Report())
    m = full.merge(part, on=["date", "symbol"], suffixes=("_f", "_p"))
    assert np.allclose(m["size_proxy_f"], m["size_proxy_p"])


@data
def test_delivery_artifact():
    d = pd.read_parquet(P.DELIVERY_PARQUET)
    assert {"date", "symbol", "deliv_qty", "delivery_pct"} <= set(d.columns)
    ok = d["delivery_pct"].dropna()
    assert (ok >= 0).all() and (ok <= 100).all()
    assert d["date"].min() >= pd.Timestamp("2019-09-01")


@data
def test_corporate_actions_artifact():
    ca = pd.read_parquet(P.CORP_ACTIONS_PARQUET)
    assert {"isin", "ex_date", "type", "ratio", "raw_subject"} <= set(ca.columns)
    adj = ca[ca["ratio"].notna()]
    assert (adj["ratio"] > 0).all() and (adj["ratio"] <= 1).all()


@data
def test_extreme_returns_explained_or_listed(ohlcv):
    ca = pd.read_parquet(P.CORP_ACTIONS_PARQUET)
    ex = P.extreme_returns(ohlcv, ca, P.Report())
    # not asserting zero — Indian midcaps move; just that the frame is produced
    # and every row is either explained or explicitly listed.
    assert set(ex.columns) >= {"date", "symbol", "ret", "near_corp_action"}
