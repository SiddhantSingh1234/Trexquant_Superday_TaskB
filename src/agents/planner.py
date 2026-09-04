"""Phase 8 · Agent 1 — Planner.

Picks the next idea-family and its budget.  The **bandit (Phase 7) does the
arithmetic**; the LLM's job is to propose genuinely new families and to cross
elite theses.  This wrapper keeps the deterministic parts deterministic: it
computes the bandit allocation itself, hands the LLM the numbers, and clamps
``max_variants`` to ``MAX_VARIANTS_PER_THESIS``.
"""
from __future__ import annotations

import json

from .. import config
from .base import LLMClient, load_prompt

SCHEMA = {
    "required": ["family", "token_budget", "max_variants", "rationale"],
    "types": {"family": str, "token_budget": int, "max_variants": int,
              "rationale": str},
    "defaults": {"max_variants": config.MAX_VARIANTS_PER_THESIS},
}


class Planner:
    role = "planner"

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self._static, self._dyn = load_prompt("planner")

    def run(self, *, allocation: dict | None = None,
            elite_theses: list[str] | None = None,
            total_token_budget: int = 400_000,
            top_family: str | None = None,
            pulls: dict | None = None,
            tried_this_run: list[str] | None = None) -> dict:
        allocation = allocation or {}
        # ``top_family`` comes from BanditState.suggest, which breaks the
        # all-equal-allocation tie properly.  Falling back to max() here would
        # reintroduce the degenerate "always the first key" pick.
        if top_family is None:
            top_family = (
                max(allocation, key=allocation.get) if allocation else "liquidity"
            )
        prompt = self._static + self._dyn.format(
            top_family=top_family,
            allocation=json.dumps(allocation, sort_keys=True),
            pulls=json.dumps(pulls or {}, sort_keys=True),
            tried=json.dumps(tried_this_run or []),
            elite=json.dumps(elite_theses or []),
            total_budget=int(total_token_budget),
            max_variants=config.MAX_VARIANTS_PER_THESIS,
        )
        obj = self.client.call(prompt, SCHEMA, static_prefix=self._static)
        obj["max_variants"] = min(int(obj["max_variants"]),
                                  config.MAX_VARIANTS_PER_THESIS)
        obj["token_budget"] = max(1, int(obj["token_budget"]))
        return obj
