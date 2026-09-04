"""Phase 8 · Agent 5 — Coder.

Turns a thesis into a formula **string built only from the Phase-5 operator
library**.  The formula is parsed under the strict Phase-5 grammar before it is
returned; a formula that does not parse triggers one repair round, then a hard
error.  The Coder never evaluates or scores — that is the backtester's job.

Prompt is kept SHORT (Coder + Judge are ~11 of 16.6 calls/thesis).
"""
from __future__ import annotations

import json

from .base import LLMClient, load_prompt

try:  # Phase 5 — degrade gracefully if absent
    from ..ast_tools import ParseError, canonical, complexity, parse

    _HAVE_P5 = True
except Exception:  # pragma: no cover
    _HAVE_P5 = False
    ParseError = Exception  # type: ignore

    def parse(f, strict=True):  # type: ignore
        return f

    def canonical(f, strict=False):  # type: ignore
        return str(f)

    def complexity(f, strict=False):  # type: ignore
        return {"nodes": 0, "depth": 0, "free_params": 0}


SCHEMA = {
    "required": ["formula", "rationale"],
    "types": {"formula": str, "rationale": str},
}


class CoderError(ValueError):
    """The Coder could not produce a formula that parses under Phase 5."""


class Coder:
    role = "coder"

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self._static, self._dyn = load_prompt("coder")

    def _check(self, formula: str) -> None:
        if _HAVE_P5:
            parse(formula, strict=True)  # raises ParseError

    def run(self, *, thesis: dict, family: str,
            prior_formula: str | None = None,
            edit_motif: str | None = None,
            repair_hint: str | None = None,
            anchor: dict | None = None) -> dict:
        if anchor:
            anchor_txt = json.dumps(
                {k: anchor.get(k) for k in ("name", "mechanism", "horizon_days")},
                ensure_ascii=False,
            )
        else:
            anchor_txt = "(none — no anchor; write the thesis directly)"
        prompt = self._static + self._dyn.format(
            family=family,
            mechanism=thesis.get("mechanism", ""),
            horizon=thesis.get("horizon_days", 5),
            sign=thesis.get("pre_registered_sign", 1),
            prior_formula=prior_formula or "(none — first attempt)",
            edit_motif=edit_motif or "(none)",
            anchor=anchor_txt,
        )
        if repair_hint:
            # the previous formula parsed but would not evaluate (usually a wrong
            # operator arity or a missing `sector` arg) — feed the exact error back.
            prompt += (
                f"\n\nYour previous formula {prior_formula!r} PARSED but FAILED TO "
                f"EVALUATE: {repair_hint}. Return a corrected formula that respects "
                f"every operator's exact arg count and uses only the listed fields."
            )
        obj = self.client.call(prompt, SCHEMA, static_prefix=self._static)

        try:
            self._check(obj["formula"])
        except ParseError as exc:
            repair = prompt + (
                f"\n\nThe formula {obj['formula']!r} does not parse: {exc}. "
                f"Return a corrected formula using ONLY the listed operators "
                f"and fields."
            )
            obj = self.client.call(repair, SCHEMA, static_prefix=self._static)
            try:
                self._check(obj["formula"])
            except ParseError as exc2:
                raise CoderError(
                    f"formula still invalid after repair: {obj['formula']!r} "
                    f"({exc2})"
                ) from exc2

        obj["parsed_ok"] = True
        if _HAVE_P5:
            obj["ast_canonical"] = canonical(obj["formula"], strict=False)
            obj["complexity"] = complexity(obj["formula"], strict=False)
        return obj
