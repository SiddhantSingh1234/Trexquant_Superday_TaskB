"""D1 — cache-builder acceptance tests.

Most assertions read the parquets already written by
``python dashboard/build_cache.py`` into ``data/dashboard/``.  Run that first
(the handoff lists the command); tests that need it ``skip`` cleanly otherwise.
Two tests build into a tmp dir to check idempotency and the missing-source path.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dashboard import build_cache
from dashboard.lib import fixtures

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "dashboard"

CHEAP = [n for n, b in build_cache._REGISTRY.items() if not b.heavy]


def _cache(name: str) -> pd.DataFrame:
    p = CACHE / f"{name}.parquet"
    if not p.exists():
        pytest.skip(f"{name}.parquet not built — run `python dashboard/build_cache.py`")
    return pd.read_parquet(p)


# --------------------------------------------------------------------------- #
# registry + schemas                                                          #
# --------------------------------------------------------------------------- #
def test_registry_covers_every_cache_file():
    assert set(build_cache._REGISTRY) == set(fixtures.CACHE_SCHEMAS)
    assert {n for n, b in build_cache._REGISTRY.items() if b.heavy} == {
        "zoo_leaderboard", "prices_yf_crosscheck"}


@pytest.mark.parametrize("name", CHEAP)
def test_cheap_parquet_matches_schema(name):
    df = _cache(name)
    schema = fixtures.CACHE_SCHEMAS[name]
    assert list(df.columns) == list(schema), name
    for col, dt in schema.items():
        got = str(df[col].dtype)
        if dt == "datetime64[ns]":
            assert got.startswith("datetime64[ns"), (name, col, got)
        elif dt == "bool":
            assert got == "bool", (name, col, got)
        elif dt == "int64":
            assert got.startswith("int"), (name, col, got)
        elif dt == "float64":
            assert got.startswith("float"), (name, col, got)


def test_check_passes():
    # --check returns 0 (OK) or 1 (stale, expected while P11/P12 run); never 2
    assert build_cache.check() in (0, 1)


# --------------------------------------------------------------------------- #
# the care-point acceptance numbers                                           #
# --------------------------------------------------------------------------- #
def test_universe_coverage_is_flat():
    dc = _cache("universe_daily_coverage")
    dt = pd.to_datetime(dc["date"])
    x = (dt - dt.min()).dt.days.to_numpy() / 365.25
    slope = np.polyfit(x, dc["n_panel"].to_numpy(float), 1)[0]
    assert abs(slope) < 3.0, f"n_panel slopes {slope:.2f}/yr — survivorship leak?"
    assert dc["n_panel"].between(150, 205).mean() > 0.98


def test_ic_shift_base_and_shift1_differ():
    sh = _cache("panel_feature_ic_shift")
    piv = sh.pivot(index="feature", columns="variant", values="rank_ic")
    rel = (piv["base"] - piv["shift1"]).abs() / piv["base"].abs()
    assert rel.loc["mom_21"] > 0.20, f"mom_21 base vs shift1 only {rel.loc['mom_21']:.1%}"
    # every feature's IC must move under a 1-day shift (no feature is shift-invariant)
    assert (piv["base"] != piv["shift1"]).all()


def test_leaky_check_recovers_unit_ic():
    lk = _cache("panel_leaky_check")
    row = lk.loc[lk["predictor"] == "fwd_ret_1", "rank_ic"]
    assert float(row.iloc[0]) > 0.9


def test_feature_ic_has_six_horizons_each():
    ic = _cache("panel_feature_ic")
    assert sorted(ic["horizon"].unique()) == [1, 2, 3, 5, 10, 21]
    assert ic.groupby("feature").size().eq(6).all()


def test_extreme_returns_are_not_winsorized():
    er = _cache("prices_extreme_returns")
    if er.empty:
        pytest.skip("no extreme returns")
    assert er["ret"].abs().min() > 0.5
    assert er["ret"].abs().max() > 0.5  # genuinely large moves kept


def test_loop_caches_are_no_source_until_a_run():
    man = build_cache._load_manifest()
    if not man:
        pytest.skip("no manifest")
    for name in ("loop_generations", "loop_run_meta"):
        if name in man:
            assert man[name]["status"] == "no_source"


# --------------------------------------------------------------------------- #
# idempotency + missing-source                                                #
# --------------------------------------------------------------------------- #
def test_idempotent_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(build_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(build_cache, "MANIFEST", tmp_path / "_manifest.json")
    names = ["corpus_family_counts", "agents_token_budget", "universe_monthly",
             "panel_feature_corr", "prices_quality"]
    build_cache.run_builders(names, heavy=False)
    h1 = {n: hashlib.md5((tmp_path / f"{n}.parquet").read_bytes()).hexdigest() for n in names}
    build_cache.run_builders(names, heavy=False)
    h2 = {n: hashlib.md5((tmp_path / f"{n}.parquet").read_bytes()).hexdigest() for n in names}
    assert h1 == h2


def test_missing_source_writes_empty_no_source(tmp_path, monkeypatch):
    monkeypatch.setattr(build_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(build_cache, "MANIFEST", tmp_path / "_manifest.json")
    monkeypatch.setattr(build_cache, "_exists", lambda *a: False)
    build_cache._panel_wide.cache_clear()
    build_cache.run_builders(["panel_feature_ic", "universe_daily_coverage"], heavy=False)
    man = build_cache._load_manifest()
    for n in ("panel_feature_ic", "universe_daily_coverage"):
        assert man[n]["status"] == "no_source"
        df = pd.read_parquet(tmp_path / f"{n}.parquet")
        assert list(df.columns) == list(fixtures.CACHE_SCHEMAS[n])
        assert len(df) == 0


def test_db_reads_do_not_mutate_source():
    led = ROOT / "data" / "ledger.db"
    if not led.exists():
        pytest.skip("no data/ledger.db")
    before = led.stat().st_mtime_ns
    build_cache._ledger_summary()
    assert led.stat().st_mtime_ns == before


def test_check_flags_staleness(tmp_path, monkeypatch):
    monkeypatch.setattr(build_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(build_cache, "MANIFEST", tmp_path / "_manifest.json")
    build_cache.run_builders(["corpus_family_counts"], heavy=False)
    man = build_cache._load_manifest()
    man["corpus_family_counts"]["sources"][0]["mtime"] = 1.0  # pretend cache is old
    build_cache._save_manifest(man)
    assert build_cache.check() == 1  # stale, non-zero
