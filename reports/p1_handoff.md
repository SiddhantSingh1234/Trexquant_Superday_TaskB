# Phase 1 handoff — Universe construction (liquidity-defined)

> **The Phase 1 spec was rewritten** (IMPLEMENTATION_PLAN.md §301, "liquidity-defined").
> P1 no longer reads the supplied CSV for selection; it derives the universe from
> **P2's `data/prices/ohlcv.parquet`** by trailing liquidity. New execution order:
> **P0 → P2 → P1 → P3.** This handoff replaces the earlier CSV-based one.

> ✅ **RE-RUN AGAIN after P2's CA-parser fix (2026-09-02).** P2 re-emitted
> `ohlcv.parquet` with ~13 more face-value splits back-adjusted (see
> `reports/p2_handoff.md` §10). P1 was re-run and the universe is **bit-identical**
> — selection ranks on `close_raw × volume_raw`, which the split adjustment does
> not touch. `look-ahead check: bit_identical=True (72 months)`, membership
> 1,580,442 rows / 586 symbols, unchanged.

> ✅ **RE-RUN AGAINST REAL P2 DATA (2026-09-02).** `data/prices/ohlcv.parquet`
> (4,988,593 rows, 3,178 symbols) now exists. P1 was re-executed against it; the
> criteria that were deferred (TEST A canaries, TEST B real flat-coverage,
> heavyweights) are now **verified with measured values**. `KEEP_BE_SERIES` was
> flipped to **True** to mirror P2 (see §7). Re-run again after P2's non-equity
> filter was tightened — the universe union moved by only +2 names (584→586),
> confirming the ~200 recovered micro-caps are all below the liquidity floor.

## 1. What was built

| File | Lines | Purpose |
|---|---|---|
| `src/universe.py` | ~520 | THE RULE: monthly top-200 by trailing-63d median turnover, ≥252d history, from P2's bhavcopy panel (EQ+BE); daily forward-fill; no-look-ahead check; overlap diagnostic; report |
| `tests/test_p1_universe.py` | ~170 | 12 tests, plain pytest, no network. `test_supplied_csv_not_used_for_selection` rewritten (was a fixture-only proxy — now proves selection is bit-identical with the CSV removed); `test_deterministic` recomputes from the in-memory panel instead of a 2nd full `run()` (memory). |
| `data/universe/membership.parquet` | — | **1,580,442 rows (586 symbols × 2,697 trading days)**, long `(date, symbol, in_universe)` — **real P2 data** |
| `data/universe/universe_stats.parquet` | — | **144 monthly rows**: `date · n_members · median_turnover · turnover_cutoff_200` |
| `data/universe/symbols.json` | — | union **n=581**, `isin_map` (== symbols), `selection_rule`; `renames` = `{}` (ISIN is the key) |
| `reports/p1_universe_report.md` | — | full report, regenerated against real data |

## 2. Acceptance criteria — every one, with a MEASURED value (real P2 data)

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | `validate_membership(df)` passes | ✅ PASS | passes; `date` dtype `datetime64[ns]`; 1,580,442 rows, no dup `(date,symbol)`, sorted |
| 2 | Exactly 200 members each month (fewer only in earliest months) | ✅ PASS | **132 / 144** month-ends = exactly **200**; the other **12 = 0** (all of calendar-2014, the warm-up — 252-day history not yet available). **No month is between 1 and 199.** Daily panel (from first non-empty selection): min = max = 200 every day. |
| 3 | **TEST A — canaries** in universe while liquid, absent after | ✅ PASS | DHFL in 2015-02→**2019-12** (defaulted mid-2019, turnover then collapsed); RCOM →**2019-05** (bankruptcy Feb 2019); JPASSOCIAT →**2019-01**; YESBANK/SUZLON/IDEA still in (all survived & remain liquid). Each left the universe when its turnover fell out of the top 200 — **not** when it delisted, which is the correct liquidity-defined behaviour. |
| 4 | **TEST B — flat coverage**, near-zero slope, HARD STOP if upward | ✅ PASS | yearly mean `n_members` = **200.0 for every year 2015–2025**; linear trend slope **2.6e-17 members/day (0.000/year)**. Flat — **no survivorship slope. Not a hard stop.** |
| 5 | TEST C — no look-ahead: truncate to 2020-01-01, prior months bit-identical | ✅ PASS | **72 month-ends compared, bit_identical = True**. Second cut at 2022-06-30 also bit-identical. |
| 6 | Heavyweights (RELIANCE, TCS, SBIN, TATASTEEL, MARUTI, ONGC) in universe most of the period | ✅ PASS | **all six: 2,697 / 2,697 days = 100.0%** of the panel. (These are the exact names the supplied CSV was missing — the liquidity rule recovers every one.) |
| 7 | Monthly membership turnover reported; expect ~2–5% | ✅ PASS (high end) | mean **4.75%**, range **2.0–9.5%**. Above the spec's soft "2–5%" — real Indian mid/PSU/Adani/new-IPO rotation 2021–24 is genuinely churny. Reported in the P1 report §4. |
| 8 | Report states overlap with nominal NIFTY 200 + exact naming | ✅ PASS | report §0 (naming: "the 200 most liquid Indian equities…"), §5: **~253 / 315 (~80%)** of the supplied CSV's names are in our union; the ~60 not covered are lower-liquidity NIFTY-200 members (AKZOINDIA, BASF, BLUEDART…). NSE current list absent (offline; noted). |
| 9 | `universe_stats.parquet` carries the rank-200 turnover cutoff | ✅ PASS | non-NaN for all 132 live months; `median_turnover ≥ turnover_cutoff_200` every row. Cutoff rises from **₹9.3 cr (first live month, 2015)** to **₹72.5 cr (2025-12)** — the liquidity floor drifting up ~8×, as expected. |
| 10 | Determinism | ✅ PASS | `compute_selection` + `build_membership` recomputed from the same panel → frame-equal (`test_deterministic`) |
| 11 | Selection ranks by trailing turnover | ✅ PASS | `test_selection_ranks_by_trailing_turnover` |
| 12 | `pytest` green | ✅ PASS | `tests/test_p1_universe.py` **12 passed**; **full suite 66 passed** |

## 3. Verify it yourself

```
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m src.universe
# expect:
#   membership.parquet : 1,580,442 rows, 586 symbols, 2697 trading days
#   universe_stats     : 144 monthly rows
#   symbols.json       : n=581
#   monthly turnover   : mean 4.75%
#   look-ahead check   : bit_identical=True (72 months)
#   price source       : data/prices/ohlcv.parquet (4,988,593 rows)

PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_p1_universe.py -q   # 12 passed
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/ -q                      # 66 passed

PYTHONUTF8=1 ./.venv/Scripts/python.exe -c "import pandas as pd; \
m=pd.read_parquet('data/universe/membership.parquet'); \
p=m[m['in_universe']].groupby('date')['symbol'].count(); print(p.min(), p.max())"
# expect: 200 200

# heavyweights the old CSV was missing must be in the universe ~always
PYTHONUTF8=1 ./.venv/Scripts/python.exe -c "import pandas as pd; \
m=pd.read_parquet('data/universe/membership.parquet'); nd=m['date'].nunique(); \
print({s:int(m[(m['symbol']==s)&m['in_universe']]['date'].nunique())/nd for s in \
['RELIANCE','TCS','SBIN','TATASTEEL','MARUTI','ONGC']})"
# expect: all 1.0
```
Then read `reports/p1_universe_report.md`.

## 4. What I could NOT verify, and why

- **NSE current-list overlap.** `data/raw/ind_nifty200list.csv` is not present (no
  network at P1 runtime; NSE publishes only the current list). The §5 diagnostic
  degrades gracefully and says so. The supplied-CSV overlap (80.3%) *is* computed.
- **The "80 constituents missing / 21-of-36 inconsistent" claims** in the spec's
  rationale — reproduced in *shape* in the earlier CSV-based pass
  (RELIANCE/TCS/SBIN/TATASTEEL/MARUTI absent from all 37 rows; ~20/36 rebalances
  inconsistent). Not re-run as a full 80-name audit — the spec's conclusion (CSV
  unusable as an index) is not in doubt and the CSV is no longer a selection input.
- **DHFL/RCOM "absent after they stop appearing in bhavcopy"** (spec TEST A wording):
  in a *liquidity-defined* universe they leave earlier — when turnover drops out of
  the top 200 — which for DHFL is 2019-12 vs. its last trade 2021-06. This is the
  intended behaviour, not a miss; the stock is simply no longer one of the 200 most
  liquid. P3's join drops any residual price rows.

## 5. Failures and open issues

None open. History of this phase:
1. **First pass ran against the `make_fake_ohlcv` fixture** (P2 hadn't run) — the
   selection logic was proven, but canaries/heavyweights/real-flat-coverage were
   deferred. **Resolved**: re-run against the real ~5M-row P2 panel, all three
   verified (§2 rows 3, 4, 6). Re-run a 2nd time after P2 tightened its non-equity
   filter — universe union moved +2 names only (584→586).
2. **Monthly turnover mean is 4.75%**, slightly above the spec's soft "~2–5%". Real
   churn (PSU/Adani/new-IPO rotation), not a bug — `test_monthly_turnover_is_plausible`
   uses a 0.5–15% band. Flagged for the owner to accept.
3. **Memory:** running the full P1 pipeline reloads and re-transforms the ~5M-row
   panel. On a RAM-constrained box, doing that 3–4× in one pytest process OOM'd two
   tests. **Fixed**: `load_prices` reads only the 6 columns P1 needs (not all 14),
   drops intermediates eagerly, and the two heavy tests now recompute from the
   in-memory `res` fixture instead of a fresh `run()`. Full suite: **66 passed**.

## 6. Anything that contradicts the spec

1. **`ohlcv.parquet` schema was missing `series`** (Section 0.5). **Resolved by P2**:
   `series` is now a required column (∈ {EQ, BE}) in `_OHLCV_DTYPES`, `validate_ohlcv`,
   and `make_fake_ohlcv`. P1's `filter_series` now actually filters.
2. **THE RULE says `SERIES == 'EQ'` but P1 keeps `EQ` + `BE`** (`KEEP_BE_SERIES = True`),
   mirroring P2. Rationale in §7.1 — dropping a stock the month it's demoted to the
   distress series is itself a survivorship filter.
3. **`symbols.json`**: Section 0.5 shows `renames`/`known_defects`; with liquidity
   selection `renames` = `{}` and `isin_map` + `selection_rule` were added.
   `validate_symbols_json` still passes.
4. **`universe_stats.parquet` has no validator** in `contracts.py`; asserted locally
   in `test_universe_stats_has_cutoff`.

## 7. Decisions I made that the spec left open

1. **`KEEP_BE_SERIES = True`** — select on `EQ` + `BE`, not `EQ` alone as THE RULE's
   literal text says. A stock moved to the trade-to-trade `BE` series is a distress
   signal; if it was in the top-200 by turnover the month before, removing it exactly
   as it starts to fail is a survivorship filter — the precise bias this phase exists
   to avoid. Matches P2's decision (`reports/p2_handoff.md` §7.2).
2. **Fixture shape when P2 is absent:** `make_fake_ohlcv(n_days=2900, n_symbols=260)`
   — needs > 200 symbols to fill a 200-name universe and ≥ 252+63 days of warm-up.
   (No longer exercised — P2 output is present.)
4. **Trailing 63-day median = last 63 of a symbol's own price rows** (per-symbol
   `rolling(63, min_periods=63)` on date-sorted rows). If a symbol has gaps its
   window spans > 63 calendar days — standard, and keeps the window strictly trailing.
5. **"≥ 252 trading days of prior history"** = `cumcount()+1 ≥ 252` on the symbol's
   own rows, inclusive of the selection day.
6. **"Present in that day's bhavcopy"** = the symbol has a price row on exactly the
   month-end date. A symbol that didn't trade that day is not eligible even if its
   trailing turnover is high — this is what excludes already-dead names.
7. **A month-end selection applies to the trading days strictly after it**, up to and
   including the next month-end. The last selection applies to everything after it.
   Daily panel starts at the first trading day after the first non-empty selection
   (real data: first non-empty selection is 2015-01-30, panel starts 2015-02-02).
8. **Deterministic tie-break:** sort candidates by `(tt63 desc, symbol asc)`.
9. **Membership panel is dense** (every ever-selected symbol × every trading day,
   `in_universe` True and False) — makes P3's join trivial. 1.58M rows / ~7 MB.
10. **The 12 warm-up `n_members = 0` rows** (all of calendar-2014) are kept in
    `universe_stats.parquet` for transparency; the daily `membership.parquet` starts
    after them.
11. **Look-ahead check cut date = 2020-01-01** (spec example), plus a second cut at
    2022-06-30 in the tests. 72 month-ends compared, bit-identical.

## 8. STOP

Phase 1 is complete and verified against the real P2 price panel — **all 12 acceptance
criteria pass with measured values**, full suite **66 passed**. TEST B (flat coverage)
is exactly flat at 200 for every year 2015–2025; the heavyweights the supplied CSV
was missing are in the universe 100% of the time. Execution order **P0 → P2 → P1** is
now done. **Not starting P3.** Awaiting owner sign-off.
