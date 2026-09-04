# DASHBOARD PHASE PROMPTS — copy-paste briefs for executing agents

> **How to use.** Give **PROMPT 0** to any agent as its first message (it orients them). Then give the
> single phase prompt for the phase you want built. Each phase prompt is self-contained: the agent does
> **not** need to know how any other phase was implemented, only the contracts in **Section 0 of
> `DASHBOARD_PLAN.md`**.
>
> **Order:** `D0` first (blocks all). Then `D1` and `D2` in parallel. Then `D3`–`D7` fan out (up to 5
> agents in separate sessions). `D8` last.
>
> **Minimum viable path** (time-boxed): `D0 → D1 → D2 → D3 → D5 → D7 → D8`.
>
> **Note:** phases D3–D7 each build 2–4 page files. That is deliberate — the pages in a phase share a
> data source and a chart vocabulary. Build and commit them one at a time; report acceptance per page;
> a partial pass ("Universe done, Prices has an open issue") is fine.

---

# PROMPT 0 — orientation (give this first, to every dashboard agent)

```
You are building one phase of a LOCAL WEB DASHBOARD for a quantitative research system. The system —
an AI-agent loop that invents, tests and filters stock-market alpha signals — is already built and
signed off through Phase 10 (see reports/p0_handoff.md .. reports/p10_handoff.md). Your job is to build
one phase of the DASHBOARD that visualises and explains it. The dashboard design is frozen.

## Build state — read this, it changes what you build

P0-P10 are DONE. P10 is the orchestration loop (src/loop.py) — so 10_The_Loop.py is a LIVE DATA PAGE
reading data/loop_checkpoint.db, NOT a "pending" placeholder. P11 (demo run, bad examples) and P12
(system evaluation) are BEING BUILT RIGHT NOW, in parallel with you, by other agents.

That means:
- Artifacts you read may appear, grow or be mid-write while you work: data/ledger.db, data/memory.db,
  data/lessons.db, data/bandit_state.json, data/loop_checkpoint.db, artifacts/cards/*.json,
  reports/p11_*, reports/p12_*.
- NEVER hard-code a phase-status list ("P0-P9 done"). Derive status by globbing reports/p*_handoff.md.
- NEVER copy a value out of src/config.py into your code or your prose. Read it at render time.
  config.py was re-verified against the live Groq API on 2026-09-04 and may change again.
- OBEY DASHBOARD_PLAN.md Section 0.8.1 (concurrency) exactly. It is load-bearing, not defensive
  polish: opening a live project .db directly can stall or crash a running P11 loop. Every .db read
  goes through data._readonly_sqlite (snapshot-then-open). load_bandit tolerates a truncated JSON.
  load_cards skips a card that fails json.load or validate_card.
- Your dashboard NEVER runs the loop (src.loop.run_loop), never writes a project artifact, and never
  spends a holdout peek. Page-triggered gate runs use Ledger(":memory:") AND do_holdout_peek=False.

## Files, and what each is for

| File | Role | Read it? |
|---|---|---|
| `DASHBOARD_PLAN.md` | THE build spec for the dashboard. Single source of truth. | MANDATORY — Section 0 in full, then ONLY your assigned phase |
| `IMPLEMENTATION_PLAN.md` | The spec for the SYSTEM the dashboard shows. | Section 0 (contracts, the data split, the AlphaCard schema) + the phase matching whatever you are visualising |
| `FLOW_EXPLAINED.md` | Plain-English walkthrough of the whole system, every term defined. | Read the parts your page explains — it is the source for the narrative blocks |
| `reports/p<N>_handoff.md` | What each system phase actually produced, with measured values. | Read the ones for the data/artifacts your page reads |
| `PHASE_PROMPTS.md` / `INITIAL_PLAN.md` / `PLAN_EXPLAINED.md` | System build briefs + architecture + decision record. | Reference only |

## The stack (frozen — see DASHBOARD_PLAN.md Section 0.2 and 0.11)

- Streamlit multipage app. Python 3.11+, Windows.
- Allowed NEW deps, complete list: streamlit, plotly, altair, graphviz (python binding). Everything in
  the project's requirements.txt is also available. New deps go in requirements-dashboard.txt.
- NOT allowed: any React/Next frontend, any API server, any DB server, Docker, a vector DB, a paid API,
  a paid data source, a LIVE LLM CALL. No network on a page load.

## Rules that apply to every phase

- Your phase spec is a contract. Build exactly the files, function signatures and cache-file schemas it
  names (DASHBOARD_PLAN.md Section 0.4 and 0.6). Other phases depend on those names.
- If a cache file or a data artifact does not exist yet, use dashboard/lib/fixtures.py
  (fake_cache / fake_cards) — build and test against fixtures. Do NOT block waiting on another phase.
- Pages import from dashboard/lib/*, NEVER from src/* directly. The ONE exception is dashboard/lib/
  engine.py (the bridge to the backtester/gates/redteam). Two pages
  (05_Operators_and_Zoo, 08_LLM_Agents) may also import src.operators / src.ast_tools / src.zoo /
  src.config / src.agents for metadata and parsing only — never constructing a live LLM client.
- One page file = one sidebar entry. Even when your phase builds several pages, do not put two tabs in
  one .py file.
- Every page: st.set_page_config(layout="wide") then ui.page_header(...). Every chart gets one sentence
  of context before it and ui.source_note(...) after it. Colours come from charts.PALETTE — no inline
  hex. Prose over 3 lines comes from narrative.block(...).
- A page whose required data is missing calls ui.data_missing(...) then st.stop(). It must NEVER raise
  a traceback on a fresh clone.
- No page reads ohlcv.parquet / features.parquet / labels.parquet in full — use the sliced lib/data
  loaders (pyarrow filters).
- Any red-team / gate run triggered from a page uses src.ledger.Ledger(":memory:") — never
  data/ledger.db — and passes do_holdout_peek=False to gate_b.

- The dashboard writes ONLY to data/dashboard/ and reports/dash_*. Never to data/panel, data/prices,
  data/universe, data/*.db, or artifacts/.
- HOLDOUT (2022-07-01 onward) is sealed. No page may backtest on split="holdout";
  lib/engine.run_backtest must reject it.
- Determinism: seed numpy/random with src.config.RANDOM_SEED anywhere you sample.
- Performance: any page cold-loads in < 3s given a built cache. build_cache.py (cheap pass) < 90s.

## FIVE src/ CONTRACTS AN EARLIER DRAFT OF THE PLAN GOT WRONG — do not trust memory, these are fixed

1. run_redteam(signal, tests=None, *, split=..., liquidity_ranks=..., ledger=..., prices=..., ...)
   `split` is KEYWORD-ONLY; the 2nd POSITIONAL is `tests`. run_redteam(sig, "val_a") silently passes
   the split as a test list. Always use keywords. Pass liquidity_ranks= or test 11 degrades to a no-op.
2. lineage_path is a METHOD, not a module function: Memory(...).lineage_path(card_id).
   `from src.memory import lineage_path` raises ImportError.
3. AGENT_ROLES lives in src.config, NOT src.agents.
4. walk_forward(signal, start, end, ...) takes DATES, not a split name. Map with config.SPLITS[region].
5. liquidity_ranks.parquet columns are month_end, symbol, liquidity_rank, trailing_turnover —
   NOT 'date'/'rank'/'turnover'.

Also: FLOW_EXPLAINED.md HAS NO PART 3. Its parts are 0,1,2,4,5,6,7,8,9,10. The P(best-of-N noise t>3)
table is in PART 2; the five-failure-modes table is in PART 6.

## EVERY PHASE IS HUMAN-VERIFIED BEFORE THE NEXT BEGINS

Read DASHBOARD_PLAN.md Section 0.10. Your phase is done when the OWNER has run it and said so — not
when the code runs. Finish by writing reports/dash_p<N>_handoff.md using the template there:
what you built · every acceptance criterion WITH A MEASURED VALUE OR A SCREENSHOT PATH (per page, for a
multi-page phase) · exact commands the owner runs to verify · what you could not verify · failures and
open issues · anything that contradicts this plan · every judgement call the plan left open.

Hard rules: never write PASS without the number/screenshot that proves it. Report failures honestly.
Never fabricate a number or a screenshot. Do not start the next phase — stop and wait for sign-off.
Save screenshots to reports/dash_shots/.
```

---

# PHASE PROMPTS

## D0 — Scaffolding and shared contracts  *(do this first; it blocks everything)*

```
Execute PHASE D0 from DASHBOARD_PLAN.md.

Build the dashboard/ tree, .streamlit/config.toml, requirements-dashboard.txt, dashboard/README.md
skeleton, and tests/test_dash_p0_scaffold.py.

The load-bearing deliverables are the lib/ module CONTRACTS in Section 0.4 — every other phase codes
against these signatures:
- lib/ui.py and lib/fixtures.py: FULLY implemented. fixtures.CACHE_SCHEMAS must cover EVERY file in
  Section 0.6, and fake_cache(name) must return exactly those columns for every one of them.
- lib/data.py: the cache layer (load_cache, try_cache, cache_manifest, available) fully implemented;
  the project-data readers implemented with SLICED / columnar pyarrow reads — assert no reader ever
  pulls the full ohlcv/features/labels parquet into pandas.
- lib/charts.py: PALETTE, TEMPLATE, and every builder implemented and theme-consistent. coverage_chart
  must really fit an OLS trend line (numpy.polyfit) and return (Figure, {'slope_per_year', 'verdict'})
  where verdict is 'FLAT' if |slope| < 3 names/year else 'SLOPING'.
- lib/flow.py and lib/narrative.py: signatures + complete name tuples (DIAGRAMS, BLOCKS); render()/
  block() raise NotImplementedError(name) for un-done names (NOT AttributeError). Implement only
  flow.region_dates() (from src.config.SPLITS).
- lib/engine.py: ensure_panel() fully implemented (load data/panel/*, call backtester.use_panel,
  return False cleanly if absent); dsr() and expected_max_sr() as thin passthroughs to src.gates;
  run_backtest() must at minimum implement the split=="holdout" rejection; the rest raise
  NotImplementedError.

build_cache.py: a @builder(name) registry + main() with --only <names>, --heavy, --check, --list, plus
a _manifest.json writer. Fully implement TWO reference builders: corpus_family_counts and
agents_token_budget (both cheap, no heavy source).

Only lib/engine.py may import from src/. Only data/dashboard/ is a new write path.

Finish by writing reports/dash_p0_handoff.md per Section 0.10. Then STOP.
```

## D1 — Cache builder (the data-prep layer)

```
Execute PHASE D1 from DASHBOARD_PLAN.md.

Implement every CHEAP builder in Section 0.6 into data/dashboard/*.parquet + a populated _manifest.json.
LEAVE zoo_leaderboard and prices_yf_crosscheck as status:"no_source" unless --heavy (D4 and D3 own the
"compute now" fallbacks).

Why this phase exists: ohlcv.parquet is ~4.9M rows and features.parquet ~539k. Reading either per page
is too slow. Precompute the small aggregates ONCE; pages then read a few-thousand-row parquet
instantly.

Each @builder: read its sources with sliced/columnar reads, compute, ASSERT the output matches
fixtures.CACHE_SCHEMAS[name], return the frame. If a source artifact is missing, write an EMPTY
schema-correct frame and set status:"no_source" — never raise.

Care points:
- universe_daily_coverage: n_panel = |members(D) ∩ symbols-that-traded(D)|. Report its 2015→2025 linear
  trend (names/year). If it slopes, that is a finding about P1/P2 — say so in the handoff, do not "fix"
  it here.
- panel_feature_ic: daily Spearman of each feature vs fwd_ret_h_demeaned for h in {1,2,3,5,10,21}; mean
  + t-stat over days. Reuse src.backtester._daily_ic or src.gates.daily_rank_ic if callable standalone;
  else a local Spearman — document which.
- panel_feature_ic_shift: recompute at h=1 with the feature panel shifted +1 trading day. base and
  shift1 MUST differ (that is P3's look-ahead self-test surfaced here).
- panel_leaky_check: RankIC of fwd_ret_1 predicting itself (expect ~1.0).
- prices_extreme_returns: every |adjusted daily return| > 0.5; tag explained_by if a corporate action
  is within +/-1 day.
- Determinism: seed once; re-running must produce byte-identical (or stable-sorted identical) parquets.

Cheap pass must complete in < 90s — report the measured time. --check must pass.

Finish by writing reports/dash_p1_handoff.md per Section 0.10. Then STOP.
```

## D2 — Home page, the six flowcharts, the narrative library

```
Execute PHASE D2 from DASHBOARD_PLAN.md.

Build dashboard/Home.py and FULLY implement lib/flow.py (all 6 DIAGRAMS + data_regions_timeline) and
lib/narrative.py (all BLOCKS). D5 and D7 call these — they are the reusable diagram/prose layer.

The six diagrams (graphviz.Digraph or DOT string that st.graphviz_chart accepts):
- pipeline: the 9 stages S1..S9 + the 4 gates + the "reject -> Memory" edges (FLOW_EXPLAINED Part 2).
- loop_graph: the P10 LangGraph state machine (IMPLEMENTATION_PLAN Phase 10) — the inner judge->code
  loop labelled "<= 20 / thesis", freshfold on VAL_B, gate_b_novelty -> gate_b_stats, gate_c_redteam,
  emit_card, reflect -> should_continue.
- gate_b: orthogonalize -> novelty -> statistics(DSR/t/PBO on the RESIDUAL) -> rationed holdout peek,
  with the "novelty is free, a peek is 1 of 12" annotation.
- data_lineage: raw NSE bhavcopy + CA API -> ohlcv.parquet -> {membership, features/labels} ->
  backtester -> gates+redteam -> Alpha Cards + ledger + book.
- phase_dag: P0->P2->P1->P3->P4->P6->P10->P11->P13 with the P5/P7/P8/P9 parallel branch; colour each
  node done/pending from the actual reports/ contents.
- card_lifecycle: an Alpha Card as a stack of sections, one added per stage.

data_regions_timeline(): a Plotly horizontal bar per region from src.config.SPLITS, coloured by role
(warm-up / search / confirm / sealed), "12 counted peeks" note on HOLDOUT.

Narrative blocks: write each from the source docs — quote/condense, do NOT invent, and end every block
with a "_Source: <doc> <section>_" line. five_failures and sqrt_2lnN return Markdown TABLES with the
measured numbers (FLOW_EXPLAINED Part 3 and Part 6). sqrt_2lnN must contain the measured
P(best-of-N noise t>3) table verbatim: 5->0.7%, 20->2.7%, 100->12.6%, 200->23.6%, 500->49.1%.

Home.py sections in the order listed in the phase spec — the one-liner, a Key Numbers KPI row (universe
200, date span, #features, #operators, len(ZOO), len(corpus), 11 red-team tests, tokens/thesis, tests
passing), the pipeline chart, card_lifecycle, data_regions_timeline, the five-failures table, three
budgets, sqrt_2lnN, the sign / cap+fresh-fold / gate-B-order blocks, the walkthrough, novelty claims,
weak points, and the BUILD STATUS board (phase_dag + a table of each handoff's headline pass count).

Home.py cold-loads in < 3s. Do NOT compute anything from data/ here — the key-numbers row reads only
cheap counts and src.config.

Finish by writing reports/dash_p2_handoff.md per Section 0.10. Then STOP.
```

## D3 — Data pages: Universe, Prices, Feature Panel

```
Execute PHASE D3 from DASHBOARD_PLAN.md.

Build THREE pages + one test file:
- dashboard/pages/01_Universe.py
- dashboard/pages/02_Prices.py
- dashboard/pages/03_Feature_Panel.py
- tests/test_dash_p3_data.py

All three read the D1 caches (universe_*, prices_*, panel_*) and do SLICED reads of the big parquets
only for the per-symbol drill-downs. Missing cache -> ui.data_missing(...) naming the exact build_cache
command, then st.stop(). Build and commit one page at a time; report acceptance per page.

01_Universe.py — prove the universe is survivorship-free, point-in-time, flat at ~200. Sections:
1. THE DECISIVE COVERAGE CHART — charts.coverage_chart(universe_daily_coverage, target=200): n_panel
   per day, the constant-200 reference line, the fitted OLS trend, a prominent FLAT/SLOPING verdict +
   the slope in names/year. "An upward slope would mean survivorship bias survived P1 — a hard stop."
2. Liquidity floor (turnover_cutoff_200, median_turnover). 3. Monthly churn (churn_pct, band 2-5%).
4. Canary Gantt — DHFL, RCOM, JPASSOCIAT, YESBANK, SUZLON, IDEA, each ENDING when the company stops
   trading. "Nothing in the pipeline ever asks 'does this company still exist?'"
5. Heavyweight Gantt — RELIANCE, TCS, SBIN, TATASTEEL, MARUTI, ONGC — in for most of the period.
6. Sector composition (stacked area; labels are current, not point-in-time — disclosed).
7. Index overlap (universe_overlap). "We call this 'the 200 most liquid Indian equities, reconstructed
   point-in-time from NSE daily bhavcopy', NOT 'NIFTY 200'."
8. Membership explorer (date -> the 200 names + turnover rank; symbol -> intervals).
9. (optional, behind a button) live src.universe.lookahead_check truncated at 2020-01-01.

02_Prices.py — coverage, the CA adjustment, delivery data, data quality. Sections:
1. Coverage by year (covered_pct, n_symbols). 2. Corporate actions (prices_ca_counts stacked bar +
   table; "a 1:10 split reads as -90% until corrected; demergers flagged not attempted").
3. Extreme returns (prices_extreme_returns table + count bar; "not winsorized").
4. Source eras (bhavcopy_legacy -> 2019-09-27, then sec_bhavdata_full). 5. Delivery availability
   ("NaN before ~2020, disclosed"). 6. VWAP sanity gauge (low <= vwap <= high, target ~100%).
7. Quality board (close<=0, high<low, negative volume — each should be 0, as pills).
8. yfinance cross-check — histogram if the cache has data, else ui.pending_banner + a "compute now
   (--heavy)" note. NEVER call yfinance on load.
9. Per-symbol candlestick from a SLICED load_ohlcv(symbols=[sym]) + CA markers + raw/adjusted toggle.

03_Feature_Panel.py — the ten features, their signal, the look-ahead self-tests. Sections:
1. The ten features reference table. 2. Distributions (violin/box, by-year toggle).
3. Correlation heatmap. 4. Cross-section size line (reference at 100).
5. Raw feature IC bar with a noise band — "the fixture plants one feature at IC ~ 0.04, you should see
   it stand out". 6. IC decay multi-line across h in {1,2,3,5,10,21}.
7. THE LOOK-AHEAD SELF-TEST — panel_feature_ic_shift: base vs shift1 RankIC per feature. "If a
   feature's IC were invariant to a one-day shift the pipeline would be leaking. It is not."
8. THE LEAKAGE-DETECTOR SANITY CHECK — panel_leaky_check: fwd_ret_1 predicting itself -> IC ~ 1.0.
9. NaN coverage heatmap (delivery_pct dark before ~2020). 10. Label distributions (raw vs demeaned).
11. Per-symbol feature series (sliced read).

A test must assert 02_Prices never calls load_ohlcv with no filter and never hits the network on load.
Do NOT read ohlcv/features/labels whole. Do NOT recompute the universe or ICs on load. Do NOT call it
"NIFTY 200". Do NOT winsorize extreme returns.

Finish by writing reports/dash_p3_handoff.md per Section 0.10 (acceptance PER PAGE). Then STOP.
```

## D4 — Formula tooling: Backtester + Operators & Zoo

```
Execute PHASE D4 from DASHBOARD_PLAN.md.

Build TWO pages + implement two engine helpers + one test file:
- dashboard/pages/04_Backtester.py
- dashboard/pages/05_Operators_and_Zoo.py
- dashboard/lib/engine.py: eval_formula, run_backtest
- tests/test_dash_p4_tooling.py

engine.ensure_panel() wires data/panel/* into src.backtester.use_panel. Panel absent -> data_missing.

04_Backtester.py:
1. The interface — a table of the backtest(...) switches + the Metrics dict shape (IMPLEMENTATION_PLAN
   Section 0.5). "One engine, called from eight places downstream."
2. The runner — formula (a src.zoo.ZOO dropdown OR free text), split in {train,val_a,val_b,train+val_a}
   (NEVER holdout — run_backtest must reject it), horizon, cost_bps, neutralize. On Run: eval_formula
   -> run_backtest -> a KPI row + charts.decay_curve(metrics["decay"]) + charts.equity_curve(...) +
   the realised sign.
3. Purge/embargo visualiser — which training rows near a test boundary are dropped; count from
   purge_embargo_mask.
4. THE ACCEPTANCE-EVIDENCE BOARD — run live: random noise -> |rank_ic|<0.01, |t_stat|<2; a signal and
   its negation -> rank_ic flips sign exactly; engine.leaky_signal() (fwd_ret_1) -> rank_ic>0.9;
   cost_bps in {0,5,15,30} -> sharpe monotonically decreasing.
5. Cache every run (@st.cache_data); spinner on first compute; second run of the same inputs < 200ms.

05_Operators_and_Zoo.py (may import src.operators / src.ast_tools / src.zoo directly):
1. Operator catalog — grouped (cross-sectional / time-series / element-wise), causality callout: "every
   operator is CAUSAL — no operator reaches forward. Formula-level look-ahead is structurally
   impossible, not hopefully caught." (FLOW_EXPLAINED S5.)
2. Causality evidence — changing a FUTURE input value leaves earlier outputs unchanged.
3. The zoo — a sortable table of src.zoo.ZOO (name, source, formula, complexity). Alpha #56 skipped.
4. AST viewer — pick a formula -> render src.ast_tools.parse(formula) as a graphviz tree.
5. Formula sandbox — parse(formula, strict=True): accept/reject, then canonical, fingerprint,
   complexity, and a one-number signal preview via engine.eval_formula + a quick RankIC. Handle
   ParseError cleanly.
6. Parser-rejection demo — __import__('os'), close.values, [x for x in y], lambda x: x — each refused.
7. Duplicate detection — src.zoo.is_zoo_duplicate; a pre-filled commuted-operands example (a*b -> b*a)
   that still matches. "A known published alpha in disguise is, by definition, crowded."
8. Zoo IC leaderboard — from the zoo_leaderboard cache if present; else a "Compute now" button that
   runs the --heavy builder inline with a progress bar.

run_backtest(split="holdout") must raise — test it. The sandbox must NEVER eval anything outside
src.ast_tools.parse. Do NOT add or modify an operator. Do NOT implement DSR/PBO here (D5).

Finish by writing reports/dash_p4_handoff.md per Section 0.10 (acceptance PER PAGE). Then STOP.
```

## D5 — Honesty machinery: Gates & Ledger + Red-Team

```
Execute PHASE D5 from DASHBOARD_PLAN.md. This is the densest phase — report acceptance per page.

Build TWO pages + implement two engine helpers + one test file:
- dashboard/pages/06_Gates_and_Ledger.py
- dashboard/pages/09_Red_Team.py
- dashboard/lib/engine.py: run_redteam_ui, leaky_signal
- tests/test_dash_p5_honesty.py

Uses src.gates, src.ledger, src.redteam, and flow.render("gate_b") / narrative.block from D2 (code
against the NotImplementedError stubs if D2 is not done yet).

06_Gates_and_Ledger.py:
1. Gate B order — flow.render("gate_b") + narrative.block("gate_b_order"). "Novelty is free; a holdout
   peek is 1 of 12 for the system's lifetime."
2. THE OVER-SEARCHING EXPLAINER — an N slider (2..1000). Three curves: sqrt(2 ln N) ceiling, realised
   E[max] (seeded Monte-Carlo, cached), Bailey-LdP E[max SR] via src.gates.expected_max_sharpe. Below
   it, the measured P(best-of-N noise t>3) table (5->0.7%, 20->2.7%, 100->12.6%, 200->23.6%,
   500->49.1%) with the slider's N highlighted.
3. DSR CALCULATOR — sliders (observed Sharpe, n_trials, sr_std, skew, kurtosis, T) -> engine.dsr(...).
   Pre-load: best-of-200-noise, t ~ 2.74 -> DSR ~ 0.477 -> REJECT; a real signal found in 5 trials,
   t ~ 7 -> DSR ~ 0.995 -> PASS.
4. Effective trial count — 20 knob-variants of one shape (vol / ts_mean(vol,k), k=5..25) ->
   src.gates.effective_trial_count ~ 2, next to raw N=20. "Deflated by the effective count, not raw N,
   scoped run-wide."
5. PBO — src.gates.cscv_pbo on a noise matrix (~0.5) and a planted signal (low).
6. Walk-forward — pick a ZOO formula -> src.gates.walk_forward over train+val_a -> the sequential OOS
   IC series + per-fold table. NOTE: walk_forward takes DATES, not a split name — use
   start, end = config.SPLITS["train"][0], config.SPLITS["val_a"][1]. There is no split= parameter.
7. THE TRIAL LEDGER — ledger_summary cumulative-count line; a filterable Ledger().trial_records()
   table. If near-empty (likely), SAY SO + show a fixture preview.
8. Holdout peeks gauge (used / HOLDOUT_PEEK_BUDGET) + the peek log.
9. Append-only guarantee — run src.ledger.assert_no_row_removal_sql() live -> "no DELETE in ledger.py:
   PASS".
10. Thresholds table — T_STAT_BAR 3.0, MIN_MARGINAL_IC 0.01, DSR_MIN 0.95, PBO_MAX 0.50,
    MIN_DSR_SAMPLE 60.

09_Red_Team.py:
1. The menu — all 11 (#, name, what it hunts, DECISIVE (1,2,4,5,10) vs diagnostic). "The agent picks
   which attacks fit; the attacks are pre-written parameterised backtests. It never writes code."
2. The survive rule — killed iff any decisive test flags; consistent sign in >= 70% of folds (test 10).
   The 5 decisive tests always run.
3. Rejection-only — "All 11 can only kill, never promote. Every red-team backtest is logged
   counts_as_trial=0."
4. Regime definition — bull (63d > +5%), bear (< -5%), high-vol (top expanding tercile). "Expanding
   thresholds only — a full-sample volatility threshold is look-ahead."
5. The runner — pick a signal (a ZOO formula, "leaky (fwd_ret_1)", or "one-lucky-year") -> Run
   (engine.run_redteam_ui, ~1-2 min, spinner) -> a per-test pass/flag heatmap, verdict, failed_tests,
   flagged_diagnostics, baseline RankIC/t.
   CALL IT WITH KEYWORDS: run_redteam(sig, tests=None, split=split,
   liquidity_ranks=data.load_liquidity_ranks(), prices=..., ledger=Ledger(":memory:")).
   `split` is keyword-only and the 2nd positional is `tests`. Without liquidity_ranks= test 11
   (universe_edge) degrades to a no-op — the heatmap must show test 11 as genuinely run.
6. Evidence board (cached): leaky fwd_ret_1 killed by test 5 (baseline ~1.0 -> ~0.002); a
   one-lucky-year signal killed by test 1; a thin-edge high-turnover signal killed by test 4 (net
   Sharpe at 15bps < 0); a clean momentum ZOO formula survives all 11.

EVERY red-team run in this page MUST use src.ledger.Ledger(":memory:") — assert data/ledger.db is
never written. Do NOT read HOLDOUT. Do NOT re-implement a statistic — call src.gates. Do NOT let the
red-team page generate test code.

Finish by writing reports/dash_p5_handoff.md per Section 0.10 (acceptance PER PAGE). Then STOP.
```

## D6 — Memory + LLM Agents

```
Execute PHASE D6 from DASHBOARD_PLAN.md.

Build TWO pages + one test file:
- dashboard/pages/07_Memory.py
- dashboard/pages/08_LLM_Agents.py
- tests/test_dash_p6_memory_agents.py

Both pages are mostly non-interactive — they render what a store or a config already contains. The
memory stores are likely EMPTY (the loop has not run) — render the empty state honestly plus a fixture
example.

07_Memory.py (uses src.memory + data/memory.db, data/lessons.db, data/bandit_state.json):
1. The six stores — a diagram/table: formula index + card store + lineage (memory.db), lesson store
   (separate lessons.db), bandit (bandit_state.json), book (book.parquet). "Exact and semantic stores
   are physically separate — a multiple-testing count cannot be 'approximately right'."
2. Lesson store table (motif, parent_context, outcome, p_helps, confidence, n_observations, family,
   veto).
3. The guards — confidence gating (not a prior until n_observations >= 3) and the ASYMMETRIC, STICKY
   veto (n_obs >= 3 AND >= 2 high-confidence failures; successes never lift it). "confidence is
   reliability, not direction — a reliably-harmful motif has high confidence, low p_helps."
4. Second-order overfitting — "'momentum fails' after 3 failures + the Planner defunds momentum = an
   irreversible call on n=3, invisible because it never appears in a backtest." Defences: confidence
   gating + the exploration floor.
5. Bandit — BanditState.allocation() bar per family with a horizontal line at the 5% EXPLORATION FLOOR;
   last_k_deltas sparkline; n_pulls / cumulative_reward / tokens_spent table.
6. Lineage — pick a card -> Memory(...).lineage_path(card_id) [a METHOD, not a module function] ->
   the parent chain as a tree. Handle "0 cards"; render a fixtures.fake_cards(3) chain on demand.
7. The book — accepted factors + a pairwise correlation heatmap, if AcceptedBook is non-empty.

08_LLM_Agents.py (may import src.config + src.agents for METADATA ONLY — a test must assert it does NOT
import groq and does NOT call build_agents / get_client / any agent .run(); no network):
1. The eight agents — a table: role, tier (src.config.LLM_ROLE_TIER), model chain
   (src.config.LLM_MODEL_CHAINS), one line each, output schema keys, calls/thesis (from
   agents_token_budget). "Deterministic computations are NOT agents."
2. Model routing — the fallback chain, the startup probe, no hard-coded model ID. Provider: Groq;
   LLM_MODE=mock runs offline. DO NOT TYPE A MODEL ID INTO THIS PAGE — render every one from
   src.config.LLM_MODEL_CHAINS at run time. (An earlier draft named llama-3.1-8b-instant as the cheap
   tier; that model now 404s. A test greps this page for "gpt-oss"/"llama"/"qwen" and must find zero
   literal matches.) Tell the story instead: PRE_BUILD_TASKS T3 guessed, models.list() settled it on
   2026-09-04, three originally-planned IDs were already gone — which is the case for a probed
   fallback chain over a pinned model.
3. Token budget — agents_token_budget bar; ~16.6 calls, ~26,500 tokens/thesis, ~20 theses/day; TPM
   bucket + TPD counter + BudgetExhausted -> resumable checkpoint. ALSO render
   src.config.LLM_MODEL_LIMITS (per-MODEL measured TPM/RPD) — stronger evidence than the per-tier
   constants, and the reason the budget is modelled per model.
4. The pre-registered sign — a diagram: thesis -> canonical JSON -> sha256 -> timestamp (BEFORE any
   backtest) -> later check_sign(pre, realized); a mismatch is a THESIS FAILURE, not a sign flip.
5. Corpus browser — load_corpus() as a filterable table (family, tradeable_with_our_data toggle);
   click -> the full record. corpus_family_counts bar. "53 entries, 17 not tradeable."
6. Retrieval demo — a family + keyword box -> src.agents.retrieve(...) -> the returned entries.
7. Prompt viewer — a role dropdown -> src/agents/prompts/<role>.txt with the "=== DYNAMIC ===" split
   highlighted.

The table's tier for each role must equal what src.config.LLM_ROLE_TIER assigns — test it.
Do NOT write to any memory store. Do NOT construct a live LLM client.

Finish by writing reports/dash_p6_handoff.md per Section 0.10 (acceptance PER PAGE). Then STOP.
```

## D7 — Narrative & example pages: The Loop, Alpha Cards, System Evaluation, Bad Examples

```
Execute PHASE D7 from DASHBOARD_PLAN.md.

Build FOUR pages + one test file:
- dashboard/pages/10_The_Loop.py
- dashboard/pages/11_Alpha_Cards.py
- dashboard/pages/12_System_Evaluation.py
- dashboard/pages/13_Bad_Examples.py
- tests/test_dash_p7_narrative.py

SPLIT THIS PHASE. P10 is BUILT, P11/P12 are running in parallel right now:
  * BUILD NOW: 10_The_Loop.py (P10 is signed off — a live data page) and 13_Bad_Examples.py
    (needs only the supplied CSV + engine.leaky_signal + check_sign).
  * BUILD 11_Alpha_Cards.py AFTER P11 lands, and 12_System_Evaluation.py AFTER P12 lands — built
    against "0 cards" they are banners; built against real output they are the two most persuasive
    pages in the deck, for the same total effort.
  If you were told to build all four now, build 11/12 fixture-first exactly as specified below.

11/12 cover parts of the SYSTEM P11/P12 will fill in — full design content now, live data the moment
the artifacts appear. Uses flow.render / narrative.block from D2, and engine.eval_formula /
engine.run_backtest from D4 (for the Bad Examples demos — code against those two stubs, or start this
phase after D4).

10_The_Loop.py — NO pending banner. P10 is built and signed off (reports/p10_handoff.md); this page
reads data/loop_checkpoint.db through data.load_loop_run_state() / the loop_generations cache.
It NEVER calls src.loop.run_loop (a test greps for that and must find zero matches).
 1. flow.render("loop_graph") with node names that MATCH the routers in src/loop.py. Note the
    subtlety from p10_handoff §7: reflect -> should_continue -> orchestrate is the OUTER loop
    (run_loop), not a graph edge.
 2. The THREE ENFORCEMENT POINTS, constants read live from src.loop: variant cap (MAX_VARIANTS=20,
    the judge->code counter, force_decision when it trips; why — best of N noise ~ sqrt(2 ln N));
    fresh fold (search on VAL_A, one winner confirmed on VAL_B at FRESHFOLD_MIN_T, no holdout peek
    spent); Gate B ordering (novelty before statistics). State these are VERIFIED BY TEST — quote the
    measured values from reports/p10_handoff.md section 2 (cap hit exactly 20;
    val_b_before_promote() is False) and name the test proving each.
 3. Run summary KPI row: status, stopped_reason, generations, accepted card ids, n_trials, holdout
    peeks used/12, FINAL vs starting t_stat_bar and min_marginal_ic, token spend, state_digest.
 4. Per-generation table + charts from loop_generations: variant_count per gen with a line at 20 (does
    the cap bind?); REJECTION REASONS STACKED BY GENERATION (the fake-learning read: falling VOLUME =
    real improvement, same volume in new clothes = drift — say which this run shows, even if
    unflattering); the funnel theses -> gate A -> promoted -> fresh fold -> gate B -> gate C ->
    accepted.
 5. Curriculum rotation — curriculum_regimes(gen) / CURRICULUM_ROTATION vs the mandatory_regimes
    actually recorded. "The Planner cannot spend a whole run in the market it likes."
 6. FDR auto-tightening — plot rolling_fdr(generations) against FDR_TIGHTEN_THRESHOLD (0.33); mark
    every generation where the bar stepped up. "A control loop on the gate, not a fixed constant."
 7. The stop rule (budget exhausted -> checkpoint / STOP_K_DEFAULT flat generations / generation cap)
    — show which fired. Plus checkpoint-resume: why SqliteSaver exists (the ~20-thesis/day ceiling
    means a real run spans days), next_gen / incomplete_gen / last updated.
 8. PORTFOLIO COMBINATION (off-loop) — src.loop.portfolio_combine output: accepted-signal correlation
    heatmap, inverse-correlation weights bar, combined vs individual RankIC + beats_best_individual.
    Explain WHY it is off the main loop (Trexquant grades the signal, not the portfolio; "does this
    add new information?" is already Gate B's job). With < 2 accepted cards it returns
    status:"insufficient" — render that honestly. If P11 has landed, prefer
    artifacts/portfolio_report.md and show the regime-gated weights too.
 9. No run yet? Every design section still renders; data sections show the empty state plus a
    fixtures.fake_loop_generations() preview, clearly labelled fake.

11_Alpha_Cards.py: ui.pending_banner("Alpha Cards", "P11 (a run that produces a card)") BUT the page
must be fully functional the moment a card JSON
exists. The card schema walkthrough (IMPLEMENTATION_PLAN Section 0.5, every field). A gallery reading
artifacts/cards/*.json AND the AlphaCardStore index, best-effort validate_card, filterable by verdict /
thesis / generation. A detail view: thesis, pre-registered sign + hash, formula + AST tree, complexity,
tier1/fresh-fold/tier2 metrics, charts.decay_curve, the audit block, the red-team report, the lineage
chain, provenance.fields_used. If 0 cards: say so, and render fixtures.fake_cards(1) behind a "preview
with a sample card" toggle. A test must confirm: shows "0 cards" now, and renders a full detail view
(including the AST tree) when fixtures.fake_cards(1) is written to artifacts/cards/.

12_System_Evaluation.py: ui.pending_banner("System evaluation & ablation", "P12 (src/evaluation.py)") +
the metric definitions (Yield / Honesty=FDR / Efficiency) + the ABLATION TABLE format (per gate: catch
rate, false-kill rate, FDR on vs off; seeded pool ~10 predictive / 10 noise / 10 overfit / 10 leaky) +
the FAKE-LEARNING check (rejections per generation, per-gate pass rate over time, rejection-reason mix
— "improvement = falling error VOLUME; drift = the same volume in new clothes"). Placeholders visibly
labelled; render reports/p12_* if it appears.

13_Bad_Examples.py — three failure stories, each in three beats NAIVE RESULT -> THE SYSTEM CATCHES IT
-> THE FIX (IMPLEMENTATION_PLAN Phase 11 sec 2/3/4, FLOW_EXPLAINED Part 8):
1. DATA — the universe source was structurally broken. Naive: load the supplied constituent CSV (find
   it in the repo root or data/raw/); show it passes every superficial check. Caught: compute and show
   — N of today's NIFTY 200 heavyweights NEVER appear in it (name them: RELIANCE, TCS, SBIN, MARUTI,
   TATASTEEL, ONGC ...), each with ZERO inclusion/exclusion events; the padded-to-200 pattern. "Caught
   by external reconciliation against NSE's own list — NOT by any statistical gate. DSR, PBO,
   purge/embargo and the lag test would all pass it silently, because it contaminates the UNIVERSE."
   Fix: Phase 1 — rebuild from bhavcopy by trailing turnover; link to the Universe flat-coverage chart.
2. STATISTICS — look-ahead leakage. Naive: engine.leaky_signal() -> engine.run_backtest on val_a -> a
   spectacular RankIC. Caught: src.redteam test 5 (extra_lag=1) -> RankIC collapses to ~0; show
   deflated_sharpe_ratio would have PASSED it. "Statistical gates catch over-searching, not cheating."
   Fix: the causal operator library + per-field timing rules (link to the Operators page).
3. ECONOMICS — right answer, wrong reason. Naive: a data-mined signal with a good IC whose REALISED
   sign is opposite its pre-registered sign; construct one deterministically; show the IC. Caught:
   src.gates.check_sign(+1, -1) -> False -> rejected as a THESIS FAILURE. "No purely statistical gate
   would ever have flagged it." Fix: reject + record that this mechanism family produces
   direction-unstable stories (link to Memory).

Example 1 numbers must come from the REAL supplied CSV — report the exact count of missing
heavyweights. Do NOT fabricate metrics (placeholders labelled as such). Do NOT block the Alpha Cards
page behind the banner. Do NOT touch HOLDOUT for example 2. Do NOT present example 3 as a sign to flip.

Finish by writing reports/dash_p7_handoff.md per Section 0.10 (acceptance PER PAGE). Then STOP.
```

## D8 — Build Log, polish, deploy  *(do this last)*

```
Execute PHASE D8 from DASHBOARD_PLAN.md.

Build dashboard/pages/14_Build_Log.py, finalise dashboard/README.md and .streamlit/config.toml, add
run_dashboard.ps1, and write tests/test_dash_e2e.py.

1. 14_Build_Log.py: the phase timeline (system P0-P13 + dashboard D0-D8, each with a status pill
   DERIVED BY GLOBBING reports/p*_handoff.md — never a hard-coded list; P11/P12 may land after you
   write this page and it must light up on its own); render every reports/*_handoff.md present in an
   expander; an acceptance-pass-count summary table; the current pytest result.
2. CONSISTENCY PASS — one walk of every page against Section 0.7: header present, every chart has
   context + source_note, colours from PALETTE, prose from narrative, missing-data paths use
   ui.data_missing + st.stop(), no raw full-parquet read, no src import outside engine.py (except the
   two allowed pages), page-triggered runs use Ledger(":memory:"). Fix violations; list them all in
   the handoff.
3. README — a fresh clone must run the dashboard in THREE commands: pip install -r
   requirements-dashboard.txt ; python dashboard/build_cache.py ; streamlit run dashboard/Home.py.
   Document --heavy, both deploy options, and what each page needs.
4. DEPLOY NOTES — Streamlit Community Cloud and HF Spaces. State the data-size implication: the
   dashboard needs only the data/dashboard/ caches + sliced reads, so document a "caches-only" deploy
   that does not ship the multi-GB ohlcv.parquet (pages that need it then degrade gracefully).
5. THEME — finalise config.toml; verify every chart type is legible in both the default dark theme AND
   a forced light theme; fix PALETTE if needed. Screenshots to reports/dash_shots/.
6. test_dash_e2e.py — import every pages/*.py and Home.py, assert no import-time exception; run
   build_cache.py --check.

Do NOT add a dependency to make it prettier. Do NOT commit a deploy shipping a paid key or the raw
multi-GB parquet.

Finish by writing reports/dash_p8_handoff.md per Section 0.10. Then STOP.
```

---

# SUGGESTED ORDER

**Sequential minimum path** (narrative + the flagship data pages + the honesty machinery + the bad
examples):
`D0 → D1 → D2 → D3 → D5 → D7 → D8`
(D7's Bad Examples then stubs `engine.eval_formula` / `run_backtest` or borrows them from D5.)

**Full build with parallel agents:**
`D0` first, then `D1` + `D2` in parallel, then fan out `D3 D4 D5 D6 D7` across up to 5 sessions, then
`D8`.

## Running this in parallel with system phases P11 and P12 — SAFE, and recommended

The write sets are disjoint: P11 writes `artifacts/cards/`, `artifacts/portfolio_report.md`,
`reports/p11_demo.md` and (via a real run) `data/*.db` + `bandit_state.json` + `book.parquet` +
`loop_checkpoint.db`; P12 writes `src/evaluation.py` + `reports/p12_*`; the dashboard writes only
`dashboard/`, `data/dashboard/`, `reports/dash_*`, `tests/test_dash_*`, `requirements-dashboard.txt`,
`.streamlit/`, `run_dashboard.ps1`. Nothing collides — **provided every phase obeys
`DASHBOARD_PLAN.md` §0.8.1** (read-only SQLite snapshots, JSON-tolerant `load_bandit`, staleness
reporting, no config value copied at author time). Skipping §0.8.1 can stall or crash a live P11 run.

```
now, in parallel with P11 + P12:  D0 → D1 → D2 → { D3, D4, D5, D6 }  +  D7's 10_The_Loop & 13_Bad_Examples
after P11 lands:                  D7's 11_Alpha_Cards
after P12 lands:                  D7's 12_System_Evaluation
last, after both:                 D8
```

P11 is bounded by the ~20-thesis/day token ceiling and will span days, so building the dashboard
alongside it is the only way it is ready when the run finishes.

| Phase | Pages | Model | Thinking |
|---|---|---|---|
| D0 Scaffolding | — | Sonnet | medium |
| D1 Cache builder | — | Sonnet | medium–high |
| D2 Home + flow + narrative | Home | Sonnet | medium |
| D3 Data pages | 01, 02, 03 | Sonnet | medium |
| D4 Formula tooling | 04, 05 | Sonnet | medium |
| D5 Honesty machinery | 06, 09 | Sonnet | high |
| D6 Memory + LLM Agents | 07, 08 | Sonnet | medium |
| D7 Narrative & examples | 10, 11, 12, 13 | Sonnet | medium–high |
| D8 Build Log + deploy | 14 | Sonnet | medium |
