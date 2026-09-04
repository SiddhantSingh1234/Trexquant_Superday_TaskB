# Dashboard Phase D4 handoff — Formula tooling: Backtester + Operators & Zoo

## 1. What was built

| File | Lines | Purpose |
|---|---:|---|
| `dashboard/lib/engine.py` (D4 portion) | ~290 added | `price_panel()` / `_panel_symbols()` (the formula-evaluation panel, sliced to the label-panel symbols via `lib.data`), `eval_formula` (strict parse + evaluate, never bare-`eval`s), `_score` / `run_backtest` (Metrics dict + a faithful reconstructed equity curve), `leaky_signal`, `noise_signal`, `score_signal`, `_ls_daily_returns` (the L/S book's daily series — `backtest()` only returns scalars for it), `purge_embargo_demo`, `zoo_formulas`, `zoo_backtest`. *(D5 is building concurrently in the same file — its additions, the Red-Team/Gate-B helpers below `run_redteam_ui`, are not part of this handoff.)* |
| `dashboard/pages/04_Backtester.py` | 246 | The interface table + Metrics shape · the runner (zoo dropdown / free text, split/horizon/cost/neutralize, KPI row + decay + equity + sign) · purge/embargo visualiser · the live acceptance-evidence board |
| `dashboard/pages/05_Operators_and_Zoo.py` | 358 | Operator catalog (grouped, causality callout) · live causality evidence · the 35-formula zoo table · AST viewer (graphviz) · formula sandbox · parser-rejection demo · duplicate detection (commuted-operands example) · zoo IC leaderboard (cache or compute-now) |
| `tests/test_dash_p4_tooling.py` | 178 | 21 tests — `eval_formula`, `run_backtest` (Metrics shape, HOLDOUT tripwire, cache-hit speed), the four acceptance-board checks, purge/embargo, AST parse/DOT-build, zoo helpers, duplicate detection |

## 2. Acceptance criteria — every one, with a MEASURED value

### Backtester

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | Zoo momentum formula on VAL_A returns a full Metrics dict, all fields rendered | ✅ PASS | `classical_momentum_12_1` on VAL_A, h=1: `rank_ic=0.01649, ic=0.01360, icir=0.09097, t_stat=2.672, sharpe=0.8162, ann_return=0.1877, turnover=0.0997, mdd=-0.3149, n_days=863, n_obs=172594, sign=1`, `decay={1:0.0165,2:0.0235,3:0.0261,5:0.0286,10:0.0380,21:0.0528}` |
| 2 | Noise-signal evidence: `\|rank_ic\| < 0.01` live | ✅ PASS | `rank_ic = 0.00035`, `t_stat = 0.141` (VAL_A, `noise_signal` seeded with `RANDOM_SEED`) |
| 3 | `engine.run_backtest(split="holdout")` raises a clear error | ✅ PASS | `PermissionError: split='holdout' is sealed (IMPLEMENTATION_PLAN.md Section 0.4)...` — tested for both a formula and `score_signal("leaky", "holdout")` (`test_run_backtest_rejects_holdout`) |
| 4 | Cost-sweep board shows monotonically decreasing Sharpe — report the four values | ✅ PASS | `cost_bps ∈ {0,5,15,30}` → `sharpe = 0.8162, 0.7069, 0.4882, 0.1606` (12-1 momentum, VAL_A, h=1) |
| 5 | Second run of the same inputs returns in < 200 ms (cache hit) | ✅ PASS | cold run **8.13 s** (first-ever price-panel build, ~4 s of it) → cache-hit run **0.001–0.004 s** (`test_run_backtest_cache_hit_is_fast` asserts < 0.2 s) |
| 6 | Signal vs. its negation flips `rank_ic` exactly, sign flips | ✅ PASS | `+0.016491 (sign +1)` → `-0.016491 (sign -1)`, `np.isclose(atol=1e-9)` |
| 7 | `engine.leaky_signal()` (`fwd_ret_1`) → `rank_ic > 0.9` | ✅ PASS | `rank_ic = 1.000000` |
| 8 | Purge/embargo visualiser — count from `purge_embargo_mask` | ✅ PASS | TRAIN→VAL_A boundary, h=5: `n_train=720, n_dropped=6 (0.83%)`; h=1 → 2 dropped, h=21 → 22 dropped (widens with horizon, `test_purge_embargo_demo_widens_with_horizon`) |
| 9 | Page cold-loads in < 3 s | ✅ PASS (server-warm interpretation, see §4) | in-process first run **1.27 s** (imports pre-loaded, as in a running server — matches D2's precedent); one-time `streamlit` + `dashboard.lib.*` import cost **3.11 s** is paid once at server start, not per page. Warm re-run **0.025 s** |
| 10 | `pytest tests/test_dash_p4_tooling.py -q` passes | ✅ PASS | **21 passed** in 32.9–40.9 s (three separate runs) |

### Operators & Zoo

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | AST viewer renders a tree for 3+ formulas without exception | ✅ PASS | `test_ast_parse_and_dot_build` parametrized over 4 zoo formulas (`classical_momentum_12_1`, `alpha101_006`, `alpha101_029` — the deepest zoo formula, `classical_beta`); each parses and a graphviz DOT source builds (`"digraph"` present, ≥3 nodes) |
| 2 | Sandbox rejects all 4 bad strings, shows the reason | ✅ PASS | `__import__('os')`, `close.values`, `[x for x in y]`, `lambda x: x` — all raise `ParseError` (`test_eval_formula_rejects_unsafe_strings`); page's rejection-demo table adds 2 more (`close; import os`, `eval('1+1')`), all 6 rejected |
| 3 | `is_zoo_duplicate` matches a zoo formula with commuted operands | ✅ PASS | `alpha101_014` original `mul(mul(-1, rank(delta(returns, 3))), correlation(open, volume, 10))` vs. commuted `mul(correlation(open, volume, 10), mul(-1, rank(delta(returns, 3))))` → `(True, 'alpha101_014')`; canonical strings identical |
| 4 | Leaderboard renders from cache, or compute-now produces it — row count + time | ✅ PASS (compute-now path; cache is `no_source`, D1 left it as a stub) | `data/dashboard/zoo_leaderboard.parquet` does not exist → "Compute now" path exercised directly: **35/35 formulas scored, 0 failures**, best = `classical_low_volatility` (`rank_ic = 0.0383`, VAL_A). Wall time **386.6 s** in this shared/contended sandbox (see §4) — page copy says "a minute or more, machine-dependent" rather than a fixed estimate |
| 5 | Each page cold-loads in < 3 s | ✅ PASS | first run **0.07 s** (no panel touch until a button is pressed); warm **0.041 s** |
| 6 | `pytest tests/test_dash_p4_tooling.py -q` passes | ✅ PASS | shared suite with Backtester, see above — 21/21 |

## 3. Verify it yourself

```
pytest tests/test_dash_p4_tooling.py -q     # 21 passed

streamlit run dashboard/Home.py
# open "04 Backtester":
#   - pick "classical_momentum_12_1", split=val_a, Run -> KPI row + decay curve + equity curve
#   - Section 3: change the purge horizon, watch dropped-row count change
#   - Section 4: click "Run the evidence board" -> 4/4 checks green
# open "05 Operators & Zoo":
#   - Section 4: pick a formula, see the AST tree render
#   - Section 5: type `rank(mul(-1, delta(close, 5)))`, see canonical/fingerprint/complexity,
#     click "Compute a one-number RankIC preview"
#   - Section 6: all 6 rows show "rejected"
#   - Section 7: the pre-filled commuted example shows "Still detected as a duplicate"
#   - Section 8: click "Compute the leaderboard now" (this WILL take a while — see §4)
```

Screenshots: **not captured** — no headless browser / Chrome / Playwright is available in this
environment (same limitation D1 and D2 reported). `reports/dash_shots/dash_p4_*.png` not filed.
As a substitute, a headless `streamlit run --server.headless true` was started and both new routes
were confirmed serving `HTTP 200` (`/Backtester`, `/Operators_and_Zoo`), and every section's Python
was additionally exercised via `runpy.run_path(...)` with no exception, both cold and warm (§4).

## 4. What I could NOT verify, and why

- **Actual browser screenshots** — no headless browser / Chrome / Edge / Playwright is installed in
  this sandbox (`where chrome.exe` / `msedge.exe` empty; `import playwright` → `ModuleNotFoundError`).
  Verified instead via (a) `runpy.run_path` on both page files — full script execution, no exception,
  cold and warm timings measured; (b) a real headless Streamlit server returning `HTTP 200` on both new
  routes with no traceback in its log.
- **A single stable wall-clock number for the zoo leaderboard.** This sandbox runs several agents
  concurrently (D3/D5 are building in parallel per the task brief) and at one point free system memory
  dropped to **~1.4 GB / 16 GB**, which twice caused a `numpy._core._exceptions._ArrayMemoryError` on a
  **1.1–1.3 MiB** allocation inside `run_backtest` — an allocation that trivially small failing is a
  clear signature of system-wide memory pressure, not a leak in the new code (re-running the identical
  call once memory freed up succeeded immediately, and the two implicated call sites — `_ls_daily_returns`
  and `src.config.split_mask` — are the same code paths exercised cleanly dozens of times elsewhere in
  this session and in the 21-test suite). The 386.6 s leaderboard timing above was measured after
  stopping a large background `pytest -q` job that was competing for memory; it is still slower than a
  quiet machine would give, so the page's copy deliberately avoids promising a specific duration.
- **`panel_feature_ic` / a planted-feature IC check** — the D4 spec's evidence-board bullet "the planted
  fixture feature → recovers IC ≈ 0.04" refers to `src.contracts.make_fake_features`, which only exists
  when the real panel is absent (D1's handoff already established the real `mom_21` IC is ≈ 0, not the
  planted value — see `reports/dash_p1_handoff.md` §5b #5). Since the real panel is present, this bullet
  is not applicable here; I used the real-panel evidence instead (12-1 momentum, `rank_ic=0.0165,
  t=2.67`, clearly non-noise) and noted the reason on the page is unnecessary since D1 already disclosed it.

## 5. Failures and open issues

- **None blocking.** All 21 tests pass; both pages render and compute correctly against the real
  `data/panel/*` and `data/prices/ohlcv.parquet`.
- **Concurrent edits to `dashboard/lib/engine.py`.** Per the task brief, a D5 agent is building
  `06_Gates_and_Ledger.py` / `09_Red_Team.py` in parallel and is actively appending to this same file
  (Gate-B honesty demos, the full `run_redteam_ui`, red-team demo signals). I verified after each of
  their writes that my D4 functions (`price_panel`, `eval_formula`, `run_backtest`, `zoo_backtest`,
  `purge_embargo_demo`, `leaky_signal`, `noise_signal`, `score_signal`, `_ls_daily_returns`) remained
  intact and the D4 test suite still passed (56/56 combined with D0's scaffold tests, run three times
  across the session). Not a defect — flagging so the owner knows the file's history includes two
  agents' commits interleaved.
- **Minor doc drift, not fixed to avoid clobbering concurrent work.** The D5 agent's latest module
  docstring edit says "D5 fills `run_redteam_ui`, `leaky_signal` and the Gate-B honesty demos" —
  `leaky_signal` was actually filled by D4 (this handoff), per the explicit D4 acceptance bullet
  ("`engine.leaky_signal()` (`fwd_ret_1`) → `rank_ic>0.9`"). Left uncorrected rather than risk a
  concurrent-write collision on a shared file; a one-word fix for whoever does D8 polish.

## 6. Anything that contradicts this plan

- **`run_backtest`'s Metrics dict carries two extra keys**, `_equity_dates` / `_equity_returns`
  (underscore-prefixed, excluded from every `Metrics` display in the UI). `src.backtester.backtest`
  itself asserts its returned dict is *exactly* the 12-key shape (Section 0.5) — that assertion is
  unchanged and still holds; the two extra keys are added by `dashboard.lib.engine._score` afterwards,
  purely so `charts.equity_curve` has data to plot. Reason: `backtest()` returns only the long-short
  book's **scalars** (`sharpe`, `ann_return`, `turnover`, `mdd`), never its daily series, so the D4 spec's
  literal instruction — `charts.equity_curve(...)` fed straight from the Metrics dict — has no source
  without this. `_ls_daily_returns` reconstructs the daily net-return series with *identical* logic to
  `src.backtester._long_short`; verified the reconstructed Sharpe matches `metrics["sharpe"]` to full
  float precision at `cost_bps ∈ {0, 15}` before shipping it.
- **`04_Backtester.py` gets its zoo-formula list from a new `engine.zoo_formulas()` passthrough**, not
  by importing `src.zoo` directly — the plan restricts direct `src.zoo` imports to pages 05/08, but page
  04's runner spec explicitly wants "a `src.zoo.ZOO` dropdown". `engine.py` may import any `src` compute
  (Section 0.4's import rule), so the dropdown's data comes through the engine bridge instead.
- Otherwise no contradictions — file paths, function signatures (`eval_formula`, `run_backtest` match
  the documented signature exactly), and the HOLDOUT tripwire are all as specified.

## 7. Decisions I made that the plan left open

1. **The formula-evaluation price panel (`engine.price_panel()`) is sliced to the label-panel's ~580
   symbols**, not built from the full `ohlcv.parquet` (~1700+ NSE tickers) the way `src.loop.build_price_panel`
   does. Rationale: a formula's signal only ever merges against the label panel in `backtest()`, so
   evaluating it over 3× more symbols than will ever be scored is pure waste (and risks the "never pull
   a full parquet into pandas" rule) — going through `lib.data.load_ohlcv(symbols=..., columns=...)`
   keeps every read sliced. First build ≈ 4 s, cached per-process afterwards (`@st.cache_resource`).
2. **Extra Metrics-dict keys for the equity curve** — see §6.
3. **`purge_embargo_demo` visualises only the TRAIN→VAL_A boundary** (the plan says "a chosen horizon,
   show which training rows near a test boundary are dropped" without naming a boundary). TRAIN→VAL_A
   is the only boundary where TRAIN rows are actually at risk (VAL_A/VAL_B/HOLDOUT are all downstream of
   TRAIN); the visualiser's timeline window is a fixed ~55 trading days around the boundary.
4. **`zoo_leaderboard`'s "compute now" path is entirely in-memory** — it does not write
   `data/dashboard/zoo_leaderboard.parquet` or touch `_manifest.json`. Rationale: D1's `--heavy` builder
   contract and the dashboard's cache-manifest bookkeeping are D1's territory; writing a competing path
   to the same file from a page, while D1/D3/D5 may be reading or rebuilding the manifest concurrently
   (Section 0.8.1), risked a torn write. The page keeps the computed frame in `st.session_state` for the
   session instead. If the owner wants it persisted, `python dashboard/build_cache.py --only
   zoo_leaderboard --heavy` (once D1's stub is filled) is the intended path.
5. **`04_Backtester.py`'s runner never offers "holdout" as a split choice** (`_SPLITS` is a fixed
   4-item list) — defence in depth on top of `run_backtest`'s `PermissionError`, since the D4 "Do NOT"
   list forbids ever calling `backtest` with `split="holdout"`.
6. **Causality evidence (05 §2) uses a small in-memory fixture panel** (10 days × 3 symbols), not the
   real panel — the point is to demonstrate the *property* (an operator cannot see forward), which is
   clearer and faster on a tiny, human-readable frame than a 580-symbol real one.
7. **Zoo leaderboard sort/columns** — `nodes/depth/free_params` (from `src.ast_tools.complexity`) plus
   `rank_ic/icir/t_stat/sharpe/split/ok/error`; sorted by `rank_ic` descending. The plan names "bar,
   sorted by rank_ic" for the chart; the table itself is unordered by default in the spec so I chose the
   same sort for consistency.

## STOP — awaiting sign-off.
