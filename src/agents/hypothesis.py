"""Phase 8 · Agent 3 — Hypothesis (the researcher) + pre-registration.

The most important creative step, and the home of the project's headline
mechanism: **the pre-registered sign**.

The agent commits to the *direction* of the effect BEFORE any data is touched.
:func:`commit_preregistration` serializes the thesis, ``sha256``-es it and stamps
a timestamp — and that hash must be stored **before any backtest runs**.  Later,
the realized RankIC sign must match the committed one, or the idea is rejected
as a *thesis failure* — not silently flipped and kept.  Every factor ``f`` has a
mirror ``-f``; without pre-commitment you test both and report one, and an LLM
shown the result first will narrate a mechanism for whatever the data did.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Callable

from .base import LLMClient, load_prompt

_THESIS_KEYS = (
    "mechanism", "counterparty", "why_not_arbitraged", "horizon_days",
    "regime", "falsifiable_claim", "pre_registered_sign",
)

SCHEMA = {
    "required": list(_THESIS_KEYS),
    "types": {
        "mechanism": str, "counterparty": str, "why_not_arbitraged": str,
        "horizon_days": int, "regime": str, "falsifiable_claim": str,
        "pre_registered_sign": int,
    },
    "enum": {"pre_registered_sign": (-1, 1)},
}


class Hypothesis:
    role = "hypothesis"

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self._static, self._dyn = load_prompt("hypothesis")

    def run(self, *, family: str, brief: str = "", horizon_hint: int = 5,
            avoid: list[str] | None = None) -> dict:
        prompt = self._static + self._dyn.format(
            family=family,
            brief=brief or "(no brief)",
            horizon_hint=int(horizon_hint),
            avoid=json.dumps(avoid or []),
        )
        obj = self.client.call(prompt, SCHEMA, static_prefix=self._static)
        if int(obj["pre_registered_sign"]) not in (-1, 1):
            raise ValueError("pre_registered_sign must be -1 or +1")
        obj["horizon_days"] = int(obj["horizon_days"])
        return obj


def _canonical_thesis(thesis: dict) -> dict:
    out = {}
    for k in _THESIS_KEYS:
        if k not in thesis or thesis[k] in (None, ""):
            raise ValueError(f"cannot pre-register: thesis missing {k!r}")
        out[k] = thesis[k]
    out["horizon_days"] = int(out["horizon_days"])
    out["pre_registered_sign"] = int(out["pre_registered_sign"])
    return out


def commit_preregistration(
    thesis: dict, *, thesis_id: str | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict:
    """Freeze the thesis: canonical JSON → sha256 → timestamp.

    Returns the block that goes into ``AlphaCard.pre_registered`` (Section 0.5)
    plus ``payload`` (the exact bytes hashed, for audit).  **Call this and store
    the result before the first backtest.**
    """
    payload = _canonical_thesis(thesis)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    ts = (now or (lambda: datetime.now(timezone.utc)))()
    return {
        "sign": payload["pre_registered_sign"],
        "horizon_days": payload["horizon_days"],
        "committed_at": ts.isoformat(timespec="seconds"),
        "hash": "sha256:" + digest,
        "thesis_id": thesis_id,
        "payload": payload,
    }


def sign_matches(prereg: dict, realized_rank_ic: float) -> bool:
    """The pre-registration test: does the realized direction match the
    committed one?  A mismatch is a **thesis failure**, not a sign flip."""
    realized_sign = 1 if realized_rank_ic > 0 else -1
    return int(prereg["sign"]) == realized_sign
