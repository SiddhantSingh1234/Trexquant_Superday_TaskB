# Phase 12 — System evaluation and ablation

**Grades the factory, not the signal.** Everything below is produced by
`src/evaluation.py`; reproduce with `python scripts/p12_run_evaluation.py`
(deterministic, `RANDOM_SEED=42`, ~5 minutes).

---

## 1. The question this phase answers

Trexquant's prompt asks how the system would be *evaluated* and *improved
over iterations* — a different question from "is this one signal good."
Two things are measured:

1. **Gate value** — a seeded pool of 40 synthetic factors with **known ground
   truth** (10 genuinely predictive, 10 pure noise, 10 overfit-to-a-subsample,
   10 look-ahead-leaky), scored with Gate B (novelty, statistics) and Gate C
   (red-team) each on and off. This needs **zero LLM calls** — Gate A (the
   Economics Reviewer) is out of scope on purpose, since PRE_BUILD_TASKS.md
   T3's measured ~20-theses/day Groq ceiling means an LLM-hungry ablation
   could never be re-run to check this report.
2. **Real vs. fake learning** — does the system's error *volume* actually
   fall across generations, or only its error *type* (the published critique
   of factor-mining agents)?

---

## 2. The seeded pool

Built entirely by `src/evaluation.py` from a hand-rolled synthetic panel (not
`src/contracts.py`'s fixtures — see §7.1 for why), independent of every other
phase's real data:

* 1,750 business days (2015-01-01 → 2021-09-15), 50 symbols, an **AR(1)**
  latent (`rho=0.92`) shared by the labels and the "genuine" factors.
* Scored on `val_a` (2018-01-01 → 2021-06-30), horizon = 1 day, 913 scored
  days per member after purge/embargo.

| Category | n | Construction | Ground truth |
|---|---:|---|---|
| **genuine** | 10 | `scale·latent(t) + small_noise`, scale ∈ U(0.3,1.5), noise ∈ U(0.05,0.35) | Real, stable edge over the whole period — nothing fitted to any subsample |
| **noise** | 10 | i.i.d. standard normal, unrelated to anything | No edge |
| **overfit** | 10 | best-of-100 pure-noise draws, picked by brute-force search to **maximize mean RankIC on val_a itself** — the exact window it is later scored on. Only the winner is ever recorded (1 ledger trial), so the ledger under-counts the true search breadth by 100×. | Spurious — a hidden multiple-comparisons problem the trial count cannot see |
| **leaky** | 10 | `±fwd_ret_1_demeaned(t) + small_noise` — the signal **is** (a sign-flipped copy of) the label it will be scored against | Textbook look-ahead: information not available at signal time |

Each member gets a unique `canonical_ast` id (its pool name), so
`effective_trial_count` never structurally collapses distinct members into
one cluster — every one of the 40 counts as its own trial for multiplicity
deflation.

---

## 3. Per-member results (full scale, n=40)

| Category | novelty_pass | stats_pass | redteam_pass | typical `t_stat` | typical `dsr` | typical `pbo` |
|---|---:|---:|---:|---:|---:|---:|
| genuine (10) | 10/10 | 10/10 | **10/10** | 11.5 – 12.8 | 1.000 | 0.00 |
| noise (10) | 0/10 | 0/10 | 0/10 | 0.18 – 2.01 | 0.02 – 0.69 | 0.16 – 0.84 |
| overfit (10) | 9/10 | **2/10** | **0/10** | 1.69 – 3.25 | 0.31 – 0.99 | 0.04 – 0.44 |
| leaky (10) | 10/10 | **10/10** | **0/10** | 35.9 – 233.7 | 1.000 | 0.00 – 0.43 |

The full 40-row table (`marginal_ic, dsr, t_stat, pbo, n_trials_effective,
novelty_pass, stats_pass, redteam_pass, redteam_failed_tests` per member) is
reproduced by `scripts/p12_run_evaluation.py`.

**What actually caught what**, reading the `redteam_failed_tests` column:

* Every **leaky** member is killed by exactly one decisive red-team test:
  `extra_lag`. Gate B's statistics do **not** see the leak — DSR=1.0, t up
  to 234, because Gate B never re-times the signal. Only Gate C, by shifting
  the signal one extra day and re-scoring, exposes that the "edge" is built
  from information the signal could not have had.
* **overfit** members split: 2 of 10 (`overfit_0`, `overfit_6`) clear the
  `t > 3` bar on the raw numbers Gate B sees (their 100-candidate search history
  is invisible to the ledger) — but all 10 are killed by Gate C, mostly via
  `cost_sweep` and `sign_stability`/`subsample_year` inconsistency across
  years, which a genuinely stable factor should not show.
* **noise** is caught for free at the novelty step — |marginal_ic| below
  `MIN_MARGINAL_IC=0.01` — before any statistics are even worth computing.
* **genuine** clears all three gates cleanly (false-kill rate 0.0 on every
  gate at this SNR) — but see §7.2: at a lower signal-to-noise ratio,
  `cost_sweep` legitimately kills weak, high-turnover "real" signals too.

---

## 4. The ablation

### 4.1 Per-gate catch rate / false-kill rate

| Gate | Catch rate (junk rejected, n=30) | False-kill rate (genuine rejected, n=10) |
|---|---:|---:|
| **novelty** | 0.367 (11/30) | 0.000 |
| **stats** (DSR / t / PBO) | 0.633 (19/30) | 0.000 |
| **redteam** (Gate C, decisive tests) | **1.000 (30/30)** | 0.000 |

Plot: `reports/p12_plots/gate_ablation.png`.

### 4.2 Headline FDR, gate on vs. off

Accept = passes every enabled gate. FDR = accepted junk ÷ accepted total.

| Variant | FDR | n accepted (of 40) |
|---|---:|---:|
| **all gates on** | **0.000** | 10 (exactly the 10 genuine) |
| novelty off | 0.000 | 10 |
| stats off | 0.000 | 10 |
| **redteam (Gate C) off** | **0.524** | 21 |

Disabling Gate C is the one change that visibly wrecks the FDR — from a
clean 0% to 52%, because every leaky member (10/10) and 2 of 10 overfit
members flood straight through once the causality/stability checks are gone.

### 4.3 Interpretation — "isn't this over-engineered?"

Not uniformly. The three gates are **not equally load-bearing against this
particular threat mix**:

* **Novelty** is cheap and catches pure noise outright (0.367 catch rate,
  all of it noise) — worth having as a free first filter, but it does
  nothing against overfit or leaky signals, which both have a real (if
  spurious or fabricated) marginal correlation.
* **Statistics** (DSR/t/PBO) catches most of the naive noise-mining
  (`overfit`, 8/10 caught) but is **structurally blind to look-ahead** — it
  has no way to know a signal used information from the future, since it
  never re-times anything. All 10 leaky members clear it with room to spare.
* **Red-team (Gate C)** is the only gate that catches 100% of both attack
  types, via a mechanism (`extra_lag`, `cost_sweep`, `sign_stability`) that
  neither novelty nor the DSR/PBO machinery implements.

One honest wrinkle: in **this specific pool**, disabling novelty or stats
*alone* did not move the FDR, because Gate C alone happened to already cover
everything either of them would otherwise have caught. That is a property of
*this* pool's attack mix, not a general claim that novelty/stats are
redundant — Gate B's own docstring motivation (deflating for how many things
were tried, and screening for genuine marginal information against a growing
factor *book*) is not something this single-factor, no-book pool exercises.
A pool that included near-duplicate variants of an existing book factor, or
many more marginally-significant overfit draws just above `t=3`, would show
Gate B's stats and novelty steps doing more of the catching on their own.
**We did not adjust the pool or the thresholds to manufacture a cleaner
story once we saw this** — see §6.

---

## 5. Real vs. fake learning

### 5.1 What the real system's ledger shows

`data/ledger.db` (read-only inspection, `real_ledger_snapshot()`):

* 76 recorded trials, across 9 distinct theses, 4 of 12 HOLDOUT peeks used.
* **Every recorded `thesis_id` carries the `_g0` tag.** There is no `_g1` or
  later generation anywhere in the real ledger.

This is the honest finding, stated plainly: **we cannot measure whether the
real system's errors mature across generations, because no real run has ever
produced a second generation.** PRE_BUILD_TASKS.md T3's measured ~20
theses/day Groq ceiling is the direct cause — every demo run (P8–P11) spent
its budget on generation-0 theses. This is not evidence *against* the
"volume stays flat" critique either; it is simply unmeasured. Reporting
"inconclusive, and here is exactly why" is more honest than presenting a
single-generation ledger as either confirming or refuting the critique.

### 5.2 A synthetic proxy (not evidence of learning)

To still produce the requested plot, the 40-member pool — in its fixed
round-robin submission order (genuine, noise, overfit, leaky, repeat) — is
sliced into 4 equal "pseudo-generations" of 10 members each:

| Generation | n | Total rejections | novelty pass rate | stats pass rate | redteam pass rate |
|---:|---:|---:|---:|---:|---:|
| 0 | 10 | 7 | 0.70 | 0.60 | 0.30 |
| 1 | 10 | 8 | 0.80 | 0.50 | 0.20 |
| 2 | 10 | 7 | 0.70 | 0.50 | 0.30 |
| 3 | 10 | 8 | 0.70 | 0.50 | 0.20 |

Plot: `reports/p12_plots/fake_learning.png`.

**Interpretation, stated as plainly as §5.1:** rejection *volume* is flat
(7–8 of 10 every generation) and every per-gate pass rate is flat within
noise. That is superficially what the "fake learning" critique predicts —
but it is not evidence of it, because **this experiment cannot show learning
by construction**: a "generation" here is an arbitrary contiguous slice of
one fixed, non-adaptive pool, not the output of an agent that revises its
hypotheses using what got rejected last round. A genuinely improving agent
and a flat random partition of a fixed pool look identical on this plot. The
real test — does rejection volume fall as the actual LLM loop iterates on
its own lesson store (`data/lessons.db`) across true generations — is
exactly the test §5.1 says the project has not yet been able to run.

---

## 6. What we did *not* do

Per the Phase 12 "Do NOT": the gates were **not** tuned to make this ablation
look good. `MIN_MARGINAL_IC`, `DSR_MIN`, `T_STAT_BAR`, `PBO_MAX` are
imported unchanged from `src/gates.py`; nothing in `src/evaluation.py`
touches them. The pool's construction parameters (noise scale, AR(1) `rho`,
number of overfit search candidates) were adjusted twice during
development — documented in `reports/p12_handoff.md` §7 — but always to fix
a **methodological confound** (see §7.2), never after seeing an ablation
result we wanted to look different, and every adjustment is disclosed.

---

## 7. Small-sample and construction caveats (read before citing this report)

1. **This is one seed, one pool, 40 members.** Every number above (catch
   rates, FDR, generation pass rates) is a point estimate from one
   deterministic run. With 10 members per category, a single flipped verdict
   moves a category's catch/false-kill rate by 10 percentage points. These
   numbers are **illustrative of mechanism, not a statistically powered
   estimate of real-world catch rates.**
2. Genuine factors' construction was tuned once, after the first full run
   killed 6 of 10 genuine members on `cost_sweep`: their noise-to-signal
   ratio produced enough daily rank churn (turnover) to be legitimately
   unprofitable at 15bps, even though their true correlation was real. That
   is an honest result about *that* construction, not a bug in Gate C — but
   it conflated "genuine" with "genuine and low-turnover," which is a
   narrower ground truth than intended, so the noise scale was reduced
   (§ handoff for the exact before/after).
3. The pool has **no factor book** — every member is judged standalone, so
   novelty here only tests "is the raw signal non-trivial," never "is this
   a near-duplicate of something already in the book." That is the one part
   of Gate B's stated purpose (marginal-IC-vs-book, multiple-comparisons
   deflation across a *growing* real search) this pool cannot exercise.
4. `trial_irs` (the empirical trial-SR sample DSR would normally deflate by)
   is deliberately **not** fed from the shared ablation ledger into each
   member's DSR — the ledger's prior trials mix pathological categories
   (leaky members have t-stats in the hundreds) with legitimate ones in one
   sequence, and an early pathological trial would poison the estimated
   variance for every later member regardless of category. `n_trials`-based
   (count) deflation still grows across the whole pool; only the empirical
   variance term falls back to its documented `1/T` floor. A real run does
   not have this confound as sharply, since its trial history is not
   deliberately salted with lookahead artifacts — but the underlying risk
   (one bad trial distorting deflation for everything after it) is real and
   worth flagging as a genuine, if secondary, finding of this exercise.

---

## 8. Real-system snapshot (yield / honesty, not the ablation)

For context, not part of the ablation — read from the **real** artifacts,
untouched by this phase:

| | Value | Source |
|---|---|---|
| Trial-ledger trials | 76 | `data/ledger.db` |
| Distinct theses | 9 (all generation 0) | `data/ledger.db` |
| HOLDOUT peeks used | 4 of 12 budget | `data/ledger.db` |
| Alpha Cards on disk | 4 (1 accept, 3 reject) | `artifacts/cards/*.json` |
| Accepted card's Deflated Sharpe | 0.976 | `artifacts/cards/good_p11.json` |
| Pre-registered sign agreement | 1/2 = 0.5 | only 2 of 4 cards reached a sign check (the other 2 were rejected earlier — one before Gate B ran at all) |

**n=4 cards is not enough to estimate a real FDR, tokens-per-accepted-alpha,
or a DSR distribution** — those numbers would be noise dressed as evidence,
so they are not reported as headline metrics. This snapshot exists to show
what the real system has actually produced, not to substitute for the
ablation's statistical claims.

---

## 9. Acceptance criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Seeded pool has documented ground truth per factor | ✅ §2 — 4 categories × 10, construction documented |
| 2 | Every gate has a catch rate and a false-kill rate | ✅ §4.1 |
| 3 | FDR on/off exists for at least Gate B-novelty, Gate B-stats, Gate C | ✅ §4.2 — all three |
| 4 | Fake-learning plot exists and is interpreted in one honest paragraph | ✅ §5.2 |
| 5 | Report states the small-sample limitation explicitly | ✅ §7 |

See `reports/p12_handoff.md` for measured values, verification commands, and
every judgement call.
