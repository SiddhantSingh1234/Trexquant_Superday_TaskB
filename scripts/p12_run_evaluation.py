"""Phase 12 verification entry point.

Rebuilds the seeded ablation pool, scores it through Gate B / Gate C, and
prints the exact tables and numbers reports/p12_system_evaluation.md quotes.
Deterministic (RANDOM_SEED=42) -- re-running reproduces the same figures.

    python scripts/p12_run_evaluation.py
"""
import sys
import time

sys.path.insert(0, ".")
from src import evaluation as ev  # noqa: E402

t0 = time.time()
out = ev.run_evaluation()
print(f"elapsed {time.time() - t0:.1f}s")

pool = out["pool_df"]
print(pool[["name", "category", "marginal_ic", "dsr", "t_stat", "pbo", "n_days_scored",
            "novelty_pass", "stats_pass", "redteam_pass"]].to_string())
print("\n-- per-gate catch / false-kill --")
print(out["catch_df"])
print("\n-- FDR, gate on vs off --")
print(out["fdr_df"])
print("\n-- pseudo-generations (fake-learning proxy) --")
print(out["gen_df"].to_string())
print("\n-- real ledger snapshot --")
print(out["real_ledger"])
print("\n-- real cards snapshot --")
print(out["real_cards"])
print(f"\nplots written to {ev.PLOTS_DIR}")
