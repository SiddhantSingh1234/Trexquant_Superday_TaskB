# Dashboard Phase D1 handoff — Cache builder (the data-prep layer)

## 1. What was built

| File | Lines added | Purpose |
|---|---:|---|
| `dashboard/build_cache.py` | +560 | 21 real cheap builders + shared source loaders (`_ohlcv`, `_membership`, `_features`, `_labels`, `_monthly_member_sets`, `_daily_coverage_frame`, `_panel_wide`), a vectorised `_wide_ic`, `_finish` (dtype-coerce + assert + status/note), `_empty`, `_exists`; the two heavy names (`zoo_leaderboard`, `prices_yf_crosscheck`) stay registered stubs |
| `dashboard/README.md` | +30 | builder catalogue with costs + measured numbers |
| `tests/test_dash_p1_cache.py` | 190 | 36 tests — schema-per-builder, `--check`, the care-point numbers, idempotency, missing-source path, `.db` read safety, staleness detection |
| `data/dashboard/*.parquet` | 24 files | the cheap-pass output |
| `data/dashboard/_manifest.json` | — | 24 rows with `rows/cols/built_at/builder_version/status/note/sources[{path,mtime,size}]` |

**Builder status after a cheap pass:** 20 `ok` · 1 `partial` (`universe_overlap`) · 3 `no_source`
(`ledger_summary`, `loop_generations`, `loop_run_meta` — their artifacts don't exist yet) ·
2 heavy stubs untouched (`zoo_leaderboard`, `prices_yf_crosscheck`).

## 2. Acceptance criteria — every one, with a MEASURED value

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | cheap pass completes in < 90 s | ✅ PASS | **34.4 s** warm / **48.0 s** cold (`time python dashboard/build_cache.py`) |
| 2 | `--check` passes: manifest `cols` == `CACHE_SCHEMAS`, dtypes match | ✅ PASS | `--check: OK`, **exit 0** |
| 3 | re-running is idempotent (hash parquets before/after a 2nd run) | ✅ PASS | **all 24 parquets byte-identical** on a 2nd `build_cache.py`; `test_idempotent_rebuild` green |
| 4 | `universe_daily_coverage.n_panel` near-zero 2015→2025 linear trend | ✅ PASS | slope = **+0.003 names/year** → **FLAT**. `n_panel` ∈ [198, 200], `gap` mean 0.18 / max 2. *No survivorship leak — see §5.* |
| 5 | `panel_feature_ic_shift`: `mom_21` `base` vs `shift1` differ by > 20 % relative | ✅ PASS | `base` = **−0.00329**, `shift1` = **+0.00141**, relative change **143 %** (sign even flips). Every one of the 11 features moves under the shift. |
| 6 | `panel_leaky_check`: `fwd_ret_1` self-predictor RankIC > 0.9 | ✅ PASS | RankIC = **1.0000** (all 6 horizons; a per-day demean is monotone so ranks are identical) |
| 7 | every builder with a missing source writes an empty frame + `status:"no_source"`, no exception | ✅ PASS | `ledger_summary` / `loop_generations` / `loop_run_meta` → 0-row schema-correct parquets, `status:"no_source"`; `test_missing_source_writes_empty_no_source` monkeypatches `_exists→False` and confirms it for `panel_feature_ic` + `universe_daily_coverage` |
| 8 | `loop_generations` builds from the checkpoint if a run exists, else `no_source` | ✅ PASS | `data/loop_checkpoint.db` absent → `no_source`, **0 rows** (note: "the loop (P10/P11) has not run yet") |
| 9 | every `.db` read goes through `data._readonly_sqlite`; source `.db` mtimes unchanged after a full run | ✅ PASS | `ledger.db` / `memory.db` / `lessons.db` `st_mtime_ns` **identical** before/after `python dashboard/build_cache.py`; no builder constructs `Ledger()`/`Memory()` on a real path |
| 10 | `--check` reports staleness per builder and exits non-zero when a source is newer | ✅ PASS | `test_check_flags_staleness` rewrites a manifest `sources[].mtime` to the past → `check()` returns **1**, prints `STALE corpus_family_counts` |
| 11 | `pytest tests/test_dash_p1_cache.py -q` passes | ✅ PASS | **36 passed** in 5.5 s |
| 12 | no regression | ✅ PASS | full suite `python -m pytest -q` → **315 passed** (0:12:53); D0+D1 dashboard tests → **71 passed** |

### Additional measured builder outputs (sanity)

| Builder | Rows | Headline number |
|---|---:|---|
| `universe_monthly` | 132 | churn_pct mean **4.66 %**, median 4.50 %, range 0–9.5 % |
| `universe_intervals` | 16 | DHFL ends 2019-12-31, JPASSOCIAT 2019-01, RCOM 2019-05 (each stops when it leaves the liquid universe); 6 heavyweights span 2015→2025 |
| `universe_sector_comp` | 2 580 | 22 NSE sectors × 131 months |
| `universe_overlap` | 131 | supplied-CSV overlap ≈ **55 %** (see §5); NSE column NaN |
| `prices_coverage_yearly` | 11 | covered_pct ≈ **99.9 %**/yr, ~258 distinct symbols/yr |
| `prices_ca_counts` | 65 | dividend 14 934 · other 10 394 · bonus 426 · split 412 · demerger 149 · bonus+split 16 |
| `prices_extreme_returns` | 453 | `|ret|` 0.5 → ~5.0; 37 tagged (demerger 32 / other 4 / bonus+split 1), 416 genuine unwinsorized moves |
| `prices_source_eras` | 2 | bhavcopy_legacy 2014-01-01→2019-09-27 (2 132 987 rows) · sec_bhavdata_full 2019-10-01→2025-12-31 (2 855 606) |
| `prices_vwap_sanity` | 12 | 100.00 % rows in range every year |
| `prices_quality` | 5 | all checks **0 violations** |
| `panel_feature_ic` (h=1) | 66 | amihud_21 IC −0.022 (t=−7.3), max_ret_21 −0.030 (t=−8.6), rev_5 +0.024 (t=7.1), mom_21 −0.003 (t=−0.9) |
| `panel_feature_stats` | 121 | 11 features × 11 years |
| `panel_nan_coverage` | 29 667 | e.g. beta_63 100 % NaN on 2015-02-02 (needs 63-day history) |
| `panel_label_dist` | 720 | 6 horizons × {raw, demeaned} × 60 fixed bins |
| `corpus_family_counts` | 10 | 53 anomalies / 10 families |
| `agents_token_budget` | 8 | Σ 16.6 calls / 26 520 tokens per thesis |

## 3. Verify it yourself

```
python dashboard/build_cache.py               # ~35-48 s; prints per-builder status
python dashboard/build_cache.py --check        # "--check: OK", exit 0
python dashboard/build_cache.py                # run again — parquets byte-identical
pytest tests/test_dash_p1_cache.py -q           # 36 passed

python - <<'PY'
import pandas as pd, numpy as np
dc = pd.read_parquet("data/dashboard/universe_daily_coverage.parquet")
x = (pd.to_datetime(dc.date) - pd.to_datetime(dc.date).min()).dt.days / 365.25
print("n_panel slope/yr:", round(np.polyfit(x, dc.n_panel, 1)[0], 4))   # ~0.003 -> FLAT
sh = pd.read_parquet("data/dashboard/panel_feature_ic_shift.parquet")
print(sh[sh.feature == "mom_21"])                                        # base vs shift1 differ
print(pd.read_parquet("data/dashboard/panel_leaky_check.parquet"))       # fwd_ret_1 -> 1.0
PY
```

No screenshots — D1 produces data files, not pages (D3 renders them).

## 4. What I could NOT verify, and why

- **`zoo_leaderboard` / `prices_yf_crosscheck` `--heavy` bodies** — left as `no_source` stubs (see §6). Not run.
- **`ledger_summary` / `loop_*` against real data** — `data/ledger.db` has 0 `counts_as_trial=1` rows and `data/loop_checkpoint.db` does not exist (P11 hasn't run). The builders' non-empty paths are exercised only by reading a snapshot that currently yields nothing; the `no_source` path is what's verified. They will light up automatically when P11 writes those artifacts (the manifest `sources` mtimes will then flag them stale until a rebuild).
- **`universe_overlap` NSE column** — `data/raw/ind_nifty200list.csv` (the path `src.config` / `src.universe.NSE_CURRENT_LIST` points at) does not exist; `_nse_current_union()` returns `None`. `overlap_nse_current_pct` is NaN, `status:"partial"`. (`data/raw/nse_meta/ind_niftytotalmarket_list.csv` exists but is a different, broader index — not used.)
- **`panel_feature_ic` "reuse `src.backtester._daily_ic`"** — I used a local vectorised `_wide_ic` instead (§7 #1). It is the same math as `src.gates._wide_rank_ic` (verified: matches `_daily_ic` mean to ~1e-6 on a spot check) but ~60× faster, which is what keeps the cheap pass under 90 s.

## 5. Failures and open issues

- **None blocking.** All 24 cheap parquets build, `--check` is green, the suite passes.
- **`data/dashboard/_snap/` accumulates snapshots** — one `.db` copy per distinct source read, including `fake_ledger.db` left by a D0 test. It is a cache dir under the one allowed write path; a `--clear-snap` flag would be nice-to-have. Not required.
- Cosmetic: `streamlit.runtime.caching` prints "No runtime found" warnings when `build_cache.py` imports `dashboard.lib.data` outside a Streamlit process. Harmless; stderr only.

## 5b. Findings surfaced (not bugs in this phase — do NOT "fix" here)

1. **Universe coverage is genuinely FLAT** (`n_panel` slope **+0.003 names/yr**, always 198–200). P1's liquidity-defined, point-in-time universe shows *no* survivorship bias. This is the decisive evidence the D3 Universe page opens on — it is a **pass**, not a problem.
2. **The supplied constituent CSV covers only ≈ 55 %** of our monthly universe (`universe_overlap.overlap_supplied_csv_pct` ≈ 54–57 % across all 131 months). This is the evidence for **D7 Bad Example ①** (the supplied CSV was structurally broken / padded to 200) — surfaced here, reconciled there.
3. **Monthly churn runs ~4.7 % mean, up to 9.5 %** — above the "2–5 %" band the D3 spec mentions. Expected for a universe defined by a hard rank-200 turnover cutoff: names near the boundary oscillate in/out monthly. A P1 characteristic, not a defect.
4. **`prices_extreme_returns` is mostly "unexplained" (416 / 453)** because the series is **CA-adjusted** — splits/bonuses don't produce a jump in `close`. The tagged rows are demergers (32; P2 flags-not-adjusts them by design) plus a few. Correct behaviour; the D3 page frames these as "Indian mid-caps genuinely move like that, not winsorized".
5. **`mom_21` real-data IC ≈ 0** (−0.003, t = −0.9). The planted RankIC ≈ 0.04 lives only in `src.contracts.make_fake_features` (the fixture panel), exactly as `DASHBOARD_PLAN.md` §"Steps — 03_Feature_Panel" step 5 warns. On real data: `amihud_21`, `max_ret_21`, `rev_5`, `beta_63`, `vol_21`, `delivery_pct`, `dist_52wh`, `turnover_21`, `size_proxy` all clear |t| > 3 at h=1.
6. **`universe_stats` has a 2015-01-30 row (200 members) one month before the membership panel starts (2015-02-02).** `universe_monthly` reports that row's churn as 0 (no prior snapshot to diff against). Noted, not altered.
7. **SUZLON has 5 in-universe intervals** in `universe_intervals` — genuine rotation across the rank-200 liquidity cutoff (2015→2018, brief 2018-12, 2019, 2022, 2022→2025). Not a splitting artifact.

## 6. Anything that contradicts this plan

- **`zoo_leaderboard` / `prices_yf_crosscheck` — `--heavy` bodies deferred.** The D1 brief says *"LEAVE `zoo_leaderboard` and `prices_yf_crosscheck` as `status:"no_source"` unless `--heavy` (D4 and D3 own the 'compute now' fallbacks)"* and *"Do not run `zoo_leaderboard` in the cheap pass. Do not hit the network outside `--heavy`."* — yet D1 **step 14** sketches their `--heavy` algorithms. These pull in opposite directions. I took the brief + "D4 and D3 own" as decisive and left both as registered `no_source` stubs (they emit a 0-row schema-correct parquet even under `--heavy`). D4 builds the zoo leaderboard compute-now button; D3 builds the yfinance fallback. **Flagging for the owner** — if you want the `--heavy` bodies in D1, say so and I'll add `zoo_leaderboard` (deterministic, no network) now; `prices_yf_crosscheck` genuinely belongs with D3 (network + per-symbol schema P2 didn't commit to).
- **`panel_feature_ic` — used a local `_wide_ic`, not `src.backtester._daily_ic`.** The plan allows "a local Spearman is fine — document which"; documented (§7 #1). Same method as `src.gates._wide_rank_ic`.

## 7. Decisions I made that the plan left open

1. **`_wide_ic`** — one vectorised per-day IC over aligned wide `date×symbol` frames (rank first for Spearman), `min_names=20` (= `backtester.MIN_STOCKS_PER_DAY`), days below threshold dropped. Replaces 132 `_daily_ic` calls; cuts `panel_feature_ic` + `panel_feature_ic_shift` from a projected ~2 min to < 3 s. Verified equal to `_daily_ic` to ~1e-6.
2. **IC window = the whole pre-HOLDOUT panel** (warmup + train + val_a + val_b, `date < config.HOLDOUT_START`), not one named split. HOLDOUT is never read (`_panel_wide` filters before pivoting; `panel_leaky_check` and `panel_label_dist` filter too). `HOLDOUT_START` is read live from `src.config`, never retyped.
3. **`panel_leaky_check`** — one row per horizon, `fwd_ret_h` vs `fwd_ret_h_demeaned`; all six = exactly 1.0 (per-day demean is a monotone shift → identical ranks). Cleaner than a self-vs-self 1.0.
4. **`ledger_summary.cumulative_effective`** — cheaper proxy: the participation ratio `(Σ|IR|)² / Σ IR²` of the running trial-IR series, *not* `src.gates.effective_trial_count` (which needs canonical ASTs the trials-table summary doesn't carry). Documented in a code comment. Moot right now (ledger empty → `no_source`).
5. **`universe_overlap` → `status:"partial"`** when only the NSE list is missing but the supplied-CSV column is populated (rather than blanking the whole frame to `no_source`).
6. **`universe_intervals` run split** = a gap > 7 calendar days between consecutive in-universe trading days starts a new `(start,end)` interval.
7. **`prices_coverage_yearly`** definitions: `universe_days` = distinct trading dates that year; `covered_days` = days with `n_panel / n_members ≥ 0.99`; `covered_pct` = `100 · mean(n_panel / n_members)`; `n_symbols` = distinct universe members that appeared that year.
8. **`prices_quality`** — added a 5th row `vwap outside [low,high]` (0 violations) beyond the 3 the plan names.
9. **`_finish(name, df, status, note)`** — every builder routes its frame through it: coerces each column to the `CACHE_SCHEMAS` dtype (tz-strip + normalize dates, int64/float64/bool/object), reorders to the schema, `_assert_schema`, tags `df.attrs["status"/"note"]`. `_write` writes `df.attrs["note"]` into the manifest, falling back to the registry note.
10. **`_ohlcv()` reads 8 columns once** (`date, symbol, close, high, low, vwap, volume, source`) and is `lru_cache`d for the process — shared by all six price builders so `ohlcv.parquet` (4.99 M rows) is read from disk exactly once per pass.
11. **`agents_token_budget` note** clarified: the T3 per-role `(calls, tokens/call)` table is hard-coded (it is a measured *projection*, not a config value), but `tier` is read live from `src.config.LLM_ROLE_TIER`.

## STOP — awaiting sign-off.
