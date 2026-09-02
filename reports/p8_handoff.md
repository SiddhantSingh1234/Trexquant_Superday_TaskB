# Phase 8 handoff — LLM agents

> Status: **READY FOR REVIEW.** Do not start Phase 9 / 10.
> Execution order so far: **P0 → P2 → P1 → P3 → P4 → P5 → P6 → P7 → P8**.
> P8 is the eight LLM roles, their prompts, the model-routing + token-budget
> machinery, and the research corpus the Librarian retrieves from. Deterministic
> code (backtester, statistics, novelty check) is **not** an agent and is not
> here — its verdicts cannot be talked around.
>
> **Everything in this phase runs offline** with `LLM_MODE=mock` and no API key.
> The `live` (Groq) and `offline` (Ollama) paths are wired but not exercised by
> the test suite (no network in CI) — see §4.

---

## 1. What was built

| File | Lines | Purpose |
|---|---|---|
| `src/agents/base.py` | 560 | The one call path: `call_llm` / `LLMClient`. Startup **model-availability probe** walking a per-tier fallback chain (no hard-coded model ID); **token-bucket TPM throttle**; **TPD counter** (`TokenBudget`, per-organisation, auto-rollover, resumable via `to_dict`/`from_dict`); **static-prefix caching**; JSON extraction + tiny-schema validate/coerce with repair retries; `BudgetExhausted` (raised *before* the request, no partial write). Mock / Groq / Ollama dispatch. |
| `src/agents/mock_fixtures.py` | 210 | Deterministic canned responses per role for `LLM_MODE=mock`. Sniffs `family=`, `rank_ic=`, `iteration=` from the prompt so the refine loop converges and the Coder returns a Phase-5-parseable formula. `COMPLETION_TOKENS` = the T3 tokens/call figures so a mock thesis lands near 26,500. |
| `src/agents/planner.py` | 55 | Agent 1. Bandit does the arithmetic; LLM picks the family, clamps `max_variants ≤ 20`. |
| `src/agents/librarian.py` | 190 | Agent 2 + the corpus loader/validator + `retrieve` (family + keyword filtering, **no embeddings**). Non-tradeable anomalies are put in `excluded_from_suggestions` by **code**, not the LLM. |
| `src/agents/hypothesis.py` | 130 | Agent 3 + **`commit_preregistration`** — canonical-JSON → sha256 → timestamp, the pre-registered-sign mechanism. `sign_matches` for the later check. |
| `src/agents/economics.py` | 85 | Agent 4 (Gate A). **Structural pre-check**: any blank rubric element → `reject` with no LLM call. Gets its **own** `LLMClient`. |
| `src/agents/coder.py` | 105 | Agent 5. Parses its own output under the strict Phase-5 grammar; one repair round then a hard `CoderError`. |
| `src/agents/judge.py` | 50 | Agent 6. Short prompt. `{action, edit_motif, reason}`. |
| `src/agents/redteam.py` | 75 | Agent 7. Picks from the fixed 11-test menu; **drops any name not on the menu**. Never writes code. |
| `src/agents/reflection.py` | 90 | Agent 8. LLM call first (so `BudgetExhausted` = no memory write), then deterministic writes through the P7 memory guards. |
| `src/agents/__init__.py` | 110 | Re-exports + `build_agents(mode=, memory=)` — shared per-tier `TokenBudget`, **Economics on its own client instance**. |
| `src/agents/prompts/*.txt` | 8 files | One per role. `=== DYNAMIC ===` splits the cacheable static prefix (rubric / operator list / menu) from the per-call body. |
| `data/corpus/anomalies.json` | 53 entries | The research corpus. 36 tradeable / **17 not**. Sources: paper abstracts + published anomaly lists (Harvey-Liu-Zhu, Hou-Xue-Zhang, Kakushadze) — abstracts and factor descriptions only, no paywalled text. |
| `.env.example` | 30 | Documents `LLM_MODE`, `GROQ_API_KEY`, `OLLAMA_HOST`. Explains why no model ID is set. |
| `tests/test_p8_agents.py` | 400 | 34 tests, plain `pytest`, no network. |
| `src/config.py` | +55 | **P0 file modified** — added the LLM-agents block: `CORPUS_DIR`, `ANOMALIES_JSON`, `AGENT_PROMPTS_DIR`, `LLM_MODE`/`GROQ_API_KEY`/`OLLAMA_HOST` (env-read), `LLM_MODEL_CHAINS`, `LLM_ROLE_TIER`, `LLM_TPM`/`LLM_TPD_CAP`/`LLM_RPM`, `AGENT_ROLES`, `LLM_TOKENS_PER_THESIS_PROJECTION`. Purely additive; no existing constant touched. See §6. |

No earlier-phase logic was modified (only the additive `config.py` block).

---

## 2. Acceptance criteria — every one, with a MEASURED value

Command: `.venv/Scripts/python.exe -m pytest tests/test_p8_agents.py -q` → **34 passed in ~21 s**.

| # | Criterion (IMPLEMENTATION_PLAN.md Phase 8) | Result | Measured value |
|---|---|---|---|
| 1 | Every agent returns schema-valid JSON, or raises a clear error after retries | ✅ PASS | `test_all_eight_agents_return_schema_valid_dicts`: all 8 `run()`s return dicts with the required keys. `test_invalid_json_raises_after_retries`: a fixture returning `{"action":"sideways"}` raises `SchemaValidationError` after 3 attempts. |
| 2 | Full test suite passes with `LLM_MODE=mock` and no network | ✅ PASS | 34/34 in `tests/test_p8_agents.py`; full P0–P8 suite: **242 passed in 313.61s** (baseline 208 + 34 P8, no regressions). No test opens a socket. |
| 3 | Hypothesis output containing no `counterparty` is **rejected** by the Economics Reviewer | ✅ PASS | `test_economics_rejects_thesis_missing_counterparty`: `verdict == "reject"`, `used_llm == False`, reason names `counterparty`. Also `test_economics_rejects_when_any_field_blank` for `mechanism`/`why_not_arbitraged`/`falsifiable_claim`. |
| 4 | Economics Reviewer demonstrably uses a separate client instance (assert object identity) | ✅ PASS | `test_economics_reviewer_is_a_separate_client`: `agents["economics"].client is not agents["hypothesis"].client`; their `_seen_prefixes` sets are distinct objects. |
| 5 | The sign hash is computed and stored before any backtest call in the test flow | ✅ PASS | `test_preregistration_hash_precedes_any_backtest`: event log has `prereg_stored` at index < `backtest`; `hash` is `sha256:` + 64 hex (len 71); `committed_at` set. `test_preregistration_is_deterministic_and_refuses_incomplete`: same thesis + fixed clock → identical hash; dropping `counterparty` → `ValueError`. |
| 6 | Token accounting sums correctly per role; exceeding the budget raises | ✅ PASS | `test_token_accounting_sums_per_role_...`: Σ per-role `billed_tokens` (small tier) `== small_budget.used` exactly. `test_exceeding_budget_raises_budget_exhausted`: cap 50 → `BudgetExhausted(cap=50, role="planner")`, `budget.used == 0`. Measured tokens/thesis: **28,010** (small 21,647 + large 6,363). |
| 7 | Coder output parses under P5's parser | ✅ PASS | `test_coder_formula_parses_under_phase5` (8 families): `parse(formula, strict=True)` never raises, `complexity(...)["nodes"] > 1`. `test_coder_repairs_an_unparseable_formula`: `close.values[0]` → repair round → `rank(close)`. |
| 8 | `data/corpus/anomalies.json` has ≥ 35 entries and validates | ✅ PASS | `test_corpus_has_enough_entries_and_validates`: **53** entries, `validate_corpus` passes. `test_corpus_validator_rejects_a_broken_entry`: removing `counterparty` raises. |
| 9 | The startup probe detects an unavailable model and falls through to the next | ✅ PASS | `test_probe_falls_through_...`: `checker=lambda m: m==chain[1]` → returns `chain[1]`, `tried == [chain[0], chain[1]]`. `test_probe_raises_when_nothing...`: all-False checker → `NoModelAvailable`. `test_client_uses_the_probed_model_not_a_hard_coded_one`. |
| 10 | The TPM throttle demonstrably delays calls when the bucket empties (tiny limit) | ✅ PASS | `test_tpm_throttle_sleeps_when_the_bucket_empties`: `tpm=20`, fake clock frozen at 0, fake sleep recorder. First call drains the bucket, second call records `sleep(60.0)`; `client.total_wait_s > 0`. |
| 11 | `BudgetExhausted` is raised, not swallowed, and leaves no partial state write | ✅ PASS | `test_budget_exhausted_leaves_memory_untouched`: `TokenBudget(cap=5)` on the Reflection client → `BudgetExhausted`; `mem.lessons.all_lessons() == []` and `mem.bandit.families() == []`. |
| 12 | Measured tokens-per-thesis in a mock run within 2× of the 26,500 projection | ✅ PASS | `test_tokens_per_thesis_is_within_2x_of_projection`: representative call multiset (1 planner + 1 librarian + 1 hypothesis + 1 economics + 6 coder + 6 judge + 1 red-team + 1 reflection = **18 calls**) → **28,010 tokens** ∈ [13,250, 53,000]. Well inside; ~5.7% over projection. |
| 13 | Retrieval on `family="liquidity"` returns only liquidity-family entries | ✅ PASS | `test_retrieval_by_family_is_exact` (4 families): every hit's `family` matches. `test_keyword_retrieval_ranks_by_hit_count`. |
| 14 | ≥ 10 corpus entries `tradeable_with_our_data: false`, and the Librarian's brief visibly excludes them | ✅ PASS | `test_at_least_ten_entries_are_not_tradeable`: **17**. `test_librarian_brief_excludes_non_tradeable_anomalies`: `family="fundamental"` → `excluded_from_suggestions` non-empty, `candidates_considered == []`, `suggested_angles == []`. `test_librarian_only_suggests_tradeable_names`: every suggested angle has `tradeable_with_our_data is True`. |

Extra tests (not required): `test_call_llm_module_entrypoint_and_prefix_caching` (static prefix billed once, then `cached_tokens` grows), `test_reflection_writes_go_through_memory_guards` (3 observations → `n_observations == 3`), `test_deterministic_same_input_same_output`.

---

## 3. Verify it yourself

```
# P8 tests — expect "34 passed"
.venv/Scripts/python.exe -m pytest tests/test_p8_agents.py -v

# full suite P0-P8 — expect "242 passed" (~5 min; P2/P3 read real parquet)
.venv/Scripts/python.exe -m pytest -q

# one thesis end-to-end, offline, and the token bill
.venv/Scripts/python.exe -c "
import tempfile
from src import config
from src.agents import build_agents
from src.memory import Memory
mem = Memory(base_dir=tempfile.mkdtemp())
ag = build_agents(mode='mock', memory=mem, probe=True)
th = {'mechanism':'m','counterparty':'c','why_not_arbitraged':'w','horizon_days':5,'regime':'calm','falsifiable_claim':'f','pre_registered_sign':1}
ag['planner'].run(allocation={'liquidity':1.0}); ag['librarian'].run(family='liquidity', keywords=['volume'])
ag['hypothesis'].run(family='liquidity'); ag['economics'].review(th)
for i in range(6):
    ag['coder'].run(thesis=th, family='liquidity'); ag['judge'].run(metrics={'rank_ic':0.01*i}, thesis=th, iteration=i)
ag['redteam'].run(thesis=th, formula='rank(close)')
ag['reflection'].run(family='liquidity', edit_motif='widen_ts_window', helped=True, rank_ic_delta=0.005)
tot = ag['planner'].client.budget.used + ag['hypothesis'].client.budget.used
print('calls:', sum(ag[r].client.n_calls for r in ag), ' tokens:', tot, ' (projection 26500)')"
#   -> calls: 18  tokens: 28010  (projection 26500)

# corpus stats
.venv/Scripts/python.exe -c "
from src.agents import load_corpus
c = load_corpus(); print('n=%d not_tradeable=%d' % (len(c), sum(1 for e in c if not e['tradeable_with_our_data'])))"
#   -> n=53 not_tradeable=17

# probe fallthrough
.venv/Scripts/python.exe -c "
from src.agents.base import probe_model_chain
ch=('openai/gpt-oss-120b','qwen/qwen3-32b','llama-3.3-70b-versatile')
print(probe_model_chain(ch, checker=lambda m: m==ch[1]))"
#   -> ('qwen/qwen3-32b', ['openai/gpt-oss-120b', 'qwen/qwen3-32b'])
```

---

## 4. What I could NOT verify, and why

- **The `live` (Groq) path.** No API key, and PRE_BUILD_TASKS T3 says the two
  named models may be deprecated (sources conflict). The code reads the chain
  from `config.LLM_MODEL_CHAINS`, probes with `groq.Groq().models.retrieve`, and
  walks the chain on failure — but **this was never run against the real API**.
  The `_groq` / `_ollama` dispatch methods are marked `# pragma: no cover`.
  First real run should confirm: (a) which chain entry is actually live, (b) that
  Groq returns `usage.completion_tokens` (the accounting assumes it does), (c)
  that `response_format={"type":"json_object"}` is honoured by the chosen model.
- **The `offline` (Ollama) path.** Same — wired, not run. Needs a local Ollama
  with one of `qwen2.5-7b` / `llama3.1` / `phi3` pulled.
- **Real prompt-cache behaviour on Groq.** The static-prefix split is in place
  and mock-verified (`cached_tokens` grows, billed does not re-charge the
  prefix), but whether Groq's cache actually zero-rates those tokens is a Groq
  implementation detail I could not confirm. If it does not, TPD is consumed
  faster than the projection and the ~20-thesis/day ceiling drops.
- **Token estimate accuracy.** `estimate_tokens` is the 4-chars/token rule of
  thumb. Real tokenisation will differ ±20%. The budget is checked against the
  *estimate* before the call; live mode reconciles with `usage` after. A
  systematic under-estimate could let a run cross the real TPD cap by a few
  percent before `BudgetExhausted` fires.
- **Whether ~40 corpus entries is "enough" for the novelty check.** The spec
  asked for ~40; I wrote 53. Retrieval quality on real family/keyword queries
  was spot-checked, not systematically evaluated.

---

## 5. Failures and open issues

- **No functional failures.** P8: 34/34. Full P0–P8 suite: **242 passed** (313.61s), no regressions.
- **Repair-round budget check.** On a schema-validation failure the repair
  re-dispatch bills tokens and `commit`s them but does **not** call
  `budget.check` first — so a repair can push `used` a few hundred tokens past
  the cap. Rare (mock never triggers it; live only on malformed JSON) and small.
  Fix if it matters: check before the repair dispatch too.
- **`build_agents` shares one `TokenBudget` per tier by object identity.** If a
  caller passes `large_budget=`/`small_budget=` they get shared correctly; if
  they construct agents individually via the classes, each gets its own budget
  and the "run-wide TPD" property is lost. P10 must use `build_agents`.
- **Mock Judge promotes at `iteration >= 3` regardless of metrics.** This is a
  deliberate loop-terminator for offline tests, not a real policy. The real
  Judge prompt says "stop once the variant budget is nearly spent"; P10 owns the
  actual variant cap enforcement.
- **`known_defects`-style disclosure for the corpus:** a handful of entries
  (`credit / distress risk`, `retail attention`) note a *partial* price-based
  proxy exists but are still marked `tradeable_with_our_data: false` because the
  canonical mechanism needs data we lack. That is a judgement call (see §7).

---

## 6. Anything that contradicts the spec

- **`config.py` was modified** (a P0 file, already signed off) to add the LLM
  block. Section 0.2 lists `langgraph`/`langchain-core`/`langchain-groq` as
  "Phases 8/10 only" and Phase 8 says "read the model ID from config", so config
  is the right home — but P0 shipped without any LLM constants, exactly as it
  shipped without `validate_card` (which P7 also had to add). The change is
  purely additive. If the owner wants it in a separate `src/agents/llm_config.py`
  instead, that is a mechanical move.
- **`langgraph` / `langchain-*` are not used in P8.** The spec allows them for
  "Phases 8/10". P8 is just the agents + the call path; the Groq call uses the
  `groq` SDK directly (simpler, fewer moving parts for a demo). LangGraph is a
  P10 (orchestration) concern. `groq` is a transitive dependency of
  `langchain-groq`, so no new top-level dependency was added. Flag if you want
  `langchain_groq.ChatGroq` used instead.
- **T3 says "Planner · Brief · Reflection = 3 calls"** — I read "Brief" as the
  Librarian's brief (agent 2), so those three roles are 1 call each per thesis.
  Consistent with the projection.
- **Model chains:** the small-tier chain ends with `llama-3.3-70b-versatile` as a
  last resort (the spec's table only lists `openai/gpt-oss-20b → llama-3.1-8b-instant`
  for the cheap roles). Added because if *both* small models are dead, falling to
  a working large model beats failing the run. Remove if you'd rather it hard-fail.

Nothing else contradicts the spec.

## 7. Decisions I made that the spec left open

1. **Three modes, `mock` the default.** `LLM_MODE ∈ {mock, live, offline}`.
   `mock` (canned, offline, no key) is the default so `pytest` and a laptop demo
   Just Work; `live` = Groq; `offline` = Ollama. The spec names `LLM_MODE=mock`
   and `OLLAMA_HOST` but not the full set.
2. **`TokenBudget` is per model *tier*, shared across roles, and lives in the
   `LLMClient`** (not a global singleton). `build_agents` wires one `large` and
   one `small` budget so "TPD exhausted" is genuinely run-wide (T3: limits are
   per-organisation). Auto-rolls over at local midnight; `to_dict`/`from_dict`
   for P10's checkpoint.
3. **Static-prefix caching is opt-in per call** via `static_prefix=` (must be a
   literal prefix of the prompt). Billed once per client, then counted in
   `cached_tokens`. The prompt files carry a `=== DYNAMIC ===` marker and every
   agent passes the static half. Whether Groq actually zero-rates it is
   unverified (§4).
4. **Economics does a structural pre-check before spending a call.** Any blank
   rubric element → immediate `reject`, `used_llm=False`. The spec says "missing
   any element → reject"; doing it in code makes it deterministic and free, and
   the acceptance test (missing `counterparty` → reject) then does not depend on
   mock behaviour.
5. **The Coder validates its own formula under the strict P5 grammar** and gets
   **one** repair round, then raises `CoderError`. The spec says "Coder output
   parses under P5's parser"; enforcing it in the agent (not just hoping) seemed
   the intent.
6. **The Red-Team agent silently drops any test name not on the 11-menu** and
   records them in `dropped_off_menu`. An LLM will occasionally invent a test;
   the menu is the contract, so hallucinations are filtered, not errored.
7. **Corpus: 53 entries, 17 non-tradeable, controlled 10-value `family`
   vocabulary** (`momentum, reversal, volatility, liquidity, microstructure,
   seasonality, trend, fundamental, sentiment, size`). `horizon_days` is a
   free-form string (ranges like `"20-60"` per the spec example). Each entry has
   `fields_needed` and, for non-tradeable ones, a `why_not` string — extra keys
   the validator ignores but a human reviewer will want.
8. **`tradeable_with_our_data` is judged against the canonical mechanism.**
   PEAD, value, profitability, accruals, issuance, F-score, dividend yield, R&D,
   short interest, analyst dispersion, media/search sentiment, fund breadth,
   options skew, distress, earnings-premium, retail-attention = `false` (need
   fundamentals / analyst / short / options / news). Net-issuance is `false`
   *and* flagged because we deliberately do not use `sharesOutstanding` (P2's
   look-ahead trap). A few of these have a weak price-based proxy — I still
   marked them `false` so the Librarian steers the Hypothesis agent toward the
   ~36 it can actually build cleanly.
9. **`mock_fixtures.COMPLETION_TOKENS`** are set to the T3 "tokens/call" figures
   (Coder 1,700→1,400, Judge 1,400→1,100 to leave room for the once-billed static
   prefix) so a full mock thesis measures **28,010** tokens — 5.7% over the
   26,500 projection, comfortably inside the 2× acceptance band. These numbers
   only affect the mock; live mode uses real `usage`.
10. **Mock Judge promotes on `rank_ic ≥ 0.02` OR `iteration ≥ 3`.** A pure loop
    terminator for offline runs. The real decision is the LLM's.
11. **`groq` SDK used directly, not `langchain_groq`.** See §6. LangGraph is
    deferred to P10 where the graph actually lives.
12. **Determinism:** `numpy`/`random` seeded in `base.py`; mock fixtures are pure
    functions of the prompt; `commit_preregistration` accepts an injectable
    clock so hashes are reproducible in tests. `datetime.now(timezone.utc)` in
    production.
