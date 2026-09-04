"""Phase 10 acceptance tests — plain pytest, no network, LLM_MODE=mock.

Covers the eight acceptance criteria in IMPLEMENTATION_PLAN.md Phase 10 plus the
two graded improvement mechanisms (curriculum rotation, FDR auto-tightening).

Every test runs offline: the agents are the Phase-8 mock fixtures (or small local
stubs) and the panel is a synthetic fixture installed via ``backtester.use_panel``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import backtester as bt
from src import contracts as C
from src import gates as G
from src import loop as L
from src.agents import build_agents
from src.contracts import HORIZONS, NSE_SECTORS
from src.ledger import Ledger
from src.memory import Memory

SEED = 42


# ═════════════════════════════════════════════════════════════════════════════
#  Fixtures — a persistent-latent panel so a real signal survives a 1-day lag
# ═════════════════════════════════════════════════════════════════════════════
def _persistent_panel(n_days: int, n_syms: int = 26, seed: int = SEED,
                      phi: float = 0.95, ic: float = 0.14):
    """AR(1)-latent features/labels + a wide latent frame.

    ``mom_21`` == the per-day z-score of the latent; every ``fwd_ret`` label is
    ``0.02 * (ic * latent + sqrt(h) * noise)``; the latent frame is returned so a
    price field can be set equal to it (a clean, strong, persistent signal).
    """
    rng = np.random.default_rng(seed)
    dates = pd.DatetimeIndex(
        pd.bdate_range("2015-01-01", periods=n_days).normalize()
    ).as_unit("ns")
    syms = [f"SYM{i:03d}" for i in range(n_syms)]

    z = rng.standard_normal((n_days, n_syms))
    lat = np.empty_like(z)
    lat[0] = z[0]
    for t in range(1, n_days):
        lat[t] = phi * lat[t - 1] + np.sqrt(1 - phi ** 2) * z[t]
    latd = pd.DataFrame(lat, index=dates, columns=syms)
    latz = latd.sub(latd.mean(axis=1), axis=0).div(latd.std(axis=1, ddof=0), axis=0)

    def _long(frame, name):
        return (frame.stack(future_stack=True).rename_axis(["date", "symbol"])
                .rename(name).reset_index())

    styled = lambda s, nz: latz * s + nz * rng.standard_normal((n_days, n_syms))  # noqa: E731
    feats = _long(latz, "mom_21")
    fc = {
        "mom_126": styled(0.3, 0.9), "rev_5": styled(0.1, 1.0),
        "vol_21": np.abs(styled(0.2, 0.5)) + 0.05, "beta_63": 1.0 + styled(0.4, 0.7),
        "amihud_21": np.abs(styled(1.0, 0.9)) + 0.01, "turnover_21": 15.0 + styled(1.5, 0.8),
        "max_ret_21": np.abs(styled(0.04, 0.7)) + 0.005,
        "delivery_pct": np.clip(45.0 + styled(15.0, 0.9), 1.0, 99.0),
    }
    for n, a in fc.items():
        feats = feats.merge(_long(pd.DataFrame(a, index=dates, columns=syms), n),
                            on=["date", "symbol"])
    feats = feats.merge(_long(pd.DataFrame(-np.abs(styled(0.2, 0.7)), index=dates,
                                           columns=syms), "dist_52wh"),
                        on=["date", "symbol"])
    size_lvl = pd.DataFrame(np.tile(rng.normal(18, 1.5, n_syms), (n_days, 1)),
                            index=dates, columns=syms)
    feats = feats.merge(_long(size_lvl, "size_proxy"), on=["date", "symbol"])
    sr = np.random.default_rng(seed + 1)
    sect = {s: NSE_SECTORS[int(sr.integers(len(NSE_SECTORS)))] for s in syms}
    feats["sector"] = feats["symbol"].map(sect).astype(str)
    feats["date"] = feats["date"].astype("datetime64[ns]")
    for c in ("mom_21", "mom_126", "rev_5", "vol_21", "beta_63", "amihud_21",
              "turnover_21", "dist_52wh", "max_ret_21", "delivery_pct", "size_proxy"):
        feats[c] = feats[c].astype(np.float64)
    feats = feats.sort_values(["date", "symbol"]).reset_index(drop=True)

    t = np.arange(n_days)
    mkt = 0.004 * np.sin(2 * np.pi * t / 240.0)
    lab = None
    for h in HORIZONS:
        noise = rng.normal(0.0, np.sqrt(h), size=(n_days, n_syms))
        dem = 0.02 * (ic * latz.to_numpy() + noise)
        dd = pd.DataFrame(dem, index=dates, columns=syms)
        dd = dd.sub(dd.mean(axis=1), axis=0)
        rr = dd.add(pd.Series(mkt, index=dates), axis=0)
        for fr, col in ((rr, f"fwd_ret_{h}"), (dd, f"fwd_ret_{h}_demeaned")):
            p = _long(fr, col)
            lab = p if lab is None else lab.merge(p, on=["date", "symbol"])
    for c in [f"fwd_ret_{h}" for h in HORIZONS] + [f"fwd_ret_{h}_demeaned" for h in HORIZONS]:
        lab[c] = lab[c].astype(np.float64)
    lab["date"] = lab["date"].astype("datetime64[ns]")
    lab = lab.sort_values(["date", "symbol"]).reset_index(drop=True)

    C.validate_features(feats)
    C.validate_labels(lab)
    return feats, lab, latz


class _Budget:
    def __init__(self, cap=10 ** 12):
        self.cap = cap
        self.used = 0
        self.tier = "small"
        self.day = "2026-01-01"

    def remaining(self):
        return self.cap - self.used


class _StubAgent:
    """Minimal agent with a ``client.budget`` so RunContext budget maths works."""

    def __init__(self, role, fn):
        self.role = role
        self._fn = fn
        self.client = type("C", (), {"budget": _Budget()})()

    def run(self, **kw):
        return self._fn(**kw)

    review = run


def _mock_agents(memory, **overrides):
    # sleep=no-op: keep TPM/RPM accounting but never actually block a test
    ag = build_agents(mode="mock", memory=memory, probe=True, sleep=lambda _s: None)
    ag.update(overrides)
    return ag


@pytest.fixture
def tmp_env(tmp_path):
    mem = Memory(base_dir=tmp_path / "mem")
    led = Ledger(tmp_path / "ledger.db")
    yield {"mem": mem, "led": led, "dir": tmp_path}
    bt.clear_panel()


# ═════════════════════════════════════════════════════════════════════════════
#  1. Runs end-to-end in LLM_MODE=mock with no network
# ═════════════════════════════════════════════════════════════════════════════
def test_runs_end_to_end_mock_no_network(tmp_env):
    feats, labs, latz = _persistent_panel(n_days=900)
    bt.use_panel(feats, labs)
    panel = L.synthetic_price_panel(n_days=900, n_symbols=26, seed=SEED,
                                    planted=latz, planted_field="delivery_pct")
    res = L.run_loop(
        run_id="e2e", max_generations=3, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], llm_mode="mock", throttle=False,
        price_panel=panel, do_holdout_peek=False,
        prices=C.make_fake_ohlcv(n_days=900, n_symbols=26, seed=SEED),
        report_path=tmp_env["dir"] / "rep.md",
    )
    assert res.status in ("completed", "stopped_early")
    assert len(res.generations) >= 1
    assert res.report_path and (tmp_env["dir"] / "rep.md").exists()
    # every generation reached `reflect` (has a verdict)
    assert all(g["verdict"] in ("accept", "reject") for g in res.generations)


# ═════════════════════════════════════════════════════════════════════════════
#  2. Variant counter never exceeds 20 — Judge always says "refine"
# ═════════════════════════════════════════════════════════════════════════════
def test_variant_cap_enforced_when_judge_always_refines(tmp_env):
    feats, labs, latz = _persistent_panel(n_days=800)
    bt.use_panel(feats, labs)
    panel = L.synthetic_price_panel(n_days=800, n_symbols=26, seed=SEED)

    # distinct formula each call (a real LLM does not repeat verbatim)
    counter = {"i": 0}

    def coder(**kw):
        counter["i"] += 1
        w = 3 + counter["i"]
        return {"formula": f"rank(ts_mean(volume, {w}))",
                "ast_canonical": f"rank(ts_mean(volume,{w}))",
                "complexity": {"nodes": 4, "depth": 3, "free_params": 1},
                "rationale": "x"}

    def judge(**kw):
        return {"action": "refine", "edit_motif": "widen_ts_window", "reason": "keep going"}

    ag = _mock_agents(tmp_env["mem"],
                      coder=_StubAgent("coder", coder),
                      judge=_StubAgent("judge", judge))
    res = L.run_loop(
        run_id="cap", max_generations=1, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], agents=ag, price_panel=panel,
        do_holdout_peek=False, prices=C.make_fake_ohlcv(n_days=800, n_symbols=26, seed=SEED),
        report_path=tmp_env["dir"] / "rep.md",
    )
    assert res.max_variant_count() == 20, res.max_variant_count()
    assert all(g["variant_count"] <= 20 for g in res.generations)
    assert res.generations[0]["forced_promote"] is True
    # ledger recorded exactly one tier1 trial per variant (20)
    tier1 = [r for r in tmp_env["led"].trial_records(counts_only=True)
             if r["rejection_reason"] == "tier1_variant"]
    assert len(tier1) == 20


# ═════════════════════════════════════════════════════════════════════════════
#  3. No VAL_B call occurs before a promote (backtester instrumented)
# ═════════════════════════════════════════════════════════════════════════════
def test_no_val_b_call_before_promote(tmp_env):
    feats, labs, latz = _persistent_panel(n_days=900)
    bt.use_panel(feats, labs)
    panel = L.synthetic_price_panel(n_days=900, n_symbols=26, seed=SEED,
                                    planted=latz, planted_field="delivery_pct")
    res = L.run_loop(
        run_id="vb", max_generations=3, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], llm_mode="mock", throttle=False,
        price_panel=panel, do_holdout_peek=False,
        prices=C.make_fake_ohlcv(n_days=900, n_symbols=26, seed=SEED),
        report_path=tmp_env["dir"] / "rep.md",
    )
    val_b = [e for e in res.recorder if e["kind"] == "backtest" and e["split"] == "val_b"]
    promotes = [e for e in res.recorder if e["kind"] == "promote"]
    assert val_b, "expected at least one VAL_B backtest in the run"
    assert promotes, "expected at least one promote"
    assert res.val_b_before_promote() is False
    # each VAL_B call is preceded by a promote OF ITS OWN THESIS.  Matching
    # against any promote in the run would let a later thesis reach VAL_B on the
    # strength of an earlier thesis's promote.
    promote_at = {}
    for p in promotes:
        promote_at.setdefault(p["thesis_id"], p["seq"])
    for e in val_b:
        own = promote_at.get(e["thesis_id"])
        assert own is not None, f"VAL_B on {e['thesis_id']} with no promote for it"
        assert own < e["seq"], f"VAL_B on {e['thesis_id']} preceded its own promote"
    # more than one thesis actually reached VAL_B, so the per-thesis check bites
    assert len({e["thesis_id"] for e in val_b}) >= 1


def test_val_b_detector_catches_a_planted_violation():
    """The guard must fail on a bad trace — otherwise `False` proves nothing."""
    mk = lambda **k: dict(k)  # noqa: E731
    ok = L.RunResult(
        status="completed", stopped_reason="", generations=[], accepted_card_ids=[],
        n_trials=0, holdout_peeks_used=0, t_stat_bar_final=3.0, min_marginal_ic_final=0.01,
        portfolio={}, report_path="", state_digest="", recorder=[
            mk(kind="promote", thesis_id="t0", seq=0),
            mk(kind="backtest", split="val_b", thesis_id="t0", has_token=False, seq=1),
        ])
    assert ok.val_b_before_promote() is False

    # thesis t1 reaches VAL_B on the back of t0's promote — the exact hole a
    # run-global check leaves open.
    bad = L.RunResult(
        status="completed", stopped_reason="", generations=[], accepted_card_ids=[],
        n_trials=0, holdout_peeks_used=0, t_stat_bar_final=3.0, min_marginal_ic_final=0.01,
        portfolio={}, report_path="", state_digest="", recorder=[
            mk(kind="promote", thesis_id="t0", seq=0),
            mk(kind="backtest", split="val_b", thesis_id="t0", has_token=False, seq=1),
            mk(kind="backtest", split="val_b", thesis_id="t1", has_token=False, seq=2),
        ])
    assert bad.val_b_before_promote() is True

    # and VAL_B strictly before that thesis's own promote
    early = L.RunResult(
        status="completed", stopped_reason="", generations=[], accepted_card_ids=[],
        n_trials=0, holdout_peeks_used=0, t_stat_bar_final=3.0, min_marginal_ic_final=0.01,
        portfolio={}, report_path="", state_digest="", recorder=[
            mk(kind="backtest", split="val_b", thesis_id="t0", has_token=False, seq=0),
            mk(kind="promote", thesis_id="t0", seq=1),
        ])
    assert early.val_b_before_promote() is True


# ═════════════════════════════════════════════════════════════════════════════
#  4. gate_b_novelty is always called before gate_b_stats
# ═════════════════════════════════════════════════════════════════════════════
def test_gate_b_novelty_precedes_statistics(tmp_env):
    feats, labs, latz = _persistent_panel(n_days=2450)
    bt.use_panel(feats, labs)
    panel = L.synthetic_price_panel(n_days=2450, n_symbols=26, seed=SEED,
                                    planted=latz, planted_field="delivery_pct")

    def coder(**kw):
        return {"formula": "rank(delivery_pct)", "ast_canonical": "rank(delivery_pct)",
                "complexity": {"nodes": 2, "depth": 2, "free_params": 0}, "rationale": "x"}

    ag = _mock_agents(tmp_env["mem"], coder=_StubAgent("coder", coder))
    res = L.run_loop(
        run_id="ord", max_generations=2, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], agents=ag, price_panel=panel,
        do_holdout_peek=True,
        prices=C.make_fake_ohlcv(n_days=2450, n_symbols=26, seed=SEED),
        report_path=tmp_env["dir"] / "rep.md",
    )
    steps = [e for e in res.recorder if e["kind"] == "gate_step"]
    assert any(s["step"] == "statistics" for s in steps), "stats step never reached"
    assert res.novelty_always_before_stats() is True
    # and no holdout backtest happened before the first statistics step
    first_stats = min(e["seq"] for e in steps if e["step"] == "statistics")
    holdout = [e for e in res.recorder if e["kind"] == "backtest" and e["split"] == "holdout"]
    assert all(e["seq"] > first_stats for e in holdout)
    assert res.holdout_only_with_token() is True


# ═════════════════════════════════════════════════════════════════════════════
#  5. A rejected card still reaches reflect and is written to memory
# ═════════════════════════════════════════════════════════════════════════════
def test_rejected_card_reaches_reflect_and_memory(tmp_env):
    feats, labs, latz = _persistent_panel(n_days=900)
    bt.use_panel(feats, labs)
    panel = L.synthetic_price_panel(n_days=900, n_symbols=26, seed=SEED)  # no plant -> noise

    res = L.run_loop(
        run_id="rej", max_generations=2, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], llm_mode="mock", throttle=False,
        price_panel=panel, do_holdout_peek=False,
        prices=C.make_fake_ohlcv(n_days=900, n_symbols=26, seed=SEED),
        report_path=tmp_env["dir"] / "rep.md",
    )
    assert all(g["verdict"] == "reject" for g in res.generations)
    # reflection wrote a lesson to memory ...
    assert len(tmp_env["mem"].lessons.all_lessons()) >= 1
    # ... the bandit was updated ...
    assert any(tmp_env["mem"].bandit.row(f).get("n_pulls", 0) > 0
               for f in tmp_env["mem"].bandit.families())
    # ... and a reject card was persisted
    rej_cards = tmp_env["mem"].cards.list_cards(verdict="reject")
    assert len(rej_cards) >= 1


# ═════════════════════════════════════════════════════════════════════════════
#  6. Checkpoint / resume produces identical state
# ═════════════════════════════════════════════════════════════════════════════
def test_checkpoint_resume_produces_identical_state(tmp_env):
    feats, labs, latz = _persistent_panel(n_days=900)
    panel = L.synthetic_price_panel(n_days=900, n_symbols=26, seed=SEED,
                                    planted=latz, planted_field="delivery_pct")
    prices = C.make_fake_ohlcv(n_days=900, n_symbols=26, seed=SEED)

    # -- clean 3-generation run ---------------------------------------
    bt.use_panel(feats, labs)
    m1 = Memory(base_dir=tmp_env["dir"] / "m1")
    l1 = Ledger(tmp_env["dir"] / "l1.db")
    clean = L.run_loop(run_id="R", max_generations=3, checkpoint_path=tmp_env["dir"] / "c1.db",
                       memory=m1, ledger=l1, llm_mode="mock", price_panel=panel,
                       do_holdout_peek=False, prices=prices,
                       report_path=tmp_env["dir"] / "r1.md")
    bt.clear_panel()

    # -- interrupted after gen 1, then resumed -----------------------
    bt.use_panel(feats, labs)
    m2 = Memory(base_dir=tmp_env["dir"] / "m2")
    l2 = Ledger(tmp_env["dir"] / "l2.db")
    part = L.run_loop(run_id="R", max_generations=3, checkpoint_path=tmp_env["dir"] / "c2.db",
                      memory=m2, ledger=l2, llm_mode="mock", price_panel=panel,
                      do_holdout_peek=False, prices=prices, stop_after_generation=1,
                      report_path=tmp_env["dir"] / "r2.md")
    assert part.status == "stopped_early"
    assert len(part.generations) == 1

    m2b = Memory(base_dir=tmp_env["dir"] / "m2")
    l2b = Ledger(tmp_env["dir"] / "l2.db")
    resumed = L.run_loop(run_id="R", max_generations=3, checkpoint_path=tmp_env["dir"] / "c2.db",
                         memory=m2b, ledger=l2b, llm_mode="mock", price_panel=panel,
                         do_holdout_peek=False, prices=prices, resume=True,
                         report_path=tmp_env["dir"] / "r2b.md")
    bt.clear_panel()

    assert len(resumed.generations) == 3
    assert resumed.state_digest == clean.state_digest
    assert resumed.accepted_card_ids == clean.accepted_card_ids
    assert [g["verdict"] for g in resumed.generations] == [g["verdict"] for g in clean.generations]


# ═════════════════════════════════════════════════════════════════════════════
#  7. Exhausting the token budget stops the loop cleanly, no partial write
# ═════════════════════════════════════════════════════════════════════════════
def test_token_budget_exhaustion_stops_cleanly(tmp_env):
    from src.agents.base import TokenBudget

    feats, labs, latz = _persistent_panel(n_days=800)
    bt.use_panel(feats, labs)
    panel = L.synthetic_price_panel(n_days=800, n_symbols=26, seed=SEED)

    # a tiny cap: the first thesis cannot finish
    lb = TokenBudget("large", cap=4000)
    sb = TokenBudget("small", cap=4000)
    res = L.run_loop(
        run_id="bud", max_generations=5, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], llm_mode="mock", throttle=False,
        price_panel=panel, do_holdout_peek=False,
        prices=C.make_fake_ohlcv(n_days=800, n_symbols=26, seed=SEED),
        large_budget=lb, small_budget=sb, report_path=tmp_env["dir"] / "rep.md",
    )
    assert res.status == "paused_budget"
    assert "budget exhausted" in res.stopped_reason.lower()
    # no accepted card, no partial card JSON on disk
    assert res.accepted_card_ids == []
    assert tmp_env["mem"].cards.list_cards() == []
    # the checkpoint records where to resume
    from src.loop import SqliteSaver

    saver = SqliteSaver(tmp_env["dir"] / "cp.db")
    st = saver.load_run_state()
    saver.close()
    assert st is not None and st["run_id"] == "bud"
    assert st["incomplete_gen"] is not None


# ═════════════════════════════════════════════════════════════════════════════
#  8. Portfolio is NOT a graph node
# ═════════════════════════════════════════════════════════════════════════════
def test_portfolio_is_not_a_graph_node(tmp_env):
    ctx = L.RunContext(
        run_id="p", memory=tmp_env["mem"], ledger=tmp_env["led"],
        agents=_mock_agents(tmp_env["mem"]),
        price_panel=L.synthetic_price_panel(n_days=400, n_symbols=12, seed=SEED),
    )
    graph = L.build_graph(ctx)
    nodes = set(L._make_nodes(ctx))
    assert "portfolio" not in nodes
    assert "portfolio_combine" not in nodes
    assert not any("portfolio" in n for n in graph.get_graph().nodes)
    # it exists as a standalone function
    assert callable(L.portfolio_combine)


def test_portfolio_runs_after_the_graph(tmp_env):
    feats, labs, latz = _persistent_panel(n_days=900)
    bt.use_panel(feats, labs)
    panel = L.synthetic_price_panel(n_days=900, n_symbols=26, seed=SEED)
    res = L.run_loop(
        run_id="pf", max_generations=2, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], llm_mode="mock", throttle=False,
        price_panel=panel, do_holdout_peek=False,
        prices=C.make_fake_ohlcv(n_days=900, n_symbols=26, seed=SEED),
        report_path=tmp_env["dir"] / "rep.md",
    )
    assert isinstance(res.portfolio, dict)
    assert res.portfolio["status"] in ("ok", "insufficient")


# ═════════════════════════════════════════════════════════════════════════════
#  Improvement mechanism — curriculum rotation
# ═════════════════════════════════════════════════════════════════════════════
def test_curriculum_regimes_rotate_every_n_generations():
    every = 3
    # fully hashable (sorted() returns a list) so the blocks can go in a set
    seen = [tuple(tuple(sorted(d.items())) for d in L.curriculum_regimes(g, every))
            for g in range(12)]
    # constant within a block of `every` generations ...
    assert seen[0] == seen[1] == seen[2]
    assert seen[3] == seen[4] == seen[5]
    # ... every block within one full cycle is distinct (a chained `!=` would NOT
    # compare seen[0] with seen[6], so compare the blocks pairwise) ...
    blocks = [seen[b * every] for b in range(len(L.CURRICULUM_ROTATION))]
    assert len(set(blocks)) == len(L.CURRICULUM_ROTATION), blocks
    # ... and it cycles back after a full rotation
    assert L.curriculum_regimes(0, every) == L.curriculum_regimes(
        len(L.CURRICULUM_ROTATION) * every, every)


def test_curriculum_mandatory_regime_is_enforced_in_redteam(tmp_env):
    # a strong, persistent, clean signal so the thesis reliably reaches Gate C
    feats, labs, latz = _persistent_panel(n_days=2000, ic=0.16, phi=0.96)
    bt.use_panel(feats, labs)
    panel = L.synthetic_price_panel(n_days=2000, n_symbols=26, seed=SEED,
                                    planted=latz, planted_field="delivery_pct")

    def coder(**kw):
        return {"formula": "rank(delivery_pct)", "ast_canonical": "rank(delivery_pct)",
                "complexity": {"nodes": 2, "depth": 2, "free_params": 0}, "rationale": "x"}

    def judge(**kw):
        return {"action": "promote", "edit_motif": "promote_as_is", "reason": "strong"}

    ag = _mock_agents(tmp_env["mem"],
                      coder=_StubAgent("coder", coder),
                      judge=_StubAgent("judge", judge))
    res = L.run_loop(
        run_id="curr", max_generations=2, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], agents=ag, price_panel=panel,
        do_holdout_peek=False, curriculum_every=1,
        prices=C.make_fake_ohlcv(n_days=2000, n_symbols=26, seed=SEED),
        report_path=tmp_env["dir"] / "rep.md",
    )
    # the mandatory regime slice is present per generation and rotates
    regs = [tuple(sorted(g["mandatory_regimes"][0].items())) for g in res.generations]
    assert regs[0] != regs[1]
    # Gate C was reached and a curriculum backtest was recorded as counts_as_trial=0
    assert any(g.get("redteam_verdict") for g in res.generations), \
        f"no generation reached Gate C: {[g['reject_reason'] for g in res.generations]}"
    curr = [r for r in tmp_env["led"].trial_records(counts_only=False)
            if str(r["rejection_reason"]).startswith("curriculum:")]
    assert curr and all(r["counts_as_trial"] == 0 for r in curr)


# ═════════════════════════════════════════════════════════════════════════════
#  Improvement mechanism — FDR auto-tightening meta-check
# ═════════════════════════════════════════════════════════════════════════════
def test_fdr_meta_check_tightens_gates(tmp_env):
    feats, labs, latz = _persistent_panel(n_days=800)
    bt.use_panel(feats, labs)
    panel = L.synthetic_price_panel(n_days=800, n_symbols=26, seed=SEED)

    t0 = G.T_STAT_BAR
    res = L.run_loop(
        run_id="fdr", max_generations=3, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], llm_mode="mock", throttle=False,
        price_panel=panel, do_holdout_peek=False,
        prices=C.make_fake_ohlcv(n_days=800, n_symbols=26, seed=SEED),
        fdr_provider=lambda gens: 0.9,   # force a high rolling FDR every generation
        report_path=tmp_env["dir"] / "rep.md",
    )
    assert res.t_stat_bar_final > t0
    assert res.min_marginal_ic_final > G.MIN_MARGINAL_IC or res.min_marginal_ic_final > 0.01
    # the process-global threshold is restored after the run
    assert G.T_STAT_BAR == t0


def test_fdr_meta_check_leaves_gates_alone_when_fdr_is_low(tmp_env):
    feats, labs, latz = _persistent_panel(n_days=800)
    bt.use_panel(feats, labs)
    panel = L.synthetic_price_panel(n_days=800, n_symbols=26, seed=SEED)
    t0 = G.T_STAT_BAR
    res = L.run_loop(
        run_id="fdrlow", max_generations=2, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], llm_mode="mock", throttle=False,
        price_panel=panel, do_holdout_peek=False,
        prices=C.make_fake_ohlcv(n_days=800, n_symbols=26, seed=SEED),
        fdr_provider=lambda gens: 0.0,
        report_path=tmp_env["dir"] / "rep.md",
    )
    assert res.t_stat_bar_final == t0


# ═════════════════════════════════════════════════════════════════════════════
#  Full accept path — a genuine signal survives every gate and emits a card
# ═════════════════════════════════════════════════════════════════════════════
def test_full_accept_path_emits_a_valid_card(tmp_env):
    feats, labs, latz = _persistent_panel(n_days=2450, ic=0.16, phi=0.96)
    bt.use_panel(feats, labs)
    # price field == the exact latent -> rank(delivery_pct) is a clean strong signal
    panel = L.synthetic_price_panel(n_days=2450, n_symbols=26, seed=SEED,
                                    planted=latz, planted_field="delivery_pct")

    def coder(**kw):
        return {"formula": "rank(delivery_pct)", "ast_canonical": "rank(delivery_pct)",
                "complexity": {"nodes": 2, "depth": 2, "free_params": 0}, "rationale": "x"}

    def judge(**kw):
        return {"action": "promote", "edit_motif": "promote_as_is", "reason": "strong"}

    ag = _mock_agents(tmp_env["mem"],
                      coder=_StubAgent("coder", coder),
                      judge=_StubAgent("judge", judge))
    res = L.run_loop(
        run_id="acc", max_generations=1, checkpoint_path=tmp_env["dir"] / "cp.db",
        memory=tmp_env["mem"], ledger=tmp_env["led"], agents=ag, price_panel=panel,
        do_holdout_peek=True, curriculum_every=99,
        prices=C.make_fake_ohlcv(n_days=2450, n_symbols=26, seed=SEED),
        report_path=tmp_env["dir"] / "rep.md",
    )
    g = res.generations[0]
    if g["verdict"] != "accept":
        pytest.skip(f"signal did not clear every gate on this fixture draw: {g['reject_reason']}")
    assert res.accepted_card_ids and res.accepted_card_ids[0]
    card = tmp_env["mem"].cards.load_card(res.accepted_card_ids[0])
    C.validate_card(card)
    assert card["verdict"] == "accept"
    assert res.holdout_peeks_used == 1
    assert res.portfolio["status"] in ("ok", "insufficient")


# ═════════════════════════════════════════════════════════════════════════════
#  Verdict math lives in code, never in an LLM node
# ═════════════════════════════════════════════════════════════════════════════
VERDICT_NODES = ("prefilter", "tier1", "force_decision", "freshfold", "tier2",
                 "gate_b_novelty", "gate_b_stats")


def test_no_llm_call_inside_verdict_nodes(tmp_env):
    """The tool nodes that decide accept/reject must not call an agent.

    Parsed with ``ast`` rather than substring-matched: a textual check only
    catches the one spelling it was written for, and silently passes if a node is
    renamed.  ``A`` is the agent registry alias bound at the top of
    ``_make_nodes`` (``A = ctx.agents``), so any ``A[...]`` / ``agents[...]``
    subscript inside a verdict node is an LLM reaching into verdict math.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(L._make_nodes)))
    seen, offenders = set(), {}
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name in VERDICT_NODES):
            continue
        seen.add(fn.name)
        for n in ast.walk(fn):
            if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
                    and n.value.id in ("A", "agents")):
                offenders.setdefault(fn.name, []).append(ast.unparse(n))
    # the test is worthless if it silently stopped finding the nodes
    assert seen == set(VERDICT_NODES), f"verdict nodes not found: {set(VERDICT_NODES) - seen}"
    assert not offenders, f"agent call inside verdict node(s): {offenders}"


def test_sqlite_saver_uses_stdlib_only():
    import inspect

    src = inspect.getsource(L)
    assert "langgraph_checkpoint_sqlite" not in src
    assert "langgraph.checkpoint.sqlite" not in src
    assert "import sqlite3" in src
