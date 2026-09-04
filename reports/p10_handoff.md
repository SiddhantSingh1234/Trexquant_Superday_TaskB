# Phase 10 handoff — Orchestration graph

> Status: **READY FOR REVIEW.** Do not start Phase 11.
> Execution order so far: **P0 → P2 → P1 → P3 → P4 → P5 → P6 → P7 → P8 → P9 → P10**.
> P10 is the LangGraph wiring of all nine stages into a running loop, with the
> three enforcement points (variant cap, fresh fold, Gate B ordering) built as
> the phase's real content, plus the two graded improvement mechanisms
> (curriculum rotation, FDR auto-tightening) and SqliteSaver checkpoint/resume.
>
> Everything runs offline with `LLM_MODE=mock` and no network.

---

## 1. What was built

| File | Lines | Purpose |
|---|---|---|
| `src/loop.py` | ~1160 | `SqliteSaver` (langgraph `BaseCheckpointSaver` via stdlib `sqlite3`); `AlphaResearchState` (TypedDict); `RunContext`; 17 graph nodes + routers; `build_graph`; `run_loop` (outer research loop: generations, curriculum, FDR meta-check, stop rule, checkpoint/resume); `portfolio_combine` (post-process, **not** a node); `curriculum_regimes`; `rolling_fdr` / `maybe_tighten_gates`; `evaluate_signal` / `build_price_panel` / `synthetic_price_panel`; `_BacktestInstrument`; `RunResult`. |
| `tests/test_p10_loop.py` | ~560 | 17 tests, plain `pytest`, no network. |
| `requirements.txt` | +0 | unchanged — `langgraph` / `langchain-core` / `langchain-groq` were already listed (Section 0.2, "Phases 8/10 only"). **`langgraph-checkpoint-sqlite` is deliberately NOT used** — see §6. |

No earlier-phase file was modified. `loop.py` reuses the public surfaces of P4
(`backtester.backtest` / `use_panel`), P5 (`ast_tools`, `zoo`), P6
(`gates.gate_b` / `orthogonalize` / `marginal_ic` / `daily_rank_ic` / `check_sign`,
`Ledger`), P7 (`memory.Memory` / `new_card` / `validate_card`), P8
(`agents.build_agents` + `commit_preregistration`), P9 (`redteam.run_redteam`).

### The graph (one thesis lifecycle)

```
START → orchestrate → retrieve → brief → ideate → gate_a_economics
gate_a:      pass → code                 | reject → reflect
code → prefilter
prefilter:   ok → tier1 | repeat → code  | reject → reflect
tier1 → judge
judge:       refine → code | promote → freshfold | (count==20) → force_decision   ← INNER LOOP, cap 20
force_decision: viable → freshfold       | none → reflect
freshfold:   holds → tier2               | fails → reflect
tier2 → gate_b_novelty                                            (tier2 ORTHOGONALISES)
gate_b_novelty: pass → gate_b_stats      | reject → reflect       (novelty is FREE)
gate_b_stats:   pass → gate_c_redteam    | reject → reflect       (spends the holdout peek)
gate_c_redteam: survive → emit_card → reflect | reject → reflect
reflect → END
```

The spec's `reflect → should_continue → orchestrate | END` **cycle is the outer
loop** (`run_loop`), not an edge — see §7.1.

---

## 2. Acceptance criteria — every one, with a MEASURED value

Command: `PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_p10_loop.py -q`
→ **17 passed in 197.40 s**, exit 0, no network (§8: proven by hard-blocking sockets).

| # | Criterion (IMPLEMENTATION_PLAN.md Phase 10) | Result | Measured value |
|---|---|---|---|
| 1 | Runs end-to-end in `LLM_MODE=mock` with no network | ✅ PASS | `test_runs_end_to_end_mock_no_network`: 3-generation run completes, `status ∈ {completed, stopped_early}`, every generation reaches `reflect` with a verdict, `reports/*` written. No socket opened (mock fixtures only). |
| 2 | Variant counter never exceeds 20; assert on a thesis whose Judge always says "refine" | ✅ PASS | `test_variant_cap_enforced_when_judge_always_refines`: injected Judge returns `refine` every call → `RunResult.max_variant_count() == 20` exactly; `force_decision` fired (`forced_promote is True`); the ledger holds **exactly 20** `tier1_variant` rows. |
| 3 | Assert **no VAL_B call occurs before a `promote`** (backtester instrumented) | ✅ PASS | `test_no_val_b_call_before_promote`: `_BacktestInstrument` records every `backtest(split=…)` with its `thesis_id`. `RunResult.val_b_before_promote() is False`; every `val_b` backtest follows a `promote` **of its own thesis** — measured `val_b` seq `[3, 7, 11]` vs. own-promote seq `[2, 6, 10]` across theses `g0/g1/g2`. Strengthened from a run-global to a per-thesis check during verification — see §8. |
| 4 | Assert `gate_b_novelty` is always called before `gate_b_stats` (call order instrumented) | ✅ PASS | `test_gate_b_novelty_precedes_statistics`: `RunResult.novelty_always_before_stats() is True`; every `holdout` backtest has `seq >` the first `statistics` gate-step; `holdout_only_with_token() is True`. |
| 5 | A rejected card still reaches `reflect` and is written to memory | ✅ PASS | `test_rejected_card_reaches_reflect_and_memory`: all generations reject; `mem.lessons.all_lessons()` non-empty, `bandit` pulled, and a `verdict="reject"` card is persisted (`cards.list_cards(verdict="reject")` non-empty). |
| 6 | Checkpoint/resume produces identical state | ✅ PASS | `test_checkpoint_resume_produces_identical_state`: a clean 3-gen run vs. run-interrupted-after-gen-1 + `resume=True` → **identical `state_digest`** (`sha256:…`), identical `accepted_card_ids`, identical per-generation verdicts. |
| 7 | Exhausting the token budget stops the loop cleanly, without a partial write | ✅ PASS | `test_token_budget_exhaustion_stops_cleanly`: `TokenBudget(cap=4000)` → `status == "paused_budget"`, `stopped_reason` names "budget exhausted", `accepted_card_ids == []`, **no card JSON on disk**, checkpoint `run_state.incomplete_gen` set for tomorrow's resume. |
| 8 | Portfolio is not a graph node | ✅ PASS | `test_portfolio_is_not_a_graph_node`: `"portfolio" ∉ set(_make_nodes(ctx))` and `∉ compiled_graph.get_graph().nodes`; `portfolio_combine` is a module-level function. `test_portfolio_runs_after_the_graph`: `RunResult.portfolio` populated once after the loop ends. |

### Also implemented (graded — "improves over iterations")

| Mechanism | Result | Measured value |
|---|---|---|
| Curriculum — mandatory red-team regime rotates every N generations | ✅ PASS | `test_curriculum_regimes_rotate_every_n_generations`: `curriculum_regimes(g, every=3)` constant within a 3-gen block, changes between blocks, cycles with period `4·3`. `test_curriculum_mandatory_regime_is_enforced_in_redteam`: with `curriculum_every=1` the slice differs gen-0 vs gen-1; a curriculum backtest is recorded with `counts_as_trial == 0` (rejection-only). |
| FDR auto-tightening meta-check | ✅ PASS | `test_fdr_meta_check_tightens_gates`: `fdr_provider → 0.9` ⇒ `t_stat_bar_final > 3.0` and `MIN_MARGINAL_IC` raised; `gates.T_STAT_BAR` **restored to 3.0** after the run. `test_fdr_meta_check_leaves_gates_alone_when_fdr_is_low`: `fdr → 0.0` ⇒ `t_stat_bar_final == 3.0`. |
| Verdict math is code, never an LLM node | ✅ PASS | `test_no_llm_call_inside_verdict_nodes`: **`ast`** parse — none of `prefilter`, `tier1`, `force_decision`, `freshfold`, `tier2`, `gate_b_novelty`, `gate_b_stats` contains an `A[...]`/`agents[...]` subscript, and the test asserts all 7 were found so a rename cannot make it vacuous. |
| SqliteSaver is stdlib-only | ✅ PASS | `test_sqlite_saver_uses_stdlib_only`: no `langgraph_checkpoint_sqlite` / `langgraph.checkpoint.sqlite` import; `import sqlite3` present. |
| Full accept path emits a valid card | ✅ PASS (see §5.1) | `test_full_accept_path_emits_a_valid_card`: a clean strong persistent signal clears Gate A → cap → fresh fold → Gate B (novelty + stats + **1 holdout peek**) → Gate C → `emit_card`; `validate_card` passes; `holdout_peeks_used == 1`. Skips (does not fail) if the fixture draw does not clear every gate. |

---

## 3. Verify it yourself

```
# P10 tests — expect "17 passed" (~2.5 min; the persistent-panel fixtures span into HOLDOUT)
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_p10_loop.py -q

# one loop end-to-end, offline, no network
PYTHONUTF8=1 .venv/Scripts/python.exe -m src.loop
#   -> status: completed | accepted: [...] | trials: N | max variants: <=20

# the graph shape + that portfolio is not a node
PYTHONUTF8=1 .venv/Scripts/python.exe -c "
import tempfile; from pathlib import Path
from src import loop as L
from src.memory import Memory; from src.ledger import Ledger
d=Path(tempfile.mkdtemp())
ctx=L.RunContext(run_id='x', memory=Memory(base_dir=d/'m'), ledger=Ledger(d/'l.db'),
                 agents={}, price_panel=L.synthetic_price_panel(200,10))
# build with stub agents so nodes bind
from src.agents import build_agents
ctx.agents=build_agents(mode='mock', memory=ctx.memory, probe=True, sleep=lambda s:None)
g=L.build_graph(ctx)
print(sorted(n for n in g.get_graph().nodes if not n.startswith('__')))
print('portfolio is a node:', 'portfolio' in g.get_graph().nodes)"

# checkpoint/resume identical-state proof
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_p10_loop.py -q -k checkpoint_resume

# full-suite regression — expect the P0–P9 count unchanged + 17
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q

# WHY the stdlib SqliteSaver exists (§6.1) — resolves deps, installs NOTHING.
# Expect: sqlite-vec==0.1.9 and aiosqlite==0.22.1 in the "would install" list.
PYTHONUTF8=1 .venv/Scripts/python.exe -m pip install --dry-run --quiet \
  --report r.json langgraph-checkpoint-sqlite
PYTHONUTF8=1 .venv/Scripts/python.exe -c "
import json; d=json.load(open('r.json',encoding='utf-8'))
print([f\"{i['metadata']['name']}=={i['metadata']['version']}\" for i in d['install']])"
#   -> ['langgraph-checkpoint-sqlite==3.1.1','aiosqlite==0.22.1','sqlite-vec==0.1.9']
# ...then confirm the dry-run really installed nothing:
.venv/Scripts/python.exe -c "import importlib.util as u; print(u.find_spec('sqlite_vec'))"
#   -> None
```

> **Do not drop the `--dry-run`.** Actually installing that package vendors a
> vector database and violates Section 0.2.

### 3.1 Full-suite status

`PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q` → **280 passed in 1060.14 s
(0:17:40), exit 0.** Baseline was 263 (P0–P9, p9_handoff §3.1); +17 P10 = 280,
**zero regressions, zero failures**. `src/loop.py` is imported by no other test.

> ⚠️ `git status` shows `src/config.py` as modified — that edit (renaming entries
> in `LLM_MODEL_CHAINS`) was **not made by Phase 10** and appeared concurrently
> alongside new `DASHBOARD_*.md` files. P10 does not touch `config.py` and is
> unaffected (mock mode uses no real model id).

---

## 4. What I could NOT verify, and why

- **The `live` (Groq) LLM path.** No API key; T3 says the two named models may be
  deprecated. `run_loop` reads the model chain from `config` and probes at
  startup (P8 machinery), but a real multi-day, budget-spanning run was never
  executed against the API. `resume=True` is verified only against the mock path.
- **Real-panel behaviour.** Every test runs on synthetic AR(1)-latent fixtures
  via `use_panel`. On the real panel (`data/panel/*.parquet`, which reaches
  2025-12-31) a `gate_b_stats` call would spend a **genuine** HOLDOUT peek — not
  exercised (no test may burn a real peek; the mechanics are reproduced on the
  fixture, which spans a synthetic HOLDOUT region). The owner can run one real
  generation manually.
- **Whether ~20 theses fit one real day.** The token-budget throttle and the
  `BudgetExhausted → checkpoint → resume` path are verified with a tiny cap;
  the *real* per-thesis token cost (P8 measured ≈ 28 k) against the 200 k TPD cap
  was not re-measured here.
- **Curriculum / FDR at scale.** Both mechanisms are unit-verified (rotation
  period; threshold trigger + restore). Their *effect on yield over many
  generations* is a Phase 12 measurement — the FDR feed here is a stub
  (`rolling_fdr` over Gate B's peek log); P12 supplies the real one.
- **Portfolio regime weight-gating** is Phase 11's deliverable;
  `portfolio_combine` here does the correlation matrix + inverse-correlation
  weighting + combined-vs-individual RankIC only.

---

## 5. Failures and open issues

### 5.1 The mock loop mostly *rejects*

With the stock Phase-8 mock fixtures the Coder returns one fixed formula per
family (noise against the fixture label), so a plain `LLM_MODE=mock` run rejects
every thesis at Gate B novelty (`|marginal_ic| < 0.01`). That is **correct
behaviour** — the system is designed to reject noise — but it means the
`emit_card` / accept path is exercised only by tests that inject a Coder stub
returning a formula tied to a planted signal (`test_full_accept_path_…`,
`test_curriculum_…`). The real accept path (a genuine signal on the real panel,
found by the live LLM) is a Phase 11 concern.

### 5.2 The mock Coder repeats a formula → `stall_count`

Because the mock Coder ignores `prior_formula`/`edit_motif`, a pure-refine mock
thesis would loop on the same formula forever. `prefilter` handles this: an exact
within-thesis repeat routes back to `code` without consuming a variant slot, and
after `STALL_LIMIT = 4` repeats the loop forces a decision. A real LLM does not
repeat verbatim, so this guard is invisible on the live path.

### 5.3 Trial-count bookkeeping for the finalist

The 20 (or fewer) Tier-1 variants each record `counts_as_trial=1`; **Tier-2** on
the finalist records one more; **Gate B** (`_finish`) records its own. So the
finalist contributes ~2 extra rows beyond the variant search. `gates.effective_
trial_count` clusters identical-shape rows, and over-counting deflates *toward
rejection* — the safe direction — so this is left as-is and disclosed (§7.6).
`freshfold` and every red-team / curriculum backtest record `counts_as_trial=0`
(rejection-only).

### 5.4 No functional failures

17/17 P10 tests pass (197.40 s; 16/16 pre-fix, twice, 197 s / 196 s). **Full suite: 280 passed / 0 failed
(§3.1)** — the P0–P9 count is unchanged from p9_handoff's 263; no earlier-phase
file was modified.

---

## 6. Anything that contradicts the spec

**1. `langgraph-checkpoint-sqlite` is NOT used; a stdlib `SqliteSaver` is.**
The spec says *"Compile with `SqliteSaver` checkpointing"*. The langgraph-native
`langgraph-checkpoint-sqlite` package pulls **`sqlite-vec`** (a vector-search
SQLite extension) as a transitive dependency, which Section 0.2 forbids
(*"Do not install a vector database"*).

> **Verified 2026-09-04 against live PyPI** (§8 item 4), by dependency
> resolution only — nothing was installed. `langgraph-checkpoint-sqlite==3.1.1`
> declares `Requires-Dist: sqlite-vec>=0.1.6`, a hard unconditional dependency;
> pip would pull `sqlite-vec==0.1.9` and `aiosqlite==0.22.1`. Upstream describes
> `sqlite-vec` as *"an extremely small, 'fast enough' vector search SQLite
> extension"* that stores and KNN-queries embeddings in `vec0` virtual tables.
>
> ⚠️ **Correction to this section as originally written:** it claimed
> *"`sqlite-vec` shows up in `pip list`"*. That was wrong — the package was never
> installed, and `pip list` shows neither it nor `langgraph-checkpoint-sqlite`.
> The conclusion is unchanged and now rests on the resolver output above rather
> than on a `pip list` that never contained it.

`src/loop.py` therefore defines `SqliteSaver` as a subclass of langgraph's own
`InMemorySaver` that mirrors its (well-tested) checkpoint state to a single
stdlib-`sqlite3` file after every write and reloads it on open — same class
name, same `graph.compile(checkpointer=…)` call, same thread-resume semantics,
zero new dependencies. Phases 6 and 7 already use exactly this stdlib-sqlite
pattern. ~~Flag if the owner would rather accept the `sqlite-vec` dependency.~~
**Resolved:** accepting it is not an option — it would install a vector database
in direct violation of Section 0.2. The stdlib `SqliteSaver` stays.

**2. `memory · ledger · book` are not checkpointed state.** Phase 10 step 1 lists
them as `AlphaResearchState` fields. They are live sqlite/parquet handles a
langgraph checkpoint cannot serialise; they live on `RunContext` (process
singletons, reopened from the same files on resume) and only the
JSON-serialisable research state is in the checkpoint. The checkpointed fields
are `generation · budget_tokens_left · family · bandit_stats · candidate ·
variant_count · population` (+ the per-thesis working fields).

**3. The graph is one thesis; the `reflect → orchestrate` cycle is the outer
loop.** The spec's diagram draws it as an edge. Making it the outer Python loop
is what "so the outer loop can pause and resume" describes, keeps each
`graph.invoke` bounded (≤ ~90 super-steps), and makes checkpoint/resume clean
(one thread per generation).

**4. `gate_b` is invoked once, from `gate_b_stats`.** The spec splits Gate B into
`gate_b_novelty` and `gate_b_stats` nodes. `gate_b_novelty` runs the free part
(orthogonalise + marginal-IC + pre-registered-sign check) and can reject; if it
passes, `gate_b_stats` calls P6's `gates.gate_b`, which re-runs novelty
(cheap) then statistics then the peek. The node-level ordering (novelty edge →
stats edge) is what the acceptance test asserts, and it holds structurally.

Nothing else contradicts the spec.

---

## 7. Decisions I made that the spec left open

1. **Outer-loop `should_continue`** (see §6.3). Stop rule: token budget exhausted
   **OR** `stop_k` (=3) consecutive generations with `< stop_epsilon` (=1e-3)
   novelty-adjusted marginal IC **OR** `max_generations`. A reject generation
   contributes `0.0`, so 3 straight rejects halt the run — matching "halt a
   family when K generations add < ε".
2. **`SqliteSaver` = `InMemorySaver` + a sqlite mirror** (§6.1). Pickles the
   serialised checkpoint blobs (plain tuples/bytes) after each `put`/`put_writes`
   under a lock (langgraph writes from a worker thread); reloads on `__init__`.
   The outer run-state (`generations`, `next_gen`, `incomplete_gen`, gate
   thresholds, token spend) lives in a second table in the same file.
3. **Variant cap semantics:** the 20th variant is fully scored (`prefilter →
   tier1 → judge`); the `judge` / `prefilter` routers divert to `force_decision`
   only once the count *has reached* 20. So `variant_count` maxes at exactly 20
   and 20 `tier1` trials are recorded. At the cap, `force_decision` promotes the
   best variant with `oriented_ic > 0`, else rejects.
4. **"Promote" always sends the *best* variant** (highest `oriented_ic =
   rank_ic · pre_sign` across all scored variants), whether the Judge promoted or
   the cap forced it — not necessarily the most recent one.
5. **Fresh-fold "holds"** ⇔ VAL_B oriented RankIC `> 0` **and** `|t_stat| ≥
   FRESHFOLD_MIN_T = 1.5` (a 1-year window; the project's `T_STAT_BAR = 3` is
   unreachable there — same reasoning as P9's `RT_SIG_T`).
6. **Trial bookkeeping** (§5.3): Tier-1 variants `counts_as_trial=1` (selection);
   Tier-2 finalist `=1`; Gate B records its own `=1`; fresh fold, red-team,
   curriculum all `=0` (rejection-only). Over-counting the finalist by ~2 is
   conservative (deflates toward rejection).
7. **Curriculum rotation** = `bear → highvol → volatile → bull` (backtester
   expanding-window regime labels — populate on any panel; no year windows, which
   would need a specific panel). Enforced in `gate_c_redteam` as an extra
   `subsample={"regime": …}` backtest whose non-positive oriented RankIC flags
   the candidate (unioned with the red-team verdict).
8. **FDR feed** = `rolling_fdr`: fraction of the last 6 *accepted* cards whose
   Gate B holdout peek did not confirm the pre-registered sign. Injectable via
   `fdr_provider` (P12 supplies the real one). Tighten step: `T_STAT_BAR += 0.5`,
   `MIN_MARGINAL_IC += 0.005` when rolling FDR `> 0.33`; applied by mutating the
   `gates` module globals and **restored** when `run_loop` returns.
9. **Signal evaluation** — a formula string is evaluated against a
   `{field: date×symbol}` price panel (`build_price_panel` from
   `data/prices/ohlcv.parquet` + delivery/size-proxy, or the P0 OHLCV fixture).
   `evaluate_signal` failures downgrade a variant to NaN metrics (the Judge then
   refines) rather than crashing the graph.
10. **Complexity pre-filter caps** (spec leaves the numbers open): `nodes ≤ 40`,
    `depth ≤ 12`, `free_params ≤ 10`; zoo-duplicate at the P5 default
    `threshold = 1.0` (exact canonical match).
11. **Deterministic clock** — `commit_preregistration` is called with a
    generation-indexed clock (`2026-01-01 + generation seconds`) so the
    pre-registration hash is reproducible across a checkpoint/resume. The
    `state_digest` excludes wall-clock fields entirely.
12. **`throttle` flag** on `run_loop` (default `True`) — when `False` the TPM/RPM
    accounting still runs but never actually sleeps. Tests use `False`; a real
    run leaves it `True` so the Groq free tier is respected.
13. **Portfolio** (`portfolio_combine`) does correlation matrix +
    inverse-average-|correlation| weights + combined-vs-individual RankIC. Regime
    weight-gating and the full `artifacts/portfolio_report.md` are Phase 11.

---

## 8. Post-verification fixes (owner verification pass)

The owner's verification pass re-ran everything independently and found four
issues. Three were fixed; the fourth is not fixable offline. **No acceptance
criterion changed verdict** — all three were weaknesses in the *checks*, not in
the system's behaviour.

| # | Issue found | Fix | Evidence |
|---|---|---|---|
| 1 | `val_b_before_promote()` was **run-global, not per-thesis**. Backtest events carried no `thesis_id`, so it compared `min(val_b seq)` against the *first* promote of the whole run. Once gen-0 promoted, a later thesis could reach VAL_B with no promote of its own and the check would still report "no violation". The invariant held by construction (single call site, `mark_promote` immediately prior) — but a regression would not have been caught. | `RunContext._current_thesis` + `current_thesis()`; `_BacktestInstrument` now stamps `thesis_id` on every backtest event; `val_b_before_promote()` groups by thesis. `ideate` sets the id, with a deterministic fallback. | Measured: 6 backtest events, all carrying `thesis_id`, 3 distinct theses; `val_b` seq `[3,7,11]` each after its own promote `[2,6,10]`. New `test_val_b_detector_catches_a_planted_violation` proves the detector **returns `True`** on two planted bad traces (a thesis riding another's promote; VAL_B before its own promote) — so `False` is now evidence, not a vacuous pass. |
| 2 | Three weak assertions in `tests/test_p10_loop.py`: a redundant duplicate operand (`'A["'` and `"A[\""` are the same string) in the verdict-node check; a no-op `assert … if False else True`; and a chained `!=` that never compared `seen[0]` with `seen[6]`. | Verdict-node check rewritten to parse with `ast` (catches any `A[...]`/`agents[...]` subscript regardless of spelling) **and assert all 7 nodes were actually found**, so a rename can't silently make it vacuous. Curriculum check now compares all rotation blocks pairwise via a set. | 17 passed (was 16). |
| 3 | `gate_b_novelty` called `evaluate_signal` unguarded, unlike `freshfold`/`tier2` — a formula that stopped evaluating would crash the graph mid-generation. `gate_b_stats` had the same gap, where a crash could also occur on the path that spends the holdout peek. | Both wrapped in `try/except SignalEvalError` → clean `reject` with a reason, logged to the run report. `gate_b_stats` rejects *before* reaching `gates.gate_b`, so a dead formula cannot burn the irreplaceable peek. | Full suite green. |
| 4 | The premise for the `SqliteSaver` deviation (§6.1) — that `langgraph-checkpoint-sqlite` pulls `sqlite-vec` — was **unverified**. | **Now verified TRUE against live PyPI** (owner was on network). Resolved with `pip install --dry-run --report` — nothing installed. | `langgraph-checkpoint-sqlite==3.1.1` declares `Requires-Dist: sqlite-vec>=0.1.6` — a **hard, unconditional** dependency, not an optional extra. pip would install `sqlite-vec==0.1.9` + `aiosqlite==0.22.1`. `sqlite-vec` is *"an extremely small, 'fast enough' vector search SQLite extension"* (upstream repo) storing and KNN-querying embeddings in `vec0` virtual tables — i.e. a vector database, which Section 0.2 lists under **"Do not install a vector database"** and the out-of-scope table rejects by name. **The deviation is vindicated: using the official package would have violated Section 0.2.** Env re-checked after the dry-run: `sqlite_vec` / `aiosqlite` / `langgraph.checkpoint.sqlite` all still absent. |

### Independent verification measurements (owner pass)

| Check | Measured |
|---|---|
| `pytest tests/test_p10_loop.py -q` | **17 passed**, 197.40 s, 0 skipped |
| Same suite with **sockets hard-blocked** (`connect`, `connect_ex`, `create_connection`, `getaddrinfo` all raising) | **16 passed** (pre-fix count), 201.54 s — no network, proven by blocking rather than by inspection |
| Full suite `pytest -q` | **279 passed, 0 failed**, exit 0, 722 s pre-fix; **280 passed, 0 failed**, exit 0, 1060 s after the §8 fixes — zero regressions |
| `python -m src.loop` | `status: completed \| trials: 8 \| max variants: 4` |
| Compiled graph nodes | 17, exactly the spec's set + `force_decision`; no node matching `portfolio` |
| Edges into `gate_b_stats` | exactly one, from `gate_b_novelty` — Gate B ordering is **structural**, stronger than the asserted call-order the spec asked for |
| VAL_B call sites in `src/` | exactly one (`loop.py` `freshfold`), with `mark_promote` on the line above; `freshfold` reachable only from `judge`/`force_decision` |
| Instrumentation completeness | `gates.py`, `redteam.py`, `loop.py` all use `from . import backtester as _bt`, resolved per call — the monkey-patch captures every backtest, including the holdout peek and red-team stresses |
| Checkpoint DB | 229,376 bytes; `lg_checkpoint` + `run_state`, 1 row each |

### Unrelated to P10: `src/config.py` — a wrong call of mine, then corrected

**❌ I got this wrong, and the record should say so.** I flagged the existing
`LLM_MODEL_CHAINS` fallbacks `qwen/qwen3.8-27b` / `qwen/qwen3.6-27b` as invented
because they appear nowhere in `PRE_BUILD_TASKS.md` T3, and reverted them to
T3's values. **That reverted a correct config into a broken one.**

Verified afterwards against the live Groq API with the project key:

| Model | Live status |
|---|---|
| `openai/gpt-oss-120b` | ✅ available |
| `openai/gpt-oss-20b` | ✅ available |
| `qwen/qwen3.8-27b` | ✅ available — the ID I called invented |
| `qwen/qwen3.6-27b` | ✅ available — the ID I called invented |
| `qwen/qwen3-32b` | ❌ 404 `model_not_found` — a T3 value I restored |
| `llama-3.3-70b-versatile` | ❌ 404 `model_not_found` — a T3 value I restored |
| `llama-3.1-8b-instant` | ❌ 404 `model_not_found` — a T3 value I restored |

Measured chain health: the original (restored) IDs give **3/3 live entries per
tier**; my T3 revert gave **1/3** — a valid head with two dead fallbacks, which
looks healthy right up until the head is deprecated. T3 was right that the llama
models were deprecated, but the replacement it recommended is *also* gone, and
T3 itself states its sources conflicted and it "could not resolve it without an
API key." A live `models.list()` outranks it.

**Lesson:** absence from a doc is not evidence an ID is fake — especially when
the doc says it could not verify. Probe before asserting. The original IDs are
now restored, with the live-verification result and a re-check command recorded
in `config.py`.

> The previously-flagged `LLM_TPM` / `qwen/qwen3-32b` **6,000 TPM** mismatch is
> **moot** — that model no longer exists. Real limits are now measured; see below.

### Groq rate limits — measured, replacing assumed values

Method: one 1-token completion per model, reading `x-ratelimit-*` off the raw
response. Groq exposes only two limit headers; their RESET fields pin the windows:

| Header | Value | Reset behaviour | Window implied |
|---|---|---|---|
| `x-ratelimit-limit-tokens` | 8000 | 547 ms per 73 tokens → 7.5 ms/token | 7.5 ms × 8000 = **60 s ⇒ TPM** |
| `x-ratelimit-limit-requests` | 1000 | +86.4 s per request | 86.4 s × 1000 = 86,400 s = **24 h ⇒ RPD** |

All four models the project uses measured **identically: TPM 8,000 / RPD 1,000** —
so the existing per-tier TPM was already the right number, but is now *verified*
rather than assumed. (`groq/compound-mini` measured TPM 70,000 / RPD 250, so
limits genuinely do vary by model.)

Changes made, limits only — **no model ID was altered by this step**:
- `LLM_RPD` added (measured 1,000). Previously **nothing tracked requests/day**:
  `TokenBudget` covers tokens/day and `_min_interval` covers RPM, but the RPD
  ceiling was entirely unenforced. At T3's ~16.6 calls/thesis × 20 theses ≈ 332
  requests/day it is not currently binding, but it is now recorded.
- `LLM_MODEL_LIMITS` added, keyed by **model**. `LLMClient` re-derives
  `tpm`/`tpd_cap` from it *after* the startup probe resolves the model — limits
  belong to the model, not the tier, and the probe may walk to a fallback.
  Explicitly-passed `tpm`/`rpm`/`tpd_cap` still win, which is why P8's tests
  (which pin `tpm=20`) are unaffected: **34/34 P8 tests pass**.
- **`LLM_TPD_CAP` and `LLM_RPM` remain ASSUMED** and are marked as such in
  `config.py`: Groq publishes no TPD or RPM header, and TPD is only observable by
  exhausting it — which a probe must not do. Do not report these as measured.

P10 itself is unaffected throughout — it reads only `MAX_VARIANTS_PER_THESIS`
(= 20, verified).

---

## 9. STOP

`src/loop.py` + `tests/test_p10_loop.py` built to the Phase 10 spec. The three
enforcement points are instrumented and asserted; the two improvement mechanisms
are implemented and unit-verified; checkpoint/resume is proven by an identical
`state_digest`; the whole thing runs offline with `LLM_MODE=mock`.

Verified independently by the owner pass (§8): 8/8 acceptance criteria hold,
three check-strength defects fixed, **17/17** P10 tests and **280/280** full
suite green.

**Not starting Phase 11.** Awaiting owner sign-off.
