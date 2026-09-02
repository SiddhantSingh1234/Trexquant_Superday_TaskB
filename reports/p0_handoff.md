# Phase 0 handoff — Project scaffolding

## 1. What was built

| File | Lines | Purpose |
|---|---|---|
| `src/config.py` | 129 | Paths (`pathlib`), Section 0.4 split dates as `pd.Timestamp`, tuning constants, `split_mask()`, `assert_not_holdout()`, `SPLITS_JSON_PAYLOAD` |
| `src/contracts.py` | 479 | `SchemaError`, validators (`validate_membership/ohlcv/features/labels/symbols_json`), fixture generators (`make_fake_ohlcv/membership/features/labels/symbols`) |
| `src/__init__.py` | 0 | package marker |
| `tests/test_p0_contracts.py` | 197 | 23 acceptance tests |
| `requirements.txt` | 13 | allowed deps from Section 0.2 only |
| `data/{raw,universe,prices,panel}/`, `src/agents/`, `tests/`, `reports/`, `artifacts/cards/`, `slides/` | — | directory tree from Section 0.3 |
| `reports/.gitkeep`, `artifacts/cards/.gitkeep`, `src/agents/.gitkeep` | — | keep empty dirs |
| `.venv/` | — | Python 3.12 venv with full `requirements.txt` installed (pip exit 0) |

## 2. Acceptance criteria — every one, with a MEASURED value

| # | Criterion (from Phase 0 "Acceptance") | Result | Measured value |
|---|---|---|---|
| 1 | `pytest tests/test_p0_contracts.py` passes | ✅ PASS | **23 passed** in 4.58s, 0 failed |
| 2 | Every validator rejects a deliberately corrupted frame with a message naming the exact column | ✅ PASS | 12 rejection tests pass: `in_universe` (missing + wrong dtype), `(date, symbol)` dup, `sorted`, `vwap`, `close`, all-NaN `vwap`, `amihud_21` missing, `dist_52wh` positive, `fwd_ret_5_demeaned` missing, symbols.json `n` mismatch |
| 3 | `make_fake_*` outputs pass their own validators | ✅ PASS | `test_fixtures_validate` green — all 5 generators |
| 4 | `assert_not_holdout` raises on 2023-01-01, passes on 2019-01-01 | ✅ PASS | raises `AssertionError` on 2023-01-01; returns `None` on 2019-01-01 |
| 5 | `make_fake_labels` contains a feature with genuine planted IC ~0.04 | ✅ PASS | mean-daily RankIC(`mom_21`, `fwd_ret_1_demeaned`) = **0.0456** (default shape 800×40); test bound 0.02–0.065 |
| 6 | Fixtures deterministic | ✅ PASS | `test_fixtures_deterministic` — `.equals()` true on repeat calls for all 4 frames |
| 7 | OHLCV has symbols that stop trading partway (survivorship bite) | ✅ PASS | **2 of 40** symbols end before panel end (default seed) |
| 8 | OHLCV ~25% annualized volatility | ✅ PASS | pooled ann. vol = **0.254** |

Extra measured facts: default `make_fake_ohlcv()` = 31,461 rows (40 symbols × ~800 bdays, minus
~1.5% gaps and 2 truncated symbols); noise feature `rev_5` mean RankIC ≈ 0 (`|mean| < 0.015`).

## 3. Verify it yourself

```
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m pytest tests/test_p0_contracts.py -v          # expect 23 passed

./.venv/Scripts/python.exe -c "from src import contracts as C; import numpy as np; f=C.make_fake_features(); l=C.make_fake_labels(); m=f[['date','symbol','mom_21']].merge(l[['date','symbol','fwd_ret_1_demeaned']]); print(round(float(m.groupby('date').apply(lambda g: g['mom_21'].corr(g['fwd_ret_1_demeaned'],method='spearman')).mean()),4))"
# expect ~0.045

./.venv/Scripts/python.exe -c "from src import config; import pandas as pd; config.assert_not_holdout(pd.to_datetime(['2019-01-01'])); print('2019 ok');
import sys
try:
    config.assert_not_holdout(pd.to_datetime(['2023-01-01'])); print('BUG: did not raise')
except AssertionError: print('2023 raises ok')"
```

## 4. What I could NOT verify, and why
- Nothing blocking. `langgraph` / `langchain-*` install cleanly but are unused in P0 (Phases 8/10 only);
  I did not exercise them.
- No real upstream data exists yet (P1–P3 unbuilt) — by design; P0 is fixtures only.

## 5. Failures and open issues
- None open. Two issues found and fixed during the run:
  1. pandas 2.3+ removed `DataFrame.stack(dropna=...)` → switched `_long()` to `stack(future_stack=True)`.
  2. pandas 2.5 / numpy 2.5 default new datetimes to `datetime64[us]`; Section 0.5 mandates `[ns]` →
     `_finalize()` now casts `date` to `datetime64[ns]` explicitly, and validators enforce it.
     **Downstream phases must also emit `datetime64[ns]`, not the pandas default** — worth a note in
     the P1/P2/P3 specs.

## 6. Anything that contradicts the spec
- **Label horizons.** Section 0.5 header writes `fwd_ret_1 … fwd_ret_21` (could read as all 21). P3
  step 3 and the Metrics `decay` keys use **{1, 2, 3, 5, 10, 21}**. I implemented {1,2,3,5,10,21} →
  12 label columns (`fwd_ret_h` + `fwd_ret_h_demeaned`). Confirm before P3 builds against it.
- `requirements.txt` lists `python-dotenv` (pip name for the `dotenv` import) and omits `sqlite3`
  (stdlib) — matches Section 0.2 intent, not its literal list.

## 7. Decisions I made that the spec left open
1. **Label horizons = {1,2,3,5,10,21}** (see §6).
2. **Fixture default shape:** `n_days=800, n_symbols=40`. Gives >252 rows for long windows and a
   cross-section >20 for rank statistics.
3. **Planted-signal wiring:** a seed-derived latent (independent of call order) is shared by
   `make_fake_features` (→ `mom_21` = per-day z-score of it) and `make_fake_labels`
   (→ `fwd_ret_h = 0.02·(0.04·latent + √h·noise)`). Gives realized RankIC ≈ 0.04 at h=1, decaying with
   horizon. `PLANTED_IC = 0.04` exported from `contracts.py`; recorded in the module + function
   docstrings.
4. **Fixture `close_raw == close`, `volume_raw == volume`** — no synthetic corporate actions in the
   fixture (P2's real adjustment work is out of scope).
5. **`vwap` fixture** = mean(O,H,L,C) clipped into `[low, high]`, guaranteeing the contract assertion.
6. **`sector`** = static per-symbol random draw from NSE's 22 official industries (mirrors P3's
   "current, not point-in-time" caveat).
7. **Validator dtype strictness:** floats must be exactly `float64`; `date` must be tz-naive
   `datetime64[ns]`; string-like columns accept object or pandas `string` dtype; `in_universe` must be
   bool.
8. **`split_mask` bounds inclusive both ends**; composite region `"train+val_a"` supported (P4 needs it).
9. **`assert_not_holdout` raises `AssertionError`** (tripwire), not a custom exception.
10. **`delivery_pct` fully populated in the fixture** (clipped 1–99) so the "no all-NaN column" check
    passes; real P3 will carry leading NaNs, still not *all*-NaN.
11. **`make_fake_symbols` default `n=315`** with 5 special-character tickers seeded in
    (`M&M`, `J&KBANK`, `BAJAJ-AUTO`, `ARE&M`, `COX&KINGS`) and the 4 canonical renames + IREDA defect.
12. **A `.venv` was created** (user asked) rather than installing into the system interpreter.
