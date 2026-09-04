"""Data-access layer for the dashboard (DASHBOARD_PLAN.md Section 0.4).

Two jobs:
  1. the cache layer — read the small precomputed parquets D1 writes into
     ``data/dashboard/`` plus their manifest.
  2. sliced / columnar readers for the big project artifacts — no reader ever
     pulls a full ``ohlcv``/``features``/``labels`` parquet into pandas.

Concurrency (Section 0.8.1): every SQLite read goes through ``_readonly_sqlite``
(snapshot-then-open); ``load_bandit`` tolerates a truncated JSON; a partially
written card is skipped.

This module must NOT import ``src.*`` (asserted by the D0 test) — it discovers
project paths by walking up from ``__file__``.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import streamlit as st

# --------------------------------------------------------------------------- #
# Paths                                                                        #
# --------------------------------------------------------------------------- #
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = PROJECT_ROOT / "data"
CACHE_DIR: Path = DATA_DIR / "dashboard"
REPORTS_DIR: Path = PROJECT_ROOT / "reports"
ARTIFACTS_DIR: Path = PROJECT_ROOT / "artifacts"
_SNAP_DIR: Path = CACHE_DIR / "_snap"

# Big parquets that must never be read whole.
_OHLCV = DATA_DIR / "prices" / "ohlcv.parquet"
_FEATURES = DATA_DIR / "panel" / "features.parquet"
_LABELS = DATA_DIR / "panel" / "labels.parquet"
_BIG_FILES = {_OHLCV, _FEATURES, _LABELS}
_BIG_ROW_THRESHOLD = 250_000


# --------------------------------------------------------------------------- #
# Read-only SQLite (Section 0.8.1 #1)                                          #
# --------------------------------------------------------------------------- #
def _readonly_sqlite(path: Path) -> sqlite3.Connection:
    """Snapshot-then-open.  Copies ``path`` (and any -wal/-journal sidecar) to
    ``data/dashboard/_snap/<name>.db`` with ``shutil.copy2``, then opens the COPY.
    Falls back to a URI read-only connection if the copy fails.  Never opens the
    live file for write; never constructs Ledger/Memory/AlphaCardStore on a path
    under ``data/``.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        _SNAP_DIR.mkdir(parents=True, exist_ok=True)
        snap = _SNAP_DIR / path.name
        shutil.copy2(path, snap)
        for suffix in ("-wal", "-journal", "-shm"):
            side = path.with_name(path.name + suffix)
            if side.exists():
                shutil.copy2(side, _SNAP_DIR / side.name)
        return sqlite3.connect(str(snap))
    except Exception:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _table_has_rows(conn: sqlite3.Connection, table: str) -> bool:
    try:
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - fixed names
        return int(cur.fetchone()[0]) > 0
    except sqlite3.Error:
        return False


# --------------------------------------------------------------------------- #
# The cache layer                                                              #
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def cache_manifest() -> dict:
    """Parsed ``data/dashboard/_manifest.json``, or ``{}`` if absent/corrupt."""
    p = CACHE_DIR / "_manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


@st.cache_data(show_spinner=False)
def load_cache(name: str) -> pd.DataFrame:
    """Read ``data/dashboard/<name>.parquet``.

    Raises ``FileNotFoundError`` naming the exact build command if absent.
    """
    p = CACHE_DIR / f"{name}.parquet"
    if not p.exists():
        raise FileNotFoundError(
            f"cache {name!r} not built — run:\n"
            f"    python dashboard/build_cache.py --only {name}"
        )
    return pd.read_parquet(p)


def try_cache(name: str) -> pd.DataFrame | None:
    """``load_cache`` but returns ``None`` instead of raising."""
    try:
        return load_cache(name)
    except FileNotFoundError:
        return None


@st.cache_data(show_spinner=False)
def available() -> dict[str, bool]:
    """Which real artifacts exist (Section 0.4).  A count-based key is ``False``
    when the store exists but is empty."""
    out: dict[str, bool] = {}
    out["universe"] = (DATA_DIR / "universe" / "membership.parquet").exists()
    out["prices"] = _OHLCV.exists()
    out["panel"] = _FEATURES.exists() and _LABELS.exists()
    out["corpus"] = (DATA_DIR / "corpus" / "anomalies.json").exists()

    cards_dir = ARTIFACTS_DIR / "cards"
    out["cards"] = cards_dir.exists() and any(
        p.stat().st_size > 0 for p in cards_dir.glob("*.json")
    )

    for key, (fname, table) in {
        "ledger": ("ledger.db", "trials"),
        "memory": ("memory.db", "card_index"),
        "lessons": ("lessons.db", "lessons"),
    }.items():
        p = DATA_DIR / fname
        if not p.exists():
            out[key] = False
            continue
        try:
            conn = _readonly_sqlite(p)
            out[key] = _table_has_rows(conn, table)
            conn.close()
        except Exception:
            out[key] = False

    bandit = DATA_DIR / "bandit_state.json"
    try:
        payload = json.loads(bandit.read_text(encoding="utf-8"))
        out["bandit"] = bool(payload.get("families"))
    except (json.JSONDecodeError, OSError, AttributeError):
        out["bandit"] = False

    loop_db = DATA_DIR / "loop_checkpoint.db"
    if loop_db.exists():
        try:
            conn = _readonly_sqlite(loop_db)
            row = conn.execute(
                "SELECT COUNT(*) FROM run_state WHERE id = 1"
            ).fetchone()
            out["loop"] = int(row[0]) > 0
            conn.close()
        except Exception:
            out["loop"] = False
    else:
        out["loop"] = False

    out["evaluation"] = (REPORTS_DIR / "p12_system_evaluation.md").exists()
    return out


def cache_staleness() -> list[str]:
    """Cache rows whose recorded source mtime/size is behind disk (Section 0.8.1 #3)."""
    stale: list[str] = []
    for name, row in cache_manifest().items():
        for src in row.get("sources", []) or []:
            sp = Path(src.get("path", ""))
            if not sp.is_absolute():
                sp = PROJECT_ROOT / sp
            if not sp.exists():
                continue
            try:
                st_ = sp.stat()
            except OSError:
                continue
            if (round(st_.st_mtime, 3) > round(float(src.get("mtime", 0)), 3)
                    or st_.st_size != int(src.get("size", st_.st_size))):
                stale.append(name)
                break
    return sorted(set(stale))


# --------------------------------------------------------------------------- #
# Project-data readers — sliced / columnar only                                #
# --------------------------------------------------------------------------- #
def _assert_sliced(path: Path, filters, columns) -> None:
    """Guard: never pull a big parquet whole into pandas."""
    if path in _BIG_FILES and filters is None and columns is None:
        raise ValueError(
            f"{path.name} is too large to read whole — pass symbols=, a date "
            f"bound, or columns="
        )


def _read_parquet_sliced(path: Path, filters=None, columns=None) -> pd.DataFrame:
    _assert_sliced(path, filters, columns)
    if not path.exists():
        raise FileNotFoundError(path)
    return pq.read_table(path, filters=filters, columns=columns).to_pandas()


@st.cache_data(show_spinner=False)
def load_universe_membership() -> pd.DataFrame:
    """``date, symbol, in_universe`` — full (small: ~1.6M booleans but one file)."""
    p = DATA_DIR / "universe" / "membership.parquet"
    if not p.exists():
        raise FileNotFoundError(p)
    return pd.read_parquet(p)


@st.cache_data(show_spinner=False)
def load_universe_stats() -> pd.DataFrame:
    """``date, n_members, median_turnover, turnover_cutoff_200`` (monthly)."""
    p = DATA_DIR / "universe" / "universe_stats.parquet"
    if not p.exists():
        raise FileNotFoundError(p)
    return pd.read_parquet(p)


@st.cache_data(show_spinner=False)
def load_liquidity_ranks() -> pd.DataFrame:
    """``month_end(ns), symbol, liquidity_rank(int), trailing_turnover(f64)``.

    Exact column names — NOT 'rank'/'turnover'.  ``src.redteam`` test 11
    (universe_edge) takes this frame verbatim.
    """
    p = DATA_DIR / "universe" / "liquidity_ranks.parquet"
    if not p.exists():
        raise FileNotFoundError(p)
    return pd.read_parquet(p)


@st.cache_data(show_spinner=False)
def load_symbols() -> dict:
    p = DATA_DIR / "universe" / "symbols.json"
    if not p.exists():
        raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_splits() -> dict:
    p = DATA_DIR / "panel" / "splits.json"
    if not p.exists():
        raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_ohlcv(symbols: list[str] | None = None, start: str | None = None,
               end: str | None = None, columns: list[str] | None = None) -> pd.DataFrame:
    """pyarrow-filtered slice of ``ohlcv.parquet``.  Requires a symbol list or a
    date bound (or an explicit column list)."""
    filters = []
    if symbols:
        filters.append(("symbol", "in", list(symbols)))
    if start:
        filters.append(("date", ">=", pd.Timestamp(start)))
    if end:
        filters.append(("date", "<=", pd.Timestamp(end)))
    flt = filters or None
    if flt is None and columns is None:
        raise ValueError("load_ohlcv needs symbols=, start/end=, or columns=")
    return _read_parquet_sliced(_OHLCV, filters=flt, columns=columns)


@st.cache_data(show_spinner=False)
def load_features(symbols: list[str] | None = None,
                  columns: list[str] | None = None) -> pd.DataFrame:
    filters = [("symbol", "in", list(symbols))] if symbols else None
    if filters is None and columns is None:
        raise ValueError("load_features needs symbols= or columns=")
    return _read_parquet_sliced(_FEATURES, filters=filters, columns=columns)


@st.cache_data(show_spinner=False)
def load_labels(symbols: list[str] | None = None,
                columns: list[str] | None = None) -> pd.DataFrame:
    filters = [("symbol", "in", list(symbols))] if symbols else None
    if filters is None and columns is None:
        raise ValueError("load_labels needs symbols= or columns=")
    return _read_parquet_sliced(_LABELS, filters=filters, columns=columns)


@st.cache_data(show_spinner=False)
def load_corporate_actions() -> pd.DataFrame:
    p = DATA_DIR / "prices" / "corporate_actions.parquet"
    if not p.exists():
        raise FileNotFoundError(p)
    return pd.read_parquet(p)


@st.cache_data(show_spinner=False)
def load_delivery(symbols: list[str] | None = None) -> pd.DataFrame:
    p = DATA_DIR / "prices" / "delivery.parquet"
    if not p.exists():
        raise FileNotFoundError(p)
    filters = [("symbol", "in", list(symbols))] if symbols else None
    return pq.read_table(p, filters=filters).to_pandas()


# --------------------------------------------------------------------------- #
# SQLite / JSON stores — all via _readonly_sqlite                              #
# --------------------------------------------------------------------------- #
def _sql_frame(fname: str, query: str) -> pd.DataFrame:
    p = DATA_DIR / fname
    if not p.exists():
        return pd.DataFrame()
    conn = _readonly_sqlite(p)
    try:
        return pd.read_sql_query(query, conn)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


@st.cache_data(show_spinner=False)
def load_ledger_trials() -> pd.DataFrame:
    return _sql_frame("ledger.db", "SELECT * FROM trials ORDER BY trial_id")


@st.cache_data(show_spinner=False)
def load_holdout_peeks() -> pd.DataFrame:
    return _sql_frame("ledger.db", "SELECT * FROM holdout_peeks ORDER BY peek_id")


@st.cache_data(show_spinner=False)
def load_lessons() -> pd.DataFrame:
    return _sql_frame("lessons.db", "SELECT * FROM lessons ORDER BY lesson_id")


@st.cache_data(show_spinner=False)
def load_bandit() -> pd.DataFrame:
    """``bandit_state.json`` → one row per family.  Tolerates a truncated file
    (Section 0.8.1 #2) by returning the empty frame."""
    cols = ["family", "n_pulls", "cumulative_reward", "tokens_spent",
            "last_k_deltas", "allocation"]
    p = DATA_DIR / "bandit_state.json"
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return pd.DataFrame(columns=cols)
    fams = payload.get("families", {})
    if not fams:
        return pd.DataFrame(columns=cols)
    total_pulls = sum(max(0, f.get("n_pulls", 0)) for f in fams.values()) or 1
    rows = []
    for name, f in fams.items():
        rows.append({
            "family": name,
            "n_pulls": int(f.get("n_pulls", 0)),
            "cumulative_reward": float(f.get("cumulative_reward", 0.0)),
            "tokens_spent": int(f.get("tokens_spent", 0)),
            "last_k_deltas": list(f.get("last_k_deltas", [])),
            "allocation": max(0, f.get("n_pulls", 0)) / total_pulls,
        })
    return pd.DataFrame(rows, columns=cols)


#: A faithful, dependency-free port of ``src.contracts.validate_card`` (Section
#: 0.5) — same keys, same nested key sets, same verdict vocabulary, same two
#: cross-field rules — so this module keeps its "no ``src`` import" guarantee
#: (Section 0.4) while giving a card the IDENTICAL accept/reject decision the
#: authoritative validator would.  Kept in sync with ``src/contracts.py``; a
#: page that wants the real function gets it via ``lib.engine`` / ``lib.fixtures``.
_CARD_TOP_KEYS = (
    "card_id", "thesis_id", "generation", "thesis", "pre_registered", "formula",
    "ast_canonical", "complexity", "tier1_metrics", "fresh_fold_metrics",
    "tier2_metrics", "audit", "redteam", "verdict", "lineage", "provenance",
)
_CARD_THESIS_KEYS = (
    "mechanism", "counterparty", "why_not_arbitraged", "horizon_days", "regime",
    "falsifiable_claim",
)
_CARD_PREREG_KEYS = ("sign", "horizon_days", "committed_at", "hash")
_CARD_COMPLEXITY_KEYS = ("nodes", "depth", "free_params")
_CARD_LINEAGE_KEYS = ("parent_card_id", "edit_motif")
_CARD_VERDICTS = frozenset({"accept", "reject", "revise", "provisional"})


def _card_looks_valid(card: object) -> bool:
    if not isinstance(card, dict):
        return False
    if any(k not in card for k in _CARD_TOP_KEYS):
        return False
    if not str(card.get("card_id", "")).strip():
        return False
    for sub, keys in (
        ("thesis", _CARD_THESIS_KEYS),
        ("pre_registered", _CARD_PREREG_KEYS),
        ("complexity", _CARD_COMPLEXITY_KEYS),
        ("lineage", _CARD_LINEAGE_KEYS),
    ):
        if not isinstance(card.get(sub), dict) or any(k not in card[sub] for k in keys):
            return False
    if card["verdict"] not in _CARD_VERDICTS:
        return False
    try:
        if int(card["pre_registered"]["sign"]) not in (-1, 1):
            return False
    except (TypeError, ValueError):
        return False
    prov = card.get("provenance")
    if not isinstance(prov, dict) or "fields_used" not in prov:
        return False
    return True


@st.cache_data(show_spinner=False)
def load_cards() -> list[dict]:
    """Every ``artifacts/cards/*.json`` (best-effort structural check).  Skips a
    file that fails ``json.load`` or the check (Section 0.8.1 #5)."""
    cards_dir = ARTIFACTS_DIR / "cards"
    if not cards_dir.exists():
        return []
    out: list[dict] = []
    for p in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not _card_looks_valid(card):
            continue
        card.setdefault("_path", str(p))
        out.append(card)
    return out


@st.cache_data(show_spinner=False)
def load_corpus() -> pd.DataFrame:
    """``data/corpus/anomalies.json`` → one row per entry."""
    p = DATA_DIR / "corpus" / "anomalies.json"
    if not p.exists():
        return pd.DataFrame()
    payload = json.loads(p.read_text(encoding="utf-8"))
    return pd.DataFrame(payload.get("anomalies", []))


def load_handoff(phase: str) -> str:
    """``reports/<phase>_handoff.md`` text, ``""`` if absent."""
    p = REPORTS_DIR / f"{phase}_handoff.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


# --------------------------------------------------------------------------- #
# P10 loop run state (Section 0.4 / 0.5 `src.loop`)                            #
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def load_loop_run_state() -> dict | None:
    """The ``run_state`` id=1 JSON from ``data/loop_checkpoint.db``, or ``None``
    if the loop has not run.  Read through ``_readonly_sqlite``."""
    p = DATA_DIR / "loop_checkpoint.db"
    if not p.exists():
        return None
    conn = _readonly_sqlite(p)
    try:
        row = conn.execute("SELECT json FROM run_state WHERE id = 1").fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None


_LOOP_GEN_COLS = list({
    "generation": "int64", "family": "object", "thesis_id": "object",
    "verdict": "object", "reject_reason": "object", "variant_count": "int64",
    "forced_promote": "bool", "marginal_ic": "float64",
    "novelty_adjusted_marginal_ic": "float64", "tier1_rank_ic": "float64",
    "fresh_fold_rank_ic": "float64", "redteam_verdict": "object",
    "holdout_rank_ic": "float64", "holdout_failed": "bool",
    "mandatory_regimes": "object",
})


@st.cache_data(show_spinner=False)
def load_loop_generations() -> pd.DataFrame:
    """``load_loop_run_state()['generations']`` flattened to one row/generation.
    Empty schema-correct frame when the loop has not run."""
    state = load_loop_run_state()
    gens = (state or {}).get("generations") or []
    if not gens:
        return pd.DataFrame(columns=_LOOP_GEN_COLS)
    df = pd.DataFrame(gens)
    for col in _LOOP_GEN_COLS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[_LOOP_GEN_COLS]
