"""Phase 11 — BAD example (2) STATISTICS: look-ahead leakage a purely
statistical gate would have PASSED.

Reproducible from a seed and a single command:
    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/p11_bad_stats.py

Beat 1 (naive result): a "signal" that is (as if by a data-pipeline bug — a
field joined one day early, an off-by-one in a merge) 85% the forward return
it is supposed to predict, plus 15% noise (an exact copy would give the
daily IC series zero variance and break the Sharpe ratio itself rather than
illustrate the point). Its Tier-1 RankIC on the REAL panel is still
spectacular. Its Deflated Sharpe clears DSR_MIN just as easily; a
statistics-only gate has nothing to say against it.

Beat 2 (the system catches it): red-team test 5 (`extra_lag`) shifts the
whole signal forward one extra trading day. A genuine edge survives a 1-day
shift (real information persists); an identity-leak on tomorrow's return does
not -- RankIC collapses to ~0 and the test kills it.

Beat 3 (the fix): this is exactly why Gate C (red-team) exists as a SEPARATE
mechanism from Gate B (statistics). DSR/PBO ask "did we search too much for
this?"; `extra_lag` asks "is this actually causal, or does it die under a
lag any honest trading process would incur?" -- different failure classes,
different instruments.

Nothing here touches HOLDOUT.
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
from src import redteam as RT
from src.config import RANDOM_SEED
from src.ledger import Ledger

np.random.seed(RANDOM_SEED)
OUT_DIR = REPO_ROOT / "artifacts" / "p11_bad_stats"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    print("=" * 78)
    print("BAD EXAMPLE 2 -- STATISTICS: look-ahead leakage")
    print("=" * 78)

    bt.clear_panel()  # use the real, on-disk Phase-3 panel
    feats, labels = bt._load_panel()
    horizon = 1   # NON-overlapping single-day label -- a lag genuinely
                  # decorrelates it (a 5-day label mostly overlaps itself
                  # under a 1-day shift and would understate the point)
    leak_col = f"fwd_ret_{horizon}_demeaned"
    label_wide = labels.pivot(index="date", columns="symbol", values=leak_col)
    # A pipeline bug that joins a field one day early rarely reproduces the
    # label EXACTLY -- and an exact match gives the daily IC series zero
    # variance, which breaks the Sharpe ratio (division by zero) rather than
    # illustrating the point. 85% label + 15% independent noise keeps the
    # leak "spectacular" (RankIC ~0.9+) while keeping the DSR well-defined.
    rng = np.random.default_rng(RANDOM_SEED)
    noise = pd.DataFrame(rng.standard_normal(label_wide.shape) * label_wide.stack().std(),
                          index=label_wide.index, columns=label_wide.columns)
    leaky_signal = 0.85 * label_wide + 0.15 * noise
    print(f"\n[naive result] 'formula' == 85% the label ({leak_col}) + 15% noise -- "
          f"stands in for a data-pipeline bug that joins a field one day "
          f"early (e.g. a same-day macro release, a delivery figure with a "
          f"broken lag) rather than anything the causal operator grammar "
          f"would produce directly (negative `delay()` windows are "
          f"structurally rejected -- see src/operators.py `_window`). The "
          f"85/15 mix (not an exact label copy) keeps the daily IC series "
          f"from being degenerate (std=0), which would otherwise break the "
          f"Sharpe ratio itself rather than illustrate the point.")

    m_a = bt.backtest(leaky_signal, "val_a", horizon=horizon)
    print(f"  Tier-1 VAL_A: rank_ic={m_a['rank_ic']:.4f}  t_stat={m_a['t_stat']:.2f}"
          f"  n_days={m_a['n_days']}")

    pre_sign = 1 if m_a["rank_ic"] >= 0 else -1
    card = {
        "card_id": "diag_bad_stats", "thesis_id": "th_bad_stats",
        "thesis": {"horizon_days": horizon}, "ast_canonical": leak_col,
        "formula": leak_col, "pre_registered": {"sign": pre_sign},
    }
    ledger = Ledger(":memory:")
    verdict, reasons, audit = G.gate_b(
        card, None, ledger, signal=leaky_signal, split="val_a",
        horizon=horizon, do_holdout_peek=False,
    )
    print(f"\n[Gate B statistics — HOLDOUT NOT touched]")
    print(f"  verdict={verdict}  reasons={reasons or '(none — clears novelty+stats easily)'}")
    print(f"  marginal_ic={audit.get('marginal_ic'):.4f}  "
          f"deflated_sharpe={audit.get('deflated_sharpe'):.3f} (DSR_MIN={G.DSR_MIN})  "
          f"t_stat={audit.get('t_stat'):.2f} (T_STAT_BAR={G.T_STAT_BAR})  "
          f"pbo={audit.get('pbo'):.3f} (PBO_MAX={G.PBO_MAX})")
    print(f"  -> a statistics-only gate would ACCEPT this.")

    rt_report = RT.run_redteam(
        leaky_signal, tests=["extra_lag"], split="val_a", horizon=horizon,
        sign=pre_sign, ledger=None,
    )
    el = rt_report["results"]["extra_lag"]
    print(f"\n[Red-team test 5 — extra_lag]")
    print(f"  base_rank_ic={el['base_rank_ic']:.4f} -> lagged={el['rank_ic_lagged']:.4f}"
          f"  t_lagged={el['t_stat_lagged']:.2f}  degradation={el['degradation']}")
    print(f"  flag={el['flag']}  verdict={rt_report['verdict']}"
          f"  failed_tests={rt_report['failed_tests']}")

    result = {
        "signal": f"label itself ({leak_col}) — stand-in for a pipeline look-ahead bug",
        "tier1_val_a": {k: float(m_a[k]) for k in ("rank_ic", "t_stat", "n_days")},
        "gate_b_statistics": {
            "verdict": verdict, "reasons": reasons,
            "marginal_ic": audit.get("marginal_ic"),
            "deflated_sharpe": audit.get("deflated_sharpe"), "dsr_min": G.DSR_MIN,
            "t_stat": audit.get("t_stat"), "t_stat_bar": G.T_STAT_BAR,
            "pbo": audit.get("pbo"), "pbo_max": G.PBO_MAX, "holdout_touched": False,
            "would_a_pure_statistics_gate_accept": verdict == "accept",
        },
        "redteam_extra_lag": el,
        "redteam_verdict": rt_report["verdict"],
        "teaching_point": "Deflated Sharpe / PBO measure OVER-SEARCHING, not CHEATING. "
                           "A single, un-searched, perfectly leaky signal has n_trials=1 "
                           "and passes DSR trivially; only a causality stress (extra_lag) "
                           "catches it.",
    }
    (OUT_DIR / "result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {OUT_DIR / 'result.json'}")


if __name__ == "__main__":
    main()
