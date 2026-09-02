"""Phase 8 · Agent 8 — Reflection.

Writes the lesson and the edit motif to memory (Phase 7 ②) and updates the
bandit priors (Phase 7 ③).  The LLM proposes the lesson text; the *writes* are
deterministic and go through the memory API's own guards (confidence gate,
sticky asymmetric veto, exploration floor).

Ordering matters: the LLM call happens first, so a :class:`BudgetExhausted`
raised there leaves memory **untouched** — no partial write to reconcile.
"""
from __future__ import annotations

import json

from .base import LLMClient, load_prompt

SCHEMA = {
    "required": ["lesson", "edit_motif", "bandit_update"],
    "types": {"lesson": dict, "edit_motif": str, "bandit_update": dict},
}


class Reflection:
    role = "reflection"

    def __init__(self, client: LLMClient, *, memory=None) -> None:
        self.client = client
        self.memory = memory
        self._static, self._dyn = load_prompt("reflection")

    def run(self, *, family: str, edit_motif: str, helped: bool,
            rank_ic_delta: float, parent_context: str = "",
            outcome: str = "", memory=None) -> dict:
        mem = memory if memory is not None else self.memory

        prompt = self._static + self._dyn.format(
            family=family,
            edit_motif=edit_motif,
            helped=str(bool(helped)),
            rank_ic_delta=round(float(rank_ic_delta), 4),
            parent_context=parent_context or f"{family} factor",
            outcome=outcome or "",
        )
        # LLM first — a BudgetExhausted here means nothing was written to memory.
        obj = self.client.call(prompt, SCHEMA, static_prefix=self._static)

        applied = {"lesson": False, "bandit": False}
        if mem is not None:
            lesson = obj["lesson"]
            try:
                mem.lessons.observe(
                    str(lesson.get("motif", edit_motif)),
                    helped=bool(lesson.get("helped", helped)),
                    confidence=float(lesson.get("confidence", 0.5)),
                    family=lesson.get("family", family),
                    parent_context=str(lesson.get("parent_context", parent_context)),
                    outcome=str(lesson.get("outcome", outcome)),
                )
                applied["lesson"] = True
            except Exception:
                pass
            bu = obj["bandit_update"]
            try:
                mem.bandit.update(
                    bu.get("family", family),
                    reward=float(bu.get("reward", rank_ic_delta)),
                    tokens=int(bu.get("tokens", 0)),
                    delta=float(bu.get("reward", rank_ic_delta)),
                )
                applied["bandit"] = True
            except Exception:
                pass

        obj["applied"] = applied
        return obj
