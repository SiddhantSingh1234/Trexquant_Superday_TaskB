"""Phase 8 · Agent 6 — Judge.

The Coder's critic inside the refinement loop.  Reads the quick-test metrics and
returns ``{"action": "refine"|"promote", "edit_motif": str, "reason": str}``.

Its real output is the **edit motif** — the *kind* of change to make ("widen the
window to match the stated horizon") — because that is the transferable
knowledge the memory stores.  Prompt is deliberately SHORT.
"""
from __future__ import annotations

from .base import LLMClient, load_prompt

SCHEMA = {
    "required": ["action", "edit_motif", "reason"],
    "types": {"action": str, "edit_motif": str, "reason": str},
    "enum": {"action": ("refine", "promote")},
}


class Judge:
    role = "judge"

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self._static, self._dyn = load_prompt("judge")

    def run(self, *, metrics: dict, thesis: dict, iteration: int) -> dict:
        prompt = self._static + self._dyn.format(
            rank_ic=round(float(metrics.get("rank_ic", 0.0)), 4),
            t_stat=round(float(metrics.get("t_stat", 0.0)), 2),
            icir=round(float(metrics.get("icir", 0.0)), 3),
            turnover=round(float(metrics.get("turnover", 0.0)), 3),
            iteration=int(iteration),
            horizon=int(thesis.get("horizon_days", 5)),
        )
        return self.client.call(prompt, SCHEMA, static_prefix=self._static)
