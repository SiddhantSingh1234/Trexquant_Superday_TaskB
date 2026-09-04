"""Reusable prose blocks (Section 0.4).

D2 fills every ``BLOCKS`` name from the source docs — quoted / condensed, never
invented.  Every block ends with a trailing ``_Source: <doc> <section>_`` line.

This module must not import ``src.*`` (asserted by the D0 test).
"""
from __future__ import annotations

BLOCKS: tuple[str, ...] = (
    "one_liner",
    "nine_stages",
    "alpha_card",
    "three_budgets",
    "four_regions",
    "five_failures",
    "sqrt_2lnN",
    "pre_registered_sign",
    "variant_cap_fresh_fold",
    "gate_b_order",
    "novelty_claims",
    "weak_points",
    "walkthrough",
    "build_status",
    "nav_guide",
)

_BLOCKS: dict[str, str] = {}


def _b(name: str):
    def deco(fn):
        _BLOCKS[name] = fn().strip() + "\n"
        return fn
    return deco


# --------------------------------------------------------------------------- #
@_b("one_liner")
def _one_liner() -> str:
    return """
A team of specialised AI agents — a manager, a librarian, a researcher, an
engineer, a critic, a statistician, a prosecutor and a historian — runs in a
**loop**: *propose an idea → turn it into a formula → test it → attack it → keep
it only if it survives every check → remember what happened → propose a better
idea next time.* A finite AI budget forces it to be economical.

The factory produces one thing, over and over: a **daily cross-sectional alpha
signal** — one number per stock per day, a *ranking* of which stocks will beat
which — **plus an economic thesis** for why it should work. Both are required; a
signal with no story is a coincidence you have not noticed yet.

_Source: FLOW_EXPLAINED.md PART 0_
"""


@_b("nine_stages")
def _nine_stages() -> str:
    return """
| # | Stage | What it does |
|---|---|---|
| S1 | **Planner** | groups ideas into families (momentum, liquidity, reversal, seasonality, microstructure), runs a multi-armed bandit over them, and enforces the **token budget** and the **20-variant cap**. |
| S2 | **Librarian** | before anyone has an idea, retrieves from the paper corpus **and the factory's own memory** — the memory half stops the loop re-proposing a dead end it killed three generations ago. |
| S3 | **Hypothesis** | writes the economic thesis: named mechanism · counterparty · why it isn't already arbitraged · horizon & regime · **a falsifiable prediction including the direction** (the pre-registered sign, locked before any data is touched). |
| — | **Gate A · Economics** | a *different* AI instance scores the thesis against the five-point rubric, harshly. Missing any item → rejected before a line of code is written — the cheapest possible rejection. |
| S5 | **Implementation loop** | the Coder assembles a formula from a fixed causal-operator toolbox; the Judge names the single change that would help. Up to **20 attempts**, then promote the best. Compile / complexity / duplicate failures are killed for free. |
| — | **Fresh-fold check** | score the promoted winner on VAL_B — data no variant ever touched. Converts within-thesis selection into a genuine out-of-sample check, at no cost to the sealed data. |
| S6 | **Backtester** | one engine, many switches (data slice · lag · costs · neutralisation · subset), called in eight situations. |
| — | **Gate B · Honesty** | orthogonalize → **novelty** → statistics (DSR / t / PBO on the residual) → one rationed holdout peek. Is it NEW? then: is it REAL, given how hard we looked? |
| — | **Gate C · Red-Team** | 11 pre-written parameterised attacks; the agent chooses which diagnostics to add but can never opt out of the 5 decisive falsifiers. Rejection-only. |
| S9 | **Memory & Reflection** | every card — accepted **and** rejected — lands here with its death certificate. The historian records which mechanisms and edit motifs keep working or failing, and nudges the Planner. This stage is the entire answer to "how does it improve over iterations?" |

_Source: FLOW_EXPLAINED.md PART 2_
"""


@_b("alpha_card")
def _alpha_card() -> str:
    return """
Everything in the system is one object travelling through nine stages: the
**Alpha Card**. It starts nearly empty and gains a section at each stage —

- thesis, mechanism, counterparty, horizon, regime
- **the pre-registered sign** — committed before any data is touched
- the formula (and its canonical tree)
- quick-test results → full-test results
- the honesty audit (on the residual)
- the red-team attack report
- verdict + family tree (parent card, edit motif) + which data fields it used

A card that gets **rejected** is not thrown away — it carries its death
certificate (*what was tried, and exactly why it died*) into memory. A factory
that only remembers its wins learns nothing.

_Source: FLOW_EXPLAINED.md PART 1_
"""


@_b("three_budgets")
def _three_budgets() -> str:
    return """
Most people see one budget. There are three:

| Budget | Who spends it | Is a backtest expensive here? |
|---|---|---|
| **AI tokens** | the thinking agents | **No** — a backtest is a Python call, ~0 tokens |
| **Computer time** | the backtests | barely |
| **Statistical integrity** | *every* test = one trial; every vault peek is irreplaceable | **Yes — invisibly** |

The reason to filter cheaply *before* testing is **budget 3**, not 1 or 2: ten
thousand careless backtests raise the honesty penalty for *every* signal in the
run. And budgets 1 and 3 **actively conflict** — token efficiency rewards finding
the winner in fewer tries; statistical integrity punishes every try you made
along the way. Any technique that makes search cleverer at maximising a noisy
score is, by the identical mechanism, cleverer at fooling you. That is the reason
for the variant cap, the fresh fold, and MCTS being on the roadmap rather than in
the loop.

_Source: FLOW_EXPLAINED.md PART 5 §②_
"""


@_b("four_regions")
def _four_regions() -> str:
    return """
```
|<-- TRAIN 3y -->|<----- VAL-A 3.5y ----->|<- VAL-B 1y ->|<=== HOLDOUT 3.5y ===>|
  2015-01→2017-12    2018-01→2021-06        2021-07→        2022-07→2025-12
  warm-up buffer     all 20 attempts        2022-06         sealed vault,
  + CSCV folds       are scored here        only the        opened a counted
  (never selects)    (the search plays)     WINNER          number of times
```

- **Warm-up (2014)** — lookback buffer only. Never scored.
- **Train (2015–2017)** — gives a 252-day rolling feature enough history to be
  computable on day 1 of Val-A, and supplies extra CSCV folds for PBO.
  **It never picks a winner** — nothing is fitted; the Coder picks the windows,
  not the data.
- **Val-A (2018 → 2021-06)** — the search playground; every formula variant is
  scored here. Spans two stress regimes (the 2018 credit crisis *and* COVID).
- **Val-B (2021-07 → 2022-06)** — the **fresh fold**. Never used to choose
  anything, so testing the winner here is a genuinely honest out-of-sample check
  that costs nothing from the sealed data.
- **Holdout (2022-07 → 2025-12)** — **sealed.** A fixed, counted number of peeks
  in the system's lifetime (12). When they're spent, they're spent.

_Source: FLOW_EXPLAINED.md PART 3 · IMPLEMENTATION_PLAN.md §0.4_
"""


@_b("five_failures")
def _five_failures() -> str:
    return """
**Five ways to be wrong. Five different mechanisms. And — the part that shows
real understanding — what each mechanism does *not* cover.**

| How you get fooled | What catches it | What definitely does **not** |
|---|---|---|
| **Cheating (look-ahead)** | Causal operators (structurally impossible) · timing rules · purge & embargo · lag attacks | **Deflated Sharpe and PBO** — proven: a Sharpe-35 cheat survives both |
| **Over-searching** | Deflated Sharpe vs effective trial count · PBO · **20-variant cap** · fresh fold · rationed vault | any amount of economic reasoning |
| **Story-fitting** ("right answer, wrong reason") | **Pre-registered sign** · counterparty rubric · author ≠ judge | IC, Sharpe and DSR all pass it happily |
| **Reinventing what you own** | Formula-tree duplicate check + leftover-IC check | all of the above |
| **Fragility** (one regime, dies on costs) | The 11 Red-Team attacks | everything measured in-sample |

_Source: FLOW_EXPLAINED.md PART 6_
"""


@_b("sqrt_2lnN")
def _sqrt_2lnN() -> str:
    return """
**Searching harder makes you *more* likely to fool yourself.** Test N formulas
that are all pure noise, keep the best, and its t-statistic will be about
**√(2 ln N)** — a *ceiling*. The realised expected max sits about 0.5 below it
(measured: best-of-200 lands at t ≈ 2.74, not the √(2 ln 200) = 3.26 ceiling).
The pre-registered sign gives **zero** protection here — all N variants share one
idea, so they share one predicted direction, and the sign check passes for every
one.

**How often does the best of N pure-noise signals clear the "t > 3" bar?**
(measured on the built system — `reports/p6_handoff.md` §"measured")

| Things you tried (N) | realised E[max t] | P(best clears t > 3) — on pure noise |
|---:|---:|---:|
| 5 | 1.16 | **0.7%** |
| **20** *(our hard cap)* | 1.87 | **2.7%** |
| 100 | 2.51 | **12.6%** |
| 200 | 2.75 | **23.6%** |
| 500 | 3.04 | **49.1%** |

At 500 attempts the bar is a **coin flip** — and nothing about the result itself
tells you which case you are in. Only the count does. Hence the ledger. We count
**effectively** (Deflated Sharpe folds in *how similar* the trials were — 20
knob-variants measured as ~2 effective bets) and **run-wide, not per-thesis**
(opening a new thesis must not reset the counter).

_Source: FLOW_EXPLAINED.md PART 2 (S6 section) · reports/p6_handoff.md §"measured"_
"""


@_b("pre_registered_sign")
def _pre_registered_sign() -> str:
    return """
Before any data is touched, the Hypothesis agent writes down and **locks** which
direction it expects: high factor value → high future return (`+1`), or the
reverse (`−1`). It is timestamped into the record. When the signal is later
tested, the realised direction must match — **if it doesn't, we reject, even if
the numbers are excellent.**

Two problems it kills:

1. **The sign is free.** Every factor `f` has an exact mirror `−f`. Without a
   prior commitment you effectively test both and keep whichever worked — two
   experiments recorded as one, and every downstream honesty calculation is now
   wrong.
2. **The AI will write a beautiful story for anything.** Let the model see the
   result first and it produces a plausible mechanism for whatever the data
   happened to show. The "economic thesis" — the thing being graded — quietly
   degenerates into a paragraph written *about noise*.

Pre-registration turns the thesis from a **description** into a **prediction that
can be wrong** — the whole difference between science and storytelling. Bonus:
committing to one direction lets the statistics use a one-sided test (rigor that
*buys* power). Honest limit: it binds one idea to one direction and gives **zero**
protection *inside* an idea — that gap is what the variant cap and fresh fold are
for.

_Source: FLOW_EXPLAINED.md PART 2 (S3) · PART 5 §①_
"""


@_b("variant_cap_fresh_fold")
def _variant_cap_fresh_fold() -> str:
    return """
**The cap bounds how much noise-fishing can happen. The fresh fold verifies the
fish is real. Neither alone is enough; together they're strong.**

- **Fix 1 — a hard cap of 20 formula attempts per idea**, enforced by the
  Planner. Twenty leaves room to find a decent expression of a good idea while
  keeping the noise-derived best t-stat around 2.45 — comfortably below the 3.0
  bar, so a real signal still has to earn its way past. At 20 the Judge's
  `refine` edge is forced to `promote` the best variant so far.
- **Fix 2 — count every attempt.** All 20 go into the trial ledger, run-wide.
- **Fix 3 — the fresh fold.** The search runs entirely on VAL_A; the single
  promoted winner must hold on VAL_B, which no variant ever touched. This
  converts within-thesis selection into a genuine out-of-sample check **without
  spending a holdout peek**.

And the flip side, which belongs on a slide: **because our search is guided by
economic theory it tries far fewer candidates than brute-force mining — fewer
trials → a smaller honesty penalty → the survivors are genuinely more
believable.** Same statistical machinery, hugely different burden of proof.

_Source: FLOW_EXPLAINED.md PART 3 ("The three fixes") · IMPLEMENTATION_PLAN.md Phase 10_
"""


@_b("gate_b_order")
def _gate_b_order() -> str:
    return """
Gate B runs four steps **in this exact order** — and we changed it deliberately
after catching our own bug:

1. **Orthogonalize** — subtract the part explained by the accepted book, leaving
   the **residual**.
2. **Novelty (runs FIRST)** — is the residual's marginal IC meaningful? If
   ≈ 0 it's a clone of something we own → reject. This step is **free and already
   computed**.
3. **The honesty maths on the residual** — Deflated Sharpe vs effective trial
   count, one-sided t-stat, PBO.
4. **One counted holdout peek — on the residual.**

Why novelty moved first: **the maths step ends by spending a sealed-vault peek**
— the scarcest thing we own — while novelty is essentially free. Under the old
order you could burn an irreplaceable peek on a signal novelty was about to
reject as a momentum clone. *Free filters that protect scarce resources go
first.* And the correct object to deflate is the **residual**: measured on a
real candidate, the original scored 0.0320 on the sealed data and the residual
0.0196 — peeking at the original would overstate the genuinely new edge by 63%.

_Source: FLOW_EXPLAINED.md PART 2 (Gate B) · IMPLEMENTATION_PLAN.md Phase 10 enforcement point 3_
"""


@_b("novelty_claims")
def _novelty_claims() -> str:
    return """
We re-checked our claims against the literature as of September 2026 and found
**two of our four original "novel" ideas had already been published**. Conceding
those with citations is a strength — a researcher who knows the paper *will* ask.

| # | Claim | Status |
|---|---|---|
| ① | **Pre-registered sign + counterparty gate** — commit to a direction *before* seeing data, then reject on mismatch. The closest existing work checks the formula against the story *afterwards*. | **Genuinely novel — our lead.** |
| ② | **Three budgets, and the fact that two of them fight** — token efficiency and statistical integrity are in direct conflict. | **Novel** — not found stated in any paper. |
| ③ | **Fixed-menu, rejection-only Red-Team** — parameterised tests, never free-form AI code; provably cannot inflate the trial count. | **Differentiated.** |
| ④ | **Statistical gates in the scoring function** (trial ledger → DSR → PBO in search). | **Already published** (arXiv 2608.27734). **Concede it.** |

Claim ④'s paper hands us something better: a deliberately **leaky** strategy
(Sharpe 35) sailed through Deflated Sharpe and PBO untouched. *Statistical gates
catch over-searching, not cheating — different problems.* Leakage has to be made
impossible by construction, which is exactly what the causal operator library
does.

_Source: FLOW_EXPLAINED.md PART 5_
"""


@_b("weak_points")
def _weak_points() -> str:
    return """
Stated openly, because pretending otherwise is worse:

1. **Free open-source models** reason a notch below frontier ones, so our theses
   are weaker than a production version's. Swapping in a frontier API is a
   one-line change.
2. **No point-in-time fundamentals** — free Indian fundamental data isn't
   trustworthy, so valuation / earnings-surprise families are out of reach. A
   **deliberate rigor choice**: bad fundamental data would inject exactly the
   look-ahead this system exists to catch.
3. **Small-sample ablation** — a few-hour prototype gives illustrative, not
   conclusive, gate statistics.
4. **~1% residual universe inconsistency** measured but not fully repaired.
5. **`delivery %` publish time** still needs one direct verification.
6. **Sector labels aren't point-in-time** — minor, since sector is only used for
   optional neutralisation.

_Source: FLOW_EXPLAINED.md PART 9_
"""


@_b("walkthrough")
def _walkthrough() -> str:
    return """
**One idea, walked all the way through** (illustrative numbers from the plan):

1. **Planner** — the "liquidity" family has been productive; allocate budget, cap 20 attempts.
2. **Librarian** — pulls papers on the illiquidity premium; memory notes *plain volume spikes failed in gen 3 without a price-direction filter*. Briefs the team.
3. **Hypothesis** — *"stocks with an abnormal one-day volume spike **on a falling price** are being dumped by forced sellers; others underreact because forced selling carries no information, so the price rebounds over 3–5 days."* Mechanism = underreaction to forced selling. Counterparty = forced/panicking sellers. Horizon 3–5 days, calm markets. **Pre-registered sign: `+1`. Locked.**
4. **Gate A** — a different AI checks the rubric. All five present, mechanism specific, counterparty plausible. **Pass.**
5. **Implementation loop** — Coder writes `rank(ts_mean(volume,1)/ts_mean(volume,20)) * sign(prev_close − close)`. VAL-A RankIC 0.031. Judge: *"the thesis claims 3–5 days but you're measuring 1 — try a 3-day forward window."* Attempt 2: 0.038. Attempt 5 widens the volume window: 0.041. **7 of 20 used.** Promote.
6. **Fresh-fold** — score the winner on VAL-B (untouched by those 7 attempts): RankIC 0.034. Lower than 0.041 — some was selection luck — but clearly alive. **Pass.**
7. **Full battery** — RankIC 0.036, ICIR 0.6, Sharpe 1.4, decay fades by day 6 (consistent with the 3–5 day story). Sign positive, matches pre-registration.
8. **Gate B** — subtract existing momentum & reversal → residual marginal IC **0.025**, genuinely new. Ledger: 143 trials this run → 31 effective after clustering. Deflated Sharpe on the residual **0.97**, clear of the 0.95 bar. t = 3.2. PBO low. **Spend holdout peek #4 of 12 — on the residual.** Holds. **Pass.**
9. **Gate C · Red-Team** — the five decisive falsifiers run (drop-best-year, bull/bear, costs at 15 bps, +1-day lag, sign stability) plus 3 diagnostics. No decisive test flags. **Survives.**
10. **Alpha Card issued** — thesis, locked sign, formula, all reports, family tree, fields used.
11. **Memory** — *"forced-seller underreaction works with a price-direction filter; plain volume spikes alone failed in gen 3. Edit motif: widen the window to match the stated horizon. Keep exploring this family."* Planner gets a nudge.

_Source: FLOW_EXPLAINED.md PART 4_
"""


@_b("build_status")
def _build_status() -> str:
    return """
The system is built in phases, each human-verified before the next begins. The
critical path is **P0 → P2 → P1 → P3 → P4 → P6 → P10 → P11 → P13**, with
**P5 / P7 / P8 / P9** (operators, memory, agents, red-team) as a parallel branch
feeding the orchestration loop (P10). Portfolio combination runs **once, after
the loop terminates** — it is a post-process, not a graph node.

The loop's stop rule: token budget exhausted **OR** K = 3 consecutive
generations adding < ε novelty-adjusted marginal IC **OR** a hard generation cap
— whichever fires first.

The board below is **derived live** from which `reports/p*_handoff.md` files
exist — never a hard-coded status list, because P11/P12 may land while this
dashboard is being built.

_Source: IMPLEMENTATION_PLAN.md Phase 10 · §0.7 · EXECUTION ORDER_
"""


@_b("nav_guide")
def _nav_guide() -> str:
    return """
| Page | What it contains |
|---|---|
| **Home** | this page — the narrative, the six flowcharts, the key numbers, the build board |
| **01 Universe** | the survivorship-free coverage chart, liquidity floor, churn, canary & heavyweight timelines, membership explorer |
| **02 Prices** | coverage by year, corporate actions, extreme returns, source eras, delivery availability, VWAP sanity, per-symbol candlesticks |
| **03 Feature Panel** | the ten features, distributions, correlation, IC & IC-decay, the look-ahead self-test, the leakage-detector sanity check |
| **04 Backtester** | the live formula sandbox — parse, evaluate, score on a split (never HOLDOUT) |
| **05 Operators & Zoo** | the causal operator library and the reference formula zoo |
| **06 Gates & Ledger** | the Deflated-Sharpe calculator, the trial ledger, the holdout-peek budget gauge |
| **07 Memory** | the formula index, lesson store, bandit allocation, lineage |
| **08 LLM Agents** | the eight agent roles, prompts, token budget projection |
| **09 Red Team** | the 11 attacks, the 5 decisive falsifiers, the live red-team runner |
| **10 The Loop** | the P10 run state — generations, verdicts, gate outcomes (live once a run exists) |
| **11 Alpha Cards** | the accepted-card gallery |
| **12 System Evaluation** | the factory-level metrics (productivity, FDR, efficiency, ablation) |
| **13 Bad Examples** | the three deliberate failures — data / statistics / economics |
| **14 Build Log** | the phase handoffs and what each produced |

_Source: DASHBOARD_PLAN.md §0.3_
"""


def block(name: str) -> str:
    """Return Markdown for a named block.  Every block ends with a
    ``_Source: <doc> <section>_`` line."""
    if name not in BLOCKS:
        raise KeyError(f"unknown block {name!r}; valid: {BLOCKS}")
    return _BLOCKS[name]
