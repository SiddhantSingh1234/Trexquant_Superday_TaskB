# Phase 9 handoff — Red-Team test menu

> **Status: READY FOR REVIEW (rev 2).** Do not start Phase 10.
> 15/15 P9 tests, 263/263 full suite, no network. The two spec-level concerns
> raised at first review were fixed **at source** (not worked around in P9) at
> the owner's direction — see §6.

Phase 9 is the eleven pre-written, parameterized falsification backtests plus the
survive/kill rule. An LLM agent (Phase 8, `src/agents/redteam.py`) picks *which*
attacks fit a signal; this module *is* the attacks — it never runs agent-authored
code. **Every one of the eleven is rejection-only** (it can kill a candidate but
never promote one), so every backtest fired here is written to the ledger with
`counts_as_trial=0` and the Deflated-Sharpe trial count is untouched.

---

## 1. What was built / changed

| File | Change | Purpose |
|---|---|---|
| `src/redteam.py` | **new**, ~470 ln | `run_redteam()` + the 11 tests + `_Runner` (records every backtest `counts_as_trial=0`) |
| `tests/test_p9_redteam.py` | **new**, ~340 ln | 15 tests; AR(1)-latent fixture panel (see §7.6) |
| `reports/p9_measure.py` | **new** | reproduces every measured value below |
| `src/backtester.py` | **mod** | `_regime_mask` → `_regime_labels` (expanding-window, look-ahead removed); `_expanding_quantile` helper; `VALID_REGIMES`; `+highvol` |
| `tests/test_p4_backtester.py` | **mod** | regime cases moved to a trending-market fixture; `test_regime_labels_are_expanding_window_only` |
| `src/universe.py` | **mod** | `build_liquidity_ranks()` — new per-symbol monthly ranking output |
| `src/config.py` | **mod** | `LIQUIDITY_RANKS_PARQUET`, `UNIVERSE_STATS_PARQUET` |
| `tests/test_p1_universe.py` | **mod** | `test_liquidity_ranks_emitted` |
| `data/universe/liquidity_ranks.parquet` | **new** | 26,395 rows / 132 months (real P1 data) |
| `IMPLEMENTATION_PLAN.md`, `PLAN_EXPLAINED.md`, `FLOW_EXPLAINED.md`, `INITIAL_PLAN.md` | **mod** | decisive/diagnostic split, test-4 rule, regime source, test-11 file — so P13 slides read correctly |

### The eleven tests

| # | name | mechanism | kind |
|---:|---|---|---|
| 1 | `subsample_year` | drop the single best year; kill if RankIC collapses >50% **and** loses significance, or <50% of years positive | **decisive** |
| 2 | `regime_split` | `backtest(subsample={"regime": bull/bear/highvol})` (expanding-window labels); kill if RankIC ≤ 0 in bull **or** bear (≥60 days each) | **decisive** |
| 3 | `size_tercile` | `subsample={"size_tercile"}` — trailing-turnover `size_proxy`, not market cap | diagnostic |
| 4 | `cost_sweep` | `cost_bps ∈ {5,15,30}`; kill if net Sharpe/return ≤ 0 at 15 bps, **or** Sharpe cut >50% **and** survivor < 0.5 | **decisive** |
| 5 | `extra_lag` | `extra_lag=1`; kill if RankIC ≤ 0, loses significance, or collapses >50% | **decisive** |
| 6 | `delivery_lag` | shift **only** `delivery_pct` by 1 day, re-evaluate the formula; `localized` iff it collapses here but not under #5 | diagnostic |
| 7 | `sector_neutral` | `neutralize="sector"` | diagnostic |
| 8 | `liquidity_filter` | `subsample={"min_turnover": p40}` (40th pctile of `exp(turnover_21)` in split) | diagnostic |
| 9 | `decay_curve` | RankIC decay from the baseline backtest; flags if the claimed horizon isn't where the edge lives | diagnostic |
| 10 | `sign_stability` | sign of per-year RankIC; kill if the modal sign holds in <70% of folds | **decisive** |
| 11 | `universe_edge` | drop the names ranked **150-200 by trailing liquidity that month**, read from `data/universe/liquidity_ranks.parquet` (P1) | diagnostic |

**Survive rule:** `verdict = "killed"` iff any **decisive** test (1,2,4,5,10) flags;
else `"survives"`. Diagnostic flags go in `flagged_diagnostics` and never flip the
verdict. **The five decisive tests always run**, unioned with the agent's
selection — `forced_decisive_tests` names any it skipped.

---

## 2. Acceptance criteria — every one, with a measured value

Fixtures: AR(1) latent (φ 0.9) + a market cycle in the raw returns; `N_DAYS=1200`,
`N_SYMBOLS=50`, `split="train+val_a"`, seed 42. Reproduce with
`./.venv/Scripts/python.exe reports/p9_measure.py`.

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | All 11 run against a fixture signal, documented shape | ✅ PASS | `test_all_eleven_run_and_return_shape` — `set(results)==REDTEAM_MENU`, every result carries `"flag"`, `verdict∈{survives,killed}`, `counts_as_trial==0`, `n_backtests > 10` |
| 2 | Leaky signal killed by test 5 | ✅ PASS | `fwd_ret_1` as its own signal: baseline RankIC **1.0000** → after `extra_lag=1` **0.0018** → `extra_lag` flag, `failed_tests==['extra_lag']`, verdict **killed** |
| 3 | One-lucky-year signal killed by test 1 | ✅ PASS | noise except 2019: drop-best-year (2019) → RankIC **0.00185**, insignificant → `subsample_year` flag, verdict **killed** |
| 4 | High-turnover thin-gross signal killed by test 4 | ✅ PASS | gross Sharpe **0.415**, net Sharpe at 15 bps **−7.97** → `cost_sweep` flag, verdict **killed** |
| 5 | Every red-team backtest `counts_as_trial=0` | ✅ PASS | full run: **25** backtests → **25** ledger rows, all `counts_as_trial==0`, every `rejection_reason` starts `"redteam:"`, `ledger.n_trials()==0` |
| 6 | Test 11 reads `liquidity_ranks.parquet`, not a hard-coded list | ✅ PASS | `test_universe_edge_reads_the_liquidity_rank_file`: pass a P1-shaped frame → fringe source = *"data/universe/liquidity_ranks.parquet …"*, **> 0** fringe names; no ticker-like literal anywhere in `redteam.py` (regex assert). `p9_measure.py` exercises the **fallback** (SYM-fixture disjoint from the real on-disk file) → 17 fringe names, source `"universe.compute_selection(prices) [fallback…]"` |
| 7 | Regime labels use expanding-window thresholds only | ✅ PASS | `bt._regime_labels`: truncating the label panel at 55% leaves **every** past regime label bit-identical (`test_regime_labels_are_expanding_only` in P9 + `test_regime_labels_are_expanding_window_only` in P4); a full-sample quantile *does* flip labels (`test_full_sample_threshold_would_be_detectable`). Fixture regimes populated: bull **516** / bear **492** / highvol **396** days |

### Behaviour tests (beyond the 7 criteria)

| Test | Result | Measured |
|---|---|---|
| clean AR(1) signal **survives** all 11 | ✅ PASS | baseline RankIC **0.0357**, t **8.61**; `failed_tests==[]`, `flagged_diagnostics==[]`. `cost_sweep` 3.97→1.25 net Sharpe (not killed). `extra_lag` 0.0357→0.0324. `universe_edge` 0.0357→0.0319 |
| `regime_split` populates & is decisive on the fixture | ✅ PASS | bull **516** / bear **492** / highvol **396** days; `decisive_comparable=True`, `flag=False` (clean signal positive in both) |
| sign-flipping signal killed by test 10 | ✅ PASS | per-year sign consistency **0.60** < 0.70; all 5 decisive tests flag it |
| test 6 collapses a `delivery_pct`-only signal | ✅ PASS | baseline RankIC **0.0273** → shift only `delivery_pct` → **−0.0127** (collapse + sign flip) |
| `universe_edge` fallback (no rank file) recomputes from prices | ✅ PASS | `test_universe_edge_falls_back_to_recomputing_when_no_rank_file` — source string mentions `compute_selection` |
| decisive tests always run when unselected | ✅ PASS | `tests=["sector_neutral"]` → all 5 decisive in `tests_run`; `forced_decisive_tests` = the 5 |
| determinism | ✅ PASS | two runs → identical `results`, `baseline`, `verdict` |

---

## 3. Verify it yourself

```
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_p9_redteam.py -q   # 15 passed (~5 min)
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_p4_backtester.py -q # 28 passed
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_p1_universe.py -q   # 13 passed
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest -q                            # 263 passed
PYTHONUTF8=1 ./.venv/Scripts/python.exe reports/p9_measure.py                   # every §2 number
```

### 3.1 Full-suite status
**263 passed in 721.6 s, exit 0.** (was 256 before this phase: +4 P4 regime tests,
+2 net P9 tests, +1 P1 test.) Nothing regressed — the P4 and P1 changes are
covered by their own suites (28/28, 13/13) and no other test moved.

Spot check:
```
PYTHONUTF8=1 ./.venv/Scripts/python.exe -c "
import numpy as np, pandas as pd
from src import backtester as bt, contracts as C, redteam as RT
from src.ledger import Ledger
import tests.test_p9_redteam as T
f,l,latz = T._persistent_panel(); bt.use_panel(f,l)
px = C.make_fake_ohlcv(n_days=T.N_DAYS,n_symbols=T.N_SYMBOLS,seed=42)
print('clean :', RT.run_redteam(latz,'train+val_a',prices=px,ledger=Ledger(':memory:'))['verdict'])
leak = l.pivot_table(index='date',columns='symbol',values='fwd_ret_1')
print('leaked:', RT.run_redteam(leak,'train+val_a',prices=px,ledger=Ledger(':memory:'))['verdict'])
"
# expect: clean : survives   /   leaked: killed
```

---

## 4. What I could NOT verify

- **Real-data behaviour.** All numbers are on synthetic fixtures. Phase 10 produces
  the first real candidate signal + real panel.
- **`regime_split` as a *kill* on a real bull-only signal.** Verified it populates,
  is decisive on the fixture, and does not kill a genuinely broad signal — not that
  it kills a real regime-dependent one (the fixture's regimes are engineered).
- **LLM agent → menu hand-off end-to-end** (contract-checked on both sides; joined
  only in Phase 10).

## 5. Failures and open issues

None open.
- `test_liquidity_ranks_emitted` first failed because the final month-end
  selection (2025-12-31, no trading day follows it) is never in force, so its 5
  fresh-listing names are in the ranking but not in membership. **Fixed:** P1 drops
  those 5 rows for consistency with the daily panel (logged in the P1 report);
  the test now allows non-contiguous ranks in that one month.
- First P4 run of the trending-market regime cases: fine. `test_p4` 28 passed.

## 6. Spec concerns from the first review — resolved at source

1. **Test 11 / `universe_stats.parquet`.** That file has only aggregate monthly
   rows and cannot answer "which names are ranked 150-200". **P1 now emits
   `data/universe/liquidity_ranks.parquet`** (`month_end · symbol · liquidity_rank
   · trailing_turnover`, `build_liquidity_ranks`), and test 11 reads it. It
   recomputes from the price panel only as a fallback (fixtures / missing file).
   `IMPLEMENTATION_PLAN.md` Phase 1 Outputs and Phase 9 updated.
2. **P4 regime look-ahead.** `backtester._regime_mask` split calm/volatile on a
   **full-sample** median vol — a look-ahead. The **only** caller of
   `subsample={"regime":...}` was the P4 test (grep-confirmed: no production code,
   not P6). **Fixed at source:** `_regime_labels` is expanding-window
   (bull/bear = trailing-63d compounded return ±5%; calm/volatile vs expanding
   median; highvol vs expanding top tercile), with a truncation-invariance test.
   The red-team dropped its own regime copy and calls the backtester.
   `IMPLEMENTATION_PLAN.md` Phase 4 subsample doc updated.
3. **Decisive-tests-always-run** and the **test-4 kill rule** are now written into
   `IMPLEMENTATION_PLAN.md` (Phase 9 "Survive rule"), `PLAN_EXPLAINED.md`
   (D11-UPDATE-2), `FLOW_EXPLAINED.md` (S8), `INITIAL_PLAN.md`.

## 7. Decisions I made that the spec left open

1. **The five decisive tests always run**, unioned with the agent's selection.
   `forced_decisive_tests` names any the agent skipped. The agent still chooses
   which *diagnostics* to add. Now documented in the plan.
2. **Test-4 kill rule:** net book unprofitable at 15 bps (`sharpe ≤ 0` or
   `ann_return ≤ 0`), **or** Sharpe cut > 50 % **and** surviving Sharpe < 0.5.
   The `0.5` floor is my number. ">50% degradation" is kept literal for test 5.
   Now documented in the plan.
3. **`RT_SIG_T = 1.5`** for the year/regime sub-sample significance floor (vs the
   project's `T_STAT_BAR = 3.0`, unreachable on a 60-day fold).
4. **`highvol`** added to the backtester's regime vocabulary (the spec's "high-vol"
   for red-team test 2); `calm`/`volatile` kept and fixed to expanding.
   `bull`/`bear` changed from a 0% sign split to ±5% (P9's explicit definition;
   the P4 spec left thresholds open).
5. **`universe_edge` fringe** = ranks 150-200 when a month has ≥ 200 names, else
   the bottom `round(n·150/200)` band. Signal cells NaN'd per *governing month*.
6. **P9 test fixture uses an AR(1) latent (φ 0.9)**, not `contracts.make_fake_*`.
   With the IID P0 latent every signal's edge is on day *t* alone, so
   `extra_lag=1` collapses everything and the "survives" branch is untestable.
   **This is a test-input choice only** — `src/redteam.py` generates no data and
   behaves identically on the real panel; `contracts.make_fake_*` is unchanged.
   The AR(1) constants are hand-tuned; editing them can flip a boundary assertion
   in that one test file.
7. **Test 6 `localized`** finalized in `run_redteam` after test 5 is known:
   collapsed here **and** not under the global lag.
8. **`horizon`** snaps `thesis["horizon_days"]` to the nearest of
   `(1,2,3,5,10,21)`; default 1.
9. **The final month-end selection's fresh listings are dropped from
   `liquidity_ranks.parquet`** (5 names, 2025-12-31) so it matches the daily
   membership panel, which never applies that selection.

## 8. STOP

Phase 9 code-complete, self-verified: **15/15 P9**, **28/28 P4**, **13/13 P1**,
**full suite 263 passed / exit 0**. Both first-review spec concerns fixed at
source (P4 regime look-ahead, P1 rank file) with no other phase affected; flags
3–5 and the residual doubts written into the plan + design docs. Not starting
Phase 10. Awaiting owner sign-off.
