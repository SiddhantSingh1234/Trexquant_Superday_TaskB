"""Phase 0 acceptance tests — contracts + fixtures. Plain pytest, no network."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import config
from src import contracts as C


# --------------------------------------------------------------------------- #
# config.py                                                                    #
# --------------------------------------------------------------------------- #
def test_constants():
    assert config.MAX_VARIANTS_PER_THESIS == 20
    assert config.HOLDOUT_PEEK_BUDGET == 12
    assert config.T_STAT_BAR == 3.0
    assert config.COST_BPS_DEFAULT == 15
    assert config.EMBARGO_DAYS == 5
    assert config.RANDOM_SEED == 42


def test_split_dates_match_section_0_4():
    assert config.SPLITS["train"][0] == pd.Timestamp("2015-01-01")
    assert config.SPLITS["val_a"] == (pd.Timestamp("2018-01-01"), pd.Timestamp("2021-06-30"))
    assert config.SPLITS["val_b"] == (pd.Timestamp("2021-07-01"), pd.Timestamp("2022-06-30"))
    assert config.SPLITS["holdout"][0] == pd.Timestamp("2022-07-01")


def test_split_mask_regions():
    dates = pd.to_datetime([
        "2014-06-01", "2016-06-01", "2019-06-01", "2021-12-01", "2023-06-01",
    ])
    assert config.split_mask(dates, "warmup").tolist() == [True, False, False, False, False]
    assert config.split_mask(dates, "train").tolist() == [False, True, False, False, False]
    assert config.split_mask(dates, "val_a").tolist() == [False, False, True, False, False]
    assert config.split_mask(dates, "val_b").tolist() == [False, False, False, True, False]
    assert config.split_mask(dates, "holdout").tolist() == [False, False, False, False, True]
    assert config.split_mask(dates, "train+val_a").tolist() == [False, True, True, False, False]


def test_split_mask_boundaries_inclusive():
    edges = pd.to_datetime(["2017-12-31", "2018-01-01", "2021-06-30", "2022-06-30"])
    assert config.split_mask(edges, "train").tolist() == [True, False, False, False]
    assert config.split_mask(edges, "val_a").tolist() == [False, True, True, False]
    assert config.split_mask(edges, "val_b").tolist() == [False, False, False, True]


def test_split_mask_unknown_region():
    with pytest.raises(ValueError):
        config.split_mask(pd.to_datetime(["2019-01-01"]), "nope")


def test_assert_not_holdout():
    config.assert_not_holdout(pd.to_datetime(["2019-01-01"]))          # passes
    with pytest.raises(AssertionError):
        config.assert_not_holdout(pd.to_datetime(["2023-01-01"]))
    with pytest.raises(AssertionError):
        config.assert_not_holdout(pd.to_datetime(["2019-01-01", "2023-01-01"]))


# --------------------------------------------------------------------------- #
# fixtures pass their own validators                                           #
# --------------------------------------------------------------------------- #
def test_fixtures_validate():
    C.validate_ohlcv(C.make_fake_ohlcv())
    C.validate_membership(C.make_fake_membership())
    C.validate_features(C.make_fake_features())
    C.validate_labels(C.make_fake_labels())
    C.validate_symbols_json(C.make_fake_symbols())


def test_fixtures_deterministic():
    assert C.make_fake_ohlcv().equals(C.make_fake_ohlcv())
    assert C.make_fake_features().equals(C.make_fake_features())
    assert C.make_fake_labels().equals(C.make_fake_labels())
    assert C.make_fake_membership().equals(C.make_fake_membership())


def test_ohlcv_has_delisted_symbols():
    """A few symbols must stop trading partway (survivorship bite)."""
    df = C.make_fake_ohlcv(n_days=600, n_symbols=40)
    last = df.groupby("symbol")["date"].max()
    overall_last = df["date"].max()
    assert (last < overall_last).sum() >= 1


def test_ohlcv_vol_in_ballpark():
    df = C.make_fake_ohlcv(n_days=750, n_symbols=30)
    df = df.sort_values(["symbol", "date"])
    rets = df.groupby("symbol")["close"].pct_change()
    ann_vol = rets.std() * np.sqrt(252)
    assert 0.15 < ann_vol < 0.40


def test_planted_ic_is_detectable():
    """mom_21 vs fwd_ret_1_demeaned has mean-daily RankIC ~= PLANTED_IC."""
    feats = C.make_fake_features(n_days=800, n_symbols=60)
    labs = C.make_fake_labels(n_days=800, n_symbols=60)
    m = feats[["date", "symbol", "mom_21"]].merge(
        labs[["date", "symbol", "fwd_ret_1_demeaned"]], on=["date", "symbol"]
    )
    daily = m.groupby("date").apply(
        lambda g: g["mom_21"].corr(g["fwd_ret_1_demeaned"], method="spearman")
    )
    assert 0.02 < daily.mean() < 0.065, daily.mean()


def test_noise_feature_has_no_ic():
    feats = C.make_fake_features(n_days=800, n_symbols=60)
    labs = C.make_fake_labels(n_days=800, n_symbols=60)
    m = feats[["date", "symbol", "rev_5"]].merge(
        labs[["date", "symbol", "fwd_ret_1_demeaned"]], on=["date", "symbol"]
    )
    daily = m.groupby("date").apply(
        lambda g: g["rev_5"].corr(g["fwd_ret_1_demeaned"], method="spearman")
    )
    assert abs(daily.mean()) < 0.015, daily.mean()


# --------------------------------------------------------------------------- #
# validators reject corrupted frames, naming the exact column                  #
# --------------------------------------------------------------------------- #
def test_membership_rejects_missing_column():
    df = C.make_fake_membership().drop(columns=["in_universe"])
    with pytest.raises(C.SchemaError, match="in_universe"):
        C.validate_membership(df)


def test_membership_rejects_wrong_dtype():
    df = C.make_fake_membership()
    df["in_universe"] = df["in_universe"].astype(int)
    with pytest.raises(C.SchemaError, match="in_universe"):
        C.validate_membership(df)


def test_ohlcv_rejects_duplicate_keys():
    df = C.make_fake_ohlcv()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True).sort_values(
        ["date", "symbol"]
    ).reset_index(drop=True)
    with pytest.raises(C.SchemaError, match="date, symbol"):
        C.validate_ohlcv(df)


def test_ohlcv_rejects_unsorted():
    df = C.make_fake_ohlcv().iloc[::-1].reset_index(drop=True)
    with pytest.raises(C.SchemaError, match="sorted"):
        C.validate_ohlcv(df)


def test_ohlcv_rejects_bad_vwap():
    df = C.make_fake_ohlcv()
    df.loc[0, "vwap"] = df.loc[0, "high"] * 2
    with pytest.raises(C.SchemaError, match="vwap"):
        C.validate_ohlcv(df)


def test_ohlcv_rejects_nonpositive_close():
    df = C.make_fake_ohlcv()
    df.loc[0, "close"] = -1.0
    with pytest.raises(C.SchemaError, match="close"):
        C.validate_ohlcv(df)


def test_ohlcv_rejects_all_nan_column():
    df = C.make_fake_ohlcv()
    df["vwap"] = np.nan
    with pytest.raises(C.SchemaError, match="vwap"):
        C.validate_ohlcv(df)


def test_features_rejects_missing_feature_column():
    df = C.make_fake_features().drop(columns=["amihud_21"])
    with pytest.raises(C.SchemaError, match="amihud_21"):
        C.validate_features(df)


def test_features_rejects_positive_dist_52wh():
    df = C.make_fake_features()
    df.loc[0, "dist_52wh"] = 0.5
    with pytest.raises(C.SchemaError, match="dist_52wh"):
        C.validate_features(df)


def test_labels_rejects_missing_horizon():
    df = C.make_fake_labels().drop(columns=["fwd_ret_5_demeaned"])
    with pytest.raises(C.SchemaError, match="fwd_ret_5_demeaned"):
        C.validate_labels(df)


def test_symbols_json_rejects_bad_count():
    payload = C.make_fake_symbols()
    payload["n"] = 999
    with pytest.raises(C.SchemaError, match="n"):
        C.validate_symbols_json(payload)
