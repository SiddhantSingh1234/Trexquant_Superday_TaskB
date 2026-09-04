"""Schema-correct fake data for every dashboard cache file (Section 0.6).

Fully implemented in D0.  Page phases build and test against these before D1's
`build_cache.py` has run.

Import rule: this is one of the two `lib` modules allowed to import `src` — and
only `src.contracts` (pure schema generators, no project data).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.contracts import make_fake_card, validate_card

# --------------------------------------------------------------------------- #
# CACHE_SCHEMAS — name -> {column: pandas-dtype-string}                         #
# Covers EVERY file in DASHBOARD_PLAN.md Section 0.6.                           #
# --------------------------------------------------------------------------- #
_F = "float64"
_I = "int64"
_S = "object"
_D = "datetime64[ns]"
_B = "bool"

CACHE_SCHEMAS: dict[str, dict[str, str]] = {
    # ---- universe ----------------------------------------------------------
    "universe_daily_coverage": {
        "date": _D, "n_members": _I, "n_traded": _I, "n_panel": _I, "gap": _I,
    },
    "universe_monthly": {
        "month_end": _D, "n_selected": _I, "turnover_cutoff_200": _F,
        "median_turnover": _F, "churn_in": _I, "churn_out": _I, "churn_pct": _F,
    },
    "universe_intervals": {
        "symbol": _S, "kind": _S, "start": _D, "end": _D,
    },
    "universe_sector_comp": {
        "month_end": _D, "sector": _S, "n_members": _I, "weight": _F,
    },
    "universe_overlap": {
        "month_end": _D, "overlap_nse_current_pct": _F,
        "overlap_supplied_csv_pct": _F,
    },
    # ---- prices -----------------------------------------------------------
    "prices_coverage_yearly": {
        "year": _I, "universe_days": _I, "covered_days": _I,
        "covered_pct": _F, "n_symbols": _I,
    },
    "prices_ca_counts": {"year": _I, "type": _S, "n": _I},
    "prices_extreme_returns": {
        "date": _D, "symbol": _S, "ret": _F, "explained_by": _S, "note": _S,
    },
    "prices_source_eras": {"source": _S, "start": _D, "end": _D, "n_rows": _I},
    "prices_vwap_sanity": {
        "year": _I, "n_rows": _I, "n_in_range": _I, "pct_in_range": _F,
    },
    "prices_quality": {"check": _S, "n_violations": _I, "detail": _S},
    "prices_yf_crosscheck": {"symbol": _S, "corr": _F, "n_days": _I},
    # ---- panel ----------------------------------------------------------
    "panel_feature_stats": {
        "feature": _S, "year": _I, "mean": _F, "std": _F, "p01": _F, "p25": _F,
        "p50": _F, "p75": _F, "p99": _F, "n": _I, "n_nan": _I,
    },
    "panel_feature_corr": {"feature_a": _S, "feature_b": _S, "corr": _F},
    "panel_feature_ic": {
        "feature": _S, "horizon": _I, "rank_ic": _F, "ic": _F,
        "t_stat": _F, "n_days": _I,
    },
    "panel_feature_ic_shift": {"feature": _S, "variant": _S, "rank_ic": _F},
    "panel_leaky_check": {"predictor": _S, "rank_ic": _F},
    "panel_xsec_size": {"date": _D, "n_symbols": _I},
    "panel_nan_coverage": {"date": _D, "feature": _S, "nan_pct": _F},
    "panel_label_dist": {
        "horizon": _I, "kind": _S, "bin_left": _F, "count": _I,
    },
    # ---- zoo / ledger / loop --------------------------------------------
    "zoo_leaderboard": {
        "name": _S, "source": _S, "formula": _S, "nodes": _I, "depth": _I,
        "free_params": _I, "rank_ic": _F, "icir": _F, "t_stat": _F,
        "sharpe": _F, "split": _S,
    },
    "ledger_summary": {
        "t": _D, "cumulative_trials": _I, "cumulative_effective": _F,
    },
    "loop_generations": {
        "generation": _I, "family": _S, "thesis_id": _S, "verdict": _S,
        "reject_reason": _S, "variant_count": _I, "forced_promote": _B,
        "marginal_ic": _F, "novelty_adjusted_marginal_ic": _F,
        "tier1_rank_ic": _F, "fresh_fold_rank_ic": _F, "redteam_verdict": _S,
        "holdout_rank_ic": _F, "holdout_failed": _B, "mandatory_regimes": _S,
    },
    "loop_run_meta": {"key": _S, "value": _S},
    # ---- corpus / agents ----------------------------------------------
    "corpus_family_counts": {
        "family": _S, "n": _I, "n_tradeable": _I, "n_not_tradeable": _I,
    },
    "agents_token_budget": {
        "role": _S, "tier": _S, "calls_per_thesis": _F, "tokens_per_thesis": _I,
    },
}

#: Builders left as `status:"no_source"` in the cheap pass (Section 0.6 / 0.7).
HEAVY_ONLY: frozenset[str] = frozenset({"zoo_leaderboard", "prices_yf_crosscheck"})

_SECTORS = (
    "Financial Services", "Information Technology", "Oil Gas & Consumable Fuels",
    "Fast Moving Consumer Goods", "Automobile and Auto Components", "Healthcare",
    "Metals & Mining", "Power", "Construction", "Capital Goods",
)
_FEATURES = (
    "mom_21", "mom_126", "rev_5", "vol_21", "beta_63", "amihud_21",
    "turnover_21", "dist_52wh", "max_ret_21", "delivery_pct", "size_proxy",
)
_HORIZONS = (1, 2, 3, 5, 10, 21)
_FAMILIES = ("momentum", "reversal", "liquidity", "microstructure", "quality_proxy")


def _dates(rows: int, rng: np.random.Generator) -> pd.Series:
    span = pd.bdate_range("2015-01-02", "2025-12-31")
    idx = np.sort(rng.choice(len(span), size=min(rows, len(span)), replace=False))
    out = span[idx]
    if len(out) < rows:  # pad by repeating the tail
        out = out.append(pd.DatetimeIndex([span[-1]] * (rows - len(out))))
    return pd.Series(out[:rows]).astype("datetime64[ns]")


def _coerce(df: pd.DataFrame, schema: dict[str, str]) -> pd.DataFrame:
    df = df[list(schema)].copy()
    for col, dt in schema.items():
        if dt == "datetime64[ns]":
            df[col] = pd.to_datetime(df[col]).dt.normalize().astype("datetime64[ns]")
        else:
            df[col] = df[col].astype(dt)
    return df.reset_index(drop=True)


def fake_cache(name: str, rows: int = 200, seed: int = 42) -> pd.DataFrame:
    """A schema-correct random frame for any Section 0.6 cache file."""
    if name not in CACHE_SCHEMAS:
        raise KeyError(f"unknown cache file {name!r}")
    schema = CACHE_SCHEMAS[name]
    rng = np.random.default_rng(seed + hash(name) % 9973)
    n = rows

    if name == "universe_daily_coverage":
        d = _dates(n, rng)
        members = rng.integers(195, 206, n)
        traded = members + rng.integers(-3, 4, n)
        panel = np.minimum(members, traded) - rng.integers(0, 3, n)
        raw = pd.DataFrame({
            "date": d, "n_members": members, "n_traded": traded,
            "n_panel": panel, "gap": members - panel,
        })
    elif name == "universe_monthly":
        me = pd.Series(pd.bdate_range("2015-01-31", periods=n, freq="BME")).astype("datetime64[ns]")
        raw = pd.DataFrame({
            "month_end": me, "n_selected": rng.integers(198, 203, n),
            "turnover_cutoff_200": rng.uniform(2e7, 8e7, n),
            "median_turnover": rng.uniform(1e8, 5e8, n),
            "churn_in": rng.integers(2, 10, n), "churn_out": rng.integers(2, 10, n),
            "churn_pct": rng.uniform(1.5, 5.0, n),
        })
    elif name == "universe_intervals":
        syms = [f"SYM{i:03d}" for i in range(n)]
        kinds = rng.choice(["canary", "heavyweight", "other"], n)
        starts = _dates(n, rng)
        raw = pd.DataFrame({
            "symbol": syms, "kind": kinds, "start": starts,
            "end": starts + pd.to_timedelta(rng.integers(100, 2000, n), unit="D"),
        })
    elif name == "universe_sector_comp":
        me = pd.Series(pd.bdate_range("2015-01-31", periods=max(1, n // 10), freq="BME"))
        recs = []
        for m in me:
            for s in _SECTORS:
                recs.append((m, s, int(rng.integers(5, 40)), float(rng.uniform(0.02, 0.25))))
        raw = pd.DataFrame(recs, columns=["month_end", "sector", "n_members", "weight"])
    elif name == "universe_overlap":
        me = pd.Series(pd.bdate_range("2015-01-31", periods=n, freq="BME")).astype("datetime64[ns]")
        raw = pd.DataFrame({
            "month_end": me,
            "overlap_nse_current_pct": rng.uniform(70, 95, n),
            "overlap_supplied_csv_pct": rng.uniform(60, 90, n),
        })
    elif name == "prices_coverage_yearly":
        yrs = np.arange(2015, 2015 + n) if n < 12 else np.arange(2014, 2026)
        k = len(yrs)
        ud = rng.integers(240, 252, k)
        cov = ud - rng.integers(0, 5, k)
        raw = pd.DataFrame({
            "year": yrs, "universe_days": ud, "covered_days": cov,
            "covered_pct": 100 * cov / ud, "n_symbols": rng.integers(300, 360, k),
        })
    elif name == "prices_ca_counts":
        recs = []
        for y in range(2014, 2026):
            for t in ("split", "bonus", "dividend"):
                recs.append((y, t, int(rng.integers(0, 60))))
        raw = pd.DataFrame(recs, columns=["year", "type", "n"])
    elif name == "prices_extreme_returns":
        d = _dates(n, rng)
        raw = pd.DataFrame({
            "date": d, "symbol": [f"SYM{i%80:03d}" for i in range(n)],
            "ret": rng.uniform(0.5, 3.0, n) * rng.choice([-1, 1], n),
            "explained_by": rng.choice(["", "split", "bonus"], n),
            "note": rng.choice(["", "unwinsorized mid-cap move"], n),
        })
    elif name == "prices_source_eras":
        raw = pd.DataFrame({
            "source": ["bhavcopy_legacy", "sec_bhavdata_full"],
            "start": pd.to_datetime(["2014-01-01", "2019-09-28"]),
            "end": pd.to_datetime(["2019-09-27", "2025-12-31"]),
            "n_rows": [1_800_000, 3_100_000],
        })
    elif name == "prices_vwap_sanity":
        yrs = np.arange(2014, 2026)
        k = len(yrs)
        nr = rng.integers(300_000, 450_000, k)
        inr = nr - rng.integers(0, 200, k)
        raw = pd.DataFrame({
            "year": yrs, "n_rows": nr, "n_in_range": inr,
            "pct_in_range": 100 * inr / nr,
        })
    elif name == "prices_quality":
        raw = pd.DataFrame({
            "check": ["close<=0", "high<low", "negative volume", "duplicate (date,symbol)"],
            "n_violations": [0, 0, 0, 0],
            "detail": ["ok", "ok", "ok", "ok"],
        })
    elif name == "prices_yf_crosscheck":
        raw = pd.DataFrame({
            "symbol": [f"SYM{i:03d}" for i in range(n)],
            "corr": rng.uniform(0.97, 0.999, n),
            "n_days": rng.integers(1500, 2600, n),
        })
    elif name == "panel_feature_stats":
        recs = []
        for f in _FEATURES:
            for y in range(2015, 2026):
                mu = float(rng.normal(0, 1))
                recs.append((f, y, mu, abs(rng.normal(1, 0.3)), mu - 2.3, mu - 0.7,
                             mu, mu + 0.7, mu + 2.3, int(rng.integers(4e4, 5e4)),
                             int(rng.integers(0, 3000))))
        raw = pd.DataFrame(recs, columns=list(CACHE_SCHEMAS[name]))
    elif name == "panel_feature_corr":
        recs = []
        for i, a in enumerate(_FEATURES):
            for b in _FEATURES[i:]:
                c = 1.0 if a == b else float(rng.uniform(-0.5, 0.5))
                recs.append((a, b, c))
        raw = pd.DataFrame(recs, columns=["feature_a", "feature_b", "corr"])
    elif name == "panel_feature_ic":
        recs = []
        for f in _FEATURES:
            for h in _HORIZONS:
                ic = float(rng.normal(0, 0.01))
                recs.append((f, h, ic, ic * 0.9, ic / 0.004, int(rng.integers(800, 2400))))
        raw = pd.DataFrame(recs, columns=list(CACHE_SCHEMAS[name]))
    elif name == "panel_feature_ic_shift":
        recs = []
        for f in _FEATURES:
            base = float(rng.normal(0, 0.02))
            recs.append((f, "base", base))
            recs.append((f, "shift1", base * rng.uniform(0.1, 0.6)))
        raw = pd.DataFrame(recs, columns=["feature", "variant", "rank_ic"])
    elif name == "panel_leaky_check":
        raw = pd.DataFrame({
            "predictor": ["fwd_ret_1", "mom_21", "random_noise"],
            "rank_ic": [0.999, 0.03, 0.001],
        })
    elif name == "panel_xsec_size":
        d = _dates(n, rng)
        raw = pd.DataFrame({"date": d, "n_symbols": rng.integers(150, 205, n)})
    elif name == "panel_nan_coverage":
        d = _dates(max(1, n // len(_FEATURES)), rng)
        recs = [(dd, f, float(rng.uniform(0, 0.4))) for dd in d for f in _FEATURES]
        raw = pd.DataFrame(recs, columns=["date", "feature", "nan_pct"])
    elif name == "panel_label_dist":
        recs = []
        for h in _HORIZONS:
            for kind in ("raw", "demeaned"):
                for b in np.linspace(-0.2, 0.2, 40):
                    recs.append((h, kind, float(b), int(rng.integers(0, 5000))))
        raw = pd.DataFrame(recs, columns=list(CACHE_SCHEMAS[name]))
    elif name == "zoo_leaderboard":
        recs = []
        for i in range(min(n, 35)):
            recs.append((f"alpha_{i:03d}", "Kakushadze 2016", "rank(close)",
                         int(rng.integers(3, 20)), int(rng.integers(2, 8)),
                         int(rng.integers(0, 4)), float(rng.normal(0, 0.02)),
                         float(rng.normal(0, 0.3)), float(rng.normal(0, 2)),
                         float(rng.normal(0, 1)), "val_a"))
        raw = pd.DataFrame(recs, columns=list(CACHE_SCHEMAS[name]))
    elif name == "ledger_summary":
        t = _dates(n, rng).sort_values().reset_index(drop=True)
        ct = np.arange(1, n + 1)
        raw = pd.DataFrame({
            "t": t, "cumulative_trials": ct,
            "cumulative_effective": np.sqrt(ct) * 1.5,
        })
    elif name == "loop_generations":
        return fake_loop_generations(n=min(n, 12), seed=seed)
    elif name == "loop_run_meta":
        raw = pd.DataFrame({
            "key": ["run_id", "next_gen", "incomplete_gen", "t_stat_bar",
                    "min_marginal_ic", "large_used", "small_used", "budget_day",
                    "n_accepted"],
            "value": ["run_demo", "6", "None", "3.0", "0.01", "12500", "88000",
                      "2026-09-04", "1"],
        })
    elif name == "corpus_family_counts":
        recs = [(f, int(rng.integers(3, 12)), int(rng.integers(2, 9)),
                 int(rng.integers(0, 4))) for f in _FAMILIES]
        raw = pd.DataFrame(recs, columns=list(CACHE_SCHEMAS[name]))
    elif name == "agents_token_budget":
        roles = ("planner", "librarian", "hypothesis", "economics", "coder",
                 "judge", "redteam", "reflection")
        recs = [(r, "large" if r in ("hypothesis", "redteam") else "small",
                 float(rng.uniform(0.4, 6)), int(rng.integers(900, 10000)))
                for r in roles]
        raw = pd.DataFrame(recs, columns=list(CACHE_SCHEMAS[name]))
    else:  # pragma: no cover - schema-generic fallback
        raw = pd.DataFrame({
            c: (_dates(n, rng) if dt == _D else
                np.zeros(n) if dt == _F else
                np.zeros(n, dtype=int) if dt == _I else
                np.zeros(n, dtype=bool) if dt == _B else
                [""] * n)
            for c, dt in schema.items()
        })

    return _coerce(raw, schema)


def fake_loop_generations(n: int = 6, seed: int = 42) -> pd.DataFrame:
    """A plausible ``loop_generations`` frame for previewing 10_The_Loop.py."""
    rng = np.random.default_rng(seed + 555)
    recs = []
    for g in range(n):
        accept = (g == n - 1)
        vc = 20 if g % 3 == 0 else int(rng.integers(4, 18))
        mic = float(rng.uniform(0.012, 0.03)) if accept else float(rng.uniform(-0.01, 0.011))
        recs.append({
            "generation": g,
            "family": _FAMILIES[g % len(_FAMILIES)],
            "thesis_id": f"thesis_{g:02d}",
            "verdict": "accept" if accept else "reject",
            "reject_reason": None if accept else rng.choice(
                ["novelty: clone", "statistics: t<3", "redteam: killed", "gate_a: implausible"]),
            "variant_count": vc,
            "forced_promote": bool(vc >= 20),
            "marginal_ic": mic,
            "novelty_adjusted_marginal_ic": mic if accept else 0.0,
            "tier1_rank_ic": float(rng.uniform(0.01, 0.05)),
            "fresh_fold_rank_ic": float(rng.uniform(-0.01, 0.04)),
            "redteam_verdict": "survives" if accept else rng.choice(["killed", "n/a"]),
            "holdout_rank_ic": float(rng.uniform(0.005, 0.03)) if accept else np.nan,
            "holdout_failed": False,
            "mandatory_regimes": '["bull", "bear"]',
        })
    return _coerce(pd.DataFrame(recs), CACHE_SCHEMAS["loop_generations"])


def fake_cards(n: int = 3, seed: int = 42) -> list[dict]:
    """`n` schema-valid Alpha Cards (cycles verdict accept/reject/revise)."""
    verdicts = ("accept", "reject", "revise")
    out = []
    for i in range(max(1, n)):
        card = make_fake_card(seed=seed + i, verdict=verdicts[i % 3])
        if i > 0:
            card["lineage"] = {"parent_card_id": out[i - 1]["card_id"],
                               "edit_motif": "widen_window"}
        validate_card(card)
        out.append(card)
    return out


def install_fake_cache(names: list[str] | None = None, force: bool = False) -> None:
    """Write ``fake_cache(...)`` frames into ``data/dashboard/`` for a demo.

    Prints a loud warning; refuses if a real manifest is present unless
    ``force=True``.
    """
    from . import data as _data

    manifest = _data.CACHE_DIR / "_manifest.json"
    if manifest.exists() and not force:
        real = _data.cache_manifest()
        if any(v.get("builder_version", "").strip() not in ("", "fixture")
               for v in real.values()):
            raise RuntimeError(
                "a real _manifest.json is present — pass force=True to overwrite "
                "with fixtures"
            )
    _data.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    names = list(names or CACHE_SCHEMAS)
    print("=" * 60)
    print("WARNING: writing FIXTURE data into data/dashboard/ — NOT real output.")
    print("=" * 60)
    import datetime as _dt
    import json as _json

    man: dict[str, dict] = {}
    for nm in names:
        df = fake_cache(nm)
        df.to_parquet(_data.CACHE_DIR / f"{nm}.parquet", index=False)
        man[nm] = {
            "rows": len(df), "cols": list(df.columns),
            "built_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "builder_version": "fixture", "status": "ok",
            "note": "FIXTURE DATA", "sources": [],
        }
    manifest.write_text(_json.dumps(man, indent=2), encoding="utf-8")
    print(f"wrote {len(names)} fixture parquet(s) + _manifest.json")
