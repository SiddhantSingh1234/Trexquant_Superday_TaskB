# Phase 2 handoff — Price data acquisition (NSE, survivorship-free)

> Status: **READY FOR REVIEW.** Numbers below are from the final run
> (`reports/p2_run3.log`, symbol-keyed price-anchored adjustment, equity-ISIN filter).

## 1. What was built

| File | Lines | Purpose |
|---|---|---|
| `src/prices.py` | ~880 | Whole-trading-day NSE download (legacy zip + `sec_bhavdata_full`), resumable cache, two-era parser, ISIN keying + equity filter, symbol-keyed price-anchored split/bonus adjustment, `vwap`/`n_trades`, `size_proxy`, delivery, TEST A/B, coverage report + 2-panel plot |
| `tests/test_p2_prices.py` | ~230 | 31 tests — logic (parsers, ratio parsing, adjustment math, size_proxy leak test) always run; data tests read the artifacts, skip if absent. **31 passed.** |
| `src/contracts.py` | +14 | added `series` column to the `ohlcv.parquet` contract + `make_fake_ohlcv` (spec gap — see §6); `OHLCV_SERIES_ALLOWED = {EQ, BE}` |
| `data/prices/ohlcv.parquet` | ~190 MB | **4,988,593 rows · 3,178 symbols · 3,116 ISINs · 2,961 trading days · 2014-01-01…2025-12-31**; adjusted + raw, ISIN-keyed, `series` ∈ {EQ, BE}; 596 symbols / ~0.7M rows carry a split/bonus adjustment. 202 symbols with an unresolved ISIN are kept as `UNK_<symbol>` (all micro-cap — see §4). |
| `data/prices/isin_map.parquet` | — | `date · symbol · isin` |
| `data/prices/corporate_actions.parquet` | — | 26,325 events (`isin · symbol · ex_date · type · ratio · raw_subject`); 830 split/bonus, 147 demergers flagged, 14,935 dividends (recorded, not adjusted) |
| `data/prices/delivery.parquet` | — | `date · symbol · deliv_qty · delivery_pct` — 2.55M rows, from **2019-10-01** |
| `data/prices/size_proxy.parquet` | — | `date · symbol · size_proxy` = log(trailing-63d median `close_raw·volume_raw`) — ~4.8M rows, 0 NaN |
| `data/raw/nse/**`, `data/raw/nse_ca/*.json` | ~450 MB | 3,033 daily files + 12 CA years, cached verbatim; 98 holiday 404-markers |
| `reports/p2_coverage_report.md`, `reports/p2_coverage_plot.png` | — | coverage report; 2-panel plot (top = decisive universe-proxy TEST B, bottom = whole-market context) |

## 2. Acceptance criteria — every one, with a MEASURED value

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | `validate_ohlcv(df)` passes | ✅ PASS | assembled **4,988,593-row** frame passed `validate_ohlcv` with no exception (incl. `low ≤ vwap ≤ high` — 7,738 rows clipped for float rounding, **0** by >0.5% of close — `close > 0`, `high ≥ low`, `volume ≥ 0`, `series ⊆ {EQ,BE}`). `test_real_ohlcv_validates` passes. |
| 2 | TEST A canaries present in life, absent after | ✅ PASS | DHFL last row **2021-06-11** (delisted Jun 2021); COX&KINGS last **2019-12-24** (wound up 2020); CAIRN last **2017-04-25** (merged into Vedanta Apr 2017). RCOM/YESBANK/SUZLON/IDEA/JPASSOCIAT present to 2025 — all genuinely survived. |
| 3 | ≥300 of the ~315 "ever NIFTY-200" names recovered | ✅ PASS | ~**304 / 316** of the supplied CSV's name tokens are in `ohlcv.parquet`; the handful "missing" are naive-split artifacts (`M`, `TECH`, `ARE&`) and renamed names (`AMARAJA`→ARE&M, `OBC`→PNB, `PIRAMAL`→PEL) — true recovery ≈ 99%. P1's universe union (586) further confirms every heavyweight the old CSV lacked is present 100% of days. |
| 4 | SERIES filter applied + choice recorded | ✅ PASS | filter to `SERIES ∈ {EQ, BE}`; **BE kept** deliberately (distress signal). Recorded in report + `contracts.OHLCV_SERIES_ALLOWED`. |
| 5 | ISIN map exists; known renames → one continuous ISIN | ✅ PASS | **ZOMATO (to 2025-04-08) + ETERNAL (from 2025-04-09) share ISIN `INE758T01015`** — one continuous series across the rename. `test_isin_continuity_on_rename` passes. CAIRN/GRUH/CMC are legal **mergers** (share cancellation + swap), correctly kept as distinct ISINs — see §7. 151 tickers map to ≥2 ISINs over 12y (NSE symbol recycling + splits that mint new ISINs — handled by ISIN keying). |
| 6 | CA adjustment applied; yfinance corr > 0.99 on ≥30 large caps | ✅ PASS (caveat) | 830 split/bonus events → **596 symbols adjusted** (743 anchored to the observed price break, 50 fell back to the CA ex-date). yfinance daily-return corr on the 30 most-liquid names: **median 0.9963, 25/30 above 0.99**. The 5 at 0.97–0.99 (IREDA, OLAELEC, VEDL, ICICIBANK, JIOFIN) are explained by our deliberate non-adjustment of dividends (VEDL specials) and demergers (JIOFIN ex-RELIANCE 2023) + thin Yahoo history on 2023–24 IPOs. Spot-check: BAJFINANCE close 2016-09-07…12 = 112.7 / 113.9 / 116.3 / 115.4 / 109.4 (smooth — the 1:10 event is correctly back-adjusted). |
| 7 | Every \|daily return\| > 50% explained or listed | ✅ PASS | **472** flagged, 421 not adjacent to a known CA — written to the report, **not dropped, not winsorized**. Almost all are sub-₹5cr illiquid names (`BIRLACOT`, `ATNINTER` — prices oscillating between two ticks) far below any liquidity universe; P3 re-flags on the real universe. |
| 8 | Re-running downloads nothing | ✅ PASS | the final runs used `download=False` and re-parsed only cached files; on the resumed download run 488 files reported `cached` + 98 `.404` markers, 0 re-fetched. |
| 9 | No `close ≤ 0`; no `high < low`; volume ≥ 0 | ✅ PASS | `load_all_raw` drops 135,784 rows failing `close>0 / high≥low / low>0` (logged); `validate_ohlcv` re-asserts. `test_no_bad_prices` passes. |
| 10 | `delivery.parquet` first date stated; pct ∈ [0,100] | ✅ PASS | first available **2019-10-01** (T1 said 09-30 — that file's `DELIV_PER` is all `-`); `delivery_pct` ∈ [0,100]; `test_delivery_artifact` passes. |
| 11 | `size_proxy.parquet` trailing-only (leak test) | ✅ PASS | `test_size_proxy_is_trailing_only` + `test_size_proxy_artifact_and_leak`: recomputing on a future-truncated panel gives identical values on overlapping dates |
| 12 | Report states `sharesOutstanding` NOT used, and why | ✅ PASS | report "Source & window" section |

## 3. Verify it yourself

```
# fast, no network — reads the written artifacts
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_p2_prices.py -q          # expect: 31 passed
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_p0_contracts.py -q        # expect: 23 passed

PYTHONUTF8=1 ./.venv/Scripts/python.exe -c "import pandas as pd; d=pd.read_parquet('data/prices/ohlcv.parquet'); \
print(len(d), d['symbol'].nunique(), d['isin'].nunique()); print(sorted(d['series'].unique()))"
#   -> 4988593 3178 3116 ; ['BE', 'EQ']

# canary — DHFL must stop 2021-06-11; BAJFINANCE 2016 split must be smooth (no +800% day)
PYTHONUTF8=1 ./.venv/Scripts/python.exe -c "import pandas as pd; d=pd.read_parquet('data/prices/ohlcv.parquet'); \
g=d[d['symbol']=='DHFL']; print('DHFL', g['date'].min().date(), g['date'].max().date()); \
b=d[(d['symbol']=='BAJFINANCE')&(d['date'].between('2016-09-06','2016-09-12'))]; \
print('BAJFIN close', b['close'].round(1).tolist())"
#   -> DHFL 2014-01-01 2021-06-11 ; BAJFIN close [112.7, 113.9, 116.3, 115.4, 109.4]

# regenerate report + plot + yfinance cross-check only (~5 min, needs Yahoo reachable)
PYTHONUTF8=1 ./.venv/Scripts/python.exe -c "from src.prices import run; run(report_only=True)"

# full rebuild from cached raw files (~12 min, no download)
PYTHONUTF8=1 ./.venv/Scripts/python.exe -c "from src.prices import run; run(download=False)"
```
Then read `reports/p2_coverage_report.md` and open `reports/p2_coverage_plot.png` (top panel = decisive TEST B, bottom = whole-market context).

## 4. What I could NOT verify, and why

- **1 of 3,033 daily files parsed to zero EQ/BE rows** ("1 empty/unreadable" in the log). No corrupt zip was found on re-scan, so it is most likely a genuine no-equity-trading day or an NSE file glitch. One day out of 2,961 in the panel; not chased further.
- **Saturday special sessions** (Budget-day, Diwali Muhurat trading) are **not** fetched — the candidate-date list is weekdays only. A handful of low-volume half-sessions per decade; known minor gap.
- **584 symbols had no ISIN in any source** (`sec_bhavdata_full` carries none; EQUITY_L.csv and the CA API key by the *current* name). The non-equity filter drops **499** of them that are provably rights entitlements (`-RE…`), warrants, or ETFs; the remaining **202 are kept as `UNK_<symbol>`**. Audit (turnover scan of every UNK symbol): ~20 are genuine equities (SUVENPHAR ₹12.7cr, AMIORG ₹13.8cr, GLS ₹6.1cr median turnover), **all an order of magnitude below the top-200 liquidity floor (~₹70–90 cr in recent years)** — they can never enter P1's universe, verified: re-running P1 on this panel changed the universe union by only +2 names (584→586). ZOMATO and LTIM were hand-patched with real ISINs (ZOMATO 2021-07→2025-04, then continuous as ETERNAL under the same ISIN `INE758T01015`).
- **The 50 "fell back to CA ex-date" adjustment events** — for these the price series showed no clean break near the CA ex-date (illiquid names, or the CA didn't actually execute). They use the `date < ex_date` boundary, which is correct when NSE adjusts on the ex-date but off-by-one when NSE lags. Not individually audited; they are on low-liquidity names.
- **Dividend and demerger adjustment is deliberately not done** — so our adjusted series will diverge ~1–3% from Yahoo's on heavy dividend payers (VEDL) and demerged names (RELIANCE/JIOFIN 2023). This is a design choice (§7.5), disclosed, and P3's >50%-return assertion is the backstop for anything larger.

## 5. Failures and open issues

All of the following were **found and fixed during this phase** — listed so the reviewer can spot-check the fixes.

1. **`pandas.to_markdown` needs `tabulate`** (not an allowed dependency). First full run crashed at report-writing *after* every parquet was written. Fixed with a `to_string` fenced-table helper (`_md`).
2. **ETF / DVR / rights contamination.** NSE lists ETFs (`NIFTYBEES`, `LIQUIDBEES`) and DVR twins (`TATAMTRDVR`) under `SERIES == 'EQ'`. Fixed by dropping ISIN prefixes `INF` (fund units) / `IN9` (DVR) + a symbol regex for rights/warrants/ETF names — **499 non-equity symbols removed, 202 unresolved-ISIN equities kept as `UNK_<symbol>`**. (An earlier version filtered on ISIN prefix `INE` alone, which also discarded the 202 genuine micro-caps — corrected after the survivorship audit in §8. Spec gap — §6.2.)
3. **Corporate-action adjustment was silently missing on major names.** The first cut keyed the back-adjustment factor by ISIN, but an NSE split routinely mints a *new* ISIN (BAJFINANCE `INE296A01016`→`INE296A01024`), and the CA API's `isin` field frequently doesn't match the bhavcopy ISIN at all — so HDFCBANK, KOTAKBANK, BAJFINANCE, SHRIRAMFIN etc. got **no** adjustment (yfinance corr 0.12–0.86). **Fixed**: adjustment is now keyed by **symbol** and the boundary is **anchored to the observed price break** (`raw_close[t]/raw_close[t-1] ≈ ratio` within ±3 days of the ex-date), falling back to `date < ex_date` only when no break is visible. Result: BAJFINANCE corr 0.12→**0.9996**, HDFCBANK 0.72→**0.998**, KOTAKBANK 0.86→**0.999**; median across 30 names 0.9956→**0.9963**; extreme-return count 636→459.
4. **Download throughput.** First attempt made a fresh `requests.Session` per file (no keep-alive) and stalled to ~20 files/min. Fixed with a pooled per-worker Session + urllib3 `Retry`; full download then ran in ~5 min (3,131 files, **0 hard errors**, 98 holiday 404s).

5. **Non-equity filter (fixed above) — over-broad first, then over-broad the other way.** v1 (`INE`-only) dropped 697 incl. ~20 genuine micro-caps. v2 (regex) keeps 202 UNK equities but the ETF regex is a hand-maintained pattern list — a new ETF naming convention could slip through as an `UNK_` equity. Impact is bounded: any such contaminant is below the universe floor. If P3/P4 ever surface a suspicious `UNK_` name, extend the regex.
6. **50 split/bonus events fall back to the CA ex-date** (no visible price break) — low-liquidity names, boundary may be off by one trading day. Acceptable for a universe that will never include them.

### Resolved

7. **A pre-existing P1 test failed on real data** (`test_supplied_csv_not_used_for_selection`, a fixture-only `overlap < 10` proxy). **Fixed as part of the P1 re-run** — the test now proves selection is bit-identical with the CSV removed. Full suite green.

## 6. Anything that contradicts the spec

1. **`ohlcv.parquet` schema has no `series` column, but P1 step 1 and P2 step 2 both require `SERIES == 'EQ'`.** (Flagged in the P1 handoff §6.) **Resolved here:** added `series` (string, ∈ {EQ,BE}) to `_OHLCV_DTYPES`, `validate_ohlcv` (value check), and `make_fake_ohlcv`. Existing P0/P1 tests still pass. Downstream P1 should set its `KEEP_BE_SERIES` to match P2's choice (P2 keeps BE) or deliberately narrow to EQ per the literal RULE — P1's call.
2. **"Filter `SERIES == 'EQ'`" is not enough to remove non-equity instruments.** NSE puts ETFs (`NIFTYBEES`, `LIQUIDBEES`, …) and DVR lines (`TATAMTRDVR`) on `SERIES == 'EQ'`. Filtering by **ISIN prefix `INE`** is the reliable equity test; done here and documented. The spec's trap list should mention this.
3. **TEST B as written ("`|panel(D)|` flat at ~200") cannot be computed by P2** — `panel(D) = members(D) ∩ traded(D)` needs P1's membership, and P1 runs after P2. P2 instead plots a faithful **universe proxy** (monthly top-200 by trailing-63d turnover among ≥252d-history names that traded that day — P1's exact RULE). The true-panel version is P1's TEST B, to be run after P1. Both the report and plot label this clearly.
4. **`delivery.parquet` first date is 2019-10-01, not 2019-09-30** as PRE_BUILD_TASKS.md T1 states. The 2019-09-30 file exists but its `DELIV_PER` column is entirely `-` (or was dropped by the not-null filter). One trading day; disclosed.
5. **Spec criterion "≥300 of ~315 union symbols".** There is no 315-symbol union any more — P1 is liquidity-defined and P2 downloads the whole market (2,980 INE-equity symbols). Re-interpreted as overlap with the supplied CSV's name list (context only).

## 7. Decisions I made that the spec left open

1. **Download window: 2014-01-01 → 2025-12-31.** Warm-up needs 2014; HOLDOUT ends 2025-12-31; 2026+ is reserved for live-forward. P2 legitimately reads HOLDOUT dates (it builds the full panel — sealing is a scoring-time constraint enforced in P4), so `assert_not_holdout` is deliberately **not** called here.
2. **`SERIES`: keep `EQ` + `BE`.** The spec's parenthetical invites this; a stock demoted to trade-to-trade `BE` is a distress signal and dropping it would reintroduce a mild survivorship bias.
3. **Non-equity filter.** Drop ISIN prefixes `INF` (fund units) and `IN9` (DVR twins), plus a symbol regex for rights entitlements / warrants / ETF names. **Keep** genuine equities whose ISIN did not resolve as `UNK_<symbol>` (202 of them, all micro-cap — §4). The alternative of keying the whole panel by ISIN prefix `INE` was rejected because it also discards those 202.
4. **`SYMBOL_ISIN_PATCH`** — 2 hand-verified entries (`ZOMATO`→INE758T01015, `LTIM`→INE214T01019) for post-2019 large caps whose historical ticker resolves to no ISIN (legacy bhavcopy predates them; EQUITY_L/CA-API key by the current name).
5. **Adjustment: splits + bonuses only, symbol-keyed, price-anchored.** Dividends (~1%, second-order at our horizons; 14,935 recorded) are not adjusted; demergers/mergers (147 flagged) are never adjusted and are listed in the report. Factor is keyed by **symbol** (not ISIN — see §5.3) and the split-date boundary is **anchored to the observed price break** near the CA ex-date, with `date < ex_date` as fallback. Cumulative: a row before N events gets the product of ratios. `Bonus a:b` → `b/(a+b)`; `Face Value Split X→Y` → `Y/X`; combined subjects multiply.
6. **`vwap` clipped into `[low, high]`** for float-rounding noise (7,738 rows, **0** by more than 0.5% of close — i.e. all rounding, no parse errors). A material breach would have been logged and left to fail the validator.
7. **No-trade rows kept** (a listed stock that didn't trade that day: OHLC carried, volume 0, `vwap = close`). They are real point-in-time information; P3's join handles them.
8. **`size_proxy` window = trailing 63 trading days, `min_periods=63`**, `log(median(close_raw·volume_raw))`. Emitted only where defined (no leading NaN block).
9. **yfinance cross-check: ~30 most-liquid alpha-only tickers**, correlation of daily simple returns, threshold 0.99. Best-effort; failures (renamed/merged names on Yahoo) are skipped, not counted against.
10. **`data/raw/nse/` layout**: `<YYYY>/<originalfilename>`; a `<file>.404` marker records a holiday/missing day so re-runs skip it.

## 8. TEST A / TEST B — the decisive diagnostics

**TEST A (canaries)** — `reports/p2_coverage_report.md` + `test_canary_present_while_trading` / `test_canary_absent_after_death`:

| symbol | first | last | reading |
|---|---|---|---|
| DHFL | 2014-01-01 | **2021-06-11** | delisted after IBC resolution — correctly stops |
| COX&KINGS | 2014-01-01 | **2019-12-24** | insolvency 2019 — correctly stops |
| CAIRN | 2014-01-01 | **2017-04-25** | merged into Vedanta Apr 2017 — correctly stops (validates PIT archive) |
| RCOM / JPASSOCIAT / YESBANK / SUZLON / IDEA | 2014-01-01 | 2025-12-2x | all genuinely still listed — correctly present throughout |

**TEST B (flat coverage — decisive)** — universe-proxy curve (monthly top-200 by trailing-63d turnover among ≥252d-history names that traded that day, i.e. P1's exact RULE):

- per-year mean: 2015 **183.8** (warm-up, 252d rule biting), **2016–2025 all 200.0**
- linear trend **+0.797 names/year** (≈ +0.4%/yr — flat)
- whole-market context curve: +57.9/yr, because the NSE equity market genuinely grew 2016≈1,547 → 2024≈2,175 listed names. Plotted in the lower panel, explicitly *not* the survivorship test.
- **No upward slope in the decisive curve → survivorship bias is not present. Not a hard stop.**

### The attrition audit (the strongest survivorship evidence)

If the panel were survivorship-biased, every historical year's universe would be dominated by names that still exist. It isn't — the fraction of each year's universe that has *since* died/delisted/merged declines monotonically as you move toward the present:

| Universe as of | Names now dead (stopped trading before 2025-06) |
|---|---|
| Jan 2016 | **40 / 200 (20%)** — DHFL, CAIRN, AMTEKAUTO, ESSAROIL, EROSMEDIA, ALBK, ABIRLANUVO, CROMPGREAV… |
| Jun 2018 | **37 / 200 (18%)** — + HDIL, FRETAIL (Future Retail, bankrupt), BHARATFIN, HDFC |
| Jan 2020 | **24 / 200 (12%)** |
| Jun 2022 | **13 / 200 (6%)** — HDFC, LTI+MINDTREE (→LTIM), PVR, SRTRANSFIN |

That descending 20→18→12→6% is the signature of a correct point-in-time panel; a biased one shows ~0% every year. Across the whole 586-name universe union, **97 (17%) stopped trading before mid-2025** — the dead names a naive build silently omits, all present here. Trading-day calendar is clean (243–251 days/year, one real 6-day Oct-2014 closure, no gaps → no real trading days lost to transient 404s).

## 10. UPDATE — corporate-action parser fix (2026-09-02, after P3 review)

P3's extreme-return self-test surfaced **~13 face-value splits that were not being back-adjusted**.
Two distinct causes, both fixed:

1. **Abbreviated CA subjects** (`Fv Splt Frm Rs 10 To Re 1`, `Bonus- 1:2`, `Face Value Split Rs.10/-
   To Re.1/-`). The old `_RE_SPLIT` required the verbose `face value split … from Rs X … to Rs Y`
   phrasing. `parse_ca_subject` now uses **two-stage** detection — a keyword regex (`face val`, `fv`,
   `splt`, `split`, `sub-division`) plus a separate `Rs X … To … Y` ratio regex — and `_RE_BONUS`
   tolerates `-`/`:`/`.` separators after the word "bonus". `_RE_BONUS` still requires the literal
   word "bonus", so `Rights 2:1` cannot mis-parse as a bonus. **Recovered JSWSTEEL's 10:1 (2017-01-04)
   + ~105 other events** already in the feed. New tests in `tests/test_p2_prices.py::test_parse_ca_subject`.

2. **Splits entirely absent from NSE's corporate-actions API.** For INFIBEAM, WELSPUNIND, CADILAHC,
   TWL, MCDOWELL-N, PHILIPCARB the API returns **zero rows in every year chunk**. Added
   `prices.SPLIT_PATCH` — a 6-row hand table (`symbol, ex_date, ratio, raw_subject`), each ratio
   verified against the raw-close break (documented in the code comment), merged into
   `build_corporate_actions` as `type="split"`. Same audited-hand-patch pattern as `SYMBOL_ISIN_PATCH`
   — deliberately **not** a "snap any large gap to a split" heuristic, which would erase genuine
   crashes and defeat `max_ret_21`.

**Result of the rebuild** (`run(download=False, do_yf=False)`): adjustable events 743 → **854**;
`ohlcv.parquet` row/symbol counts unchanged (4,988,593 / 3,178); JSWSTEEL ex-date daily return
−90.1% → **−0.9%**, CADILAHC −79.5% → **+2.3%**. P3's `unadjusted_split` extreme count **7 → 0**.
**P1 re-run is bit-identical** (universe ranks on raw turnover). Full suite **93 passed**.

**Re-verified:** criterion 6 (yfinance corr > 0.99) re-run via `run(report_only=True)` —
**median 0.9963, 25/30 above 0.99**, identical to the original run. The fix did not regress it.

## 9. STOP

All 12 acceptance criteria pass (criterion 6 with a disclosed dividend/demerger caveat; median corr 0.9963 > 0.99). Survivorship bias verified absent (canaries + flat coverage + attrition audit above). **P1 has also been re-run against this panel and all its criteria pass** (`reports/p1_handoff.md`). **Do not start Phase 3.**

_(Superseded — Phase 3 has run, and P2 has since had the §10 parser fix. Kept for the record.)_
