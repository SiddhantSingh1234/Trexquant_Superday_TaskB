# Phase 7 handoff — Memory stores

> Status: **READY FOR REVIEW.** Do not start Phase 8.
> P7: 20/20 tests. Full suite P0–P7: 208 passed, no regressions.
> Execution order so far: **P0 → P2 → P1 → P3 → P4 → P5 → P6 → P7**.
> P7 is the six persistent stores that let the system improve across
> generations, with two guards against *second-order overfitting* (overfitting
> the search process itself): a confidence gate + sticky asymmetric veto on
> lessons, and an exploration floor on the bandit.
>
> **Design-doc updates:** the decisions in §7 are recorded for the deck in
> `IMPLEMENTATION_PLAN.md` Phase 7 (**P7-UPDATE** callout) and
> `PLAN_EXPLAINED.md` (**Cluster J — J27–J29**, "pull straight into the slides").
>
> **A self-review pass after the first draft changed three things** (all in §7):
> the veto no longer erodes on later successes (it was — a single good run could
> wipe out three failures); it now needs **two** confident failures, not one, so
> a fluke cannot block; and `confidence` was reframed so a reliably-*harmful*
> motif reads as high-confidence, not low. Also: the card validator was moved to
> `contracts.py` where the spec's other artifact validators live.

---

## 1. What was built

| File | Lines | Purpose |
|---|---|---|
| `src/memory.py` | 992 | The six stores + a `Memory` facade. `FormulaIndex` (exact + fingerprint dedupe), `LessonStore` (confidence gate + sticky asymmetric veto + `clear_veto`/`force_veto`), `BanditState` (softmax allocation, 5% exploration floor), `AlphaCardStore` (JSON-per-card + SQLite index), lineage tree (`lineage_path`, `children`), `AcceptedBook` (`data/book.parquet`). `new_card` builder, `formula_hash` (canonicalises first), `init_memory`. Re-exports `validate_card` / `make_fake_card` / `CardSchemaError` from `contracts`. |
| `tests/test_p7_memory.py` | 392 | 20 tests, plain `pytest`, no network. |
| `src/config.py` | +8 | Added `MEMORY_DB`, `LESSONS_DB`, `BANDIT_STATE_JSON`, `BOOK_PARQUET` (mirrors the existing `LEDGER_DB` line). Nothing else. |
| `src/contracts.py` | +115 | **P0 file modified** — added the AlphaCard contract that Section 0.5 specifies but P0 never built: `validate_card`, `make_fake_card`, `CardSchemaError` (subclass of P0's `SchemaError`), `CARD_VERDICTS`, and the key-set constants. No change to any existing validator or fixture. See §6. |
| `data/memory.db` | 45 KB | Exact stores — empty schema: `formulas`, `card_index`, `lineage`. Regenerate: `python -m src.memory`. |
| `data/lessons.db` | 24 KB | Semantic store — **physically separate file** from `memory.db` (spec: "keep exact and semantic stores physically separate"). Table `lessons`. |
| `data/bandit_state.json` | 1.8 KB | Seeded with the 10 idea-families, each `n_pulls=0`; records `exploration_floor: 0.05`. |
| `artifacts/cards/` | — | Directory exists (P0 `.gitkeep`); cards land here as `<card_id>.json`. |

`src/ledger.py` (P6's trial ledger — the exact multiple-testing count) is
**imported, never modified**.

### The six stores and where each lives

| # | Store | Backing | Access pattern |
|---|---|---|---|
| ① | Formula index | `memory.db` / `formulas` | exact hash lookup + fingerprint bucket |
| ② | Lesson / edit-motif | **`lessons.db`** / `lessons` | fuzzy: family + keyword filter |
| ③ | Bandit state | `bandit_state.json` | whole-file read/rewrite, ~10 rows |
| ④ | Alpha-card store | `memory.db` / `card_index` + `artifacts/cards/*.json` | filter by verdict/thesis; human-readable JSON |
| ⑤ | Lineage | `memory.db` / `lineage` | parent-pointer walk to root |
| ⑥ | Accepted book | `book.parquet` | full-panel numeric read for orthogonalisation |
| (P6) | Trial ledger | `ledger.db` | exact, append-only, no DELETE — **owned by P6** |

---

## 2. Acceptance criteria — every one, with a MEASURED value

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | All stores survive a process restart | ✅ PASS | `test_all_stores_survive_restart`: a fresh `Memory(base_dir=…)` on the same files recovers the formula (`seen_exact` True), the veto (`is_vetoed('shorten_window','momentum')` True), 1 applicable liquidity prior, 10 bandit families with `momentum.n_pulls==1`, lineage `['c_persist','c_persist2']`, `book.factors()==['c_persist']`. |
| 2 | Lesson with `n_observations=1` is **not** an applicable prior; at 3 it is | ✅ PASS | `test_lesson_confidence_gate`: `applicable_priors(family='liquidity')` → `[]` at n=1 and n=2; length **1** at n=3, `n_observations >= 3`. `LESSON_CONFIDENCE_GATE = 3`. |
| 3 | A vetoed motif is excluded from retrieval in its context, not in another | ✅ PASS | `test_asymmetric_veto_is_context_scoped`: after 3 failures at conf 0.9 in `momentum`, `is_vetoed(...,'momentum')` True and `shorten_window` absent from `applicable_priors(family='momentum')` (present with `include_vetoed=True`); after 3 successes in `reversal`, not vetoed there and **is** returned for `reversal`. |
| 4 | Bandit never allocates 0% to any family, even after 50 simulated failures | ✅ PASS | `test_bandit_exploration_floor_after_50_failures`: 50× `update('momentum', reward=-1.0)` → `allocation()` min share **0.05741**, `momentum` **0.05741**, sum **1.0** (10 families). After one `reversal` win: `reversal` **0.5498**, `momentum` floored at **0.05000**. `EXPLORATION_FLOOR = 0.05`. |
| 5 | `lineage_path` reconstructs a 4-generation chain correctly | ✅ PASS | `test_lineage_path_reconstructs_four_generations`: `lineage_path('c_gen3')` → `['c_gen0','c_gen1','c_gen2','c_gen3']` (root→leaf); `children('c_gen1') == ['c_gen2']`. |
| 6 | Cards round-trip to JSON without loss and validate against Section 0.5 | ✅ PASS | `test_card_roundtrips_and_validates`: `json.dumps(loaded, sort_keys=True) == json.dumps(card, sort_keys=True)`; `validate_card` passes; index row `rank_ic≈0.031`, `marginal_ic≈0.021`, `generation==2`. `test_validate_card_rejects_missing_key`: deleting `pre_registered.hash` raises `CardSchemaError`. `make_fake_card()` (the new P0 fixture) is schema-valid. |

**Extra guard tests (not required, added for the §7 decisions):**

| Check | Result | Measured value |
|---|---|---|
| Sticky veto survives 10 later successes | ✅ PASS | `test_veto_is_sticky_under_later_successes`: still vetoed after 10× `helped=True, confidence=1.0`; `clear_veto` lifts it and it stays lifted through a further confident failure. |
| Lone confident failure does **not** veto | ✅ PASS | `test_lone_confident_failure_does_not_veto`: 3 successes + 1 failure@0.95 → not vetoed; a 2nd failure@0.9 → vetoed. |
| `confidence` = reliability regardless of direction | ✅ PASS | `test_confidence_is_high_for_a_reliably_harmful_motif`: 5 failures@0.9 → `p_helps < 0.15`, `confidence > 0.6`. Symmetric for 5 successes. |
| `force_veto` bypasses the count, stays context-scoped | ✅ PASS | `test_force_veto`. |
| `M.validate_card is contracts.validate_card` | ✅ PASS | `test_validate_card_is_the_contracts_one`. |

**P7 test suite:** `20 passed in 5.31s` (`.venv/Scripts/python.exe -m pytest tests/test_p7_memory.py`).

**Full suite (P0–P7):** `208 passed in 281.39s` — no regressions
(`.venv/Scripts/python.exe -m pytest -q`). Prior run was `203 passed`; the delta
is exactly P7's own test count (15 → 20). The `contracts.py` addition broke
nothing in P0/P3/P4/P6.

---

## 3. Verify it yourself

```
# P7 tests — expect "20 passed"
.venv/Scripts/python.exe -m pytest tests/test_p7_memory.py -v

# full suite — expect all green (P0-P7); ~5 min (P2/P3 read real parquet)
.venv/Scripts/python.exe -m pytest -q

# (re)create the on-disk deliverables — idempotent
.venv/Scripts/python.exe -m src.memory
#   -> data/memory.db, data/lessons.db, data/bandit_state.json, artifacts/cards/

# exploration floor holds under sustained failure
.venv/Scripts/python.exe -c "
from src.memory import Memory, FAMILIES
import tempfile; m=Memory(base_dir=tempfile.mkdtemp())
[m.bandit.register_family(f) for f in FAMILIES]
[m.bandit.update('momentum', reward=-1.0) for _ in range(50)]
a=m.bandit.allocation(); print(round(min(a.values()),5), round(sum(a.values()),9))"
#   -> 0.05741 1.0

# veto needs TWO confident failures, and then it is sticky
.venv/Scripts/python.exe -c "
from src.memory import Memory
import tempfile; m=Memory(base_dir=tempfile.mkdtemp()); L=m.lessons
for _ in range(3): L.observe('w', helped=True, confidence=0.9, family='x')
L.observe('w', helped=False, confidence=0.9, family='x'); print('1 fail:', L.is_vetoed('w', family='x'))
L.observe('w', helped=False, confidence=0.9, family='x'); print('2 fail:', L.is_vetoed('w', family='x'))
for _ in range(10): L.observe('w', helped=True, confidence=1.0, family='x')
print('after 10 wins:', L.is_vetoed('w', family='x'))
L.clear_veto('w', family='x'); print('after clear_veto:', L.is_vetoed('w', family='x'))"
#   -> 1 fail: False   2 fail: True   after 10 wins: True   after clear_veto: False

# the P0 card fixture is schema-valid; the book feeds Gate B unchanged
.venv/Scripts/python.exe -c "
from src import contracts as C, gates as G
from src.memory import AcceptedBook
import numpy as np, pandas as pd, tempfile
C.validate_card(C.make_fake_card()); print('make_fake_card OK')
bk=AcceptedBook(tempfile.mkdtemp()+'/b.parquet')
d=pd.bdate_range('2018-01-01',periods=20); s=[f'S{i}' for i in range(8)]
bk.add_to_book('c1', pd.DataFrame(np.random.randn(20,8), index=d, columns=s))
print(list(G._book_to_frames(bk.get_book())))"
#   -> make_fake_card OK
#   -> ['c1']
```

---

## 4. What I could NOT verify, and why

- **Real-data behaviour of the book.** `AcceptedBook` was exercised only on
  synthetic 20–30 × 8–10 frames. On the real panel it holds ~200 symbols ×
  ~2 700 days × N cards; `add_to_book` **rewrites the whole parquet each call**
  (O(total rows)). Fine at demo scale (a handful of accepted cards); it would
  want an append path at hundreds. Not measured at full size.
- **Concurrent writers.** `FormulaIndex` and `AlphaCardStore` open separate
  connections to `memory.db`; each sets `PRAGMA busy_timeout = 5000` + a 30 s
  connect timeout, so brief contention retries. Two OS processes writing at once
  is untested — P10 is single-process.
- **Full `gate_b` round-trip.** Verified only that `gates._book_to_frames`
  accepts `get_book()`'s shape, not a complete `gate_b(card, book=…, ledger=…)`
  call — that is a P10 concern.

---

## 5. Failures and open issues

- No functional failures. P7: **20/20** tests pass. Full suite P0–P7:
  **208 passed**, no regressions.
- The first draft shipped a **defect I caught in self-review**: the veto decayed
  its failure record on each success, so one good run could lift a veto earned by
  three failures — backwards from "failures are more reliable than successes".
  Fixed (sticky veto + `clear_veto`); regression test `test_veto_is_sticky_…`.

---

## 6. Anything that contradicts the spec

- **Section 0.5 specifies an `AlphaCard` artifact; P0's `contracts.py` never
  built its `validate_card` / `make_fake_*`** (P0 only did the tabular parquet
  artifacts — verifiable in `reports/p0_handoff.md`). Section 0 says "for **each**
  artifact in Section 0.5: `validate_<name>` … and `make_fake_<name>`". I have
  now added `validate_card` + `make_fake_card` to `contracts.py` to close that
  gap — **this edits a phase that was already signed off.** The edit is purely
  additive (new `CardSchemaError(SchemaError)`, new functions, new constants);
  no existing validator, fixture, or constant was touched, and the full suite is
  the check. If the owner would rather this had stayed out of `contracts.py`,
  moving it back to `memory.py` is mechanical.
- **`verdict` vocabulary.** Section 0.5 shows top-level `"verdict":"accept"` and,
  separately, `redteam.verdict":"survives"`. `validate_card` enforces the
  **top-level** set `{accept, reject, revise, provisional}` (`provisional` =
  pre-Gate-B) and does not inspect `redteam.verdict`. Flag if you want the
  top-level set narrowed to `{accept, reject}`.
- Nothing else contradicts the spec.

## 7. Decisions I made that the spec left open

1. **Physical layout.** The three *exact* stores (formula index, card index,
   lineage) share `data/memory.db`; the *semantic* lesson store is a separate
   file `data/lessons.db`; the book is `data/book.parquet`. The spec mandates
   exact-vs-semantic separation, not one-file-per-exact-store.

2. **Veto trigger — TWO confident failures + the gate.** `veto` iff
   `n_observations >= 3` **AND** `n_conf_failures >= 2`, where a "conf failure"
   is one reported at `confidence >= VETO_CONFIDENCE (0.80)`. Reasoning: the spec
   pairs "a high-confidence failure hard-blocks" with "not applied until n≥3", and
   the guard section is explicit that *even n=3 is a dangerous basis for an
   irreversible call*. So: never an n<3 veto (the gate), and never a one-sample
   veto (needs two independent confident failures — a lone confident failure
   among successes is treated as a fluke, tested). `force_veto()` is the
   human/Planner escape hatch that bypasses both — a deliberate override, not a
   learned inference. If you want a single confident failure to block, it is a
   one-line change (`_MIN_CONF_FAILS_TO_VETO = 1`).

3. **Vetoes are sticky.** Once the rule fires it stays fired; later successes
   never lift it. The only reversal is an explicit `clear_veto()` (logged,
   human/Planner). A permanent-ish motif veto is acceptable because (a) it is
   *narrow* — one edit motif in one context, not a family defund — and (b) the
   exploration floor (③) keeps the whole family funded regardless. That is the
   spec's stated second defense against second-order overfitting; veto erosion
   is not.

4. **`confidence` = reliability, not direction.** Two fields:
   `p_helps` = EWMA(α=0.5) of the helped signal (the direction), and
   `confidence = |2·p_helps − 1| · (1 − 0.5**n_observations)` = one-sidedness ×
   maturity. A motif that *reliably hurts* therefore has **high** confidence and
   **low** `p_helps` — the negative knowledge is not hidden behind a small
   number. `applicable_priors` is ordered `p_helps` desc then `confidence` desc,
   so lean-toward priors surface first and a reliably-harmful-but-not-yet-vetoed
   motif appears last with its low `p_helps` visible. The spec shows only a
   static `confidence: 0.7` with no definition.

5. **Context key = family by default.** Lessons keyed `(motif, context_key)`,
   `context_key` defaulting to `family`. `parent_context` (free text) is kept for
   keyword retrieval but not used as a key — near-identical contexts would never
   aggregate otherwise. Callers can pass an explicit `context_key` for finer
   scoping.

6. **Bandit allocation = softmax over mean reward, floored and renormalised.**
   `alloc_f = floor + (1 − n·floor) · softmax(mean_reward_f / 0.5)_f`; every
   share `≥ floor` (while `n·floor ≤ 1`), sum `= 1`. Temperature 0.5 is a
   judgement call (lower = greedier). Degrades to uniform if `n·floor ≥ 1`.

7. **The 10 idea-families** (`momentum, reversal, volatility, liquidity,
   value_proxy, microstructure, seasonality, quality_proxy, sentiment_proxy,
   trend`) are seeded by `init_memory`. The spec says "~10 rows" without naming
   them; P8/P10 may rename — `register_family` accepts any string.

8. **`formula_hash` canonicalises before hashing** (`"sha256:" + sha256(
   ast_tools.canonical(f))`), so `mul(a,b)` and `mul(b,a)` collide. Unparseable
   formulas fall back to the stripped raw string and store `canonical_ast = NULL`.

9. **`lineage_path` returns root → leaf**, full card dicts; a missing ancestor
   becomes `{"card_id":…, "missing": True}`, a cycle is broken defensively with a
   `{"cycle_detected": True}` sentinel. Root-first matches how a genealogy reads.

10. **`AcceptedBook.get_book()` returns long `date·symbol·factor·value`**
    (`factor` = `card_id`) — exactly one of the shapes `gates._book_to_frames`
    accepts, so `memory.get_book()` drops straight into `gate_b`.
    `get_book_wide()` gives the `{card_id: wide}` dict for other callers.

11. **`new_card` stays in `memory.py`** (not `contracts.py`). It is a
    convenience *builder* the loop/tests use, not an artifact contract — it is
    not mentioned anywhere in the spec. Only the *validator* and *fixture*
    (`validate_card`, `make_fake_card`) went to `contracts.py`.
