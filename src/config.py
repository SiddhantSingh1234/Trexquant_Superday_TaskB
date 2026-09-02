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
