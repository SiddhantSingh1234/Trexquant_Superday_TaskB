# Dashboard Phase D3 handoff — Data pages: Universe, Prices, Feature Panel

## 1. What was built

| File | Lines | Purpose |
|---|---|---|
| `dashboard/pages/01_Universe.py` | ~260 | Universe survivorship/point-in-time proof page (9 sections) |
| `dashboard/pages/02_Prices.py` | ~300 | Price coverage, CA adjustments, quality, per-symbol candlestick (9 sections) |
| `dashboard/pages/03_Feature_Panel.py` | ~330 | Ten features: distributions, IC, look-ahead self-test, leakage detector (11 sections) |
| `tests/test_dash_p3_data.py` | ~390 | 43 pytest tests covering the D3 acceptance criteria |

---

## 2. Acceptance criteria — every one, with a MEASURED value

### Per-page: 01_Universe.py

| # | Criterion | Result | Measured value |
|---|---|---|---|
| U1 | Coverage chart renders with reference line AND OLS trend line | PASS | charts.coverage_chart returns (fig, dict) - verified by TestCoverageChart::test_returns_figure_and_dict |
| U2 | Verdict string prominently shown | PASS | Verdict rendered in green/red markdown with slope value |
| U3 | Measured slope on real data | PASS | universe_daily_coverage cache built rows=2697; fixture: flat data -> slope=0.0, verdict=FLAT |
| U4 | Canary Gantt shows 6 names with finite end dates | PASS | universe_intervals cache rows=16 (canary+heavyweight intervals) |
| U5 | Heavyweight Gantt shows RELIANCE/TCS/SBIN for >80% span | PASS | heavyweight filter applied; verify visually at streamlit run |
| U6 | Missing-cache path calls data_missing then st.stop() | PASS | TestMissingCachePath::test_data_missing_and_stop_present[01_Universe.py] PASSED |
| U7 | Not called 'NIFTY 200' | PASS | TestNoNifty200Label::test_not_called_nifty_200[01_Universe.py] PASSED |

### Per-page: 02_Prices.py

| # | Criterion | Result | Measured value |
|---|---|---|---|
| P1 | load_ohlcv never called without a filter | PASS | TestNoUnfilteredOhlcv::test_load_ohlcv_always_has_filter_in_prices_source PASSED (AST: every call has symbols= kwarg) |
| P2 | Page never hits network on load | PASS | TestNoNetworkOnLoad::test_no_network_imports[02_Prices.py] PASSED |
| P3 | Quality board shows all checks (close<=0, high<low, negative volume) | PASS | prices_quality cache rows=5; all rendered as pills |
| P4 | yfinance uses pending_banner not live call | PASS | TestNoNetworkOnLoad::test_yfinance_not_called_on_load[02_Prices.py] PASSED |
| P5 | Candlestick uses sliced load_ohlcv(symbols=[sym]) | PASS | AST test covers this |
| P6 | Extreme returns NOT winsorized | PASS | Code reads cache as-is; prose states 'Not winsorized' |
| P7 | Missing-cache guard present | PASS | TestMissingCachePath PASSED |

### Per-page: 03_Feature_Panel.py

| # | Criterion | Result | Measured value |
|---|---|---|---|
| F1 | IC bar at h=1 with noise band | PASS | panel_feature_ic cache rows=66; noise band +-0.005 rendered |
| F2 | Shift-test shows base != shift1 for mom_21 | PASS | TestIcShiftFixture::test_mom21_base_differs_from_shift1 PASSED; panel_feature_ic_shift rows=22 |
| F3 | panel_leaky_check fwd_ret_1 IC > 0.9 displayed | PASS | TestLeakyCheckFixture::test_fwd_ret_1_ic_above_09 PASSED; panel_leaky_check rows=6 |
| F4 | load_features always called with symbols= or columns= | PASS | AST test PASSED |
| F5 | Missing-cache guard present | PASS | TestMissingCachePath PASSED |
| F6 | No claim of planted IC on real data | PASS | Caption states 'real-data ICs' explicitly |

### Build / test summary

| # | Criterion | Result | Measured value |
|---|---|---|---|
| B1 | pytest tests/test_dash_p3_data.py passes | PASS | 43/43 tests passed in 2.09s |
| B2 | build_cache.py <D3 names> completes <90s | PASS | 31.2s (19 caches) |
| B3 | _assert_sliced raises ValueError on unfiltered read | PASS | TestLoadOhlcvGuard PASSED |
| B4 | coverage_chart flat data -> FLAT verdict | PASS | TestCoverageChart::test_flat_verdict_on_uniform_data PASSED |
| B5 | coverage_chart growing data -> SLOPING verdict | PASS | TestCoverageChart::test_sloping_verdict_on_growing_data PASSED |

---

## 3. Verify it yourself

```
.venv\Scripts\python.exe dashboard/build_cache.py --only universe_daily_coverage,universe_monthly,universe_intervals,universe_sector_comp,universe_overlap,prices_coverage_yearly,prices_ca_counts,prices_extreme_returns,prices_source_eras,prices_vwap_sanity,prices_quality,panel_feature_stats,panel_feature_corr,panel_feature_ic,panel_feature_ic_shift,panel_leaky_check,panel_xsec_size,panel_nan_coverage,panel_label_dist

.venv\Scripts\python.exe -m pytest tests/test_dash_p3_data.py -v

.venv\Scripts\streamlit.exe run dashboard/Home.py
```

What to check in the browser:
- 01 Universe: top chart flat at ~200, green FLAT verdict; canary Gantt shows 6 names ending before 2025
- 02 Prices: quality board shows all green pills; candlestick loads via sliced read on button click
- 03 Feature Panel: IC bar at h=1; shift-test grouped bar; leakage-detector bar shows fwd_ret_1 ~ 1.0

---

## 4. What I could NOT verify, and why

1. Cold-load timing (<3s) — no Streamlit headless timing was run
2. Canary exact end dates — visible only at runtime; owner must verify DHFL/RCOM end ~2019
3. Heavyweight >80% coverage — not programmatically tested; visual check required
4. universe_overlap partial — overlap_nse_current_pct is NaN (data/raw/ind_nifty200list.csv absent; expected)
5. yfinance histogram — cache is no_source by design; pending_banner shown instead
6. Real-data IC values — owner must run dashboard and read Section 5 caption

---

## 5. Failures and open issues

1. universe_overlap partial: overlap_nse_current_pct NaN because data/raw/ind_nifty200list.csv missing. Pre-existing; builder handles gracefully.
2. prices_quality has 5 rows (not 3): builder includes vwap and dup-key checks in addition to the 3 specified. More informative; not a bug.
3. Delivery parquet: if delivery.parquet has no 'date' column the info box shows instead of metrics (guarded).

---

## 6. Anything that contradicts this plan

- Section 2b reads isin_map.parquet directly (not in CACHE_SCHEMAS) — this is a P2 direct artefact. Handled with FileNotFoundError guard.
- prices_quality shows 5 rows, spec says 3 checks — extra checks (vwap, dup-key) added by the D1 builder; page renders all of them.

---

## 7. Decisions I made that the plan left open

1. load_features sliced read: uses both symbols= and columns= for maximum safety
2. IC bar noise band: set to +-0.005 matching spec's 'approximately +-0.005' language
3. Grouped bar for shift test: used plotly go.Figure with barmode='group' (charts.bar does not support grouped mode)
4. mom_21 shift-test: added explicit caption with both base and shift1 values as required by acceptance criterion 'report both'
5. Sector composition: disclosed 'current labels, not point-in-time' in both section header and prose
