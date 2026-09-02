"""Phase 0 — project constants, paths, and the canonical data split.

Single source of truth for: repository paths, the five split date ranges from
IMPLEMENTATION_PLAN.md Section 0.4, the tuning constants, and two split helpers
(`split_mask`, `assert_not_holdout`).

No business logic lives here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Paths                                                                        #
# --------------------------------------------------------------------------- #
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path = REPO_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
UNIVERSE_DIR: Path = DATA_DIR / "universe"
PRICES_DIR: Path = DATA_DIR / "prices"
PANEL_DIR: Path = DATA_DIR / "panel"

SRC_DIR: Path = REPO_ROOT / "src"
TESTS_DIR: Path = REPO_ROOT / "tests"
REPORTS_DIR: Path = REPO_ROOT / "reports"
CARDS_DIR: Path = REPO_ROOT / "artifacts" / "cards"
SLIDES_DIR: Path = REPO_ROOT / "slides"

LEDGER_DB: Path = DATA_DIR / "ledger.db"

# Phase 7 — memory stores.  Exact stores (formula index, card index, lineage)
# live in memory.db; the semantic lesson store is a physically separate file
# (data/lessons.db) so the two can never be confused for one another.
MEMORY_DB: Path = DATA_DIR / "memory.db"
LESSONS_DB: Path = DATA_DIR / "lessons.db"
BANDIT_STATE_JSON: Path = DATA_DIR / "bandit_state.json"
BOOK_PARQUET: Path = DATA_DIR / "book.parquet"

# Named artifact files (contract paths — downstream phases import these)
MEMBERSHIP_PARQUET: Path = UNIVERSE_DIR / "membership.parquet"
SYMBOLS_JSON: Path = UNIVERSE_DIR / "symbols.json"
OHLCV_PARQUET: Path = PRICES_DIR / "ohlcv.parquet"
FEATURES_PARQUET: Path = PANEL_DIR / "features.parquet"
LABELS_PARQUET: Path = PANEL_DIR / "labels.parquet"
SPLITS_JSON: Path = PANEL_DIR / "splits.json"

# --------------------------------------------------------------------------- #
# Tuning constants (IMPLEMENTATION_PLAN.md Phase 0 Outputs)                     #
# --------------------------------------------------------------------------- #
MAX_VARIANTS_PER_THESIS: int = 20
HOLDOUT_PEEK_BUDGET: int = 12
T_STAT_BAR: float = 3.0
COST_BPS_DEFAULT: int = 15
EMBARGO_DAYS: int = 5
RANDOM_SEED: int = 42

# --------------------------------------------------------------------------- #
# The canonical data split — Section 0.4                                       #
# --------------------------------------------------------------------------- #
# Inclusive [start, end] bounds, timezone-naive, normalized to midnight.
SPLITS: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {
    "warmup": (pd.Timestamp("2014-01-01"), pd.Timestamp("2014-12-31")),
    "train": (pd.Timestamp("2015-01-01"), pd.Timestamp("2017-12-31")),
    "val_a": (pd.Timestamp("2018-01-01"), pd.Timestamp("2021-06-30")),
    "val_b": (pd.Timestamp("2021-07-01"), pd.Timestamp("2022-06-30")),
    "holdout": (pd.Timestamp("2022-07-01"), pd.Timestamp("2025-12-31")),
}

# The plain dict form used by data/panel/splits.json (Section 0.5).
SPLITS_JSON_PAYLOAD: dict[str, list[str]] = {
    name: [lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d")]
    for name, (lo, hi) in SPLITS.items()
}

HOLDOUT_START: pd.Timestamp = SPLITS["holdout"][0]

# --------------------------------------------------------------------------- #
# Phase 8 — LLM agents: corpus paths, model routing, free-tier budget          #
# --------------------------------------------------------------------------- #
import os as _os  # noqa: E402  (kept local to this section)

CORPUS_DIR: Path = DATA_DIR / "corpus"
ANOMALIES_JSON: Path = CORPUS_DIR / "anomalies.json"
AGENT_PROMPTS_DIR: Path = SRC_DIR / "agents" / "prompts"
LLM_BUDGET_STATE_JSON: Path = DATA_DIR / "llm_budget_state.json"

# LLM_MODE: "mock" (offline canned responses — no key, the test default)
#         | "live"  (Groq free tier, needs GROQ_API_KEY)
#         | "offline" (local Ollama, zero-limit, no network egress)
LLM_MODE: str = (_os.environ.get("LLM_MODE", "mock").strip().lower() or "mock")
GROQ_API_KEY: str = _os.environ.get("GROQ_API_KEY", "").strip()
OLLAMA_HOST: str = _os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip()

# ⚠️ NEVER hard-code a model ID.  PRE_BUILD_TASKS.md T3: `llama-3.3-70b-versatile`
# and `llama-3.1-8b-instant` were reportedly deprecated 2026-06-17 (sources
# conflict with Groq's own models page).  Read the tier's ordered fallback chain
# from here and probe availability at startup, walking down the list.
LLM_MODEL_CHAINS: dict[str, tuple[str, ...]] = {
    "large": ("openai/gpt-oss-120b", "qwen/qwen3-32b", "llama-3.3-70b-versatile"),
    "small": ("openai/gpt-oss-20b", "llama-3.1-8b-instant", "llama-3.3-70b-versatile"),
    "offline": ("qwen2.5-7b", "llama3.1", "phi3"),
}

# Role -> model tier.  Hypothesis and Red-Team get the reasoning model; the
# high-volume cheap roles (Coder/Judge ~11 of 16.6 calls/thesis) get the small.
LLM_ROLE_TIER: dict[str, str] = {
    "hypothesis": "large", "redteam": "large",
    "coder": "small", "judge": "small", "reflection": "small",
    "planner": "small", "librarian": "small", "economics": "small",
}

# Free-tier limits per ORGANISATION (extra keys do not multiply capacity),
# PRE_BUILD_TASKS.md T3.  Conservative: the gpt-oss row (TPM 8k, TPD 200k).
# Tokens-per-day is the binding constraint, not requests.
LLM_TPM: dict[str, int] = {"large": 8_000, "small": 8_000, "offline": 1_000_000}
LLM_TPD_CAP: dict[str, int] = {"large": 200_000, "small": 200_000, "offline": 10_000_000}
LLM_RPM: dict[str, int] = {"large": 30, "small": 30, "offline": 600}

# The eight agent roles (deterministic code — backtester, stats, novelty — is NOT
# an agent and does not appear here).
AGENT_ROLES: tuple[str, ...] = (
    "planner", "librarian", "hypothesis", "economics",
    "coder", "judge", "redteam", "reflection",
)

# Measured projection (PRE_BUILD_TASKS.md T3 / IMPLEMENTATION_PLAN.md Phase 8):
# ~16.6 LLM calls and ~26,500 tokens per thesis.  ~20 theses/day is the ceiling.
LLM_TOKENS_PER_THESIS_PROJECTION: int = 26_500

# Composite regions the backtester (P4) accepts.
_COMPOSITE_REGIONS: dict[str, tuple[str, ...]] = {
    "train+val_a": ("train", "val_a"),
}

VALID_REGIONS: tuple[str, ...] = tuple(SPLITS) + tuple(_COMPOSITE_REGIONS)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _as_datetime_index(dates) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def split_mask(dates, region: str) -> np.ndarray:
    """Boolean mask selecting rows of `dates` that fall inside `region`.

    `region` is one of SPLITS ("warmup"|"train"|"val_a"|"val_b"|"holdout") or a
    composite ("train+val_a"). Bounds are inclusive on both ends.
    """
    if region not in VALID_REGIONS:
        raise ValueError(
            f"unknown split region {region!r}; valid: {sorted(VALID_REGIONS)}"
        )
    idx = _as_datetime_index(dates)

    if region in _COMPOSITE_REGIONS:
        parts = _COMPOSITE_REGIONS[region]
    else:
        parts = (region,)

    mask = np.zeros(len(idx), dtype=bool)
    for part in parts:
        lo, hi = SPLITS[part]
        mask |= (idx >= lo) & (idx <= hi)
    return mask


def assert_not_holdout(dates) -> None:
    """Tripwire: raise if any of `dates` falls on/after the HOLDOUT start.

    Call this defensively in any phase that must never observe holdout rows.
    """
    idx = _as_datetime_index(dates)
    offending = idx[idx >= HOLDOUT_START]
    if len(offending) > 0:
        sample = ", ".join(d.strftime("%Y-%m-%d") for d in offending[:5])
        raise AssertionError(
            f"HOLDOUT violation: {len(offending)} date(s) on/after "
            f"{HOLDOUT_START.strftime('%Y-%m-%d')} reached non-holdout code "
            f"(e.g. {sample}). HOLDOUT is sealed — only Phase 6's rationed-peek "
            f"API may read it."
        )
