# PHASE PROMPTS — copy-paste briefs for executing agents

> **How to use.** Give **PROMPT 0** to any agent as its first message (it orients them). Then give the
> single phase prompt for the phase you want built. Each phase prompt is self-contained: the agent does
> **not** need to know how any other phase was implemented, only the file contracts in Section 0 of
> `IMPLEMENTATION_PLAN.md`.
>
> **Parallel execution:** P5, P7, P8 and P9 depend only on P0. Four agents can run those simultaneously
> in separate sessions with no coordination.
>
> ⚠️ **Data-track order is P0 → P2 → P1 → P3** — P2 runs before P1. See the P1 prompt for why.

---

# PROMPT 0 — orientation (give this first, to every agent)

```
You are implementing one phase of a quantitative research system that uses AI agents to discover
stock-market alpha signals. The design is frozen; your job is to build one phase of it.

## Files, and what each is for

| File | Role | Read it? |
|---|---|---|
| `IMPLEMENTATION_PLAN.md` | **The build spec. Single source of truth for execution.** | **MANDATORY** — Section 0 (SHARED CONTRACTS) in full, then ONLY your assigned phase |
| `PRE_BUILD_TASKS.md` | Empirical findings from live investigation: verified URLs, exact dates, measured rate limits, validated derivations | **MANDATORY if your phase touches data or LLM APIs** (P1, P2, P3, P5, P8). Useful otherwise |
| `FLOW_EXPLAINED.md` | Plain-English walkthrough of the whole system, every term defined | Optional — read if you want to understand *why* your phase exists |
| `INITIAL_PLAN.md` | Architecture spec: nine stages, gates, evaluation metrics, references | Reference — needed for P10, P12, P13 |
| `PLAN_EXPLAINED.md` | Decision record (every doubt -> decision -> why) + a full dictionary of terms | Reference only — see the warning below |
| `Superday_2026_Prompt_QR_India.pdf` | The original task this all serves (only task B) | Optional context |

## ⚠️ PRECEDENCE — this matters, the docs genuinely disagree in places

1. **`IMPLEMENTATION_PLAN.md` wins** on anything about what to build.
2. **`PRE_BUILD_TASKS.md` wins over the design docs on empirical facts** — dates, URLs, limits,
   what does and does not exist. Those were verified by probing live endpoints; the design docs were
   written before that investigation.
3. The design docs (`INITIAL_PLAN`, `PLAN_EXPLAINED`, `FLOW_EXPLAINED`) are **background and
   rationale**, not instructions.

## ⚠️ WARNING about `PLAN_EXPLAINED.md`

It deliberately **preserves superseded text** alongside "UPDATE" / "SUPERSEDED" callouts, so the
reasoning trail survives. There are 24 such markers. If you read a passage there without reading its
callout, you may implement a decision we reversed — the old Gate B ordering (statistics before novelty),
a 5-year Train window, or MCTS as the primary formula search are all still visible in the original text.

**Use it for two things only: looking up a term you do not know, and understanding why a decision was
made. Never take a build instruction from it.**

## Rules that apply to every phase

- Your phase spec is a contract. Build exactly what its Inputs/Outputs sections specify, with the exact
  file paths and column names. Downstream phases depend on those names.
- If an input file does not exist yet, use the synthetic fixture generators in `src/contracts.py`
  (Phase 0 builds them). Do not block waiting for another phase.
- Respect the "Do NOT" section. It stops you wandering into another phase's territory or reintroducing
  something we deliberately excluded. `IMPLEMENTATION_PLAN.md` has an "EXPLICITLY OUT OF SCOPE" section
  at the end listing what was considered and rejected, with reasons — do not helpfully re-add any of it.
- Write the tests listed under Acceptance. They must pass with plain `pytest` and no network.
- Determinism: seed numpy and random. Same input must produce the same output.
- Fail loudly. Assert contracts on read and write. Never silently fill NaN.
- Log every filter, drop, or fill decision to your phase's report in `reports/`.
- HOLDOUT dates (2022-07-01 onward) are sealed. Only Phase 6's rationed-peek API may read them.

Environment: Python 3.11+, Windows, PowerShell. Allowed dependencies are listed in Section 0.2 — do not
add others. In particular: no vector database, no Docker, no paid API, no paid data source.

## ⛔ EVERY PHASE IS HUMAN-VERIFIED BEFORE THE NEXT BEGINS

**Your phase is not done when the code runs. It is done when the project owner has verified it and said
so.** Read `IMPLEMENTATION_PLAN.md` section **0.7 (Phase completion protocol)** — it is mandatory.

This changes what you must produce: **evidence, not assurances.** "The tests pass" is not a handoff;
a number the owner can check is.

You must finish by writing **`reports/p<N>_handoff.md`** using the template in section 0.7. It covers:
what you built · every acceptance criterion with its **measured value** · exact commands the owner can
run to verify independently · what you could NOT verify and why · failures and open issues · anything
contradicting the spec · **every judgement call you made that the spec left open**.

Hard rules:
- **Never write PASS without the number that proves it.**
- **Report failures.** 3 of 12 criteria failing, honestly reported, is far more useful than a claimed
  12/12 that collapses in the next phase. Nothing here is graded on a clean sheet.
- **Never fabricate or infer a result.** If it could not be tested, say so.
- **Do not start the next phase.** Stop and wait for sign-off.
- **Expect rework.** Verification may send your phase back. That is the protocol working.
- If you find the spec is wrong, say so plainly — several specs already changed because an
  investigation contradicted them.

Why this exists: this system is built to catch self-deception in *signals*; the same discipline applies
to the *build*. The data phases especially can produce output that looks perfectly reasonable while
being quietly wrong — **a survivorship-biased panel does not throw an exception, it just makes every
later result look too good.**
```

---

# PHASE PROMPTS

## P0 — Scaffolding *(do this first; it blocks everything)*

```
Execute PHASE 0 from IMPLEMENTATION_PLAN.md.

Build the repo skeleton, src/config.py, src/contracts.py, and tests/test_p0_contracts.py.

The single most important deliverable is the FIXTURE GENERATORS in contracts.py (make_fake_ohlcv,
make_fake_features, make_fake_labels, make_fake_membership, make_fake_symbols). Every other phase is
built and tested against these rather than waiting for real data, so they must be realistic:
- make_fake_ohlcv: geometric random walk, ~25% annualized vol, occasional gaps, and a few symbols that
  stop trading partway through (so downstream survivorship logic has something to bite on).
- make_fake_labels: MUST contain one feature with a genuine planted IC of ~0.04. Later phases use it to
  prove their machinery can detect a real signal, so record the planted value in a docstring.

config.py constants: MAX_VARIANTS_PER_THESIS=20, HOLDOUT_PEEK_BUDGET=12, T_STAT_BAR=3.0,
COST_BPS_DEFAULT=15, EMBARGO_DAYS=5, RANDOM_SEED=42, plus the four split date ranges from Section 0.4
and a split_mask() helper and an assert_not_holdout() tripwire.

Do NOT implement any business logic — no features, no backtester, no agents.
Finish by writing reports/p0_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P1 — Universe construction (liquidity-defined) — **run AFTER P2**

```
Execute PHASE 1 from IMPLEMENTATION_PLAN.md.

IMPORTANT: P1 now runs AFTER P2, and no longer reads any constituent CSV. The order was flipped after
verification proved the supplied index file unusable — 80 of today's 200 NIFTY 200 constituents
(RELIANCE, TCS, SBIN, MARUTI, TATASTEEL, ONGC...) never appear in it, all with zero inclusion/exclusion
events. That is the signature of a change-log replayed onto an incomplete base seed. Read P1's
"Standalone context" for the full finding; do not try to repair or replay that file.

Build the universe from P2's bhavcopy data instead. THE RULE, applied on the last trading day of each
month using only data available that day:
  1. every SERIES == EQ stock in that day's bhavcopy
  2. require >= 252 trading days of prior history
  3. rank by median daily turnover over the trailing 63 days
  4. top 200 = the universe for the following month

Trailing windows only. Never centred, never full-sample. That is the entire survivorship defence: the
selection rule cannot see the future, and the source is a per-day snapshot of whatever actually traded,
so dead names are never excluded rather than being specially rescued. A stock leaves when it stops
appearing in the files — the absence IS the delisting.

Three acceptance tests decide whether this worked:
- TEST A (canaries): DHFL, RCOM, JPASSOCIAT, YESBANK, SUZLON, IDEA present while trading, absent after.
- TEST B (flat coverage): universe size per day must be FLAT at ~200 across 2015-2025. An upward slope
  means survivorship bias is still present — HARD STOP, do not proceed to P3.
- TEST C (no look-ahead): recompute using only data to 2020-01-01; every prior month's membership must
  be bit-identical to the full run.

The supplied CSV may be read ONLY for the step-6 overlap diagnostic in the report. Never to select
members. Do not hand-add "obviously large" names — the rule decides, or the universe is not
reproducible.

Use this naming everywhere, including any text that reaches the slides: "the 200 most liquid Indian
equities, reconstructed point-in-time from NSE daily bhavcopy." NOT "NIFTY 200."

Finish by writing reports/p1_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P2 — Price data ⭐ **run this first, before P1**

```
Execute PHASE 2 from IMPLEMENTATION_PLAN.md. NOTE: P2 runs BEFORE P1 — it needs no symbol list, and P1's
universe is derived from P2's output. Read its "Standalone context" section carefully — it
contains a boxed set of VERIFIED endpoints (probed live 2026-09-02) and the construction principle.


Also read: PRE_BUILD_TASKS.md section T1 IN FULL. It is the empirical record behind this phase —
exact probe dates and their HTTP responses, the measured latencies and file sizes, the VWAP
validation table, and the corporate-actions API shape. If an endpoint misbehaves, that section tells
you what was known to work and when.

The one idea that matters: do NOT fetch a symbol list. Download WHOLE TRADING DAYS from NSE. Delisted
companies then arrive automatically because they were trading that day. That structural choice is what
eliminates survivorship bias; everything else is bookkeeping.

Sources (all verified working):
- 2014-01-01 to 2019-09-27: legacy zip .../content/historical/EQUITIES/<YYYY>/<MON>/cm<DDMONYYYY>bhav.csv.zip
- 2019-09-30 onward: .../products/content/sec_bhavdata_full_<DDMMYYYY>.csv  (delivery data starts here)
- Corporate actions: .../api/corporates-corporateActions  (needs a session cookie + Referer)
Send a browser User-Agent. Cache every file to data/raw/nse/ and skip if present — make it resumable.
Measured: ~3,130 requests, ~78 min sequential or ~20 min with 4 workers, ~450 MB.

Four traps the spec details and you must handle:
- Filter SERIES == 'EQ' (bhavcopy also carries debt and ETFs; not filtering silently double-counts).
- Key internally by ISIN, present by SYMBOL — ISIN is stable across renames.
- bhavcopy is UNADJUSTED. Build your own split/bonus adjustment from the corporate-actions API. Do not
  attempt demergers; flag and disclose them.
- Derive vwap (TOTTRDVAL/TOTTRDQTY, or AVG_PRICE after 2019-09) and assert low <= vwap <= high on every
  row. Derive size_proxy from TRAILING turnover — never use current shares outstanding, that is a
  look-ahead.

Finish with the two tests that prove it worked: the canary test, and the flat-coverage plot. If panel
size per day slopes upward across 2015-2025, survivorship bias is still present — that is a HARD STOP,
do not proceed.
Finish by writing reports/p2_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P3 — Feature panel, labels, splits

```
Execute PHASE 3 from IMPLEMENTATION_PLAN.md.

Also read: PRE_BUILD_TASKS.md T2 (the sector-mapping method and the 22 official NSE industry names)
and T1 (why delivery_pct starts 2019-09-30).

Build data/panel/features.parquet, labels.parquet, splits.json, and reports/p3_panel_report.md.

Timing contract, exactly: features use data available before the trade -> trade at t+1 open -> return
earned t+1 open to t+2 open. The spec has a per-field availability table; obey it rather than any single
blanket rule.

Sector mapping is 78% automated — download
https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv (752 names, has both
Industry and ISIN), join on ISIN, then hand-classify the ~65 delisted names it cannot contain. Use
NSE's 22 official industry names verbatim.

delivery_pct only exists from 2019-09-30. Leave it NaN before that and state the first available date
in the report. Do not fabricate or back-fill it.

The most important part of this phase is step 7, the look-ahead self-test:
- Shift the entire feature panel forward one day and confirm a known factor's IC CHANGES. If it doesn't,
  the pipeline is time-symmetric somewhere and is leaking.
- Compute the IC of a deliberately leaky feature (fwd_ret_1 predicting itself) and confirm it is ~1.0.
  That proves the measurement machinery can detect leakage when present, which is what makes the
  negative result on real features meaningful.

Do not winsorize extreme returns — flag moves >50% for review. Indian mid-caps genuinely move like that
and clipping them would distort max_ret_21, which exists to capture exactly that.
Finish by writing reports/p3_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P4 — Backtester engine

```
Execute PHASE 4 from IMPLEMENTATION_PLAN.md.

Build src/backtester.py with the exact signature given in the spec. This is ONE engine with switches,
called from eight places downstream — build it parameterized, not as several functions.

If data/panel/ doesn't exist, use contracts.make_fake_* . The fake labels contain a feature with a
planted IC of ~0.04; use it to prove the engine detects a real signal.

Non-negotiables:
- Purge + embargo implemented as a reusable function (Phase 6's CSCV will call it too).
- split="holdout" must REQUIRE an explicit i_have_a_peek_token=True and raise otherwise. This is a
  tripwire; Phase 6 owns token issuance.
- Metrics dict must match Section 0.5 exactly, including the decay curve over h in {1,2,3,5,10,21} and
  the realized `sign`.

Acceptance tests to write: random noise gives |rank_ic| < 0.01; the planted feature recovers its IC
within 0.01; fwd_ret_1 as its own signal gives rank_ic > 0.9; negating a signal exactly negates rank_ic;
higher cost_bps monotonically lowers sharpe; two identical calls are bit-identical.

Do NOT implement Deflated Sharpe, PBO, CSCV or the trial ledger — those are Phase 6. This engine only
measures; it never decides accept/reject.
Finish by writing reports/p4_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P5 — Operators, AST tools, alpha zoo

```
Execute PHASE 5 from IMPLEMENTATION_PLAN.md.

Also read: PRE_BUILD_TASKS.md section T5 — it contains the Alpha101 expressibility audit, the list of
confirmed-expressible formula numbers, and the field-coverage table. Do not re-derive that audit.

Build src/operators.py, src/ast_tools.py, src/zoo.py, tests/test_p5_operators.py.

The operator library is a SAFETY feature, not a convenience. Every operator must be causal — no
operator may reach forward in time. This is what makes formula-level look-ahead structurally impossible
rather than hopefully caught. The mandatory acceptance test: for every time-series operator, changing a
FUTURE input value must not change any earlier output. Assert it for all of them. If an operator cannot
pass, delete it.

Include if_else(cond,a,b) and ts_product(x,d) — if_else alone unlocks ~11 more Alpha101 formulas and is
element-wise, so it is trivially causal.

The parser must use Python's ast module with a STRICT whitelist (Call, Name, Constant, BinOp only).
It must reject __import__('os'), close.values, comprehensions, and lambdas.

src/zoo.py is REQUIRED, not test fixtures — the pre-filter's novelty check compares against it. ~35
formulas: 25 from Alpha101 plus 10 classical. An audit already confirmed ~39 of Alpha #1-60 are
expressible with our operators; the spec lists the confirmed-expressible numbers. vwap IS available
(P2 derives it) and adv{d} is the idiom ts_mean(mul(volume,close),d). Skip Alpha#56 (needs true market
cap) and disclose that.
Finish by writing reports/p5_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P6 — Statistical gates and trial ledger

```
Execute PHASE 6 from IMPLEMENTATION_PLAN.md.

Build src/gates.py, src/ledger.py, data/ledger.db, tests/test_p6_gates.py.

If src/backtester.py doesn't exist, stub it — the statistics are what this phase is about.

The governing fact: if you test N worthless signals, the best one's t-stat is about sqrt(2*ln(N)).
N=20 gives 2.45, N=200 gives 3.26 — clearing a "t>3" bar from pure noise. Everything here prices that in.

Gate B runs in this order and the order is load-bearing:
  1 orthogonalize against the book -> residual
  2 novelty (marginal IC of the residual) — kill clones HERE
  3 statistics: Deflated Sharpe ON THE RESIDUAL, t>3, PBO
  4 rationed holdout peek — only now, and counted
Novelty precedes statistics because step 4 spends an irreplaceable holdout peek while step 2 is free.
And the DSR must be computed on the RESIDUAL, not the raw signal — the fitness object is
"deflated, holdout-gated, orthogonalized marginal IC", one composite thing.

Implement the selection-vs-rejection-only distinction precisely: Tier-1 runs across variants are
selection (counts_as_trial=1); red-team stresses, cost sweeps and lag tests can only kill and never
promote, so they cannot inflate the false-discovery rate (counts_as_trial=0).

The ledger module must contain NO DELETE statement. If trials can be removed, deflation is gameable.

Headline acceptance test: generate 200 pure-noise signals, take the best. Its raw t-stat should land
near 3.3 (validating the sqrt(2 ln N) rule) and the Deflated Sharpe MUST reject it. A real signal found
in 5 trials must pass the same gate.
Finish by writing reports/p6_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P7 — Memory stores

```
Execute PHASE 7 from IMPLEMENTATION_PLAN.md.

Build src/memory.py, data/memory.db, data/bandit_state.json, artifacts/cards/, tests/test_p7_memory.py.

Memory is SIX stores, not one — the consumers have incompatible access patterns, and one of them (the
trial ledger feeding the Deflated Sharpe) must be exact and complete because a multiple-testing count
cannot be "approximately right". Keep exact and semantic stores physically separate.

Two mechanisms are mandatory in the lesson store:
- Asymmetric veto: a high-confidence FAILURE hard-blocks that edit motif in that context; a success only
  nudges a prior upward. Failures are more reliable evidence than successes in a noisy domain.
- Confidence gating: a lesson is not applied as a prior until n_observations >= 3.

And in the bandit state: an EXPLORATION FLOOR. A family may be starved to 5% of budget, never to 0%.

Both exist to guard against second-order overfitting — if Reflection writes "momentum fails" after three
failures and the Planner defunds momentum, an irreversible decision has been made on n=3. That never
shows up in any backtest, so the guards are the only defense. Document this in docstrings.

Retrieval: start with family + keyword filtering. With a few hundred lessons that is sufficient. Do NOT
install a vector database.
Finish by writing reports/p7_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P8 — LLM agents and research corpus

```
Execute PHASE 8 from IMPLEMENTATION_PLAN.md.

Also read: PRE_BUILD_TASKS.md section T3 IN FULL — the model-deprecation finding, the exact free-tier
rate-limit table, and the per-thesis token projection this phase must design around.

Build src/agents/*.py, src/agents/prompts/*.txt, data/corpus/anomalies.json, .env.example, tests.

Eight agents. Deterministic computations are NOT agents — the backtester, statistics and novelty check
are plain code, so their verdicts cannot be talked around.

Three things easy to get wrong:
1. Do NOT hard-code a model ID. llama-3.3-70b-versatile and llama-3.1-8b-instant were reportedly
   deprecated in June 2026. Read from config, probe availability at startup, walk a fallback chain.
2. Budget is TIGHT. Free-tier tokens-per-day binds before requests-per-day. Measured: ~16.6 calls and
   ~26,500 tokens per thesis, so ~20 theses is a full day. Implement a token-bucket throttle (TPM), a
   TPD counter, static-prefix prompts so the rubric/operator-list caches, and a clean BudgetExhausted
   exception that leaves no partial write. Keep the Judge and Coder prompts SHORT — they are ~11 of the
   16.6 calls per thesis.
3. You must BUILD data/corpus/anomalies.json (~40 entries) — the Librarian has nothing to retrieve from
   otherwise. Use free abstracts and published anomaly lists only, no paywalled content. Include the
   tradeable_with_our_data flag so the Librarian can tell the Hypothesis agent "real anomaly, but we
   have no fundamentals — don't propose it".

The pre-registered sign is the project's headline mechanism: the Hypothesis agent commits to a direction
BEFORE any data is touched; serialize the thesis, sha256 it, store the hash with a timestamp before any
backtest runs. The Economics Reviewer must be a SEPARATE client instance from the Hypothesis agent —
models grade their own work generously.

Everything must run offline with LLM_MODE=mock and no API key.
Finish by writing reports/p8_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P9 — Red-Team test menu

```
Execute PHASE 9 from IMPLEMENTATION_PLAN.md.

Build src/redteam.py and tests/test_p9_redteam.py — the eleven parameterized falsification tests plus
the survive/kill rule.

The agent decides WHICH attacks fit; the attacks themselves are pre-written parameterized backtests. It
never writes free-form code. That is what keeps every attack reproducible.

All eleven are REJECTION-ONLY — they can kill a candidate but never promote one. A filter that only
rejects cannot raise the false-discovery rate, so record every one of these runs with counts_as_trial=0.
This is the answer to "doesn't running 11 backtests per candidate blow up your trial count?"

Two tests to understand rather than just implement:
- Test 6 (shift only delivery_pct) is more diagnostic than test 5 (global lag): if RankIC survives a
  global shift but collapses when only delivery_pct moves, you have LOCALIZED the dependency to the one
  field whose timing is genuinely ambiguous.
- Test 3 is a SIZE tercile using the trailing-turnover size_proxy, NOT market cap. Current shares
  outstanding applied to 2015 is a look-ahead.

Regime labels must use EXPANDING-window thresholds only. A full-sample volatility threshold is
look-ahead; assert that no full-sample statistic is used.
Finish by writing reports/p9_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P10 — Orchestration graph

```
Execute PHASE 10 from IMPLEMENTATION_PLAN.md.

Also read: INITIAL_PLAN.md section 3 (the nine-stage architecture diagram, which this phase wires up)
and PRE_BUILD_TASKS.md T3 (why checkpointing is load-bearing: the free tier only supports ~20 theses
per day, so runs must span days).

Build src/loop.py and tests/test_p10_loop.py — the LangGraph wiring of all nine stages.

The rule the whole design obeys: agency where there is a DECISION, deterministic code where it is a
FIXED COMPUTATION. All verdict math is code with a fixed threshold, so nothing can talk its way past a
gate. Do not put verdict logic in an LLM node.

Three enforcement points are this phase's real content:
1. Variant cap: the judge->code edge maintains a per-thesis counter, hard-capped at 20. At the cap,
   force promote-best or reject. (At 200 variants the best of pure noise shows t=3.26 — the cap is what
   stops the search manufacturing significance.)
2. Fresh-fold: the search runs entirely on VAL_A; the single promoted winner must hold on VAL_B, which
   no variant ever touched. Instrument the backtester and ASSERT no VAL_B call happens before a promote.
3. Gate B ordering: novelty before statistics. Instrument call order and assert it.

Also implement: the curriculum (rotate mandatory red-team regimes every N generations) and the FDR
auto-tightening meta-check (raise T_STAT_BAR when rolling FDR rises). Both are improvement mechanisms
and "improves over iterations" is directly graded.

Checkpointing with SqliteSaver is essential, not optional — the LLM budget only supports ~20 theses per
day, so a run must resume tomorrow rather than restart.

Portfolio is NOT a graph node — it runs once after the graph terminates.

Must run end-to-end with LLM_MODE=mock and no network.
Finish by writing reports/p10_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P11 — Demo run and the three bad examples

```
Execute PHASE 11 from IMPLEMENTATION_PLAN.md.

Produce the presentation's evidence: one genuinely accepted Alpha Card, three bad examples, and the
off-loop portfolio post-process.

The three bad examples span the three failure families, each told in three beats (naive result -> the
system catches it -> the fix):
1. DATA — the universe source was structurally broken. Show the supplied constituent file passing
   every superficial check (37 snapshots, exactly 200 names each, dead companies retained) while 80 of
   today's 200 NIFTY 200 constituents never appear in it at all, every one with zero inclusion/
   exclusion events — the signature of a change-log replayed onto an incomplete base seed. Show that
   DSR, PBO, purge/embargo and the lag test ALL PASS it, because it contaminates the universe rather
   than any single factor. It was caught by external reconciliation against NSE's list. That is the
   point of this example. The fix was Phase 1: rebuild the universe from bhavcopy by trailing turnover.
2. STATISTICS — a leaky factor with spectacular Tier-1 RankIC, destroyed by red-team test 5. Show that
   the Deflated Sharpe would have passed it.
3. ECONOMICS — a data-mined signal whose realized sign is OPPOSITE its pre-registered sign. A thesis
   failure, not a discovery, and no statistical gate would have flagged it.

Every example must be reproducible from a seed and a single command.

If the loop fails to produce an accepted card, REPORT THAT HONESTLY. A system that rejects everything is
a finding. Do not fabricate a result.
Finish by writing reports/p11_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P12 — System evaluation and ablation

```
Execute PHASE 12 from IMPLEMENTATION_PLAN.md.

Also read: INITIAL_PLAN.md section 10 (the system-evaluation metrics) and PRE_BUILD_TASKS.md T3 (the
~20-thesis/day ceiling — which is why the seeded ablation pool must stay LLM-free).

Build src/evaluation.py and reports/p12_system_evaluation.md. This grades the FACTORY, not the signal,
and it is a directly graded deliverable.

The ablation is the answer to "isn't this over-engineered?":
- Seed a pool of ~40 factors with known ground truth: ~10 genuinely predictive (plant real signal into
  the fixture labels), ~10 pure noise, ~10 deliberately overfit, ~10 deliberately leaky.
- Run the pool through the gates with each gate enabled, then disabled.
- Report per gate: catch rate (junk rejected), false-kill rate (good rejected), and headline FDR with
  the gate on vs off.
This pool needs NO LLM calls, so it is not constrained by the token budget.

Also implement fake-learning detection: track total rejections per generation and per-gate pass rate
over time, not just the changing character of failures. There is a published critique that factor-mining
agents only look like they're learning — their error TYPES mature while total error VOLUME stays flat.
Report which one we actually observe, INCLUDING if it is the unflattering answer.

Do NOT tune the gates to make the ablation look good — that is overfitting the evaluation. Run it once,
report what it says. State the small-sample limitation explicitly.
Finish by writing reports/p12_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

## P13 — Slide deck

```
Execute PHASE 13 from IMPLEMENTATION_PLAN.md — the 20-minute deck, using the slide table in that
section for structure and sources.

The strongest slide is "five failure modes, five mechanisms — and what each does NOT catch"
(INITIAL_PLAN.md section 6). Build the deck around it.

Slide 14 matters more than it looks: two of our four original "novel" claims were already published
(arXiv 2608.27734 and 2608.11250). Concede them with citations and lead with the two that survive —
the pre-registered sign, and the three-budget conflict. A researcher who knows those papers will ask,
and conceding is a stronger position than a bluff.

Check every citation before it goes on a slide. Author attributions especially — arXiv 2608.27734 is a
single author, Eray Gençay.
Finish by writing reports/p13_handoff.md per IMPLEMENTATION_PLAN.md section 0.7, with a measured
value against every acceptance criterion. Then STOP — the owner verifies before the next phase starts.
```

---

# SUGGESTED ORDER

**Sequential minimum path** (if time is short — real data, real backtester, real gates, real bad
examples, agent loop presented as design):
`P0 → P1 → P2 → P3 → P4 → P6 → P11 → P13`

**Full build:**
`P0` first, then `P1 → P2 → P3` on the data track while `P5, P7, P8, P9` run in parallel, then
`P4 → P6 → P10 → P11 → P12 → P13`.

┌────────────────────────────────────────────────────────────────────┬────────┬─────────────────────────────────────────┐
│                               Phase                                │ Model  │                Thinking                 │
├────────────────────────────────────────────────────────────────────┼────────┼─────────────────────────────────────────┤
│ P0 Scaffolding, P1 Universe, P4 Backtester, P7 Memory, P9 Red-Team │ Sonnet │ medium                                  │
├────────────────────────────────────────────────────────────────────┼────────┼─────────────────────────────────────────┤
│ P3 Panel, P5 Operators+zoo, P8 Agents                              │ Sonnet │ medium — high volume, not high subtlety │
├────────────────────────────────────────────────────────────────────┼────────┼─────────────────────────────────────────┤
│ P2 Prices                                                          │ Opus   │ high                                    │
├────────────────────────────────────────────────────────────────────┼────────┼─────────────────────────────────────────┤
│ P6 Gates                                                           │ Opus   │ high                                    │
├────────────────────────────────────────────────────────────────────┼────────┼─────────────────────────────────────────┤
│ P10 Loop                                                           │ Opus   │ medium–high                             │
├────────────────────────────────────────────────────────────────────┼────────┼─────────────────────────────────────────┤
│ P11 Demo, P12 Evaluation                                           │ Opus   │ high                                    │
├────────────────────────────────────────────────────────────────────┼────────┼─────────────────────────────────────────┤
│ P13 Slides                                                         │ Opus   │ medium                                  │
└──────────────────────────────────────────────────────────────────────────────────────────┘