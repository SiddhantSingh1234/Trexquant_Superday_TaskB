"""Phase 7 acceptance tests — plain pytest, no network.

Covers the six acceptance criteria in IMPLEMENTATION_PLAN.md Phase 7 plus the
two second-order-overfitting guards (confidence gate, exploration floor) and the
formula-index / book contracts the downstream phases depend on.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src import memory as M
from src.memory import (
    EXPLORATION_FLOOR,
    LESSON_CONFIDENCE_GATE,
    AcceptedBook,
    BanditState,
    FormulaIndex,
    LessonStore,
    Memory,
    formula_hash,
    new_card,
    validate_card,
)


@pytest.fixture
def mem(tmp_path):
    m = Memory(base_dir=tmp_path)
    yield m
    m.close()


# ─────────────────────────────────────────────────────────────────────────────
#  ①  Formula index
# ─────────────────────────────────────────────────────────────────────────────
def test_formula_hash_is_canonical():
    # a*b and b*a must hash identically (canonicalised first)
    assert formula_hash("mul(mom_21, rev_5)") == formula_hash("mul(rev_5, mom_21)")
    assert formula_hash("add(1, 2)") == formula_hash("add(2, 1)")
    assert formula_hash("mul(mom_21, rev_5)") != formula_hash("add(mom_21, rev_5)")


def test_formula_index_seen_and_fingerprint(mem):
    fi = mem.formulas
    h = fi.record("rank(ts_mean(volume, 5))", outcome="rejected")
    assert fi.seen_exact("rank(ts_mean(volume, 5))")
    assert fi.seen_exact(h)
    assert not fi.seen_exact("rank(ts_mean(volume, 20))")

    # same structural shape, different window -> shares a fingerprint
    fi.record("rank(ts_mean(volume, 20))")
    cands = fi.candidates_by_fingerprint("rank(ts_mean(volume, 5))")
    got = {c["canonical_ast"] for c in cands}
    assert "rank(ts_mean(volume,20))" in got and "rank(ts_mean(volume,5))" in got

    # a structurally different formula shares nothing
    fi.record("delta(close, 1)")
    assert all(
        "delta" not in c["canonical_ast"]
        for c in fi.candidates_by_fingerprint("rank(ts_mean(volume, 5))")
    )


# ─────────────────────────────────────────────────────────────────────────────
#  ②  Lesson store — confidence gate + asymmetric veto
# ─────────────────────────────────────────────────────────────────────────────
def test_lesson_confidence_gate(mem):
    """A lesson with n_observations < 3 is NOT an applicable prior; at 3 it is."""
    ls = mem.lessons
    ls.observe("widen_ts_window", helped=True, confidence=0.6, family="liquidity",
               parent_context="volume-ratio factor, horizon 3-5d")
    assert ls.applicable_priors(family="liquidity") == []
    assert ls.get("widen_ts_window", "liquidity")["n_observations"] == 1

    ls.observe("widen_ts_window", helped=True, confidence=0.6, family="liquidity")
    assert ls.applicable_priors(family="liquidity") == []      # n_obs == 2

    ls.observe("widen_ts_window", helped=True, confidence=0.7, family="liquidity")
    priors = ls.applicable_priors(family="liquidity")
    assert len(priors) == 1 and priors[0]["motif"] == "widen_ts_window"
    assert priors[0]["n_observations"] >= LESSON_CONFIDENCE_GATE


def test_lesson_keyword_filter(mem):
    ls = mem.lessons
    for _ in range(3):
        ls.observe("widen_ts_window", helped=True, confidence=0.7, family="liquidity",
                   parent_context="volume-ratio factor")
        ls.observe("add_sector_neutral", helped=True, confidence=0.7, family="value_proxy",
                   parent_context="earnings-yield proxy")
    assert {p["motif"] for p in ls.applicable_priors(keywords=["volume"])} == {"widen_ts_window"}
    assert {p["motif"] for p in ls.applicable_priors(keywords=["earnings"])} == {"add_sector_neutral"}


def test_asymmetric_veto_is_context_scoped(mem):
    """A high-confidence FAILURE hard-blocks a motif in its context — but not in
    a different context."""
    ls = mem.lessons
    # three confident failures in 'momentum'
    for _ in range(3):
        ls.observe("shorten_window", helped=False, confidence=0.9, family="momentum",
                   parent_context="price-momentum factor")
    assert ls.is_vetoed("shorten_window", family="momentum")
    assert ls.get("shorten_window", "momentum")["veto"] == 1

    # excluded from retrieval in its own context...
    assert "shorten_window" not in {
        p["motif"] for p in ls.applicable_priors(family="momentum")
    }
    # ...but still returned with include_vetoed=True (Planner can see the block)
    assert "shorten_window" in {
        p["motif"] for p in ls.applicable_priors(family="momentum", include_vetoed=True)
    }

    # same motif, different context: three successes -> applicable, not vetoed
    for _ in range(3):
        ls.observe("shorten_window", helped=True, confidence=0.8, family="reversal",
                   parent_context="short-term reversal factor")
    assert not ls.is_vetoed("shorten_window", family="reversal")
    assert "shorten_window" in {
        p["motif"] for p in ls.applicable_priors(family="reversal")
    }


def test_success_never_creates_a_veto(mem):
    ls = mem.lessons
    for _ in range(6):
        ls.observe("widen_ts_window", helped=True, confidence=1.0, family="liquidity")
    assert not ls.is_vetoed("widen_ts_window", family="liquidity")


def test_veto_is_sticky_under_later_successes(mem):
    """Asymmetry: a confident failure record is NOT eroded by good runs.  A veto
    is lifted only by an explicit clear_veto()."""
    ls = mem.lessons
    for _ in range(3):
        ls.observe("shorten_window", helped=False, confidence=0.9, family="momentum")
    assert ls.is_vetoed("shorten_window", family="momentum")

    # ten straight successes must NOT lift it
    for _ in range(10):
        ls.observe("shorten_window", helped=True, confidence=1.0, family="momentum")
    assert ls.is_vetoed("shorten_window", family="momentum")

    # only the explicit override clears it, and it stays cleared
    ls.clear_veto("shorten_window", family="momentum")
    assert not ls.is_vetoed("shorten_window", family="momentum")
    ls.observe("shorten_window", helped=False, confidence=0.95, family="momentum")
    assert not ls.is_vetoed("shorten_window", family="momentum")


def test_force_veto(mem):
    ls = mem.lessons
    ls.force_veto("use_raw_price", family="microstructure")
    assert ls.is_vetoed("use_raw_price", family="microstructure")
    assert not ls.is_vetoed("use_raw_price", family="momentum")


def test_lone_confident_failure_does_not_veto(mem):
    """A single high-confidence failure among successes is a fluke, not a
    hard-block — the veto needs two independent confident failures."""
    ls = mem.lessons
    ls.observe("widen_ts_window", helped=True, confidence=0.9, family="liquidity")
    ls.observe("widen_ts_window", helped=False, confidence=0.95, family="liquidity")
    ls.observe("widen_ts_window", helped=True, confidence=0.9, family="liquidity")
    ls.observe("widen_ts_window", helped=True, confidence=0.9, family="liquidity")
    assert not ls.is_vetoed("widen_ts_window", family="liquidity")
    # a second confident failure crosses the bar
    ls.observe("widen_ts_window", helped=False, confidence=0.9, family="liquidity")
    assert ls.is_vetoed("widen_ts_window", family="liquidity")


def test_confidence_is_high_for_a_reliably_harmful_motif(mem):
    """`confidence` = reliability regardless of direction. A motif that always
    hurts has HIGH confidence and LOW p_helps — the harm is not hidden."""
    ls = mem.lessons
    row = {}
    for _ in range(5):
        row = ls.observe("shorten_window", helped=False, confidence=0.9, family="momentum")
    assert row["p_helps"] < 0.15               # direction: reliably hurts
    assert row["confidence"] > 0.6             # but we are confident about it
    # symmetry: a reliably-helpful motif also has high confidence
    for _ in range(5):
        row = ls.observe("add_neutralize", helped=True, confidence=0.9, family="value_proxy")
    assert row["p_helps"] > 0.85 and row["confidence"] > 0.6


def test_validate_card_is_the_contracts_one(mem):
    from src import contracts as C
    assert M.validate_card is C.validate_card
    assert M.CardSchemaError is C.CardSchemaError
    fake = C.make_fake_card()
    C.validate_card(fake)                       # the P0 fixture is schema-valid
    mem.cards.save_card(fake)
    assert mem.cards.load_card(fake["card_id"])["card_id"] == fake["card_id"]


# ─────────────────────────────────────────────────────────────────────────────
#  ③  Bandit state — exploration floor
# ─────────────────────────────────────────────────────────────────────────────
def test_bandit_exploration_floor_after_50_failures(mem):
    b = mem.bandit
    for fam in M.FAMILIES:
        b.register_family(fam)
    for _ in range(50):
        b.update("momentum", reward=-1.0, tokens=100, delta=-0.01)

    alloc = b.allocation()
    assert set(alloc) == set(M.FAMILIES)
    assert min(alloc.values()) >= EXPLORATION_FLOOR - 1e-9      # never starved to 0
    assert alloc["momentum"] >= EXPLORATION_FLOOR - 1e-9
    assert abs(sum(alloc.values()) - 1.0) < 1e-9
    # a winning family gets more than the floor
    b.update("reversal", reward=5.0, tokens=100, delta=0.05)
    assert b.allocation()["reversal"] > EXPLORATION_FLOOR


def test_bandit_last_k_window(mem):
    b = mem.bandit
    for i in range(20):
        b.update("trend", reward=float(i), delta=float(i))
    row = b.row("trend")
    assert row["n_pulls"] == 20
    assert len(row["last_k_deltas"]) == M.BANDIT_LAST_K
    assert row["last_k_deltas"][-1] == 19.0


# ─────────────────────────────────────────────────────────────────────────────
#  ④ + ⑤  Alpha card store + lineage
# ─────────────────────────────────────────────────────────────────────────────
def _fill_thesis(card: dict) -> dict:
    card["thesis"].update(
        mechanism="liquidity providers demand a premium",
        counterparty="forced sellers", why_not_arbitraged="capacity-constrained",
        falsifiable_claim="RankIC > 0 on VAL_B",
    )
    return card


def test_card_roundtrips_and_validates(mem):
    card = _fill_thesis(new_card("c_demo", "th_1", "rank(ts_mean(volume, 5))",
                                 generation=2, pre_registered_sign=1, horizon_days=5))
    card["tier1_metrics"] = {"rank_ic": 0.031}
    card["audit"] = {"marginal_ic": 0.021}
    card["verdict"] = "accept"
    validate_card(card)

    path = mem.cards.save_card(card)
    assert path.exists()
    loaded = mem.cards.load_card("c_demo")
    assert json.dumps(loaded, sort_keys=True) == json.dumps(card, sort_keys=True)

    idx = mem.cards.list_cards(verdict="accept")
    assert len(idx) == 1
    assert idx[0]["rank_ic"] == pytest.approx(0.031)
    assert idx[0]["marginal_ic"] == pytest.approx(0.021)
    assert idx[0]["generation"] == 2


def test_validate_card_rejects_missing_key(mem):
    card = _fill_thesis(new_card("c_bad", "th_1", "rank(volume)"))
    del card["pre_registered"]["hash"]
    with pytest.raises(M.CardSchemaError):
        validate_card(card)


def test_lineage_path_reconstructs_four_generations(mem):
    prev = None
    for g in range(4):
        cid = f"c_gen{g}"
        card = _fill_thesis(new_card(cid, "th_1", f"delta(close, {g + 1})",
                                     generation=g, parent_card_id=prev,
                                     edit_motif=None if prev is None else "widen_ts_window"))
        card["verdict"] = "accept"
        mem.cards.save_card(card)
        prev = cid

    path = mem.cards.lineage_path("c_gen3")
    assert [c["card_id"] for c in path] == ["c_gen0", "c_gen1", "c_gen2", "c_gen3"]
    assert mem.cards.children("c_gen1") == ["c_gen2"]


# ─────────────────────────────────────────────────────────────────────────────
#  ⑥  Accepted book
# ─────────────────────────────────────────────────────────────────────────────
def _fake_signal(seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=30)
    syms = [f"SYM{i:02d}" for i in range(10)]
    return pd.DataFrame(rng.standard_normal((30, 10)), index=dates, columns=syms)


def test_book_add_get_and_replace(mem):
    sig = _fake_signal(1)
    mem.add_to_book("c_a", sig)
    book = mem.get_book()
    assert set(book.columns) == {"date", "symbol", "factor", "value"}
    assert (book["factor"] == "c_a").all()
    assert len(book) == 30 * 10

    # a second card appends; re-adding the first replaces (no duplication)
    mem.add_to_book("c_b", _fake_signal(2))
    mem.add_to_book("c_a", _fake_signal(3))
    book = mem.get_book()
    assert sorted(book["factor"].unique()) == ["c_a", "c_b"]
    assert (book["factor"] == "c_a").sum() == 300

    wide = mem.book.get_book_wide()
    assert set(wide) == {"c_a", "c_b"}
    assert wide["c_a"].shape == (30, 10)


def test_book_is_consumable_by_gate_b():
    """get_book()'s long shape must be exactly what gates._book_to_frames eats."""
    from src import gates as G

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        bk = AcceptedBook(f"{d}/book.parquet")
        bk.add_to_book("c_x", _fake_signal(4))
        frames = G._book_to_frames(bk.get_book())
    assert set(frames) == {"c_x"}
    assert isinstance(frames["c_x"], pd.DataFrame)


# ─────────────────────────────────────────────────────────────────────────────
#  Acceptance criterion 1 — persistence across a process restart
# ─────────────────────────────────────────────────────────────────────────────
def test_all_stores_survive_restart(tmp_path):
    m1 = Memory(base_dir=tmp_path)
    m1.formulas.record("rank(ts_mean(volume, 5))", outcome="accepted")
    for _ in range(3):
        m1.lessons.observe("widen_ts_window", helped=True, confidence=0.7,
                           family="liquidity")
        m1.lessons.observe("shorten_window", helped=False, confidence=0.95,
                           family="momentum")
    for fam in M.FAMILIES:
        m1.bandit.register_family(fam)
    m1.bandit.update("momentum", reward=-1.0)
    card = _fill_thesis(new_card("c_persist", "th_1", "delta(close, 1)"))
    card["verdict"] = "accept"
    m1.cards.save_card(card)
    m1.cards.save_card(_verd(_fill_thesis(new_card("c_persist2", "th_1", "delta(close, 2)",
                                                   parent_card_id="c_persist"))))
    m1.add_to_book("c_persist", _fake_signal(9))
    m1.close()

    # brand-new objects, same files
    m2 = Memory(base_dir=tmp_path)
    try:
        assert m2.formulas.seen_exact("rank(ts_mean(volume, 5))")
        assert m2.lessons.is_vetoed("shorten_window", family="momentum")
        assert len(m2.lessons.applicable_priors(family="liquidity")) == 1
        assert set(m2.bandit.allocation()) == set(M.FAMILIES)
        assert m2.bandit.row("momentum")["n_pulls"] == 1
        assert [c["card_id"] for c in m2.cards.lineage_path("c_persist2")] == [
            "c_persist", "c_persist2"]
        assert m2.book.factors() == ["c_persist"]
    finally:
        m2.close()


def _verd(card, v="accept"):
    card["verdict"] = v
    return card


# ─────────────────────────────────────────────────────────────────────────────
#  init_memory writes the deliverables
# ─────────────────────────────────────────────────────────────────────────────
def test_init_memory_creates_files(tmp_path, monkeypatch):
    import src.config as cfg

    monkeypatch.setattr(cfg, "MEMORY_DB", tmp_path / "memory.db")
    monkeypatch.setattr(cfg, "LESSONS_DB", tmp_path / "lessons.db")
    monkeypatch.setattr(cfg, "BANDIT_STATE_JSON", tmp_path / "bandit_state.json")
    monkeypatch.setattr(cfg, "CARDS_DIR", tmp_path / "cards")
    monkeypatch.setattr(M, "MEMORY_DB", tmp_path / "memory.db")
    monkeypatch.setattr(M, "LESSONS_DB", tmp_path / "lessons.db")
    monkeypatch.setattr(M, "BANDIT_STATE_JSON", tmp_path / "bandit_state.json")
    monkeypatch.setattr(M, "CARDS_DIR", tmp_path / "cards")

    M.init_memory()
    assert (tmp_path / "memory.db").exists()
    assert (tmp_path / "lessons.db").exists()
    state = json.loads((tmp_path / "bandit_state.json").read_text())
    assert set(state["families"]) == set(M.FAMILIES)
    assert state["exploration_floor"] == EXPLORATION_FLOOR
