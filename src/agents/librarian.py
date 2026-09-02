"""Phase 8 · Agent 2 — Librarian (brief writer).

Two jobs, and the second matters more:

1. Retrieve corpus anomalies that match the requested family / keywords.
2. Pull **past lessons from memory** so the system does not re-propose the idea
   it killed three generations ago.

Retrieval is **keyword + family filtering** — with ~40 corpus entries and a few
hundred lessons that is entirely sufficient.  No embeddings, no vector database
(IMPLEMENTATION_PLAN.md Phase 7/8 "Do NOT").

The ``tradeable_with_our_data`` flag is load-bearing: an anomaly that needs
fundamentals / short interest / options is put in ``excluded_from_suggestions``
by **deterministic code** (not the LLM), so the Hypothesis agent is told *"real
anomaly, but we have no data — do not propose it"* and no tokens are burned on
an idea we structurally cannot implement.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import config
from .base import LLMClient, load_prompt

# ── corpus schema ───────────────────────────────────────────────────────────
CORPUS_REQUIRED_KEYS = (
    "name", "family", "mechanism", "counterparty", "horizon_days",
    "evidence", "known_decay", "tradeable_with_our_data",
)
CORPUS_FAMILIES = frozenset({
    "momentum", "reversal", "volatility", "liquidity", "microstructure",
    "seasonality", "trend", "fundamental", "sentiment", "size",
})


class CorpusError(ValueError):
    """`data/corpus/anomalies.json` violated its schema."""


def load_corpus(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else Path(config.ANOMALIES_JSON)
    data = json.loads(p.read_text(encoding="utf-8"))
    entries = data["anomalies"] if isinstance(data, dict) else data
    validate_corpus(entries)
    return entries


def validate_corpus(entries: list[dict]) -> None:
    if not isinstance(entries, list) or not entries:
        raise CorpusError("corpus must be a non-empty list of anomaly objects")
    seen: set[str] = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise CorpusError(f"entry {i} is not an object")
        for k in CORPUS_REQUIRED_KEYS:
            if k not in e:
                raise CorpusError(f"entry {i} ({e.get('name','?')}) missing key {k!r}")
        if not isinstance(e["tradeable_with_our_data"], bool):
            raise CorpusError(
                f"entry {e['name']!r}: tradeable_with_our_data must be bool"
            )
        if e["family"] not in CORPUS_FAMILIES:
            raise CorpusError(
                f"entry {e['name']!r}: family {e['family']!r} not in "
                f"{sorted(CORPUS_FAMILIES)}"
            )
        if e["name"] in seen:
            raise CorpusError(f"duplicate anomaly name {e['name']!r}")
        seen.add(e["name"])


def retrieve(entries: list[dict], *, family: str | None = None,
             keywords: list[str] | None = None, limit: int = 12) -> list[dict]:
    """Family filter (exact, case-insensitive) then keyword ranking.

    Different family ⇒ excluded.  With a family and no keyword the whole family
    is returned (up to ``limit``); with keywords, entries are ranked by hit
    count against name/mechanism/counterparty/evidence/known_decay.
    """
    kw = [k.lower() for k in (keywords or []) if k]
    pool = entries
    if family is not None:
        fam = family.lower()
        pool = [e for e in pool if e["family"].lower() == fam]
    if not kw:
        return pool[:limit]

    def score(e: dict) -> int:
        hay = " ".join(str(e.get(c, "")) for c in (
            "name", "mechanism", "counterparty", "evidence", "known_decay"
        )).lower()
        return sum(1 for k in kw if k in hay)

    ranked = sorted(pool, key=score, reverse=True)
    ranked = [e for e in ranked if score(e) > 0] or pool
    return ranked[:limit]


SCHEMA = {
    "required": ["brief", "suggested_angles", "rationale"],
    "types": {"brief": str, "suggested_angles": list, "rationale": str},
}


class Librarian:
    role = "librarian"

    def __init__(self, client: LLMClient, *, memory=None) -> None:
        self.client = client
        self.memory = memory
        self._static, self._dyn = load_prompt("librarian")

    def run(self, *, family: str, keywords: list[str] | None = None,
            corpus: list[dict] | None = None) -> dict:
        entries = corpus if corpus is not None else load_corpus()
        hits = retrieve(entries, family=family, keywords=keywords)
        tradeable = [e for e in hits if e["tradeable_with_our_data"]]
        excluded = [e["name"] for e in hits if not e["tradeable_with_our_data"]]

        lessons, vetoed = [], []
        if self.memory is not None:
            try:
                lessons = self.memory.lessons.applicable_priors(
                    family=family, keywords=keywords
                )
                vetoed = [v["motif"] for v in
                          self.memory.lessons.vetoed_motifs(family=family)]
            except Exception:  # memory optional / not yet populated
                lessons, vetoed = [], []

        tradeable_view = [
            {k: e[k] for k in ("name", "mechanism", "counterparty", "horizon_days")}
            for e in tradeable
        ]
        prompt = self._static + self._dyn.format(
            family=family,
            tradeable=json.dumps(tradeable_view),
            excluded=json.dumps(excluded),
            lessons=json.dumps([
                {"motif": l["motif"], "p_helps": round(l["p_helps"], 2),
                 "outcome": l.get("outcome", "")}
                for l in lessons
            ]),
            vetoed=json.dumps(vetoed),
        )
        obj = self.client.call(prompt, SCHEMA, static_prefix=self._static)

        # deterministic post-conditions the LLM does not get to override
        candidate_names = {e["name"] for e in tradeable}
        obj["suggested_angles"] = [
            a for a in obj.get("suggested_angles", []) if a in candidate_names
        ]
        obj["candidates_considered"] = sorted(candidate_names)
        obj["excluded_from_suggestions"] = excluded
        obj["lessons_recalled"] = [l["motif"] for l in lessons]
        obj["vetoed_motifs"] = vetoed
        return obj
