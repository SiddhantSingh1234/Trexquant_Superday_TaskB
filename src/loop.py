"""Phase 10 — the orchestration graph (LangGraph wiring of the nine stages).

The governing rule the whole design obeys: **agency where there is a DECISION,
deterministic code where it is a FIXED COMPUTATION.**  Every verdict here is
computed by code against a fixed threshold — an LLM node never decides
accept/reject.  The LLM nodes propose (family, thesis, formula, which red-team
tests); the tool nodes measure and judge.

Three enforcement points are this phase's real content
-----------------------------------------------------
1. **Variant cap (<= 20 per thesis).**  The ``judge -> code`` edge maintains a
   per-thesis counter, hard-capped at ``config.MAX_VARIANTS_PER_THESIS``.  At the
   cap the loop forces *promote-best* or *reject* — the search can never
   manufacture significance by trying a 200th variant of pure noise (best-of-200
   noise shows t ~ 3.26).
2. **Fresh-fold confirmation.**  The formula search runs entirely on **VAL_A**.
   The single promoted winner must hold on **VAL_B**, which no variant ever
   touched.  The backtester is instrumented and the run asserts **no VAL_B call
   happens before a promote**.
3. **Gate B ordering.**  Orthogonalise -> **novelty** -> statistics -> holdout
   peek.  ``gate_b_novelty`` is a distinct node wired *before* ``gate_b_stats``;
   call order is instrumented and asserted.  Novelty is free; the statistics step
   spends an irreplaceable holdout peek.

Also implemented (improvement mechanisms — "improves over iterations" is graded):
* **Curriculum** — every ``curriculum_every`` generations the Red-Team's
  mandatory regime slice rotates to a harder one (:func:`curriculum_regimes`).
* **FDR auto-tightening meta-check** — when the rolling holdout FDR rises above a
  threshold, ``T_STAT_BAR`` and the marginal-IC floor are raised a fixed step and
  the change is logged (:func:`maybe_tighten_gates`).

Checkpointing
-------------
The per-thesis graph is compiled with :class:`SqliteSaver` (a langgraph
``BaseCheckpointSaver`` backed by **stdlib sqlite3** — see the class docstring
for why not ``langgraph-checkpoint-sqlite``).  The outer research loop persists
its own state (generation counter, gate thresholds, per-generation metrics,
accepted card ids, token-budget spend) into the same DB file, so a run whose LLM
token budget is exhausted mid-way **resumes the next day** rather than restarting
(PRE_BUILD_TASKS.md T3: the free tier supports only ~20 theses/day).

Portfolio is **not** a graph node — :func:`portfolio_combine` runs once, after the
graph terminates, over the accepted book.

Runs end-to-end with ``LLM_MODE=mock`` and no network.
"""
from __future__ import annotations

import argparse
import importlib
import json
import operator
import os
import pickle
import random
import sqlite3
import tempfile
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Callable, TypedDict

import numpy as np
import pandas as pd

from . import backtester as _bt
from . import contracts as _contracts
from . import gates as _gates
from . import redteam as _redteam
from . import zoo as _zoo
from .agents import build_agents
from .agents.base import BudgetExhausted, TokenBudget
from .agents.hypothesis import commit_preregistration
from .agents.librarian import load_corpus, retrieve as _corpus_retrieve
from .agents.redteam import RED_TEAM_MENU
from .ast_tools import ParseError, canonical, complexity, evaluate, parse
from . import config as _config
from .config import COST_BPS_DEFAULT, DATA_DIR
from .contracts import HORIZONS, validate_card
from .ledger import Ledger
from .memory import FAMILIES, Memory, new_card

# --------------------------------------------------------------------------- #
# Determinism (Section 0.6)                                                    #
# --------------------------------------------------------------------------- #
np.random.seed(_config.RANDOM_SEED)
random.seed(_config.RANDOM_SEED)

# --------------------------------------------------------------------------- #
# Tunables (documented judgement calls — see reports/p10_handoff.md §7)         #
# --------------------------------------------------------------------------- #
MAX_VARIANTS = _config.MAX_VARIANTS_PER_THESIS            # 20 — the hard cap
STALL_LIMIT = 4                    # identical-formula repeats before force-decision
RECURSION_LIMIT = 240             # langgraph super-steps per thesis (>> worst case)

COMPLEXITY_MAX_NODES = 40
COMPLEXITY_MAX_DEPTH = 12
COMPLEXITY_MAX_PARAMS = 10
ZOO_DUP_THRESHOLD = 1.0            # exact canonical match only (P5 default)

FRESHFOLD_MIN_T = 1.5             # |t| floor for VAL_B "holds" (1y window; cf. RT_SIG_T)

CURRICULUM_EVERY_DEFAULT = 3      # rotate the mandatory regime every N generations
CURRICULUM_ROTATION: tuple[tuple[dict, ...], ...] = (
    ({"regime": "bear"},),
    ({"regime": "highvol"},),
    ({"regime": "volatile"},),
    ({"regime": "bull"},),
)

FDR_TIGHTEN_THRESHOLD = 0.33      # rolling holdout FDR above this -> tighten
FDR_TIGHTEN_STEP_T = 0.5
FDR_TIGHTEN_STEP_MI = 0.005
FDR_ROLL_WINDOW = 6

STOP_EPSILON_DEFAULT = 1e-3      # novelty-adjusted marginal-IC increment
STOP_K_DEFAULT = 3              # consecutive lean generations before halting

DEFAULT_CHECKPOINT = DATA_DIR / "loop_checkpoint.db"
DEFAULT_REPORT = _config.REPORTS_DIR / "p10_loop_report.md"

# Price fields the formula evaluator can resolve (kept in sync with operators.FIELDS)
_PRICE_FIELDS = (
    "open", "high", "low", "close", "volume", "vwap", "n_trades",
    "close_raw", "volume_raw",
)


class SignalEvalError(RuntimeError):
    """A promoted / candidate formula could not be turned into a signal frame."""


# ═════════════════════════════════════════════════════════════════════════════
#  SqliteSaver — a langgraph checkpointer backed by stdlib sqlite3
# ═════════════════════════════════════════════════════════════════════════════
def _plain(d: Any) -> Any:
    """Deep-copy nested (default)dicts to plain dicts so ``pickle`` never meets a
    lambda ``default_factory``."""
    if isinstance(d, (dict, defaultdict)):
        return {k: _plain(v) for k, v in d.items()}
    return d


try:  # langgraph is a Phase 8/10 dependency (Section 0.2)
    from langgraph.checkpoint.memory import InMemorySaver as _InMemorySaver
    from langgraph.graph import END, START, StateGraph

    _HAVE_LANGGRAPH = True
except Exception:  # pragma: no cover - langgraph always present in this repo
    _HAVE_LANGGRAPH = False
    _InMemorySaver = object  # type: ignore
    END = "__end__"  # type: ignore
    START = "__start__"  # type: ignore
    StateGraph = None  # type: ignore


class SqliteSaver(_InMemorySaver):  # type: ignore[misc]
    """A drop-in langgraph checkpointer that mirrors its in-memory state to a
    single stdlib-``sqlite3`` file after every write, and reloads it on open.

    **Why not ``langgraph-checkpoint-sqlite``?**  That package pulls
    ``sqlite-vec`` as a transitive dependency — a vector-search extension, which
    the plan lists under *"Explicitly NOT allowed: FAISS, Pinecone, Chroma ...
    any ... no vector database"* (Section 0.2).  ``sqlite3`` is stdlib and
    explicitly allowed, and Phases 6/7 already use exactly this pattern.  This
    subclass keeps langgraph's own (well-tested) checkpoint semantics — thread
    resume, channel versions, pending writes — and only adds durable persistence.

    The langgraph runtime calls ``put`` / ``put_writes`` from a worker thread, so
    the connection is opened ``check_same_thread=False`` and every write is
    serialised through a lock.
    """

    def __init__(self, db_path: str | Path, *, serde: Any = None) -> None:
        super().__init__(serde=serde)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS lg_checkpoint "
            "(id INTEGER PRIMARY KEY CHECK (id = 1), blob BLOB NOT NULL, updated TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS run_state "
            "(id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL, updated TEXT NOT NULL)"
        )
        self._db.commit()
        self._restore()

    # -- langgraph checkpoint mirror ----------------------------------
    def _restore(self) -> None:
        row = self._db.execute("SELECT blob FROM lg_checkpoint WHERE id = 1").fetchone()
        if not row:
            return
        storage, writes, blobs = pickle.loads(row[0])
        for tid, ns_map in storage.items():
            for ns, cp_map in ns_map.items():
                self.storage[tid][ns].update(cp_map)
        for key, val in writes.items():
            self.writes[key].update(val)
        self.blobs.update(blobs)

    def _persist(self) -> None:
        with self._lock:
            blob = pickle.dumps(
                (_plain(self.storage), _plain(self.writes), dict(self.blobs))
            )
            self._db.execute(
                "INSERT INTO lg_checkpoint (id, blob, updated) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET blob = excluded.blob, updated = excluded.updated",
                (blob, _utcnow_iso()),
            )
            self._db.commit()

    def put(self, *args: Any, **kw: Any) -> Any:
        result = super().put(*args, **kw)
        self._persist()
        return result

    def put_writes(self, *args: Any, **kw: Any) -> Any:
        result = super().put_writes(*args, **kw)
        self._persist()
        return result

    # -- outer research-loop state ----------------------------------
    def save_run_state(self, payload: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO run_state (id, json, updated) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET json = excluded.json, updated = excluded.updated",
                (json.dumps(payload, default=str), _utcnow_iso()),
            )
            self._db.commit()

    def load_run_state(self) -> dict | None:
        row = self._db.execute("SELECT json FROM run_state WHERE id = 1").fetchone()
        return json.loads(row[0]) if row else None

    def close(self) -> None:
        try:
            self._db.close()
        except Exception:  # pragma: no cover
            pass


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ═════════════════════════════════════════════════════════════════════════════
#  The graph state
# ═════════════════════════════════════════════════════════════════════════════
class AlphaResearchState(TypedDict, total=False):
    """Per-thesis state threaded through the graph.

    The spec (Phase 10 step 1) also names ``memory · ledger · book`` as state
    fields; those are live sqlite/parquet handles that a langgraph checkpoint
    cannot serialise, so they live on :class:`RunContext` (process singletons,
    reopened on resume from the same files) and only the JSON-serialisable
    research state is checkpointed here.  See reports/p10_handoff.md §7.
    """

    generation: int
    budget_tokens_left: int
    family: str
    bandit_stats: dict
    max_variants: int

    corpus_angles: list
    corpus_anchor: dict
    keywords: list
    brief: str

    thesis: dict
    thesis_id: str
    pre_registered: dict
    gate_a: dict

    candidate: dict
    variant_count: int
    stall_count: int
    edit_motif: str
    eval_error: str
    population: Annotated[list, operator.add]
    best_variant: dict
    promoted: dict
    forced_promote: bool
    prefilter: dict
    judge: dict

    tier1_metrics: dict
    fresh_fold_metrics: dict
    tier2_metrics: dict
    gate_b_novelty: dict
    gate_b_audit: dict
    redteam_report: dict

    mandatory_regimes: list
    verdict: str
    reject_reason: str
    card: dict


# ═════════════════════════════════════════════════════════════════════════════
#  Run context — the live handles the nodes need (not checkpointed)
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class RunContext:
    run_id: str
    memory: Memory
    ledger: Ledger
    agents: dict
    price_panel: dict            # {field: wide date x symbol frame}
    horizon: int = 5
    do_holdout_peek: bool = True
    prices: pd.DataFrame | None = None          # ohlcv-like, for red-team test 11
    liquidity_ranks: pd.DataFrame | None = None
    recorder: list = field(default_factory=list)      # instrumentation events
    report_lines: list = field(default_factory=list)
    prereg_log: list = field(default_factory=list)    # (thesis_id, hash, "before_backtest")
    accepted: list = field(default_factory=list)
    families_tried: list = field(default_factory=list)   # one entry per generation
    _promote_marked: set = field(default_factory=set)
    _clock_base: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    _current_gen: int = 0
    _current_thesis: str | None = None

    def clock(self) -> datetime:
        # deterministic, monotone-per-generation — keeps the pre-registration
        # hash reproducible across a checkpoint/resume.
        return self._clock_base + timedelta(seconds=self._current_gen)

    def current_thesis(self) -> str:
        """The thesis a backtest belongs to.

        ``ideate`` stamps this; the fallback reproduces the same deterministic id
        so a backtest fired before ``ideate`` still attributes to the right
        thesis rather than leaking into the previous one.
        """
        return self._current_thesis or f"th_{self.run_id}_g{self._current_gen}"

    # -- instrumentation --------------------------------------------
    def record(self, **event: Any) -> None:
        event.setdefault("seq", len(self.recorder))
        self.recorder.append(event)

    def mark_promote(self, thesis_id: str) -> None:
        if thesis_id not in self._promote_marked:
            self._promote_marked.add(thesis_id)
            self.record(kind="promote", thesis_id=thesis_id)


# ═════════════════════════════════════════════════════════════════════════════
#  Backtester instrumentation
# ═════════════════════════════════════════════════════════════════════════════
class _BacktestInstrument:
    """Context manager that wraps ``backtester.backtest`` for the duration of a
    run so every call's ``split`` is recorded.  ``gates`` and ``redteam`` call
    ``_bt.backtest`` (module attribute, resolved per call), so patching the
    attribute captures the holdout peek and every red-team stress too.
    """

    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self._orig: Callable | None = None

    def __enter__(self) -> "_BacktestInstrument":
        self._orig = _bt.backtest

        def _wrapped(signal, split, *a, **kw):
            self.ctx.record(
                kind="backtest", split=split,
                thesis_id=self.ctx.current_thesis(),
                has_token=bool(kw.get("i_have_a_peek_token", False)),
            )
            return self._orig(signal, split, *a, **kw)

        _bt.backtest = _wrapped  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._orig is not None:
            _bt.backtest = self._orig  # type: ignore[assignment]


# ═════════════════════════════════════════════════════════════════════════════
#  Signal evaluation:  formula string  ->  wide date x symbol frame
# ═════════════════════════════════════════════════════════════════════════════
def _panel_from_ohlcv(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build a ``{field: wide date x symbol}`` panel from an OHLCV-shaped frame."""
    fields: dict[str, pd.DataFrame] = {}
    for col in _PRICE_FIELDS:
        if col in df.columns:
            w = df.pivot_table(index="date", columns="symbol", values=col).sort_index()
            w.index = pd.DatetimeIndex(pd.to_datetime(w.index)).normalize()
            fields[col] = w
    if "close" in fields:
        fields["returns"] = fields["close"].pct_change()
    for extra in ("delivery_pct", "size_proxy"):
        if extra in df.columns:
            w = df.pivot_table(index="date", columns="symbol", values=extra).sort_index()
            w.index = pd.DatetimeIndex(pd.to_datetime(w.index)).normalize()
            fields[extra] = w
    return fields


def build_price_panel(source: str | Path | pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Assemble the field panel formulas are evaluated against.

    ``source`` — a DataFrame or parquet path; ``None`` reads
    ``data/prices/ohlcv.parquet`` (+ ``delivery.parquet`` / ``size_proxy.parquet``
    / the panel's ``sector`` where present), falling back to the Phase-0 OHLCV
    fixture.
    """
    if isinstance(source, pd.DataFrame):
        return _panel_from_ohlcv(source)
    if source is not None:
        return _panel_from_ohlcv(pd.read_parquet(source))

    if _config.OHLCV_PARQUET.exists():
        panel = _panel_from_ohlcv(pd.read_parquet(_config.OHLCV_PARQUET))
        dp = _config.PRICES_DIR / "delivery.parquet"
        sp = _config.PRICES_DIR / "size_proxy.parquet"
        if dp.exists():
            d = pd.read_parquet(dp)
            vcol = "delivery_pct" if "delivery_pct" in d.columns else d.columns[-1]
            w = d.pivot_table(index="date", columns="symbol", values=vcol).sort_index()
            w.index = pd.DatetimeIndex(pd.to_datetime(w.index)).normalize()
            panel["delivery_pct"] = w
        if sp.exists():
            s = pd.read_parquet(sp)
            vcol = "size_proxy" if "size_proxy" in s.columns else s.columns[-1]
            w = s.pivot_table(index="date", columns="symbol", values=vcol).sort_index()
            w.index = pd.DatetimeIndex(pd.to_datetime(w.index)).normalize()
            panel["size_proxy"] = w
        if _config.FEATURES_PARQUET.exists():
            f = pd.read_parquet(_config.FEATURES_PARQUET, columns=["date", "symbol", "sector"])
            panel["sector"] = f.pivot_table(
                index="date", columns="symbol", values="sector", aggfunc="first"
            ).sort_index()
        return panel

    return _panel_from_ohlcv(_contracts.make_fake_ohlcv())


def synthetic_price_panel(
    n_days: int = 800, n_symbols: int = 24, seed: int = _config.RANDOM_SEED,
    *, planted_field: str = "delivery_pct", planted: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """A field panel for tests.  ``planted`` (a wide date x symbol frame) is
    written into ``planted_field`` so a formula like ``rank(delivery_pct)`` carries
    a known signal; otherwise the field keeps its fixture values.
    """
    ohlcv = _contracts.make_fake_ohlcv(n_days=n_days, n_symbols=n_symbols, seed=seed)
    panel = _panel_from_ohlcv(ohlcv)
    dates, syms = panel["close"].index, panel["close"].columns
    if planted is not None:
        p = planted.reindex(index=dates, columns=syms)
        panel[planted_field] = (50.0 + 15.0 * p.clip(-3, 3)).astype(float)
    else:
        rng = np.random.default_rng(seed + 5)
        panel.setdefault(
            planted_field,
            pd.DataFrame(rng.uniform(20, 85, size=panel["close"].shape),
                         index=dates, columns=syms),
        )
    panel.setdefault(
        "size_proxy",
        pd.DataFrame(18.0, index=dates, columns=syms),
    )
    return panel


def evaluate_signal(formula: str, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Evaluate ``formula`` (Phase-5 grammar) against ``panel`` -> wide frame."""
    try:
        out = evaluate(formula, panel, strict=False)
    except Exception as exc:  # noqa: BLE001
        raise SignalEvalError(f"could not evaluate {formula!r}: {exc}") from exc
    if not isinstance(out, pd.DataFrame):
        raise SignalEvalError(f"formula {formula!r} produced a {type(out).__name__}, not a frame")
    out = out.copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index)).normalize()
    return out.sort_index()


# ═════════════════════════════════════════════════════════════════════════════
#  Curriculum + FDR meta-check  (improvement mechanisms)
# ═════════════════════════════════════════════════════════════════════════════
def curriculum_regimes(generation: int, every: int = CURRICULUM_EVERY_DEFAULT) -> list[dict]:
    """The Red-Team's *mandatory* regime slice for ``generation``.

    Rotates every ``every`` generations through
    ``bear -> highvol -> volatile -> bull`` so a candidate cannot survive merely
    because the agent picked a gentle stress.  Returned as a list of ``subsample``
    dicts the backtester accepts.
    """
    every = max(1, int(every))
    idx = (generation // every) % len(CURRICULUM_ROTATION)
    return [dict(s) for s in CURRICULUM_ROTATION[idx]]


def rolling_fdr(generations: list[dict], window: int = FDR_ROLL_WINDOW) -> float:
    """Rolling holdout false-discovery rate over the last ``window`` *accepted*
    cards: fraction whose HOLDOUT peek did not confirm the pre-registered sign.
    (On real runs P12 supplies this; here it is derived from Gate B's peek log.)
    """
    accepted = [g for g in generations if g.get("verdict") == "accept"][-window:]
    if not accepted:
        return 0.0
    fails = sum(1 for g in accepted if g.get("holdout_failed"))
    return fails / len(accepted)


def maybe_tighten_gates(
    fdr: float, t_bar: float, mi_floor: float, report_lines: list,
) -> tuple[float, float]:
    """If ``fdr`` exceeds :data:`FDR_TIGHTEN_THRESHOLD`, raise ``T_STAT_BAR`` and
    the marginal-IC floor a fixed step, apply them to ``gates``, and log it.
    """
    if fdr <= FDR_TIGHTEN_THRESHOLD:
        return t_bar, mi_floor
    t_bar = round(t_bar + FDR_TIGHTEN_STEP_T, 4)
    mi_floor = round(mi_floor + FDR_TIGHTEN_STEP_MI, 4)
    _gates.T_STAT_BAR = t_bar
    _gates.MIN_MARGINAL_IC = mi_floor
    report_lines.append(
        f"[meta] rolling FDR={fdr:.2f} > {FDR_TIGHTEN_THRESHOLD}: "
        f"T_STAT_BAR -> {t_bar}, MIN_MARGINAL_IC -> {mi_floor}"
    )
    return t_bar, mi_floor


# ═════════════════════════════════════════════════════════════════════════════
#  Node helpers
# ═════════════════════════════════════════════════════════════════════════════
_FAMILY_KEYWORDS: dict[str, list[str]] = {
    "momentum": ["momentum", "trend", "drift"],
    "reversal": ["reversal", "mean reversion", "short-term"],
    "volatility": ["volatility", "idiosyncratic", "risk"],
    "liquidity": ["liquidity", "volume", "turnover", "amihud"],
    "value_proxy": ["value", "cheap", "book"],
    "microstructure": ["microstructure", "trade size", "order flow"],
    "seasonality": ["seasonality", "calendar", "turn of month"],
    "quality_proxy": ["quality", "stability", "profitability"],
    "sentiment_proxy": ["sentiment", "attention", "delivery"],
    "trend": ["trend", "moving average", "breakout"],
}


def _pre_sign(state: AlphaResearchState) -> int:
    return int(state.get("pre_registered", {}).get("sign", 1) or 1)


def _viable(item: dict | None, pre_sign: int) -> bool:
    if not item:
        return False
    v = item.get("oriented_ic")
    return v is not None and np.isfinite(v) and v > 0


def _best_delta(population: list[dict]) -> float:
    """Improvement in oriented RankIC from the first variant to the best."""
    oic = [p["oriented_ic"] for p in population
           if p.get("oriented_ic") is not None and np.isfinite(p["oriented_ic"])]
    if len(oic) < 2:
        return 0.0
    return float(max(oic) - oic[0])


def _thesis_block(thesis: dict) -> dict:
    keys = ("mechanism", "counterparty", "why_not_arbitraged", "horizon_days",
            "regime", "falsifiable_claim")
    return {k: thesis.get(k, "" if k != "horizon_days" else 5) for k in keys}


def _build_card(state: AlphaResearchState, ctx: RunContext, *, verdict: str) -> dict:
    gen = int(state.get("generation", 0))
    promoted = state.get("promoted") or state.get("best_variant") or state.get("candidate") or {}
    formula = promoted.get("formula") or state.get("candidate", {}).get("formula", "rank(close)")
    tag = "acc" if verdict == "accept" else "rej"
    card = new_card(
        card_id=f"card_{ctx.run_id}_g{gen}_{tag}",
        thesis_id=state.get("thesis_id", f"th_{ctx.run_id}_g{gen}"),
        formula=formula,
        generation=gen,
        pre_registered_sign=_pre_sign(state),
        horizon_days=int(state.get("thesis", {}).get("horizon_days", ctx.horizon) or ctx.horizon),
        edit_motif=state.get("edit_motif"),
    )
    if state.get("thesis"):
        card["thesis"] = _thesis_block(state["thesis"])
    if state.get("pre_registered"):
        card["pre_registered"] = {
            k: state["pre_registered"][k]
            for k in ("sign", "horizon_days", "committed_at", "hash")
        }
    card["tier1_metrics"] = _metric_summary(state.get("tier1_metrics", {}))
    card["fresh_fold_metrics"] = _metric_summary(state.get("fresh_fold_metrics", {}))
    card["tier2_metrics"] = _metric_summary(state.get("tier2_metrics", {}))
    card["audit"] = dict(state.get("gate_b_audit", {}))
    card["audit"].setdefault("marginal_ic",
                             state.get("gate_b_novelty", {}).get("marginal_ic"))
    rt = state.get("redteam_report", {})
    card["redteam"] = {
        "tests_run": rt.get("tests_run", []),
        "results": {k: v.get("flag") for k, v in (rt.get("results") or {}).items()},
        "verdict": rt.get("verdict", "not_run"),
        "failed_tests": rt.get("failed_tests", []),
        "curriculum_flags": rt.get("curriculum_flags", []),
    }
    card["verdict"] = verdict
    if verdict != "accept":
        card["audit"]["reject_reason"] = state.get("reject_reason", "")
    return card


def _metric_summary(m: dict) -> dict:
    keep = ("rank_ic", "ic", "icir", "t_stat", "sharpe", "ann_return",
            "turnover", "mdd", "n_days", "n_obs", "sign",
            "residual_rank_ic", "net_sharpe_15bps")
    return {k: _num(m[k]) for k in keep if k in m}


def _num(x: Any) -> Any:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return x
    return None if not np.isfinite(f) else f


# ═════════════════════════════════════════════════════════════════════════════
#  The nodes
# ═════════════════════════════════════════════════════════════════════════════
def _make_nodes(ctx: RunContext) -> dict[str, Callable]:
    A = ctx.agents

    # -- S1 ------------------------------------------------------------
    def orchestrate(state: AlphaResearchState) -> dict:
        ctx._current_gen = int(state.get("generation", 0))
        try:
            alloc = ctx.memory.bandit.allocation()
        except Exception:  # noqa: BLE001
            alloc = {}
        if not alloc:
            for f in FAMILIES:
                ctx.memory.bandit.register_family(f)
            alloc = ctx.memory.bandit.allocation()
        # BanditState.suggest breaks the all-equal-allocation tie (unpulled arms
        # first, then a deterministic rotation).  ``max(alloc, key=alloc.get)``
        # returned the first-sorted key forever, which is why every generation of
        # the live_explore run drew `liquidity`.
        tried = list(ctx.families_tried)
        try:
            suggested = ctx.memory.bandit.suggest(ctx._current_gen, exclude=tuple(tried))
        except Exception:  # noqa: BLE001
            suggested = "liquidity"
        plan = A["planner"].run(
            allocation=alloc, top_family=suggested,
            pulls={f: ctx.memory.bandit.row(f).get("n_pulls", 0) for f in alloc},
            tried_this_run=tried,
        )
        family = plan.get("family")
        if family not in FAMILIES:
            family = suggested
        # Hard no-repeat guard: while any family is still unexplored, a repeat
        # pick is overridden.  A 3-generation run has no budget to spend two of
        # them on the same family.
        untried = [f for f in FAMILIES if f not in tried]
        if family in tried and untried:
            ctx.report_lines.append(
                f"[orchestrate] planner re-picked {family!r} (already tried this "
                f"run); overriding to {suggested!r} — {len(untried)} families unexplored"
            )
            family = suggested if suggested not in tried else untried[0]
        ctx.families_tried.append(family)
        ctx.memory.bandit.register_family(family)
        return {
            "family": family,
            "bandit_stats": alloc,
            "max_variants": min(int(plan.get("max_variants", MAX_VARIANTS)), MAX_VARIANTS),
            "variant_count": 0,
            "stall_count": 0,
            "mandatory_regimes": state.get("mandatory_regimes")
            or curriculum_regimes(ctx._current_gen),
        }

    # -- S2: retrieve (RAG) ------------------------------------------
    def retrieve(state: AlphaResearchState) -> dict:
        fam = state["family"]
        kws = _FAMILY_KEYWORDS.get(fam, [fam])
        try:
            hits = _corpus_retrieve(load_corpus(), family=fam, keywords=kws)
        except Exception:  # noqa: BLE001
            hits = []
        tradeable = [h for h in hits if h.get("tradeable_with_our_data")]
        angles = [h["name"] for h in tradeable]
        # The top tradeable hit becomes the ANCHOR: the Coder's first variant must
        # implement it faithfully before mutating.  Without this the Coder invents
        # raw-field arithmetic from scratch and never reaches documented effects
        # that the grammar can express in six nodes.
        anchor = {}
        if tradeable:
            a = tradeable[0]
            anchor = {k: a.get(k) for k in
                      ("name", "mechanism", "horizon_days", "fields_needed")}
        return {"corpus_angles": angles, "keywords": kws, "corpus_anchor": anchor}

    # -- S2: brief (LLM) -------------------------------------------
    def brief(state: AlphaResearchState) -> dict:
        b = A["librarian"].run(family=state["family"], keywords=state.get("keywords"))
        return {"brief": b.get("brief", "")}

    # -- S3: hypothesis + pre-registration -------------------------
    def ideate(state: AlphaResearchState) -> dict:
        th = A["hypothesis"].run(
            family=state["family"], brief=state.get("brief", ""),
            horizon_hint=ctx.horizon,
        )
        tid = f"th_{ctx.run_id}_g{int(state.get('generation', 0))}"
        ctx._current_thesis = tid          # attributes every later backtest to this thesis
        prereg = commit_preregistration(th, thesis_id=tid, now=ctx.clock)
        # the sign hash is stored BEFORE any backtest — recorded for audit
        ctx.prereg_log.append((tid, prereg["hash"], "before_backtest"))
        ctx.record(kind="prereg_stored", thesis_id=tid, hash=prereg["hash"])
        return {
            "thesis": th, "thesis_id": tid,
            "pre_registered": {
                k: prereg[k] for k in ("sign", "horizon_days", "committed_at", "hash")
            },
        }

    # -- S4: Gate A ------------------------------------------------
    def gate_a_economics(state: AlphaResearchState) -> dict:
        r = A["economics"].review(state["thesis"])
        if r["verdict"] == "reject":
            return {"gate_a": r, "verdict": "reject",
                    "reject_reason": "Gate A (economics): " + "; ".join(r.get("reasons", []))}
        return {"gate_a": r}

    # -- S5: Coder ----------------------------------------------
    def code(state: AlphaResearchState) -> dict:
        vc = int(state.get("variant_count", 0)) + 1
        prior = state.get("candidate", {}).get("formula")
        c = A["coder"].run(
            thesis=state["thesis"], family=state["family"],
            prior_formula=prior, edit_motif=state.get("edit_motif"),
            repair_hint=state.get("eval_error"),
            # anchor only on the FIRST variant — after that the Judge's edit
            # motif drives refinement and a fixed anchor would just freeze it.
            anchor=state.get("corpus_anchor") if not prior else None,
        )
        f = c["formula"]
        cand = {
            "formula": f,
            "ast_canonical": c.get("ast_canonical") or _safe_canonical(f),
            "complexity": c.get("complexity") or _safe_complexity(f),
            "rationale": c.get("rationale", ""),
        }
        # eval_error is consumed here; prefilter re-sets it if this formula also
        # fails to evaluate.
        return {"candidate": cand, "variant_count": vc, "eval_error": None}

    # -- S5: pre-filter (free, code) ----------------------------
    def prefilter(state: AlphaResearchState) -> dict:
        f = state["candidate"]["formula"]
        reasons: list[str] = []
        parses = True
        try:
            parse(f, strict=True)
        except ParseError as exc:
            parses = False
            reasons.append(f"parse:{exc}")
        cx = state["candidate"]["complexity"]
        if (cx.get("nodes", 0) > COMPLEXITY_MAX_NODES
                or cx.get("depth", 0) > COMPLEXITY_MAX_DEPTH
                or cx.get("free_params", 0) > COMPLEXITY_MAX_PARAMS):
            reasons.append(f"complexity:{cx}")
        zoo_match = None
        if parses:
            try:
                dup, zoo_match = _zoo.is_zoo_duplicate(f, threshold=ZOO_DUP_THRESHOLD)
                if dup:
                    reasons.append(f"zoo_duplicate:{zoo_match}")
            except Exception:  # noqa: BLE001
                pass
        repeat = ctx.memory.formulas.seen_exact(f)
        ctx.memory.formulas.record(f, outcome="prefiltered")

        # dry-run evaluation — a formula can parse yet still be un-evaluable
        # (wrong operator arity, a missing `sector` arg, an undefined field).
        # Catch it HERE, before a Tier-1 trial is spent, and hand it back to the
        # Coder with the exact error rather than scoring it NaN.
        eval_err: str | None = None
        if parses and not reasons:
            try:
                evaluate_signal(f, ctx.price_panel)
            except SignalEvalError as exc:
                eval_err = str(exc)

        stall = int(state.get("stall_count", 0))
        at_cap = int(state.get("variant_count", 0)) >= MAX_VARIANTS
        if reasons:
            decision = "reject"
        elif eval_err and not at_cap and stall + 1 < STALL_LIMIT:
            decision = "repair"
            stall += 1
        elif eval_err:
            # out of stall budget (or at the cap) — this dead formula is a reject
            decision = "reject"
            reasons.append(f"does not evaluate: {eval_err}")
        elif repeat and not at_cap and stall + 1 < STALL_LIMIT:
            decision = "repeat"
            stall += 1
        else:
            decision = "ok"
        out: dict = {
            "prefilter": {"decision": decision, "reasons": reasons, "zoo_match": zoo_match,
                          "repeat": repeat, "eval_error": eval_err},
            "stall_count": stall,
        }
        if decision in ("repeat", "repair"):
            # not a genuine new variant — hand the slot back so the cap counts
            # real attempts only (``stall_count`` still bounds the loop).  A
            # verbatim repeat only bites the mock; ``repair`` bites a real LLM
            # that mis-called an operator.
            out["variant_count"] = max(0, int(state.get("variant_count", 0)) - 1)
        if decision == "repair":
            out["eval_error"] = eval_err
            ctx.report_lines.append(f"[prefilter] repair: {f!r} -> {eval_err}")
        if decision == "reject":
            out["verdict"] = "reject"
            out["reject_reason"] = "pre-filter: " + "; ".join(reasons)
        return out

    # -- S6: Tier-1 backtest on VAL_A (counts as a trial) ------
    def tier1(state: AlphaResearchState) -> dict:
        pre = _pre_sign(state)
        f = state["candidate"]["formula"]
        try:
            sig = evaluate_signal(f, ctx.price_panel)
            m = _bt.backtest(sig, "val_a", horizon=ctx.horizon)
        except SignalEvalError as exc:
            ctx.report_lines.append(f"[tier1] {f!r} did not evaluate: {exc}")
            m = _bt_empty()
        oic = float(m["rank_ic"]) * pre if np.isfinite(m["rank_ic"]) else float("nan")
        ctx.ledger.record_trial(
            state["thesis_id"], state.get("pre_registered", {}).get("hash"),
            state["candidate"]["ast_canonical"], "val_a",
            m["rank_ic"], m["sharpe"], m["t_stat"], m["n_days"],
            counts_as_trial=1, rejection_reason="tier1_variant",
        )
        item = {
            "formula": f, "ast": state["candidate"]["ast_canonical"],
            "variant": int(state["variant_count"]),
            "rank_ic": _num(m["rank_ic"]), "oriented_ic": _num(oic),
            "t_stat": _num(m["t_stat"]), "sharpe": _num(m["sharpe"]),
        }
        best = state.get("best_variant")
        new_best = best
        if _viable(item, pre) and (not _viable(best, pre)
                                   or item["oriented_ic"] > best["oriented_ic"]):
            new_best = item
        elif best is None:
            new_best = item
        return {"tier1_metrics": m, "population": [item], "best_variant": new_best}

    # -- S5: Judge --------------------------------------------
    def judge(state: AlphaResearchState) -> dict:
        j = A["judge"].run(
            metrics=state.get("tier1_metrics", {}), thesis=state["thesis"],
            iteration=int(state["variant_count"]) - 1,
        )
        return {"judge": j, "edit_motif": j.get("edit_motif") or state.get("edit_motif")}

    # -- variant-cap forced decision -------------------------
    def force_decision(state: AlphaResearchState) -> dict:
        pre = _pre_sign(state)
        best = state.get("best_variant")
        ctx.report_lines.append(
            f"[cap] thesis {state.get('thesis_id')} hit the {MAX_VARIANTS}-variant "
            f"cap; best oriented RankIC="
            f"{(best or {}).get('oriented_ic')}"
        )
        if _viable(best, pre):
            return {"promoted": best, "forced_promote": True}
        return {"verdict": "reject", "forced_promote": True,
                "reject_reason": f"variant cap ({MAX_VARIANTS}) reached with no viable variant"}

    # -- S6: fresh-fold confirmation on VAL_B ---------------
    def freshfold(state: AlphaResearchState) -> dict:
        pre = _pre_sign(state)
        best = state.get("promoted") or state.get("best_variant")
        ctx.mark_promote(state["thesis_id"])          # BEFORE the first VAL_B call
        try:
            sig = evaluate_signal(best["formula"], ctx.price_panel)
            m = _bt.backtest(sig, "val_b", horizon=ctx.horizon)
        except SignalEvalError as exc:
            ctx.report_lines.append(f"[freshfold] {exc}")
            m = _bt_empty()
        oic = float(m["rank_ic"]) * pre if np.isfinite(m["rank_ic"]) else float("nan")
        holds = np.isfinite(oic) and oic > 0 and abs(float(m["t_stat"])) >= FRESHFOLD_MIN_T
        out = {"fresh_fold_metrics": m}
        if not holds:
            out["verdict"] = "reject"
            out["reject_reason"] = (
                f"fresh fold: VAL_B oriented RankIC={oic:.4f} "
                f"(t={_num(m['t_stat'])}) did not hold"
            )
        return out

    # -- S6/S7: Tier-2 + orthogonalisation ----------------
    def tier2(state: AlphaResearchState) -> dict:
        best = state.get("promoted") or state.get("best_variant")
        try:
            sig = evaluate_signal(best["formula"], ctx.price_panel)
        except SignalEvalError:
            return {"tier2_metrics": _bt_empty()}
        book = ctx.memory.book.get_book()
        try:
            resid = _gates.orthogonalize(sig, book)
        except Exception:  # noqa: BLE001
            resid = sig
        m_full = _bt.backtest(sig, "val_a", horizon=ctx.horizon)
        m_net = _bt.backtest(resid, "val_a", horizon=ctx.horizon, cost_bps=COST_BPS_DEFAULT)
        ctx.ledger.record_trial(
            state["thesis_id"], state.get("pre_registered", {}).get("hash"),
            best.get("ast"), "val_a", m_net["rank_ic"], m_net["sharpe"],
            m_net["t_stat"], m_net["n_days"],
            counts_as_trial=1, rejection_reason="tier2_finalist",
        )
        return {"tier2_metrics": {
            **m_full,
            "residual_rank_ic": _num(m_net["rank_ic"]),
            "net_sharpe_15bps": _num(m_net["sharpe"]),
        }}

    # -- S7: Gate B — NOVELTY (free; runs BEFORE statistics) --
    def gate_b_novelty(state: AlphaResearchState) -> dict:
        ctx.record(kind="gate_step", step="novelty", thesis_id=state["thesis_id"])
        pre = _pre_sign(state)
        best = state.get("promoted") or state.get("best_variant")
        # guarded like freshfold/tier2: a formula that stops evaluating rejects
        # the candidate instead of crashing the whole graph mid-generation.
        try:
            sig = evaluate_signal(best["formula"], ctx.price_panel)
        except SignalEvalError as exc:
            ctx.report_lines.append(f"[gate_b_novelty] {exc}")
            return {"verdict": "reject",
                    "reject_reason": f"Gate B novelty: signal did not evaluate ({exc})"}
        book = ctx.memory.book.get_book()
        mi = _gates.marginal_ic(sig, book, split="val_a", horizon=ctx.horizon)
        realized = 1 if (np.isfinite(mi) and mi > 0) else -1
        novel = np.isfinite(mi) and abs(mi) >= _gates.MIN_MARGINAL_IC
        sign_ok = _gates.check_sign(pre, realized)
        out = {"gate_b_novelty": {"marginal_ic": _num(mi), "realized_sign": realized,
                                  "novel": bool(novel), "sign_ok": bool(sign_ok)}}
        if not novel:
            out["verdict"] = "reject"
            out["reject_reason"] = (
                f"Gate B novelty: |marginal_ic|={abs(mi):.4f} < {_gates.MIN_MARGINAL_IC} "
                f"(clone / no marginal information)"
            )
        elif not sign_ok:
            out["verdict"] = "reject"
            out["reject_reason"] = (
                f"Gate B: pre-registered sign {pre:+d} != realised {realized:+d} "
                f"(thesis failure — hard reject)"
            )
        return out

    # -- S7: Gate B — STATISTICS (spends a holdout peek) --
    def gate_b_stats(state: AlphaResearchState) -> dict:
        ctx.record(kind="gate_step", step="statistics", thesis_id=state["thesis_id"])
        best = state.get("promoted") or state.get("best_variant")
        # reject before `gates.gate_b` is reached, so a dead formula cannot burn
        # the irreplaceable holdout peek.
        try:
            sig = evaluate_signal(best["formula"], ctx.price_panel)
        except SignalEvalError as exc:
            ctx.report_lines.append(f"[gate_b_stats] {exc}")
            return {"verdict": "reject",
                    "reject_reason": f"Gate B statistics: signal did not evaluate ({exc})"}
        book = ctx.memory.book.get_book()
        card = _build_card(state, ctx, verdict="provisional")
        verdict, reasons, audit = _gates.gate_b(
            card, book, ctx.ledger, signal=sig, split="val_a",
            horizon=ctx.horizon, do_holdout_peek=ctx.do_holdout_peek,
        )
        out = {"gate_b_audit": audit}
        if verdict != "accept":
            out["verdict"] = "reject"
            out["reject_reason"] = "Gate B statistics: " + "; ".join(reasons)
        return out

    # -- S8: Gate C — Red-Team ---------------------------
    def gate_c_redteam(state: AlphaResearchState) -> dict:
        pre = _pre_sign(state)
        best = state.get("promoted") or state.get("best_variant")
        formula = best["formula"]
        sig = evaluate_signal(formula, ctx.price_panel)
        sel = A["redteam"].run(
            thesis=state["thesis"], formula=formula,
            metrics=state.get("tier1_metrics", {}),
        )
        report = _redteam.run_redteam(
            sig, [t for t in sel.get("tests", []) if t in RED_TEAM_MENU] or None,
            split="val_a", horizon=ctx.horizon, sign=pre,
            thesis=state["thesis"], formula=formula,
            prices=ctx.prices, liquidity_ranks=ctx.liquidity_ranks,
            ledger=ctx.ledger, thesis_id=state["thesis_id"],
            formula_hash=state.get("pre_registered", {}).get("hash"),
            canonical_ast=best.get("ast"),
        )
        # curriculum — mandatory regime slice, rotated by generation
        curr_flags: list[dict] = []
        for sub in state.get("mandatory_regimes", []):
            m = _bt.backtest(sig, "val_a", horizon=ctx.horizon, subsample=sub)
            ctx.ledger.record_trial(
                state["thesis_id"], state.get("pre_registered", {}).get("hash"),
                best.get("ast"), "val_a", m["rank_ic"], m["sharpe"], m["t_stat"],
                m["n_days"], counts_as_trial=0, rejection_reason=f"curriculum:{sub}",
            )
            oic = float(m["rank_ic"]) * pre if np.isfinite(m["rank_ic"]) else float("nan")
            if not (np.isfinite(oic) and oic > 0):
                curr_flags.append(sub)

        survived = report["verdict"] == "survives" and not curr_flags
        out = {"redteam_report": {**report, "curriculum_flags": curr_flags}}
        if not survived:
            out["verdict"] = "reject"
            out["reject_reason"] = (
                f"Gate C red-team: failed={report.get('failed_tests')} "
                f"curriculum={curr_flags}"
            )
        return out

    # -- emit the accepted card ------------------------
    def emit_card(state: AlphaResearchState) -> dict:
        card = _build_card(state, ctx, verdict="accept")
        validate_card(card)
        ctx.memory.cards.save_card(card)
        best = state.get("promoted") or state.get("best_variant")
        try:
            sig = evaluate_signal(best["formula"], ctx.price_panel)
            ctx.memory.book.add_to_book(card["card_id"], sig)
        except SignalEvalError:  # pragma: no cover
            pass
        ctx.accepted.append(card["card_id"])
        ctx.report_lines.append(f"[accept] {card['card_id']}  formula={best['formula']}")
        return {"card": card, "verdict": "accept"}

    # -- S9: Reflection & memory ---------------------
    def reflect(state: AlphaResearchState) -> dict:
        verdict = state.get("verdict") or "reject"
        delta = _best_delta(state.get("population", []))
        motif = state.get("edit_motif") or "promote_as_is"
        # LLM call first: a BudgetExhausted here leaves memory untouched.
        rf = A["reflection"].run(
            family=state.get("family", "liquidity"),
            edit_motif=motif, helped=delta > 0, rank_ic_delta=delta,
            parent_context=f"{state.get('family', '')} factor",
            outcome=verdict, memory=ctx.memory,
        )
        # A failed memory write used to be swallowed silently, which is how the
        # live_explore run finished with n_pulls=0 on every bandit arm and no
        # lessons — three generations that could not learn from each other.
        for err in (rf.get("applied", {}) or {}).get("errors", []):
            ctx.report_lines.append(f"[reflect] MEMORY WRITE FAILED — {err}")
        # a rejected candidate with a formula is still written as a (reject) card
        if verdict != "accept" and state.get("candidate"):
            try:
                rc = _build_card(state, ctx, verdict="reject")
                validate_card(rc)
                ctx.memory.cards.save_card(rc)
            except Exception as exc:  # noqa: BLE001
                ctx.report_lines.append(f"[reflect] could not save reject card: {exc}")
        ctx.report_lines.append(
            f"[gen {state.get('generation')}] {state.get('family')} -> {verdict}"
            + (f"  ({state.get('reject_reason')})" if verdict != "accept" else "")
        )
        return {"verdict": verdict}

    return {
        "orchestrate": orchestrate, "retrieve": retrieve, "brief": brief,
        "ideate": ideate, "gate_a_economics": gate_a_economics, "code": code,
        "prefilter": prefilter, "tier1": tier1, "judge": judge,
        "force_decision": force_decision, "freshfold": freshfold, "tier2": tier2,
        "gate_b_novelty": gate_b_novelty, "gate_b_stats": gate_b_stats,
        "gate_c_redteam": gate_c_redteam, "emit_card": emit_card, "reflect": reflect,
    }


def _bt_empty() -> dict:
    return {
        "rank_ic": float("nan"), "ic": float("nan"), "icir": float("nan"),
        "t_stat": float("nan"), "sharpe": float("nan"), "ann_return": float("nan"),
        "turnover": float("nan"), "mdd": float("nan"), "n_days": 0, "n_obs": 0,
        "decay": {h: float("nan") for h in HORIZONS}, "sign": 0,
    }


def _safe_canonical(f: str) -> str:
    try:
        return canonical(f, strict=False)
    except Exception:  # noqa: BLE001
        return str(f)


def _safe_complexity(f: str) -> dict:
    try:
        return complexity(f, strict=False)
    except Exception:  # noqa: BLE001
        return {"nodes": 0, "depth": 0, "free_params": 0}


# ═════════════════════════════════════════════════════════════════════════════
#  Routers (conditional edges — read state, return the next node name)
# ═════════════════════════════════════════════════════════════════════════════
def _route_gate_a(state: AlphaResearchState) -> str:
    return "reflect" if state.get("verdict") == "reject" else "code"


def _route_after_code(state: AlphaResearchState) -> str:
    # The 20th variant still gets scored (prefilter -> tier1 -> judge); the
    # `judge` / `prefilter` routers then divert once the count HAS reached the
    # cap.  This guard only fires on the impossible 21st entry.
    if int(state.get("variant_count", 0)) > MAX_VARIANTS:
        return "force_decision"
    return "prefilter"


def _route_prefilter(state: AlphaResearchState) -> str:
    d = state["prefilter"]["decision"]
    if d == "reject":
        return "reflect"
    if d in ("repeat", "repair"):
        return "force_decision" if int(state.get("variant_count", 0)) >= MAX_VARIANTS else "code"
    return "tier1"


def _route_judge(state: AlphaResearchState) -> str:
    if int(state.get("variant_count", 0)) >= MAX_VARIANTS:
        return "force_decision"
    if state.get("judge", {}).get("action") == "promote":
        return "freshfold"
    return "code"


def _route_force_decision(state: AlphaResearchState) -> str:
    return "reflect" if state.get("verdict") == "reject" else "freshfold"


def _route_freshfold(state: AlphaResearchState) -> str:
    return "reflect" if state.get("verdict") == "reject" else "tier2"


def _route_gate_b_novelty(state: AlphaResearchState) -> str:
    return "reflect" if state.get("verdict") == "reject" else "gate_b_stats"


def _route_gate_b_stats(state: AlphaResearchState) -> str:
    return "reflect" if state.get("verdict") == "reject" else "gate_c_redteam"


def _route_gate_c(state: AlphaResearchState) -> str:
    return "reflect" if state.get("verdict") == "reject" else "emit_card"


# ═════════════════════════════════════════════════════════════════════════════
#  Graph builder — ONE thesis lifecycle (orchestrate -> ... -> reflect -> END)
# ═════════════════════════════════════════════════════════════════════════════
def build_graph(ctx: RunContext, checkpointer: Any = None):
    """Compile the per-thesis LangGraph.

    The spec's diagram shows ``reflect -> should_continue -> orchestrate | END``
    as a cycle; here the graph is **one thesis** and the
    ``reflect -> should_continue -> orchestrate`` cycle is the *outer* loop
    (:func:`run_loop`) — which is precisely what "so the outer loop can pause and
    resume" describes, and it keeps every graph invocation bounded (~90
    super-steps) and checkpoint/resume clean.  See reports/p10_handoff.md §7.
    """
    if not _HAVE_LANGGRAPH:  # pragma: no cover
        raise RuntimeError("langgraph is required for Phase 10 (Section 0.2)")

    nodes = _make_nodes(ctx)
    g = StateGraph(AlphaResearchState)
    for name, fn in nodes.items():
        g.add_node(name, fn)

    g.add_edge(START, "orchestrate")
    g.add_edge("orchestrate", "retrieve")
    g.add_edge("retrieve", "brief")
    g.add_edge("brief", "ideate")
    g.add_edge("ideate", "gate_a_economics")
    g.add_conditional_edges("gate_a_economics", _route_gate_a,
                            {"code": "code", "reflect": "reflect"})
    g.add_conditional_edges("code", _route_after_code,
                            {"prefilter": "prefilter", "force_decision": "force_decision"})
    g.add_conditional_edges("prefilter", _route_prefilter,
                            {"tier1": "tier1", "code": "code",
                             "force_decision": "force_decision", "reflect": "reflect"})
    g.add_edge("tier1", "judge")
    g.add_conditional_edges("judge", _route_judge,
                            {"code": "code", "freshfold": "freshfold",
                             "force_decision": "force_decision"})
    g.add_conditional_edges("force_decision", _route_force_decision,
                            {"freshfold": "freshfold", "reflect": "reflect"})
    g.add_conditional_edges("freshfold", _route_freshfold,
                            {"tier2": "tier2", "reflect": "reflect"})
    g.add_edge("tier2", "gate_b_novelty")
    g.add_conditional_edges("gate_b_novelty", _route_gate_b_novelty,
                            {"gate_b_stats": "gate_b_stats", "reflect": "reflect"})
    g.add_conditional_edges("gate_b_stats", _route_gate_b_stats,
                            {"gate_c_redteam": "gate_c_redteam", "reflect": "reflect"})
    g.add_conditional_edges("gate_c_redteam", _route_gate_c,
                            {"emit_card": "emit_card", "reflect": "reflect"})
    g.add_edge("emit_card", "reflect")
    g.add_edge("reflect", END)

    return g.compile(checkpointer=checkpointer)


# ═════════════════════════════════════════════════════════════════════════════
#  Portfolio post-process  (NOT a graph node — runs once after the graph ends)
# ═════════════════════════════════════════════════════════════════════════════
def portfolio_combine(
    memory: Memory, *, split: str = "val_a", horizon: int = 5,
    panel: tuple[pd.DataFrame, pd.DataFrame] | None = None,
) -> dict:
    """Combine the accepted book once the loop has terminated.

    Returns a dict with the correlation matrix, an inverse-correlation weighting,
    and combined-vs-individual RankIC.  If fewer than two cards were accepted it
    says so plainly (Phase 11 owns the full portfolio report / regime gating).
    """
    wide = memory.book.get_book_wide()
    names = sorted(wide)
    if len(names) < 2:
        return {"status": "insufficient", "n_accepted": len(names),
                "note": "fewer than 2 accepted cards — no combination performed "
                        "(Phase 11 demonstrates the mechanism on a synthetic set)"}

    ics = {}
    daily = {}
    for n in names:
        ser = _gates.daily_rank_ic(wide[n], split, horizon, panel=panel)
        daily[n] = ser
        ics[n] = float(ser.mean()) if len(ser) else float("nan")

    D = pd.DataFrame(daily).dropna(how="all")
    corr = D.corr()
    # inverse-average-|correlation| weights
    inv = {}
    for n in names:
        c = corr[n].drop(n).abs().mean()
        inv[n] = 1.0 / (c + 1e-6) if np.isfinite(c) else 1.0
    tot = sum(inv.values())
    weights = {n: inv[n] / tot for n in names}

    combined = sum(D[n] * weights[n] for n in names).dropna()
    combined_ic = float(combined.mean()) if len(combined) else float("nan")
    return {
        "status": "ok",
        "n_accepted": len(names),
        "individual_rank_ic": ics,
        "correlation_matrix": corr.round(4).to_dict(),
        "weights": weights,
        "combined_rank_ic": combined_ic,
        "beats_best_individual": bool(
            np.isfinite(combined_ic)
            and combined_ic >= max(v for v in ics.values() if np.isfinite(v))
        ),
    }


# ═════════════════════════════════════════════════════════════════════════════
#  RunResult
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class RunResult:
    status: str                       # "completed" | "paused_budget" | "stopped_early"
    stopped_reason: str
    generations: list                 # per-generation outcome dicts
    accepted_card_ids: list
    n_trials: int
    holdout_peeks_used: int
    t_stat_bar_final: float
    min_marginal_ic_final: float
    portfolio: dict
    recorder: list
    report_path: str
    state_digest: str

    # ---- assertions the acceptance tests lean on ------------------
    def max_variant_count(self) -> int:
        return max((g.get("variant_count", 0) for g in self.generations), default=0)

    def val_b_before_promote(self) -> bool:
        """True iff any thesis touched VAL_B before *its own* promote.

        Checked per thesis, not run-wide: once any thesis has promoted, a
        run-global ``min(val_b) > first_promote`` test would wave through a later
        thesis that reached VAL_B without ever promoting — exactly the regression
        this is meant to catch.
        """
        promote_at: dict[str, int] = {}
        for e in self.recorder:
            if e["kind"] == "promote":
                promote_at.setdefault(e["thesis_id"], e["seq"])
        for e in self.recorder:
            if e["kind"] != "backtest" or e["split"] != "val_b":
                continue
            p = promote_at.get(e.get("thesis_id"))
            if p is None or e["seq"] < p:
                return True          # VAL_B with no promote, or before it
        return False

    def novelty_always_before_stats(self) -> bool:
        steps = [e for e in self.recorder if e["kind"] == "gate_step"]
        by_thesis: dict[str, list[str]] = {}
        for e in steps:
            by_thesis.setdefault(e["thesis_id"], []).append(e["step"])
        for seq in by_thesis.values():
            if "statistics" in seq:
                if "novelty" not in seq[: seq.index("statistics")]:
                    return False
        return True

    def holdout_only_with_token(self) -> bool:
        return all(e.get("has_token") for e in self.recorder
                   if e["kind"] == "backtest" and e["split"] == "holdout")


# ═════════════════════════════════════════════════════════════════════════════
#  The outer research loop
# ═════════════════════════════════════════════════════════════════════════════
def run_loop(
    *,
    run_id: str = "run",
    max_generations: int = 20,
    checkpoint_path: str | Path | None = None,
    price_panel: dict | None = None,
    memory: Memory | None = None,
    ledger: Ledger | None = None,
    agents: dict | None = None,
    llm_mode: str | None = None,
    horizon: int = 5,
    curriculum_every: int = CURRICULUM_EVERY_DEFAULT,
    fdr_provider: Callable[[list], float] | None = None,
    stop_epsilon: float = STOP_EPSILON_DEFAULT,
    stop_k: int = STOP_K_DEFAULT,
    do_holdout_peek: bool = True,
    prices: pd.DataFrame | None = None,
    liquidity_ranks: pd.DataFrame | None = None,
    resume: bool = False,
    stop_after_generation: int | None = None,
    large_budget: TokenBudget | None = None,
    small_budget: TokenBudget | None = None,
    report_path: str | Path | None = None,
    throttle: bool = True,
) -> RunResult:
    """Drive the nine-stage loop for up to ``max_generations`` theses.

    Stop rule (whichever fires first): token budget exhausted · ``stop_k``
    consecutive generations adding < ``stop_epsilon`` novelty-adjusted marginal
    IC · the hard generation cap.  ``resume=True`` continues from the last
    checkpoint (used to span the ~20-thesis/day free-tier ceiling).
    """
    np.random.seed(_config.RANDOM_SEED)
    random.seed(_config.RANDOM_SEED)

    ckpt_path = Path(checkpoint_path) if checkpoint_path else DEFAULT_CHECKPOINT
    rep_path = Path(report_path) if report_path else DEFAULT_REPORT
    saver = SqliteSaver(ckpt_path)

    # -- gate thresholds: snapshot so we can restore them after the run -----
    _t0, _mi0 = _gates.T_STAT_BAR, _gates.MIN_MARGINAL_IC
    t_bar, mi_floor = _t0, _mi0

    mem = memory or Memory()
    for f in FAMILIES:
        mem.bandit.register_family(f)
    led = ledger or Ledger(_config.LEDGER_DB)

    restored = saver.load_run_state() if resume else None
    generations: list = []
    accepted: list = []
    start_gen = 0
    resume_incomplete: int | None = None
    if restored and restored.get("run_id") == run_id:
        generations = restored.get("generations", [])
        accepted = restored.get("accepted_card_ids", [])
        start_gen = int(restored.get("next_gen", 0))
        resume_incomplete = restored.get("incomplete_gen")
        t_bar = float(restored.get("t_stat_bar", _t0))
        mi_floor = float(restored.get("min_marginal_ic", _mi0))
        _gates.T_STAT_BAR, _gates.MIN_MARGINAL_IC = t_bar, mi_floor

    # -- agents / token budgets -------------------------------------------
    if agents is None:
        lb = large_budget
        sb = small_budget
        if resume and restored:
            lb = lb or TokenBudget("large", cap=_config.LLM_TPD_CAP["large"],
                                   used=int(restored.get("large_used", 0)),
                                   day=restored.get("budget_day"))
            sb = sb or TokenBudget("small", cap=_config.LLM_TPD_CAP["small"],
                                   used=int(restored.get("small_used", 0)),
                                   day=restored.get("budget_day"))
        client_kw: dict = {}
        if not throttle:
            # tests / offline demo: keep the TPM/RPM accounting but never actually
            # sleep (the real run leaves throttle=True so the free tier is respected).
            client_kw["sleep"] = lambda _s: None
        agents = build_agents(mode=llm_mode, memory=mem, probe=True,
                              large_budget=lb, small_budget=sb, **client_kw)

    price_panel = price_panel or build_price_panel()

    ctx = RunContext(
        run_id=run_id, memory=mem, ledger=led, agents=agents,
        price_panel=price_panel, horizon=horizon, do_holdout_peek=do_holdout_peek,
        prices=prices, liquidity_ranks=liquidity_ranks,
    )
    ctx.report_lines.append(f"# Phase 10 loop — run_id={run_id}  started {_utcnow_iso()}")

    fdr_fn = fdr_provider or (lambda gens: rolling_fdr(gens))
    status, reason = "completed", "reached generation cap"

    with _BacktestInstrument(ctx):
        graph = build_graph(ctx, checkpointer=saver)

        gen = start_gen
        while gen < max_generations:
            ctx._current_gen = gen
            cfg = {"configurable": {"thread_id": f"{run_id}:g{gen}"},
                   "recursion_limit": RECURSION_LIMIT}
            init_state: AlphaResearchState = {
                "generation": gen,
                "budget_tokens_left": _budget_left(agents),
                "variant_count": 0, "stall_count": 0,
                "mandatory_regimes": curriculum_regimes(gen, curriculum_every),
            }
            try:
                if resume_incomplete == gen:
                    final = graph.invoke(None, cfg)      # continue the interrupted thesis
                    resume_incomplete = None
                else:
                    final = graph.invoke(init_state, cfg)
            except BudgetExhausted as exc:
                ctx.report_lines.append(
                    f"[budget] {exc}  — checkpointing gen {gen} for tomorrow"
                )
                _save_run_state(saver, run_id, generations, gen, gen, t_bar,
                                mi_floor, accepted, agents)
                status, reason = "paused_budget", str(exc)
                break

            g_out = _generation_outcome(gen, final, ctx)
            generations.append(g_out)
            if g_out["verdict"] == "accept":
                accepted.append(final.get("card", {}).get("card_id"))

            # -- FDR auto-tightening meta-check --------------------------
            fdr = float(fdr_fn(generations))
            g_out["rolling_fdr"] = fdr
            t_bar, mi_floor = maybe_tighten_gates(fdr, t_bar, mi_floor, ctx.report_lines)
            g_out["t_stat_bar"] = t_bar

            _save_run_state(saver, run_id, generations, gen + 1, None, t_bar,
                            mi_floor, accepted, agents)

            # -- stop rules ------------------------------------------
            if stop_after_generation is not None and gen + 1 >= stop_after_generation:
                status, reason = "stopped_early", "stop_after_generation hook"
                gen += 1
                break
            if _diminishing_returns(generations, stop_k, stop_epsilon):
                status, reason = "stopped_early", (
                    f"{stop_k} consecutive generations added < {stop_epsilon} "
                    f"novelty-adjusted marginal IC"
                )
                gen += 1
                break
            gen += 1

    # -- portfolio: once, after the graph terminates (NOT a node) ---------
    portfolio = portfolio_combine(mem, split="val_a", horizon=horizon)
    ctx.report_lines.append(f"[portfolio] {json.dumps(portfolio, default=str)[:400]}")

    digest = _state_digest(run_id, generations, accepted, t_bar, led)
    _write_report(rep_path, ctx, status, reason, generations, accepted, portfolio,
                  t_bar, mi_floor, digest)

    # -- restore process-global gate thresholds --------------------------
    _gates.T_STAT_BAR, _gates.MIN_MARGINAL_IC = _t0, _mi0
    result = RunResult(
        status=status, stopped_reason=reason, generations=generations,
        accepted_card_ids=[c for c in accepted if c],
        n_trials=led.n_trials(), holdout_peeks_used=led.holdout_peeks_used(),
        t_stat_bar_final=t_bar, min_marginal_ic_final=mi_floor,
        portfolio=portfolio, recorder=ctx.recorder, report_path=str(rep_path),
        state_digest=digest,
    )
    saver.close()
    return result


# ═════════════════════════════════════════════════════════════════════════════
#  Outer-loop helpers
# ═════════════════════════════════════════════════════════════════════════════
def _budget_left(agents: dict) -> int:
    try:
        return min(a.client.budget.remaining() for a in agents.values())
    except Exception:  # noqa: BLE001
        return 0


def _generation_outcome(gen: int, final: AlphaResearchState, ctx: RunContext) -> dict:
    verdict = final.get("verdict") or "reject"
    nov = final.get("gate_b_novelty", {})
    audit = final.get("gate_b_audit", {})
    holdout_ic = audit.get("holdout_rank_ic")
    pre = int(final.get("pre_registered", {}).get("sign", 1) or 1)
    holdout_failed = bool(
        verdict == "accept" and holdout_ic is not None and np.isfinite(holdout_ic)
        and (1 if holdout_ic > 0 else -1) != pre
    )
    return {
        "generation": gen,
        "family": final.get("family"),
        "thesis_id": final.get("thesis_id"),
        "verdict": verdict,
        "reject_reason": final.get("reject_reason"),
        "variant_count": int(final.get("variant_count", 0)),
        "forced_promote": bool(final.get("forced_promote", False)),
        "marginal_ic": nov.get("marginal_ic"),
        "novelty_adjusted_marginal_ic": nov.get("marginal_ic") if verdict == "accept" else 0.0,
        "tier1_rank_ic": _num(final.get("tier1_metrics", {}).get("rank_ic")),
        "fresh_fold_rank_ic": _num(final.get("fresh_fold_metrics", {}).get("rank_ic")),
        "redteam_verdict": final.get("redteam_report", {}).get("verdict"),
        "holdout_rank_ic": _num(holdout_ic),
        "holdout_failed": holdout_failed,
        "mandatory_regimes": final.get("mandatory_regimes"),
    }


def _diminishing_returns(generations: list, k: int, eps: float) -> bool:
    if len(generations) < k:
        return False
    recent = generations[-k:]
    return all(abs(g.get("novelty_adjusted_marginal_ic") or 0.0) < eps for g in recent)


def _save_run_state(saver: SqliteSaver, run_id, generations, next_gen, incomplete_gen,
                    t_bar, mi_floor, accepted, agents) -> None:
    lb = sb = None
    day = None
    try:
        budgets = {a.client.budget.tier: a.client.budget for a in agents.values()}
        lb = budgets.get("large")
        sb = budgets.get("small")
        day = (lb or sb).day if (lb or sb) else None
    except Exception:  # noqa: BLE001
        pass
    saver.save_run_state({
        "run_id": run_id,
        "generations": generations,
        "next_gen": int(next_gen),
        "incomplete_gen": incomplete_gen,
        "accepted_card_ids": [c for c in accepted if c],
        "t_stat_bar": float(t_bar),
        "min_marginal_ic": float(mi_floor),
        "large_used": lb.used if lb else 0,
        "small_used": sb.used if sb else 0,
        "budget_day": day,
    })


def _state_digest(run_id, generations, accepted, t_bar, ledger: Ledger) -> str:
    import hashlib

    payload = {
        "run_id": run_id,
        "gens": [
            {k: g.get(k) for k in ("generation", "family", "verdict", "variant_count",
                                   "forced_promote", "redteam_verdict")}
            for g in generations
        ],
        "accepted": sorted(c for c in accepted if c),
        "t_stat_bar": round(float(t_bar), 4),
        "n_trials": ledger.n_trials(),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def _write_report(path: Path, ctx: RunContext, status, reason, generations, accepted,
                  portfolio, t_bar, mi_floor, digest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n_acc = len([c for c in accepted if c])
    lines = [
        f"# Phase 10 loop report — run_id={ctx.run_id}",
        "",
        f"- status: **{status}** ({reason})",
        f"- generations run: {len(generations)}",
        f"- accepted cards: {n_acc}",
        f"- trials (counts_as_trial=1): {ctx.ledger.n_trials()}",
        f"- holdout peeks used: {ctx.ledger.holdout_peeks_used()}",
        f"- final T_STAT_BAR: {t_bar}   final MIN_MARGINAL_IC: {mi_floor}",
        f"- state digest: `{digest}`",
        "",
        "## Per-generation",
        "",
        "| gen | family | verdict | variants | forced | redteam | reject reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for g in generations:
        lines.append(
            f"| {g['generation']} | {g.get('family')} | {g['verdict']} | "
            f"{g.get('variant_count')} | {g.get('forced_promote')} | "
            f"{g.get('redteam_verdict')} | {str(g.get('reject_reason') or '')[:80]} |"
        )
    lines += ["", "## Pre-registration log (sign hash stored before any backtest)", ""]
    for tid, h, when in ctx.prereg_log:
        lines.append(f"- `{tid}` {h[:23]}… — {when}")
    lines += ["", "## Portfolio (post-process, off-graph)", "",
              "```json", json.dumps(portfolio, indent=2, default=str)[:2000], "```",
              "", "## Event log tail", ""]
    for e in ctx.recorder[-40:]:
        lines.append(f"- {e}")
    lines += ["", "## Run log", ""] + [f"- {ln}" for ln in ctx.report_lines]
    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def _load_dotenv(path: str | Path = ".env") -> None:
    """Populate os.environ from a .env file.  Nothing else in the package reads
    it, so a live run had to be launched with the key already exported."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if v.strip():
            os.environ.setdefault(k.strip(), v.strip())


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(
        prog="python -m src.loop",
        description="Run the Phase-10 alpha research loop.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python -m src.loop --smoke
  python -m src.loop --mode live --generations 10 --run-id live_1
  python -m src.loop --mode live --run-id live_1 --resume
  python -m src.loop --mode live --run-id live_1 --resume --stop-after 3
""",
    )
    ap.add_argument("--run-id", default="run", help="run identifier (default: run)")
    ap.add_argument("--mode", default=None, choices=["mock", "live", "offline"],
                    help="LLM mode; overrides $LLM_MODE (default: $LLM_MODE or mock)")
    ap.add_argument("-n", "--generations", type=int, default=10,
                    help="max theses to attempt (default: 10)")
    ap.add_argument("--horizon", type=int, default=5,
                    help="forward-return horizon in days (default: 5)")
    ap.add_argument("--resume", action="store_true",
                    help="continue from the checkpoint for this run-id")
    ap.add_argument("--stop-after", type=int, default=None, metavar="N",
                    help="halt after N generations this invocation (use with "
                         "--resume to step one generation at a time)")
    ap.add_argument("--checkpoint", default=None, metavar="PATH",
                    help="checkpoint db (default: artifacts/<run-id>/ck.db)")
    ap.add_argument("--report", default=None, metavar="PATH",
                    help="markdown report (default: reports/<run-id>.md)")
    ap.add_argument("--no-holdout-peek", action="store_true",
                    help="never spend a holdout peek in Gate B")
    ap.add_argument("--no-throttle", action="store_true",
                    help="skip rate-limit sleeps (mock/offline only)")
    ap.add_argument("--stop-epsilon", type=float, default=STOP_EPSILON_DEFAULT,
                    help=f"marginal-IC increment below which a generation counts "
                         f"as lean (default: {STOP_EPSILON_DEFAULT}); pass a large "
                         f"negative number to disable the early stop")
    ap.add_argument("--stop-k", type=int, default=STOP_K_DEFAULT,
                    help=f"consecutive lean generations before halting "
                         f"(default: {STOP_K_DEFAULT})")
    ap.add_argument("--curriculum-every", type=int, default=CURRICULUM_EVERY_DEFAULT,
                    help="rotate the mandatory red-team regime every N generations")
    ap.add_argument("--sandbox", action="store_true",
                    help="use a throwaway memory/ledger instead of data/ — leaves "
                         "the real bandit, ledger and holdout-peek budget untouched")
    ap.add_argument("--synthetic", action="store_true",
                    help="use a synthetic price panel instead of data/panel")
    ap.add_argument("--smoke", action="store_true",
                    help="shorthand: --mode mock --synthetic --sandbox "
                         "--no-holdout-peek -n 2")
    ap.add_argument("--env-file", default=".env", metavar="PATH",
                    help="dotenv file to load before running (default: .env)")
    a = ap.parse_args(argv)

    if a.smoke:
        a.mode = a.mode or "mock"
        a.synthetic = a.sandbox = a.no_holdout_peek = True
        if a.generations == 10:
            a.generations = 2

    _load_dotenv(a.env_file)
    if a.mode:
        os.environ["LLM_MODE"] = a.mode
        importlib.reload(_config)

    if a.mode == "live" and not _config.GROQ_API_KEY:
        ap.error("--mode live needs GROQ_API_KEY (export it or put it in .env)")

    ck = Path(a.checkpoint) if a.checkpoint else (
        _config.REPO_ROOT / "artifacts" / a.run_id / "ck.db")
    ck.parent.mkdir(parents=True, exist_ok=True)
    report = Path(a.report) if a.report else _config.REPORTS_DIR / f"{a.run_id}.md"

    mem = led = None
    if a.sandbox:
        tmp = Path(tempfile.mkdtemp(prefix=f"{a.run_id}_"))
        mem, led = Memory(base_dir=tmp / "mem"), Ledger(tmp / "ledger.db")
        print(f"[sandbox] memory + ledger under {tmp}")

    panel = (synthetic_price_panel(n_days=700, n_symbols=20)
             if a.synthetic else build_price_panel())

    res = run_loop(
        run_id=a.run_id,
        max_generations=a.generations,
        checkpoint_path=ck,
        price_panel=panel,
        memory=mem,
        ledger=led,
        llm_mode=a.mode,
        horizon=a.horizon,
        resume=a.resume,
        stop_after_generation=a.stop_after,
        do_holdout_peek=not a.no_holdout_peek,
        throttle=not a.no_throttle,
        stop_epsilon=a.stop_epsilon,
        stop_k=a.stop_k,
        curriculum_every=a.curriculum_every,
        report_path=report,
    )
    print(f"status: {res.status} ({res.stopped_reason})")
    print(f"generations: {len(res.generations)} | accepted: {res.accepted_card_ids} "
          f"| trials: {res.n_trials} | peeks: {res.holdout_peeks_used}")
    for g in res.generations:
        print(f"  gen {g['generation']}  {str(g.get('family')):16s} "
              f"{g['verdict']:8s} {str(g.get('reject_reason') or '')[:90]}")
    print(f"report: {report}")
    return 0 if res.status != "error" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
