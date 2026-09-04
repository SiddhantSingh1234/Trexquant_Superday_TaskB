# Alpha Factory

An automated equity-alpha research system for the NIFTY-200 (India) universe. LLM
agents propose factor theses and formulas; deterministic code (backtester,
statistical gates, red-team stress tests) decides accept/reject. The system is
built as thirteen phases (P0-P13), each with its own module, tests, and
handoff report under `reports/`. A read-only Streamlit dashboard explains and
lets a reviewer explore the finished system.

This README explains, stage by stage, what each phase does and the exact
command(s) to run it, then walks through the main orchestration loop (P10) in
detail: every node in the graph, the order they run in, and the rules that
govern promotion, rejection, and stopping.

Full design rationale lives in `IMPLEMENTATION_PLAN.md` (the build spec),
`FLOW_EXPLAINED.md` (plain-English walkthrough), and `PHASE_PROMPTS.md` (the
brief given to build each phase). This document is the "how do I actually run
it" companion to those.

## Quick start: running the main loop end to end

The loop (`src/loop.py`) has a proper CLI. This section is everything you
need to get it running; later sections cover each prerequisite stage and the
loop's internals in more detail.

### Prerequisites

Nothing is strictly required -- `--smoke` runs fully offline on synthetic
data with no setup at all:

```
./.venv/Scripts/python.exe -m src.loop --smoke
```

For a real run against actual market data, build the data artifacts first,
in this order (P2 before P1 -- the universe is derived from price data):

```
./.venv/Scripts/python.exe -m src.prices     # P2: data/prices/ohlcv.parquet
./.venv/Scripts/python.exe -m src.universe   # P1: data/universe/membership.parquet (needs P2)
./.venv/Scripts/python.exe -m src.panel      # P3: data/panel/features.parquet, labels.parquet, splits.json (needs P1+P2)
```

P4-P9 (backtester, operators/zoo, gates/ledger, memory, agents, red-team)
need no build step -- the loop imports them directly.

For `--mode live` you additionally need a Groq API key. Either export it or
put it in a `.env` file at the repo root (loaded automatically):

```
GROQ_API_KEY=your_key_here
```

### Running it

```
python -m src.loop --smoke                                # mock + synthetic + sandbox, 2 generations, no setup needed
python -m src.loop --mode live -n 10 --run-id live_1       # full live run, 10 generations, real data
python -m src.loop --mode live --run-id live_1 --resume    # continue after a budget pause (~20 theses/day free-tier ceiling)
python -m src.loop --mode live --run-id live_1 --resume --stop-after 1   # step one generation at a time
```

Key flags:

| Flag | Effect |
|---|---|
| `--run-id NAME` | run identifier; also names the default checkpoint/report paths (default: `run`) |
| `--mode {mock,live,offline}` | overrides `$LLM_MODE`; `mock` needs nothing, `live` needs `GROQ_API_KEY`, `offline` needs a local Ollama |
| `-n`, `--generations N` | max theses to attempt (default: 10) |
| `--horizon N` | forward-return horizon in days (default: 5) |
| `--resume` | continue from the checkpoint for this run-id |
| `--stop-after N` | halt after N generations this invocation; combine with `--resume` to step generation by generation |
| `--checkpoint PATH` | checkpoint db (default: `artifacts/<run-id>/ck.db`) |
| `--report PATH` | markdown report (default: `reports/<run-id>.md`) |
| `--no-holdout-peek` | never spend a holdout peek in Gate B |
| `--no-throttle` | skip rate-limit sleeps (mock/offline only) |
| `--stop-epsilon`, `--stop-k` | diminishing-returns stop rule tuning |
| `--curriculum-every N` | rotate the mandatory red-team regime every N generations |
| `--sandbox` | throwaway memory/ledger in a temp dir -- leaves the real `data/bandit_state.json`, `data/ledger.db`, and the 12-peek holdout budget untouched |
| `--synthetic` | use a synthetic price panel instead of `data/panel` |
| `--smoke` | shorthand for `--mode mock --synthetic --sandbox --no-holdout-peek -n 2` |
| `--env-file PATH` | dotenv file to load before running (default: `.env`) |

Three things the CLI handles that a hand-rolled script would not:

- **`.env` is loaded automatically.** Nothing else in the package reads it,
  so before this a live run needed `GROQ_API_KEY` exported by hand.
- **`--mode live` fails fast** with a clear error if `GROQ_API_KEY` is
  missing, instead of dying mid-run on the model probe.
- **`--sandbox` isolates state.** By default the loop reads/writes the real
  `data/` stores (memory, ledger, holdout-peek budget); `--sandbox` redirects
  memory and the ledger to a temp directory so an experimental run cannot
  spend from the real holdout budget or pollute the real bandit state. You
  have to opt in to isolation -- the defaults are the real stores.

Checkpoint and report paths are auto-created under `artifacts/<run-id>/ck.db`
and `reports/<run-id>.md` unless overridden.

## Contents

- [Quick start: running the main loop end to end](#quick-start-running-the-main-loop-end-to-end)
- [Setup](#setup)
- [Configuration](#configuration)
- [Pipeline order](#pipeline-order)
- [Stages P0-P9 (data, engine, tooling)](#stages-p0-p9-data-engine-tooling)
- [The main agent loop (P10) in detail](#the-main-agent-loop-p10-in-detail)
- [P11-P13 (demo run, evaluation, slides)](#p11-p13-demo-run-evaluation-slides)
- [Dashboard](#dashboard)
- [Running the test suite](#running-the-test-suite)

## Setup

Python 3.11+, Windows/PowerShell. No Docker, no paid API, no vector database.

```
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

The dashboard has its own, smaller dependency file (Streamlit, plotly), kept
separate so the core research code never depends on a UI framework:

```
./.venv/Scripts/python.exe -m pip install -r requirements-dashboard.txt
```

## Configuration

Everything path- and constant-related lives in `src/config.py` (Phase 0):
repo paths, the five canonical data splits (`warmup`, `train`, `val_a`,
`val_b`, `holdout`), and tuning constants (`MAX_VARIANTS_PER_THESIS=20`,
`HOLDOUT_PEEK_BUDGET=12`, `T_STAT_BAR=3.0`, `COST_BPS_DEFAULT=15`,
`EMBARGO_DAYS=5`, `RANDOM_SEED=42`).

Three environment variables control the LLM agents (Phase 8/10):

| Variable | Values | Effect |
|---|---|---|
| `LLM_MODE` | `mock` (default) \| `live` \| `offline` | `mock` = canned offline responses, no key needed, used by every test. `live` = Groq free tier, needs `GROQ_API_KEY`. `offline` = local Ollama, no network egress. |
| `GROQ_API_KEY` | your key | only read when `LLM_MODE=live` |
| `OLLAMA_HOST` | URL, default `http://localhost:11434` | only read when `LLM_MODE=offline` |

Everything in this repository runs and every test passes with `LLM_MODE=mock`
and no network access.

## Pipeline order

The data track has one twist: **P2 runs before P1.** The universe (P1) is
built from P2's raw bhavcopy price data by trailing 63-day turnover, so P2
must exist first.

```
P0  (scaffolding, config, fixtures)
 -> P2  (price data)
 -> P1  (universe: liquidity-ranked top 200, monthly, trailing-only)
 -> P3  (feature panel, labels, train/val/holdout splits)
 -> P4  (backtester engine)
 -> P5  (operators, AST tools, alpha zoo)          -- independent of P0 only
 -> P6  (statistical gates + trial ledger)
 -> P7  (memory stores)                             -- independent of P0 only
 -> P8  (LLM agents + research corpus)               -- independent of P0 only
 -> P9  (red-team test menu)                         -- independent of P0 only
 -> P10 (orchestration graph -- the main agent loop)
 -> P11 (demo run + bad-example write-ups)
 -> P12 (system evaluation / gate ablation)
 -> P13 (slide deck)
```

P5, P7, P8, P9 depend only on P0 and can be built/run in any order relative to
each other and to P1-P4.

## Stages P0-P9 (data, engine, tooling)

Each stage is one `src/*.py` module. Most expose a `run()` (or module-level
`__main__` block) that regenerates its output artifact(s) under `data/`, and
a `tests/test_p<N>_*.py` file. Run a stage's script when its inputs change;
run its tests to verify the stage in isolation.

### P0 -- Scaffolding (`src/config.py`, `src/contracts.py`)

Paths, constants, the five data splits, and the synthetic fixture generators
(`make_fake_ohlcv`, `make_fake_features`, `make_fake_labels`,
`make_fake_membership`, `make_fake_symbols`) every later phase's tests run
against. No business logic.

```
./.venv/Scripts/python.exe -m pytest tests/test_p0_contracts.py -v
```

### P2 -- Price data (`src/prices.py`)

Downloads/parses NSE bhavcopy OHLCV data, applies corporate-action (split,
bonus, dividend) adjustments keyed by symbol, and writes
`data/prices/ohlcv.parquet` (and `delivery.parquet`, `size_proxy.parquet`
where available).

```
./.venv/Scripts/python.exe -m src.prices
./.venv/Scripts/python.exe -m pytest tests/test_p2_prices.py -q
```

### P1 -- Universe construction (`src/universe.py`)

Builds the tradeable universe **from P2's output**, not from any supplied
constituent file (the supplied NIFTY 200 history file was found to be
missing 80 of today's 200 constituents with zero inclusion/exclusion events
-- a broken source, documented in `reports/p1_universe_report.md`). Rule,
applied on the last trading day of each month using only same-day-available
data:

1. every `SERIES == EQ` stock that day
2. require >= 252 trading days of prior history
3. rank by median daily turnover over the trailing 63 days
4. top 200 names become next month's universe

Writes `data/universe/membership.parquet`, `universe_stats.parquet`,
`liquidity_ranks.parquet` (consumed by red-team test 11), and
`symbols.json`.

```
./.venv/Scripts/python.exe -m src.universe
./.venv/Scripts/python.exe -m pytest tests/test_p1_universe.py -q
```

### P3 -- Feature panel, labels, splits (`src/panel.py`)

Builds the daily feature panel and forward-return labels used by every
backtest, plus `data/panel/splits.json` (the plain-dict form of
`config.SPLITS`). Runs two self-tests on every build: a look-ahead check
(shifting a feature forward changes its IC) and a leak check (a label
predicting itself scores RankIC = 1.0, proving the harness can detect a
leak if one is ever introduced).

```
./.venv/Scripts/python.exe -m src.panel
./.venv/Scripts/python.exe -m pytest tests/test_p3_panel.py -q
```

### P4 -- Backtester engine (`src/backtester.py`)

The single `backtest(signal, split, horizon=..., cost_bps=..., subsample=...)`
entry point every later phase (gates, red-team, the loop) calls. Computes
RankIC/IC, t-stat, Sharpe, turnover, max drawdown, and per-horizon IC decay
over a named split.

```
./.venv/Scripts/python.exe -m src.backtester
./.venv/Scripts/python.exe -m pytest tests/test_p4_backtester.py -q
```

### P5 -- Operators, AST tools, alpha zoo (`src/operators.py`, `src/ast_tools.py`, `src/zoo.py`)

The formula grammar (the small DSL formulas like `rank(delivery_pct)` are
written in), its parser/evaluator/canonicalizer/complexity scorer
(`ast_tools.py`), and a reference "zoo" of ~100 published formulas
(Alpha101 + classical factors) used for duplicate detection in the loop's
pre-filter step.

```
./.venv/Scripts/python.exe -m src.zoo
./.venv/Scripts/python.exe -m pytest tests/test_p5_operators.py -q
```

### P6 -- Statistical gates and trial ledger (`src/gates.py`, `src/ledger.py`)

The deterministic acceptance machinery: Deflated Sharpe Ratio (DSR),
Probability of Backtest Overfitting (PBO), purge/embargo-aware walk-forward
validation, marginal-IC novelty check against the existing book, and
`gate_b()` which combines them into a single accept/reject with reasons.
`ledger.py` is the append-only SQLite record of every trial (so multiple-
testing correction is computed against the true trial count, not a
self-reported one).

```
./.venv/Scripts/python.exe -m src.ledger      # regenerates the empty ledger schema
./.venv/Scripts/python.exe -m pytest tests/test_p6_gates.py -q
```

### P7 -- Memory stores (`src/memory.py`)

Six persistent stores the loop reads and writes across generations: an
exact-match formula index, a semantic lesson store (`data/lessons.db`, kept
physically separate from `data/memory.db` on purpose), a multi-armed bandit
over factor families, an alpha-card store, a lineage graph, and the
accepted-signal "book" used for orthogonalization/novelty checks.

```
./.venv/Scripts/python.exe -m src.memory      # regenerates the empty store schemas
./.venv/Scripts/python.exe -m pytest tests/test_p7_memory.py -q
```

### P8 -- LLM agents and research corpus (`src/agents/*.py`)

Eight LLM-backed agent roles (`planner`, `librarian`, `hypothesis`,
`economics`, `coder`, `judge`, `redteam`, `reflection`) plus the shared
call path in `src/agents/base.py` (model-probe with fallback chain, TPM/TPD
budget enforcement, mock mode) and a 53-entry hand-curated anomaly corpus
(`data/corpus/anomalies.json`) the `librarian` retrieves from.

```
./.venv/Scripts/python.exe -m pytest tests/test_p8_agents.py -q
```

### P9 -- Red-team test menu (`src/redteam.py`, `src/agents/redteam.py`)

Eleven rejection-only falsification tests (a candidate can only be hurt by
them, never helped) run against every candidate that reaches Gate C:
regime robustness, leakage/shift, cost sensitivity, universe-edge behaviour,
and more. Five are always run regardless of what the `redteam` agent selects
(`RED_TEAM_MENU` in `src/agents/redteam.py`); every red-team backtest is
logged to the ledger with `counts_as_trial=0` since it cannot itself promote
a candidate.

```
./.venv/Scripts/python.exe -m pytest tests/test_p9_redteam.py -q
```

## The main agent loop (P10) in detail

Module: `src/loop.py`. This is the orchestration graph that actually
searches for and accepts alpha factors, wiring together P1-P9. It is built
with LangGraph and follows one governing rule:

> **Agency where there is a decision, deterministic code where it is a fixed
> computation.** LLM nodes only *propose* (a family, a thesis, a formula,
> which red-team tests to run). Every accept/reject verdict is computed by
> code against a fixed, pre-declared threshold.

### Two nested loops

There are two loops, not one:

- **The inner graph** (`build_graph`) runs **one thesis** end to end:
  `orchestrate -> retrieve -> brief -> ideate -> gate_a_economics -> code ->
  prefilter -> tier1 -> judge -> (repeat code/prefilter/tier1/judge up to 20
  variants) -> freshfold -> tier2 -> gate_b_novelty -> gate_b_stats ->
  gate_c_redteam -> emit_card -> reflect`.
- **The outer loop** (`run_loop`) invokes the inner graph once per
  "generation" (one generation = one thesis attempt), up to
  `max_generations`, applying stop rules and checkpointing between
  generations. The `reflect -> orchestrate` cycle the design docs describe
  as one big loop is implemented as this outer Python `while` loop rather
  than a graph cycle, which keeps every single graph invocation small
  (well under its 240-super-step recursion limit) and checkpoint/resume
  clean.

### The nodes, in order

| # | Node | What it does | Kind |
|---|---|---|---|
| 1 | `orchestrate` | Bandit picks a factor family (asks the `planner` agent for its family choice, guided by the bandit's per-family allocation); a no-repeat guard stops it drawing the same family twice in one run while others are unexplored. Sets the mandatory curriculum regime for this generation. | agent + code |
| 2 | `retrieve` | Keyword search over the 53-entry anomaly corpus for the chosen family; the top tradeable hit becomes an "anchor" the Coder's first variant must faithfully implement before mutating. | code (RAG) |
| 3 | `brief` | `librarian` agent turns the retrieved angles into a short research brief. | agent |
| 4 | `ideate` | `hypothesis` agent proposes a thesis (mechanism, counterparty, why-not-arbitraged, horizon, expected regime, falsifiable claim). The thesis's predicted sign is **pre-registered and hashed before any backtest runs** -- logged to `ctx.prereg_log` -- so a later "the sign flipped, but that's fine, we predicted this" cannot be fabricated after the fact. | agent + commit |
| 5 | `gate_a_economics` | `economics` agent reviews the thesis for economic plausibility. Reject here skips straight to `reflect` -- no formula is ever coded for an economically incoherent thesis. | agent (Gate A) |
| 6 | `code` | `coder` agent writes/edits a formula in the Phase-5 grammar. Anchored to the corpus hit only on variant 1; afterwards driven by the Judge's edit motif. | agent |
| 7 | `prefilter` | Free, code-only checks before spending a real backtest: does it parse, is it too complex (node/depth/free-param caps), is it an exact zoo duplicate, is it an exact repeat of a formula already tried, does it even evaluate against the price panel. Routes to `code` again (repair/repeat), `tier1` (ok), or `reflect` (reject). | code |
| 8 | `tier1` | Backtests the candidate on **VAL_A only** and records it to the ledger as `counts_as_trial=1`. Tracks the best-so-far variant by pre-registration-oriented RankIC. | code (spends a trial) |
| 9 | `judge` | `judge` agent looks at the Tier-1 metrics and either says "promote" (this variant is good enough) or returns an edit motif for the next `code` iteration. | agent |
| -- | `force_decision` | If the 20-variant cap is hit before the Judge promotes, this node forces the decision: promote the best viable variant seen, or reject outright if none was ever viable. This is the hard stop that keeps a noisy family from manufacturing significance by trying a 200th variant (best-of-200 pure noise would show t ~ 3.26). | code |
| 10 | `freshfold` | The single promoted variant is confirmed on **VAL_B**, which no variant in this thesis has touched before. `ctx.mark_promote()` is called immediately before the first VAL_B call and the run asserts no VAL_B backtest ever precedes it. Requires the oriented RankIC to still be positive and `\|t\| >= 1.5`. | code (fresh-fold confirmation) |
| 11 | `tier2` | Orthogonalizes the signal against the existing accepted "book" and backtests both the raw and the cost-adjusted residual signal on VAL_A. Logs a second `counts_as_trial=1` ledger row (the finalist trial). | code |
| 12 | `gate_b_novelty` | **Runs before statistics, always.** Computes marginal IC versus the book; rejects if the candidate adds no new information (a clone) or if the realized sign disagrees with the pre-registered sign (a thesis failure -- hard reject regardless of statistics). Novelty is free; it is checked first so a doomed candidate never spends... | code (Gate B, part 1) |
| 13 | `gate_b_stats` | ...the one thing Gate B statistics costs: an irreplaceable **holdout peek** (rationed, `HOLDOUT_PEEK_BUDGET=12` total). Runs DSR, PBO, and the walk-forward check via `gates.gate_b()`. | code (Gate B, part 2) |
| 14 | `gate_c_redteam` | `redteam` agent selects which of the eleven falsification tests to run (five always run regardless); `redteam.run_redteam()` executes them plus the generation's mandatory curriculum-regime slice. Any failure is a reject. | agent + code (Gate C) |
| 15 | `emit_card` | Writes the accepted Alpha Card to `artifacts/cards/`, validates its schema, and adds the signal to the book so future generations' novelty checks see it. | code |
| 16 | `reflect` | `reflection` agent updates the bandit (which family paid off) and the lesson store from this generation's outcome, whatever it was. A rejected-but-coded candidate is still saved as a `(reject)` card for audit. Terminal node -- returns to the outer loop. | agent |

Any reject at any gate routes directly to `reflect`, skipping every node
after it -- a thesis that fails Gate A never reaches the Coder; a formula
that fails the pre-filter never spends a Tier-1 trial.

### Three things that are structurally enforced, not just conventions

1. **Variant cap <= 20 per thesis.** Counted by `variant_count`, hard-capped
   in `_route_after_code` / `_route_judge` / `_route_prefilter`, and every
   run asserts `max_variant_count() <= 20`.
2. **Fresh-fold confirmation never touches VAL_B before a promote.** The
   `_BacktestInstrument` context manager wraps `backtester.backtest` for the
   whole run and records every call's split; `RunResult.val_b_before_promote()`
   asserts no thesis's VAL_B call precedes its own promote event.
3. **Gate B ordering: novelty before statistics, always.** `gate_b_novelty`
   and `gate_b_stats` are separate graph nodes, called in that fixed order;
   `RunResult.novelty_always_before_stats()` asserts it from the recorded
   event log.

### Improvement mechanisms (the loop is graded on "does it improve")

- **Curriculum** (`curriculum_regimes`): every `curriculum_every`
  generations (default 3), the red-team's mandatory regime slice rotates
  `bear -> highvol -> volatile -> bull`, so later generations face a harder
  mandatory stress than earlier ones.
- **FDR auto-tightening** (`maybe_tighten_gates`): a rolling window of the
  last 6 accepted cards' holdout false-discovery rate is tracked; if it
  exceeds 0.33, `T_STAT_BAR` and the marginal-IC floor are each raised one
  fixed step and the change is logged to the run report.

### Stop rules (outer loop, whichever fires first)

1. **Token budget exhausted** -- a `BudgetExhausted` exception from any
   agent call. The current generation's state is checkpointed and the run
   ends with `status="paused_budget"`, resumable the next day (the Groq free
   tier supports only ~20 theses/day, per `PRE_BUILD_TASKS.md` T3).
2. **Diminishing returns** -- `stop_k` (default 3) consecutive generations
   each adding less than `stop_epsilon` (default 0.001) novelty-adjusted
   marginal IC.
3. **`max_generations`** reached (hard cap, default 20 when calling
   `run_loop` directly).

### Checkpointing and resume

`SqliteSaver` (in `src/loop.py`) is a LangGraph checkpointer backed by
plain stdlib `sqlite3` (chosen specifically to avoid
`langgraph-checkpoint-sqlite`'s `sqlite-vec` dependency, which this project
disallows as a vector-search library). It mirrors LangGraph's own
checkpoint state to disk after every write, and separately persists the
**outer loop's** state (generation counter, gate thresholds, accepted card
ids, token budget spend) in the same file via `save_run_state` /
`load_run_state`. Passing `resume=True` to `run_loop()` continues from the
last saved generation instead of starting over.

Portfolio combination (`portfolio_combine`) is deliberately **not** a graph
node -- it runs once, after the outer loop terminates, over the full
accepted book (inverse-correlation-weighted combination of all accepted
signals).

### How to run it

Use the CLI -- see [Quick start](#quick-start-running-the-main-loop-end-to-end)
above for the full flag reference. Short version:

```
python -m src.loop --smoke                             # no setup needed: mock + synthetic + sandbox
python -m src.loop --mode live -n 10 --run-id live_1    # real run against data/prices, data/universe, data/panel
```

The CLI loads `.env` for `GROQ_API_KEY` automatically, fails fast if
`--mode live` is requested without a key, and writes its checkpoint to
`artifacts/<run-id>/ck.db` and its Markdown report to `reports/<run-id>.md`
by default (per-generation table, pre-registration log with hashes,
portfolio result, event-log tail).

To drive it from Python instead -- e.g. for a custom `price_panel` or to
wire in your own `Memory`/`Ledger` instances -- call `run_loop()` directly,
which is what `main()` in `src/loop.py` does under the hood:

```python
from src.loop import run_loop
from src.memory import Memory
from src.ledger import Ledger

result = run_loop(
    run_id="my_run",
    max_generations=10,
    memory=Memory(),                 # data/memory.db + data/lessons.db etc.
    ledger=Ledger("data/ledger.db"),
    llm_mode="live",                 # or "mock" / "offline"; needs GROQ_API_KEY if "live"
    checkpoint_path="artifacts/my_run/ck.db",
    report_path="reports/my_run.md",
)
print(result.status, result.accepted_card_ids, result.n_trials)
```

`price_panel=None` (the default) loads `data/prices/ohlcv.parquet` plus
delivery/size-proxy/sector data automatically; pass
`price_panel=synthetic_price_panel(...)` (or the CLI's `--synthetic`) to run
entirely on synthetic data with no dependency on P1-P3 having produced real
artifacts.

Tests:

```
./.venv/Scripts/python.exe -m pytest tests/test_p10_loop.py -q
```

## P11-P13 (demo run, evaluation, slides)

### P11 -- Demo run and bad examples

`reports/p11_live_explore_report.md` is a real `run_loop()` invocation
(`run_id="live_explore"`) against the built data artifacts, run the same way
as the "How to run it" example above with `llm_mode="live"`. In that run all
three generations were honestly rejected at the fresh-fold step (VAL_B did
not confirm) -- reported as-is per the project rule that a system which
rejects everything is itself a finding, not something to paper over. The
three-bad-examples write-up planned for this phase (data / statistics /
economics failure modes, each caught by a different mechanism) is described
in `PHASE_PROMPTS.md`'s P11 section; consult that plus `reports/p9_handoff.md`
and `reports/p1_universe_report.md` for the underlying evidence.

### P12 -- System evaluation and ablation

Planned deliverable: `src/evaluation.py` plus `reports/p12_system_evaluation.md`,
grading the gates themselves (an LLM-free ~40-factor pool with known ground
truth -- predictive / noise / overfit / leaky -- run through each gate on and
off, reporting catch rate, false-kill rate, and headline FDR per gate) and a
fake-learning-detection check (do rejection *types* mature over generations
while total rejection volume stays flat). Not yet built in this checkout --
see `PHASE_PROMPTS.md`'s P12 section for the exact spec if resuming this work.

### P13 -- Slide deck

`slides/deck.html` (also exported as `slides/Alpha Factory Deck.pdf`) and
`slides/mc_variant_table.py` (a supporting table generator). Details and
every measured value behind each slide are in `reports/p13_handoff.md`.

## Dashboard

A local, read-only Streamlit app that explains and lets a reviewer explore
the whole system without touching `data/` (it only writes its own cache,
`data/dashboard/`). It never calls a paid API or a live LLM. Full detail in
`dashboard/README.md`; summary here.

```
./.venv/Scripts/python.exe -m pip install -r requirements-dashboard.txt
./.venv/Scripts/python.exe dashboard/build_cache.py     # precompute aggregates, < 90s
./.venv/Scripts/python.exe -m streamlit run dashboard/Home.py
```

`dashboard/build_cache.py --heavy` additionally runs the two expensive
builders (`zoo_leaderboard`, a network-hitting yfinance cross-check).
`dashboard/build_cache.py --list` prints the live builder registry;
`--check` verifies every cached parquet against its declared schema and
flags staleness.

Build status in this checkout: phases D0-D3 are complete (scaffold, cache
builders, `Home.py`, the Universe/Prices/Feature-Panel pages); see
`reports/dash_p0_handoff.md` through `reports/dash_p3_handoff.md`.
`tests/test_dash_p4_tooling.py` exists for the in-progress D4 work
(Backtester / Operators-and-Zoo pages).

```
./.venv/Scripts/python.exe -m pytest tests/test_dash_p0_scaffold.py tests/test_dash_p1_cache.py tests/test_dash_p2_home.py tests/test_dash_p3_data.py -q
```

## Running the test suite

Every stage's tests, plus the full suite, run offline with `LLM_MODE=mock`
(the default) and no network:

```
./.venv/Scripts/python.exe -m pytest -q
```

On Windows, prefix with `PYTHONUTF8=1` if you hit console-encoding errors
from non-ASCII characters in test output:

```
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest -q
```
