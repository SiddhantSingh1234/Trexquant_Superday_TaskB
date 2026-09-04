"""Precompute the small dashboard aggregates into ``data/dashboard/*.parquet``.

D0 ships the ``@builder(name)`` registry, the CLI (``--only`` / ``--heavy`` /
``--check`` / ``--list``), the ``_manifest.json`` writer, and TWO fully
implemented reference builders (``corpus_family_counts``, ``agents_token_budget``
— both cheap, no heavy source).  D1 implements every other cheap builder.

Contract for a builder function
-------------------------------
* takes no arguments, returns a ``pd.DataFrame`` matching
  ``fixtures.CACHE_SCHEMAS[name]``.
* if a source artifact is missing, return an EMPTY schema-correct frame with
  ``df.attrs["status"] = "no_source"`` — never raise.
* determinism: seed once (``src.config.RANDOM_SEED``); a re-run is stable-sorted
  identical.

Usage
-----
    python dashboard/build_cache.py                 # every cheap builder
    python dashboard/build_cache.py --only a,b      # just those
    python dashboard/build_cache.py --heavy         # + the opt-in heavy builders
    python dashboard/build_cache.py --list          # print the registry
    python dashboard/build_cache.py --check         # verify manifest vs disk/schema
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.lib import fixtures  # noqa: E402
from src.config import RANDOM_SEED  # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "dashboard"
MANIFEST = CACHE_DIR / "_manifest.json"
BUILDER_VERSION = "d0"


# --------------------------------------------------------------------------- #
# Registry                                                                     #
# --------------------------------------------------------------------------- #
@dataclass
class Builder:
    name: str
    func: Callable[[], pd.DataFrame]
    heavy: bool = False
    sources: list[str] = field(default_factory=list)
    note: str = ""


_REGISTRY: dict[str, Builder] = {}

#: Source artifacts each cache file depends on — used for the manifest `sources`
#: block (mtime/size staleness, Section 0.8.1 #3) and shared by real + stub
#: builders so the two never drift.
_SOURCES: dict[str, list[str]] = {
    "universe_daily_coverage": ["data/universe/membership.parquet", "data/prices/ohlcv.parquet"],
    "universe_monthly": ["data/universe/universe_stats.parquet", "data/universe/membership.parquet"],
    "universe_intervals": ["data/universe/membership.parquet"],
    "universe_sector_comp": ["data/universe/membership.parquet", "data/panel/features.parquet"],
    "universe_overlap": ["data/universe/membership.parquet",
                         "nifty200_2015-01-01_to_2026-09-01.csv",
                         "data/raw/ind_nifty200list.csv"],
    "prices_coverage_yearly": ["data/prices/ohlcv.parquet", "data/universe/membership.parquet"],
    "prices_ca_counts": ["data/prices/corporate_actions.parquet"],
    "prices_extreme_returns": ["data/prices/ohlcv.parquet", "data/prices/corporate_actions.parquet"],
    "prices_source_eras": ["data/prices/ohlcv.parquet"],
    "prices_vwap_sanity": ["data/prices/ohlcv.parquet"],
    "prices_quality": ["data/prices/ohlcv.parquet"],
    "prices_yf_crosscheck": ["reports/p2_coverage_report.md"],
    "panel_feature_stats": ["data/panel/features.parquet"],
    "panel_feature_corr": ["data/panel/features.parquet"],
    "panel_feature_ic": ["data/panel/features.parquet", "data/panel/labels.parquet"],
    "panel_feature_ic_shift": ["data/panel/features.parquet", "data/panel/labels.parquet"],
    "panel_leaky_check": ["data/panel/labels.parquet"],
    "panel_xsec_size": ["data/panel/features.parquet"],
    "panel_nan_coverage": ["data/panel/features.parquet"],
    "panel_label_dist": ["data/panel/labels.parquet"],
    "zoo_leaderboard": ["data/panel/features.parquet", "data/panel/labels.parquet"],
    "ledger_summary": ["data/ledger.db"],
    "loop_generations": ["data/loop_checkpoint.db"],
    "loop_run_meta": ["data/loop_checkpoint.db"],
    "corpus_family_counts": ["data/corpus/anomalies.json"],
    "agents_token_budget": ["src/config.py"],
}
_HEAVY_NAMES = {"zoo_leaderboard", "prices_yf_crosscheck"}


def builder(name: str, *, heavy: bool | None = None, sources: list[str] | None = None,
            note: str = "") -> Callable:
    def deco(func: Callable[[], pd.DataFrame]) -> Callable:
        _REGISTRY[name] = Builder(
            name, func,
            heavy=(name in _HEAVY_NAMES) if heavy is None else heavy,
            sources=list(sources if sources is not None else _SOURCES.get(name, [])),
            note=note,
        )
        return func
    return deco


def _seed() -> None:
    np.random.seed(RANDOM_SEED)
    random.seed(RANDOM_SEED)


def _source_meta(rel_paths: list[str]) -> list[dict]:
    out = []
    for rp in rel_paths:
        p = PROJECT_ROOT / rp
        if p.exists():
            st_ = p.stat()
            out.append({"path": rp, "mtime": round(st_.st_mtime, 3), "size": st_.st_size})
        else:
            out.append({"path": rp, "mtime": 0.0, "size": 0})
    return out


def _assert_schema(name: str, df: pd.DataFrame) -> None:
    schema = fixtures.CACHE_SCHEMAS[name]
    missing = [c for c in schema if c not in df.columns]
    extra = [c for c in df.columns if c not in schema]
    if missing or extra:
        raise AssertionError(
            f"[{name}] column mismatch — missing={missing} extra={extra}"
        )
    # order columns to the schema
    df = df[list(schema)]
    for col, dt in schema.items():
        got = str(df[col].dtype)
        if dt == "datetime64[ns]":
            if not str(df[col].dtype).startswith("datetime64[ns"):
                raise AssertionError(f"[{name}] {col!r} must be datetime64[ns], got {got}")
        elif dt == "bool":
            if got != "bool":
                raise AssertionError(f"[{name}] {col!r} must be bool, got {got}")
        elif dt == "int64":
            if not got.startswith("int"):
                raise AssertionError(f"[{name}] {col!r} must be int64, got {got}")
        elif dt == "float64":
            if not got.startswith("float"):
                raise AssertionError(f"[{name}] {col!r} must be float64, got {got}")


# --------------------------------------------------------------------------- #
# Reference builders (D0) — cheap, no heavy source                             #
# --------------------------------------------------------------------------- #
@builder("corpus_family_counts", sources=["data/corpus/anomalies.json"],
         note="anomalies grouped by family; tradeable split")
def _corpus_family_counts() -> pd.DataFrame:
    schema = fixtures.CACHE_SCHEMAS["corpus_family_counts"]
    src = PROJECT_ROOT / "data" / "corpus" / "anomalies.json"
    if not src.exists():
        df = pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})
        df.attrs["status"] = "no_source"
        return df
    payload = json.loads(src.read_text(encoding="utf-8"))
    an = pd.DataFrame(payload.get("anomalies", []))
    if an.empty:
        df = pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})
        df.attrs["status"] = "no_source"
        return df
    an["tradeable_with_our_data"] = an["tradeable_with_our_data"].astype(bool)
    g = an.groupby("family")
    out = pd.DataFrame({
        "family": g.size().index,
        "n": g.size().to_numpy(),
        "n_tradeable": g["tradeable_with_our_data"].sum().to_numpy(),
        "n_not_tradeable": (~an["tradeable_with_our_data"]).groupby(an["family"]).sum().to_numpy(),
    })
    out = out.astype({"n": "int64", "n_tradeable": "int64", "n_not_tradeable": "int64"})
    return out.sort_values("family").reset_index(drop=True)


#: The measured per-role projection (PRE_BUILD_TASKS.md T3 / FINDING 2).
#: calls_per_thesis and tokens_per_call — the ~16.6 calls / ~26,500 tokens total.
_T3_PROJECTION: dict[str, tuple[float, int]] = {
    # role: (calls_per_thesis, tokens_per_call)
    "hypothesis": (1.0, 3300),
    "redteam": (0.4, 2400),
    "coder": (5.6, 1700),
    "judge": (5.6, 1400),
    "economics": (1.0, 1900),
    "planner": (1.0, 1000),
    "librarian": (1.0, 1000),
    "reflection": (1.0, 1000),
}


@builder("agents_token_budget", sources=["src/config.py"],
         note="per-role call/token projection (T3 FINDING 2) x live LLM_ROLE_TIER")
def _agents_token_budget() -> pd.DataFrame:
    from src.config import AGENT_ROLES, LLM_ROLE_TIER  # read live

    rows = []
    for role in AGENT_ROLES:
        calls, tok_per_call = _T3_PROJECTION.get(role, (1.0, 1000))
        rows.append({
            "role": role,
            "tier": LLM_ROLE_TIER.get(role, "small"),
            "calls_per_thesis": float(calls),
            "tokens_per_thesis": int(round(calls * tok_per_call)),
        })
    df = pd.DataFrame(rows)
    df = df.astype({"calls_per_thesis": "float64", "tokens_per_thesis": "int64"})
    return df.sort_values("role").reset_index(drop=True)


# =========================================================================== #
# D1 — the cheap builders                                                      #
# =========================================================================== #
import functools  # noqa: E402

from src.config import HOLDOUT_START  # noqa: E402  — read live, never retyped

_UNIVERSE_DIR = PROJECT_ROOT / "data" / "universe"
_PRICES_DIR = PROJECT_ROOT / "data" / "prices"
_PANEL_DIR = PROJECT_ROOT / "data" / "panel"

_FEATURE_COLS = (
    "mom_21", "mom_126", "rev_5", "vol_21", "beta_63", "amihud_21",
    "turnover_21", "dist_52wh", "max_ret_21", "delivery_pct", "size_proxy",
)
_HORIZONS = (1, 2, 3, 5, 10, 21)


def _empty(name: str, note: str = "source artifact missing") -> pd.DataFrame:
    schema = fixtures.CACHE_SCHEMAS[name]
    df = pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})
    df.attrs["status"] = "no_source"
    df.attrs["note"] = note
    return df


def _exists(*rel: str) -> bool:
    return all((PROJECT_ROOT / r).exists() for r in rel)


def _finish(name: str, df: pd.DataFrame, status: str = "ok",
            note: str | None = None) -> pd.DataFrame:
    """Coerce every column to its ``CACHE_SCHEMAS`` dtype, assert, tag status."""
    schema = fixtures.CACHE_SCHEMAS[name]
    df = df.reset_index(drop=True).copy()
    for col, dt in schema.items():
        if col not in df.columns:
            raise AssertionError(f"[{name}] builder produced no {col!r} column")
        if dt == "datetime64[ns]":
            s = pd.to_datetime(df[col])
            if getattr(s.dt, "tz", None) is not None:
                s = s.dt.tz_localize(None)
            df[col] = s.dt.normalize().astype("datetime64[ns]")
        elif dt == "int64":
            df[col] = df[col].astype("int64")
        elif dt == "float64":
            df[col] = df[col].astype("float64")
        elif dt == "bool":
            df[col] = df[col].astype("bool")
        else:
            df[col] = df[col].where(df[col].notna(), None).astype("object")
    df = df[list(schema)]
    _assert_schema(name, df)
    df.attrs["status"] = status
    if note is not None:
        df.attrs["note"] = note
    return df


# ---- shared source loaders (cached for the run) --------------------------
@functools.lru_cache(maxsize=1)
def _ohlcv() -> pd.DataFrame:
    """One columnar read of ``ohlcv.parquet`` (8 cols) reused by every price
    builder — the single most expensive read in the cheap pass."""
    import pyarrow.parquet as pq

    cols = ["date", "symbol", "close", "high", "low", "vwap", "volume", "source"]
    df = pq.read_table(_PRICES_DIR / "ohlcv.parquet", columns=cols).to_pandas()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["symbol"] = df["symbol"].astype(str)
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


@functools.lru_cache(maxsize=1)
def _membership() -> pd.DataFrame:
    df = pd.read_parquet(_UNIVERSE_DIR / "membership.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["symbol"] = df["symbol"].astype(str)
    return df


@functools.lru_cache(maxsize=1)
def _features() -> pd.DataFrame:
    df = pd.read_parquet(_PANEL_DIR / "features.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df


@functools.lru_cache(maxsize=1)
def _labels() -> pd.DataFrame:
    df = pd.read_parquet(_PANEL_DIR / "labels.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df


@functools.lru_cache(maxsize=1)
def _monthly_member_sets() -> tuple[tuple[pd.Timestamp, frozenset], ...]:
    """``((month_end, {symbols}), ...)`` — one entry per ``universe_stats`` month
    that has members, from the membership panel's last trading day of that month.
    Ordered by month_end."""
    us = pd.read_parquet(_UNIVERSE_DIR / "universe_stats.parquet")
    us = us[us["n_members"] > 0]
    mem = _membership()
    mem = mem[mem["in_universe"]].copy()
    mem["ym"] = mem["date"].dt.to_period("M")
    last = mem.groupby("ym")["date"].transform("max")
    snap = mem[mem["date"] == last]
    by_ym = {ym: frozenset(g["symbol"]) for ym, g in snap.groupby("ym")}
    out = []
    for d in pd.to_datetime(us["date"]).dt.normalize().sort_values():
        s = by_ym.get(d.to_period("M"))
        if s:
            out.append((d, s))
    return tuple(out)


@functools.lru_cache(maxsize=1)
def _daily_coverage_frame() -> pd.DataFrame:
    mem = _membership()
    mem_m = mem.loc[mem["in_universe"], ["date", "symbol"]]
    oh = _ohlcv()[["date", "symbol"]].drop_duplicates()

    n_members = mem_m.groupby("date").size()
    n_traded = oh.groupby("date")["symbol"].nunique()
    panel = mem_m.merge(oh, on=["date", "symbol"], how="inner")
    n_panel = panel.groupby("date").size()

    out = pd.DataFrame({"date": n_members.index})
    out["n_members"] = n_members.to_numpy()
    out["n_traded"] = n_traded.reindex(n_members.index).fillna(0).to_numpy()
    out["n_panel"] = n_panel.reindex(n_members.index).fillna(0).to_numpy()
    out["gap"] = out["n_members"] - out["n_panel"]
    return out.sort_values("date").reset_index(drop=True)


# ---- universe_* ---------------------------------------------------------
@builder("universe_daily_coverage",
         note="members(D) vs symbols-that-traded(D); n_panel = intersection")
def _universe_daily_coverage() -> pd.DataFrame:
    if not _exists("data/universe/membership.parquet", "data/prices/ohlcv.parquet"):
        return _empty("universe_daily_coverage")
    dc = _daily_coverage_frame()
    return _finish("universe_daily_coverage", dc)


@builder("universe_monthly",
         note="universe_stats + monthly membership churn (in/out/pct)")
def _universe_monthly() -> pd.DataFrame:
    if not _exists("data/universe/universe_stats.parquet", "data/universe/membership.parquet"):
        return _empty("universe_monthly")
    us = pd.read_parquet(_UNIVERSE_DIR / "universe_stats.parquet")
    us = us[us["n_members"] > 0].copy()
    us["date"] = pd.to_datetime(us["date"]).dt.normalize()
    sets = dict(_monthly_member_sets())
    rows = []
    prev: frozenset = frozenset()
    for _, r in us.sort_values("date").iterrows():
        cur = sets.get(r["date"], frozenset())
        n_sel = int(r["n_members"])
        # churn is only defined once we have a real previous month's snapshot
        # (the membership panel starts 2015-02, one month after universe_stats).
        c_in = len(cur - prev) if (prev and cur) else 0
        c_out = len(prev - cur) if (prev and cur) else 0
        rows.append({
            "month_end": r["date"], "n_selected": n_sel,
            "turnover_cutoff_200": r["turnover_cutoff_200"],
            "median_turnover": r["median_turnover"],
            "churn_in": c_in, "churn_out": c_out,
            "churn_pct": (100.0 * c_in / n_sel) if (n_sel and prev and cur) else 0.0,
        })
        if cur:
            prev = cur
    return _finish("universe_monthly", pd.DataFrame(rows))


@builder("universe_intervals",
         note="in-universe (start,end) runs for the canary + heavyweight names")
def _universe_intervals() -> pd.DataFrame:
    if not _exists("data/universe/membership.parquet"):
        return _empty("universe_intervals")
    from src.universe import CANARIES, HEAVYWEIGHTS

    mem = _membership()
    kinds = {s: "canary" for s in CANARIES}
    kinds.update({s: "heavyweight" for s in HEAVYWEIGHTS})
    rows = []
    for sym, kind in kinds.items():
        sub = mem[(mem["symbol"] == sym) & mem["in_universe"]].sort_values("date")
        if sub.empty:
            continue
        d = sub["date"].to_numpy()
        # split into runs where the gap between in-universe days exceeds 7 calendar days
        breaks = np.where(np.diff(d).astype("timedelta64[D]").astype(int) > 7)[0]
        starts = np.concatenate([[0], breaks + 1])
        ends = np.concatenate([breaks, [len(d) - 1]])
        for s, e in zip(starts, ends):
            rows.append({"symbol": sym, "kind": kind,
                         "start": pd.Timestamp(d[s]), "end": pd.Timestamp(d[e])})
    if not rows:
        return _empty("universe_intervals", "no canary/heavyweight rows in membership")
    df = pd.DataFrame(rows).sort_values(["kind", "symbol", "start"])
    return _finish("universe_intervals", df)


@builder("universe_sector_comp",
         note="monthly member counts by (current) sector label from features")
def _universe_sector_comp() -> pd.DataFrame:
    if not _exists("data/universe/membership.parquet", "data/panel/features.parquet"):
        return _empty("universe_sector_comp")
    sec = (_features()[["date", "symbol", "sector"]]
           .sort_values("date").groupby("symbol")["sector"].last())
    rows = []
    for month_end, members in _monthly_member_sets():
        s = pd.Series({m: sec.get(m, "Unknown") for m in members})
        counts = s.value_counts()
        total = int(counts.sum()) or 1
        for sector, n in counts.items():
            rows.append({"month_end": month_end, "sector": str(sector),
                         "n_members": int(n), "weight": n / total})
    if not rows:
        return _empty("universe_sector_comp")
    df = pd.DataFrame(rows).sort_values(["month_end", "sector"])
    return _finish("universe_sector_comp", df)


@builder("universe_overlap",
         note="monthly overlap of our members with the supplied CSV / NSE list")
def _universe_overlap() -> pd.DataFrame:
    if not _exists("data/universe/membership.parquet"):
        return _empty("universe_overlap")
    from src.universe import _nse_current_union, _supplied_csv_union

    csv_u = _supplied_csv_union()
    nse_u = _nse_current_union()
    if csv_u is None and nse_u is None:
        return _empty("universe_overlap", "neither the supplied CSV nor the NSE list is present")
    rows = []
    for month_end, members in _monthly_member_sets():
        n = len(members) or 1
        rows.append({
            "month_end": month_end,
            "overlap_nse_current_pct": (100.0 * len(members & nse_u) / n) if nse_u else np.nan,
            "overlap_supplied_csv_pct": (100.0 * len(members & csv_u) / n) if csv_u else np.nan,
        })
    df = pd.DataFrame(rows).sort_values("month_end")
    status = "ok" if (csv_u and nse_u) else "partial"
    note = None if status == "ok" else (
        "NSE 'current list' file absent (data/raw/ind_nifty200list.csv) — "
        "overlap_nse_current_pct is NaN; supplied-CSV column is populated"
    )
    return _finish("universe_overlap", df, status=status, note=note)


# ---- prices_* ---------------------------------------------------------
@builder("prices_coverage_yearly",
         note="per-year universe-day coverage and distinct member count")
def _prices_coverage_yearly() -> pd.DataFrame:
    if not _exists("data/prices/ohlcv.parquet", "data/universe/membership.parquet"):
        return _empty("prices_coverage_yearly")
    dc = _daily_coverage_frame().copy()
    dc["year"] = dc["date"].dt.year
    dc["ratio"] = dc["n_panel"] / dc["n_members"].replace(0, np.nan)
    mem = _membership()
    mem = mem[mem["in_universe"]].copy()
    mem["year"] = mem["date"].dt.year
    nsym = mem.groupby("year")["symbol"].nunique()
    rows = []
    for year, g in dc.groupby("year"):
        rows.append({
            "year": int(year),
            "universe_days": int(g["date"].nunique()),
            "covered_days": int((g["ratio"] >= 0.99).sum()),
            "covered_pct": float(100.0 * g["ratio"].mean()),
            "n_symbols": int(nsym.get(year, 0)),
        })
    return _finish("prices_coverage_yearly", pd.DataFrame(rows).sort_values("year"))


@builder("prices_ca_counts", note="corporate-action counts per year and type")
def _prices_ca_counts() -> pd.DataFrame:
    if not _exists("data/prices/corporate_actions.parquet"):
        return _empty("prices_ca_counts")
    ca = pd.read_parquet(_PRICES_DIR / "corporate_actions.parquet")
    ca["year"] = pd.to_datetime(ca["ex_date"]).dt.year
    g = ca.groupby(["year", "type"]).size().rename("n").reset_index()
    return _finish("prices_ca_counts", g.sort_values(["year", "type"]))


@builder("prices_extreme_returns",
         note="|adjusted daily return| > 0.5, tagged by a CA within +/-1 day")
def _prices_extreme_returns() -> pd.DataFrame:
    if not _exists("data/prices/ohlcv.parquet"):
        return _empty("prices_extreme_returns")
    oh = _ohlcv()[["date", "symbol", "close"]].copy()
    oh["ret"] = oh.groupby("symbol")["close"].pct_change()
    ext = oh[oh["ret"].abs() > 0.5].dropna(subset=["ret"]).copy()
    if ext.empty:
        return _finish("prices_extreme_returns",
                       pd.DataFrame(columns=list(fixtures.CACHE_SCHEMAS["prices_extreme_returns"])),
                       note="no |daily return| > 0.5 in the adjusted series")
    explained, note = [], []
    if _exists("data/prices/corporate_actions.parquet"):
        ca = pd.read_parquet(_PRICES_DIR / "corporate_actions.parquet")
        ca["ex_date"] = pd.to_datetime(ca["ex_date"]).dt.normalize()
        ca_by_sym: dict[str, pd.DataFrame] = {s: g for s, g in ca.groupby("symbol")}
        for _, r in ext.iterrows():
            g = ca_by_sym.get(r["symbol"])
            hit = ""
            if g is not None:
                near = g[(g["ex_date"] - r["date"]).abs() <= pd.Timedelta(days=1)]
                if not near.empty:
                    hit = str(near.iloc[0]["type"])
            explained.append(hit)
            note.append("" if hit else "unexplained — not winsorized")
    else:
        explained = [""] * len(ext)
        note = ["no corporate_actions.parquet"] * len(ext)
    ext["explained_by"] = explained
    ext["note"] = note
    df = ext[["date", "symbol", "ret", "explained_by", "note"]].sort_values(["date", "symbol"])
    return _finish("prices_extreme_returns", df)


@builder("prices_source_eras", note="date span + row count per bhavcopy source")
def _prices_source_eras() -> pd.DataFrame:
    if not _exists("data/prices/ohlcv.parquet"):
        return _empty("prices_source_eras")
    oh = _ohlcv()[["date", "source"]]
    g = oh.groupby("source")["date"].agg(["min", "max", "size"]).reset_index()
    g.columns = ["source", "start", "end", "n_rows"]
    return _finish("prices_source_eras", g.sort_values("start"))


@builder("prices_vwap_sanity", note="per-year fraction of rows with low <= vwap <= high")
def _prices_vwap_sanity() -> pd.DataFrame:
    if not _exists("data/prices/ohlcv.parquet"):
        return _empty("prices_vwap_sanity")
    oh = _ohlcv()[["date", "low", "high", "vwap"]].copy()
    oh["year"] = oh["date"].dt.year
    oh["ok"] = (oh["vwap"] >= oh["low"]) & (oh["vwap"] <= oh["high"])
    g = oh.groupby("year").agg(n_rows=("ok", "size"), n_in_range=("ok", "sum")).reset_index()
    g["pct_in_range"] = 100.0 * g["n_in_range"] / g["n_rows"]
    return _finish("prices_vwap_sanity", g.sort_values("year"))


@builder("prices_quality", note="close<=0 / high<low / negative volume / dup key")
def _prices_quality() -> pd.DataFrame:
    if not _exists("data/prices/ohlcv.parquet"):
        return _empty("prices_quality")
    oh = _ohlcv()
    checks = {
        "close<=0": int((oh["close"] <= 0).sum()),
        "high<low": int((oh["high"] < oh["low"]).sum()),
        "negative volume": int((oh["volume"] < 0).sum()),
        "vwap outside [low,high]": int(((oh["vwap"] < oh["low"]) | (oh["vwap"] > oh["high"])).sum()),
        "duplicate (date,symbol)": int(oh.duplicated(["date", "symbol"]).sum()),
    }
    rows = [{"check": k, "n_violations": v, "detail": "ok" if v == 0 else f"{v} row(s)"}
            for k, v in checks.items()]
    return _finish("prices_quality", pd.DataFrame(rows))


# ---- panel_* ---------------------------------------------------------
def _wide_ic(sig_wide: pd.DataFrame, y_wide: pd.DataFrame,
             spearman: bool, min_names: int = 20) -> pd.Series:
    """Vectorised per-day IC of two wide ``date x symbol`` frames — the same
    method as ``src.gates._wide_rank_ic``, generalised to Pearson too."""
    s, y = sig_wide.align(y_wide, join="inner")
    if s.shape[0] == 0 or s.shape[1] == 0:
        return pd.Series(dtype=float)
    mask = s.notna() & y.notna()
    n = mask.sum(axis=1)
    s = s.where(mask)
    y = y.where(mask)
    if spearman:
        s = s.rank(axis=1)
        y = y.rank(axis=1)
    s = s.sub(s.mean(axis=1), axis=0)
    y = y.sub(y.mean(axis=1), axis=0)
    cov = (s * y).sum(axis=1, min_count=1)
    denom = np.sqrt((s ** 2).sum(axis=1) * (y ** 2).sum(axis=1))
    ic = cov / denom.replace(0.0, np.nan)
    return ic[n >= min_names].dropna()


@functools.lru_cache(maxsize=1)
def _panel_wide() -> tuple[dict, dict]:
    """``({feature: wide}, {horizon: wide fwd_ret_h_demeaned})`` — pre-HOLDOUT."""
    f = _features()
    lab = _labels()
    f = f[f["date"] < HOLDOUT_START]
    lab = lab[lab["date"] < HOLDOUT_START]
    feats = {c: f.pivot_table(index="date", columns="symbol", values=c).sort_index()
             for c in _FEATURE_COLS}
    labs = {h: lab.pivot_table(index="date", columns="symbol",
                               values=f"fwd_ret_{h}_demeaned").sort_index()
            for h in _HORIZONS}
    return feats, labs


@builder("panel_feature_stats", note="per-feature per-year distribution summary")
def _panel_feature_stats() -> pd.DataFrame:
    if not _exists("data/panel/features.parquet"):
        return _empty("panel_feature_stats")
    f = _features()
    f = f.assign(year=f["date"].dt.year)
    rows = []
    for feat in _FEATURE_COLS:
        for year, g in f.groupby("year"):
            s = g[feat]
            v = s.dropna()
            q = v.quantile([0.01, 0.25, 0.5, 0.75, 0.99]) if len(v) else pd.Series(
                {0.01: np.nan, 0.25: np.nan, 0.5: np.nan, 0.75: np.nan, 0.99: np.nan})
            rows.append({
                "feature": feat, "year": int(year),
                "mean": float(v.mean()) if len(v) else np.nan,
                "std": float(v.std(ddof=1)) if len(v) > 1 else np.nan,
                "p01": float(q.loc[0.01]), "p25": float(q.loc[0.25]),
                "p50": float(q.loc[0.5]), "p75": float(q.loc[0.75]),
                "p99": float(q.loc[0.99]),
                "n": int(s.notna().sum()), "n_nan": int(s.isna().sum()),
            })
    df = pd.DataFrame(rows).sort_values(["feature", "year"])
    return _finish("panel_feature_stats", df)


@builder("panel_feature_corr", note="pairwise Pearson correlation of the 11 features")
def _panel_feature_corr() -> pd.DataFrame:
    if not _exists("data/panel/features.parquet"):
        return _empty("panel_feature_corr")
    corr = _features()[list(_FEATURE_COLS)].corr()
    rows = []
    for i, a in enumerate(_FEATURE_COLS):
        for b in _FEATURE_COLS[i:]:
            rows.append({"feature_a": a, "feature_b": b, "corr": float(corr.loc[a, b])})
    return _finish("panel_feature_corr", pd.DataFrame(rows))


@builder("panel_feature_ic",
         note="daily Spearman/Pearson IC of each feature vs fwd_ret_h_demeaned, "
              "mean + t-stat over days; vectorised (cf. src.gates._wide_rank_ic); "
              "pre-HOLDOUT only")
def _panel_feature_ic() -> pd.DataFrame:
    if not _exists("data/panel/features.parquet", "data/panel/labels.parquet"):
        return _empty("panel_feature_ic")
    feats, labs = _panel_wide()
    rows = []
    for feat in _FEATURE_COLS:
        fw = feats[feat]
        for h in _HORIZONS:
            ric = _wide_ic(fw, labs[h], spearman=True)
            pic = _wide_ic(fw, labs[h], spearman=False)
            n = int(len(ric))
            sd = float(ric.std(ddof=1)) if n > 1 else np.nan
            mean_ic = float(ric.mean()) if n else np.nan
            rows.append({
                "feature": feat, "horizon": h, "rank_ic": mean_ic,
                "ic": float(pic.mean()) if len(pic) else np.nan,
                "t_stat": (mean_ic / (sd / np.sqrt(n)))
                if sd and n and np.isfinite(sd) and sd > 0 else np.nan,
                "n_days": n,
            })
    return _finish("panel_feature_ic", pd.DataFrame(rows).sort_values(["feature", "horizon"]))


@builder("panel_feature_ic_shift",
         note="h=1 RankIC, base vs the feature panel shifted +1 trading day "
              "(P3's look-ahead self-test surfaced here — the two MUST differ)")
def _panel_feature_ic_shift() -> pd.DataFrame:
    if not _exists("data/panel/features.parquet", "data/panel/labels.parquet"):
        return _empty("panel_feature_ic_shift")
    feats, labs = _panel_wide()
    y1 = labs[1]
    rows = []
    for feat in _FEATURE_COLS:
        fw = feats[feat]
        base = _wide_ic(fw, y1, spearman=True).mean()
        s1 = _wide_ic(fw.shift(1), y1, spearman=True).mean()
        rows.append({"feature": feat, "variant": "base", "rank_ic": float(base)})
        rows.append({"feature": feat, "variant": "shift1", "rank_ic": float(s1)})
    return _finish("panel_feature_ic_shift", pd.DataFrame(rows).sort_values(["feature", "variant"]))


@builder("panel_leaky_check",
         note="RankIC of fwd_ret_h used as its own predictor (expect ~1.0)")
def _panel_leaky_check() -> pd.DataFrame:
    if not _exists("data/panel/labels.parquet"):
        return _empty("panel_leaky_check")
    from src import backtester as _bt

    lab = _labels()
    lab = lab[lab["date"] < HOLDOUT_START]
    rows = []
    for h in _HORIZONS:
        ic = _bt._daily_ic(lab, f"fwd_ret_{h}", f"fwd_ret_{h}_demeaned", spearman=True)
        rows.append({"predictor": f"fwd_ret_{h}", "rank_ic": float(ic.mean())})
    return _finish("panel_leaky_check", pd.DataFrame(rows))


@builder("panel_xsec_size", note="distinct symbols in the feature panel per day")
def _panel_xsec_size() -> pd.DataFrame:
    if not _exists("data/panel/features.parquet"):
        return _empty("panel_xsec_size")
    g = _features().groupby("date")["symbol"].nunique().rename("n_symbols").reset_index()
    return _finish("panel_xsec_size", g.sort_values("date"))


@builder("panel_nan_coverage", note="per-(day,feature) NaN fraction across symbols")
def _panel_nan_coverage() -> pd.DataFrame:
    if not _exists("data/panel/features.parquet"):
        return _empty("panel_nan_coverage")
    f = _features()
    long = f.melt(id_vars=["date"], value_vars=list(_FEATURE_COLS),
                  var_name="feature", value_name="v")
    long["isna"] = long["v"].isna()
    g = long.groupby(["date", "feature"])["isna"].mean().rename("nan_pct").reset_index()
    return _finish("panel_nan_coverage", g.sort_values(["date", "feature"]))


_LABEL_BINS = np.round(np.linspace(-0.30, 0.30, 61), 4)


@builder("panel_label_dist", note="fixed-bin histogram of fwd_ret_h (raw vs demeaned)")
def _panel_label_dist() -> pd.DataFrame:
    if not _exists("data/panel/labels.parquet"):
        return _empty("panel_label_dist")
    lab = _labels()
    lab = lab[lab["date"] < HOLDOUT_START]
    rows = []
    for h in _HORIZONS:
        for kind, col in (("raw", f"fwd_ret_{h}"), ("demeaned", f"fwd_ret_{h}_demeaned")):
            counts, _ = np.histogram(lab[col].dropna().to_numpy(), bins=_LABEL_BINS)
            for left, c in zip(_LABEL_BINS[:-1], counts):
                rows.append({"horizon": h, "kind": kind,
                             "bin_left": float(left), "count": int(c)})
    return _finish("panel_label_dist", pd.DataFrame(rows))


# ---- ledger / loop --------------------------------------------------
@builder("ledger_summary", note="cumulative selection-trial count over time")
def _ledger_summary() -> pd.DataFrame:
    from dashboard.lib import data as _data

    p = _data.DATA_DIR / "ledger.db"
    if not p.exists():
        return _empty("ledger_summary")
    conn = _data._readonly_sqlite(p)
    try:
        tr = pd.read_sql_query(
            "SELECT timestamp, counts_as_trial, t_stat, n_days FROM trials ORDER BY trial_id",
            conn)
    except Exception:
        return _empty("ledger_summary", "trials table unreadable")
    finally:
        conn.close()
    tr = tr[tr["counts_as_trial"] == 1]
    if tr.empty:
        return _empty("ledger_summary", "ledger has no counts_as_trial=1 rows yet")
    _ts = pd.to_datetime(tr["timestamp"], utc=True)
    tr["t"] = _ts.dt.tz_localize(None)
    tr = tr.sort_values("t").reset_index(drop=True)
    tr["cumulative_trials"] = np.arange(1, len(tr) + 1)
    # cheaper proxy for the running effective count: sqrt-participation of the
    # trial IR series (documented in the handoff) — effective_trial_count needs
    # canonical ASTs which the summary does not carry.
    ir = (tr["t_stat"] / np.sqrt(tr["n_days"].clip(lower=1))).fillna(0.0)
    eff = []
    for i in range(len(tr)):
        window = ir.iloc[: i + 1].to_numpy()
        s = np.abs(window).sum()
        eff.append((s ** 2 / np.square(window).sum()) if np.square(window).sum() else float(i + 1))
    tr["cumulative_effective"] = eff
    return _finish("ledger_summary", tr[["t", "cumulative_trials", "cumulative_effective"]])


@builder("loop_generations", note="per-generation outcomes from loop_checkpoint.db")
def _loop_generations() -> pd.DataFrame:
    from dashboard.lib import data as _data

    df = _data.load_loop_generations()
    if df.empty:
        return _empty("loop_generations", "the loop (P10/P11) has not run yet")
    return _finish("loop_generations", df)


@builder("loop_run_meta", note="run-scalar key/value rows from loop_checkpoint.db")
def _loop_run_meta() -> pd.DataFrame:
    from dashboard.lib import data as _data

    state = _data.load_loop_run_state()
    if not state:
        return _empty("loop_run_meta", "the loop (P10/P11) has not run yet")
    keys = ["run_id", "next_gen", "incomplete_gen", "t_stat_bar", "min_marginal_ic",
            "large_used", "small_used", "budget_day"]
    rows = [{"key": k, "value": str(state.get(k))} for k in keys]
    rows.append({"key": "n_accepted", "value": str(len(state.get("accepted_card_ids", [])))})
    return _finish("loop_run_meta", pd.DataFrame(rows))


# --------------------------------------------------------------------------- #
# Stubs for the builders D1 does NOT own (heavy / opt-in).  Registered last so  #
# a real @builder above always wins.                                           #
# --------------------------------------------------------------------------- #
def _make_stub(name: str) -> Callable[[], pd.DataFrame]:
    def _stub() -> pd.DataFrame:
        return _empty(name, "heavy / opt-in — build with --heavy (D3/D4 own the fallbacks)")
    _stub.__name__ = f"_stub_{name}"
    return _stub


for _name in fixtures.CACHE_SCHEMAS:
    if _name in _REGISTRY:
        continue
    _REGISTRY[_name] = Builder(
        _name, _make_stub(_name), heavy=_name in _HEAVY_NAMES,
        sources=list(_SOURCES.get(_name, [])),
        note="heavy / opt-in (D0 stub)" if _name in _HEAVY_NAMES else "stub",
    )


# --------------------------------------------------------------------------- #
# Runner                                                                       #
# --------------------------------------------------------------------------- #
def _write(name: str, df: pd.DataFrame) -> dict:
    schema = fixtures.CACHE_SCHEMAS[name]
    df = df.reset_index(drop=True)[list(schema)]
    _assert_schema(name, df)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE_DIR / f"{name}.parquet", index=False)
    return {
        "rows": int(len(df)),
        "cols": list(df.columns),
        "built_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "builder_version": BUILDER_VERSION,
        "status": df.attrs.get("status", "ok"),
        "note": df.attrs.get("note") or _REGISTRY[name].note,
        "sources": _source_meta(_REGISTRY[name].sources),
    }


def run_builders(names: list[str], *, heavy: bool) -> dict:
    _seed()
    manifest = _load_manifest()
    for name in names:
        b = _REGISTRY[name]
        if b.heavy and not heavy:
            manifest[name] = {
                "rows": 0, "cols": list(fixtures.CACHE_SCHEMAS[name]),
                "built_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "builder_version": BUILDER_VERSION, "status": "no_source",
                "note": f"{b.note} (heavy — run with --heavy)".strip(),
                "sources": _source_meta(b.sources),
            }
            # still emit an empty schema-correct parquet so pages don't crash
            schema = fixtures.CACHE_SCHEMAS[name]
            empty = pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            empty.to_parquet(CACHE_DIR / f"{name}.parquet", index=False)
            print(f"  {name:32s} SKIP (heavy)")
            continue
        try:
            df = b.func()
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:32s} ERROR {exc!r}")
            raise
        row = _write(name, df)
        print(f"  {name:32s} {row['status']:10s} rows={row['rows']}")
        manifest[name] = row
    _save_manifest(manifest)
    return manifest


def _load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_manifest(manifest: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------------------- #
# --check                                                                      #
# --------------------------------------------------------------------------- #
def check() -> int:
    """Verify every MANIFEST row against disk + ``CACHE_SCHEMAS`` and report
    staleness.  A builder that has no manifest row is simply "not built" — not a
    failure (build it with ``--only`` or a full pass)."""
    manifest = _load_manifest()
    problems: list[str] = []
    stale: list[str] = []

    if not manifest:
        print("--check: no _manifest.json — run `python dashboard/build_cache.py`")
        return 2

    for name, row in manifest.items():
        if name not in fixtures.CACHE_SCHEMAS:
            problems.append(f"{name}: not a known cache file")
            continue
        p = CACHE_DIR / f"{name}.parquet"
        if not p.exists():
            problems.append(f"{name}: manifest row but parquet missing")
            continue
        df = pd.read_parquet(p)
        schema = fixtures.CACHE_SCHEMAS[name]
        if list(df.columns) != list(schema):
            problems.append(f"{name}: cols {list(df.columns)} != schema {list(schema)}")
        else:
            try:
                _assert_schema(name, df)
            except AssertionError as exc:
                problems.append(str(exc))
        if row.get("cols") != list(schema):
            problems.append(f"{name}: manifest cols drift")
        # staleness — meaningless for a deliberately empty `no_source` cache
        if row.get("status") == "no_source":
            continue
        for src in row.get("sources", []):
            sp = PROJECT_ROOT / src["path"]
            if not sp.exists():
                continue
            st_ = sp.stat()
            if (round(st_.st_mtime, 3) > round(float(src.get("mtime", 0)), 3)
                    or st_.st_size != int(src.get("size", st_.st_size))):
                stale.append(name)
                break

    for row in problems:
        print(f"FAIL  {row}")
    for name in sorted(set(stale)):
        print(f"STALE {name}: a source is newer than the cache — rebuild")

    if problems:
        print(f"\n--check: {len(problems)} problem(s)")
        return 2
    if stale:
        print(f"\n--check: {len(set(stale))} stale builder(s) (expected while P11/P12 run)")
        return 1
    print("--check: OK")
    return 0


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="comma-separated builder names")
    ap.add_argument("--heavy", action="store_true", help="also run opt-in heavy builders")
    ap.add_argument("--check", action="store_true", help="verify manifest vs disk/schema")
    ap.add_argument("--list", action="store_true", help="print the builder registry")
    args = ap.parse_args(argv)

    if args.list:
        print(f"{len(_REGISTRY)} builders:")
        for name, b in sorted(_REGISTRY.items()):
            tag = "HEAVY" if b.heavy else "cheap"
            print(f"  {name:32s} [{tag}] {b.note}")
        return 0

    if args.check:
        return check()

    if args.only:
        names = [n.strip() for n in args.only.split(",") if n.strip()]
        unknown = [n for n in names if n not in _REGISTRY]
        if unknown:
            ap.error(f"unknown builder(s): {unknown}")
    else:
        names = [n for n, b in _REGISTRY.items() if not b.heavy or args.heavy]

    t0 = _dt.datetime.now()
    print(f"building {len(names)} cache file(s) into {CACHE_DIR} ...")
    run_builders(names, heavy=args.heavy)
    dt = (_dt.datetime.now() - t0).total_seconds()
    print(f"done in {dt:.1f}s  ->  {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
