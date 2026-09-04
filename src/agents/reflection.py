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


def _as_float(v, default: float) -> float:
    """LLM payloads carry things like ``"0.0012 (small)"`` or ``None``; a bare
    ``float(v)`` raised and the caller's ``except: pass`` ate it."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _as_int(v, default: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return int(default)


def _as_bool(v, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1")
    return bool(default)


def _as_family(v, default: str) -> str:
    """Keep an invented family name out of the bandit — a hallucinated arm
    would take a permanent exploration-floor share of the budget."""
    try:
        from ..memory import FAMILIES
    except Exception:  # pragma: no cover
        return str(v or default)
    return str(v) if v in FAMILIES else str(default)


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

        applied = {"lesson": False, "bandit": False, "errors": []}
        if mem is not None:
            lesson = obj["lesson"]
            try:
                mem.lessons.observe(
                    str(lesson.get("motif", edit_motif)),
                    helped=_as_bool(lesson.get("helped"), helped),
                    confidence=_as_float(lesson.get("confidence"), 0.5),
                    family=_as_family(lesson.get("family"), family),
                    parent_context=str(lesson.get("parent_context", parent_context)),
                    outcome=str(lesson.get("outcome", outcome)),
                )
                applied["lesson"] = True
            except Exception as exc:  # noqa: BLE001
                applied["errors"].append(f"lessons.observe: {exc!r}")
            bu = obj["bandit_update"]
            # The bandit REWARD is deterministic — the caller's measured
            # rank_ic_delta — not whatever number the LLM felt like emitting.
            # A model-chosen reward is second-order overfitting, and a
            # non-numeric one used to fail silently and freeze the bandit.
            try:
                mem.bandit.update(
                    _as_family(bu.get("family"), family),
                    reward=float(rank_ic_delta),
                    tokens=_as_int(bu.get("tokens"), 0),
                    delta=float(rank_ic_delta),
                )
                applied["bandit"] = True
            except Exception as exc:  # noqa: BLE001
                applied["errors"].append(f"bandit.update: {exc!r}")

        obj["applied"] = applied
        return obj
