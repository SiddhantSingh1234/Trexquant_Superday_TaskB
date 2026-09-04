# Alpha Factory Dashboard

A local Streamlit app that explains and lets a reviewer explore the Alpha Factory
research system (see `../IMPLEMENTATION_PLAN.md`, `../FLOW_EXPLAINED.md`).

Read-only over the project's data. It never mutates `data/` except its own cache
`data/dashboard/`, never calls a paid API, never calls a live LLM.

## Run it (three commands)

```
pip install -r requirements-dashboard.txt
python dashboard/build_cache.py            # precompute the small aggregates (< 90s)
streamlit run dashboard/Home.py
```

`--heavy` adds the opt-in builders (`zoo_leaderboard`, `prices_yf_crosscheck`) —
minutes, and `prices_yf_crosscheck` hits the network.

## Phase map (dashboard build)

| Phase | Deliverable |
|---|---|
| D0 | scaffold, `lib/` contracts, theme, cache-builder registry, fixtures |
| D1 | every cheap cache builder → `data/dashboard/*.parquet` |
| D2 | `Home.py`, the six flowcharts (`lib/flow`), the narrative library (`lib/narrative`) |
| D3 | `01_Universe`, `02_Prices`, `03_Feature_Panel` |
| D4 | `04_Backtester`, `05_Operators_and_Zoo` |
| D5 | `06_Gates_and_Ledger`, `09_Red_Team` |
| D6 | `07_Memory`, `08_LLM_Agents` |
| D7 | `10_The_Loop`, `11_Alpha_Cards`, `12_System_Evaluation`, `13_Bad_Examples` |
| D8 | `14_Build_Log`, consistency pass, deploy notes |

## Cache builders

`python dashboard/build_cache.py --list` prints the live registry. Each builder
writes one `data/dashboard/<name>.parquet` plus a row in `_manifest.json`
(`rows`, `cols`, `built_at`, `builder_version`, `status`, `note`, `sources`).
A missing source → an empty schema-correct frame + `status:"no_source"`.

`--check` verifies every parquet against `lib/fixtures.CACHE_SCHEMAS` and reports
staleness (a source newer than its cache); it exits non-zero when a cache is
stale — expected while P11/P12 are running.

### Builder catalogue (D1)

Cheap pass measured at **~34-48 s** on the dev machine (well under the 90 s
budget). One columnar read of `ohlcv.parquet` (8 cols) is shared across every
price builder.

| Builder | Cost | Source | Notes |
|---|---|---|---|
| `universe_daily_coverage` | cheap | membership, ohlcv | `n_panel = |members(D) ∩ traded(D)|`; 2015→2025 `n_panel` slope ≈ **+0.003 names/yr** (FLAT) |
| `universe_monthly` | cheap | universe_stats, membership | monthly churn in/out/pct (mean ≈ 4.7 %) |
| `universe_intervals` | cheap | membership + `src.universe.CANARIES/HEAVYWEIGHTS` | in-universe (start,end) runs |
| `universe_sector_comp` | cheap | membership, features(`sector`) | sector labels are current, not point-in-time |
| `universe_overlap` | cheap | membership, supplied CSV, NSE list | `status:"partial"` — NSE current-list file absent, that column is NaN |
| `prices_coverage_yearly` | cheap | ohlcv, membership | per-year covered_pct ≈ 99.9 % |
| `prices_ca_counts` | cheap | corporate_actions | per (year, type) |
| `prices_extreme_returns` | cheap | ohlcv, corporate_actions | `|adjusted daily ret| > 0.5`, CA-tagged within ±1 day; **not winsorized** |
| `prices_source_eras` | cheap | ohlcv | bhavcopy_legacy → 2019-09-27, then sec_bhavdata_full |
| `prices_vwap_sanity` | cheap | ohlcv | % rows with low ≤ vwap ≤ high (≈ 100 %) |
| `prices_quality` | cheap | ohlcv | close≤0 / high<low / neg volume / dup key — all 0 |
| `prices_yf_crosscheck` | **--heavy** | reports/p2_* | left `status:"no_source"` — D3 owns the yfinance fallback |
| `panel_feature_stats` | cheap | features | per feature × year distribution summary |
| `panel_feature_corr` | cheap | features | pairwise Pearson |
| `panel_feature_ic` | medium | features, labels | daily Spearman/Pearson IC × 6 horizons, vectorised (`_wide_ic`, same method as `src.gates._wide_rank_ic`); pre-HOLDOUT only |
| `panel_feature_ic_shift` | medium | features, labels | h=1, base vs feature panel shifted +1 day — the two **differ** (mom_21 by >100 % rel) |
| `panel_leaky_check` | cheap | labels | `fwd_ret_h` predicting its own demeaned label → RankIC = **1.0** |
| `panel_xsec_size` | cheap | features | distinct symbols/day |
| `panel_nan_coverage` | cheap | features | per (day, feature) NaN fraction |
| `panel_label_dist` | cheap | labels | fixed-bin histogram, raw vs demeaned |
| `zoo_leaderboard` | **--heavy** | zoo, backtester, panel | left `status:"no_source"` — D4 owns the compute-now fallback |
| `ledger_summary` | cheap | ledger.db (read-only snapshot) | `no_source` until the loop records a `counts_as_trial=1` row |
| `loop_generations` / `loop_run_meta` | cheap | loop_checkpoint.db | `no_source` until P10/P11 runs |
| `corpus_family_counts` | cheap | anomalies.json | 53 anomalies / 10 families |
| `agents_token_budget` | cheap | `src.config` (live) + T3 projection | Σ 16.6 calls / 26,520 tokens per thesis |

## Layout

```
dashboard/
  Home.py            build_cache.py       README.md
  pages/NN_Title.py  (one file = one sidebar entry)
  lib/
    data.py          cache layer + sliced project-data readers + _readonly_sqlite
    charts.py        PALETTE, TEMPLATE, chart builders
    flow.py          6 flowcharts + region timeline (D2)
    narrative.py     prose blocks (D2)
    ui.py            page_header / data_missing / pending_banner / stale_banner
    fixtures.py      CACHE_SCHEMAS + fake_cache / fake_cards / fake_loop_generations
    engine.py        the ONLY bridge to src/ compute (backtester / gates / redteam)
```
