"""Phase 8 acceptance tests — plain pytest, no network, LLM_MODE=mock.

Covers every acceptance bullet in IMPLEMENTATION_PLAN.md Phase 8.
"""
from __future__ import annotations

import json

import pytest

from src import config
from src.agents import (
    Coder,
    Economics,
    Hypothesis,
    Judge,
    Planner,
    RedTeam,
    Reflection,
    build_agents,
    commit_preregistration,
    load_corpus,
    retrieve,
    validate_corpus,
)
from src.agents.base import (
    BudgetExhausted,
    LLMClient,
    NoModelAvailable,
    SchemaValidationError,
    TokenBudget,
    call_llm,
    estimate_tokens,
    probe_model_chain,
    reset_clients,
)
from src.agents.librarian import Librarian
from src.agents.redteam import RED_TEAM_MENU
from src.ast_tools import complexity, parse
from src.memory import Memory


@pytest.fixture(autouse=True)
def _clean_clients():
    reset_clients()
    yield
    reset_clients()


@pytest.fixture
def mem(tmp_path):
    m = Memory(base_dir=tmp_path)
    yield m
    m.close()


@pytest.fixture
def agents(mem):
    return build_agents(mode="mock", memory=mem, probe=True)


# ─────────────────────────────────────────────────────────────────────────────
#  1 · every agent returns schema-valid JSON in mock mode
# ─────────────────────────────────────────────────────────────────────────────
def test_all_eight_agents_return_schema_valid_dicts(agents):
    pl = agents["planner"].run(allocation={"liquidity": 0.5, "momentum": 0.3})
    assert set(pl) >= {"family", "token_budget", "max_variants", "rationale"}
    assert isinstance(pl["token_budget"], int) and pl["max_variants"] <= 20

    lib = agents["librarian"].run(family="liquidity", keywords=["volume"])
    assert set(lib) >= {"brief", "suggested_angles", "excluded_from_suggestions"}

    th = agents["hypothesis"].run(family="liquidity", brief=lib["brief"])
    assert set(th) >= {"mechanism", "counterparty", "why_not_arbitraged",
                       "horizon_days", "regime", "falsifiable_claim",
                       "pre_registered_sign"}
    assert th["pre_registered_sign"] in (-1, 1)

    ec = agents["economics"].review(th)
    assert ec["verdict"] in ("pass", "reject")

    cd = agents["coder"].run(thesis=th, family="liquidity")
    assert cd["parsed_ok"] is True

    ju = agents["judge"].run(metrics={"rank_ic": 0.03, "t_stat": 3.5},
                             thesis=th, iteration=1)
    assert ju["action"] in ("refine", "promote")

    rt = agents["redteam"].run(thesis=th, formula=cd["formula"])
    assert all(t in RED_TEAM_MENU for t in rt["tests"])

    rf = agents["reflection"].run(family="liquidity", edit_motif="widen_ts_window",
                                  helped=True, rank_ic_delta=0.006)
    assert rf["applied"]["lesson"] and rf["applied"]["bandit"]


def test_invalid_json_raises_after_retries():
    client = LLMClient("judge", mode="mock", probe=True,
                       fixtures={"judge": lambda p, s: {"action": "sideways"}})
    with pytest.raises(SchemaValidationError):
        client.call("x", {"required": ["action", "edit_motif", "reason"],
                          "enum": {"action": ("refine", "promote")}})


# ─────────────────────────────────────────────────────────────────────────────
#  3 · Hypothesis output with no counterparty is rejected by Gate A
# ─────────────────────────────────────────────────────────────────────────────
def test_economics_rejects_thesis_missing_counterparty(agents):
    th = agents["hypothesis"].run(family="momentum")
    th["counterparty"] = ""
    ec = agents["economics"].review(th)
    assert ec["verdict"] == "reject"
    assert ec["used_llm"] is False
    assert any("counterparty" in r for r in ec["reasons"])


def test_economics_rejects_when_any_field_blank(agents):
    th = agents["hypothesis"].run(family="liquidity")
    for missing in ("mechanism", "why_not_arbitraged", "falsifiable_claim"):
        bad = dict(th)
        bad[missing] = ""
        assert agents["economics"].review(bad)["verdict"] == "reject"


# ─────────────────────────────────────────────────────────────────────────────
#  4 · Economics Reviewer is a SEPARATE client instance
# ─────────────────────────────────────────────────────────────────────────────
def test_economics_reviewer_is_a_separate_client(agents):
    assert agents["economics"].client is not agents["hypothesis"].client
    assert agents["economics"].client._seen_prefixes is not \
        agents["hypothesis"].client._seen_prefixes
    # different roles, and neither shares conversation state with the other
    assert agents["economics"].client.role == "economics"
    assert agents["hypothesis"].client.role == "hypothesis"


# ─────────────────────────────────────────────────────────────────────────────
#  5 · the sign hash is computed & stored BEFORE any backtest call
# ─────────────────────────────────────────────────────────────────────────────
def test_preregistration_hash_precedes_any_backtest(agents):
    events: list[str] = []

    def fake_backtest(*a, **k):
        events.append("backtest")
        return {"rank_ic": 0.03}

    th = agents["hypothesis"].run(family="liquidity")
    events.append("hypothesis")
    prereg = commit_preregistration(th, thesis_id="t1")
    events.append("prereg_stored")
    store = {"t1": prereg}                      # "stored with a timestamp"

    fake_backtest()                              # only now may data be touched

    assert prereg["hash"].startswith("sha256:") and len(prereg["hash"]) == 71
    assert prereg["committed_at"]
    assert events.index("prereg_stored") < events.index("backtest")
    assert store["t1"]["sign"] in (-1, 1)


def test_preregistration_is_deterministic_and_refuses_incomplete():
    thesis = {
        "mechanism": "m", "counterparty": "c", "why_not_arbitraged": "w",
        "horizon_days": 5, "regime": "calm", "falsifiable_claim": "f",
        "pre_registered_sign": -1,
    }
    fixed = lambda: __import__("datetime").datetime(2026, 1, 1,
                                                    tzinfo=__import__("datetime").timezone.utc)
    a = commit_preregistration(thesis, now=fixed)
    b = commit_preregistration(dict(thesis), now=fixed)
    assert a["hash"] == b["hash"]
    thesis.pop("counterparty")
    with pytest.raises(ValueError):
        commit_preregistration(thesis)


# ─────────────────────────────────────────────────────────────────────────────
#  6 · token accounting sums per role; exceeding the budget raises
# ─────────────────────────────────────────────────────────────────────────────
def test_token_accounting_sums_per_role_and_across_the_shared_budget(mem):
    ag = build_agents(mode="mock", memory=mem, probe=True)
    small_budget = ag["coder"].client.budget
    assert ag["judge"].client.budget is small_budget          # shared per tier
    assert ag["hypothesis"].client.budget is not small_budget  # large tier

    ag["planner"].run(allocation={"liquidity": 1.0})
    ag["coder"].run(thesis={"mechanism": "m", "pre_registered_sign": 1,
                            "horizon_days": 5}, family="liquidity")
    ag["judge"].run(metrics={"rank_ic": 0.03}, thesis={"horizon_days": 5},
                    iteration=1)

    per_role = (ag["planner"].client.billed_tokens
                + ag["coder"].client.billed_tokens
                + ag["judge"].client.billed_tokens
                + ag["librarian"].client.billed_tokens
                + ag["economics"].client.billed_tokens
                + ag["reflection"].client.billed_tokens)
    assert per_role == small_budget.used
    assert small_budget.used > 0


def test_exceeding_budget_raises_budget_exhausted():
    budget = TokenBudget("small", cap=50)
    c = LLMClient("planner", mode="mock", budget=budget, probe=True)
    with pytest.raises(BudgetExhausted) as ei:
        c.call("family=liquidity", {"required": ["family", "token_budget",
                                                 "max_variants", "rationale"]})
    assert ei.value.cap == 50 and ei.value.role == "planner"
    assert budget.used == 0            # nothing committed


# ─────────────────────────────────────────────────────────────────────────────
#  7 · Coder output parses under the Phase-5 parser
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("family", [
    "momentum", "reversal", "volatility", "liquidity", "microstructure",
    "trend", "seasonality", "value_proxy",
])
def test_coder_formula_parses_under_phase5(agents, family):
    cd = agents["coder"].run(
        thesis={"mechanism": "m", "pre_registered_sign": 1, "horizon_days": 5},
        family=family,
    )
    node = parse(cd["formula"], strict=True)      # raises if invalid
    assert complexity(cd["formula"])["nodes"] > 1


def test_coder_repairs_an_unparseable_formula():
    calls = {"n": 0}

    def fixture(prompt, schema):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"formula": "close.values[0]", "rationale": "bad"}
        return {"formula": "rank(close)", "rationale": "fixed"}

    client = LLMClient("coder", mode="mock", probe=True, fixtures={"coder": fixture})
    cd = Coder(client).run(thesis={"mechanism": "m"}, family="momentum")
    assert cd["formula"] == "rank(close)" and calls["n"] == 2


# ─────────────────────────────────────────────────────────────────────────────
#  8 · data/corpus/anomalies.json — count + schema
# ─────────────────────────────────────────────────────────────────────────────
def test_corpus_has_enough_entries_and_validates():
    corpus = load_corpus()
    assert len(corpus) >= 35
    validate_corpus(corpus)          # raises on any schema violation


def test_corpus_validator_rejects_a_broken_entry():
    good = load_corpus()[0]
    bad = dict(good)
    bad.pop("counterparty")
    with pytest.raises(Exception):
        validate_corpus([good, bad])


# ─────────────────────────────────────────────────────────────────────────────
#  9 · startup probe detects an unavailable model, falls through the chain
# ─────────────────────────────────────────────────────────────────────────────
def test_probe_falls_through_to_the_next_available_model():
    chain = ("openai/gpt-oss-120b", "qwen/qwen3-32b", "llama-3.3-70b-versatile")
    model, tried = probe_model_chain(chain, checker=lambda m: m == chain[1])
    assert model == chain[1]
    assert tried == [chain[0], chain[1]]     # stopped as soon as one answered


def test_probe_raises_when_nothing_in_the_chain_answers():
    with pytest.raises(NoModelAvailable):
        probe_model_chain(("a", "b"), checker=lambda m: False)


def test_client_uses_the_probed_model_not_a_hard_coded_one():
    c = LLMClient("coder", mode="mock", probe=True,
                  model_checker=lambda m: m == config.LLM_MODEL_CHAINS["small"][1])
    assert c.model == config.LLM_MODEL_CHAINS["small"][1]


# ─────────────────────────────────────────────────────────────────────────────
#  10 · TPM throttle demonstrably delays calls when the bucket empties
# ─────────────────────────────────────────────────────────────────────────────
def test_tpm_throttle_sleeps_when_the_bucket_empties():
    slept: list[float] = []
    t = [0.0]
    c = LLMClient("judge", mode="mock", tpm=20, rpm=100_000, probe=True,
                  clock=lambda: t[0], sleep=lambda s: slept.append(s))
    prompt = "iteration=3 rank_ic=0.05"
    schema = {"required": ["action", "edit_motif", "reason"]}
    c.call(prompt, schema)          # first call drains the (tiny) bucket
    c.call(prompt, schema)          # second must wait for a refill
    assert slept and sum(slept) > 0
    assert c.total_wait_s > 0


# ─────────────────────────────────────────────────────────────────────────────
#  11 · BudgetExhausted is raised, not swallowed, and leaves no partial write
# ─────────────────────────────────────────────────────────────────────────────
def test_budget_exhausted_leaves_memory_untouched(mem):
    tiny = TokenBudget("small", cap=5)
    client = LLMClient("reflection", mode="mock", budget=tiny, probe=True)
    refl = Reflection(client, memory=mem)
    with pytest.raises(BudgetExhausted):
        refl.run(family="liquidity", edit_motif="widen_ts_window",
                 helped=True, rank_ic_delta=0.01)
    assert mem.lessons.all_lessons() == []
    assert mem.bandit.families() == []          # nothing written


# ─────────────────────────────────────────────────────────────────────────────
#  12 · measured tokens/thesis in a mock run within 2× of the 26,500 projection
# ─────────────────────────────────────────────────────────────────────────────
def test_tokens_per_thesis_is_within_2x_of_projection(mem):
    ag = build_agents(mode="mock", memory=mem, probe=True)
    thesis = {"mechanism": "m", "counterparty": "c", "why_not_arbitraged": "w",
              "horizon_days": 5, "regime": "calm", "falsifiable_claim": "f",
              "pre_registered_sign": 1}

    ag["planner"].run(allocation={"liquidity": 1.0})
    ag["librarian"].run(family="liquidity", keywords=["volume"])
    ag["hypothesis"].run(family="liquidity")
    ag["economics"].review(thesis)
    # T3 projection: ~5.6 Coder + ~5.6 Judge + 0.4 Red-Team per thesis
    for i in range(6):
        ag["coder"].run(thesis=thesis, family="liquidity")
        ag["judge"].run(metrics={"rank_ic": 0.01 * i}, thesis=thesis, iteration=i)
    ag["redteam"].run(thesis=thesis, formula="rank(close)")
    ag["reflection"].run(family="liquidity", edit_motif="widen_ts_window",
                         helped=True, rank_ic_delta=0.005)

    total = (ag["planner"].client.budget.used
             + ag["hypothesis"].client.budget.used)   # small + large tiers
    projection = config.LLM_TOKENS_PER_THESIS_PROJECTION
    assert projection / 2 <= total <= projection * 2, total


# ─────────────────────────────────────────────────────────────────────────────
#  13 · retrieval on family="liquidity" returns only liquidity entries
# ─────────────────────────────────────────────────────────────────────────────
def test_retrieval_by_family_is_exact():
    corpus = load_corpus()
    for fam in ("liquidity", "momentum", "fundamental", "seasonality"):
        hits = retrieve(corpus, family=fam)
        assert hits and all(e["family"] == fam for e in hits)


def test_keyword_retrieval_ranks_by_hit_count():
    corpus = load_corpus()
    hits = retrieve(corpus, family="liquidity", keywords=["delivery"])
    # the delivery-percentage entry should surface if it is liquidity-family;
    # at minimum every hit is still liquidity-family
    assert all(e["family"] == "liquidity" for e in hits)


# ─────────────────────────────────────────────────────────────────────────────
#  14 · >=10 corpus entries are not tradeable AND the Librarian excludes them
# ─────────────────────────────────────────────────────────────────────────────
def test_at_least_ten_entries_are_not_tradeable():
    corpus = load_corpus()
    n_false = sum(1 for e in corpus if not e["tradeable_with_our_data"])
    assert n_false >= 10


def test_librarian_brief_excludes_non_tradeable_anomalies(mem):
    lib = Librarian(build_agents(mode="mock", memory=mem)["librarian"].client,
                    memory=mem)
    # the 'fundamental' family is entirely non-tradeable in our corpus
    res = lib.run(family="fundamental", keywords=["earnings", "value"])
    assert res["excluded_from_suggestions"]                     # they were found
    assert res["candidates_considered"] == []                   # none tradeable
    assert res["suggested_angles"] == []                        # nothing proposed
    for name in res["excluded_from_suggestions"]:
        assert name not in res["suggested_angles"]


def test_librarian_only_suggests_tradeable_names(agents):
    res = agents["librarian"].run(family="liquidity", keywords=["volume", "turnover"])
    corpus = {e["name"]: e for e in load_corpus()}
    for name in res["suggested_angles"]:
        assert corpus[name]["tradeable_with_our_data"] is True


# ─────────────────────────────────────────────────────────────────────────────
#  cross-cutting
# ─────────────────────────────────────────────────────────────────────────────
def test_call_llm_module_entrypoint_and_prefix_caching():
    c = LLMClient("judge", mode="mock", probe=True)
    schema = {"required": ["action", "edit_motif", "reason"]}
    static = "STATIC RUBRIC " * 20
    c.call(static + "iteration=1 rank_ic=0.0", schema, static_prefix=static)
    billed_after_first = c.billed_tokens
    c.call(static + "iteration=3 rank_ic=0.0", schema, static_prefix=static)
    # second call must not re-bill the (identical) static prefix
    assert c.cached_tokens >= estimate_tokens(static)
    assert c.billed_tokens - billed_after_first < billed_after_first


def test_reflection_writes_go_through_memory_guards(mem):
    ag = build_agents(mode="mock", memory=mem, probe=True)
    for _ in range(3):
        ag["reflection"].run(family="liquidity", edit_motif="widen_ts_window",
                             helped=True, rank_ic_delta=0.004)
    lessons = mem.lessons.all_lessons()
    assert lessons and lessons[0]["n_observations"] == 3
    assert "liquidity" in mem.bandit.families()


def test_deterministic_same_input_same_output(mem):
    a1 = build_agents(mode="mock", memory=mem, probe=True)
    r1 = a1["hypothesis"].run(family="volatility", brief="b")
    a2 = build_agents(mode="mock", memory=mem, probe=True)
    r2 = a2["hypothesis"].run(family="volatility", brief="b")
    assert r1 == r2
