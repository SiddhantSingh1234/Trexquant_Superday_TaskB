"""Phase 8 · Agent 4 — Economics Reviewer (Gate A).

Scores the thesis against the five-part rubric, **harshly**.  Missing any
element → reject, no LLM call needed (the structural check below).

> **Must run as a SEPARATE LLM instance from the Hypothesis agent** — a
> different client object, no shared conversation history.  Models grade their
> own work generously; separating author from judge removes a large bias
> cheaply.  ``build_agents`` gives this agent its own :class:`LLMClient`.
"""
from __future__ import annotations

import json

from .base import LLMClient, load_prompt

# The five rubric elements. Missing / blank any of these -> immediate reject.
RUBRIC = ("mechanism", "counterparty", "why_not_arbitraged",
          "falsifiable_claim", "horizon_days")

SCHEMA = {
    "required": ["verdict", "scores", "reasons"],
    "types": {"verdict": str, "scores": dict, "reasons": list},
    "enum": {"verdict": ("pass", "reject")},
}


class Economics:
    role = "economics"

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self._static, self._dyn = load_prompt("economics")

    def review(self, thesis: dict) -> dict:
        # ── structural gate: any missing rubric element is an automatic reject ──
        missing = [
            k for k in RUBRIC
            if k not in thesis or thesis.get(k) in (None, "", 0)
        ]
        if missing:
            return {
                "verdict": "reject",
                "scores": {k: 0 for k in RUBRIC},
                "reasons": [f"thesis is missing required element(s): {missing}"],
                "gate": "A",
                "used_llm": False,
            }

        prompt = self._static + self._dyn.format(
            thesis=json.dumps({k: thesis.get(k) for k in (
                "mechanism", "counterparty", "why_not_arbitraged",
                "horizon_days", "regime", "falsifiable_claim",
                "pre_registered_sign",
            )}, indent=0),
        )
        obj = self.client.call(prompt, SCHEMA, static_prefix=self._static)

        # a zero on any sub-score overrides a lenient 'pass'
        scores = obj.get("scores", {}) or {}
        if obj["verdict"] == "pass" and any(
            (isinstance(v, (int, float)) and v <= 0) for v in scores.values()
        ):
            obj["verdict"] = "reject"
            obj.setdefault("reasons", []).append(
                "a rubric sub-score was zero — rejected despite the summary verdict"
            )
        obj["gate"] = "A"
        obj["used_llm"] = True
        return obj

    # convenience alias
    run = review
