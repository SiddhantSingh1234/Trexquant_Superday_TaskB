# Phase 5 handoff — Operator library and AST tools

> Status: **READY FOR REVIEW.** Do not start Phase 6.
> Execution order so far: **P0 → P2 → P1 → P3 → P4 → P5**.
> P5 is pure tooling — no data written, no LLM, no backtest. It builds the safe
> formula toolbox (`src/operators.py`), the parser / tree analysis
> (`src/ast_tools.py`), and the reference alpha zoo (`src/zoo.py`) that P6's
> novelty check compares against.

## 1. What was built

| File | Lines | Purpose |
|---|---|---|
| `src/operators.py` | 420 | 35 operators on wide `date × symbol` frames: 5 cross-sectional (`rank, scale, zscore_cs, demean_cs, sector_neutral`), 13 strictly-trailing time-series (`delay, delta, ts_mean, ts_std, ts_min, ts_max, ts_rank, ts_sum, ts_argmax, ts_product, decay_linear, correlation, covariance`), 17 element-wise (`add, sub, mul, div, pow, log, abs, sign, min, max, signed_power, if_else, lt, gt, le, ge, eq`). `div`/`log`/`pow` guard against zero / negatives → NaN, never raise. Registry: `OPERATORS`, plus `TIME_SERIES_OPS`, `COMMUTATIVE_OPS`, `SYMMETRIC_HEAD_OPS`, `ARITH_OPS`, `FIELDS`. |
| `src/ast_tools.py` | 305 | `parse` (Python `ast`, strict whitelist), `evaluate`, `canonical`, `complexity`, `fingerprint`. `ParseError` / `EvalError`. Internal `Node` = nested tuple. |
| `src/zoo.py` | 255 | `ZOO` — 35 formulas (25 Alpha101 + 10 classical), each `{name, formula, canonical, fingerprint, source}`; `ZOO_BY_NAME`; `SKIPPED_ALPHA101` (discloses #56); `is_zoo_duplicate(formula, threshold)`; `demo_panel()` (dense synthetic `{field: date×symbol}` dict for tests/demo). |
| `tests/test_p5_operators.py` | 320 | 42 tests, plain `pytest`, no network. |

`src/config.py`, `src/contracts.py`, and every earlier phase's files are **unchanged**.

## 2. Acceptance criteria — every one, with a MEASURED value

Environment: Python 3.12.6, pandas 3.0.5, numpy 2.5.2. Command:
`./.venv/Scripts/python.exe -m pytest tests/test_p5_operators.py -q` → **42 passed** (~5 s).

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | Every operator has a unit test on a hand-computed 5×3 panel | ✅ PASS | All 35 operators asserted with hand values on the fixture `P` (`A=[1,2,3,4,5]`, `B=[5,4,3,2,1]`, `C=[2,2,2,2,2]`). e.g. `ts_mean(P,2).iloc[1] = [1.5, 4.5, 2.0]`; `ts_argmax(P,3).iloc[2] = [0, 2, 2]`; `decay_linear(P,2).iloc[1] = [5/3, 13/3, 2]`; `sector_neutral(P,{A:x,B:x,C:y}).iloc[0] = [-2, 2, 0]`. Tests: `test_cross_sectional_operators`, `test_sector_neutral`, `test_time_series_operators_hand_values`, `test_correlation_and_covariance`, `test_elementwise_operators`, `test_div_and_log_guards`, `test_comparisons_and_if_else`. |
| 2 | **Causality (mandatory):** for every time-series operator, changing a future input value must not change any earlier output | ✅ PASS | `test_time_series_operators_are_causal` — parametrized over all **13** TS operators. For each: perturb input row `p ∈ {12, 25, last}` to `[-1e6, 1e6, …]`; assert `output.iloc[:p]` **bit-identical** (`pd.testing.assert_frame_equal`) to the unperturbed run. Plus a non-vacuity guard (perturbing a mid row *does* change some later output). `test_every_time_series_operator_has_a_causality_case` asserts `set(TS_CALLS) == O.TIME_SERIES_OPS` so none can be silently skipped. |
| 3 | `if_else` and `ts_product` pass the causality test | ✅ PASS | Covered by #2 (`ts_product` ∈ `TIME_SERIES_OPS`) and explicitly by `test_if_else_and_ts_product_are_causal`: perturb input row 20, `output.iloc[:20]` unchanged for both. |
| 4 | `rank` produces values in `[0,1]` with no NaN where input is non-NaN | ✅ PASS | `test_rank_range_and_nan_preservation`: `rank(x)` (40×4 panel, one NaN injected) — all non-NaN outputs in `[1/n, 1]` ⊂ `[0,1]`; NaN input → NaN output; `notna` count preserved exactly (159 == 159). |
| 5 | Parser rejects `__import__('os')`, `close.values`, `[x for x in y]`, `lambda x: x` | ✅ PASS | `test_parser_rejects_unsafe_syntax` — all 4 raise `ParseError`, plus `close[0]` (Subscript), `rank(close); import os` (SyntaxError→ParseError), `f'{close}'` (JoinedStr). `__import__('os')` is rejected twice over: unknown operator *and* string constant. |
| 6 | `canonical("a*b") == canonical("b*a")` | ✅ PASS | `test_canonical_sorts_commutative_and_folds_constants`: equal; also `canonical("mul(2,3)") == "6"` (constant fold), `canonical("add(mul(2,3),close)") == canonical("add(close,6)")`, `canonical("correlation(volume,close,10)") == canonical("correlation(close,volume,10)")` (symmetric head), and `canonical("sub(a,b)") != canonical("sub(b,a)")` (non-commutative not reordered). |
| 7 | `complexity` returns the correct node count on a hand-drawn tree | ✅ PASS | `complexity("mul(rank(close), delta(volume, 5))") == {"nodes": 6, "depth": 3, "free_params": 1}` (mul + rank + close + delta + volume + `5`). `complexity("ts_mean(add(close, 1.5), 20)")["free_params"] == 2` (window sizes count as knobs). |
| 8 | All ~35 zoo formulas parse, evaluate, and produce finite values on the fake panel | ✅ PASS | `test_every_zoo_formula_parses_evaluates_and_is_finite` — 35/35 strict-parse, evaluate on `demo_panel()` (1000 days × 25 symbols), finite-cell count per formula **13,193 – 24,999** (min is Alpha #3, a corr of two ranks; all > 0). Also asserts stored `canonical`/`fingerprint` match a fresh recompute. |
| 9 | `is_zoo_duplicate` → `True` for a zoo formula with operands commuted, `False` for a genuinely different formula using the same fields | ✅ PASS | `test_is_zoo_duplicate_detects_commuted_operands`: `mul(correlation(rank(volume), rank(open), 10), -1)` → `(True, "alpha101_003")`. `test_is_zoo_duplicate_false_for_a_different_formula_same_fields`: `rank(sub(open, ts_mean(volume, 10)))` → `(False, None)`; `mul(-1, correlation(rank(open), rank(volume), 5))` (only the window differs) → `(False, …)`. `test_is_zoo_duplicate_exact_match`: every one of the 35 entries matches itself. |
| 10 | Zoo is REQUIRED (`src/zoo.py`), ~35 formulas = 25 Alpha101 + 10 classical | ✅ PASS | `test_zoo_size_and_composition`: `len(ZOO) == 35`, 25 tagged `Kakushadze 2016`, 10 tagged `classical`. |
| 11 | Skip Alpha #56 and disclose | ✅ PASS | `SKIPPED_ALPHA101 == {"alpha101_056": "requires true market capitalisation (cap); size_proxy is a trailing-turnover proxy, not shares × price"}`; asserted absent from `ZOO`. |
| 12 | Determinism — same input → same output | ✅ PASS | `test_operators_are_deterministic`: `evaluate(alpha101_003, panel)` twice → `assert_frame_equal`. No RNG in `operators.py` / `ast_tools.py`; `numpy`/`random` seeded at import per §0.6. |

### Full-suite regression

`./.venv/Scripts/python.exe -m pytest tests/ -q` → **158 passed** (was 116 after P4; +42 P5).

## 3. Verify it yourself

```powershell
# P5 only — fast, no network
./.venv/Scripts/python.exe -m pytest tests/test_p5_operators.py -q          # expect: 42 passed (~5s)

# whole suite
./.venv/Scripts/python.exe -m pytest tests/ -q                              # expect: 158 passed

# zoo smoke — prints all 35 formulas, their finite-cell counts and fingerprints
./.venv/Scripts/python.exe -m src.zoo
```

```python
# one-liners the owner can paste
from src import operators as O, zoo as Z
from src.ast_tools import parse, canonical, complexity, fingerprint, evaluate

# causality, by hand: change tomorrow, yesterday's value must not move
import numpy as np, pandas as pd
x = pd.DataFrame(np.arange(20.0).reshape(10, 2), index=pd.bdate_range("2020-01-01", periods=10))
a = O.ts_mean(x, 3)
x2 = x.copy(); x2.iloc[-1] = 999
print((a.iloc[:-1] == O.ts_mean(x2, 3).iloc[:-1]).all().all())     # True

# whitelist
for bad in ["__import__('os')", "close.values", "[x for x in y]", "lambda x: x"]:
    try: parse(bad); print("LEAK", bad)
    except Exception as e: print("blocked:", type(e).__name__)

# duplicate detection
print(Z.is_zoo_duplicate("mul(correlation(rank(volume), rank(open), 10), -1)"))  # (True, 'alpha101_003')
print(Z.is_zoo_duplicate("rank(sub(close, vwap))"))                              # (False, None)
```

## 4. What I could NOT verify, and why

- **The 25 Alpha101 transcriptions are not checked cell-by-cell against a
  reference implementation of Alpha101** (there is no licensed one in the repo,
  and none is an allowed dependency). They are verified to (a) parse under the
  strict grammar, (b) evaluate to finite values, (c) match the published
  *structure* (operators, fields, windows) from Kakushadze 2016. For the zoo's
  job — a structural-novelty reference set — structure is what matters, not
  numerical fidelity. If a transcription has a bug it makes the duplicate check
  *slightly less* effective, never wrong in a way that leaks.
- **Fidelity audit (done by hand against Kakushadze 2016, arXiv:1601.00991):**
  24 of the 25 are faithful operator-for-operator transcriptions —
  #1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 16, 18, 19, 20, 22, 26, 33, 34, 35,
  38, 40, 44. **#29 was initially over-simplified and has been corrected** to the
  full published form
  `min(product(rank(rank(scale(log(sum(ts_min(rank(rank(-1*rank(delta(close-1,5)))),2),1)))))‚1),5) + ts_rank(delay(-1*returns,6),5)`.
  Two documented semantic choices where Alpha101 implementations differ:
  `ts_argmax` returns days-since-max (§7.2), and `correlation`/`covariance` are
  sample (ddof=1) statistics (§7.6). These shift *values*, not structure, and
  only #1/#26 (argmax) and #2/#3/#5/#6/#13/#14/#16/#18/#22/#26/#40/#44 (corr/cov)
  touch them.
- **`sector_neutral` on real point-in-time sector data** — tested only on a
  synthetic 3-symbol / 2-sector panel. The real `sector` column (P3) is static,
  not point-in-time (already disclosed by P3); this operator inherits that.
- **`is_zoo_duplicate` threshold tuning.** Default `threshold=1.0` (exact
  canonical match only). The fuzzy path (`SequenceMatcher` ratio ≥ threshold on
  canonical strings, gated by matching fingerprint) is implemented and unit-safe
  but **its calibration is P6's call** — P6 owns the novelty gate and should pick
  the threshold against its own corpus.

## 5. Failures and open issues

None open. 42/42 P5 tests pass; full suite 158 passed.

## 6. Anything that contradicts the spec

1. **The spec says the whitelist is "`Call`, `Name`, `Constant`, `BinOp` only".
   The parser also allows a unary `-`/`+` applied *directly to a numeric
   literal*** (`ast.UnaryOp` with a `Constant` operand), folded immediately to a
   signed constant. Without this, `-1 * rank(x)` — which appears in a large
   fraction of Alpha101 — is inexpressible, since Python parses `-1` as
   `UnaryOp(USub, Constant(1))`. Unary operators on *expressions* (`-rank(x)`)
   are still rejected; the zoo writes `mul(-1, rank(x))`. This is strictly
   narrower than "allow UnaryOp" and does not widen the safety surface (a signed
   number literal can do nothing an unsigned one can't).
2. **Comparison operators `lt, gt, le, ge, eq` are in the library but not in the
   spec's operator list.** The spec mandates `if_else(cond, a, b)` and says it
   "unlocks ~11 Alpha101 formulas, all of which are conditional" — but every one
   of those conditions is a comparison (`returns < 0`, `adv20 < volume`,
   `0 < ts_min(...)`, …), and the spec's element-wise list has no way to produce
   a boolean `cond`. So the comparisons are a necessary consequence of the
   `if_else` requirement. They are element-wise and trivially causal. `if_else`
   also accepts a plain numeric `cond` (truthy where `> 0`) as a fallback.
3. **`div`/`covariance` etc. — the spec lists `covariance(x,y,d)` and
   `correlation(x,y,d)`; both are implemented via `pandas.rolling().cov/.corr`,
   which is sample (ddof=1) covariance.** Noted, not a contradiction — just a
   convention choice the spec left open (see §7).
4. **Nothing else.** All operator names, the zoo size (25+10), the #56 skip, the
   `if_else`/`ts_product` additions, and the strict-whitelist rejection cases
   match the spec exactly.

## 7. Decisions I made that the spec left open

1. **Time-series `min_periods == window`.** Every `ts_*` operator emits NaN until
   it has a full `d` observations (standard Alpha101 semantics). Consequence: on
   a *gappy* panel a long window can be all-NaN. `demo_panel()` therefore
   **densifies** — forward-fills interior gaps within symbol, drops symbols with
   < 300 observations — so the long windows in Alpha #8/#19/#29 resolve. On the
   real (near-dense) P2 panel this is a non-issue for the windows actually used.
2. **`ts_argmax` returns "trading days since the trailing-window maximum"**
   (`0` = today is the max, up to `d-1`). Alpha101's convention varies by
   implementation; this one is monotone and bounded. `ts_argmin` was **not**
   added (not in the spec list, not needed by the confirmed-expressible set).
3. **`ts_rank(x,d)` = fraction of the trailing `d`-window ≤ today's value**,
   i.e. in `(0, 1]`. `rank(x)` (cross-sectional) uses `pct=True` → also `(0, 1]`.
4. **`decay_linear` weights are `1, 2, …, d`** (most recent day weight `d`),
   normalized by the sum of weights over the non-NaN entries in the window.
5. **`scale(x, a=1.0)`** rescales each *day* so `Σ|x| == a` (Alpha101 `scale`);
   `a` is an optional 2nd arg.
6. **`correlation`/`covariance` are sample statistics** (pandas `.corr`/`.cov`,
   ddof=1), column-wise (each symbol's own trailing series), NaN until `d` pairs.
7. **`pow` with a negative base and a non-integer exponent → NaN** (numpy
   semantics, warning suppressed). Integer exponents on negative bases are fine
   (`pow(sub(low, close), 2)`).
8. **Canonicalization:** commutative set = `{add, mul, min, max, eq}` (operands
   sorted by their emitted canonical string); `correlation`/`covariance` sort
   only their first two args (the window stays last); constant arithmetic folded
   for `{add, sub, mul, div, pow}` (div-by-0 and negative-base-fractional-pow are
   left unfolded); numeric literals normalized (`6.0 → "6"`, `0.5 → "0.5"`).
9. **`complexity.nodes` counts every leaf and every operator node**; a bare field
   is `depth 1`; **`free_params` counts every numeric literal, window sizes
   included** — they are overfitting knobs per the spec's own wording.
10. **`fingerprint`** = first 16 hex chars of `sha1(repr((sorted_op_multiset,
    depth, sorted_leaf_fields)))`. Stable across runs; different fingerprint ⇒
    provably not a duplicate.
11. **`is_zoo_duplicate` default `threshold=1.0`** (exact canonical match). The
    `< 1.0` fuzzy path exists for P6 to tune (see §4).
12. **`FIELDS`** = `{open, high, low, close, volume, vwap, returns, n_trades,
    delivery_pct, size_proxy, sector, close_raw, volume_raw}` — the P2/P3 fields
    plus `returns` (adjusted-close pct-change; the Coder agent / zoo derive it).
    `adv{d}` is **not** a field — it is the documented idiom
    `ts_mean(mul(volume, close), d)`, inlined in the zoo.
13. **The 25 Alpha101 chosen:** #1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 16, 18,
    19, 20, 22, 26, 29, 33, 34, 35, 38, 40, 44 (from the T5 confirmed-expressible
    set; #1, 7, 9 exercise `if_else`+comparisons, #29 exercises `ts_product`).
    Hand-audited against Kakushadze 2016 — see §4. `adv20` inlined as
    `ts_mean(mul(volume, close), 20)`.
    The 10 classical: 12-1 momentum, short-term reversal, low-volatility,
    illiquidity (Amihud), lottery, 52-week-high proximity, turnover, beta
    (via `correlation(returns, market, 63)` where `market = returns −
    demean_cs(returns)`), size (`−size_proxy`), volume-shock.

## 8. STOP

`src/operators.py`, `src/ast_tools.py`, `src/zoo.py`, `tests/test_p5_operators.py`
built to the Phase 5 spec. Every time-series operator is proven causal by a
bit-identical-earlier-output test. The parser rejects imports, attribute access,
subscripts, comprehensions, lambdas, and string constants. The zoo has 35
formulas; #56 is skipped and disclosed. 12/12 acceptance criteria pass with
measured values; full suite 158 passed.

**Not starting Phase 6.** Awaiting sign-off.
