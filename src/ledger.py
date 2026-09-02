"""Phase 6 — the trial ledger.

An **append-only** SQLite store of every backtest that was ever run in anger,
plus the rationed HOLDOUT-peek log.  It exists for one reason: the Deflated
Sharpe Ratio and every other multiple-testing correction needs an *honest*,
*complete* count of how many times we looked.  If a row could be removed, that
count would be gameable and the deflation meaningless — so this module contains
**no row-removal SQL of any kind** (there is a test that greps for it).

Two tables (IMPLEMENTATION_PLAN.md Phase 6, step 1):

    trials(trial_id, thesis_id, formula_hash, canonical_ast, timestamp,
           split_used, rank_ic, sharpe, t_stat, n_days,
           counts_as_trial, rejection_reason)
    holdout_peeks(peek_id, card_id, timestamp, result_json)

The selection-vs-rejection distinction — implemented precisely
--------------------------------------------------------------
A run only inflates the false-discovery rate if it is used to **pick a winner**.

* Quick screening across formula variants is *selection* → ``counts_as_trial=1``.
* Red-team stress tests, cost sweeps and lag tests can only ever **kill** a
  candidate, never promote it.  A filter that only rejects cannot raise the
  false-discovery rate, so those are *rejection-only* → ``counts_as_trial=0``.

``n_trials`` / ``trial_sharpes`` / ``trial_irs`` count **only** the
``counts_as_trial=1`` rows — that is the number the statistics gate is allowed
to see.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import HOLDOUT_PEEK_BUDGET, LEDGER_DB

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    trial_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id       TEXT,
    formula_hash    TEXT,
    canonical_ast   TEXT,
    timestamp       TEXT NOT NULL,
    split_used      TEXT,
    rank_ic         REAL,
    sharpe          REAL,
    t_stat          REAL,
    n_days          INTEGER,
    counts_as_trial INTEGER NOT NULL DEFAULT 1,
    rejection_reason TEXT
);
CREATE TABLE IF NOT EXISTS holdout_peeks (
    peek_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     TEXT,
    timestamp   TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trials_thesis ON trials(thesis_id);
CREATE INDEX IF NOT EXISTS ix_trials_counts ON trials(counts_as_trial);
"""

# Guard: this source file must never contain a row-removal statement.  The token
# is spelled indirectly here so the guard test (which greps the raw file) does
# not trip on its own explanatory comment.
_FORBIDDEN_SQL = ("delete", "drop table", "truncate")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _f(x: Any) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else x


class Ledger:
    """Append-only trial ledger backed by SQLite at ``db_path``.

    Safe to open many times against the same file; the schema is created if
    absent and never altered.  Use as a context manager or call :meth:`close`.
    """

    def __init__(self, db_path: str | Path = LEDGER_DB) -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    # -- trials ----------------------------------------------------------
    def record_trial(
        self,
        thesis_id: str | None,
        formula_hash: str | None,
        canonical_ast: str | None,
        split_used: str | None,
        rank_ic: float | None,
        sharpe: float | None,
        t_stat: float | None,
        n_days: int | None,
        counts_as_trial: int = 1,
        rejection_reason: str | None = None,
    ) -> int:
        """Append one trial row and return its ``trial_id``.

        ``counts_as_trial`` is coerced to ``0`` or ``1``.  Pass ``1`` for a
        selection run (variant screening); pass ``0`` for a rejection-only run
        (red-team stress, cost sweep, lag test) — see the module docstring.
        """
        counts = 1 if int(counts_as_trial) != 0 else 0
        cur = self._conn.execute(
            "INSERT INTO trials (thesis_id, formula_hash, canonical_ast, timestamp, "
            "split_used, rank_ic, sharpe, t_stat, n_days, counts_as_trial, "
            "rejection_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                thesis_id, formula_hash, canonical_ast, _now(), split_used,
                _f(rank_ic), _f(sharpe), _f(t_stat),
                None if n_days is None else int(n_days),
                counts, rejection_reason,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def _select_trials(self, thesis_id: str | None, counts_only: bool) -> list[sqlite3.Row]:
        q = "SELECT * FROM trials"
        clauses, args = [], []
        if counts_only:
            clauses.append("counts_as_trial = 1")
        if thesis_id is not None:
            clauses.append("thesis_id = ?")
            args.append(thesis_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY trial_id"
        return list(self._conn.execute(q, args))

    def n_trials(self, thesis_id: str | None = None) -> int:
        """Number of **selection** trials (``counts_as_trial=1``), global or per thesis."""
        return len(self._select_trials(thesis_id, counts_only=True))

    def trial_sharpes(self, thesis_id: str | None = None) -> list[float]:
        """The annualised Sharpe of every selection trial (NaNs dropped)."""
        return [
            r["sharpe"] for r in self._select_trials(thesis_id, counts_only=True)
            if r["sharpe"] is not None
        ]

    def trial_irs(self, thesis_id: str | None = None) -> list[float]:
        """Per-period information ratio (``t_stat / sqrt(n_days)``) of every
        selection trial — the trial-SR sample the Deflated Sharpe deflates by."""
        out = []
        for r in self._select_trials(thesis_id, counts_only=True):
            if r["t_stat"] is None or not r["n_days"]:
                continue
            out.append(float(r["t_stat"]) / math.sqrt(float(r["n_days"])))
        return out

    def trial_records(
        self, thesis_id: str | None = None, counts_only: bool = True
    ) -> list[dict]:
        return [dict(r) for r in self._select_trials(thesis_id, counts_only)]

    def trial_canonical_asts(self, thesis_id: str | None = None) -> list[str]:
        return [
            r["canonical_ast"] for r in self._select_trials(thesis_id, counts_only=True)
            if r["canonical_ast"]
        ]

    # -- rationed HOLDOUT peeks -----------------------------------------
    def holdout_peeks_used(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM holdout_peeks").fetchone()[0])

    def holdout_peeks_remaining(self) -> int:
        return max(0, HOLDOUT_PEEK_BUDGET - self.holdout_peeks_used())

    def request_holdout_peek(self, card_id: str) -> dict | None:
        """Reserve one HOLDOUT peek and return a token, or ``None`` once the
        budget (``HOLDOUT_PEEK_BUDGET``) is spent — **forever**.

        The token is a dict ``{"peek_id", "card_id", "i_have_a_peek_token": True}``.
        Pass ``i_have_a_peek_token=True`` on to ``backtester.backtest`` and then
        hand the token to :meth:`finalize_holdout_peek` with the result.
        The row is written *now* (status ``reserved``); reserving is what spends
        the budget, so an abandoned token still counts.
        """
        if self.holdout_peeks_used() >= HOLDOUT_PEEK_BUDGET:
            return None
        cur = self._conn.execute(
            "INSERT INTO holdout_peeks (card_id, timestamp, result_json) VALUES (?,?,?)",
            (card_id, _now(), json.dumps({"status": "reserved"})),
        )
        self._conn.commit()
        return {
            "peek_id": int(cur.lastrowid),
            "card_id": card_id,
            "i_have_a_peek_token": True,
        }

    def finalize_holdout_peek(self, token: dict, result: dict) -> None:
        """Attach the peek result to its reserved row (an UPDATE — the row is
        never removed, only filled in)."""
        peek_id = int(token["peek_id"])
        payload = json.dumps({"status": "used", **result}, default=str)
        self._conn.execute(
            "UPDATE holdout_peeks SET result_json = ? WHERE peek_id = ?",
            (payload, peek_id),
        )
        self._conn.commit()

    def holdout_peek_records(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM holdout_peeks ORDER BY peek_id"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["result"] = json.loads(d.pop("result_json"))
            except (ValueError, TypeError):
                d["result"] = {}
            out.append(d)
        return out


# --------------------------------------------------------------------------- #
# Self-audit + one-shot DB creation                                            #
# --------------------------------------------------------------------------- #
def assert_no_row_removal_sql(module_path: str | Path | None = None) -> None:
    """Raise if this source file contains a row-removal statement.

    The ledger's integrity guarantee is that trials cannot be un-counted.  It is
    asserted structurally (the file is scanned) rather than trusted.  Only the
    tuple that *names* the forbidden tokens for this check, and pure comments,
    are exempt.
    """
    path = Path(module_path) if module_path else Path(__file__)
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, raw in enumerate(lines, start=1):
        line = raw.strip()
        if line.startswith("#") or line.startswith("_FORBIDDEN_SQL"):
            continue
        low = line.lower()
        for tok in _FORBIDDEN_SQL:
            if tok in low:
                raise AssertionError(
                    f"{path.name}:{i} contains forbidden SQL {tok!r}: {line!r}"
                )


def init_ledger_db(db_path: str | Path = LEDGER_DB) -> Path:
    """Create ``data/ledger.db`` with the empty schema (idempotent)."""
    led = Ledger(db_path)
    led.close()
    return Path(db_path)


if __name__ == "__main__":  # pragma: no cover
    assert_no_row_removal_sql()
    p = init_ledger_db()
    print(f"ledger schema written to {p}")
