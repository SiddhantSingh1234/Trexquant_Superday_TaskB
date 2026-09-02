"""Phase 8 · Agent 7 — Red-Team selector.

**It never writes code.**  It picks which of the fixed 11 stress tests
(Phase 9) fit this signal and returns ``{"tests": [str], "rationale": str}``.
Any name the model returns that is not on the menu is dropped here — the menu
is the contract, so every attack stays a pre-written, reproducible backtest.
"""
from __future__ import annotations

import json

from .base import LLMClient, load_prompt

# The fixed 11-test menu (IMPLEMENTATION_PLAN.md Phase 9).
RED_TEAM_MENU: tuple[str, ...] = (
    "subsample_year", "regime_split", "size_tercile", "cost_sweep",
    "extra_lag", "delivery_lag", "sector_neutral", "liquidity_filter",
    "decay_curve", "sign_stability", "universe_edge",
)

# A safe default battery if the model returns nothing usable.
_DEFAULT_TESTS = ("subsample_year", "regime_split", "extra_lag", "cost_sweep",
                  "decay_curve", "sign_stability")

SCHEMA = {
    "required": ["tests", "rationale"],
    "types": {"tests": list, "rationale": str},
}


class RedTeam:
    role = "redteam"

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self._static, self._dyn = load_prompt("redteam")

    def run(self, *, thesis: dict, formula: str, metrics: dict | None = None) -> dict:
        prompt = self._static + self._dyn.format(
            formula=formula,
            mechanism=thesis.get("mechanism", ""),
            horizon=thesis.get("horizon_days", 5),
            fields_used=json.dumps(_fields_in(formula)),
            menu=json.dumps(list(RED_TEAM_MENU)),
        )
        obj = self.client.call(prompt, SCHEMA, static_prefix=self._static)

        picked = [t for t in obj.get("tests", []) if t in RED_TEAM_MENU]
        dropped = [t for t in obj.get("tests", []) if t not in RED_TEAM_MENU]
        obj["tests"] = picked or list(_DEFAULT_TESTS)
        obj["dropped_off_menu"] = dropped
        return obj


def _fields_in(formula: str) -> list[str]:
    try:
        from ..ast_tools import _leaf_fields, parse

        return sorted(_leaf_fields(parse(formula, strict=False), set()))
    except Exception:
        return []
