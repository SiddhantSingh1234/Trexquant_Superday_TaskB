# Dashboard Phase D0 handoff — Scaffolding and shared contracts

## 1. What was built

| File | Lines | Purpose |
|---|---:|---|
| `dashboard/__init__.py` | 1 | package marker |
| `dashboard/Home.py` | 42 | D0 landing-page scaffold (`streamlit run` entrypoint); D2 fills the body |
| `dashboard/build_cache.py` | 340 | `@builder(name)` registry (26 builders), CLI (`--only/--heavy/--check/--list`), `_manifest.json` writer, **two fully-implemented reference builders** (`corpus_family_counts`, `agents_token_budget`) + 24 schema-correct stubs |
| `dashboard/README.md` | 70 | run commands + phase map + builder/layout reference (skeleton) |
| `dashboard/pages/01_Universe.py … 14_Build_Log.py` | 14 × 12 | one-line page stubs (header + "built in D\<n\>" info); one file = one sidebar entry |
| `dashboard/lib/__init__.py` | 6 | package marker + import-rule note |
| `dashboard/lib/ui.py` | 92 | **fully implemented** — `page_header`, `section`, `source_note`, `pending_banner`, `data_missing`, `stale_banner`, `status_pill` |
| `dashboard/lib/fixtures.py` | 330 | **fully implemented** — `CACHE_SCHEMAS` (26 entries, every §0.6 file), `fake_cache`, `fake_cards`, `fake_loop_generations`, `install_fake_cache` |
| `dashboard/lib/data.py` | 400 | **fully implemented** cache layer (`available`, `cache_manifest`, `load_cache`, `try_cache`, `cache_staleness`) + `_readonly_sqlite` + all project-data readers (sliced/columnar) + all SQLite/JSON store readers |
| `dashboard/lib/charts.py` | 300 | **fully implemented** — `PALETTE`, `TEMPLATE` (registered), 16 builders; `coverage_chart` fits an OLS line via `numpy.polyfit` |
| `dashboard/lib/flow.py` | 45 | signatures + `DIAGRAMS` tuple + `region_dates()` implemented from `src.config.SPLITS`; `render` / `data_regions_timeline` raise `NotImplementedError(name)` |
| `dashboard/lib/narrative.py` | 40 | signatures + `BLOCKS` tuple; `block` raises `NotImplementedError(name)` |
| `dashboard/lib/engine.py` | 110 | `ensure_panel()` fully implemented; `dsr` / `expected_max_sr` thin passthroughs to `src.gates`; `run_backtest` / `run_redteam_ui` implement the `split=="holdout"` rejection; `eval_formula` / full `run_backtest` / `leaky_signal` raise `NotImplementedError` (D4/D5) |
| `.streamlit/config.toml` | 16 | dark theme, wide layout, `primaryColor` = `PALETTE['accent']` (`#4C9BE8`) |
| `requirements-dashboard.txt` | 5 | `streamlit`, `plotly`, `altair`, `graphviz` (the complete allowed list) |
| `tests/test_dash_p0_scaffold.py` | 300 | 35 tests — see §2 |

New deps installed into `.venv`: `streamlit 1.63.0`, `plotly 7.0.0`, `altair 6.2.2`, `graphviz 0.21` (python binding only; no system Graphviz binary needed — `st.graphviz_chart` accepts DOT).

## 2. Acceptance criteria — every one, with a MEASURED value

| # | Criterion | Result | Measured value |
|---|---|---|---|
| 1 | `streamlit run dashboard/Home.py` starts headless, stays up ≥ 5 s, serves HTTP 200 on `/` | ✅ PASS | process up 6 s, `curl /` → **HTTP 200**; log: "Uvicorn server started on 127.0.0.1:8599" |
| 2 | `build_cache.py --list` prints ≥ 20 builder names | ✅ PASS | **26 builders** listed (2 real + 24 stubs; `zoo_leaderboard` / `prices_yf_crosscheck` tagged HEAVY) |
| 3 | `build_cache.py --only corpus_family_counts,agents_token_budget` writes 2 parquets + manifest; `--check` passes | ✅ PASS | wrote `corpus_family_counts.parquet` (10 rows), `agents_token_budget.parquet` (8 rows), `_manifest.json`; `--check` → `--check: OK`, **exit 0** |
| 4 | `pytest tests/test_dash_p0_scaffold.py -q` passes | ✅ PASS | **35 passed in 7.39s** |
| 5 | signature-truth: `run_redteam.split` is KEYWORD_ONLY, 2nd positional is `tests`; `walk_forward` has `start`/`end`, no `split`; `src.memory.lineage_path` not module attr but is `Memory` method | ✅ PASS | `test_run_redteam_signature_truth`, `test_walk_forward_signature_truth`, `test_lineage_path_is_method_not_module_function` all green |
| 6 | no `lib` module imports `src` except `engine.py` (any), `fixtures.py` (`src.contracts`), `flow.py` (`src.config`) — asserted by AST parse | ✅ PASS | `test_import_fence` (7 params) green; `data.py` uses a faithful in-module **port** of `validate_card` (0/18 decision mismatches, see §6) so it stays `src`-free |
| 7 | `fake_cache(name)` returns exact §0.6 columns+dtypes for **all** names | ✅ PASS | `test_fake_cache_all_names` iterates all 26 schemas |
| 8 | `flow.render` / `narrative.block` raise `NotImplementedError` (not `AttributeError`) for an un-done name | ✅ PASS | `test_flow_render_not_implemented`, `test_narrative_block_not_implemented` |
| 9 | `engine.ensure_panel()` returns a bool | ✅ PASS | returns `True` (real panel present: `data/panel/{features,labels}.parquet`) |
| 10 | `engine.run_backtest(..., split="holdout")` raises | ✅ PASS | raises `PermissionError`; `run_redteam_ui(..., "holdout")` also raises |
| 11 | `charts.coverage_chart(fake_cache("universe_daily_coverage"))` → `(Figure, dict)` with `slope_per_year` key | ✅ PASS | returns `(go.Figure, {'slope_per_year': 0.036, 'verdict': 'FLAT'})`; a synthetic +20/yr series → `verdict='SLOPING'`, slope 19.98 |
| 12 | `fixtures.fake_cards(2)` → 2 dicts both passing `src.contracts.validate_card` | ✅ PASS | `test_fake_cards_valid` |
| 13 | `_readonly_sqlite` never opens a path under `data/` for write | ✅ PASS | `test_readonly_sqlite_does_not_mutate_source`: source db `st_mtime_ns` **unchanged** after a read; real `data/ledger.db` mtime unchanged after `sqlite_master` read |
| 14 | `data/dashboard/` is the only new data path written | ✅ PASS | writes go to `data/dashboard/*.parquet`, `data/dashboard/_manifest.json`, `data/dashboard/_snap/` (snapshots); nothing else under `data/` touched (verified via `git status`) |
| 15 | reference builder numbers sane | ✅ PASS | `agents_token_budget`: Σ calls/thesis = **16.6**, Σ tokens/thesis = **26,520** (≈ 26,500 T3 projection); `corpus_family_counts`: **53** anomalies across **10** families, `n_tradeable + n_not_tradeable == n` for every row |

## 3. Verify it yourself

```
pip install -r requirements-dashboard.txt        # or: .venv\Scripts\pip install ...

python dashboard/build_cache.py --list            # 26 builders
python dashboard/build_cache.py --only corpus_family_counts,agents_token_budget
python dashboard/build_cache.py --check           # prints "--check: OK", exit 0

python -m pytest tests/test_dash_p0_scaffold.py -q # 35 passed

streamlit run dashboard/Home.py --server.headless true
#   open http://localhost:8501 — Home renders the D0 scaffold + an
#   "Artifact availability (live)" expander; the sidebar lists all 14 pages,
#   each showing "This page is built in phase D<n>."
```

No screenshots saved — D0 has no real page content to shoot (every page is a
one-line stub by design). `reports/dash_shots/` is created empty for later phases.

## 4. What I could NOT verify, and why

- **Cold-load < 3 s per page**: not meaningful yet — pages are stubs. Home.py
  renders in well under 3 s (it only calls `data.available()` + `cache_staleness()`).
- **`--heavy` builders**: `zoo_leaderboard` / `prices_yf_crosscheck` are registered
  as stubs only (D0 scope explicitly excludes them; D1/D3/D4 own the real bodies).
- **Full project test suite**: `python -m pytest -q` was still running past the
  120 s shell limit when this was written (the P8/P10 agent/loop tests are slow).
  D0 adds no `src/` changes, so no regression is expected; the D0 test file is
  self-contained and green. **Owner should run the full suite once to confirm.**
- **`install_fake_cache`**: implemented but only smoke-exercised indirectly
  (its refuse-on-real-manifest branch is not unit-tested).

## 5. Failures and open issues

- None blocking. The em-dash in stub `note` strings renders as `�` in a cp1252
  Windows console — cosmetic only; replaced with `-` in the committed version.
- `data/dashboard/_snap/` accumulates one `.db` snapshot per distinct source db
  read. It is a cache dir under the allowed write path; a future phase may want a
  `--clear-snap` housekeeping flag. Not needed for D0.

## 6. Anything that contradicts this plan

- **§0.4 `load_cards` says "(validated best-effort)"** implying
  `src.contracts.validate_card`. But acceptance criterion "no `lib` module imports
  from `src` except engine/fixtures/flow" is asserted by an **AST parse of every
  import statement**, which a function-local `from src.contracts import ...` in
  `data.py` would still trip. Resolved by giving `data.py` a **faithful,
  dependency-free port** of `src.contracts.validate_card` (`_card_looks_valid`:
  same 16 top-level keys, same nested key sets for `thesis` / `pre_registered` /
  `complexity` / `lineage`, same `verdict` vocabulary, same
  `pre_registered.sign ∈ {−1,+1}` and `provenance.fields_used` rules).
  **Verified identical**: 0 accept/reject mismatches vs `validate_card` across 18
  cases (valid cards with all 4 verdicts, fixture cards, and 8 deliberately-broken
  variants exercising each failure branch). A page needing the authoritative
  object gets it via `lib.engine` / `lib.fixtures`. Flagged here as the plan text
  and the import fence are in tension; the port must be kept in sync with
  `src/contracts.py`.
- `fixtures.py` §0.4 lists `fake_cards` **twice** (once with `(n, seed)`, once
  with `(n=3)`). Implemented once as `fake_cards(n=3, seed=42)`.

## 7. Decisions I made that the plan left open

1. **`data.py` stays `src`-free** (see §6) via a faithful in-module port of
   `validate_card`, verified to give an identical accept/reject decision.
2. **PALETTE**: accent `#4C9BE8` (blue), accent2 `#F2A65A` (amber), pos `#3FB984`,
   neg `#E5606B`, 8-colour `cat`, 7-step `seq`, on `bg` `#0E1117`. `TEMPLATE` is a
   registered Plotly template `"alphafactory"` (transparent paper/plot so it sits
   on the Streamlit theme). D8 does the final light/dark legibility pass.
3. **`build_cache.py` registers all 26 builder names in D0** (24 as stubs that
   emit an empty schema-correct parquet + `status:"no_source"`), so `--list` shows
   the full registry and a bare `build_cache.py` run never crashes before D1.
4. **`--check` iterates the manifest, not the registry** — a builder with no
   manifest row is "not built yet", not a failure. Staleness is skipped for
   `status:"no_source"` rows (an intentionally-empty cache cannot be "stale").
5. **`_readonly_sqlite` snapshot dir** = `data/dashboard/_snap/` (under the one
   allowed write path). Copies `-wal` / `-journal` / `-shm` sidecars too.
6. **Path bootstrap**: every `pages/*.py` and `Home.py` prepend the project root
   to `sys.path` (4 lines) so both `dashboard.lib.*` and `src.*` (engine) resolve
   regardless of how Streamlit sets the entrypoint dir.
7. **`agents_token_budget` projection** hard-codes the PRE_BUILD_TASKS.md T3
   FINDING-2 per-role `(calls_per_thesis, tokens_per_call)` table but reads
   `tier` **live** from `src.config.LLM_ROLE_TIER` at build time. The T3 *token*
   numbers are a measured projection, not a config value, so copying them is not
   the "never copy a config value" violation.
8. **`load_universe_membership` / `load_universe_stats` / `load_liquidity_ranks`
   read whole** — they are small (≤ 1.6 M rows, one boolean/float column set, a
   few MB). Only `ohlcv` / `features` / `labels` are guarded against a full read.

## STOP — awaiting sign-off before D1.
