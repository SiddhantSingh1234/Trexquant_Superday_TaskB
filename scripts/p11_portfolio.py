"""Phase 11 — deliverable (5): the off-loop portfolio post-process.

Reproducible from a seed and a single command:
    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/p11_portfolio.py

Tries the REAL accepted book first (`Memory().book.get_book_wide()`, via
`src.loop.portfolio_combine` — the exact function Phase 10 built). If fewer
than 2 real cards were accepted (this run: 0 or 1 — the loop is designed to
reject almost everything), it says so plainly and demonstrates BOTH
mechanisms — correlation-based low-correlation combination, and regime
weight-gating — on a documented set: four zoo formulas from four different
families (reversal/liquidity, momentum, low-volatility, illiquidity),
evaluated on the REAL price panel with REAL daily rank-IC. This is a
demonstration of the mechanism, not a claim that these four have each
individually cleared Gate B — none of them (beyond the one card actually run
through the loop) has a pre-registration, a fresh-fold confirmation, or a
red-team survival on record.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from src import backtester as bt
from src import gates as G
from src import loop as L
from src.config import RANDOM_SEED
from src.memory import Memory

np.random.seed(RANDOM_SEED)
OUT_DIR = REPO_ROOT / "artifacts"
HORIZON = 5

DEMO_FORMULAS = {
    "reversal_pv_covar": "mul(-1, rank(covariance(rank(high), rank(volume), 6)))",
    "momentum_12_1": "sub(div(delay(close, 21), delay(close, 252)), 1)",
    "low_volatility": "mul(-1, ts_std(returns, 21))",
    "illiquidity_amihud": "ts_mean(div(abs(returns), mul(close, volume)), 21)",
}

REGIMES = ("bull", "bear", "calm", "volatile", "highvol")


def _icir(series: pd.Series) -> float:
    s = series.dropna()
    if len(s) < 2 or s.std(ddof=1) == 0:
        return float("nan")
    return float(s.mean() / s.std(ddof=1))


def demo_on_documented_set() -> dict:
    bt.clear_panel()
    panel = L.build_price_panel()
    _, labels = bt._load_panel()

    daily = {}
    for name, formula in DEMO_FORMULAS.items():
        sig = L.evaluate_signal(formula, panel)
        ic = G.daily_rank_ic(sig, "val_a", HORIZON)
        daily[name] = ic
        print(f"  {name:22s} mean_ic={ic.mean():.4f}  icir={_icir(ic):.3f}  n_days={len(ic)}")

    D = pd.DataFrame(daily).dropna(how="all")
    corr = D.corr()
    inv = {n: 1.0 / (corr[n].drop(n).abs().mean() + 1e-6) for n in D.columns}
    tot = sum(inv.values())
    static_weights = {n: inv[n] / tot for n in D.columns}
    combined_static = sum(D[n] * static_weights[n] for n in D.columns).dropna()
    combined_icir = _icir(combined_static)
    individual_icir = {n: _icir(D[n]) for n in D.columns}

    print(f"\n  correlation matrix:\n{corr.round(3)}")
    print(f"  static (inverse-|corr|) weights: {static_weights}")
    print(f"  combined ICIR={combined_icir:.3f}  vs best individual "
          f"ICIR={max(individual_icir.values()):.3f}")
    beats_best = combined_icir >= max(individual_icir.values())
    print(f"  combined beats best individual: {beats_best}")

    # -- regime weight-gating --------------------------------------------
    regime_labels = bt._regime_labels(labels).reindex(D.index).fillna(False)
    per_regime = {}
    for r in REGIMES:
        mask = regime_labels[r]
        days = D.index[mask.reindex(D.index, fill_value=False)]
        D_r = D.loc[D.index.intersection(days)]
        if len(D_r) < 30:
            per_regime[r] = {"n_days": len(D_r), "note": "too few days, skipped"}
            continue
        corr_r = D_r.corr()
        inv_r = {n: 1.0 / (corr_r[n].drop(n).abs().mean() + 1e-6) for n in D_r.columns}
        tot_r = sum(inv_r.values())
        weights_r = {n: inv_r[n] / tot_r for n in D_r.columns}
        combined_gated = sum(D_r[n] * weights_r[n] for n in D_r.columns).dropna()
        combined_static_r = sum(D_r[n] * static_weights[n] for n in D_r.columns).dropna()
        icir_gated = _icir(combined_gated)
        icir_static_r = _icir(combined_static_r)
        per_regime[r] = {
            "n_days": int(len(D_r)), "weights": weights_r,
            "icir_regime_gated": icir_gated, "icir_static_weights": icir_static_r,
            "gating_improves_icir": bool(np.isfinite(icir_gated) and np.isfinite(icir_static_r)
                                         and icir_gated > icir_static_r),
        }
        print(f"  [{r:9s}] n_days={len(D_r):4d}  gated_icir={icir_gated:.3f}  "
              f"static_icir={icir_static_r:.3f}  "
              f"gating_improves={per_regime[r]['gating_improves_icir']}")

    return {
        "status": "demonstration_on_documented_set",
        "note": "fewer than 2 real accepted cards on record — demonstrating the "
                "combination + regime-gating mechanism on 4 documented formulas "
                "from 4 families, scored on the real panel; NOT a claim that "
                "these 4 have individually cleared Gate B.",
        "formulas": DEMO_FORMULAS,
        "individual_rank_ic": {n: float(D[n].mean()) for n in D.columns},
        "individual_icir": individual_icir,
        "correlation_matrix": corr.round(4).to_dict(),
        "static_weights": static_weights,
        "combined_icir": combined_icir,
        "beats_best_individual": beats_best,
        "regime_gating": per_regime,
    }


def main() -> None:
    print("=" * 78)
    print("PORTFOLIO POST-PROCESS")
    print("=" * 78)

    mem = Memory()
    real = L.portfolio_combine(mem, split="val_a", horizon=HORIZON)
    print(f"\n[real accepted book] status={real['status']}  n_accepted={real.get('n_accepted')}")

    result = {"real_book": real}
    if real["status"] == "ok" and real["n_accepted"] >= 2:
        print("  Real book has >=2 accepted cards — using it as the primary result.")
        result["primary"] = "real_book"
    else:
        print("  Fewer than 2 real accepted cards — demonstrating the mechanism "
              "on a documented set (real formulas, real panel, real daily IC):\n")
        demo = demo_on_documented_set()
        result["demonstration"] = demo
        result["primary"] = "demonstration"

    out = OUT_DIR / "portfolio_report.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
