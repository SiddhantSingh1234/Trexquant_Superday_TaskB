# Phase 11 handoff — Demo run: one good card, three bad examples

> Status: **READY FOR REVIEW.** Do not start Phase 12.

## 1. What was built

| File | Purpose |
|---|---|
| `scripts/p11_good_card.py` | Runs the REAL, unmodified `src/loop.py` graph (Gate A → Gate B novelty/statistics → HOLDOUT → Gate C red-team) on a documented, published formula instead of an LLM-authored one. Contains the full attempt log (§3) in its docstring. |
| `scripts/p11_bad_data.py` | BAD example ① — rebuilds a Phase-3-shaped panel from the supplied constituent CSV (naive use) instead of Phase 1's real universe; runs DSR/PBO/purge-embargo/red-team against it; reconciles against the real universe. |
| `scripts/p11_bad_stats.py` | BAD example ② — a simulated data-pipeline leak (85% label + 15% noise); shows Gate B statistics accepting it and red-team's `extra_lag` killing it. |
| `scripts/p11_bad_economics.py` | BAD example ③ — pre-registers a momentum thesis, measures a realized reversal, shows `gates.check_sign` hard-rejecting a statistically strong, correctly-oriented edge. |
| `scripts/p11_build_bad_cards.py` | Assembles `bad_data.json` / `bad_stats.json` / `bad_economics.json` (Section 0.5 schema) from the three scripts' saved results — no new computation. |
| `scripts/p11_portfolio.py` | Off-loop portfolio combination + regime weight-gating; falls back to a documented 4-formula demonstration set (only 1 real accepted card on record). |
| `src/backtester.py` (mod, 8 lines) | **Real bug fix**, found during attempt 4: `_shift_signal` crashed (`IndexError: arrays used as indices must be of integer or boolean type`) whenever the signal's date range extends past the label calendar (the normal case for a full-history real panel) — a float/NaN-typed index array was never cast back to int after being filtered. Fixed; `tests/test_p4_backtester.py` 28/28 still pass. |
| `src/gates.py` (mod, 4 lines) | Extracted the inline `0.3` holdout-collapse literal into a named, documented constant `HOLDOUT_COLLAPSE_FLOOR = 0.30`, matching the pattern of `DSR_MIN`/`PBO_MAX`/`T_STAT_BAR` — makes it a legitimate, disclosed override target (see §4). `tests/test_p6_gates.py` 30/30 still pass. |
| `artifacts/cards/good_p11.json` | The accepted card. |
| `artifacts/cards/bad_data.json`, `bad_stats.json`, `bad_economics.json` | The three bad-example cards, `verdict="reject"`. |
| `artifacts/portfolio_report.json` / `.md` | Portfolio post-process output. |
| `reports/p11_demo.md` | The presentation narrative — all four examples, three beats each. |

No P0–P10 file besides the two 4-8 line, test-verified fixes above was modified.

---

## 2. Acceptance criteria — every one, with a MEASURED value

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | At least one genuinely accepted card exists with a complete audit trail | ✅ PASS (with disclosed overrides — see §4) | `good_p11.json`: `verdict=accept`, deflated_sharpe=0.976, pbo=0.043, t_stat=7.23, fresh-fold VAL_B t=2.95, HOLDOUT rank_ic=0.0137 (peek #4 of 12), red-team `survives` with **zero** failed tests across 6 tests run. |
| 2 | All three bad examples are reproducible from a seed and a single command | ✅ PASS | `python scripts/p11_bad_data.py`, `p11_bad_stats.py`, `p11_bad_economics.py` — each a single command, `RANDOM_SEED=42` seeded, real data, no network. Verified by re-running each (§3 below shows two mid-course reruns after fixing weak/degenerate first attempts). |
| 3 | Each bad example's report shows: the naive metric, the catching mechanism with its number, and the stated fix | ✅ PASS | See `reports/p11_demo.md` §②③④ — each has a numbered naive result, a numbered catch, and a stated fix. |
| 4 | The broken-universe example demonstrates that DSR/PBO **pass** it | ✅ PASS | `bad_data.json` audit: **deflated_sharpe=1.000, pbo=0.000** (both comfortably inside DSR_MIN=0.95 / PBO_MAX=0.50 — the project's REAL, unrelaxed thresholds), t=8.12, red-team `survives`, purge/embargo raised no flag. Caught only by reconciliation: 88/200 real names absent from the CSV union, 98.9% with zero inclusion/exclusion events. |
| 5 | Every card validates against the Section 0.5 schema | ✅ PASS | `src.contracts.validate_card` called on all four cards at write time (`p11_good_card.py` via `emit_card`'s own `validate_card` call; `p11_build_bad_cards.py` explicitly) — all four printed `VALID`. Command in §3. |

**Never write PASS without the number that proves it** — every number above is copy-pasted from a real run's output, not inferred.

---

## 3. Verify it yourself

```bash
# schema validation of all four cards
PYTHONUTF8=1 .venv/Scripts/python.exe -c "
import json
from src.contracts import validate_card
for f in ['good_p11','bad_data','bad_stats','bad_economics']:
    c = json.load(open(f'artifacts/cards/{f}.json', encoding='utf-8'))
    validate_card(c); print(f, '-> VALID, verdict =', c['verdict'])"
# expect: all four print VALID; good_p11 verdict=accept, the other three verdict=reject

# re-run any bad example (single command, real data, no network)
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/p11_bad_stats.py
# expect: Tier-1 rank_ic~0.97, Gate B statistics verdict=accept (DSR~1.0),
#         red-team extra_lag verdict=killed

PYTHONUTF8=1 .venv/Scripts/python.exe scripts/p11_bad_economics.py
# expect: pre_registered_sign=+1, realized_sign=-1, sign_ok=False

PYTHONUTF8=1 .venv/Scripts/python.exe scripts/p11_bad_data.py
# expect: Gate B statistics verdict=accept (DSR~1.0, PBO~0.0), red-team survives,
#         reconciliation shows ~88 real names missing from the CSV union

# regression check on the two touched core files
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_p4_backtester.py tests/test_p6_gates.py tests/test_p9_redteam.py -q
# expect: 28 + 30 + 15 = all passed, 0 failed (measured this session: 28/30/15 all green)

# real holdout-peek budget consumed this phase
PYTHONUTF8=1 .venv/Scripts/python.exe -c "
import sqlite3
c = sqlite3.connect('data/ledger.db').cursor()
c.execute('SELECT COUNT(*) FROM holdout_peeks'); print('peeks used (of 12, ever):', c.fetchone()[0])"
# expect: 4
```

**⚠️ Re-running `scripts/p11_good_card.py` will spend a 5th real holdout peek** if
you change the formula. Do not re-run it casually — the ledger is real and
peeks are not refundable.

---

## 4. What I could NOT verify, and why

- **Whether the good card's edge is real out-of-sample beyond the single
  peek spent.** HOLDOUT is sealed by design; one peek shows 24.9% retention
  of the VAL_A marginal IC (rank_ic 0.0137 vs 0.0550), which is a genuine,
  weaker-than-ideal replication — I could not spend a second peek on this
  same card to see if that was noise or a real (if partial) decay, and would
  not have without an explicit instruction to, given the budget is
  project-wide and irreplaceable.
- **Whether a stronger documented formula exists that clears every gate at
  the PROJECT'S REAL thresholds (DSR_MIN=0.95, HOLDOUT_COLLAPSE_FLOOR=0.30)
  without any override.** Three honest, real attempts (§ below) converged
  0.813 → 0.911 → 0.948 toward DSR_MIN=0.95 without crossing it before the
  owner directed a relaxation. I did not exhaustively search the full
  35-formula zoo × window grid — only ~35 + 12 targeted variants were
  screened (see the attempt log below); a wider or LLM-assisted search might
  find one that clears the real bars unaided. Not attempted, given the
  holdout-peek cost of testing each candidate for real.
- **Whether the portfolio mechanism's regime-gating result (3/5 regimes
  improved) generalizes.** It is measured on 4 documented, not-all-accepted
  formulas over 863 real days — Phase 12's ablation is the place a
  statistically rigorous version of this question belongs (small-sample
  caveat, same as Phase 12's own stated limitation).

---

## 5. Failures and open issues

### 5.1 The honest attempt history (the core finding of this phase)

Six real, full-pipeline attempts were run before the good card was produced.
**None fabricated; every number below is what the real gates measured.**

| # | Formula | Result |
|---|---|---|
| 1 | Alpha#16-family covariance (`high`/`volume`, 6d) | Gate B statistics REJECT: deflated_sharpe=**0.813** < 0.95 (t=5.99, pbo=0.014). |
| 2 | Alpha#13-family covariance (`close`/`volume`, 4d) | Gate B statistics REJECT: deflated_sharpe=**0.911** < 0.95 (t=6.92, pbo=0.029). |
| 3 | Alpha#13-family covariance (`vwap`/`volume`, 4d) | Gate B statistics REJECT: deflated_sharpe=**0.948** < 0.95 (t=7.50) — **0.002 short**. Trigger for the owner-directed override. |
| 4 | Same formula as #3, `DSR_MIN` relaxed to 0.90 | Gate B statistics PASSED for the first time → **exposed a real bug** in `backtester._shift_signal` (crashed inside Gate C's `extra_lag` test — never previously exercised against a real, full-date-range panel). Fixed (§1); **1 real holdout peek spent** before the crash. Re-run reached Gate C and was **REJECTED**: `cost_sweep` killed it — net Sharpe at 15bps was **negative** (turnover ≈45%/day is too fast to survive realistic costs). **2nd real peek spent.** |
| 5 | Low-volatility factor (`ts_std(returns,42)`), same relaxed DSR_MIN | Cleared Gate B statistics (chosen specifically for lower turnover, verified cost-robust in a 7-window re-screen). **Failed the HOLDOUT confirmation itself**: rank_ic=0.0137 vs. required ≥0.0165 (30% of the 0.0550 VAL_A marginal_ic) — retained only 24.9%. **3rd real peek spent.** |
| 6 | Same formula, `HOLDOUT_COLLAPSE_FLOOR` also relaxed (0.30→0.20) | **ACCEPTED.** Same real holdout number (0.0137, 24.9%) now clears the relaxed 0.20 floor. Gate C red-team run fresh: `survives`, zero flags. **4th real peek spent.** |

**4 of the project's 12 real, irreplaceable holdout peeks are now spent.**
Attempts 1-3 spent zero (rejected before reaching the peek). This is
disclosed prominently because it is the single most consequential resource
this phase used.

### 5.2 Two disclosed, owner-directed threshold overrides

Per explicit instruction ("if no card is working just reduce some of
threshold"), two Gate B parameters were relaxed **for `good_p11.json` only**:

| Parameter | Project default | Used for this card | Real measured value |
|---|---:|---:|---:|
| `DSR_MIN` | 0.95 | 0.90 | deflated_sharpe = **0.976** (clears both) |
| `HOLDOUT_COLLAPSE_FLOOR` | 0.30 | 0.20 | retention = **24.9%** (clears 0.20, not 0.30) |

Mechanics: a module-global mutate-then-restore on `src.gates`
(`G.DSR_MIN = ...; try: ... finally: G.DSR_MIN = DSR_MIN_PROJECT`), the
identical pattern `loop.maybe_tighten_gates` already uses for FDR
auto-tightening. **No permanent edit to `src/config.py` or the threshold
values in `src/gates.py`** — only `HOLDOUT_COLLAPSE_FLOOR`'s existence as a
named (rather than inline-literal) constant is a permanent, disclosed source
change (§1), and its *value* is restored after every run.
`T_STAT_BAR` (3.0) and `PBO_MAX` (0.50) were never touched — the accepted
card clears both on its own (t=7.23, pbo=0.043).

**Both the override and the real number it overrode are recorded in the
card's own `provenance.threshold_overrides` block** — a reader of
`good_p11.json` alone, without this report, can see exactly what was
relaxed and by how much.

### 5.3 Two of the four bad-example scripts needed a second pass

- `p11_bad_stats.py`: the first construction (signal == exact label) gave a
  degenerate daily-IC series (std=0 → DSR is NaN, not "trivially accepts") —
  fixed by mixing in 15% noise and switching to the 1-day (non-overlapping)
  label so the `extra_lag` test's 1-day shift actually decorrelates it.
- `p11_bad_economics.py`: the first formula (5-day reversal) measured only
  t=-1.65 — too weak to argue "no statistical gate would flag this," since a
  real DSR check might reject it for weak significance regardless of sign.
  Switched to a 2-day window (t=-4.35, decisively significant) after a
  5-window re-screen.

Both reruns are disclosed in the scripts' own docstrings/output, not hidden.

---

## 6. Anything that contradicts the spec

**The good card required two disclosed threshold relaxations to accept.**
The spec's own fallback language anticipated this class of outcome ("If the
loop fails to produce an accepted card, report that honestly — a system that
rejects everything is a finding") — but did not anticipate an owner
explicitly directing a threshold relaxation mid-phase. I complied, but only
in the disclosed, reversible, real-number-preserving form described in §5.2,
specifically because the alternative the request could have meant
(fabricating results) is explicitly forbidden by this same spec ("Do NOT
fabricate results... never fabricate or infer a result") and would defeat
the phase's own purpose. This is the single largest judgement call in this
handoff and the owner should weigh whether the override is acceptable for
the final presentation or whether `good_p11.json` should instead be replaced
with the honest "6 real attempts, no unassisted accept" finding.

---

## 7. Decisions I made that the spec left open

1. **Ideation source for the good card.** The spec says "runs the real loop
   until an accepted card emerges." I interpreted this as: the *loop
   machinery* (Gate A/B/C, fresh fold, holdout peek accounting) must be real
   and unmodified, but the *formula* need not come from a live LLM call —
   `scripts/p11_good_card.py` stubs only the `coder`/`hypothesis`/`judge`
   agents to supply a fixed, cited, literature formula, exactly as
   `IMPLEMENTATION_PLAN.md`'s "minimum viable path" note anticipates ("the
   agent loop presented as design rather than code").
2. **Structural novelty via window adaptation.** Every documented formula
   used was adapted with a different lookback window than its zoo entry
   (P6's zoo-duplicate check is an exact canonical-AST match at
   threshold=1.0), preserving the cited mechanism while passing novelty
   honestly rather than exploiting a loophole.
3. **`HOLDOUT_COLLAPSE_FLOOR` extracted as a named constant.** The spec
   never names this parameter; it was an inline `0.3` literal inside
   `gates.gate_b`. Extracting it was necessary to make the owner-directed
   override mechanically possible in the same disclosed, mutate-and-restore
   style as `DSR_MIN` — the alternative (monkey-patching the whole `gate_b`
   function) seemed more opaque, not less.
4. **Portfolio fallback set.** With only 1 real accepted card, I built the
   documented demonstration set from 4 zoo-family formulas representing 4
   different economic mechanisms (reversal, momentum, low-vol, illiquidity)
   rather than a purely synthetic panel, on the view that "documented
   formulas on the real panel" is strictly more informative than synthetic
   fixtures while remaining honestly labeled as a demonstration, not a
   4-card accepted book.
5. **Script cleanup.** Six ad-hoc screening scripts under `scratch/`
   (formula/window search used to arrive at the final candidates) were
   deleted after their findings were folded into `p11_good_card.py`'s
   docstring and this report — they were exploratory, not deliverables, and
   `scratch/` is documented elsewhere in this session as a scratch
   directory. `scripts/` retains exactly the six files needed to reproduce
   every deliverable (§1); nothing pre-existing outside Phase 11's scope
   (e.g. `fix.py`, `update_slides*.py` at the repo root) was touched.

---

## 8. STOP

Four cards built and schema-validated; `reports/p11_demo.md` carries the
three-beat narrative for each; the portfolio post-process ran on a documented
set with an honest, mixed regime-gating result; a real backtester bug was
found and fixed with regression tests still green; every threshold override
is disclosed with the real number it overrode, both in the card's own JSON
and here. 4 of 12 real holdout peeks are spent — flagged prominently for the
owner's awareness going into Phase 12/13.

**Not starting Phase 12.** Awaiting owner sign-off.
