# Phase 4 handoff — Backtester engine

> Status: **READY FOR REVIEW.** Do not start Phase 5.
> Execution order so far: **P0 → P2 → P1 → P3 → P4**.
> One deterministic, parameterized function, `src/backtester.backtest(...)`, with the exact
> signature from the spec. It only **measures** — no accept/reject, no Deflated Sharpe / PBO /
> CSCV / ledger (all Phase 6), no LLM.

## 1. What was built

| File | Lines | Purpose |
|---|---|---|
| `src/backtester.py` | ~450 | THE engine: `backtest()` (align → subsample → HOLDOUT-tail purge → thin-day drop → rank-scale / optional sector-neutralize → IC/ICIR/t-stat → decay curve → long-short book with costs); `purge_embargo_mask()` (reusable train/test purge+embargo, Phase 6's CSCV calls it); `use_panel()`/`clear_panel()` in-process panel override; `_METRIC_KEYS` asserts the Section 0.5 shape on every return. |
| `tests/test_p4_backtester.py` | ~230 | 23 tests (21 on Phase-0 fixtures, +1 synthetic-calendar, +1 real-panel-or-skip), no network. Every acceptance criterion + switch coverage (all 5 subsample modes, sector neutralize, long/wide signal equivalence, Metrics shape, decay curve). |

`src/config.py`, `src/contracts.py` unchanged. Full suite: **116 passed** (was 93; +23).

## 2. Acceptance criteria — every one, with a MEASURED value

Fixture = `make_fake_features/labels(n_days=1400, n_symbols=60, seed=42)`; planted feature is
`mom_21` (planted RankIC 0.04), leak feature is `fwd_ret_1` predicting itself.

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | Random noise → `\|rank_ic\| < 0.01`, `\|t_stat\| < 2` | ✅ PASS | fixture `train+val_a` (1398 days): rank_ic = **0.00211**, t_stat = **0.619**. Real panel `val_a` (863 days): rank_ic = **0.00232**, t_stat = **0.956**. |
| 2 | Known-good fake feature → `rank_ic` within ±0.01 of 0.04 | ✅ PASS | `mom_21` on `train+val_a`: rank_ic = **0.0404** (Δ from 0.04 = **0.0004**). `train` alone = 0.0435, `val_a` alone = 0.0362. |
| 3 | `fwd_ret_1` as its own signal → `rank_ic > 0.9` | ✅ PASS | fixture `val_a` = **1.0000**; real panel `val_a` = **1.0000** (demeaning preserves within-day rank order). |
| 4 | Negating a signal exactly negates `rank_ic`, flips `sign` | ✅ PASS | fixture: +0.036237 / −0.036237, exact to 1e-12, sign +1 / −1. Real panel: +0.01643788 / −0.01643788, **bit-exact** (`rank_ic == -neg_rank_ic` is `True`), sign +1 / −1. `ic` also exactly negates. |
| 5 | `extra_lag=1` measurably changes a signal with genuine short-horizon power | ✅ PASS | `fwd_ret_1` self-signal `val_a`: rank_ic **1.0000 → −0.0052** with `extra_lag=1` (Δ = **1.005**). |
| 6 | Increasing `cost_bps` monotonically lowers `sharpe` | ✅ PASS | fixture `mom_21` `train+val_a`, cost_bps (0,5,10,20,40,80): sharpe = **4.14 → 1.37 → −1.41 → −6.95 → −17.89 → −38.73** (strictly decreasing). Real panel `val_a` (0,5,10,20,40): **1.038 → 0.879 → 0.719 → 0.400 → −0.238**. |
| 7 | `split="holdout"` without token raises | ✅ PASS | `backtest(sig,"holdout")` raises `PermissionError`. `backtest(sig,"holdout", i_have_a_peek_token=True)` returns a full Metrics dict (real panel: rank_ic 0.0004, n_days 859). |
| 8 | Purge+embargo removes the expected rows for `horizon=5` | ✅ PASS | `purge_embargo_mask` (the reusable helper) — train spanning both sides of a 10-day test block on a 60-day calendar: **h=5, embargo=0 → 6 dropped** (label overlap, positions 34–39); **h=5, embargo=5 → 11 dropped** (+positions 50–54); **h=1, embargo=0 → 2 dropped**. `_purge_holdout_tail` on a synthetic calendar straddling 2022-07-01: a val_b-like window loses its **last 2 (h=1) / 22 (h=21)** days; a window ending 40 td before HOLDOUT loses **0**. Real panel `val_b` n_days **247 (h=1) → 227 (h=21)**, `val_a` n_days **863 → 863** (unchanged — val_a is far from HOLDOUT). Verified 2022-06-30 has 198/200 populated `fwd_ret_21` from HOLDOUT opens. See §7.6. |
| 9 | Two identical calls → bit-identical | ✅ PASS | fixture, `horizon=5, cost_bps=15, neutralize="sector"`: `a == b` is `True` (full nested dict incl. `decay`). Real panel: `True`. No RNG in the engine. |

### Extra checks (not formal criteria)

| Check | Measured |
|---|---|
| Metrics dict shape == Section 0.5 key order | ✅ `tuple(m) == _METRIC_KEYS`; `decay` keys `[1,2,3,5,10,21]` (ints); `n_days`/`n_obs`/`sign` are `int`; `rank_ic == decay[horizon]`. |
| Decay curve on the planted fixture | falls monotonically **0.0389 (h1) → 0.0033 (h21)** — matches `PLANTED_IC/sqrt(PLANTED_IC²+h)`. |
| Decay curve, real `mom_126` `val_a` | **0.016 → 0.024 → 0.028 → 0.033 → 0.045 → 0.064** (rising — real 6-1m momentum, matches P3 handoff). |
| All 5 subsample modes + `neutralize="sector"` | run, return finite `rank_ic`, `n_obs` ≤ full. |
| Long-format signal == wide-format signal | identical Metrics. |
| Real panel full backtest wall time | **~2.3 s** (581 symbols, 857 eval days). |

## 3. Verify it yourself

```powershell
# fast, no network — all fixtures
./.venv/Scripts/python.exe -m pytest tests/test_p4_backtester.py -q          # expect: 23 passed (~30s)
./.venv/Scripts/python.exe -m pytest tests/ -q                                # expect: 116 passed (~2min)

# real-panel smoke (reads data/panel/*.parquet) — mom_126 on val_a, horizon=5
./.venv/Scripts/python.exe -m src.backtester
#   rank_ic: ~0.0325   ic: ~0.0334   t_stat: ~4.97   sharpe: ~1.04   n_days: 863
#   decay: {1: 0.016, 2: 0.025, 3: 0.028, 5: 0.033, 10: 0.045, 21: 0.064}   sign: 1
```

```python
# one-liners the owner can paste
from src import backtester as bt
f, l = bt._load_panel()
sig = f.pivot_table(index="date", columns="symbol", values="mom_126")

# leak detector
s1 = l.pivot_table(index="date", columns="symbol", values="fwd_ret_1")
print(bt.backtest(s1, "val_a")["rank_ic"])                 # 1.0

# holdout tripwire
try: bt.backtest(sig, "holdout")
except PermissionError as e: print("blocked:", e)

# cost monotonicity
print([round(bt.backtest(sig,"val_a",cost_bps=c)["sharpe"],3) for c in (0,10,20,40)])
```

## 4. What I could NOT verify, and why

- **The long-short book's absolute Sharpe / ann_return / MDD are not calibrated against an external
  reference.** They are internally consistent and respond correctly to cost and to signal quality,
  but I have no ground-truth "mom_126 in India returned X Sharpe 2018–2021" number to check against.
  The IC family (`rank_ic`, `ic`, `icir`, `t_stat`, `decay`) *is* cross-checked — `mom_126` decay
  on VAL_A is 0.016 / 0.025 / 0.028 / 0.033 / 0.045 / 0.064 for h=1…21, matching the P3 handoff's
  VAL_A feature-IC table.
- **`extra_lag` on a slow feature (`mom_21`, `mom_126`)** barely moves the IC because those features
  are ~95% autocorrelated day-to-day — so criterion 5 is demonstrated with `fwd_ret_1` (a genuine
  1-day-horizon signal), where the lag is decisive. This is the spec's intent ("genuine
  short-horizon predictive power") but worth noting the slow-feature case looks almost unchanged.
- **Holdout metrics** were computed once (criterion 7) to prove the token path returns a valid dict;
  I did not analyse them. Reading HOLDOUT is Phase 6's job through the rationed peek — this was a
  single mechanical check, not research.
- **`subsample={"regime": ...}`** uses a regime definition I invented (see §7); there is no spec
  definition to verify it against.

## 5. Failures and open issues

None open. All 23 P4 tests pass; full suite 116 pass.

One thing to watch downstream: **the noise criterion (#1) is statistical, not absolute.** With
seed 42 and ≥ ~850 days it passes comfortably (`|t|` ≈ 0.6–0.9), but a different noise draw can
produce `|t_stat| > 2` roughly 5% of the time — that is the definition of a t-stat, not a bug. The
test pins seed 42. Phase 6's Deflated-Sharpe machinery is what actually prices in "best of N noise
signals"; this engine just measures one signal at a time.

## 6. Anything that contradicts the spec

1. **The spec's `backtest` signature does not list `i_have_a_peek_token`, but the Phase 4 prose
   mandates it** ("split='holdout' must REQUIRE an explicit `i_have_a_peek_token=True` and raise
   otherwise"). Added as a keyword-only argument after `embargo_days`, so the 10 positional
   parameters in the spec block are unchanged. Raises `PermissionError` (not a bare `Exception`).
2. **Spec step 3 defines `icir` and `t_stat` over "daily_ic" without saying which IC.** The engine
   computes both from the **daily rank-IC series** (Spearman), since `rank_ic` is the headline
   metric and the P3 handoff quotes IR values alongside RankIC. `ic` (Pearson) is reported but not
   used for `icir`/`t_stat`. Flagged as a judgement call (§7.2) — trivially changed if the owner
   wants Pearson-based dispersion.
3. **Spec step 4 says "Subtract `cost_bps × turnover` per side."** "Turnover per side" is ambiguous.
   The engine charges `cost_bps × 1e-4 × Σ_i |w_{t,i} − w_{t-1,i}|` per day — i.e. every unit of
   absolute weight change on **both** legs is charged once. The reported `turnover` metric is the
   **one-way** figure (`0.5 × mean_t Σ_i |Δw|`), the conventional definition. So `cost drag ≈
   cost_bps × 1e-4 × 2 × turnover` per day. Documented in §7.3.
4. **Spec step 6 describes purge/embargo purely as a train/test-boundary operation** ("a *training*
   row near a test boundary…"), which in a single-split `backtest()` call (no train set) means it
   removes nothing. The engine follows that — `backtest()` applies no train/test purge — with **one**
   addition: a HOLDOUT-boundary tail purge (§7.6), forced by P3 having computed labels across the
   val_b→HOLDOUT boundary. The reusable `purge_embargo_mask` implements the spec's train/test
   purge+embargo for Phase 6.
5. **Nothing else.** The Metrics dict matches Section 0.5 exactly (key order asserted at runtime);
   determinism holds; the interface matches the spec block (plus the mandated `i_have_a_peek_token`).

## 7. Decisions I made that the spec left open

1. **Long-short book holding period = 1 day, regardless of `horizon`.** Daily P&L is
   `w_t · fwd_ret_1`, book fully rebalanced every day. `horizon` drives the IC and the decay curve
   (the primary signal-quality measures); it does **not** change the book's holding period.
   *Reason:* overlapping multi-day tranche accounting (Jegadeesh–Titman style) is not part of the
   Section 0.5 Metrics contract, adds a large surface of its own assumptions, and none of the eight
   downstream callers ask for a horizon-matched portfolio — they ask for IC-family metrics plus one
   comparable Sharpe. A daily-rebalanced book gives a stable, comparable Sharpe across all signals.
   *Consequence:* for a pure h=21 signal the Sharpe understates a real 21-day strategy's economics;
   the decay curve is where multi-horizon behaviour is read.
2. **`icir` / `t_stat` are computed on the daily rank-IC (Spearman) series** — see §6.2.
   `icir = mean / std(ddof=1)`, `t_stat = mean / (std(ddof=1) / sqrt(n_days))`.
3. **Transaction cost is charged on total absolute weight change (both legs); the reported
   `turnover` metric is one-way** — see §6.3.
4. **Cross-sectional rank-scaling maps ranks to `[-1, 1]` linearly** (`2·(rank−1)/(n−1) − 1`,
   `method="average"` ties). The spec says "Rank-transform … within each day to [-1, 1]" without
   giving the map; this is the standard uniform one and is exactly antisymmetric under negation
   (needed for criterion 4).
5. **`neutralize="sector"` demeans the raw signal within `(date, sector)` groups *before* the
   rank-scale**, per spec step 2 ("demean within sector first"). `sector` is joined from
   `features.parquet`; a symbol with no sector is bucketed as `__NA__` (kept, not dropped).
6. **The single-split engine's only tail purge is at the HOLDOUT boundary** (`_purge_holdout_tail`).
   *Why this exists at all:* P4 never reads HOLDOUT price rows — the signal is filtered to the
   split's own dates and the token tripwire blocks `split="holdout"`. But **P3 deliberately computed
   `fwd_ret_h` across every split boundary** (P3 handoff §6.3: "Sealing is enforced at scoring time
   (P4's `i_have_a_peek_token` tripwire), not by withholding rows here"). Verified: the last val_b
   day, 2022-06-30, has **198/200 populated `fwd_ret_21`** — each is
   `open[~22 td into Aug 2022] / open[2022-07-01] − 1`, i.e. **derived from HOLDOUT opens**. Without
   the purge, `backtest(sig, "val_b", horizon=21)` scores the signal on val_b's final ~21 days
   against holdout-derived labels — and Phase 6 scores promoted winners on val_b. So the purge is the
   P4 half of the sealing contract P3 delegated here.
   *Scope decision (I initially applied it at every split boundary, then narrowed it):* it now fires
   **only** when a row's `fwd_ret_horizon` window reaches a date `>= HOLDOUT_START`. An eval day is
   kept iff `pos + 1 + purge_days < holdout_boundary` (`purge_days` defaults to `horizon`).
   Non-sealed boundaries (val_a → val_b, train → val_a) are left intact: those splits' return
   windows may overlap the next region, which is standard in out-of-sample evaluation and is not a
   sealing concern — and Phase 6's walk-forward / CSCV do their own fold purging via
   `purge_embargo_mask` anyway. This keeps `backtest()` behaviour as close as possible to the spec's
   literal single-split reading (which purges nothing) while still honouring the one hard rule
   ("HOLDOUT is sacred"). Rows past the panel end carry NaN labels and drop downstream on their own.
   The leading embargo is **not** applied in `backtest` (no train block in a single-split score); it
   lives in `purge_embargo_mask` for Phase 6's CSCV.
7. **`purge_embargo_mask(train_dates, test_dates, horizon, embargo_days, calendar)`** contract:
   a train day at calendar position `p` is dropped if `a − horizon − 1 ≤ p ≤ b + embargo_days` for
   any contiguous test run `[a, b]` (positions on `calendar`). The `− horizon − 1` lower bound is
   the label-overlap rule (`fwd_ret_h` at `p` consumes positions `p+1 … p+1+h`). Distances are in
   **trading days on the supplied calendar**, never calendar days.
8. **`subsample` regime definitions (invented — no spec definition exists):**
   market proxy = equal-weight mean of `fwd_ret_1` across that day's panel names.
   `bull`/`bear` split on the **trailing 63-day cumulative** market return (≥ 0 → bull);
   `calm`/`volatile` split on the **trailing 21-day std** of the market return vs its own median
   over the eval window. All four labels are accepted.
9. **`subsample={"size_tercile": ...}`** buckets each day's names into terciles by `size_proxy`
   (from `features.parquet`) via `pd.qcut(..., 3)`; `{"min_turnover": X}` filters on
   `exp(turnover_21)` because P3 stores `turnover_21` as `log(mean rupee turnover)` — `X` is
   therefore a rupee threshold.
10. **`horizon` is validated against `{1,2,3,5,10,21}`** (the Section 0.5 decay keys / P3 label
    columns). A horizon outside that set raises `ValueError` rather than silently computing a label
    that does not exist.
11. **Panel source resolution:** in-process override (`use_panel`) → `data/panel/*.parquet` →
    Phase-0 fixtures, in that order. Both frames are validated (`validate_features`/`validate_labels`)
    on every load. `use_panel` exists for the tests and for Phase 6 (which scores data subsets);
    it is not part of the `backtest` signature.
12. **Signal accepted in wide (`date × symbol`) or long (`date, symbol, <value>`) form** — the spec
    says wide; long is accepted as a convenience and proven equivalent by a test.

## 8. STOP

`src/backtester.py` is one parameterized engine meeting the exact spec signature. All 9 acceptance
criteria pass with measured values (fixture **and** real panel where applicable); full suite
116 passed. The engine measures only — no accept/reject, no Phase-6 statistics, no LLM.

**Not starting Phase 5.** Awaiting sign-off.
