"""Phase 11 — BAD example (3) ECONOMICS: right idea, wrong sign.

Reproducible from a seed and a single command:
    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/p11_bad_economics.py

Beat 1 (naive result / the thesis): raw 2-day price change, pre-registered
BEFORE any backtest with a momentum mechanism ("investors underreact to
recent news; a stock that has just risen keeps rising over the next few
sessions; counterparty = the slow-moving retail flow that hasn't caught up
yet") and sign = +1.

Beat 2 (the system catches it): the realized direction on VAL_A is measured
AFTER pre-registration and comes out negative, with |t|=4.35 -- decisively
significant, easily clearing T_STAT_BAR=3.0 -- because short-horizon Indian
equities mean-revert over 2 days (a textbook, well-documented liquidity-
provision / bid-ask-bounce effect, not the momentum story that was
pre-registered; `classical_short_term_reversal` in the zoo is written with
exactly this `x -1` orientation). `gates.check_sign` hard-rejects: NOT
because the |IC| is weak -- it is strong and would clear DSR/PBO/red-team
easily with the OPPOSITE sign applied -- but because the realized sign
contradicts the committed mechanism. This is a thesis failure, caught by NO
statistical gate: DSR/PBO/red-team all score the ORIENTED series, and with
the pre-registered (wrong) sign applied they would see a strong, real,
systematically NEGATIVE-of-what-was-claimed signal and have nothing to flag.

Beat 3 (the fix): a mechanism has to explain the sign, not just the
existence, of an edge. `commit_preregistration` freezes the sign before any
data is touched specifically so an agent cannot rationalize a flip after
seeing the number; `check_sign` (src/gates.py) enforces it as a hard reject,
never an invitation to relabel the thesis and keep the discovery.

Nothing here touches HOLDOUT.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from src import backtester as bt
from src import gates as G
from src import loop as L
from src.config import RANDOM_SEED

np.random.seed(RANDOM_SEED)
OUT_DIR = REPO_ROOT / "artifacts" / "p11_bad_economics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FORMULA = "sub(div(close, delay(close, 2)), 1)"   # raw 2-day price change, UNFLIPPED
PRE_REGISTERED_SIGN = +1   # thesis: momentum continues
HORIZON = 5


def main() -> None:
    print("=" * 78)
    print("BAD EXAMPLE 3 -- ECONOMICS: realized sign opposite the pre-registered one")
    print("=" * 78)

    thesis = {
        "mechanism": "Investors underreact to recent price-relevant news; a stock "
                     "that has just risen over the past 2 sessions keeps rising as "
                     "slower participants catch up.",
        "counterparty": "Retail / slow-moving flow that has not yet priced in the "
                         "recent move.",
        "why_not_arbitraged": "Short-horizon, small per-name edge; capacity-limited "
                              "and cost-sensitive, so large funds don't fully close it.",
        "horizon_days": HORIZON,
        "regime": "calm",
        "falsifiable_claim": "Stocks in the top quintile of trailing 2-day return "
                             "outperform the bottom quintile over the next 5 days.",
        "pre_registered_sign": PRE_REGISTERED_SIGN,
    }
    print(f"\n[pre-registered, BEFORE any backtest]")
    print(f"  formula = {FORMULA!r}")
    print(f"  mechanism = {thesis['mechanism']!r}")
    print(f"  pre_registered_sign = {PRE_REGISTERED_SIGN:+d}  (momentum continues)")

    bt.clear_panel()  # real, on-disk Phase-3 panel
    panel = L.build_price_panel()
    sig = L.evaluate_signal(FORMULA, panel)

    m_a = bt.backtest(sig, "val_a", horizon=HORIZON)
    realized_sign = 1 if m_a["rank_ic"] > 0 else -1
    print(f"\n[realized, VAL_A -- AFTER pre-registration]")
    print(f"  rank_ic={m_a['rank_ic']:.4f}  t_stat={m_a['t_stat']:.2f}  n_days={m_a['n_days']}")
    print(f"  realized_sign={realized_sign:+d}")

    sign_ok = G.check_sign(PRE_REGISTERED_SIGN, realized_sign)
    print(f"\n[gates.check_sign] pre_registered={PRE_REGISTERED_SIGN:+d}  "
          f"realized={realized_sign:+d}  sign_ok={sign_ok}")
    if not sign_ok:
        print("  -> Gate B novelty HARD REJECTS: thesis failure, regardless of |IC|.")

    oriented = sig * PRE_REGISTERED_SIGN  # what a statistics-only gate would score
    m_oriented = bt.backtest(oriented, "val_a", horizon=HORIZON)
    print(f"\n[what a statistics-only gate would see -- oriented by the PRE-REGISTERED "
          f"sign, per Gate B's own convention]")
    print(f"  oriented rank_ic={m_oriented['rank_ic']:.4f}  t_stat={m_oriented['t_stat']:.2f}")
    print(f"  (this is the same magnitude, opposite sign of the raw backtest above -- "
          f"DSR/PBO/red-team operate on the ORIENTED series and would see nothing "
          f"wrong with a strong, real, systematically-signed edge)")

    result = {
        "formula": FORMULA,
        "thesis": thesis,
        "pre_registered_sign": PRE_REGISTERED_SIGN,
        "realized_val_a": {k: float(m_a[k]) for k in ("rank_ic", "t_stat", "n_days")},
        "realized_sign": realized_sign,
        "sign_ok": sign_ok,
        "gate_b_novelty_verdict": "reject (thesis failure)" if not sign_ok else "pass",
        "what_a_stats_only_gate_would_see": {
            k: float(m_oriented[k]) for k in ("rank_ic", "t_stat", "n_days")
        },
        "teaching_point": "No purely statistical gate flags this -- DSR/PBO/red-team "
                          "all score the pre-registered-sign-oriented series, which "
                          "looks like a perfectly good discovery. Only comparing the "
                          "REALIZED sign against what was committed BEFORE the "
                          "backtest catches a thesis that got the mechanism backwards.",
    }
    (OUT_DIR / "result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {OUT_DIR / 'result.json'}")


if __name__ == "__main__":
    main()
