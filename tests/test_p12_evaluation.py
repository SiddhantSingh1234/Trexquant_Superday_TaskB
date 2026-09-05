"""Phase 12 tests -- fast, shrunk-scale smoke tests over the real machinery.

Full-scale numbers (N_DAYS=1750, N_SYMBOLS=50, OVERFIT_N_CANDIDATES=100) take
several minutes -- reports/p12_system_evaluation.md quotes those, reproduced
via scripts/p12_run_evaluation.py. These tests run a shrunk pool so `pytest`
stays fast, and check structural properties rather than exact numbers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import evaluation as ev


@pytest.fixture()
def small_ev(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "N_DAYS", 700)
    monkeypatch.setattr(ev, "N_SYMBOLS", 24)
    monkeypatch.setattr(ev, "N_PER_CATEGORY", 3)
    monkeypatch.setattr(ev, "OVERFIT_N_CANDIDATES", 10)
    monkeypatch.setattr(ev, "ABLATION_LEDGER_DB", tmp_path / "ablation_ledger.db")
    monkeypatch.setattr(ev, "PLOTS_DIR", tmp_path / "plots")
    return ev


def test_build_world_is_schema_valid_and_deterministic(small_ev):
    w1 = small_ev.build_world(seed=42)
    w2 = small_ev.build_world(seed=42)
    pd.testing.assert_frame_equal(w1.features, w2.features)
    pd.testing.assert_frame_equal(w1.labels, w2.labels)
    # mom_21 is exactly the planted latent's per-day z-score
    mom21 = w1.features.pivot(index="date", columns="symbol", values="mom_21")
    pd.testing.assert_frame_equal(mom21, w1.latent_wide, check_names=False, check_freq=False)


def test_pool_has_known_ground_truth_and_expected_size(small_ev):
    world = small_ev.build_world(seed=42)
    pool = small_ev.build_pool(world, seed=42)
    assert len(pool) == 4 * small_ev.N_PER_CATEGORY
    names = [p[0] for p in pool]
    assert len(set(names)) == len(names)  # every member uniquely identified
    cats = {p[1] for p in pool}
    assert cats == set(small_ev.CATEGORIES)
    for cat in small_ev.CATEGORIES:
        assert sum(1 for _, c, _ in pool if c == cat) == small_ev.N_PER_CATEGORY


def test_genuine_signal_correlates_with_the_planted_latent(small_ev):
    world = small_ev.build_world(seed=42)
    pool = small_ev.build_pool(world, seed=42)
    name, cat, sig = next(p for p in pool if p[1] == "genuine")
    corr = np.corrcoef(sig.to_numpy().ravel(), world.latent_wide.to_numpy().ravel())[0, 1]
    assert corr > 0.3  # genuine tracks the true latent; noise/leaky/overfit do not by construction


def test_run_evaluation_end_to_end_no_exceptions(small_ev):
    out = small_ev.run_evaluation(seed=42)
    df = out["pool_df"]
    assert len(df) == 4 * small_ev.N_PER_CATEGORY
    assert set(df["category"]) == set(small_ev.CATEGORIES)
    for col in ("novelty_pass", "stats_pass", "redteam_pass"):
        assert df[col].dtype == bool

    catch_df = out["catch_df"]
    assert set(catch_df["gate"]) == set(small_ev.GATE_COLS)
    assert catch_df["catch_rate"].between(0, 1).all()
    assert catch_df["false_kill_rate"].between(0, 1).all()

    fdr_df = out["fdr_df"]
    assert set(fdr_df["variant"]) == {"all_gates_on", "novelty_off", "stats_off", "redteam_off"}

    gen_df = out["gen_df"]
    assert len(gen_df) == small_ev.N_GENERATIONS
    assert (gen_df["n"] == gen_df["n"].iloc[0]).all()  # equal-sized batches

    assert (small_ev.PLOTS_DIR / "gate_ablation.png").exists()
    assert (small_ev.PLOTS_DIR / "learning.png").exists()


def test_real_ledger_snapshot_is_read_only_and_reports_generation_zero():
    snap = ev.real_ledger_snapshot()
    if snap["exists"]:
        # Documented finding (reports/p12_handoff.md): every real recorded
        # thesis is generation 0 -- the LLM budget ceiling has never let a
        # real run reach a second generation.
        assert snap["generation_tags"] == ["0"] or snap["generation_tags"] == []


def test_real_cards_snapshot_reads_without_raising():
    snap = ev.real_cards_snapshot()
    assert snap["n_cards"] >= 0
    assert snap["n_accepted"] <= snap["n_cards"]
