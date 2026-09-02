# IMPLEMENTATION PLAN — Agentic AI Alpha Researcher

> **How to use this document.** The project is cut into **14 independent phases**. Each phase spec is
> self-contained: it states what the project is, its exact inputs and outputs (with schemas), its
> steps, its acceptance tests, and an explicit scope fence.
>
> **An agent executing a phase needs only: (a) Section 0 of this document, and (b) that phase's spec.**
> It does **not** need to know how any other phase was implemented — only the *contract* of the files
> it reads and writes. Every phase includes a **synthetic fixture generator**, so it can be built and
> tested even if upstream phases have not run yet.
>
> Design documents (background, not required to execute a phase):
> `FLOW_EXPLAINED.md` (plain-English walkthrough) · `INITIAL_PLAN.md` (architecture spec) ·
> `PLAN_EXPLAINED.md` (decision record + dictionary).

---

# SECTION 0 — SHARED CONTRACTS

**Every phase agent must read this section. Nothing else outside your own phase is required.**

## 0.1 What this project is (30 seconds)

We are building an **AI agent loop that invents, tests and filters stock-market alpha signals**.

An **alpha signal** is a daily cross-sectional score: **one number per stock per day**, where the
*ranking* across stocks predicts their relative forward returns. Universe = **NIFTY 200** (Indian
equities). The system produces **Alpha Cards** — each containing an economic thesis plus an executable
formula — and it is deliberately designed to *reject* most of what it generates.

The central engineering theme is **not fooling ourselves**: hard statistical gates, an adversarial
red-team, a locked holdout, and a trial ledger that raises the bar the more we search.

## 0.2 Environment

- **Python 3.11+**, Windows (paths use `E:\Trexquant_Superday`). Prefer `pathlib`, never hard-code
  separators.
- **Allowed dependencies:** `pandas`, `numpy`, `pyarrow`, `scipy`, `statsmodels`, `yfinance`,
  `requests`, `matplotlib`, `pytest`, `python-dotenv`, `sqlite3` (stdlib), and for Phases 8/10 only:
  `langgraph`, `langchain-core`, `langchain-groq`.
- **Explicitly NOT allowed:** FAISS, Pinecone, Chroma, Postgres, Redis, Docker, any paid data source,
  any paid API. Volumes here are hundreds of rows; every extra dependency is something that breaks
  during a live demo.
- **No network access at runtime** except Phase 2 (price download) and Phase 8/10 (LLM calls).

## 0.3 Repository layout

```
E:\Trexquant_Superday\
├── data/
│   ├── raw/            # downloaded files, NEVER modified in place
│   ├── universe/       # P1 output
│   ├── prices/         # P2 output
│   └── panel/          # P3 output
├── src/
│   ├── config.py       # P0 — constants, paths, split dates
│   ├── contracts.py    # P0 — schema definitions + validators + fixture generators
│   ├── universe.py     # P1
│   ├── prices.py       # P2
│   ├── panel.py        # P3
│   ├── backtester.py   # P4
│   ├── operators.py    # P5
│   ├── ast_tools.py    # P5
│   ├── gates.py        # P6
│   ├── ledger.py       # P6
│   ├── memory.py       # P7
│   ├── agents/         # P8
│   ├── redteam.py      # P9
│   ├── loop.py         # P10
│   └── evaluation.py   # P12
├── tests/              # pytest, one file per phase: test_p1_universe.py, ...
├── reports/            # audit reports, plots
├── artifacts/cards/    # Alpha Cards (JSON)
└── slides/             # P13
```

## 0.4 The canonical data split — **memorise this**

| Region | Start | End | Job |
|---|---|---|---|
| *warm-up* | 2014-01-01 | 2014-12-31 | lookback buffer only. **Never scored.** |
| **TRAIN** | 2015-01-01 | 2017-12-31 | warm-up + CSCV fold supply. **Never selects anything.** |
| **VAL_A** | 2018-01-01 | 2021-06-30 | the search playground — every formula variant is scored here |
| **VAL_B** | 2021-07-01 | 2022-06-30 | **fresh fold.** Only a promoted winner is ever scored here |
| **HOLDOUT** | 2022-07-01 | 2025-12-31 | **sealed.** A fixed, counted number of peeks, ever |
| *reserved* | 2026-01-01 | — | live-forward check |

> ⚠️ **HOLDOUT is sacred.** No phase may read HOLDOUT except through the rationed-peek API in Phase 6.
> Any code that touches HOLDOUT dates outside that API is a bug.

## 0.5 File contracts

All tabular artifacts are **parquet** (`pyarrow`). All dates are timezone-naive `datetime64[ns]`,
normalized to midnight. All symbols are **uppercase NSE tickers without the `.NS` suffix**.

### `data/universe/membership.parquet`
Daily boolean membership panel.
| Column | Type | Notes |
|---|---|---|
| `date` | datetime64[ns] | one row per calendar trading day |
| `symbol` | string | uppercase, no `.NS` |
| `in_universe` | bool | was this stock a NIFTY 200 constituent on this date |

Long format. Index reset. Sorted by `(date, symbol)`.

### `data/universe/symbols.json`
```json
{"symbols": ["ABB","ACC", "..."], "n": 315,
 "renames": {"CAIRN": "VEDL", "GRUH": "BANDHANBNK", "CMC": "TCS", "BHARATFIN": "INDUSINDBK"},
 "selection_rule": "top 200 by trailing 63d median turnover, monthly"}
```

### `data/prices/ohlcv.parquet`
| Column | Type | Notes |
|---|---|---|
| `date` | datetime64[ns] | |
| `symbol` | string | |
| `open,high,low,close,volume` | float64 | **split/dividend ADJUSTED** |
| `close_raw`, `volume_raw` | float64 | **UNADJUSTED**, for turnover sanity checks |
| `vwap` | float64 | `TOTTRDVAL/TOTTRDQTY` (pre-2019-09) or `AVG_PRICE` (after). **Verified derivable** — needed by ~10 Alpha101 formulas |
| `n_trades` | float64 | `TOTALTRADES` / `NO_OF_TRADES`. Enables avg-trade-size microstructure |
| `isin` | string | stable across ticker renames — the internal key |
| `source` | string | `"bhavcopy_legacy"` \| `"sec_bhavdata_full"` |

### `data/panel/features.parquet`
| Column | Type |
|---|---|
| `date` | datetime64[ns] |
| `symbol` | string |
| `mom_21`, `mom_126`, `rev_5`, `vol_21`, `beta_63`, `amihud_21`, `turnover_21`, `dist_52wh`, `max_ret_21`, `delivery_pct` | float64 |
| `size_proxy` | float64 — trailing-turnover stand-in for market cap (see P2 step 4c); used by red-team test 3 |
| `sector` | string |

### `data/panel/labels.parquet`
| Column | Type | Notes |
|---|---|---|
| `date` | datetime64[ns] | the **signal** date *t* |
| `symbol` | string | |
| `fwd_ret_1` … `fwd_ret_21` | float64 | return from *t+1* open → *t+1+h* open |
| `fwd_ret_1_demeaned` … | float64 | cross-sectionally demeaned each day — **this is the label** |

### `data/panel/splits.json`
```json
{"warmup":["2014-01-01","2014-12-31"], "train":["2015-01-01","2017-12-31"],
 "val_a":["2018-01-01","2021-06-30"], "val_b":["2021-07-01","2022-06-30"],
 "holdout":["2022-07-01","2025-12-31"]}
```

### The `Metrics` dict — every backtest returns this shape
```python
{"rank_ic": float, "ic": float, "icir": float, "t_stat": float,
 "sharpe": float, "ann_return": float, "turnover": float, "mdd": float,
 "n_days": int, "n_obs": int, "decay": {1: float, 2: float, 3: float, 5: float, 10: float, 21: float},
 "sign": int}     # +1 or -1, from the realized rank_ic
```

### The `AlphaCard` JSON — the project's output unit

> **P6-UPDATE — three fields added to `audit`, and the illustrative DSR corrected.** `n_trials_effective`
> (the cluster-adjusted, run-wide count the DSR is actually deflated by), `expected_max_sr` (the
> Bailey-LdP deflator applied), and `holdout_scored_on` (`"residual"` — so the peek's target is
> auditable, not assumed). The example previously showed `deflated_sharpe: 0.9` on an *accepted* card,
> which sits below the `DSR_MIN = 0.95` bar Phase 6 enforces; the example now reads 0.97. Gate B's full
> audit dict is a superset of this block — see `reports/p6_handoff.md`.
```json
{"card_id":"...", "thesis_id":"...", "generation":3,
 "thesis":{"mechanism":"...","counterparty":"...","why_not_arbitraged":"...",
           "horizon_days":5,"regime":"calm","falsifiable_claim":"..."},
 "pre_registered":{"sign":1,"horizon_days":5,"committed_at":"2026-09-01T10:00:00","hash":"sha256:..."},
 "formula":"rank(ts_mean(volume,1)/ts_mean(volume,20))*sign(delay(close,1)-close)",
 "ast_canonical":"...", "complexity":{"nodes":11,"depth":4,"free_params":2},
 "tier1_metrics":{}, "fresh_fold_metrics":{}, "tier2_metrics":{},
 "audit":{"marginal_ic":0.025,"deflated_sharpe":0.97,"t_stat":3.2,"pbo":0.18,
          "n_trials_global":143,"n_trials_within_thesis":7,"n_trials_effective":31,
          "expected_max_sr":0.061,"holdout_peek_id":4,"holdout_scored_on":"residual"},
 "redteam":{"tests_run":["subsample_year","regime_split"],"results":{},"verdict":"survives"},
 "verdict":"accept", "lineage":{"parent_card_id":null,"edit_motif":null},
 "provenance":{"fields_used":["volume","close"]}}
```

## 0.6 Conventions every phase must follow

1. **Determinism.** Seed everything (`numpy`, `random`). Same input → same output, always.
2. **Fail loudly.** Assert contracts on read and on write. Never silently fill NaN.
3. **Never modify `data/raw/`.** Download once, transform into new files.
4. **Log decisions.** Any filter, drop, or fill writes a line to the phase's report in `reports/`.
5. **Tests live in `tests/test_p<N>_<name>.py`** and must run with plain `pytest` and no network.
6. **Point-in-time discipline.** Nothing may use information from after the date on the row. If you are
   unsure whether a computation looks forward, write a test that shifts the panel and checks the result
   changes in the expected direction.

## 0.7 Phase completion protocol — **every phase is human-verified before the next begins**

**No phase is "done" when the code runs. It is done when the project owner has verified it and said so.**
Work stops at the end of your phase. Do not start the next one.

This changes what you must produce: **evidence, not assurances.** "The tests pass" is not a handoff.
A number the owner can check is.

### Required: `reports/p<N>_handoff.md`

Every phase ends by writing this file. It is the thing that gets reviewed.

```markdown
# Phase <N> handoff — <name>

## 1. What was built
| File | Lines | Purpose |
(one row per file created or modified)

## 2. Acceptance criteria — every one, with a MEASURED value
| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | Random noise gives \|rank_ic\| < 0.01 | ✅ PASS | rank_ic = 0.0032 |
| 2 | ... | ❌ FAIL | expected <0.01, got 0.04 — see §5 |
(NEVER write "PASS" without the number that proves it)

## 3. Verify it yourself
Exact commands the owner can run, with the output they should expect:
```
pytest tests/test_p<N>_*.py -v        # expect 14 passed
python -c "..."                        # expect: 315
```

## 4. What I could NOT verify, and why
(e.g. "endpoint returned 404 for 12 dates in 2016 — listed in reports/p2_coverage_report.md;
could not determine whether those were holidays or genuine gaps")

## 5. Failures and open issues
(each with what you tried and what you recommend)

## 6. Anything that contradicts the spec
(the spec has already been wrong several times. If you found an error, say so plainly —
do not silently work around it)

## 7. Decisions I made that the spec left open
(every judgement call, with the reasoning — these are what the owner most needs to check)
```

### Rules

1. **Every acceptance criterion reports a measured value.** A checkbox with no number is not evidence.
2. **Report failures.** A phase with 3 of 12 criteria failing, honestly reported, is more useful than
   one claiming 12/12 that falls over in the next phase. Nothing here is graded on a clean sheet.
3. **Never fabricate a result.** If something could not be tested, say that — do not infer it.
4. **Flag every judgement call** in §7. The spec cannot anticipate everything; the owner needs to see
   where you chose.
5. **Do not start the next phase.** Stop and wait for sign-off.
6. **Expect rework.** Verification may send a phase back. That is the protocol working, not a failure.

### Why this exists

The whole system is built to catch self-deception in *signals*. The same discipline applies to the
*build*: an unverified phase silently poisons everything downstream, and the data phases especially
(P1–P3) can produce output that looks perfectly reasonable while being quietly wrong. **A survivorship-
biased panel does not throw an exception — it just makes every later result too good.** Human
verification at each boundary is the equivalent of the red-team gate, applied to ourselves.

---

# PHASE 0 — Project scaffolding

**Objective:** create the skeleton, config, schema validators, and fixture generators every other
phase depends on.

**Depends on:** nothing. **Blocks:** everything.

## Inputs
None.

## Outputs
- `src/config.py` — paths, split dates (Section 0.4), constants: `MAX_VARIANTS_PER_THESIS = 20`,
  `HOLDOUT_PEEK_BUDGET = 12`, `T_STAT_BAR = 3.0`, `COST_BPS_DEFAULT = 15`, `EMBARGO_DAYS = 5`,
  `RANDOM_SEED = 42`.
- `src/contracts.py` — for **each** artifact in Section 0.5:
  - `validate_<name>(df) -> None` (raises with a precise message on violation)
  - `make_fake_<name>(n_days, n_symbols, seed) -> DataFrame` — **the fixture generator**
- `tests/test_p0_contracts.py`
- `requirements.txt`
- `reports/.gitkeep`, `artifacts/cards/.gitkeep`

## Steps
1. Create the directory tree from Section 0.3.
2. `config.py`: absolute paths via `pathlib.Path`, all split dates as `pd.Timestamp`, a helper
   `split_mask(dates, region) -> np.ndarray[bool]`, and `assert_not_holdout(dates)` which raises if any
   date falls in HOLDOUT — call it defensively in phases that must never see it.
3. `contracts.py`: validators check column presence, dtypes, sort order, no duplicate `(date, symbol)`,
   and no all-NaN columns.
4. **Fixture generators are load-bearing** — they are how later phases get built without upstream data.
   Make them realistic: `make_fake_ohlcv` should produce geometric-random-walk prices with plausible
   volatility (~25% annualized), occasional gaps, and a few symbols that stop trading partway through.
   `make_fake_features` should produce correlated features, and `make_fake_labels` should contain **one
   feature with a genuine, known IC of ~0.04** so downstream phases can test that their machinery can
   detect a real signal.

## Acceptance
- [ ] `pytest tests/test_p0_contracts.py` passes.
- [ ] Every validator rejects a deliberately corrupted frame with a message naming the exact column.
- [ ] `make_fake_*` outputs pass their own validators.
- [ ] `assert_not_holdout` raises on `2023-01-01` and passes on `2019-01-01`.

## Do NOT
Do not implement business logic. No features, no backtester, no agents. Contracts and fixtures only.

**Effort:** ~1.5h

---

# PHASE 1 — Universe construction (liquidity-defined)

> ⚠️ **RUNS AFTER PHASE 2.** The dependency was inverted after verification proved the supplied index
> file unusable (see below). P1 no longer reads any CSV — it derives the universe from P2's bhavcopy
> data. **Execution order is P0 → P2 → P1 → P3.**

**Objective:** build a point-in-time, survivorship-free universe of the 200 most liquid Indian equities,
derived entirely from NSE daily bhavcopy.

**Depends on:** P0 contracts, **P2's `data/prices/ohlcv.parquet`**. **Blocks:** P3.

## Standalone context

### Why we do NOT use the supplied index file

The project originally planned to use `nifty200_2015-01-01_to_2026-09-01.csv` (37 NIFTY 200 rebalance
snapshots from niftyhistory.in). **Verification proved it unusable as an index:**

- **80 of today's 200 NIFTY 200 constituents never appear in it at all** — including RELIANCE, TCS,
  SBIN, MARUTI, TATASTEEL, TATAMOTORS, SUNPHARMA, TITAN, ULTRACEMCO, ONGC.
- **All 80 have zero inclusion/exclusion events.** That is the diagnostic signature: the file was
  reconstructed by replaying a change-log onto a base seed, so any stock already in the index before the
  log begins — and never subsequently churning — was never added. Permanent heavyweights are exactly
  that profile. Each snapshot was then padded back to 200 with mid-caps, which is why every row is a
  clean 200 while missing the largest names by weight.
- Separately, **21 of 36 rebalances are internally inconsistent** (declared inclusions/exclusions do not
  reconcile against the `symbols` deltas).

**Replay cannot repair this.** Forward replay needs a correct 2015 base list; ours is the broken one.
Backward replay from NSE's current `ind_nifty200list.csv` needs a complete change log; ours is 21/36
inconsistent. NSE publishes only the *current* constituent list, not historical snapshots.

### What we do instead

**Define the universe by liquidity, from the exchange's own daily files.**

> **THE RULE.** On the last trading day of each month, using only data available that day:
> 1. Take every `SERIES == 'EQ'` stock present in that day's bhavcopy.
> 2. Require **≥ 252 trading days of prior history** (so features are computable from day 1).
> 3. Rank by **median daily turnover over the trailing 63 trading days**.
> 4. **The top 200 are the universe for the following month.**

### Why this is survivorship-free — and provably so

Survivorship bias enters when the universe is chosen using information about *who survived*. Both halves
of this rule are blind to that:

- **The ranking** uses trailing 63-day turnover as of date *D*. On 2018-03-15 DHFL was highly liquid, so
  it is in that month's top 200. Its 2019 collapse is unknowable on that date and cannot influence the
  selection.
- **The source** is a per-day snapshot listing whatever actually traded — DHFL, RCOM, YESBANK included
  (verified in P2).

The dead names are not *rescued* by a special step. **They are simply never excluded, because nothing in
the pipeline ever asks "does this company still exist?"** And exit is automatic: a stock leaves when it
stops appearing in the daily files. No delisting-date list, no judgement call — **the absence is the
delisting.** That is what makes it robust: there is no step where a human could get it wrong.

**Contrast with the broken approach:** starting from today's constituent list and walking backwards
filters by "still in the index in 2026" — a survival filter, and a silent one, because nothing errors.

## Inputs
- `data/prices/ohlcv.parquet` from P2 — needs `date, symbol, isin, close_raw, volume_raw, series`.
  *(If missing: `contracts.make_fake_ohlcv()`, which includes symbols that stop trading partway through
  — exactly what the survivorship logic must handle.)*
- **Optional, for the report only:** `nifty200_2015-01-01_to_2026-09-01.csv`, used solely to document
  overlap between our universe and the nominal index. **Never used to select members.**

## Outputs
- `data/universe/membership.parquet` — Section 0.5 schema (`date · symbol · in_universe`), daily,
  forward-filled from each monthly selection to the next
- `data/universe/universe_stats.parquet` — `date · n_members · median_turnover · turnover_cutoff_200`
- `data/universe/symbols.json` — union of every symbol ever selected, plus the ISIN map
- `reports/p1_universe_report.md`

## Steps

1. **Load P2's panel.** Filter `SERIES == 'EQ'` (record whether you also keep `BE` — see P2). Key by
   ISIN internally, present by symbol.
2. **Compute trailing turnover** per symbol: `close_raw × volume_raw`, then a rolling **63-day median**.
   **Trailing only** — never centred, never full-sample.
3. **Monthly selection.** On each month's last trading day apply THE RULE. Record that month's rank-200
   turnover cutoff into `universe_stats` — it is a useful diagnostic and shows the liquidity floor
   rising over time.
4. **Forward-fill to daily.** Each monthly selection holds until the next. A stock that stops trading
   mid-month simply has no price rows; it remains nominally in the universe until the next selection and
   is dropped by the join in P3. Document this choice.
5. **Emit the union and ISIN map** to `symbols.json`.
6. **Index-overlap diagnostic (report only).** Compare the universe against NSE's current
   `ind_nifty200list.csv` and against the supplied CSV; report overlap percentages. This is *context for
   the reader*, never a selection input — state that explicitly in the report.

## Acceptance

- [ ] `validate_membership(df)` passes.
- [ ] Exactly **200 members** selected each month — or fewer only in the earliest months if the 252-day
      history requirement bites. Report any such month.
- [ ] **TEST A — canaries.** DHFL, RCOM, JPASSOCIAT, YESBANK, SUZLON, IDEA are each in the universe on a
      date when they were actively trading, and absent after they stop appearing in bhavcopy. Assert on
      specific dates.
- [ ] **TEST B — flat coverage (the decisive diagnostic).** Plot `n_members` per day 2015 → today. It
      must be **flat at ~200** with **near-zero linear trend**. An upward slope means survivorship bias
      is still present — **HARD STOP, do not proceed to P3.**
- [ ] **TEST C — no look-ahead in selection.** Recompute the universe using only data up to 2020-01-01
      and confirm membership for every month before that date is **bit-identical** to the full run. If
      truncating the future changes the past, the rule is leaking.
- [ ] The heavyweights the old file was missing (RELIANCE, TCS, SBIN, TATASTEEL, MARUTI, ONGC) **are**
      in the universe for most of the period — they are among the most liquid stocks in India. Their
      absence would indicate a turnover-computation bug.
- [ ] Monthly membership turnover (names entering/leaving) is reported; expect roughly 2–5%.
- [ ] The report states overlap with the nominal NIFTY 200 and the exact naming we will use.

## Do NOT

- **Do not select members using the supplied CSV, or any current constituent list.** Both encode
  "survived to today." The CSV may be read *only* for the step-6 overlap diagnostic.
- Do not use a centred or full-sample turnover window — trailing only.
- Do not hand-add "obviously large" names. The rule decides, or the universe is not reproducible.
- Do not compute features (P3's job).

## Naming — use this wording everywhere, including the slides

> **"The 200 most liquid Indian equities, reconstructed point-in-time from NSE daily bhavcopy."**

**Not "NIFTY 200."** For a cross-sectional ranking exercise the index label was never load-bearing — a
coherent, survivorship-free, point-in-time universe is what matters, and this one is reproducible from
primary source by anyone. Say so plainly; it is a stronger claim than the one we gave up.

**Effort:** ~2.5h

# PHASE 2 — Price data acquisition ⭐ *recommended starting phase*

**Objective:** obtain OHLCV for every symbol in the universe union, with honest measurement of what
could not be obtained.

**Depends on:** P0 contracts only. **Blocks:** P1, P3.
> ⚠️ **ORDER CHANGED — P2 now runs BEFORE P1.** P2 downloads whole trading days, so it needs no symbol
> list; and P1 now derives the universe *from* P2's output. Execution order: **P0 → P2 → P1 → P3.**

## Standalone context

We need daily price history covering every stock that was *ever* in NIFTY 200 between 2015 and today —
**including the ~115 that were dropped, delisted, or went bankrupt.** Testing only on companies that
still exist is **survivorship bias**, and it makes any strategy look better than reality.

### 🔑 THE CONSTRUCTION PRINCIPLE — read this before writing any code

> **Never filter the universe by anything that is only knowable today.**

The trap almost everyone falls into: start from a list of stocks that exist *now* and walk backwards.
That is survivorship bias built into the foundation, and no later gate can detect it.

The correct approach is the reverse: **start from what existed on each day, as recorded on that day.**
We have two independent per-date snapshots, and neither is reconstructed from the present:

| Source | Answers | Why it's survivorship-free |
|---|---|---|
| Membership CSV (P1) | *which stocks were in the index on date D* | each row was the list in force at that time |
| **NSE daily bhavcopy** | *which stocks actually traded on date D* | the file was published that evening and lists everything that traded |

Three rules follow, and every step below obeys them:

- **R1** — Membership for date D comes from the snapshot in force on D. **Never a later snapshot.**
- **R2** — Prices for date D come from the file published on D, containing whatever traded that day.
- **R3** — A stock leaves the panel when it **stops appearing in the daily files**. You never need a
  "delisting date" list — *the absence is the delisting.* This is what makes the method robust: there
  is no judgement call to get wrong.

> ### ✅ VERIFIED — these endpoints were probed live on 2026-09-02, not taken from documentation
> - **Legacy bhavcopy** `.../content/historical/EQUITIES/<YYYY>/<MON>/cm<DDMONYYYY>bhav.csv.zip`
>   → HTTP 200 for 2015, 2016, 2018, 2019. Downloading 2018-03-15 (1,854 rows) confirmed
>   **DHFL, RCOM, JPASSOCIAT, YESBANK, SUZLON, IDEA, COX&KINGS all present with real prices.**
>   CAIRN was correctly *absent* — it merged into Vedanta in April 2017. That absence is a
>   **validation** that the archive is genuinely point-in-time.
>   Schema: `SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP,
>   TOTALTRADES, ISIN`.
> - **`sec_bhavdata_full`** `.../products/content/sec_bhavdata_full_<DDMMYYYY>.csv`
>   → **starts 2019-09-30** (2019-09-27 is 404; bisected exactly). Survives NSE's July-2024 UDiFF
>   migration, so one parser covers 2019-09-30 → present. Adds `DELIV_QTY`, `DELIV_PER`.
> - **Corporate actions API** `.../api/corporates-corporateActions?index=equities&from_date=..&to_date=..`
>   → HTTP 200, **2,012 records for 2018**, fields `symbol · exDate · subject`.
> - **Throughput measured:** 15 consecutive requests, **zero failures, no throttling** (latency *fell*
>   across the burst). Legacy ≈ 1.05 s / 64 KB; full ≈ 1.86 s / 208 KB.
>   **~3,130 requests ≈ 78 min sequential (~20 min with 4 workers), ~450 MB.**

**NSE is therefore the PRIMARY source and yfinance is demoted to a cross-check.** The original plan had
this backwards.

## Inputs
**None.** This phase is self-contained — it downloads whole trading days from NSE and does not need a
symbol list. (That is precisely what makes it survivorship-free: you get whatever traded, rather than
whatever you thought to ask for.)

## Outputs
- `data/raw/nse/<YYYY>/<file>` — every daily bhavcopy, cached verbatim, never modified
- `data/raw/nse_ca/<YYYY>.json` — corporate actions per year
- `data/prices/ohlcv.parquet` (Section 0.5 schema) — **adjusted + raw, ISIN-keyed**
- `data/prices/isin_map.parquet` — `date · symbol · isin` (resolves renames)
- `data/prices/corporate_actions.parquet` — `isin · ex_date · type · ratio · raw_subject`
- `data/prices/delivery.parquet` — `date · symbol · deliv_qty · delivery_pct` (2019-09-30 →)
- `data/prices/size_proxy.parquet` — `date · symbol · size_proxy`
- `reports/p2_coverage_report.md`
- `reports/p2_coverage_plot.png` — **TEST B, the decisive diagnostic. See step 5.**

## Steps

**1. Download every trading day from NSE — the whole market, not a symbol list.**
This is the step that eliminates survivorship bias, and the reason is structural: you are downloading
**whatever traded that day**, so delisted names arrive automatically without you asking for them.

- **2014-01-01 → 2019-09-27:** legacy zip
  `https://nsearchives.nseindia.com/content/historical/EQUITIES/<YYYY>/<MON>/cm<DDMONYYYY>bhav.csv.zip`
  (`<MON>` is uppercase three-letter, e.g. `MAR`.)
- **2019-09-30 → today:** `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_<DDMMYYYY>.csv`
- Send a browser `User-Agent`. For the corporate-actions API (step 3) also establish a session cookie by
  first requesting `https://www.nseindia.com`, and send a `Referer`.
- **Cache every file to `data/raw/nse/` and skip if present.** This phase will be re-run; make it
  resumable. A 404 on a weekend or holiday is expected and is not an error — record and continue.
- Parallelism ≤ 4 workers with a small delay. No throttling was observed at 15 requests, but that was
  not tested at 3,000 — be conservative, it costs nothing on an unattended run.

**2. Parse and normalize — three traps here.**
- **⚠️ Filter `SERIES == 'EQ'`.** bhavcopy contains debt, ETFs, and trade-to-trade series. Failing to
  filter silently double-counts symbols and corrupts the cross-section. *(Consider also allowing `BE`,
  the trade-to-trade series — a stock moved to `BE` is a distress signal, so dropping it would reintroduce
  a mild survivorship bias. Record which choice you made.)*
- **Key internally by `ISIN`, present by `SYMBOL`.** ISIN is stable across ticker renames, so
  CAIRN→VEDL, GRUH→BANDHANBNK, CMC→TCS resolve **by identifier rather than by a hand-written name map**.
  Build a `date → symbol → isin` map from the daily files.
- The two eras have different column names (`TOTTRDQTY` vs `TTL_TRD_QNTY`, etc.). Normalize both into
  one schema, and tag each row's `source` era.

**3. Corporate actions → build our own adjustment.**
bhavcopy is **unadjusted**: a 1:10 split reads as a −90% return unless corrected.
- Fetch `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY`
  one year at a time (~2,000 records/year). Re-establish the session cookie per year-chunk.
- Parse `subject` free text into a ratio. The two that matter:
  - `"Bonus 1:1"` → factor `b/(a+b)`
  - `"Face Value Split ... From Rs 10/- Per Share To Rs 5/- Per Share"` → factor `Y/X`
- Dividends distort by ~1% and are second-order at our horizons; splits and bonuses distort by 50–90%
  and are the ones that must be right. **Demergers and mergers are genuinely hard — do not attempt
  them; flag affected symbol-dates and disclose.**
- Build a cumulative back-adjustment factor per ISIN and emit both **adjusted** (`open/high/low/close`)
  and **raw** (`close_raw`, `volume_raw`) columns.

> **The simplification that makes this tractable:** nine of our eleven features are *return- or
> ratio-based*. For those you only need the **return on the ex-date neutralized**, not a perfectly
> back-adjusted series. And a missed split produces a −90% single-day return, which P3's extreme-return
> assertion **already flags** — so the hard cases self-report rather than hiding.

**4. Cross-check against yfinance (validation only, not the source).**
For ~30 surviving large caps, download from yfinance and compare our adjusted daily returns to Yahoo's.
Correlation should be > 0.99. Any date where they diverge sharply is a **missed corporate action** —
investigate and record. This is a test, not a data source.

**4b. Fetch delivery data — `sec_bhavdata_full` (REQUIRED — `delivery_pct` is one of our ten features).**
NSE publishes `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_<DDMMYYYY>.csv`
after the close each day, carrying `DELIV_QTY` and `DELIV_PER` per symbol. Download the daily files for
2014→present into `data/raw/nse_delivery/`, then assemble `data/prices/delivery.parquet`:

| Column | Type |
|---|---|
| `date` | datetime64[ns] |
| `symbol` | string |
| `deliv_qty` | float64 |
| `delivery_pct` | float64 (0–100) |

Same headers/session-cookie requirement as bhavcopy. **Time-box to 90 minutes.** History before ~2020
may be unavailable at this endpoint — if so, fetch what exists, record the first available date in the
report, and let `delivery_pct` be NaN before it. **Do not fabricate it.** A feature that only exists
from 2020 is fine and disclosable; an invented one is not.

**4a. Derive `vwap` and `n_trades` — required by the alpha zoo.** *(Verified derivable 2026-09-02.)*
- Legacy era: `vwap = TOTTRDVAL / TOTTRDQTY`; `n_trades = TOTALTRADES`.
- Modern era: `vwap = AVG_PRICE`; `n_trades = NO_OF_TRADES`. Cross-check against
  `TURNOVER_LACS / TTL_TRD_QNTY`.
- **Assert `low <= vwap <= high`** on every row. Validated on 2018-03-15: RELIANCE 918.37 ∈ [910,
  929.45], TCS 2,876.92 ∈ [2,855.60, 2,902.55], DHFL 519.46 ∈ [513, 524.90], SUZLON 11.65 ∈ [11.45,
  11.75]. A row failing this assertion signals a parsing or units error.
- `vwap` is needed by ~10 Alpha101 formulas; `n_trades` gives average trade size
  (`volume / n_trades`) — genuine microstructure that a yfinance-only pipeline cannot produce.

**4c. Size proxy — and a look-ahead trap to avoid.**
Red-team test 3 splits by company size. **Do NOT use `yfinance`'s `sharesOutstanding`**: it returns the
*current* share count only, so applying it to 2015 silently uses information from the future (buybacks,
issuance, splits already reflected). That is exactly the class of leak this project exists to catch.

**Instead compute a point-in-time size proxy from trailing rupee turnover**:
`size_proxy = log(median(close_raw × volume_raw) over the trailing 63 days)`. Emit it into
`data/prices/size_proxy.parquet` (`date · symbol · size_proxy`). Document the substitution in the
report — it is a defensible, leak-free stand-in for market cap, and saying why is a small rigor point.

**5. The join, and the two tests that PROVE it worked.**

For each trading date D:
```
members(D) = the membership snapshot in force on D          (R1)
traded(D)  = symbols present in the bhavcopy published on D  (R2)
panel(D)   = members(D) ∩ traded(D)
gap(D)     = |members(D)| - |panel(D)|     ← the residual, measured daily
```

> ### 🔬 TEST A — the canary test
> `DHFL, RCOM, JPASSOCIAT, YESBANK, SUZLON, IDEA, COX&KINGS` must be **present in the panel during
> their trading lives and absent afterwards.** Assert on specific dates. If any is missing while it was
> still trading, the pipeline is dropping the dead — which is the exact bias we are eliminating.

> ### 🔬 TEST B — the flat-coverage test (**the decisive diagnostic**)
> Plot `|panel(D)|` per day against the constant 200, 2015 → today.
> **A survivorship-biased panel slopes upward** — recent years look well covered because those
> companies still exist, while early years are thin because the dead were dropped.
> **A correct panel is roughly flat at ~200 across the entire history.**
>
> This one chart both proves the construction and *is* the disclosure slide. If it slopes, stop and fix
> the pipeline — do not proceed to Phase 3.

**5b. Point-in-time liquidity handling.** A stock can be in the index and in bhavcopy yet barely trade.
Any liquidity filter must use a **trailing** window only (e.g. median turnover over the prior 21 days).
A filter using full-sample statistics is look-ahead and would reintroduce bias through the back door.

**6. Write the coverage report.** Must state: symbols attempted, recovered by source, failed;
**how many of the 115 dropped names were recovered**; universe-days covered as a percentage, by year;
and a named list of what is still missing.

## Acceptance
- [ ] `validate_ohlcv(df)` passes.
- [ ] **TEST A (canaries):** DHFL, RCOM, JPASSOCIAT, YESBANK, SUZLON, IDEA, COX&KINGS each appear in the
      panel on a date when they were trading, and are absent after they stopped. CAIRN is absent after
      April 2017.
- [ ] **TEST B (flat coverage):** `|panel(D)|` is ≥ 185 in **both** 2016 and 2024, and the linear trend
      across 2015→2025 has **near-zero slope**. An upward slope means survivorship bias is still present
      — **this is a hard stop.**
- [ ] ≥ 300 of ~315 union symbols have at least one day of data (NSE should recover nearly all).
- [ ] `SERIES` filtering is applied and the choice (`EQ` only vs `EQ`+`BE`) is recorded.
- [ ] ISIN map exists; the four known renames resolve to a single continuous ISIN series.
- [ ] Corporate-action adjustment applied; **yfinance cross-check correlation > 0.99** on ≥ 30 large caps.
- [ ] Every |daily return| > 50% is either explained by a corporate action or listed for review.
- [ ] Re-running the phase re-downloads nothing (cache works).
- [ ] No `close <= 0`; no `high < low`; volume is non-negative.
- [ ] `delivery.parquet` exists; its first available date is stated in the report; `delivery_pct` is
      within `[0, 100]` where present.
- [ ] `size_proxy.parquet` exists and uses **only trailing** data — assert that recomputing it on a
      truncated panel gives identical values for the overlapping dates (a leak test).
- [ ] The report explicitly states that `sharesOutstanding` was **not** used, and why.

## Do NOT
- Do not compute features (Phase 3's job) beyond `size_proxy`.
- **Do not build the symbol list from anything that exists today** — download whole trading days and let
  the universe fall out of the intersection. This is the whole point.
- Do not silently drop failed days or symbols — every gap appears in the report.
- Do not fill missing prices by interpolation. A stock that did not trade did not trade.
- Do not attempt demerger/merger adjustment. Flag and disclose.

**Effort:** ~5.5h engineering + ~20 min unattended download (4 workers) / ~78 min sequential; ~450 MB.

---

# PHASE 3 — Feature panel, labels, splits

**Objective:** turn prices into the point-in-time feature panel and the prediction label, and prove
there is no look-ahead.

**Depends on:** P0 contracts, P1 membership, P2 prices. **Blocks:** P4, P6, P11.

## Standalone context
A **feature** is a number describing a stock on a day, computed only from information available by then.
The **label** is what we are trying to predict: tomorrow's return *relative to other stocks*.

**The timing contract — obey it exactly:**
> Features use data available before the trade → **trade at the *t+1* open** → the return is earned
> from ***t+1* open to *t+2* open**.

This guarantees a clean gap between the information used and the money earned.

**Per-field availability** (this replaces any single blanket rule):
| Field | Knowable at | Lag |
|---|---|---|
| OHLCV and everything derived from it | day *t*, 15:30 IST | 0 |
| `delivery_pct` | day *t*, ~19:00 IST — **post-close, but before the *t+1* open** | 0 |
| `sector` | static (**not** point-in-time; reclassifications untracked — disclose) | 0 |
| `in_universe` | effective date, applied 1–3 days late (conservative) | 0 |

## Inputs
- `data/prices/ohlcv.parquet`, `data/prices/delivery.parquet`, `data/prices/size_proxy.parquet`,
  `data/universe/membership.parquet` (P1 — the liquidity-defined universe, schema unchanged)
  *(If missing: use `contracts.make_fake_ohlcv()` and `make_fake_membership()`; emit `delivery_pct` and
  `size_proxy` as NaN and note it.)*
- **Sector mapping — 78% automated, do NOT hand-type it.** *(Verified live 2026-09-02.)*
  Download `https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv` → 752 names,
  header `Company Name, Industry, Symbol, Series, ISIN Code`. **Join on ISIN**, not symbol — our panel is
  ISIN-keyed (P2), so renames resolve automatically.
  - **246 of our 315 union symbols are covered directly (78%).**
  - **~69 are not** — the delisted and renamed names (`DHFL, CAIRN, CMC, GRUH, COX&KINGS, AMTEKAUTO,
    HDIL, BHARATFIN, …`), which NSE's current list cannot contain. Four resolve via the rename map;
    classify the remaining **~65 by hand** (~20–30 min; most are obvious).
  - **Use NSE's 22 official industries verbatim** — do not invent categories:
    Automobile and Auto Components · Capital Goods · Chemicals · Construction · Construction Materials ·
    Consumer Durables · Consumer Services · Diversified · Fast Moving Consumer Goods ·
    Financial Services · Forest Materials · Healthcare · Information Technology ·
    Media Entertainment & Publication · Metals & Mining · Oil Gas & Consumable Fuels · Power · Realty ·
    Services · Telecommunication · Textiles · Utilities
  - ⚠️ **Disclose:** the classification is **current, not point-in-time** — a company reclassified since
    2015 carries today's label throughout. Acceptable, because sector drives only *optional*
    neutralization and red-team test 7. State it in the report; do not hide it.

## Outputs
- `data/panel/features.parquet`, `data/panel/labels.parquet`, `data/panel/splits.json`
- `reports/p3_panel_report.md`

## Steps

**1. Compute returns** from adjusted close. Guard against zero/negative prices.

**2. Compute the ten features.** All windows are **trailing**. All are cross-sectionally comparable.

| Feature | Definition |
|---|---|
| `mom_21` | 21-day return, skipping the most recent day (`close[t-1]/close[t-22] - 1`) |
| `mom_126` | 126-day return, skipping the most recent 21 days |
| `rev_5` | −(5-day return) — short-term reversal |
| `vol_21` | std-dev of daily returns over 21 days, annualized |
| `beta_63` | slope of a 63-day regression of stock return on the equal-weight universe return |
| `amihud_21` | mean over 21 days of `abs(return) / (close × volume)`, ×1e6 |
| `turnover_21` | mean over 21 days of `close_raw × volume_raw`, log-transformed |
| `dist_52wh` | `close / max(close, 252 days) − 1` (≤ 0 by construction) |
| `max_ret_21` | max single-day return over the last 21 days (the "lottery" feature) |
| `delivery_pct` | join from `data/prices/delivery.parquet` (P2 step 4b). **Where unavailable — likely before ~2020 — leave NaN and state the first available date in the report.** Do not fabricate or back-fill it |
| `size_proxy` | join from `data/prices/size_proxy.parquet` (P2 step 4c) — trailing-turnover stand-in for market cap. **Never use current shares outstanding**; that is a look-ahead |

**3. Compute labels.** For `h ∈ {1,2,3,5,10,21}`: `fwd_ret_h = open[t+1+h]/open[t+1] − 1`.
Then, for each date, **cross-sectionally demean within the in-universe set** →
`fwd_ret_h_demeaned`. That demeaned value is the label — it measures "did it beat its peers," not
"did the market rise."

**4. Mask to the universe.** Rows where `in_universe == False` are dropped from both frames.

**5. Write `splits.json`** exactly as in Section 0.4.

**6. Run the assertion suite.** A data pipeline without assertions is a leak generator.
- Cross-section size per day is plausible (≥ 100 after 2016; log any day below).
- No NaN label where a stock is in-universe and traded.
- `dist_52wh ≤ 0` everywhere.
- `vol_21 > 0` everywhere it is non-NaN.
- No duplicate `(date, symbol)`.
- **Extreme returns:** flag daily moves > 50% into the report for human review. **Do not auto-drop and
  do not winsorize** — Indian mid-caps genuinely move like that, and silently clipping them would
  distort `max_ret_21`, which exists precisely to capture that behaviour.

**7. The look-ahead self-test — the most important test in this phase.**
> Take `mom_21`. Compute its RankIC against `fwd_ret_1_demeaned`. Now shift the **entire feature panel
> forward by one day** and recompute. The IC must **change**. If a feature's IC is invariant to a
> one-day shift, the pipeline is time-symmetric somewhere, which means it is leaking.

Additionally: compute the IC of a **deliberately leaky** feature — `fwd_ret_1` used as its own predictor
— and confirm it produces an absurd IC near 1.0. This proves the measurement machinery can *detect*
leakage when it is present, which is what makes the negative result on real features meaningful.

## Acceptance
- [ ] Both validators pass.
- [ ] Every assertion in step 6 passes or is explicitly logged with a count.
- [ ] The shift test in step 7 shows a materially different IC.
- [ ] The leaky-feature test yields `|RankIC| > 0.9`.
- [ ] `reports/p3_panel_report.md` documents: the sector-mapping caveat, the `delivery_pct`
      availability decision, extreme-return counts, and any day with a thin cross-section.

## Do NOT
Do not build a backtester. Do not compute any metric on HOLDOUT dates. Do not winsorize.

**Effort:** ~3h

---

# PHASE 4 — Backtester engine

**Objective:** one deterministic, parameterized engine that scores a signal. Everything downstream
calls it.

**Depends on:** P0, P3 panel. **Blocks:** P6, P9, P10, P11, P12.

## Standalone context
A **backtest** replays history: *"if I had used this signal every day, what would have happened?"* This
is **one engine with switches**, called from eight places (quick screening, fresh-fold confirmation,
the full battery, marginal-IC, the rationed holdout peek, red-team stress tests, portfolio combination,
and the ablation study). Build it once, parameterized.

## Inputs
- `data/panel/features.parquet`, `labels.parquet`, `splits.json`
  *(If missing: `contracts.make_fake_*`. The fake labels contain one feature with a known IC ≈ 0.04 —
  use it to prove the engine can detect a real signal.)*

## Outputs
- `src/backtester.py`, `tests/test_p4_backtester.py`

## The interface — build exactly this
```python
def backtest(
    signal: pd.DataFrame,          # date × symbol, one score per stock per day
    split: str,                    # "train"|"val_a"|"val_b"|"holdout"|"train+val_a"
    horizon: int = 1,
    extra_lag: int = 0,            # shift the whole signal forward N extra days (red-team test 5)
    cost_bps: float = 0.0,
    neutralize: str | None = None, # None | "sector"
    subsample: dict | None = None, # {"years":[2018,2019]} | {"size_tercile":"large"} |
                                   # {"regime":"bear"} | {"min_turnover": 1e7} |
                                   # {"exclude_symbols":[...]}
    purge_days: int = None,        # defaults to horizon
    embargo_days: int = 5,
) -> Metrics                       # the dict shape in Section 0.5
```

## Steps

**1. Align and clean.** Join signal to labels on `(date, symbol)`. Drop days with fewer than 20 valid
stocks (a rank correlation on 8 names is noise).

**2. Cross-sectional standardization.** Rank-transform the signal within each day to `[-1, 1]`.
If `neutralize == "sector"`, demean within sector first.

**3. Core metrics.**
- `rank_ic` — mean daily Spearman correlation between signal and the demeaned forward return.
- `ic` — same with Pearson.
- `icir` — `mean(daily_ic) / std(daily_ic)`.
- `t_stat` — `mean(daily_ic) / (std(daily_ic) / sqrt(n_days))`.
- `sign` — `+1` if `rank_ic > 0` else `-1`.

**4. Long-short portfolio (secondary).** Top quintile long, bottom quintile short, equal-weight,
dollar-neutral. Daily return, then `sharpe`, `ann_return`, `mdd`, and `turnover` (mean absolute weight
change). Subtract `cost_bps × turnover` per side.

**5. Decay curve.** Repeat the RankIC calculation for `h ∈ {1,2,3,5,10,21}`.

**6. Purge and embargo — non-negotiable.**
> Because a forward return spans several days, a training row near a test boundary can have a label
> window that overlaps the test period. **Purge** drops those overlapping rows; **embargo** additionally
> skips `embargo_days` after each test window before using data again.

Implement as a reusable function; Phase 6's CSCV will call it too.

**7. Holdout protection.** If `split == "holdout"`, require an explicit keyword
`i_have_a_peek_token=True`. Raise otherwise. Phase 6 owns the token issuance; this is a tripwire.

## Acceptance
- [ ] Random noise as signal → `|rank_ic| < 0.01`, `|t_stat| < 2`.
- [ ] The known-good fake feature → `rank_ic` within ±0.01 of its planted value.
- [ ] Using `fwd_ret_1` as the signal → `rank_ic > 0.9` (the engine can see leakage).
- [ ] Negating a signal exactly negates `rank_ic` and flips `sign`.
- [ ] `extra_lag=1` measurably changes results on a signal with genuine short-horizon predictive power.
- [ ] Increasing `cost_bps` monotonically reduces `sharpe`.
- [ ] Calling with `split="holdout"` without the token raises.
- [ ] Purge+embargo demonstrably removes the expected number of rows for `horizon=5`.
- [ ] Two identical calls return bit-identical results.

## Do NOT
Do not implement Deflated Sharpe, PBO, CSCV, or the trial ledger — those are Phase 6. Do not call an
LLM. Do not decide accept/reject; this engine only *measures*.

**Effort:** ~4h

---

# PHASE 5 — Operator library and AST tools

**Objective:** the safe formula toolbox the Coder agent builds from, plus tree analysis for complexity
and duplicate detection.

**Depends on:** P0. **Blocks:** P8, P10.

## Standalone context
Formulas are built from a fixed set of operators (the WorldQuant "Alpha101" style), not arbitrary code.
Example: `rank(ts_mean(volume,5)) * sign(close - open)`.

> ### ⚠️ This is a SAFETY feature, not a convenience
> **Every operator must be causal** — `delay` looks backward, `ts_mean` averages a *trailing* window,
> `rank` compares today's stocks to each other today. **No operator may reach forward in time.**
> This makes formula-level look-ahead *structurally impossible* rather than *hopefully caught*.
> If you add an operator, you must prove it is causal.

## Inputs
None beyond a panel to evaluate against (`contracts.make_fake_features()` suffices).

## Outputs
- `src/operators.py`, `src/ast_tools.py`, `tests/test_p5_operators.py`

## Steps

**1. Implement the operator set.** All operate on `date × symbol` frames.

*Cross-sectional (same-day):* `rank(x)` · `scale(x)` · `zscore_cs(x)` · `demean_cs(x)` ·
`sector_neutral(x, sector)`
*Time-series (strictly trailing):* `delay(x,d)` · `delta(x,d)` · `ts_mean(x,d)` · `ts_std(x,d)` ·
`ts_min(x,d)` · `ts_max(x,d)` · `ts_rank(x,d)` · `ts_sum(x,d)` · `ts_argmax(x,d)` ·
`correlation(x,y,d)` · `covariance(x,y,d)` · `decay_linear(x,d)`
*Element-wise:* `add · sub · mul · div · pow · log · abs · sign · min · max · signed_power` ·
**`if_else(cond, a, b)`** · **`ts_product(x, d)`**

`div` and `log` must guard against zero and negatives (return NaN, never raise).

> **`if_else` is the highest-value operator in the library** — it alone unlocks ~11 more Alpha101
> formulas (#1, 7, 9, 10, 21, 23, 24, 27, 46, 49, 51), all of which are conditional. It is element-wise
> and therefore trivially causal, ~10 lines. `ts_product` (trailing) unlocks #29. Both must still pass
> the causality test in the acceptance criteria.

**Derived-field idioms** to document alongside the operators, so the Coder agent knows them:
- `adv{d}` (Alpha101's average daily dollar volume) → `ts_mean(mul(volume, close), d)`
- `IndNeutralize(x, IndClass.*)` → `sector_neutral(x, sector)` — our 22 NSE industries are coarser than
  Alpha101's sub-industry, but the operation is the same and remains valid
- `avg_trade_size` → `div(volume, n_trades)` — a genuine microstructure feature yfinance cannot give us

**2. Parser and evaluator.** Parse a formula string into an AST; evaluate against a panel. Use Python's
`ast` module with a **strict whitelist** — permit only `Call`, `Name`, `Constant`, `BinOp`. Reject
attribute access, subscripts, comprehensions, lambdas, imports. Any name not in the operator table or
the field table is an error.

**3. Canonicalization** (for duplicate detection). Produce a normalized string: sort commutative
operands deterministically, fold constant arithmetic, normalize numeric literals. `a*b` and `b*a` must
canonicalize identically.

**4. Complexity metrics.** `{"nodes": int, "depth": int, "free_params": int}` where `free_params`
counts numeric literals — the knobs available for overfitting.

**5. Fingerprint for fast bucketing.** A cheap hash from the sorted multiset of operators + depth + the
set of leaf fields. Two formulas with different fingerprints cannot be duplicates; matching
fingerprints go to exact canonical comparison.

**6. The alpha zoo — `src/zoo.py` (REQUIRED, not just test fixtures).**
The pre-filter's structural novelty check asks *"is this formula secretly one that already exists?"* —
which needs an actual reference set to compare against. Provide **~35 formulas**:
- **25 transcribed from Kakushadze's *101 Formulaic Alphas*** (arXiv 1601.00991). **Audited: ~39 of
  #1–60 are expressible with our operator set** — `vwap` is available (P2) and `adv{d}` is an idiom, so
  the earlier concern was unfounded. Confirmed-expressible set to draw from:
  **#2, 3, 4, 5, 6, 8, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 25, 26, 28, 30, 32, 33, 34, 35, 38,
  40, 41, 42, 43, 44, 45, 50, 52, 53, 54, 55, 57, 60.**
  With `if_else` added, the conditional ones (#1, 7, 9, 10, 21, 23, 24, 27, 46, 49, 51) also become
  available. **Skip #56** — it needs true market cap, which we do not have. Disclose that.
- **~10 classical factors:** 12-1 momentum, short-term reversal, low-volatility, illiquidity, lottery,
  52-week-high proximity, turnover, beta, size, volume-shock.

Each entry: `{"name","formula","canonical","fingerprint","source"}`. Expose
`is_zoo_duplicate(formula, threshold) -> (bool, matched_name)` using the two-stage fingerprint→canonical
comparison from step 5.

**This doubles as the crowding defense:** a signal that is a known published alpha in disguise is, by
definition, crowded — and crowded signals decay fast.

## Acceptance
- [ ] Every operator has a unit test on a hand-computed 5×3 panel.
- [ ] **The causality test (mandatory):** for every time-series operator, changing a *future* value in
      the input must **not** change any earlier output value. Assert this for all of them.
- [ ] `rank` produces values in `[0,1]` with no NaN where input is non-NaN.
- [ ] The parser rejects `__import__('os')`, `close.values`, `[x for x in y]`, and `lambda x: x`.
- [ ] `canonical("a*b") == canonical("b*a")`.
- [ ] `complexity` returns the correct node count on a hand-drawn tree.
- [ ] All ~35 zoo formulas parse, evaluate, and produce finite values on the fake panel.
- [ ] `if_else` and `ts_product` pass the causality test alongside every other operator.
- [ ] `is_zoo_duplicate` returns `True` for a zoo formula with its operands commuted, and `False` for a
      genuinely different formula using the same fields.

## Do NOT
Do not call an LLM. Do not backtest. Do not add any operator that references a future index — if you
cannot pass the causality test, delete the operator.

**Effort:** ~5h (was 4h; the zoo adds ~1h)

---

# PHASE 6 — Statistical gates and the trial ledger

**Objective:** the honesty machinery — Deflated Sharpe, PBO via CSCV, the multiple-testing ledger,
marginal IC, and the rationed holdout.

**Depends on:** P0, P4 backtester. **Blocks:** P10, P11, P12.

## Standalone context

> **The core problem.** If you test **N worthless** signals, the best one's t-statistic will be of order
> **√(2 ln N)** *purely by chance*: **N=20 → 2.45 · N=100 → 3.03 · N=200 → 3.26.** At 200 attempts, your
> best formula clears a "t > 3" bar with nothing there at all. Every gate here exists to price that in.

> ⚠️ **P6-UPDATE (measured) — √(2 ln N) is a CEILING, not the expected best t-stat.** It is the
> asymptotic upper bound on the maximum of N standard normals. The **realised** maximum centres about
> **0.5 lower**, and it is the realised maximum the gate must actually beat. Monte Carlo, 20,000 draws
> per N:
>
> | N | realised E[max] | √(2 ln N) | Bailey-LdP E[max] |
> |---|---|---|---|
> | 5 | 1.168 | 1.794 | 1.193 |
> | 20 | 1.868 | 2.448 | 1.901 |
> | 200 | **2.744** | 3.255 | 2.766 |
> | 500 | 3.038 | 3.526 | 3.053 |
>
> The number that actually justifies every gate here is the **tail**, not the mean:
> **P(best-of-N pure-noise t-stat > 3.0)** = **0.7%** at N=5 · **2.7%** at N=20 (our variant cap) ·
> **12.6%** at N=100 · **23.6%** at N=200 · **49.1%** at N=500 (200,000 Monte-Carlo searches per
> point). At 500 variants a "t > 3" bar is a **coin flip against pure noise**.
>
> Two consequences, both load-bearing:
> 1. **The deflator is Bailey-López de Prado `E[max SR]`, never √(2 ln N).** BLdP tracks the true order
>    statistic to ~0.03; the bound overshoots by ~0.5. Deflating by the bound over-rejects genuine
>    signals — measured: a real signal found in 5 trials with **t = 7.07** scores **DSR 0.9952 (pass)**
>    under BLdP and **DSR 0.6579 (reject)** under a √(2 ln N) deflator.
> 2. **The headline acceptance test's band is 2.5–4.2, not "≈3.3".** The realised best-of-200-noise
>    t-stat measures **2.74**; a band centred on 3.26 would fail on correct code.
>
> Use "**of order** √(2 ln N)" in the write-up and slides, and quote 2.74 as the measured value with
> 3.26 named as the ceiling. The load-bearing claim is unchanged and unweakened: *the Deflated Sharpe
> must reject the best of 200 noise signals*, and it does — **DSR 0.477**.

**Gate B runs in this exact order, and the order is load-bearing:**
1. **Orthogonalize** against the existing factor book → the *residual* signal.
2. **Novelty** — is the residual's marginal IC meaningful? Kill clones here.
3. **Statistics** — Deflated Sharpe **on the residual**, t > 3, PBO.
4. **Rationed holdout peek** — only now, it is counted, and it scores the **residual**.

*Why novelty first:* step 4 spends an **irreplaceable** holdout peek while step 2 is free and already
computed. Never spend a peek on a signal that is about to be rejected as a momentum clone.
*Why the residual:* the fitness object was always *"deflated, holdout-gated, **orthogonalized marginal**
IC"* — one composite. Deflating the raw signal and *separately* glancing at marginal IC is a different,
weaker calculation.

> **P6-UPDATE — the residual rule binds step 4 as well, not only step 3.** The rationed peek scores the
> **residual**, the same object steps 2–3 judged. Peeking on the raw signal lets a *partial clone* — one
> with real but small marginal IC and most of its raw IC explained by the book — be confirmed on
> HOLDOUT by the very book it was supposed to be measured against, and it leaves the "did it collapse
> out of sample?" check comparing a **raw** holdout IC against a **residual** VAL IC, mixed units that
> can never bite. Measured on such a partial clone: raw holdout RankIC **0.0320**, residual holdout
> RankIC **0.0196** — a peek on the raw signal overstates the surviving edge by **63%**, and it spends
> an irreplaceable peek to do it.

## Inputs
- `src/backtester.py` from P4 *(if missing, stub it: a function returning a `Metrics` dict with
  plausible random values, seeded — the statistics are what this phase is about)*
- The panel from P3 *(or fixtures)*

## Outputs
- `src/gates.py`, `src/ledger.py`, `data/ledger.db` (SQLite), `tests/test_p6_gates.py`

## Steps

**1. Trial ledger (`ledger.py`) — SQLite, append-only.**
```sql
CREATE TABLE trials (
  trial_id INTEGER PRIMARY KEY, thesis_id TEXT, formula_hash TEXT, canonical_ast TEXT,
  timestamp TEXT, split_used TEXT, rank_ic REAL, sharpe REAL, t_stat REAL, n_days INTEGER,
  counts_as_trial INTEGER, rejection_reason TEXT);
CREATE TABLE holdout_peeks (
  peek_id INTEGER PRIMARY KEY, card_id TEXT, timestamp TEXT, result_json TEXT);
```
API: `record_trial(...)`, `n_trials(thesis_id=None)`, `trial_sharpes(thesis_id=None)`,
`request_holdout_peek(card_id) -> token | None` (returns `None` once `HOLDOUT_PEEK_BUDGET` is spent).

> **The selection-vs-rejection distinction — implement this precisely.** A run only inflates the
> false-discovery rate if it is used to **pick a winner**. Quick screening across variants is selection
> (`counts_as_trial=1`). Red-team stress tests can only **kill**, never promote — a filter that only
> rejects cannot raise your false-discovery rate, so `counts_as_trial=0`. Cost sweeps and lag tests are
> likewise rejection-only.

**No `DELETE` statement may exist in this module.** If trials can be removed, deflation is gameable.

**2. Effective trial count.** Raw N over-penalizes: 20 variants of `vol/ts_mean(vol,k)` for k ∈ 5…25 are
maybe 3 independent bets, not 20. Cluster by canonical-AST similarity **and** by correlation of the
trial Sharpes; return an effective count.

> **P6-UPDATE — two rules that make this count real.**
> 1. **The DSR must be handed the effective count, not `max(effective, raw N)`.** Since `n_eff ≤ N` by
>    construction, taking that max silently restores raw N and this whole step becomes decorative.
>    Measured: 20 knob-variants of one shape → **effective count 2.0**, raw 20.
> 2. **Scope is the WHOLE ledger, with the thesis as a floor.** P10 promotes the best card *across*
>    theses, so the population the winner was maximised over is the run-wide one. Deflating only
>    within the thesis gives a brand-new thesis **N = 1 → E[max SR] = 0 → no deflation at all**, however
>    much search preceded it — the exact hole this phase exists to close. Measured: 40 noise variants
>    searched under 40 different thesis_ids, winner gated under a fresh 41st thesis. Its raw t-stat is
>    **−3.000** — it clears the naive `t > 3` bar from pure noise. Thesis-local scope → E[max SR] = 0,
>    DSR = 1.000, **accept**. Run-wide scope → effective N = 41, E[max SR] = **0.0728**, DSR = **0.789**,
>    **reject**. Report both counts on the card (`n_trials_within_thesis`, `n_trials_global`).

**3. Deflated Sharpe Ratio** (Bailey & López de Prado). Inputs: observed Sharpe, number of trials,
variance of the trial Sharpes, skew and kurtosis of the return series, sample length. Returns a
probability that the true Sharpe exceeds zero. Include the standard expected-maximum-Sharpe term
`E[max] ≈ σ_SR × ((1−γ)Z⁻¹(1−1/N) + γZ⁻¹(1−1/(N·e)))`.

> **P6-UPDATE — floor `σ²_SR` at `1/T`.** A sample of trial Sharpes cannot honestly be *less* dispersed
> than pure estimation noise, and `σ_SR = 0` (identical or near-identical trial SRs — common early in a
> run) collapses `E[max SR]` to 0 and switches deflation **off** exactly when a thin ledger makes it
> most needed. `1/T` is the asymptotic sampling variance of a zero-mean IR estimate; it is also the
> fallback when fewer than two prior trials exist. Measured: 40 identical trial IRs at N=100, T=900 →
> `E[max SR]` **0.0 before, 0.0844 after**.

**3b. Walk-forward validation — the workhorse (decision C9).**
Walk-forward is the *primary* out-of-sample method; CSCV exists only to produce one honest PBO number.
Implement `walk_forward(signal, start, end, train_years=3, step_months=6, purge_days, embargo_days)`:
an **expanding** training window, stepping the test window forward, producing a **sequential
out-of-sample series** of daily ICs. Return `(oos_ic_series, per_fold_metrics)`.

*Why it is the workhorse:* it is simple, faithful to how the signal would actually be used live, and it
yields the continuous OOS series the decay and regime checks consume. CSCV cannot do that — it produces
a *distribution* over recombined folds, which is what PBO needs and nothing else.

Purge and embargo apply inside **every** fold boundary.

**4. CSCV → PBO.** Split the combined TRAIN+VAL_A series into `S=8` blocks; for every way of choosing
`S/2` as in-sample, rank strategies in-sample and observe the winner's out-of-sample rank. **PBO** is
the fraction of splits where the in-sample winner lands below the out-of-sample median. Apply purge and
embargo inside every split.

**5. Orthogonalization / marginal IC.** Regress the candidate signal on the existing book
cross-sectionally each day; keep the residual; compute the residual's RankIC. Handle an empty book
(marginal IC = raw IC).

**6. `gate_b(card, book, ledger, signal=…)`** — runs steps 1–4 of the Gate B order above and returns
`(verdict, reasons, audit_dict)`.

> **P6-UPDATE — the evaluated `signal` is a required fourth argument.** A card carries a `formula`
> *string*, not values, and Gate B cannot evaluate it from either of its other two arguments: P5's
> parser accepts only base OHLCV fields (`close, volume, high, low, open, vwap, returns, …`) — the P3
> feature panel contains **none** of them (`ParseError: unknown field: 'mom_21'`), and the prices they
> need live in a third file, `data/prices/ohlcv.parquet`, that Gate B is not given. Evaluation is
> P10's job; Gate B judges the evaluated frame. Accepted as `signal=` or as `card["_signal"]`.

**7. Pre-registered sign check.** `check_sign(pre_registered_sign, realized_sign) -> bool`.
A mismatch is a **thesis failure**, not an invitation to flip the sign. This is a hard reject.

## Acceptance
- [ ] Ledger is append-only; module contains no `DELETE`.
- [ ] `request_holdout_peek` returns a token exactly `HOLDOUT_PEEK_BUDGET` times, then `None` forever.
- [ ] **The headline test:** generate 200 pure-noise signals, take the best. Its raw t-stat should land
      in **2.5–4.2** — of order √(2 ln 200) = 3.26, which is the *ceiling*; the realised value measures
      **2.74** (see the P6-UPDATE above). The **Deflated Sharpe must reject it**.
- [ ] A genuinely predictive signal found in 5 trials passes the same gate.
- [ ] Effective trial count for 20 near-identical formulas is materially below 20, **and that count is
      what the DSR is deflated by** (not raw N).
- [ ] Deflation is scoped to the **whole ledger**: a noise winner selected across 40 theses is rejected
      even when gated under a brand-new thesis whose own trial count is 0.
- [ ] The **rationed peek scores the residual**, not the raw signal.
- [ ] PBO ≈ 0.5+ for noise; low for a real signal.
- [ ] Marginal IC of a factor against *itself* as the book is ≈ 0.
- [ ] `check_sign(+1, -1)` is `False`.

## Thresholds (fixed here so P10 and the slides quote one set)
`T_STAT_BAR = 3.0` (config, spec-given). The rest were open and are now pinned:

| Constant | Value | Basis |
|---|---|---|
| `MIN_MARGINAL_IC` | 0.01 | Novelty floor. Measured sampling noise of a daily-IC mean over VAL_A (T = 913): **0.00436**, so 0.01 is **2.3σ** — above float-residual noise, below genuine marginal alpha (0.02–0.03). |
| `DSR_MIN` | 0.95 | Bailey-LdP's own convention. **Note:** the illustrative AlphaCard in §0.5 shows `deflated_sharpe: 0.9` with `verdict: accept`; that example is not a threshold, and 0.95 governs. |
| `PBO_MAX` | 0.50 | PBO > 0.5 is worse than a coin. Measured null: **0.486 ± 0.013** over 300 noise matrices. |
| `MIN_DSR_SAMPLE` | 60 | Below ~60 scored days the skew/kurtosis terms in the DSR denominator are unreliable. |

## Do NOT
Do not call an LLM. Do not implement the red-team menu (Phase 9). Do not read HOLDOUT except through
`request_holdout_peek`.

**Effort:** ~5h

---

# PHASE 7 — Memory stores

**Objective:** the six persistent stores that let the system improve across generations.

**Depends on:** P0. **Blocks:** P8, P10, P12.

## Standalone context
"Memory" is **not one store** — five consumers have incompatible needs, and one of them (the trial
ledger feeding the Deflated Sharpe) **must be exact and complete**, because a multiple-testing count
cannot be "approximately right." So exact and semantic stores are physically separate.

## Inputs
None. *(P6 owns the trials table; this phase owns the other five stores and may import P6's ledger.)*

## Outputs
- `src/memory.py`, `data/memory.db`, `data/bandit_state.json`, `artifacts/cards/`,
  `tests/test_p7_memory.py`

## Steps

**① Formula index** — SQLite table `formula_hash · canonical_ast · fingerprint · first_seen · outcome`.
API: `seen_exact(hash)`, `candidates_by_fingerprint(fp)`.

**② Lesson / edit-motif store** — the reusable knowledge.
```python
{"motif": "widen_ts_window",
 "parent_context": "volume-ratio factor, thesis horizon 3-5d, window was 1d",
 "outcome": "helped: RankIC 0.031 -> 0.038",
 "confidence": 0.7, "n_observations": 4, "family": "liquidity", "veto": False}
```
Two mechanisms, both required:
- **Asymmetric veto** — a high-confidence *failure* hard-blocks that motif in that context; a success
  only nudges a prior upward. Failures are more reliable evidence than successes in a noisy domain.
- **Confidence gating** — a lesson is not applied as a prior until `n_observations >= 3`.

Retrieval: **start with family + keyword filtering.** With a few hundred lessons that is sufficient.
Add embeddings only if retrieval is visibly poor — and if you do, use `sentence-transformers` with
plain numpy cosine. **Do not install a vector database.**

**③ Bandit state** — one JSON file, ~10 rows:
`family · n_pulls · cumulative_reward · tokens_spent · last_k_deltas`.
> **Mandatory: an exploration floor.** A family may be starved to 5% of budget, **never to 0%.**
> See the second-order-overfitting note below.

**④ Alpha Card store** — one human-readable JSON per card in `artifacts/cards/` plus a SQLite index
(`card_id · thesis_id · verdict · rank_ic · marginal_ic · generation · created_at`). Human-readable
matters: these are the demo artifact.

**⑤ Lineage** — a parent pointer on each card (`parent_card_id`, `edit_motif`). It is a tree, not a
general graph. Provide `lineage_path(card_id) -> list[card]`.

**⑥ The accepted book** — `data/book.parquet`, the actual `date × symbol × factor` values, because
orthogonalization needs numbers, not descriptions. API: `add_to_book(card_id, signal_df)`,
`get_book() -> DataFrame`.

## ⚠️ Guard against second-order overfitting
If Reflection writes *"momentum ideas fail"* after three failures and the Planner defunds momentum, an
irreversible decision has been made on **n=3**. That is overfitting the *search process* — invisible,
because it never appears in any backtest. Two defenses, both implemented here: **confidence gating**
(②) and the **exploration floor** (③). Document both in docstrings.

## Acceptance
- [ ] All stores survive a process restart (persistence works).
- [ ] A lesson with `n_observations=1` is **not** returned as an applicable prior; at 3 it is.
- [ ] A vetoed motif is excluded from retrieval in its context but not in a different context.
- [ ] The bandit never allocates 0% to any family, even after 50 simulated failures.
- [ ] `lineage_path` reconstructs a 4-generation chain correctly.
- [ ] Cards round-trip to JSON without loss and validate against the Section 0.5 schema.

## Do NOT
Do not call an LLM. Do not install a vector database. Do not add a `DELETE` path to the trial ledger.

**Effort:** ~3.5h

---

# PHASE 8 — LLM agents

**Objective:** the eight LLM roles, their prompts, model routing, and token accounting.

**Depends on:** P0. Optionally P5 (operators) and P7 (memory) — stub both if absent.
**Blocks:** P10.

## Standalone context
Eight agents, each the same underlying model given a different job, different instructions, different
tools. **Deterministic computations are NOT agents** — the backtester, the statistics and the novelty
check are plain code, so their verdicts cannot be talked around.

**Free-tier model routing.** ⚠️ **Do NOT hard-code a model ID.** `llama-3.3-70b-versatile` and
`llama-3.1-8b-instant` were reportedly **deprecated 17 June 2026** (sources conflict with Groq's own
models page). Read the ID from config and **probe availability at startup**, walking a fallback chain:

| Role | Preference order | Why |
|---|---|---|
| Hypothesis, Red-Team | `openai/gpt-oss-120b` → `qwen/qwen3-32b` → `llama-3.3-70b-versatile` | the two roles needing real reasoning |
| Coder, Judge, Reflection, Planner, Brief, Economics Reviewer | `openai/gpt-oss-20b` → `llama-3.1-8b-instant` | high-volume, cheap |
| Offline fallback | Ollama local (`qwen2.5-7b`) | zero-limit, no network |

### ⚠️ Budget reality — measured, and it constrains the design

Free-tier limits are **per organisation** (extra API keys do not multiply capacity), and **tokens-per-day
is the binding constraint**, not requests: large models get **100–200K TPD**, small models 200–500K TPD,
at **6,000–12,000 TPM**.

**Measured projection: ~16.6 LLM calls and ~26,500 tokens per thesis** (4,260 large + 22,260 small),
assuming 70% pass Gate A, 20% reach the Red-Team, ~8 variants average.

| Run size | Large tokens | Small tokens | Fits one day? |
|---|---:|---:|---|
| 50 theses | 213,000 | 1,113,000 | ❌ ~2× over on both |
| **20 theses** | 85,200 | 445,000 | ✅ **the practical ceiling** |

Throttling alone puts a 20-thesis run at **~74 minutes minimum wall clock**.

**Four requirements this imposes on P8:**
1. A **token-bucket throttle** respecting TPM, plus a TPD counter against a configured cap.
2. **Static-prefix prompts** — put the rubric, operator list and corpus brief *first* so they cache;
   cached tokens reportedly do not count toward limits.
3. **Keep the Judge and Coder prompts short** — they are ~11 of the 16.6 calls per thesis and dominate
   spend.
4. On TPD exhaustion, **fail cleanly into P10's checkpoint** so the run resumes tomorrow rather than
   restarting.

*This turns "alpha per token" from a slogan into a measured constraint we designed around: ~26,500
tokens per hypothesis explored, ~1,000 per formula variant, ~20 theses/day on free infrastructure.*

## Outputs
- `src/agents/{base,planner,librarian,hypothesis,economics,coder,judge,redteam,reflection}.py`
- `src/agents/prompts/*.txt`
- **`data/corpus/anomalies.json`** — the research corpus (see agent 2 below; ~40 entries)
- `.env.example` — documenting `GROQ_API_KEY`, `LLM_MODE`, `OLLAMA_HOST`
- `tests/test_p8_agents.py`

## The eight agents

**1. Planner** — picks the next idea-family and allocates budget. Bandit (from P7) does the arithmetic;
the LLM proposes genuinely *new* families and crosses elite theses. Returns
`{"family": str, "token_budget": int, "max_variants": 20, "rationale": str}`.

**2. Librarian (brief writer)** — summarizes retrieved corpus material **and past lessons from memory**
into a short brief. The memory half matters more: it stops the system re-proposing the idea it killed
three generations ago.

> ### ⚠️ You must BUILD the corpus — it does not exist yet
> The Librarian has nothing to retrieve from until you create `data/corpus/anomalies.json`. Task B
> lists "a research literature corpus" as an assumed resource, so a small honest one is required.
>
> **Build ~40 entries**, each:
> ```json
> {"name":"post-earnings-announcement drift","family":"fundamental",
>  "mechanism":"investors underreact to earnings surprises",
>  "counterparty":"attention-constrained retail and slow institutions",
>  "horizon_days":"20-60","evidence":"Bernard & Thomas 1989",
>  "known_decay":"weakened post-2000 in US large caps",
>  "tradeable_with_our_data": false}
> ```
> Sources are free: paper **abstracts** (arXiv, SSRN), the anomaly lists in Harvey–Liu–Zhu and
> Hou–Xue–Zhang, and Kakushadze's operator paper. **Abstracts and factor descriptions only — no
> paywalled full text, no scraping behind a login.**
>
> The `tradeable_with_our_data` flag matters: it lets the Librarian tell the Hypothesis agent *"this is
> a real anomaly but we have no fundamentals, so don't propose it"* — which stops the system burning
> tokens on ideas it structurally cannot implement.
>
> **Retrieval: keyword + family filtering.** With ~40 entries, embeddings are unnecessary. Do not
> install a vector database.

**3. Hypothesis (the researcher)** — the most important creative step. **Must** return all of:
```json
{"mechanism":"...","counterparty":"...","why_not_arbitraged":"...",
 "horizon_days":5,"regime":"calm","falsifiable_claim":"...",
 "pre_registered_sign": 1}
```
> ### The pre-registered sign — the project's headline mechanism
> The agent commits to the **direction** of the effect *before any data is touched*. Later, the realized
> direction must match, or the idea is **rejected as a thesis failure** — not flipped and kept.
> **Why:** every factor `f` has a mirror `−f`, so without pre-commitment you silently test both while
> logging one; and worse, an LLM shown the result first will happily invent a plausible mechanism for
> whatever the data showed, turning the "economic thesis" into narration of noise.
> **Implementation:** serialize the thesis, `sha256` it, store the hash with a timestamp **before** any
> backtest runs.

**4. Economics Reviewer (Gate A)** — scores the thesis against the five-part rubric, harshly. Missing
any element → reject. **Must run as a separate LLM instance from the Hypothesis agent** (different
client object, no shared conversation history). Models grade their own work generously; separating
author from judge removes a large bias cheaply.

**5. Coder** — thesis → formula string using only the P5 operator library. Returns
`{"formula": str, "rationale": str}`.

**6. Judge** — the Coder's critic inside the refinement loop. Reads the quick-test metrics and returns
`{"action": "refine"|"promote", "edit_motif": str, "reason": str}`. Its real output is the
**edit motif** — the *kind* of change to make ("widen the window to match the stated horizon") — because
that is the transferable knowledge memory stores.

**7. Red-Team** — *selects* which stress tests fit this signal from the fixed 11-test menu (Phase 9).
Returns `{"tests": [str], "rationale": str}`. **It never writes code**; it picks from a menu.

**8. Reflection** — writes the lesson and the edit motif to memory, and updates bandit priors.

## Cross-cutting requirements
- **`base.py`** provides `call_llm(role, prompt, schema) -> dict` with: retries, JSON-schema validation
  and repair, **token accounting per role**, a **token-bucket throttle** (TPM) and **TPD counter**, a
  **startup model-availability probe** walking the fallback chain, and a **hard budget stop** that
  raises a resumable `BudgetExhausted` rather than dying mid-write.
- Every prompt lives in `prompts/*.txt`, never inline — they will be iterated on.
- **Offline test mode:** `LLM_MODE=mock` returns canned responses from fixtures so the entire test
  suite runs with no network and no API key.

## Acceptance
- [ ] Every agent returns schema-valid JSON, or raises a clear error after retries.
- [ ] Full test suite passes with `LLM_MODE=mock` and no network.
- [ ] Hypothesis output containing no `counterparty` is **rejected** by the Economics Reviewer.
- [ ] Economics Reviewer demonstrably uses a separate client instance (assert on object identity).
- [ ] The sign hash is computed and stored before any backtest call in the test flow.
- [ ] Token accounting sums correctly per role; exceeding the budget raises.
- [ ] Coder output parses under P5's parser (or the mock returns a formula that does).
- [ ] `data/corpus/anomalies.json` has ≥ 35 entries and validates against its schema.
- [ ] The startup probe detects an unavailable model and falls through to the next in the chain.
- [ ] The TPM throttle demonstrably delays calls when the bucket empties (test with a tiny limit).
- [ ] `BudgetExhausted` is raised, not swallowed, and leaves no partial state write.
- [ ] Measured tokens-per-thesis in a mock run is within 2× of the 26,500 projection — if it is wildly
      higher, the prompts are too long and the Judge/Coder are the place to cut.
- [ ] Retrieval on `family="liquidity"` returns only liquidity-family entries.
- [ ] At least 10 corpus entries are marked `tradeable_with_our_data: false`, and the Librarian's brief
      visibly excludes them from what it suggests proposing.

## Do NOT
Do not implement the orchestration graph (Phase 10). Do not let an agent compute a verdict that
deterministic code should own. Do not hard-code an API key — use `.env`. Do not scrape paywalled
content for the corpus; abstracts and factor descriptions only.

**Effort:** ~6h (was 5h; the corpus adds ~1h)

---

# PHASE 9 — Red-Team test menu

**Objective:** the eleven parameterized falsification tests, and the survive/kill rule.

**Depends on:** P0, P4 backtester. **Blocks:** P10, P11.

## Standalone context
The Red-Team's job is to **destroy** the candidate. The LLM agent decides *which* attacks fit; **the
attacks themselves are pre-written parameterized backtests.** The agent chooses *what*, the code
computes *how much*. It never writes free-form code — that keeps every attack reproducible.

> **All eleven are rejection-only** — they can kill a candidate but never promote one. A filter that
> only rejects cannot raise the false-discovery rate, so **none of these runs counts as a trial.** Record
> them with `counts_as_trial=0`. (This is the answer to *"doesn't running 11 backtests per candidate
> blow up your trial count?"*)

## Outputs
- `src/redteam.py`, `tests/test_p9_redteam.py`

## The eleven tests

| # | Name | Call | Hunts |
|---:|---|---|---|
| 1 | `subsample_year` | one backtest per year | "it was one lucky year" |
| 2 | `regime_split` | bull / bear / high-vol subsamples | "only works in a bull market" |
| 3 | `size_tercile` | by `size_proxy` tercile (**trailing turnover, not market cap** — see P2 step 4c) | "it's a small-cap artefact" |
| 4 | `cost_sweep` | `cost_bps ∈ {5,15,30}` | "great gross, loses money net" |
| 5 | `extra_lag` | `extra_lag=1` | **hidden look-ahead** |
| 6 | `delivery_lag` | shift **only** `delivery_pct` by 1 day | **which field is the edge leaning on?** |
| 7 | `sector_neutral` | `neutralize="sector"` | "it's one industry bet" |
| 8 | `liquidity_filter` | `min_turnover` filter | "untradeable names" |
| 9 | `decay_curve` | `h ∈ {1,2,3,5,10,21}` | "the claimed horizon is fiction" |
| 10 | `sign_stability` | sign of RankIC per fold | "the direction flips around" |
| 11 | `universe_edge` | drop names ranked 150-200 by liquidity that month | "it only works on the illiquid fringe of the universe" |

**Test 6 is more diagnostic than test 5** and worth understanding: if RankIC survives a *global* one-day
lag but collapses when only `delivery_pct` shifts, you have **localized** the dependency to the one
field whose availability timing is genuinely ambiguous. It names the culprit instead of just flagging
that one exists.

## Survive rule
Survives **iff**: RankIC stays positive and significant across tests 1, 2, 5; does not collapse
(> 50% degradation) under test 4 at 15 bps or under test 5; and test 10 shows a consistent sign in
≥ 70% of folds. Return `{"verdict": "survives"|"killed", "failed_tests": [...], "results": {...}}`.

## Regime definition
Define regimes from the equal-weight universe index: **bull** = 63-day return > +5%; **bear** = < −5%;
**high-vol** = 21-day realized volatility in the top tercile of its own history *up to that date*
(expanding, never full-sample — a full-sample threshold is look-ahead).

## Acceptance
- [ ] All 11 run against a fixture signal and return the documented shape.
- [ ] A deliberately leaky signal is killed by test 5.
- [ ] A signal that works in only one year is killed by test 1.
- [ ] A signal with high turnover and thin gross edge is killed by test 4.
- [ ] Every red-team backtest is recorded with `counts_as_trial=0`.
- [ ] Test 11 uses the liquidity ranking from `universe_stats.parquet`, not a hard-coded symbol list.
- [ ] Regime labels use expanding-window thresholds only (assert no full-sample statistic).

## Do NOT
Do not let the LLM generate test code. Do not count these as trials. Do not touch HOLDOUT.

**Effort:** ~3h

---

# PHASE 10 — Orchestration graph

**Objective:** wire the nine stages into the running loop, with the variant cap, the fresh fold, and
the gate ordering enforced.

**Depends on:** P4, P5, P6, P7, P8, P9. **Blocks:** P11, P12.

## Standalone context
> **The rule the whole design obeys:** *agency where there is a **decision**; deterministic code where
> it is a **fixed computation**.* All verdict math is code with a fixed threshold — so nothing in the
> system can talk its way past a gate.

## Outputs
- `src/loop.py`, `tests/test_p10_loop.py`

## The graph
```python
orchestrate → retrieve → brief → ideate → gate_a_economics
gate_a:      pass → code            | reject → reflect
code → prefilter
prefilter:   ok   → tier1           | reject → reflect
tier1 → judge
judge:       refine → code          | promote → freshfold      # INNER LOOP, capped at 20
freshfold:   holds  → tier2         | fails   → reflect
tier2 → gate_b_novelty                                          # tier2 also ORTHOGONALIZES
gate_b_novelty: pass → gate_b_stats | reject → reflect
gate_b_stats:   pass → gate_c_redteam | reject → reflect
gate_c_redteam: survive → emit_card → reflect | reject → reflect
reflect → should_continue: continue → orchestrate | stop → END
```

## The three enforcement points — these are the phase's real content

**1. Variant cap (≤ 20 per thesis).** The `judge → code` edge maintains a per-thesis counter. At 20,
force `promote` with the best variant so far, or reject if none is viable.
> **Why:** the best of N worthless signals shows a t-stat of ≈ √(2 ln N) — **N=200 → 3.26**, which
> clears a "t > 3" bar from pure noise. And the pre-registered sign gives **zero** protection here,
> because all variants inherit the same direction and pass the check trivially.

**2. Fresh-fold confirmation.** The search runs entirely on **VAL_A**. The single promoted winner must
hold on **VAL_B**, which no variant ever touched. This converts within-thesis selection into a genuine
out-of-sample check **without spending a holdout peek**.

**3. Gate B ordering.** Orthogonalize → **novelty** → statistics → holdout peek. Never reverse it: the
statistics step spends an irreplaceable holdout peek, while novelty is free and already computed.

## Steps
1. Define `AlphaResearchState` (TypedDict): `budget_tokens_left · family · bandit_stats · candidate ·
   variant_count · population · memory · ledger · book · generation`.
2. Implement each node as `f(state) -> dict` (partial state update). LLM nodes call P8; tool nodes call
   P4/P5/P6/P7/P9.
3. Conditional edges read state and return the next node name.
4. Compile with `SqliteSaver` checkpointing so the outer loop can pause and resume.
5. **Stop rule:** token budget exhausted **OR** K=3 consecutive generations adding < ε
   novelty-adjusted marginal IC **OR** a hard generation cap. Whichever fires first.
5b. **Curriculum (improvement mechanism).** Every N generations, the Red-Team's *mandatory* test set
   rotates to a harder regime slice — e.g. force the 2020 COVID window or the 2018 credit-crisis window
   into tests 1 and 2 rather than letting the agent choose. Prevents candidates surviving only because
   the agent picked gentle stresses.
5c. **Meta-check: gates auto-tighten (improvement mechanism).** Track rolling FDR from P12. If it rises
   above a threshold, raise `T_STAT_BAR` and the marginal-IC minimum by a fixed step, and log the
   change with its trigger. **This is a graded requirement** — the prompt asks how the system improves
   over iterations, and a system that tightens its own standards when it starts making mistakes is a
   direct answer.
6. **Portfolio runs once, after the graph terminates** — it is a post-process over the accepted book,
   not a node. (Task B grades the *signal*; the "does this add information?" question is already
   answered inside Gate B.)

## Acceptance
- [ ] Runs end-to-end in `LLM_MODE=mock` with no network.
- [ ] Variant counter never exceeds 20; assert on a thesis whose Judge always says "refine".
- [ ] Assert **no VAL_B call occurs** before a `promote` (instrument the backtester).
- [ ] Assert `gate_b_novelty` is always called before `gate_b_stats` (instrument call order).
- [ ] A rejected card still reaches `reflect` and is written to memory.
- [ ] Checkpoint/resume produces identical state.
- [ ] Exhausting the token budget stops the loop cleanly, without a partial write.
- [ ] Portfolio is not a graph node.

## Do NOT
Do not put verdict logic in an LLM node. Do not let any node read HOLDOUT outside P6's peek API. Do not
implement MCTS or code-based evolution — those are roadmap items, deliberately excluded (see the
"Explicitly out of scope" section below).

**Effort:** ~5h

---

# PHASE 11 — Demo run: one good card, three bad examples

**Objective:** produce the presentation's evidence.

**Depends on:** P10 (or, degraded, P4+P6+P9 with hand-written formulas). **Blocks:** P13.

## Standalone context
Trexquant explicitly asks: *"show us a real example of it producing a bad signal or a bad thesis, and
explain what you would change in response."* This phase produces that. Each example is told in three
beats: **naive result → the system catches it → the fix.**

## Outputs
- `artifacts/cards/good_*.json`, `artifacts/cards/bad_*.json`
- `reports/p11_demo.md`, plots per example
- `artifacts/portfolio_report.md` (the off-loop combination step)

## The four deliverables

**① One GOOD card.** Runs the real loop until an accepted card emerges. Full thesis, formula, all
metrics, audit, red-team report, lineage.

**② BAD — data integrity: the universe source was structurally broken (open with this one).**
Show the supplied constituent file passing every superficial check — 37 snapshots, exactly 200 names
each, dead companies retained — while **80 of today's 200 NIFTY 200 constituents never appear in it at
all** (RELIANCE, TCS, SBIN, MARUTI, TATASTEEL, ONGC...), every one with **zero inclusion/exclusion
events**: the signature of a change-log replayed onto an incomplete base seed, then padded back to 200
with mid-caps.
> **Why it lands:** the missing names are systematically the largest and most liquid stocks in India,
> so every liquidity, size and capacity feature would have been computed on a biased sample.
> **How it was caught: external reconciliation against NSE's own list — not by any statistical gate.**
> DSR, PBO, purge/embargo and the lag test would all have passed it silently, because it contaminates
> the *universe*, not any one factor. Nothing would have thrown an error.
> **The fix:** abandon constituent data entirely; rebuild the universe from daily bhavcopy as the top
> 200 by trailing turnover — point-in-time and survivorship-free by construction (Phase 1).

**③ BAD — statistical: look-ahead leakage.**
Build a factor that uses same-day or forward information. Show a spectacular Tier-1 RankIC, then show
red-team test 5 (`extra_lag`) destroying it. **The teaching point:** the Deflated Sharpe would have
*passed* it. Statistical gates catch **over-searching**, not **cheating** — those are different
problems requiring different mechanisms.

**④ BAD — economic: "right answer, wrong reason".**
A data-mined signal with a good IC whose realized sign is **opposite** to its pre-registered sign.
Rejected as a **thesis failure**. No purely statistical gate would ever have flagged it.

**⑤ Portfolio post-process.** Over whatever cards were accepted:
- correlation matrix of the accepted signals;
- a **low-correlation combination** (equal-risk or inverse-correlation weights), reporting combined vs
  individual RankIC — the combined set should beat any single member;
- **regime weight-gating** — recompute weights conditional on the regime labels from P9 (bull / bear /
  high-vol, expanding-window thresholds only), so the book leans on the signals suited to current
  conditions. Report per-regime weights and whether gating improves combined ICIR.

If fewer than 3 cards were accepted, say so plainly and demonstrate both mechanisms on a synthetic set.

## Acceptance
- [ ] At least one genuinely accepted card exists with a complete audit trail.
- [ ] All three bad examples are reproducible from a seed and a single command.
- [ ] Each bad example's report shows: the naive metric, the catching mechanism with its number, and the
      stated fix.
- [ ] The broken-universe example demonstrates that DSR/PBO **pass** it — this is its whole point.
- [ ] Every card validates against the Section 0.5 schema.

## Do NOT
Do not fabricate results. If the loop fails to produce an accepted card, **report that honestly** —
a system that rejects everything is a finding, and the prompt explicitly values a partial result you
understand over a complete one you cannot defend.

**Effort:** ~4h

---

# PHASE 12 — System evaluation and ablation

**Objective:** grade the **factory**, not the signal. This is a directly graded deliverable.

**Depends on:** P4, P6, P9, P10. **Blocks:** P13.

## Standalone context
Trexquant asks how you would **evaluate the system** and **improve it over iterations**. Grading one
signal is the Alpha Card. Grading the factory asks entirely different questions.

## Outputs
- `src/evaluation.py`, `reports/p12_system_evaluation.md`, plots

## The metrics

| Dimension | Metric |
|---|---|
| **Yield** | hypotheses → accepted cards · **tokens per accepted alpha** · new marginal IC per generation · diversity of accepted alphas |
| **Honesty** | **FDR = accepted-but-fails-holdout ÷ accepted** · distribution of Deflated Sharpes · realized-vs-pre-registered sign agreement rate |
| **Efficiency** | real alpha per token — the headline objective |
| **Gate value** | the ablation, below |
| **Real vs fake learning** | error **volume** trend, below |

## The ablation — the answer to "isn't this over-engineered?"

1. **Seed a pool** of ~40 factors with known ground truth: ~10 genuinely predictive (plant real signal
   into the fixture labels), ~10 pure noise, ~10 deliberately overfit (fitted to a subsample), ~10
   deliberately leaky.
2. **Run the pool through the gates** with each gate **enabled** and then **disabled**.
3. **Report per gate:** **catch rate** (junk correctly rejected), **false-kill rate** (good factors
   wrongly rejected), and the headline **FDR with the gate on vs off**.

Disabling Gate B or Gate C should visibly raise FDR. This makes complexity *self-justifying* rather
than asserted: *we did not add gates because papers have them — we measured what each one catches.*

**State the limitation honestly:** a prototype's sample is small, so these numbers are **illustrative,
not conclusive**. Say so in the report.

## Detecting *fake* learning

There is a well-argued critique that factor-mining agents only *look* like they're learning: their
mistakes get more sophisticated over generations — conceptual → operational → strategic — while the
**total number of mistakes barely moves.**

So track and plot: **total rejections per generation**, **per-gate pass rate over time**, and the
**distribution of rejection reasons**. Genuine improvement = falling error *volume* and rising pass
rate. Drift = the same volume in new clothes. Report which one we actually observe — **including if it
is the unflattering answer.**

## Acceptance
- [ ] The seeded pool has documented ground truth per factor.
- [ ] Every gate has a catch rate and a false-kill rate.
- [ ] The FDR on/off comparison exists for at least Gate B-novelty, Gate B-stats, and Gate C.
- [ ] The fake-learning plot exists and is interpreted in one honest paragraph.
- [ ] The report states the small-sample limitation explicitly.

## Do NOT
Do not tune the gates to make the ablation look good — that is overfitting the evaluation. Run it once,
report what it says.

**Effort:** ~4h

---

# PHASE 13 — Slide deck

**Objective:** the 20-minute presentation.

**Depends on:** P11, P12 for evidence. **Blocks:** nothing.

## Outputs
`slides/` — PDF or Google-Slides-ready.

## The deck

| # | Slide | Source |
|---:|---|---|
| 1 | Problem + task specification (exact I/O, what one Alpha Card is) | `INITIAL_PLAN.md` §1 |
| 2 | Literature map (what we adapt from each paper) | `INITIAL_PLAN.md` §16 |
| 3 | **The nine-stage architecture** (main diagram) | `INITIAL_PLAN.md` §3 |
| 4 | *(appendix)* the 16 components inside the 9 stages, with paper lineage | `INITIAL_PLAN.md` §4 |
| 5 | **Five failure modes, five mechanisms — and what each does NOT catch** ← the best slide | `INITIAL_PLAN.md` §6 |
| 6 | Search policy: √(2 ln N), the variant cap, the fresh fold | `INITIAL_PLAN.md` §7 |
| 7 | Three budgets — and the conflict between #1 and #3 | `INITIAL_PLAN.md` §8 |
| 8 | Data audit: effective-vs-announcement dates, coverage plot, disclosed defects | P1, P2 reports |
| 9 | Evaluating the **system** + the ablation table | P12 |
| 10 | Improvement over iterations + fake-learning detection | P12 |
| 11–13 | The good card, and the three bad examples (three beats each) | P11 |
| 14 | **Honest novelty positioning** — including the claim we concede, with its citation | `INITIAL_PLAN.md` §13 |
| 15 | Limitations and roadmap | `INITIAL_PLAN.md` §14, §9 |

**Tone note:** slide 14 matters more than it looks. Two of our four original "novel" claims were
already published (arXiv 2608.27734, 2608.11250). Conceding them with citations and leading with the
two that survive is a stronger position than a bluff — a researcher who knows those papers *will* ask.

**Effort:** ~4h

---

# EXECUTION ORDER AND DEPENDENCIES

```
P0 ─┬─ P2 ── P1 ── P3 ─┬─ P4 ─┬─ P6 ─┬─ P10 ─┬─ P11 ─┬─ P13
    │  ^^^^^^^^^^      │      │      │       │       │
    │  order flipped   │      │      └─ ... ─┘       │
    ├─ P5 ─────────────┘      │       └─ P12 ────────┘
    ├─ P7 ────────────────────┘
    ├─ P8
    └─ P9
```

> ⚠️ **P2 NOW RUNS BEFORE P1.** P2 downloads whole trading days, so it needs no symbol list; and P1
> derives the universe *from* P2's bhavcopy output. The old order (P1→P2) assumed a constituent file we
> have since abandoned — see P1's Standalone context.

**Suggested start: P0 → P2 → P1.**

**Parallelizable with no coordination:** P5, P7, P8 and P9 depend only on P0 and their own contracts.
Four agents can build those simultaneously.

| Phase | Effort | Parallel-safe with |
|---|---:|---|
| P0 Scaffolding | 1.5h | — (blocks all) |
| P1 Universe (after P2) | **2.5h** | P5, P7, P8 |
| P2 Prices ⭐ **(run first)** | **5.5h** + ~20 min unattended download | P5, P7, P8, P9 |
| P3 Panel | 3h | P5, P7, P8, P9 |
| P4 Backtester | 4h | P5, P7, P8 |
| P5 Operators + zoo | **5h** | P1–P4, P7, P8 |
| P6 Gates | 5h | P5, P7, P8, P9 |
| P7 Memory | 3.5h | everything except P0 |
| P8 Agents + corpus | **6h** | everything except P0 |
| P9 Red-Team | 3h | P5, P7, P8 |
| P10 Loop | 5h | — |
| P11 Demo | 4h | P12 |
| P12 Evaluation | 4h | P11 |
| P13 Slides | 4h | — |

**Revised total ≈ 55.5h sequential; ≈ 27h with four parallel agents.**
*(P2, P5 and P8 grew after the pre-build investigation — see `PRE_BUILD_TASKS.md`: NSE-primary data with
our own corporate-action adjustment, the 35-formula alpha zoo, and the research corpus + LLM throttling.)*

*(totals below the table)*

> **Scope reality check.** The prompt says *"a few focused hours"* and that *"a clear design with a
> rigorous evaluation and improvement plan scores as highly as a demo."* If time is short, the
> **minimum viable path is P0 → P1 → P2 → P3 → P4 → P6 → P11(②③④ only) → P13**: real data, a real
> backtester, real statistical gates, and the three bad examples — with the agent loop presented as
> design rather than code. That is a defensible deliverable. **A partial result you understand beats a
> complete one you cannot defend.**

---

# EXPLICITLY OUT OF SCOPE

These were considered and **deliberately excluded**. Do not implement them; if asked why, the reasons
are below.

| Excluded | Why |
|---|---|
| **MCTS formula search** | Its value is finding the maximum in *fewer* evaluations — which, when the reward is noise, means finding the tail of the noise *faster*. Its **adaptive** draws also make "effective number of independent trials" hard to define, undermining the Deflated Sharpe. It is a multiplier; verify the measuring instruments first. |
| **Code-based evolution** (arbitrary Python factors) | Unbounded complexity (memorization risk), weakens AST duplicate detection, and **reopens the look-ahead surface** that the causal operator library currently closes. |
| **Feature registry / access control** | Redundant with the compile check — the panel *is* the whitelist. Formula-level look-ahead is already structurally impossible via causal operators. The per-field lag engine reduced to **one field**, kept as red-team test 6. And it would not have caught the broken universe source anyway; external reconciliation did. |
| **Point-in-time fundamentals** | Free Indian fundamental data is not point-in-time, so using it would inject exactly the look-ahead this system exists to catch. A **rigor choice, not an oversight**. Needs a paid vendor. |
| **A vector database** | A few hundred lessons. Numpy cosine is instant; a vector DB is a dependency that can break during a live demo. |
| **Live trading / execution modelling** | Task B grades the *signal*. Costs enter only as a robustness check. |
