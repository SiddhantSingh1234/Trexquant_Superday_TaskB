"""Phase 8 — the eight LLM agent roles, their prompts, model routing and token
accounting.

Deterministic computations (the backtester, the statistics, the novelty check)
are **not** agents and live elsewhere — their verdicts cannot be talked around.

Public surface
--------------
* :func:`~src.agents.base.call_llm`        — the one call path (throttle, TPD,
  probe, mock)
* :class:`~src.agents.base.LLMClient`      — per-role client
* :class:`~src.agents.base.BudgetExhausted`— resumable hard stop
* :func:`build_agents`                     — all eight, wired, Economics on a
  SEPARATE client instance
* the eight agent classes
"""
from __future__ import annotations

from .base import (
    BudgetExhausted,
    LLMClient,
    NoModelAvailable,
    SchemaValidationError,
    TokenBudget,
    call_llm,
    estimate_tokens,
    probe_model_chain,
)
from .coder import Coder
from .economics import Economics
from .hypothesis import Hypothesis, commit_preregistration
from .judge import Judge
from .librarian import (
    Librarian,
    load_corpus,
    retrieve,
    validate_corpus,
)
from .planner import Planner
from .redteam import RED_TEAM_MENU, RedTeam
from .reflection import Reflection

__all__ = [
    "BudgetExhausted", "LLMClient", "NoModelAvailable", "SchemaValidationError",
    "TokenBudget", "call_llm", "estimate_tokens", "probe_model_chain",
    "Planner", "Librarian", "Hypothesis", "Economics", "Coder", "Judge",
    "RedTeam", "Reflection", "commit_preregistration",
    "load_corpus", "retrieve", "validate_corpus", "RED_TEAM_MENU",
    "build_agents",
]


def build_agents(
    *,
    mode: str | None = None,
    memory=None,
    probe: bool = True,
    large_budget: "TokenBudget | None" = None,
    small_budget: "TokenBudget | None" = None,
    **client_kw,
) -> dict:
    """Construct all eight agents with shared per-tier token budgets.

    The token budget is per *organisation* (PRE_BUILD_TASKS T3), so every
    small-tier role shares one :class:`TokenBudget` and every large-tier role
    shares another — that is what makes "TPD exhausted" a run-wide event.

    **The Economics Reviewer is given its own distinct :class:`LLMClient`**
    even though it shares the small tier — a different client object with no
    shared prompt-cache / conversation state, because "models grade their own
    work generously" (IMPLEMENTATION_PLAN.md Phase 8, agent 4).

    ``memory`` (a :class:`src.memory.Memory`) is passed to the Librarian and
    Reflection; both degrade gracefully to no-ops if it is ``None``.
    """
    from .. import config

    lb = large_budget or TokenBudget("large", cap=config.LLM_TPD_CAP["large"])
    sb = small_budget or TokenBudget("small", cap=config.LLM_TPD_CAP["small"])

    def mk(role: str) -> LLMClient:
        tier = config.LLM_ROLE_TIER[role]
        return LLMClient(
            role, mode=mode, probe=probe,
            budget=(lb if tier == "large" else sb),
            **client_kw,
        )

    return {
        "planner": Planner(mk("planner")),
        "librarian": Librarian(mk("librarian"), memory=memory),
        "hypothesis": Hypothesis(mk("hypothesis")),
        "economics": Economics(mk("economics")),
        "coder": Coder(mk("coder")),
        "judge": Judge(mk("judge")),
        "redteam": RedTeam(mk("redteam")),
        "reflection": Reflection(mk("reflection"), memory=memory),
    }
