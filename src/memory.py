"""Phase 7 — the six persistent memory stores.

"Memory" is **not one store**.  Five consumers have incompatible access
patterns, and one of them — P6's trial ledger, which feeds the Deflated Sharpe —
**must be exact and complete**, because a multiple-testing count cannot be
"approximately right".  So the exact stores and the semantic (fuzzy-retrieval)
store are kept **physically separate files**:

    data/memory.db        exact  — formula index, alpha-card index, lineage
    data/lessons.db       semantic — the edit-motif / lesson store
    data/bandit_state.json         — family budget allocator
    data/book.parquet              — the accepted factor book (real numbers)
    artifacts/cards/<id>.json      — one human-readable card per accepted signal
    data/ledger.db                 — P6 owns this; imported, never written here

The six stores (IMPLEMENTATION_PLAN.md Phase 7, steps ①–⑥):

  ① FormulaIndex   — dedupe: has this exact formula been tried? near-duplicates?
  ② LessonStore    — reusable "widening the window helped / hurt" knowledge
  ③ BanditState    — how much search budget each idea-family gets next
  ④ AlphaCardStore — the demo artifact: one readable JSON per card + an index
  ⑤ Lineage        — the parent pointer on each card (a tree, not a graph)
  ⑥ AcceptedBook   — date × symbol × factor values, for orthogonalisation

──────────────────────────────────────────────────────────────────────────────
⚠️  SECOND-ORDER OVERFITTING  — why ② and ③ have the guards they have
──────────────────────────────────────────────────────────────────────────────
If Reflection writes *"momentum ideas fail"* after **three** failures and the
Planner then defunds momentum, an irreversible decision has been made on n=3.
That is overfitting the *search process itself* — and it is invisible, because
it never shows up in any backtest.  The backtester scores signals, not the
policy that generated them.  Two defenses live here, and they are the **only**
defense:

  • **Confidence gating (②).**  A lesson is not returned as an applicable prior
    until ``n_observations >= LESSON_CONFIDENCE_GATE`` (3).  One or two data
    points never move the Planner.

  • **Asymmetric veto (②).**  A *failure* is stronger evidence than a *success*
    in a domain this noisy, so the two are treated asymmetrically:
      – **two** independent high-confidence failures (confidence ≥
        ``VETO_CONFIDENCE``) *hard-block* that motif **in that context**, once
        the confidence gate (``n_observations >= 3``) is also met.  Two, not one,
        so a single fluke cannot block; the gate, so it is never an n<3 call.
      – a success only *nudges the prior upward*, never creates a veto, and —
        critically — **never clears one**.  A veto is *sticky*: reversed only by
        an explicit ``clear_veto`` (a logged human / Planner decision).
    A veto is scoped to its ``context_key`` (default: the family) — the same
    motif is still free to be tried in a different context.

  • **Exploration floor (③).**  A family may be starved to
    ``EXPLORATION_FLOOR`` (5%) of the budget, **never to 0%**.  However badly a
    family has done, the loop keeps sampling it, so a premature "X always fails"
    verdict is self-correcting rather than terminal.

Retrieval (②) is **family + keyword filtering** — with a few hundred lessons
that is entirely sufficient.  There is deliberately **no vector database** and
no embedding model; see IMPLEMENTATION_PLAN.md Phase 7 "Do NOT".
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .config import (
    BANDIT_STATE_JSON,
    BOOK_PARQUET,
    CARDS_DIR,
    LESSONS_DB,
    MEMORY_DB,
    RANDOM_SEED,
)
from .contracts import CardSchemaError, make_fake_card, validate_card

__all__ = [
    "Memory", "FormulaIndex", "LessonStore", "BanditState", "AlphaCardStore",
    "AcceptedBook", "validate_card", "make_fake_card", "CardSchemaError",
    "new_card", "formula_hash", "init_memory", "FAMILIES",
    "LESSON_CONFIDENCE_GATE", "VETO_CONFIDENCE", "EXPLORATION_FLOOR",
]

try:  # ast_tools is Phase 5; degrade gracefully if a formula will not parse
    from .ast_tools import ParseError, canonical, complexity, fingerprint
except Exception:  # pragma: no cover - Phase 5 always present in this repo
    ParseError = Exception  # type: ignore

    def canonical(f, strict=False):  # type: ignore
        return str(f)

    def fingerprint(f, strict=False):  # type: ignore
        return _sha(str(f))[:16]

    def complexity(f, strict=False):  # type: ignore
        return {"nodes": 0, "depth": 0, "free_params": 0}


# Determinism (Section 0.6).  Only the bandit tie-breaks ever sample.
np.random.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)

# ── tuning constants (documented judgement calls — see reports/p7_handoff.md) ──
LESSON_CONFIDENCE_GATE: int = 3      # n_observations before a lesson is a prior
VETO_CONFIDENCE: float = 0.80        # a failure at/above this confidence "counts"
#                                     toward a veto; TWO of them (+ the gate) block
EXPLORATION_FLOOR: float = 0.05      # min budget share per family — never 0
BANDIT_TEMPERATURE: float = 0.50     # softmax temperature over mean family reward
BANDIT_LAST_K: int = 10              # rolling window kept in last_k_deltas


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def formula_hash(formula: str) -> str:
    """Content hash of a formula, **canonicalised first** so ``a*b`` and ``b*a``
    hash identically.  Falls back to the raw string if it will not parse."""
    try:
        key = canonical(formula, strict=False)
    except ParseError:
        key = str(formula).strip()
    return "sha256:" + _sha(key)


# ═════════════════════════════════════════════════════════════════════════════
#  A tiny SQLite base — mirrors src/ledger.py's connection discipline
# ═════════════════════════════════════════════════════════════════════════════
class _SqliteStore:
    _SCHEMA = ""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        # memory.db is opened by two stores (FormulaIndex + AlphaCardStore) on
        # separate connections; a 5 s busy-timeout removes the "database is
        # locked" race under the single-process P10 loop.
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()


# ═════════════════════════════════════════════════════════════════════════════
#  ①  Formula index  —  exact + fingerprint dedupe
# ═════════════════════════════════════════════════════════════════════════════
class FormulaIndex(_SqliteStore):
    """SQLite table ``formulas(formula_hash · canonical_ast · fingerprint ·
    first_seen · outcome)``.

    Two questions the Coder agent asks before spending a backtest:

    * :meth:`seen_exact` — *have we tried this exact formula already?*  (hash)
    * :meth:`candidates_by_fingerprint` — *what near-duplicates exist?*  The
      fingerprint (operator multiset + depth + leaf-field set, from
      ``ast_tools.fingerprint``) buckets structurally-similar formulas; a
      fingerprint match is escalated to a canonical-AST comparison by the caller.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS formulas (
        formula_hash  TEXT PRIMARY KEY,
        canonical_ast TEXT,
        fingerprint   TEXT,
        first_seen    TEXT NOT NULL,
        outcome       TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_formulas_fp ON formulas(fingerprint);
    """

    def record(self, formula: str, outcome: str | None = None) -> str:
        """Insert ``formula`` if new (keyed by canonical hash); return its hash.

        A repeat call with a new ``outcome`` updates the outcome but never the
        ``first_seen`` timestamp — the index is append-only in spirit.
        """
        h = formula_hash(formula)
        try:
            cast = canonical(formula, strict=False)
            fp = fingerprint(formula, strict=False)
        except ParseError:
            cast, fp = None, None
        row = self._conn.execute(
            "SELECT formula_hash FROM formulas WHERE formula_hash = ?", (h,)
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO formulas (formula_hash, canonical_ast, fingerprint, "
                "first_seen, outcome) VALUES (?,?,?,?,?)",
                (h, cast, fp, _now(), outcome),
            )
        elif outcome is not None:
            self._conn.execute(
                "UPDATE formulas SET outcome = ? WHERE formula_hash = ?",
                (outcome, h),
            )
        self._conn.commit()
        return h

    def set_outcome(self, formula_or_hash: str, outcome: str) -> None:
        h = formula_or_hash if str(formula_or_hash).startswith("sha256:") else formula_hash(formula_or_hash)
        self._conn.execute(
            "UPDATE formulas SET outcome = ? WHERE formula_hash = ?", (outcome, h)
        )
        self._conn.commit()

    def seen_exact(self, formula_or_hash: str) -> bool:
        h = formula_or_hash if str(formula_or_hash).startswith("sha256:") else formula_hash(formula_or_hash)
        return (
            self._conn.execute(
                "SELECT 1 FROM formulas WHERE formula_hash = ?", (h,)
            ).fetchone()
            is not None
        )

    def candidates_by_fingerprint(self, formula_or_fp: str) -> list[dict]:
        """Rows sharing a fingerprint with the argument (a formula string or a
        raw fingerprint).  Different fingerprint ⇒ provably not a duplicate."""
        if any(c in str(formula_or_fp) for c in "()+-*/ ,"):
            try:
                fp = fingerprint(formula_or_fp, strict=False)
            except ParseError:
                return []
        else:
            fp = str(formula_or_fp)
        return [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM formulas WHERE fingerprint = ? ORDER BY first_seen",
                (fp,),
            )
        ]

    def all_records(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM formulas ORDER BY first_seen")]


# ═════════════════════════════════════════════════════════════════════════════
#  ②  Lesson / edit-motif store  —  the semantic store (physically separate)
# ═════════════════════════════════════════════════════════════════════════════
class LessonStore(_SqliteStore):
    """Reusable knowledge of the form *"widening the ts window helped this kind
    of factor"*, with the two guards from the module docstring.

    A lesson is keyed by ``(motif, context_key)``.  ``context_key`` defaults to
    the ``family`` — so a veto learned for ``liquidity`` factors does not touch
    ``momentum`` factors.  Each :meth:`observe` call folds one new data point in:

      * ``n_observations`` increments; ``n_failures`` and ``n_conf_failures``
        (failures reported at confidence ≥ ``VETO_CONFIDENCE``) track the bad
        outcomes.
      * ``p_helps`` is an EWMA of the per-observation success signal
        (1.0 helped / 0.0 hurt) — the **direction** of the lesson.
      * ``confidence`` is *reliability regardless of direction*:
        ``|2·p_helps − 1| · (1 − 0.5**n_observations)`` — high when the evidence
        is both **one-sided** (consistently helps OR consistently hurts) and
        **plentiful**.  A motif that reliably *hurts* has a **high** confidence
        and a low ``p_helps``; the harm is not hidden behind a small number.

    Two guards (module docstring):

      * **Confidence gate** — :meth:`applicable_priors` never returns a lesson
        with ``n_observations < LESSON_CONFIDENCE_GATE`` (3).
      * **Asymmetric veto** — ``veto`` becomes ``True`` iff the gate is met
        **and** ``n_conf_failures >= 2`` (two independent high-confidence failure
        reports in the same context).  A lone confident failure among successes
        does **not** hard-block — that guards against a fluke.  Successes never
        set the veto and, crucially, **never clear it** (failures are the more
        reliable evidence): the block is *sticky*, lifted only by an explicit
        :meth:`clear_veto` — a logged human / Planner decision.  Reversibility of
        the *search* comes from the exploration floor in ③ (the family stays
        funded no matter how many motif-vetoes it accrues), not from eroding a
        veto.

    Retrieval is ``family`` + keyword substring matching.  No embeddings.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS lessons (
        lesson_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        motif           TEXT NOT NULL,
        context_key     TEXT NOT NULL,
        family          TEXT,
        parent_context  TEXT,
        outcome         TEXT,
        p_helps         REAL NOT NULL DEFAULT 0.5,
        confidence      REAL NOT NULL DEFAULT 0.0,
        n_observations  INTEGER NOT NULL DEFAULT 0,
        n_failures      INTEGER NOT NULL DEFAULT 0,
        n_conf_failures INTEGER NOT NULL DEFAULT 0,
        veto            INTEGER NOT NULL DEFAULT 0,
        veto_override   INTEGER,
        first_seen      TEXT NOT NULL,
        last_seen       TEXT NOT NULL,
        UNIQUE(motif, context_key)
    );
    CREATE INDEX IF NOT EXISTS ix_lessons_family ON lessons(family);
    """

    _EWMA_ALPHA = 0.5   # weight on the newest observation
    _MIN_CONF_FAILS_TO_VETO = 2

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        # defensive migration for a lessons.db created by an earlier schema
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(lessons)")}
        for col, decl in (
            ("veto_override", "INTEGER"),
            ("p_helps", "REAL NOT NULL DEFAULT 0.5"),
            ("confidence", "REAL NOT NULL DEFAULT 0.0"),
            ("n_conf_failures", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE lessons ADD COLUMN {col} {decl}")
        self._conn.commit()

    @staticmethod
    def _reliability(p_helps: float, n_obs: int) -> float:
        """Confidence in the lesson *whatever its direction*: one-sidedness ×
        maturity.  ~0 for a 50/50 or barely-seen motif; ~1 for a motif seen
        many times that always lands the same way."""
        consistency = abs(2.0 * p_helps - 1.0)
        maturity = 1.0 - 0.5 ** max(n_obs, 0)
        return float(consistency * maturity)

    def observe(
        self,
        motif: str,
        *,
        helped: bool,
        confidence: float,
        family: str | None = None,
        context_key: str | None = None,
        parent_context: str = "",
        outcome: str = "",
    ) -> dict:
        """Fold one observation of ``motif`` into the store and return the row.

        ``helped`` — did the edit improve the candidate?  ``confidence`` in
        [0, 1] — how sure the reporter is (Reflection's self-rated certainty).
        """
        confidence = float(min(max(confidence, 0.0), 1.0))
        ck = context_key or family or "global"
        now = _now()
        signal = 1.0 if helped else 0.0
        conf_fail = int((not helped) and confidence >= VETO_CONFIDENCE)
        cur = self._conn.execute(
            "SELECT * FROM lessons WHERE motif = ? AND context_key = ?", (motif, ck)
        ).fetchone()

        if cur is None:
            p_helps = signal
            n_obs, n_fail, n_cf = 1, (0 if helped else 1), conf_fail
            rel = self._reliability(p_helps, n_obs)
            veto = self._veto_rule(n_obs, n_cf)
            self._conn.execute(
                "INSERT INTO lessons (motif, context_key, family, parent_context, "
                "outcome, p_helps, confidence, n_observations, n_failures, "
                "n_conf_failures, veto, first_seen, last_seen) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (motif, ck, family, parent_context, outcome, p_helps, rel, n_obs,
                 n_fail, n_cf, int(veto), now, now),
            )
        else:
            a = self._EWMA_ALPHA
            p_helps = (1 - a) * cur["p_helps"] + a * signal
            n_obs = cur["n_observations"] + 1
            n_fail = cur["n_failures"] + (0 if helped else 1)
            n_cf = cur["n_conf_failures"] + conf_fail
            rel = self._reliability(p_helps, n_obs)
            override = cur["veto_override"]
            # sticky: once the rule has fired it stays fired until clear_veto();
            # an explicit override (0 or 1) wins over the rule entirely.
            if override is not None:
                veto = bool(override)
            else:
                veto = self._veto_rule(n_obs, n_cf) or bool(cur["veto"])
            self._conn.execute(
                "UPDATE lessons SET p_helps = ?, confidence = ?, n_observations = ?, "
                "n_failures = ?, n_conf_failures = ?, veto = ?, last_seen = ?, "
                "parent_context = COALESCE(NULLIF(?,''), parent_context), "
                "outcome = COALESCE(NULLIF(?,''), outcome), "
                "family = COALESCE(family, ?) WHERE motif = ? AND context_key = ?",
                (p_helps, rel, n_obs, n_fail, n_cf, int(veto), now, parent_context,
                 outcome, family, motif, ck),
            )
        self._conn.commit()
        return self.get(motif, ck)

    @classmethod
    def _veto_rule(cls, n_obs: int, n_conf_failures: int) -> bool:
        """Vetoed iff the confidence gate is met AND at least two independent
        high-confidence failures have been reported in this context.  Successes
        cannot trigger it; a single confident failure cannot either."""
        return (
            n_obs >= LESSON_CONFIDENCE_GATE
            and n_conf_failures >= cls._MIN_CONF_FAILS_TO_VETO
        )

    def clear_veto(self, motif: str, *, family: str | None = None,
                   context_key: str | None = None) -> None:
        """Explicit override: lift a veto and pin it off (the rule will not
        re-raise it).  This is the *only* way a veto is reversed — a human /
        Planner decision, logged, not an automatic consequence of a good run."""
        ck = context_key or family or "global"
        self._conn.execute(
            "UPDATE lessons SET veto = 0, veto_override = 0 "
            "WHERE motif = ? AND context_key = ?", (motif, ck),
        )
        self._conn.commit()

    def force_veto(self, motif: str, *, family: str | None = None,
                   context_key: str | None = None) -> None:
        """Explicit override the other way: hard-block a motif regardless of the
        observation count (a human 'never do this here')."""
        ck = context_key or family or "global"
        now = _now()
        row = self._conn.execute(
            "SELECT 1 FROM lessons WHERE motif = ? AND context_key = ?", (motif, ck)
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO lessons (motif, context_key, family, parent_context, "
                "outcome, p_helps, confidence, n_observations, n_failures, "
                "n_conf_failures, veto, veto_override, first_seen, last_seen) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (motif, ck, family, "", "forced (human override)", 0.0, 1.0,
                 0, 0, 0, 1, 1, now, now),
            )
        else:
            self._conn.execute(
                "UPDATE lessons SET veto = 1, veto_override = 1 "
                "WHERE motif = ? AND context_key = ?", (motif, ck),
            )
        self._conn.commit()

    def get(self, motif: str, context_key: str) -> dict:
        r = self._conn.execute(
            "SELECT * FROM lessons WHERE motif = ? AND context_key = ?",
            (motif, context_key),
        ).fetchone()
        return dict(r) if r else {}

    def is_vetoed(self, motif: str, *, family: str | None = None,
                  context_key: str | None = None) -> bool:
        """Is ``motif`` hard-blocked in this context?  A veto in one context
        does not bleed into another."""
        ck = context_key or family or "global"
        r = self._conn.execute(
            "SELECT veto FROM lessons WHERE motif = ? AND context_key = ?",
            (motif, ck),
        ).fetchone()
        return bool(r and r["veto"])

    def applicable_priors(
        self,
        *,
        family: str | None = None,
        keywords: Iterable[str] | None = None,
        context_key: str | None = None,
        include_vetoed: bool = False,
    ) -> list[dict]:
        """Lessons usable as a prior **right now**: confidence gate met
        (``n_observations >= LESSON_CONFIDENCE_GATE``) and not vetoed in the
        queried context.  Filtered by ``family`` and by case-insensitive keyword
        substring match against motif / parent_context / outcome.  Ordered
        most-likely-to-help first (``p_helps`` desc, then reliability) — a
        reliably-*harmful* motif that has not (yet) earned a veto still appears,
        at the bottom, with its low ``p_helps`` visible to the caller.
        """
        rows = [dict(r) for r in self._conn.execute("SELECT * FROM lessons")]
        out = []
        kw = [k.lower() for k in (keywords or [])]
        for r in rows:
            if r["n_observations"] < LESSON_CONFIDENCE_GATE:
                continue
            if family is not None and r["family"] != family:
                continue
            if context_key is not None and r["context_key"] != context_key:
                continue
            if not include_vetoed and r["veto"]:
                continue
            if kw:
                hay = " ".join(
                    str(r.get(c) or "") for c in ("motif", "parent_context", "outcome")
                ).lower()
                if not any(k in hay for k in kw):
                    continue
            out.append(r)
        out.sort(key=lambda r: (-r["p_helps"], -r["confidence"], -r["n_observations"]))
        return out

    def vetoed_motifs(self, *, family: str | None = None,
                      context_key: str | None = None) -> list[dict]:
        """Every hard-blocked (motif, context) — what the Planner must NOT try."""
        q = "SELECT * FROM lessons WHERE veto = 1"
        args: list[Any] = []
        if family is not None:
            q += " AND family = ?"
            args.append(family)
        if context_key is not None:
            q += " AND context_key = ?"
            args.append(context_key)
        return [dict(r) for r in self._conn.execute(q, args)]

    def all_lessons(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM lessons ORDER BY lesson_id")]


# ═════════════════════════════════════════════════════════════════════════════
#  ③  Bandit state  —  JSON, with the exploration floor
# ═════════════════════════════════════════════════════════════════════════════
class BanditState:
    """One JSON file, ~10 rows:
    ``family · n_pulls · cumulative_reward · tokens_spent · last_k_deltas``.

    :meth:`allocation` turns the accumulated reward into next-round budget
    shares via a softmax over **mean reward per family**, then clamps every
    share up to ``EXPLORATION_FLOOR`` and renormalises the remainder.  The floor
    is the guard against second-order overfitting (module docstring): a family
    that has failed 50 times in a row still receives 5% of the budget, so the
    loop can discover that the *earlier* failures were regime-specific rather
    than making an irreversible "this family is dead" decision.
    """

    def __init__(self, path: str | Path = BANDIT_STATE_JSON) -> None:
        self.path = Path(path)
        self._state: dict[str, dict] = {}
        if self.path.exists():
            self._state = json.loads(self.path.read_text(encoding="utf-8")).get(
                "families", {}
            )

    # -- persistence ----------------------------------------------------
    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "families": self._state,
            "exploration_floor": EXPLORATION_FLOOR,
            "updated_at": _now(),
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    # -- mutation -----------------------------------------------------
    def register_family(self, family: str) -> None:
        if family not in self._state:
            self._state[family] = {
                "family": family, "n_pulls": 0, "cumulative_reward": 0.0,
                "tokens_spent": 0, "last_k_deltas": [],
            }
            self._save()

    def update(self, family: str, reward: float, *, tokens: int = 0,
               delta: float | None = None) -> None:
        """Record one pull of ``family``: its ``reward`` (e.g. best RankIC gain,
        can be negative), the ``tokens`` it cost, and optionally the IC ``delta``
        it produced (appended to the rolling ``last_k_deltas`` window)."""
        self.register_family(family)
        row = self._state[family]
        row["n_pulls"] += 1
        row["cumulative_reward"] += float(reward)
        row["tokens_spent"] += int(tokens)
        d = float(reward if delta is None else delta)
        row["last_k_deltas"] = (row["last_k_deltas"] + [d])[-BANDIT_LAST_K:]
        self._save()

    # -- reads -------------------------------------------------------
    def mean_reward(self, family: str) -> float:
        row = self._state.get(family)
        if not row or row["n_pulls"] == 0:
            return 0.0
        return row["cumulative_reward"] / row["n_pulls"]

    def families(self) -> list[str]:
        return sorted(self._state)

    def row(self, family: str) -> dict:
        return dict(self._state.get(family, {}))

    def allocation(self) -> dict[str, float]:
        """Budget share per family for the next round.  Sums to 1.0; every value
        is ``>= EXPLORATION_FLOOR`` and therefore **strictly positive**."""
        fams = self.families()
        if not fams:
            return {}
        floor = EXPLORATION_FLOOR
        if len(fams) * floor >= 1.0:  # too many families for the floor — uniform
            return {f: 1.0 / len(fams) for f in fams}
        means = np.array([self.mean_reward(f) for f in fams], dtype=float)
        z = means / max(BANDIT_TEMPERATURE, 1e-6)
        z -= z.max()
        w = np.exp(z)
        w = w / w.sum()
        budget = 1.0 - floor * len(fams)
        alloc = {f: floor + budget * float(wi) for f, wi in zip(fams, w)}
        # guard against float drift so the contract (sum == 1) holds exactly
        s = sum(alloc.values())
        return {f: v / s for f, v in alloc.items()}


# ═════════════════════════════════════════════════════════════════════════════
#  Alpha-card  (Section 0.5)  — `validate_card` / `make_fake_card` live in
#  contracts.py (P0's artifact-validator home); imported at the top and
#  re-exported.  Below: the `new_card` builder and the exact card/lineage index.
# ═════════════════════════════════════════════════════════════════════════════
def new_card(
    card_id: str,
    thesis_id: str,
    formula: str,
    *,
    generation: int = 0,
    pre_registered_sign: int = 1,
    horizon_days: int = 5,
    parent_card_id: str | None = None,
    edit_motif: str | None = None,
    **overrides: Any,
) -> dict:
    """Build a schema-valid AlphaCard skeleton with sensible blanks.

    Convenience for tests / the loop — fills ``ast_canonical``, ``complexity``
    and ``provenance.fields_used`` from the formula, stamps the pre-registration
    hash, and leaves the metric blocks as empty dicts for Gate B to populate.
    """
    try:
        cast = canonical(formula, strict=False)
        cx = complexity(formula, strict=False)
        from .ast_tools import parse, _leaf_fields  # type: ignore

        fields = sorted(_leaf_fields(parse(formula, strict=False), set()))
    except Exception:
        cast, cx, fields = str(formula), {"nodes": 0, "depth": 0, "free_params": 0}, []
    committed = _now()
    card = {
        "card_id": card_id,
        "thesis_id": thesis_id,
        "generation": int(generation),
        "thesis": {
            "mechanism": "", "counterparty": "", "why_not_arbitraged": "",
            "horizon_days": int(horizon_days), "regime": "calm",
            "falsifiable_claim": "",
        },
        "pre_registered": {
            "sign": int(np.sign(pre_registered_sign) or 1),
            "horizon_days": int(horizon_days),
            "committed_at": committed,
            "hash": "sha256:" + _sha(
                json.dumps({"formula": cast, "sign": int(np.sign(pre_registered_sign) or 1),
                            "horizon_days": int(horizon_days), "committed_at": committed},
                           sort_keys=True)
            ),
        },
        "formula": formula,
        "ast_canonical": cast,
        "complexity": cx,
        "tier1_metrics": {}, "fresh_fold_metrics": {}, "tier2_metrics": {},
        "audit": {}, "redteam": {},
        "verdict": "provisional",
        "lineage": {"parent_card_id": parent_card_id, "edit_motif": edit_motif},
        "provenance": {"fields_used": fields},
    }
    card.update(overrides)
    return card


# ═════════════════════════════════════════════════════════════════════════════
#  ④  Alpha-card store  +  ⑤  Lineage   (both exact — live in memory.db)
# ═════════════════════════════════════════════════════════════════════════════
class AlphaCardStore(_SqliteStore):
    """One human-readable JSON per card in ``artifacts/cards/`` (the demo
    artifact) plus a SQLite index for fast filtering, and the lineage tree.

    ``card_index`` — ``card_id · thesis_id · verdict · rank_ic · marginal_ic ·
    generation · created_at``.
    ``lineage``    — ``card_id · parent_card_id · edit_motif``.  It is a *tree*:
    each card has at most one parent; :meth:`lineage_path` walks it to the root.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS card_index (
        card_id     TEXT PRIMARY KEY,
        thesis_id   TEXT,
        verdict     TEXT,
        rank_ic     REAL,
        marginal_ic REAL,
        generation  INTEGER,
        created_at  TEXT NOT NULL,
        path        TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS lineage (
        card_id        TEXT PRIMARY KEY,
        parent_card_id TEXT,
        edit_motif     TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_card_verdict ON card_index(verdict);
    CREATE INDEX IF NOT EXISTS ix_card_thesis  ON card_index(thesis_id);
    CREATE INDEX IF NOT EXISTS ix_lineage_parent ON lineage(parent_card_id);
    """

    def __init__(self, db_path: str | Path = MEMORY_DB,
                 cards_dir: str | Path = CARDS_DIR) -> None:
        super().__init__(db_path)
        self.cards_dir = Path(cards_dir)
        self.cards_dir.mkdir(parents=True, exist_ok=True)

    def save_card(self, card: dict, *, validate: bool = True) -> Path:
        """Validate, write ``artifacts/cards/<card_id>.json`` (pretty, stable key
        order) and upsert the index + lineage rows.  Returns the JSON path."""
        if validate:
            validate_card(card)
        cid = str(card["card_id"])
        path = self.cards_dir / f"{cid}.json"
        path.write_text(json.dumps(card, indent=2, sort_keys=True, default=str),
                        encoding="utf-8")

        t1 = card.get("tier1_metrics") or {}
        rank_ic = t1.get("rank_ic")
        if rank_ic is None:
            rank_ic = (card.get("fresh_fold_metrics") or {}).get("rank_ic")
        marg = (card.get("audit") or {}).get("marginal_ic")
        self._conn.execute(
            "INSERT INTO card_index (card_id, thesis_id, verdict, rank_ic, "
            "marginal_ic, generation, created_at, path) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(card_id) DO UPDATE SET thesis_id=excluded.thesis_id, "
            "verdict=excluded.verdict, rank_ic=excluded.rank_ic, "
            "marginal_ic=excluded.marginal_ic, generation=excluded.generation, "
            "path=excluded.path",
            (
                cid, card.get("thesis_id"), card.get("verdict"),
                _f(rank_ic), _f(marg),
                int(card.get("generation", 0) or 0), _now(), str(path),
            ),
        )
        lin = card.get("lineage") or {}
        self._conn.execute(
            "INSERT INTO lineage (card_id, parent_card_id, edit_motif) VALUES (?,?,?) "
            "ON CONFLICT(card_id) DO UPDATE SET parent_card_id=excluded.parent_card_id, "
            "edit_motif=excluded.edit_motif",
            (cid, lin.get("parent_card_id"), lin.get("edit_motif")),
        )
        self._conn.commit()
        return path

    def load_card(self, card_id: str) -> dict:
        path = self.cards_dir / f"{card_id}.json"
        if not path.exists():
            row = self._conn.execute(
                "SELECT path FROM card_index WHERE card_id = ?", (card_id,)
            ).fetchone()
            if row:
                path = Path(row["path"])
        if not path.exists():
            raise KeyError(f"no card {card_id!r}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_cards(self, *, verdict: str | None = None,
                   thesis_id: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM card_index", []
        clauses = []
        if verdict is not None:
            clauses.append("verdict = ?")
            args.append(verdict)
        if thesis_id is not None:
            clauses.append("thesis_id = ?")
            args.append(thesis_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created_at, card_id"
        return [dict(r) for r in self._conn.execute(q, args)]

    # -- ⑤ lineage ---------------------------------------------------
    def lineage_path(self, card_id: str) -> list[dict]:
        """Full card dicts from the root ancestor down to ``card_id`` inclusive.

        A missing ancestor JSON becomes a ``{"card_id":…, "missing":True}`` stub
        rather than an error.  Cycles (which a tree must not contain) are broken
        defensively and flagged.
        """
        chain: list[str] = []
        seen: set[str] = set()
        cur: str | None = card_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            row = self._conn.execute(
                "SELECT parent_card_id FROM lineage WHERE card_id = ?", (cur,)
            ).fetchone()
            cur = row["parent_card_id"] if row else None
        out: list[dict] = []
        for cid in reversed(chain):
            try:
                out.append(self.load_card(cid))
            except KeyError:
                out.append({"card_id": cid, "missing": True})
        if cur is not None:  # loop exited because of a cycle
            out.insert(0, {"card_id": cur, "cycle_detected": True})
        return out

    def children(self, card_id: str) -> list[str]:
        return [r["card_id"] for r in self._conn.execute(
            "SELECT card_id FROM lineage WHERE parent_card_id = ?", (card_id,))]


def _f(x: Any) -> float | None:
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


# ═════════════════════════════════════════════════════════════════════════════
#  ⑥  The accepted book  —  real date × symbol × factor numbers
# ═════════════════════════════════════════════════════════════════════════════
class AcceptedBook:
    """``data/book.parquet`` — the actual factor values of every accepted card,
    because orthogonalisation (Gate B step 1) needs *numbers*, not descriptions.

    Stored long: ``date · symbol · factor · value`` where ``factor`` is the
    ``card_id``.  That is exactly the shape ``gates._book_to_frames`` consumes,
    so ``get_book()`` can be handed straight to ``gate_b``.
    """

    _COLS = ("date", "symbol", "factor", "value")

    def __init__(self, path: str | Path = BOOK_PARQUET) -> None:
        self.path = Path(path)

    def _read(self) -> pd.DataFrame:
        if self.path.exists():
            df = pd.read_parquet(self.path)
        else:
            df = pd.DataFrame({c: pd.Series(dtype=t) for c, t in (
                ("date", "datetime64[ns]"), ("symbol", "object"),
                ("factor", "object"), ("value", "float64"))})
        return df

    def add_to_book(self, card_id: str, signal_df: pd.DataFrame) -> None:
        """Add (or replace) ``card_id``'s factor values.  ``signal_df`` may be
        wide (``date`` index × ``symbol`` columns) or long
        (``date, symbol, <value col>``)."""
        long = self._to_long(signal_df)
        long["factor"] = str(card_id)
        long = long[list(self._COLS)]
        book = self._read()
        book = book[book["factor"] != str(card_id)]
        book = pd.concat([book, long], ignore_index=True)
        book["date"] = pd.to_datetime(book["date"]).dt.normalize().astype("datetime64[ns]")
        book["symbol"] = book["symbol"].astype(str)
        book["factor"] = book["factor"].astype(str)
        book["value"] = book["value"].astype("float64")
        book = book.sort_values(["factor", "date", "symbol"]).reset_index(drop=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        book.to_parquet(self.path, index=False)

    def get_book(self) -> pd.DataFrame:
        """Long ``date · symbol · factor · value`` — feed directly to ``gate_b``."""
        return self._read()

    def get_book_wide(self) -> dict[str, pd.DataFrame]:
        """``{card_id: wide date × symbol frame}`` for callers that want pivots."""
        book = self._read()
        out = {}
        for name, grp in book.groupby("factor"):
            out[str(name)] = grp.pivot_table(index="date", columns="symbol", values="value")
        return out

    def factors(self) -> list[str]:
        return sorted(self._read()["factor"].astype(str).unique().tolist())

    @staticmethod
    def _to_long(signal_df: pd.DataFrame) -> pd.DataFrame:
        df = signal_df.copy()
        if {"date", "symbol"}.issubset(df.columns):
            vcols = [c for c in df.columns if c not in ("date", "symbol", "factor")]
            if len(vcols) != 1:
                raise ValueError(f"long signal needs exactly one value column, got {vcols}")
            df = df.rename(columns={vcols[0]: "value"})[["date", "symbol", "value"]]
        else:
            df = (
                df.rename_axis("date").reset_index()
                .melt(id_vars="date", var_name="symbol", value_name="value")
            )
        df = df.dropna(subset=["value"])
        return df


# ═════════════════════════════════════════════════════════════════════════════
#  Facade
# ═════════════════════════════════════════════════════════════════════════════
class Memory:
    """All six stores behind one object.

    ``m = Memory()`` opens the default on-disk stores; pass a ``base_dir`` to
    sandbox everything (tests).  The sub-stores are also usable standalone.
    """

    def __init__(self, base_dir: str | Path | None = None,
                 cards_dir: str | Path | None = None) -> None:
        if base_dir is None:
            mem_db, les_db = MEMORY_DB, LESSONS_DB
            bandit, book = BANDIT_STATE_JSON, BOOK_PARQUET
            cdir = Path(cards_dir) if cards_dir else CARDS_DIR
        else:
            base = Path(base_dir)
            base.mkdir(parents=True, exist_ok=True)
            mem_db, les_db = base / "memory.db", base / "lessons.db"
            bandit, book = base / "bandit_state.json", base / "book.parquet"
            cdir = Path(cards_dir) if cards_dir else base / "cards"

        self.formulas = FormulaIndex(mem_db)
        self.lessons = LessonStore(les_db)
        self.bandit = BanditState(bandit)
        self.cards = AlphaCardStore(mem_db, cdir)
        self.book = AcceptedBook(book)

    # lineage lives on the card store; expose it here for convenience
    def lineage_path(self, card_id: str) -> list[dict]:
        return self.cards.lineage_path(card_id)

    def add_to_book(self, card_id: str, signal_df: pd.DataFrame) -> None:
        self.book.add_to_book(card_id, signal_df)

    def get_book(self) -> pd.DataFrame:
        return self.book.get_book()

    def close(self) -> None:
        self.formulas.close()
        self.lessons.close()
        self.cards.close()


# ═════════════════════════════════════════════════════════════════════════════
#  One-shot creation of the on-disk deliverables
# ═════════════════════════════════════════════════════════════════════════════
def init_memory(base_dir: str | Path | None = None) -> dict[str, Path]:
    """Create ``data/memory.db``, ``data/lessons.db``, ``data/bandit_state.json``
    and ``artifacts/cards/`` with empty schemas / seed content (idempotent).

    The bandit is seeded with the ten idea-families so ``allocation()`` is
    meaningful on a fresh run; every family starts at the exploration floor.
    """
    m = Memory(base_dir)
    for fam in FAMILIES:
        m.bandit.register_family(fam)
    m.bandit._save()
    m.close()
    paths = {
        "memory_db": MEMORY_DB, "lessons_db": LESSONS_DB,
        "bandit_state": BANDIT_STATE_JSON, "cards_dir": CARDS_DIR,
    }
    return paths


#: The idea-families the bandit allocates across (INITIAL_PLAN / FLOW_EXPLAINED).
FAMILIES: tuple[str, ...] = (
    "momentum", "reversal", "volatility", "liquidity", "value_proxy",
    "microstructure", "seasonality", "quality_proxy", "sentiment_proxy", "trend",
)


if __name__ == "__main__":  # pragma: no cover
    p = init_memory()
    print("memory stores initialised:")
    for k, v in p.items():
        print(f"  {k:14s} {v}")
