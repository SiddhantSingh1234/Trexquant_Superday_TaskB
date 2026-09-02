# Phase 6 handoff — Statistical gates and the trial ledger

> Status: **READY FOR REVIEW (second pass).** Do not start Phase 7.
> Execution order so far: **P0 → P2 → P1 → P3 → P4 → P5 → P6**.
> P6 is the honesty machinery: an append-only trial ledger, the Deflated Sharpe
> Ratio, walk-forward, CSCV→PBO, orthogonalised marginal IC, the pre-registered
> sign check, and `gate_b` which runs them in the load-bearing order.
>
> **What changed since the first pass.** A verification pass re-derived every
> acceptance number independently instead of trusting the test asserts, and found
> **five defects that the 25 green tests did not catch** — four of them because
> the acceptance criteria test each *statistic* in isolation while the defects
> lived in **how the statistics were wired together**. All five are fixed, each
> with a regression test whose assertions the pre-fix values violate — §5 gives the
> pre-fix and post-fix number side by side for every one, so the claim is checkable
> rather than asserted. The design docs were updated so P13 can build slides from
> them (§8).

---

## 1. What was built

| File | Lines | Purpose |
|---|---|---|
| `src/ledger.py` | 280 | `Ledger` — append-only SQLite (`trials`, `holdout_peeks`). `record_trial`, `n_trials`, `trial_sharpes`, `trial_irs`, `trial_canonical_asts`, `request_holdout_peek` (returns a token exactly `HOLDOUT_PEEK_BUDGET` times, then `None` forever), `finalize_holdout_peek`, `holdout_peek_records`. `assert_no_row_removal_sql()` structurally scans the file; `init_ledger_db()` writes the empty schema. **No `DELETE` / `DROP TABLE` / `TRUNCATE` anywhere** (only the `_FORBIDDEN_SQL` tuple names the tokens, for the guard). |
| `src/gates.py` | 895 | `expected_max_sharpe`, `deflated_sharpe_ratio`, `dsr_from_ic_series`; `effective_trial_count` (+ `_corr_effective_n`); `orthogonalize`, `daily_rank_ic`, `marginal_ic`, `clear_label_cache`; `walk_forward`; `cscv_pbo`; `check_sign`; `gate_b(card, book, ledger, signal=…)`. Thresholds: `MIN_MARGINAL_IC=0.01`, `DSR_MIN=0.95`, `PBO_MAX=0.50`, `MIN_DSR_SAMPLE=60`, `LABEL_CACHE_MAXSIZE=4`. |
| `data/ledger.db` | — | Empty schema (2 tables). 24 KB. Regenerate: `python -m src.ledger`. |
| `tests/test_p6_gates.py` | 534 | **30** tests, plain `pytest`, no network. 25 acceptance + 5 regressions for the defects in §5. |

`src/config.py`, `src/contracts.py`, `src/backtester.py` and every earlier phase's
files are **unchanged**. `gates.py` reuses three things from `backtester.py`:
`_load_panel` (respects the `use_panel` test override), `MIN_STOCKS_PER_DAY`
(the thin-day threshold, 20), and the public `backtest()` (only for the HOLDOUT
peek). Same-repo reuse, no contract change. Daily RankIC is computed by a fast
vectorised wide-frame path in `gates.py` (`_wide_rank_ic`), not via the
backtester's long-form `_daily_ic`.

---

## 2. Acceptance criteria — every one, with a MEASURED value

Environment: Python 3.12.6, pandas 3.0.5, numpy 2.5.2, scipy 1.18.1.

```
./.venv/Scripts/python.exe -m pytest tests/test_p6_gates.py -q   ->  30 passed in 50.1 s
./.venv/Scripts/python.exe -m pytest -q                          -> 188 passed in 242.1 s
```

Zero regressions across P0–P5 (183 before, 188 after = 183 + 5 new).

Fixture: `make_fake_features/labels(n_days=2700, n_symbols=60, seed=42)` — 2015-01-01
→ 2025-05-07, so it spans HOLDOUT (2022-07-01 →) for the peek path. Planted
mean-daily RankIC ≈ 0.04 in `mom_21`; VAL_A scoring window = **913 days**.

| # | Criterion (spec) | Result | Measured value |
|---|---|---|---|
| 1 | Ledger is append-only; module contains **no `DELETE`** | ✅ PASS | `grep -rin 'delete\|drop table\|truncate' src/ledger.py` → **one hit, line 69**, the `_FORBIDDEN_SQL` guard tuple. `assert_no_row_removal_sql()` passes. Rows survive a close-and-reopen. |
| 2 | `request_holdout_peek` returns a token exactly `HOLDOUT_PEEK_BUDGET` times, then `None` forever | ✅ PASS | 17 requests → **12 tokens**; requests 13–17 → `None`; a further request → `None`. `holdout_peeks_used()==12`, `holdout_peeks_remaining()==0`. `HOLDOUT_PEEK_BUDGET=12`. |
| 3 | **Headline:** 200 pure-noise signals, best one's raw t-stat ≈ √(2 ln N); Deflated Sharpe **must reject it** | ✅ PASS (spec wording corrected — §6) | best-of-200 raw **t = 2.742** over T=913 (assertion band 2.5–4.2). √(2 ln 200) = 3.255 is the **ceiling**; the realised expected max of 200 normals is **2.744** (20k-draw MC) — the observed value lands on the realised figure, not the ceiling. observed_sr = 0.0908, deflator E[max SR] = **0.0927**, **DSR = 0.477** → rejected. |
| 4 | A genuinely predictive signal found in 5 trials passes the same gate | ✅ PASS | planted `mom_21`: rank_ic **0.0312**, observed_sr 0.2338, **t = 7.065**, E[max SR] (N=5) = 0.1463, **DSR = 0.9952 ≥ 0.95** → passes. End-to-end through `gate_b` → `verdict="accept"`. |
| 5 | Effective trial count for 20 near-identical formulas is materially below 20 **and is what the DSR uses** | ✅ PASS | `effective_trial_count(['div(volume,ts_mean(volume,k))' for k in 5..24])` → **1.0**. 5 distinct structures → **5.0**. Through `gate_b` with 20 such trials in the ledger: raw N **20** → `n_trials_effective` **2.0**, and 2.0 is what reaches the deflator (**pre-fix it was 20** — finding D). |
| 6 | Deflation is scoped to the **whole ledger**, not the thesis *(new criterion — finding B)* | ✅ PASS | 40 noise variants searched under **40 different `thesis_id`s**, winner gated under a fresh 41st thesis. Winner's raw **t = −3.000** (clears the naive t>3 bar from noise). `n_trials_within_thesis=0`, `n_trials_global=40`, `n_trials_effective=41`, E[max SR] **0.0728**, **DSR 0.789 → reject**, 0 peeks spent. Pre-fix: N=1, E[max SR]=0, DSR=1.000, **accept**. |
| 7 | The rationed peek scores the **residual** *(new criterion — finding A)* | ✅ PASS | Partial clone (marginal_ic 0.0154, raw_ic 0.0312) reaches step 4. `audit["holdout_scored_on"]=="residual"`; recorded `holdout_rank_ic` **0.01957** = `backtest(residual)`, ≠ `backtest(raw)` **0.03200**. |
| 8 | PBO ≈ 0.5+ for noise; low for a real signal | ✅ PASS | **300** pure-noise matrices (T=800, M=12): mean PBO **0.4859**, SE 0.0130, 95% CI **[0.460, 0.511]** — statistically indistinguishable from 0.5. One real column among 11 noise, **100** matrices: mean **0.0019**, max 0.071. `cscv_pbo` runs C(8,4) = **70** splits. *(The first-pass handoff quoted 0.384 from only 15 matrices — an honest but under-powered estimate; 300 matrices settle it.)* |
| 9 | Marginal IC of a factor against **itself** as the book is ≈ 0 | ✅ PASS | `marginal_ic(mom_21, book={mom_21})` = **−0.00665** vs raw IC **0.03123**. Residual is numerically ~1e-14; its RankIC is sampling noise (measured sd of the IC mean over VAL_A = **0.00436**). Asserted `|mi| < 0.012` **and** `|mi| < raw/2`. |
| 10 | `check_sign(+1, -1)` is `False` | ✅ PASS | `check_sign(1,-1)=False`, `(-1,1)=False`, `(1,1)=True`, `(-1,-1)=True`, `(1,0)=False`. In `gate_b` a mismatch is a hard reject that **never flips the sign**, and it spends **0** peeks. |

### Spec body (steps 1–7), measured

| Item | Result | Measured value |
|---|---|---|
| E[max SR] term = `σ·((1−γ)Z⁻¹(1−1/N)+γZ⁻¹(1−1/(N·e)))` | ✅ PASS | `expected_max_sharpe(N, 1.0)` returns N=20→**1.901**, 100→**2.531**, 200→**2.766**, 500→**3.053**; my 20k-draw MC of the true order statistic gives **1.868 / 2.504 / 2.744 / 3.038**. Max discrepancy **0.033**, and the formula sits slightly *above* the order statistic at every N (conservative). `expected_max_sharpe(1,·)=0`, `(200, σ=0)=0`. |
| DSR uses skew + **non-excess** kurtosis | ✅ PASS | Same Sharpe, fat left tail (40 injected −5% days) → DSR strictly below the normal series' DSR. |
| Trial-SR variance floored at `1/T` *(finding E)* | ✅ PASS | 40 identical trial IRs, N=100, T=900 → E[max SR] **0.0844**. Pre-fix: sample variance 0 → E[max SR] **0.0** → deflation silently off. |
| Walk-forward: expanding train, stepped test, sequential OOS IC series + per-fold metrics | ✅ PASS | Planted signal, 2018-01-01→2021-06-30, `train_years=1, step_months=6`: **5 folds, 622 OOS days, mean OOS IC 0.029** (planted 0.04, asserted ±0.02). Noise → mean OOS IC **0.008** (asserted <0.01). `walk_forward` spanning 2022-07-01 raises `PermissionError`. |
| CSCV purge+embargo inside every split | ⚠️ PARTIAL | `cscv_pbo(purge_days=…)` drops the first `purge_days` rows of every block. Strategies are **not refit** in CSCV, so leakage is limited to label overlap at block seams; a light purge is applied, a full train/test embargo is not meaningful here. Disclosed, unchanged from the first pass. |
| Orthogonalisation = per-day cross-sectional regression, residual kept | ✅ PASS | signal = planted + 0.01·noise → raw IC 0.031, marginal IC after projecting planted out **< raw/2**. |
| Gate B order is load-bearing | ✅ PASS | `audit["gate_b_order"] == ["orthogonalize","novelty","statistics","holdout_peek"]`. A book-clone dies at the **free** novelty step with `holdout_peeks_used()==0`. Best-of-40 noise sharing a thesis → rejected at statistics. |
| Determinism | ✅ PASS | Two **separate interpreter processes**, different ledger files: byte-identical audit to 12 dp — `('accept', 0.03122657596, 0.999999999998, 7.064582902852, 0.0, 0.031998135683)`. `_pbo_from_signal` seeds its surrogates with `RANDOM_SEED`. |
| No network | ✅ PASS | `grep -rn "requests\|urllib\|http\|socket\|yfinance"` over `gates.py`, `ledger.py`, `test_p6_gates.py` → **no matches**. |
| Label cache bounded and id-safe *(finding C)* | ✅ PASS | 12 distinct panel objects → **4** cache entries (`LABEL_CACHE_MAXSIZE`). Each live entry pins its own panel (`id(labels_ref) == key`). Pre-fix: 12 entries, unbounded, no eviction. |

---

## 3. Verify it yourself

```bash
# 1. all Phase-6 tests (no network)
./.venv/Scripts/python.exe -m pytest tests/test_p6_gates.py -v        # expect 30 passed

# 2. the ledger has no row-removal SQL
grep -rin "delete\|drop table\|truncate" src/ledger.py                # expect ONE line: 69 (_FORBIDDEN_SQL)
./.venv/Scripts/python.exe -c "from src.ledger import assert_no_row_removal_sql; assert_no_row_removal_sql(); print('clean')"

# 3. rebuild the empty ledger DB
./.venv/Scripts/python.exe -m src.ledger                              # writes data/ledger.db

# 4. √(2 ln N) is a CEILING — the realised max sits ~0.5 below it
./.venv/Scripts/python.exe - <<'PY'
import numpy as np, math
from src.gates import expected_max_sharpe
rng = np.random.default_rng(12345)
for N in (5, 20, 200, 500):
    mc = rng.standard_normal((20000, N)).max(axis=1).mean()
    print(f"N={N:>3}  realised E[max]={mc:.3f}   sqrt(2lnN)={math.sqrt(2*math.log(N)):.3f}"
          f"   Bailey-LdP={expected_max_sharpe(N,1.0):.3f}")
PY

# 4b. the tail fact - how often pure noise clears "t > 3"
./.venv/Scripts/python.exe - <<'PYTAIL'
import numpy as np
rng = np.random.default_rng(777)
for N in (5, 20, 100, 200, 500):
    m = rng.standard_normal((200000, N)).max(axis=1)
    print(f"N={N:>3}: P(best t>3) = {100*np.mean(m>3):5.1f}%   mean max {m.mean():.3f}  sd {m.std(ddof=1):.3f}")
PYTAIL
#   expect 0.7 / 2.7 / 12.6 / 23.6 / 49.1 %

# 5. the headline fact, by hand
./.venv/Scripts/python.exe - <<'PY'
import numpy as np, pandas as pd
from src import contracts as C, backtester as bt, gates as G
f=C.make_fake_features(n_days=2700,n_symbols=60,seed=42); l=C.make_fake_labels(n_days=2700,n_symbols=60,seed=42)
bt.use_panel(f,l)
planted=f.pivot_table(index='date',columns='symbol',values='mom_21')
rng=np.random.default_rng(0); irs=[]; ser=[]
for i in range(200):
    ic=G.daily_rank_ic(pd.DataFrame(rng.standard_normal(planted.shape),index=planted.index,columns=planted.columns),'val_a',1)
    irs.append(ic.mean()/ic.std(ddof=1)); ser.append(ic)
t=np.array([ir*np.sqrt(len(s)) for ir,s in zip(irs,ser)]); b=int(np.argmax(np.abs(t)))
print("best-of-200 raw t-stat:", round(float(t[b]),3))          # 2.742  (ceiling sqrt(2 ln 200)=3.255)
print("DSR:", round(G.dsr_from_ic_series(ser[b]*np.sign(t[b]),200,irs)['dsr'],4))   # 0.4773 -> REJECT
ic=G.daily_rank_ic(planted,'val_a',1)
print("real DSR (N=5):", round(G.dsr_from_ic_series(ic,5,[ic.mean()/ic.std(ddof=1)]*5)['dsr'],4))  # ~0.99 -> PASS
PY

# 6. the run-wide deflation fix (finding B) — noise at t = -3.00 must be rejected
./.venv/Scripts/python.exe -m pytest tests/test_p6_gates.py -q \
    -k "global_ledger or residual_not_the_raw or effective_count_not_raw or sampling_floor or cache_is_bounded" -v

# 7. full repo regression
./.venv/Scripts/python.exe -m pytest -q                               # expect 188 passed (~4.5 min)
```

---

## 4. What I could NOT verify, and why

- **Real-panel Gate B behaviour.** All tests run on the synthetic fixture. The
  real panel (`data/panel/*.parquet`) reaches 2025-12-31, so a real-data `gate_b`
  call would spend a genuine HOLDOUT peek — deliberately not exercised (no test
  may burn a real peek, and the fixture reproduces the mechanics). The owner can
  run one real peek manually if desired.
- **PBO on a real crowded signal.** `_pbo_from_signal`'s surrogate construction
  (sign-flip + column permutation of the residual) is a *defensible* single-
  candidate CSCV input, but I could not validate it against a known-overfit real
  formula — there isn't one yet. The standalone `cscv_pbo(matrix)` is validated
  directly and at high power (criterion 8).
- **Effective-trial-count calibration.** "20 near-identical → materially below 20"
  is met (→ 1.0 standalone, 2.0 inside `gate_b` once the candidate's own distinct
  shape is added), but I have no ground truth for the *right* effective count of a
  real variant family; the structural-cluster / participation-ratio method is a
  modelling choice (§7).
- **Whether run-wide deflation is too harsh at scale.** Finding B's fix makes
  E[max SR] grow with the whole ledger. On a long run (hundreds of effective
  trials) that is a genuinely high bar — which is the point — but I have not
  measured it against a real multi-generation run, because no such run exists yet.
  **P10 should watch for it and report;** if real signals are dying at N_eff in the
  low hundreds, the lever is the variant cap (G19), not the deflator.

---

## 5. Failures and open issues

**Five defects found by the verification pass. All fixed, each with a regression
test whose assertions the pre-fix values below violate.** Note the direction: **three of the four
statistical defects (A, B, E) made the gate more permissive**; D made it harsher
than intended, and C was an engineering leak. A gate that errs in the *accepting*
direction is the one failure mode this phase exists to prevent, so that clustering
is the part worth reporting, not the count.

| # | Defect | Pre-fix | Post-fix |
|---|---|---|---|
| **A** | **The rationed HOLDOUT peek scored the raw signal, not the residual.** The whole phase computes on the residual precisely because the fitness object is *one composite thing*; step 4 then handed `backtest()` the raw signal. A **partial clone** — real but small marginal IC, most of its raw IC explained by the book — clears novelty and statistics, and was then confirmed on HOLDOUT by the very book it was measured against. The collapse check `abs(holdout_ic) < 0.3*abs(marginal_ic)` was also comparing a **raw** holdout IC with a **residual** VAL IC — mixed units, so it could never bite. | recorded holdout ic **0.03200** (raw) | **0.01957** (residual). Overstatement removed: **63%**. `audit["holdout_scored_on"]="residual"` makes it auditable. |
| **B** | **Deflation was scoped to the thesis only.** `PLAN_EXPLAINED` C8-UPDATE says "within-thesis, *not only* global"; the build read it as "only within-thesis". A brand-new `thesis_id` therefore arrived with N=1 → E[max SR]=0 → **no deflation whatsoever**, however much search preceded it. Since P10 promotes the best card *across* theses, that is the wrong population. | 40 noise trials across 40 theses, winner at raw **t = −3.000**, gated under a fresh thesis → N_eff **1**, E[max SR] **0.0**, DSR **1.000**, **ACCEPT** | N_eff **41**, E[max SR] **0.0728**, DSR **0.789**, **REJECT**. Within-thesis kept as a floor; both counts on the card. |
| **C** | **`_LABEL_WIDE_CACHE` was unbounded and keyed on `id(labels)`.** `backtester._load_panel()` returns a **fresh** frame on every disk read, so the key never repeated: one never-hit entry per `gate_b` call, never evicted. The cache held no reference to the panel either, so a freed frame's `id` could be recycled and return a stale pivot. | 12 panels → **12** entries; **12.5 MB** each on the real panel (pivot 2695×581) ⇒ ~1.25 GB over 100 candidates | Bounded LRU, `LABEL_CACHE_MAXSIZE=4`; each entry pins its panel so the id cannot be recycled. 12 panels → **4** entries. `clear_label_cache()` added. |
| **D** | **The effective trial count was computed and then discarded.** The DSR was handed `max(n_eff, raw_N)`; since `n_eff ≤ N` by construction that is *always* raw N, so step 2 of the spec — the whole "20 knob-variants are 2 bets, not 20" argument — never reached the deflator. | 20 knob-variants of one shape → DSR deflated by **20** | deflated by **2.0** (the effective count). |
| **E** | **`σ²_SR = 0` switched deflation off.** With identical or near-identical trial SRs (common early in a run, and whenever trials are recorded with a shared placeholder t-stat) the sample variance is 0 → E[max SR] = 0 → the DSR reduces to an undeflated one-sample test, exactly when a thin ledger makes deflation most necessary. | 40 identical trial IRs → E[max SR] **0.0** | floored at `1/T` → E[max SR] **0.0844** (N=100, T=900). |

**Remaining open items (not defects):**

1. **`gate_b` needs the evaluated `signal`.** The spec signature is
   `gate_b(card, book, ledger)`. This is a real deviation, and the reason is
   stronger than "a card has no values": P5's parser accepts only base OHLCV
   fields (`ParseError: unknown field: 'mom_21'` — its allowed set is
   `close, volume, high, low, open, vwap, returns, …`), the P3 feature panel
   contains **none** of them, and the prices they need live in a third file
   (`data/prices/ohlcv.parquet`) that Gate B is not handed. Evaluation is P10's
   job. Accepted as `signal=` or `card["_signal"]`. Recorded in
   `IMPLEMENTATION_PLAN.md` Phase 6 step 6.
2. **`gate_b` scores HOLDOUT through `backtester.backtest`, which reads the
   process-global panel** (`use_panel` override or disk), not the `panel=` arg
   passed to `gate_b`. Callers must `use_panel(...)` first when using a non-disk
   panel. Documented in the docstring.
3. **CSCV purge/embargo is light** (drops `purge_days` rows per block, no full
   embargo). Justified because CSCV does not refit, but noted.
4. **Run-wide deflation is untested at scale** — see §4, last bullet.

---

## 6. Anything that contradicts the spec

**1. √(2 ln N) is a loose upper bound, not the expected best t-stat.** The spec
says "the best one's t-stat **will be about** √(2 ln N) … N=200 → 3.26" and asks
the headline test to expect "≈ 3.3". Measured (20,000 Monte-Carlo draws per N):

| N | realised E[max] | √(2 ln N) | Bailey-LdP E[max] | bound − realised |
|---|---|---|---|---|
| 5 | 1.168 | 1.794 | 1.193 | +0.63 |
| 20 | 1.868 | 2.448 | 1.901 | +0.58 |
| 200 | **2.744** | 3.255 | 2.766 | **+0.51** |
| 500 | 3.038 | 3.526 | 3.053 | +0.49 |

Two consequences:

- The **deflator must stay Bailey-López de Prado `E[max SR]`**, which tracks the
  order statistic to ≤0.04. A √(2 ln N) deflator would be ~0.5 too harsh and would
  **kill real signals** — measured on the real 5-trial signal (t = 7.07):
  **DSR 0.9952 (pass)** under Bailey-LdP vs **DSR 0.6579 (reject)** under
  √(2 ln N).
- The headline test's t-stat band is **2.5–4.2**, not "≈3.3". The realised
  best-of-200 measures **2.742**; a band centred on 3.26 would fail on correct
  code.

**This does not weaken the phase — and the right number makes the case better than
√(2 ln N) did.** The load-bearing claim — *the Deflated Sharpe must reject the best
of 200 pure-noise signals* — holds decisively (**DSR 0.477**). And the justification
for every gate here is sharper stated as a **tail probability** than as a mean.
Measured, 200,000 Monte-Carlo searches per row:

| Things tried (N) | realised E[max t] | sd | **P(best t > 3.0) on pure noise** |
|---|---|---|---|
| 5 | 1.163 | 0.668 | 0.7% |
| **20** *(the G19 variant cap)* | 1.869 | 0.526 | **2.7%** |
| 100 | 2.507 | 0.430 | 12.6% |
| 200 | 2.746 | 0.401 | **23.6%** |
| 500 | 3.037 | 0.371 | **49.1%** |

At 500 variants the "t > 3" bar is a **coin flip against pure noise**; at the
20-variant cap it is 2.7%. This is now in `INITIAL_PLAN.md`, `FLOW_EXPLAINED.md`
and `PLAN_EXPLAINED.md` G19-UPDATE as slide material. Wording elsewhere: say
"**of order** √(2 ln N)", quote 3.26 as the ceiling and **2.74** as the realised
value.

**2. The illustrative `AlphaCard` in §0.5 showed `deflated_sharpe: 0.9` on an
`accept`ed card**, below the `DSR_MIN = 0.95` the phase enforces. That example is
the only numeric hint the spec gives about the bar. I kept 0.95 (Bailey-LdP's own
convention) and corrected the example to 0.97 so the contract is self-consistent
— **flagging it explicitly in case the owner intended 0.90 as the bar.** Changing
it is a one-line edit to `src/gates.py`.

Everything else matches the spec.

---

## 7. Decisions I made that the spec left open

1. **The DSR is computed on the residual's daily RankIC series**, not the
   long-short portfolio's daily P&L. `backtester.backtest` returns only the
   summary `Metrics` dict (`src/backtester.py:301`) — there is no daily P&L
   series to take a Sharpe of. The IC series is also the right object on the
   merits: its Sharpe **is** the information ratio and its t-stat **is** the
   spec's `t > 3` bar, so units stay consistent with `trial_irs()`.
2. **Trial-SR sample = `t_stat_i / √n_days_i`** over the ledger's
   `counts_as_trial=1` rows (`Ledger.trial_irs`), read **globally** (finding B),
   with variance floored at `1/T` (finding E). `Ledger.trial_sharpes()` exists per
   the spec's API but Gate B does not use it — annualised P&L Sharpes are the
   wrong units for a per-day IR.
3. **`MIN_MARGINAL_IC = 0.01`.** Measured sampling-noise sd of a daily-IC mean
   over VAL_A (T=913) is **0.00436**, so 0.01 is **2.3σ** — above float-residual
   noise, below genuine marginal alpha (0.02–0.03).
4. **`DSR_MIN = 0.95`, `PBO_MAX = 0.50`, `MIN_DSR_SAMPLE = 60`.** Bailey-LdP use
   DSR > 0.95; PBO > 0.5 is worse than a coin (measured null **0.486 ± 0.013**);
   below ~60 scored days the skew/kurtosis terms are unreliable. See §6 item 2 for
   the DSR_MIN tension with the spec's example card.
5. **Deflation scope = run-wide effective count, with within-thesis as a floor**
   (finding B). Both are reported on the card.
6. **Effective trial count = structural clusters refined by return decorrelation.**
   Group trials whose canonical-AST *shape* matches (standalone numeric literals →
   `#`); a cluster of `m` counts as `1 + (m−1)·(1 − mean|corr|)` bets when a return
   matrix is available, else 1. `_corr_effective_n` (eigenvalue participation
   ratio) is the pure-correlation path.
7. **`_structural_key` normalises only *standalone* numeric literals** — a digit
   inside an identifier (`mom_21`, `beta_63`) is left alone, so `mom_21` and
   `mom_126` do not collapse.
8. **The peek scores the residual** (finding A), recorded as
   `audit["holdout_scored_on"]`.
9. **`gate_b` records exactly one `counts_as_trial=1` row per call** (in
   `_finish`), carrying the residual's realised `rank_ic` / `t_stat`. Red-team,
   cost-sweep and lag runs are Phase 9's to record with `counts_as_trial=0`.
10. **Single-candidate PBO** (`_pbo_from_signal`): CSCV return matrix = the
    residual's daily-IC series + 12 sign-flip/permutation surrogates of the same
    signal, seeded with `RANDOM_SEED`. A genuine signal beats its own scrambles
    both in- and out-of-sample → low PBO; noise does not → ≈0.5.
11. **`request_holdout_peek` spends the budget at reservation time**, not at
    result time — an abandoned token still counts. The conservative reading of
    "rationed", and it makes the budget check a simple row count.
12. **Orthogonalisation leaves a symbol's raw signal value untouched on days where
    a book factor is missing for it** (rather than dropping the symbol or imputing
    the factor). We never fabricate a book value.
13. **`walk_forward` does not refit** (the signal is fixed); each fold contributes
    the daily RankIC of its test window, with the first `purge_days + embargo_days`
    test days dropped so no test label window reaches back across the expanding
    train boundary.
14. **`LABEL_CACHE_MAXSIZE = 4`** (finding C) — enough to hold a working set of
    panel/horizon combinations, small enough that the worst case is ~50 MB on the
    real panel.
15. **`data/ledger.db` stays git-ignored** (`.gitignore:21`, a Phase-0 decision I
    kept). Worth stating explicitly because it defends the same property the
    no-`DELETE` rule does: a version-controlled ledger could be rolled back with
    `git checkout`, and rolling back the trial count **is** un-counting trials.
    The file is regenerable empty (`python -m src.ledger`) but its *contents* are
    append-only run state, not source.

---

## 8. Documentation updated (so P13 can build slides from the docs, not the code)

All five findings and the √(2 ln N) correction are written into the design docs,
in each doc's own established style:

| Doc | Change |
|---|---|
| `IMPLEMENTATION_PLAN.md` | Phase 6 standalone context: **P6-UPDATE** on the √(2 ln N) ceiling (with the MC table and the over-rejection measurement) and on the peek scoring the residual. Step 2: effective count must be *used*, and scope is run-wide. Step 3: `σ²_SR` floor. Step 6: the `signal=` argument and why. Acceptance: three criteria added, headline band corrected to 2.5–4.2, and a **Thresholds table** pinning `MIN_MARGINAL_IC / DSR_MIN / PBO_MAX / MIN_DSR_SAMPLE` with their bases. §0.5 `AlphaCard`: three `audit` fields added, illustrative DSR corrected to 0.97. |
| `PLAN_EXPLAINED.md` | **G19-UPDATE** (√(2 ln N) is a ceiling; deflate by Bailey-LdP; slide wording). **G21-UPDATE** (the residual rule binds step 4 too). **C8-UPDATE-2** (deflation is run-wide; `max(n_eff, N)` discarded the cluster adjustment). New **G24** entry — *the honesty machinery gets audited the way a signal does*: 25 green tests and 8/8 criteria still hid five defects, four of them pushing towards acceptance, because the criteria tested statistics in isolation while the defects lived in the wiring. |
| `INITIAL_PLAN.md` | The "√(2 ln N)" slide table now has **both** columns (ceiling and realised max) plus the over-rejection note. Gate B graph node updated: peek is on the residual, deflation uses the run-wide effective count. S7 stage row updated. |
| `FLOW_EXPLAINED.md` | Plain-English versions: *"opening a new thesis must not reset the counter"* with the t = −3.00 example; *"and so is step 4"* on the peek judging the leftover (0.0320 vs 0.0196); worked-example numbers made consistent with the enforced bar. |
| `PHASE_PROMPTS.md` | Superseded-marker count updated 24 → 27, naming the three new callouts. |

**Four slide-ready facts this phase produced:**
0. **P(best-of-N pure-noise t-stat > 3.0)**: 2.7% at N=20 · 23.6% at N=200 · **49.1% at N=500**. At 500 tries the "t > 3" bar is a coin flip against noise. *The result never tells you which case you are in — only the trial count does.*
1. Best of 200 pure-noise signals: raw **t = 2.74** (ceiling 3.26) → Deflated Sharpe **0.477** → rejected. A real signal found in 5 trials: **t = 7.07** → DSR **0.9952** → passed. *Same gate.*
2. Noise selected across 40 theses arrives at **t = −3.00** — it clears "t > 3". Charged per-thesis: **accepted**. Charged run-wide: **rejected** (DSR 0.79). *Opening a new thesis must not reset the counter.*
3. Peeking at the raw signal instead of the leftover overstates the surviving edge by **63%** (0.0320 vs 0.0196) — and burns one of only 12 lifetime peeks to do it.
