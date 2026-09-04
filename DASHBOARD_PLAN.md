# DASHBOARD IMPLEMENTATION PLAN — Alpha Factory Dashboard

> **How to use this document.** The dashboard is cut into **9 phases** (`D0`–`D8`). Each phase spec is
> self-contained: what it is, its exact inputs and outputs (with file/function contracts), its steps,
> its acceptance tests, and an explicit scope fence.
>
> **An agent executing a phase needs only: (a) Section 0 of this document, and (b) that phase's spec.**
> It does **not** need to know how any other phase was implemented — only the *contract* of the `lib/`
> modules and cache files it reads and writes. Every phase can be built and self-tested with the
> **fixture generators** in `dashboard/lib/fixtures.py` even if the cache builder (`D1`) has not run.
>
> Companion documents (background, not required to execute a phase):
> `IMPLEMENTATION_PLAN.md` (the system this dashboard visualises — Section 0 especially) ·
> `FLOW_EXPLAINED.md` (plain-English walkthrough) · `INITIAL_PLAN.md` (architecture) ·
> `reports/p0_handoff.md` … `reports/p10_handoff.md` (what each system phase produced).

> **Build state this plan assumes (2026-09-04): P0–P10 are built and signed off.** P10 (`src/loop.py`,
> the orchestration graph) landed after this plan's first draft — `10_The_Loop.py` is a **live data
> page**, not a placeholder. P11 (demo run + bad examples) and P12 (system evaluation) are in flight
> *while this dashboard is being built*; §0.8.1 and the parallelism note at the end of EXECUTION ORDER
> are what make that concurrency safe. Never hard-code a phase-status list — derive it from
> `reports/p*_handoff.md`.
>
> Copy-paste briefs for executing agents: `DASHBOARD_PHASE_PROMPTS.md`.
>
> **History.** An earlier draft split this into 15 micro-phases for maximum agent parallelism. It was
> consolidated to 9: several pages that share a data source and a chart vocabulary are now built
> together (see the phase map in "EXECUTION ORDER"). Nothing was dropped.

---

# SECTION 0 — SHARED CONTRACTS

**Every phase agent must read this section. Nothing else outside your own phase is required.**

## 0.1 What this is (30 seconds)

A **local, tabbed web dashboard** that presents the entire Alpha Factory build — the system that uses
AI agents to invent, test and filter stock-market alpha signals (see `IMPLEMENTATION_PLAN.md` §0.1).

It has two jobs:

1. **Explain how the system works** — the nine-stage pipeline, the gates, the three budgets, the five
   failure modes — with flowcharts and prose, as a companion to the 20-minute presentation.
2. **Let a reviewer explore the evidence** — the survivorship-free universe, the feature panel, the
   statistical gates, the trial ledger, the red-team, the Alpha Cards — with interactive charts and,
   where it matters, live computation (run a backtest, run the red-team, compute a Deflated Sharpe).

The dashboard is **read-only over the project's data**. It never mutates `data/` except its own cache
directory `data/dashboard/`. It never calls a paid API and never calls a live LLM.

## 0.2 Environment and dependencies

- **Python 3.11+**, Windows (`E:\Trexquant_Superday`). Prefer `pathlib`; never hard-code separators.
- **Framework: Streamlit** (multipage app). Decision recorded in §0.11.
- **Allowed new dependencies (this is the complete list — do not add others):**
  `streamlit`, `plotly`, `altair`, `graphviz` (the Python binding; `st.graphviz_chart` also accepts a
  DOT string and needs no system binary), plus everything already in the project's `requirements.txt`
  (`pandas`, `numpy`, `pyarrow`, `scipy`, `statsmodels`, `matplotlib`, …).
- **Explicitly NOT allowed:** any React/Next.js frontend, any separate API server (FastAPI/Flask), any
  database server, any vector DB, Docker, a paid data source, a paid API, a live LLM call. `yfinance`
  may be imported only if a cache builder needs it and only behind a `--heavy` / opt-in flag — never on
  a page load.
- **No network access on any page load.** A cache builder (`D1`) may hit the network only if a specific
  builder documents it and it is opt-in.
- New deps go in **`requirements-dashboard.txt`** (a separate file), not the project `requirements.txt`.

## 0.3 Repository layout

```
E:\Trexquant_Superday\
├── dashboard/
│   ├── Home.py                       # D2 — "Start here": narrative + master flowchart
│   ├── build_cache.py                # D1 — precompute small aggregates into data/dashboard/
│   ├── README.md                     # D0 skeleton, D8 completed
│   ├── pages/
│   │   ├── 01_Universe.py            # D3
│   │   ├── 02_Prices.py              # D3
│   │   ├── 03_Feature_Panel.py       # D3
│   │   ├── 04_Backtester.py          # D4
│   │   ├── 05_Operators_and_Zoo.py   # D4
│   │   ├── 06_Gates_and_Ledger.py    # D5
│   │   ├── 07_Memory.py              # D6
│   │   ├── 08_LLM_Agents.py          # D6
│   │   ├── 09_Red_Team.py            # D5
│   │   ├── 10_The_Loop.py            # D7
│   │   ├── 11_Alpha_Cards.py         # D7
│   │   ├── 12_System_Evaluation.py   # D7
│   │   ├── 13_Bad_Examples.py        # D7
│   │   └── 14_Build_Log.py           # D8
│   └── lib/
│       ├── __init__.py
│       ├── data.py                   # D0 signatures; cached loaders + the cache readers
│       ├── charts.py                 # D0 — shared Plotly/Altair builders + PALETTE
│       ├── flow.py                   # D0 stubs; D2 implements the 6 diagrams
│       ├── narrative.py              # D0 stubs; D2 implements the prose blocks
│       ├── ui.py                     # D0 — page_header, pending_banner, data_missing, source_note
│       ├── fixtures.py               # D0 — schema-correct fake data for every cache file
│       └── engine.py                 # D0 signatures + ensure_panel; D4/D5 fill the compute helpers
├── data/
│   └── dashboard/                    # D1 output — small precomputed parquets + _manifest.json
│       └── _manifest.json
├── .streamlit/
│   └── config.toml                   # D0 skeleton, D8 finalised — theme
├── reports/
│   ├── dash_p0_handoff.md … dash_p8_handoff.md
│   └── dash_shots/                   # screenshots referenced by handoffs
├── requirements-dashboard.txt        # D0
└── tests/
    ├── test_dash_p0_scaffold.py … test_dash_p8_*.py   # one per phase, plain pytest, no network
    └── test_dash_e2e.py              # D8 — imports every page, asserts no import-time exception
```

## 0.4 The `lib/` module contracts — **build exactly these signatures**

Every function that reads data is decorated `@st.cache_data` unless noted. `Path` = `pathlib.Path`.
`DF` = `pandas.DataFrame`.

### `dashboard/lib/data.py`

```python
PROJECT_ROOT: Path            # E:\Trexquant_Superday
DATA_DIR: Path                # PROJECT_ROOT / "data"
CACHE_DIR: Path               # DATA_DIR / "dashboard"
REPORTS_DIR: Path             # PROJECT_ROOT / "reports"

def available() -> dict[str, bool]:
    """Which real artifacts exist. Keys (exact) and what each one tests:
      'universe'  -> data/universe/membership.parquet
      'prices'    -> data/prices/ohlcv.parquet
      'panel'     -> data/panel/features.parquet AND labels.parquet
      'ledger'    -> data/ledger.db has >= 1 row in `trials`
      'memory'    -> data/memory.db has >= 1 row in `card_index`
      'lessons'   -> data/lessons.db has >= 1 row in `lessons`
      'bandit'    -> data/bandit_state.json parses and has >= 1 family
      'corpus'    -> data/corpus/anomalies.json
      'cards'     -> artifacts/cards/*.json is non-empty
      'loop'      -> data/loop_checkpoint.db exists AND its `run_state` table
                     has the id=1 row (i.e. a real run happened, not just an
                     initialised file)
      'evaluation'-> reports/p12_system_evaluation.md exists (P12's deliverable;
                     the page also globs reports/p12_*.parquet / *.csv if P12
                     emits any, but must not require a schema P12 has not
                     committed to)
    A count-based key is False when the store exists but is empty — that is the
    state the pages must render honestly."""

def cache_manifest() -> dict:
    """Parsed data/dashboard/_manifest.json, or {} if absent."""

def load_cache(name: str) -> DF:
    """Read data/dashboard/<name>.parquet. Raise FileNotFoundError with a message
    naming the exact `python dashboard/build_cache.py --only <name>` command if absent."""

def try_cache(name: str) -> DF | None:
    """load_cache but returns None instead of raising — page shows an empty state."""

# Direct project-data readers (sliced; never load a raw parquet whole)
def load_universe_membership() -> DF          # date, symbol, in_universe
def load_universe_stats() -> DF               # date, n_members, median_turnover, turnover_cutoff_200
def load_liquidity_ranks() -> DF              # month_end(ns), symbol, liquidity_rank(int),
                                              # trailing_turnover(f64)  <- exact column names;
                                              # NOT 'rank'/'turnover'.  src.redteam test 11
                                              # (universe_edge) takes this frame verbatim.
def load_symbols() -> dict                    # symbols.json parsed
def load_splits() -> dict                     # panel/splits.json parsed
def load_ohlcv(symbols: list[str] | None = None,
               start: str | None = None, end: str | None = None,
               columns: list[str] | None = None) -> DF   # pyarrow-filtered slice
def load_features(symbols: list[str] | None = None,
                  columns: list[str] | None = None) -> DF
def load_labels(symbols: list[str] | None = None,
                columns: list[str] | None = None) -> DF
def load_corporate_actions() -> DF
def load_delivery(symbols: list[str] | None = None) -> DF

# SQLite / JSON stores
def load_ledger_trials() -> DF                # trials table as a frame
def load_holdout_peeks() -> DF
def load_lessons() -> DF                      # lessons.db → flat frame
def load_bandit() -> DF                       # bandit_state.json → one row per family
def load_cards() -> list[dict]               # every artifacts/cards/*.json (validated best-effort)
def load_corpus() -> DF                       # data/corpus/anomalies.json → one row per entry
def load_handoff(phase: str) -> str           # reports/<phase>_handoff.md text, "" if absent

# P10 loop run state (see §0.5 `src.loop`)
def load_loop_run_state() -> dict | None
    """The `run_state` id=1 JSON from data/loop_checkpoint.db, or None if the loop
    has not run. Keys: run_id, generations (list of the per-generation outcome
    dicts), next_gen, incomplete_gen, accepted_card_ids, t_stat_bar,
    min_marginal_ic, large_used, small_used, budget_day.
    Read through `_readonly_sqlite` (§0.8) — a P11 run may hold this file open."""

def load_loop_generations() -> DF
    """load_loop_run_state()['generations'] flattened to one row per generation.
    Empty schema-correct frame when the loop has not run."""
```

### `dashboard/lib/charts.py`

```python
PALETTE: dict          # 'accent','accent2','pos','neg','grid','text','muted', 'cat' (list[str]),
                       # 'seq' (list[str]), 'bg'
TEMPLATE: str          # a registered plotly template name — apply to every figure

def kpi_row(items: list[tuple[str, str, str | None]]) -> None
    # renders st.columns of metric tiles: (label, value, delta|None)

def line(df, x, y, color=None, title="", y_title="", ref: float | None = None) -> "plotly.graph_objects.Figure"
def bar(df, x, y, color=None, title="", horizontal=False, sort=None) -> Figure
def hist(series, title="", bins=40, x_title="") -> Figure
def violin(df, x, y, title="") -> Figure
def box(df, x, y, title="") -> Figure
def heatmap(matrix_df, title="", zmid=None, colorscale=None) -> Figure    # matrix_df is a pivoted DF
def stacked_area(df, x, y, color, title="") -> Figure
def candlestick(df, title="", markers: DF | None = None) -> Figure        # df: date,open,high,low,close
def gantt(df, start="start", end="end", label="symbol", color=None, title="") -> Figure
def scatter(df, x, y, color=None, trend=False, title="") -> Figure
def gauge(value: float, maximum: float, label: str, thresholds: dict | None = None) -> Figure

# Purpose-built
def coverage_chart(daily: DF, target: int = 200) -> tuple[Figure, dict]
    # daily: date, n_members (or n_panel). Returns (figure with a target reference line
    # AND a fitted OLS trend line, {'slope_per_year': float, 'verdict': 'FLAT'|'SLOPING'})
    # verdict is 'FLAT' if abs(slope_per_year) < 3 names/year else 'SLOPING'
def decay_curve(by_horizon: dict[int, float], title="RankIC decay") -> Figure
def equity_curve(daily_returns: "pd.Series", title="Long-short equity") -> Figure
def ic_bar(df, feature_col="feature", ic_col="rank_ic", err_col=None, noise_band: float | None = None) -> Figure
```

### `dashboard/lib/flow.py`

```python
DIAGRAMS: tuple[str, ...] = (
    "pipeline",          # the 9-stage flow (INITIAL_PLAN §3 / FLOW_EXPLAINED Part 2)
    "loop_graph",        # the P10 LangGraph state machine, with the inner refine loop
    "gate_b",            # orthogonalize → novelty → statistics → rationed peek
    "data_lineage",      # raw NSE files → ohlcv → {universe, panel} → backtester → gates → cards
    "phase_dag",         # P0→P2→P1→P3→P4→P6→P10→P11→P13 with the P5/P7/P8/P9 fan-out
    "card_lifecycle",    # an Alpha Card gaining a section at each stage
)

def render(name: str) -> "graphviz.Digraph" | str:
    """Return something st.graphviz_chart accepts (a Digraph or a DOT string).
    D0 ships this raising NotImplementedError(name); D2 implements all six."""

def data_regions_timeline() -> "plotly.graph_objects.Figure":
    """A horizontal timeline of warmup/train/val_a/val_b/holdout from
    IMPLEMENTATION_PLAN.md §0.4. D0 stub, D2 implements."""

def region_dates() -> dict:   # {'warmup':(start,end), ...} — from src.config.SPLITS. D0 implements.
```

### `dashboard/lib/narrative.py`

```python
BLOCKS: tuple[str, ...] = (
    "one_liner", "nine_stages", "alpha_card", "three_budgets", "four_regions",
    "five_failures",            # returns a Markdown TABLE
    "sqrt_2lnN",                # the over-searching explainer + the measured P(t>3) table
    "pre_registered_sign", "variant_cap_fresh_fold", "gate_b_order",
    "novelty_claims",           # the 4 claims, 2 conceded, with citations
    "weak_points", "walkthrough",   # "one idea walked all the way through" (FLOW_EXPLAINED Part 4)
    "build_status",             # P0–P13 with current status
    "nav_guide",
)

def block(name: str) -> str:
    """Return Markdown. Every block ends with a trailing '_Source: <doc> <section>_' line.
    D0 ships this raising NotImplementedError(name); D2 fills all."""
```

### `dashboard/lib/ui.py`  (fully implemented in D0)

```python
def page_header(title: str, subtitle: str = "", phase_tag: str | None = None) -> None
    # a consistent H1 + caption; phase_tag renders a small "built in D3" chip

def pending_banner(what: str, blocked_on: str) -> None
    # st.warning: "<what> is design-only until <blocked_on> ships. The layout below is final;
    #  the live data will populate automatically once the artifact exists."

def data_missing(artifact: str, how_to_build: str) -> None
    # st.info with the exact command; caller then st.stop()

def section(title: str, help_text: str = "") -> None
def source_note(text: str) -> None            # a small grey caption: "Source: data/universe/…"
def status_pill(state: str) -> str            # 'done'|'pending'|'partial' → a coloured md string

def stale_banner(names: list[str]) -> None
    # st.warning when a cache is older than its source (§0.8.1 #3) — expected
    # while P11/P12 are running: "cache is N sources stale — run
    # `python dashboard/build_cache.py`". No-op on an empty list.
```

### `dashboard/lib/fixtures.py`  (fully implemented in D0)

```python
CACHE_SCHEMAS: dict[str, dict]     # name -> {col: dtype-string} for EVERY file in §0.6

def fake_cache(name: str, rows: int = 200, seed: int = 42) -> DF
    """A schema-correct random frame for any cache file in §0.6. Page phases use
    this to build and test before D1 has run."""

def fake_cards(n: int = 1, seed: int = 42) -> list[dict]
    """`n` schema-valid Alpha Cards — a thin wrapper over
    `src.contracts.make_fake_card(seed=…, verdict=…)`, varying the seed per card
    and cycling `verdict` through accept/reject/revise so a gallery has something
    to filter. Every returned card passes `src.contracts.validate_card`.
    Used by D6 (lineage preview) and D7 (`11_Alpha_Cards` sample-card toggle)."""

def fake_loop_generations(n: int = 6, seed: int = 42) -> DF
    """A plausible `loop_generations` frame (§0.6) for previewing
    `10_The_Loop.py` before a real run exists."""

def fake_cards(n: int = 3) -> list[dict]      # via src.contracts.make_fake_card
def install_fake_cache(names: list[str] | None = None, force: bool = False) -> None
    """Write fake_cache(...) frames into data/dashboard/ for a from-scratch demo.
    Prints a loud warning; refuses if a real manifest is present unless force=True."""
```

### `dashboard/lib/engine.py`  (signatures + `ensure_panel` in D0; compute helpers land with D4/D5)

```python
@st.cache_resource
def ensure_panel() -> bool:
    """Load data/panel/{features,labels}.parquet and call
    src.backtester.use_panel(...). Idempotent; also makes src.redteam / src.gates
    see the same panel. Returns False (and pages show data_missing) if the panel
    is absent."""

@st.cache_data
def eval_formula(formula: str) -> DF          # parse (strict) + evaluate → date×symbol signal   (D4)
@st.cache_data
def run_backtest(formula: str, split: str, horizon: int = 1, cost_bps: float = 0.0,
                 neutralize: str | None = None, extra_lag: int = 0) -> dict   # a Metrics dict   (D4)
@st.cache_data
def run_redteam_ui(formula: str, split: str = "val_a") -> dict                # (D5)
    """MUST call src.redteam.run_redteam with `split` and `ledger` as KEYWORDS
    (see the §0.5 signature warning) and MUST pass
    `liquidity_ranks=data.load_liquidity_ranks()` or test 11 silently degrades:
        run_redteam(sig, tests=None, split=split,
                    liquidity_ranks=data.load_liquidity_ranks(),
                    prices=data.load_ohlcv(columns=[...]),
                    ledger=Ledger(":memory:"))"""
@st.cache_data
def dsr(observed_sr: float, n_trials: int, sr_std: float,
        skew: float, kurt: float, n_obs: int) -> float                        # D0 (passthrough)
@st.cache_data
def expected_max_sr(n_trials: int, sr_std: float) -> float                    # D0 (passthrough)
def leaky_signal() -> DF                      # fwd_ret_1 as its own signal (for demos)            (D5)
```

> **Import rule.** `lib/engine.py` is the **only** module that imports *compute* from `src/`. Two
> narrow exceptions, both metadata-only and both asserted by the D0 test:
> `lib/fixtures.py` may import `src.contracts` (`make_fake_card` etc. — pure schema generators, no
> project data) and `lib/flow.py` may import `src.config` (`SPLITS`, for `region_dates()`).
> Pages import `lib/*`, never `src/*` directly — except `pages/05_Operators_and_Zoo.py` and
> `pages/08_LLM_Agents.py`, which may import `src.operators` / `src.ast_tools` / `src.zoo` /
> `src.config` / `src.agents` (metadata and parsing only — **no live LLM client is ever constructed**).
>
> **HOLDOUT guard.** `lib/engine.run_backtest` must reject `split == "holdout"` with a clear error.
> No page may score a signal on HOLDOUT (`IMPLEMENTATION_PLAN.md` §0.4 — it is sealed).

## 0.5 What the system exposes (the `src/` contracts you may rely on)

These exist and are signed off (`reports/p0`–`p10_handoff.md`). Treat as stable.

> ⚠️ **`src/config.py` is a living file** — it was last re-verified against the Groq API on
> 2026-09-04 and P11/P12 may extend it again. **Never copy a config value into dashboard code or
> prose**; read it at render time. The only place this rule was ever violated is called out in D6.

| Module | Useful surface |
|---|---|
| `src.config` | `SPLITS`, `VALID_REGIONS` (adds the composite `"train+val_a"`), `RANDOM_SEED`, `T_STAT_BAR`, `HOLDOUT_PEEK_BUDGET`, `MAX_VARIANTS_PER_THESIS`, `COST_BPS_DEFAULT`, `EMBARGO_DAYS`, `LLM_MODEL_CHAINS`, `LLM_ROLE_TIER`, `LLM_TPM`, `LLM_TPD_CAP`, `LLM_RPM`, **`LLM_RPD`**, **`LLM_MODEL_LIMITS`** (per-*model* measured TPM/RPD — better evidence than the per-tier table), `LLM_TOKENS_PER_THESIS_PROJECTION`, `AGENT_ROLES`, `LLM_MODE`, `split_mask()`, `assert_not_holdout()` |
| `src.contracts` | `validate_*`, `make_fake_ohlcv/features/labels/membership`, `validate_card`, `make_fake_card` |
| `src.universe` | `compute_selection(prices, as_of=None)`, `build_liquidity_ranks`, `overlap_diagnostic(membership)`, `monthly_turnover_rate`, `lookahead_check`, `CANARIES`, `HEAVYWEIGHTS`, `TARGET_N=200`, `SUPPLIED_CSV` / `NSE_CURRENT_LIST` (the two paths D7's Bad Example ① reconciles) |
| `src.backtester` | `backtest(signal, split, horizon=1, extra_lag=0, cost_bps=0.0, neutralize=None, subsample=None, purge_days=None, embargo_days=5, *, i_have_a_peek_token=False)` → Metrics; `use_panel(features, labels)`, `clear_panel()`, `purge_embargo_mask(...)`. **`i_have_a_peek_token` is the structural holdout tripwire** — `split="holdout"` without it raises inside `src`, which is why `engine.run_backtest` can never leak a peek even if a page tries. Never pass it `True`. `metrics["decay"]` is `dict[int, float]` (horizon → RankIC), the exact input `charts.decay_curve` wants. |
| `src.operators` | the operator functions + a registry; `src.ast_tools` — `parse(formula, strict=True)`, `canonical`, `fingerprint`, `complexity` → `{nodes,depth,free_params}`, AST node objects |
| `src.zoo` | `ZOO` (list of `{name,formula,canonical,fingerprint,source}`), `ZOO_BY_NAME`, `is_zoo_duplicate(formula, threshold=1.0)`, `demo_panel(...)` |
| `src.gates` | `deflated_sharpe_ratio(...)`, `dsr_from_ic_series(...)`, `expected_max_sharpe(n_trials, sr_std)`, `effective_trial_count(...)`, `orthogonalize(signal, book)`, `daily_rank_ic(signal, split, horizon, panel=None)`, `marginal_ic(signal, book, split="val_a", horizon=1, *, panel=None)`, **`walk_forward(signal, start, end, train_years=3, step_months=6, horizon=1, purge_days=None, embargo_days=5, *, book=None, panel=None)`** — takes **dates, not a split name**: map a region with `config.SPLITS[region]` first, `cscv_pbo(returns_matrix, n_blocks=8, purge_days=0)` — takes a `T × M` matrix, not a signal, `check_sign(pre_registered_sign, realized_sign)`, `gate_b(card, book, ledger, signal=None, *, split="val_a", horizon=None, do_holdout_peek=True, panel=None)` → `(verdict, reasons, audit)`. Thresholds live here as module constants: `MIN_MARGINAL_IC`, `DSR_MIN`, `PBO_MAX`, `MIN_DSR_SAMPLE` — read them, don't retype them. |
| `src.ledger` | `Ledger(db_path)` — `.n_trials()`, `.trial_records()`, `.trial_sharpes()`, `.holdout_peeks_used()`, `.holdout_peeks_remaining()`, `.holdout_peek_records()`; `assert_no_row_removal_sql()` |
| `src.memory` | `Memory(base_dir=…)`, `FormulaIndex`, `LessonStore`, `BanditState` (`.families()`, `.row(f)`, `.allocation()`), `AlphaCardStore`, `AcceptedBook` (`.factors()`, `.get_book()`, `.get_book_wide()`), `new_card(...)`, `FAMILIES`. ⚠️ **`lineage_path` is a METHOD, not a module function** — `Memory(...).lineage_path(card_id)` or `AlphaCardStore(...).lineage_path(card_id)`. `from src.memory import lineage_path` raises `ImportError`. |
| `src.redteam` | ⚠️ **Signature — read carefully.** `run_redteam(signal, tests=None, *, split="val_a", horizon=None, sign=1, thesis=None, formula=None, panel=None, prices=None, liquidity_ranks=None, ledger=None, thesis_id=None, formula_hash=None, canonical_ast=None)`. **`split` is KEYWORD-ONLY and `tests` is the 2nd positional** — `run_redteam(sig, "val_a")` silently passes the split string as the *test list*. Always call with keywords. **Pass `liquidity_ranks=`** (see `data.load_liquidity_ranks`) or test 11 `universe_edge` degrades to a no-op. Returns `{verdict, failed_tests, flagged_diagnostics, results, baseline, n_backtests, counts_as_trial}`; `REDTEAM_MENU` (11 names), `DECISIVE_TESTS` (5 names). |
| `src.agents` | `build_agents`, `load_corpus`, `retrieve`, `validate_corpus`, `RED_TEAM_MENU`, `commit_preregistration`, the eight agent classes; prompt files at `src/agents/prompts/*.txt`. ⚠️ **`AGENT_ROLES` is NOT exported here** — it lives in `src.config`. |
| `src.loop` **(P10 — built and signed off, `reports/p10_handoff.md`)** | `run_loop(...)` → `RunResult`; `RunResult` (`.status`, `.stopped_reason`, `.generations`, `.accepted_card_ids`, `.n_trials`, `.holdout_peeks_used`, `.t_stat_bar_final`, `.min_marginal_ic_final`, `.portfolio`, `.report_path`, `.state_digest`, plus the four invariant assertions `max_variant_count()` / `val_b_before_promote()` / `novelty_always_before_stats()` / `holdout_only_with_token()`); `build_graph(ctx, checkpointer)`, `RunContext`, `AlphaResearchState`; `portfolio_combine(memory, *, split="val_a", horizon=5, panel=None)` → `{status, n_accepted, individual_rank_ic, correlation_matrix, weights, combined_rank_ic, beats_best_individual}`; `curriculum_regimes(generation, every=3)`, `rolling_fdr(generations, window=6)`, `maybe_tighten_gates(...)`, `evaluate_signal(formula, panel)`, `build_price_panel(...)`, `synthetic_price_panel(...)`; constants `MAX_VARIANTS=20`, `FRESHFOLD_MIN_T=1.5`, `CURRICULUM_ROTATION`, `FDR_TIGHTEN_THRESHOLD=0.33`, `STOP_K_DEFAULT=3`; paths `DEFAULT_CHECKPOINT = data/loop_checkpoint.db`, `DEFAULT_REPORT = reports/p10_loop_report.md`. **The dashboard NEVER calls `run_loop`** — it reads the checkpoint (§0.8). |

## 0.6 The cache-file contract  (`D1` writes these; every data page reads them)

All files: **parquet**, in `data/dashboard/`, dates as `datetime64[ns]`, index reset, deterministic.
`D1` also writes `data/dashboard/_manifest.json`:
`{ "<name>": {"rows": int, "cols": [str], "built_at": iso8601, "builder_version": str,
   "status": "ok"|"no_source"|"partial", "note": str }, ... }`.

If a source artifact is missing, the builder still writes a **schema-correct empty frame** and sets
`status: "no_source"` — pages then render an empty state rather than crashing.

| File | Columns (dtype) | Source artifacts | Builder cost |
|---|---|---|---|
| `universe_daily_coverage` | `date`(ns) · `n_members`(int) · `n_traded`(int) · `n_panel`(int) · `gap`(int) | membership, ohlcv | cheap |
| `universe_monthly` | `month_end`(ns) · `n_selected`(int) · `turnover_cutoff_200`(f64) · `median_turnover`(f64) · `churn_in`(int) · `churn_out`(int) · `churn_pct`(f64) | universe_stats, membership | cheap |
| `universe_intervals` | `symbol`(str) · `kind`(str: `canary`\|`heavyweight`\|`other`) · `start`(ns) · `end`(ns) | membership, `src.universe.CANARIES/HEAVYWEIGHTS` | cheap |
| `universe_sector_comp` | `month_end`(ns) · `sector`(str) · `n_members`(int) · `weight`(f64) | membership, features(`sector`) | cheap |
| `universe_overlap` | `month_end`(ns) · `overlap_nse_current_pct`(f64) · `overlap_supplied_csv_pct`(f64) | `src.universe.overlap_diagnostic` | cheap |
| `prices_coverage_yearly` | `year`(int) · `universe_days`(int) · `covered_days`(int) · `covered_pct`(f64) · `n_symbols`(int) | ohlcv, membership | cheap |
| `prices_ca_counts` | `year`(int) · `type`(str) · `n`(int) | corporate_actions | cheap |
| `prices_extreme_returns` | `date`(ns) · `symbol`(str) · `ret`(f64) · `explained_by`(str) · `note`(str) | ohlcv, corporate_actions | cheap |
| `prices_source_eras` | `source`(str) · `start`(ns) · `end`(ns) · `n_rows`(int) | ohlcv | cheap |
| `prices_vwap_sanity` | `year`(int) · `n_rows`(int) · `n_in_range`(int) · `pct_in_range`(f64) | ohlcv | cheap |
| `prices_quality` | `check`(str) · `n_violations`(int) · `detail`(str) | ohlcv | cheap |
| `prices_yf_crosscheck` | `symbol`(str) · `corr`(f64) · `n_days`(int) | `reports/p2_*` if present, else `status:no_source` | opt-in (`--heavy`, network) |
| `panel_feature_stats` | `feature`(str) · `year`(int) · `mean`·`std`·`p01`·`p25`·`p50`·`p75`·`p99`(f64) · `n`(int) · `n_nan`(int) | features | cheap |
| `panel_feature_corr` | `feature_a`(str) · `feature_b`(str) · `corr`(f64) | features | cheap |
| `panel_feature_ic` | `feature`(str) · `horizon`(int) · `rank_ic`(f64) · `ic`(f64) · `t_stat`(f64) · `n_days`(int) | features, labels | medium |
| `panel_feature_ic_shift` | `feature`(str) · `variant`(str: `base`\|`shift1`) · `rank_ic`(f64) | features, labels | medium |
| `panel_leaky_check` | `predictor`(str) · `rank_ic`(f64) | labels | cheap |
| `panel_xsec_size` | `date`(ns) · `n_symbols`(int) | features | cheap |
| `panel_nan_coverage` | `date`(ns) · `feature`(str) · `nan_pct`(f64) | features | cheap |
| `panel_label_dist` | `horizon`(int) · `kind`(str: `raw`\|`demeaned`) · `bin_left`(f64) · `count`(int) | labels | cheap |
| `zoo_leaderboard` | `name`(str) · `source`(str) · `formula`(str) · `nodes`·`depth`·`free_params`(int) · `rank_ic`·`icir`·`t_stat`·`sharpe`(f64) · `split`(str) | zoo, backtester, panel | **`--heavy`** (minutes) |
| `ledger_summary` | `t`(ns) · `cumulative_trials`(int) · `cumulative_effective`(f64) | ledger.db | cheap |
| `loop_generations` | `generation`(int) · `family`(str) · `thesis_id`(str) · `verdict`(str) · `reject_reason`(str) · `variant_count`(int) · `forced_promote`(bool) · `marginal_ic`(f64) · `novelty_adjusted_marginal_ic`(f64) · `tier1_rank_ic`(f64) · `fresh_fold_rank_ic`(f64) · `redteam_verdict`(str) · `holdout_rank_ic`(f64) · `holdout_failed`(bool) · `mandatory_regimes`(str, JSON) | `data/loop_checkpoint.db` → `run_state` → `generations` | cheap |
| `loop_run_meta` | `key`(str) · `value`(str) — one row per scalar: `run_id`, `next_gen`, `incomplete_gen`, `t_stat_bar`, `min_marginal_ic`, `large_used`, `small_used`, `budget_day`, `n_accepted` | same | cheap |
| `corpus_family_counts` | `family`(str) · `n`(int) · `n_tradeable`(int) · `n_not_tradeable`(int) | anomalies.json | cheap |
| `agents_token_budget` | `role`(str) · `tier`(str) · `calls_per_thesis`(f64) · `tokens_per_thesis`(int) | `src.config` + T3 projection | cheap |

`D1` implements every builder **except `zoo_leaderboard` and `prices_yf_crosscheck`**, which are
`--heavy` / opt-in and are left `status:"no_source"` in the cheap pass. `D4` owns the "compute the zoo
leaderboard now" fallback button; `D3` owns the yfinance fallback.

## 0.7 Page conventions

1. **Filename** `pages/NN_Title_Case.py`, `NN` two digits (`01`…`14`) fixing sidebar order.
2. First code lines: `import streamlit as st` then `st.set_page_config(page_title="…", layout="wide")`.
3. First render call: `ui.page_header(title, subtitle, phase_tag="D<n>")`.
4. **Every chart** is preceded by one sentence of plain-English context and followed by
   `ui.source_note(...)` naming the file(s) it came from.
5. A page whose required cache/artifact is missing calls `ui.data_missing(...)` then `st.stop()` —
   **it must never raise on a fresh clone.**
6. Pending-phase pages (`10_The_Loop`, `11_Alpha_Cards`, `12_System_Evaluation`) call
   `ui.pending_banner(...)` at the top and still render all design content.
7. Interactive computation goes behind an explicit `st.button(...)` or a widget change, wrapped in
   `st.spinner(...)`, and its result is cached (`lib/engine` handles the caching).
8. No page performs a raw read of `ohlcv.parquet` / `features.parquet` / `labels.parquet` in full —
   use the sliced `lib/data` loaders (pyarrow filters).
9. Colours come from `charts.PALETTE`. No inline hex in a page.
10. Markdown prose that is more than three lines comes from `narrative.block(...)`, not inline strings.
11. A page file is one page. Do not put two tabs in one file even when a phase builds several pages —
    one `.py` per sidebar entry.

## 0.8 Determinism, caching, safety

- Seed `numpy` / `random` with `src.config.RANDOM_SEED` in `build_cache.py` and in any page that
  samples.
- All `lib/data` readers: `@st.cache_data`. `ensure_panel`: `@st.cache_resource`. Engine compute
  helpers: `@st.cache_data` keyed on their arguments.
- **The dashboard writes only to `data/dashboard/` and `reports/dash_*`.** Never to `data/panel`,
  `data/prices`, `data/universe`, `data/*.db`, `artifacts/`.
- No page imports `groq` / constructs a live `LLMClient`. `LLM_MODE` is irrelevant to the dashboard.
- Any red-team / gate run triggered from a page uses `src.ledger.Ledger(":memory:")` — never the real
  `data/ledger.db` — **and passes `do_holdout_peek=False`** to `gate_b`. An in-memory ledger will
  happily grant all 12 peeks; the gauge on `06_Gates_and_Ledger` must show the *real* budget state,
  never one a page run inflated.
- The dashboard **never calls `src.loop.run_loop`**. It reads the checkpoint. A run costs tokens,
  spends real holdout peeks, and belongs to P11.
- A cache builder that needs the network prints a one-line notice and is skipped unless `--heavy`.

### 0.8.1 Concurrency — the dashboard is built *while* P11 and P12 are running

P11 executes the real loop and P12 writes the evaluation module. Both mutate artifacts this dashboard
reads. The dashboard must be safe to open at any moment, and must never interfere with a live run.

1. **Never open a live project SQLite file directly.** `src.ledger.Ledger.__init__` runs `executescript`
   + `commit()` — DDL, so merely *constructing* it takes a brief **write** lock on `data/ledger.db`.
   With the default rollback journal (not WAL) a writer blocks readers outright, so a page and a live
   P11 run can each stall the other up to the 5 s default timeout and then raise
   `sqlite3.OperationalError: database is locked` — in the worst case aborting a generation mid-run.
   `lib/data` therefore exposes:

   ```python
   def _readonly_sqlite(path: Path) -> sqlite3.Connection:
       """Snapshot-then-open. Copies <path> (and any -wal/-journal sidecar) to
       data/dashboard/_snap/<name>.db with shutil.copy2, then opens the COPY.
       Falls back to sqlite3.connect(f"file:{path}?mode=ro", uri=True) if the
       copy fails. Never opens the live file for write, and never constructs
       Ledger/Memory/AlphaCardStore against a path under data/."""
   ```

   Every reader in §0.4 that touches `ledger.db` / `memory.db` / `lessons.db` / `loop_checkpoint.db`
   goes through it. `Ledger(...)` / `Memory(...)` may be constructed **only** on `":memory:"` or on a
   snapshot path.
2. **`bandit_state.json` is not written atomically** (`src/memory.py` → `path.write_text(...)`, no
   temp + `os.replace`). A read landing mid-write gets a truncated file. `load_bandit()` wraps the
   parse in `try/except (json.JSONDecodeError, OSError)` and returns the empty frame — the page then
   renders its normal empty state instead of a traceback. Do **not** "fix" `src/memory.py` from a
   dashboard phase; that file belongs to P7.
3. **Cache staleness is the normal state, not an error.** A cache built before a P11 run shows an
   empty ledger and zero cards forever, and `@st.cache_data` compounds it. So: `_manifest.json` stores
   each builder's source **mtimes**; `build_cache.py --check` reports every row whose source is newer
   than its cache and exits non-zero; `Home.py` renders a single `st.warning` — "cache is N sources
   stale — run `python dashboard/build_cache.py`" — when `--check` would fail. `ui.py` gets a
   `stale_banner(names: list[str])` helper for it.
4. **Read `src.config` at render time, never at author time.** It changed on 2026-09-04 and P12 may
   extend it. No config value is ever retyped into page prose or a `lib` constant.
5. **Treat a partially-written artifact as absent.** `artifacts/cards/*.json` may be mid-write during
   a P11 run: `load_cards()` skips any file that fails `json.load` or `validate_card` and reports the
   skipped count in the UI rather than raising.

## 0.9 Performance budget

- Cold load of any page, **given a built cache**: < 3 s.
- `python dashboard/build_cache.py` (cheap pass): < 90 s on the dev machine.
- `--heavy` (zoo leaderboard, yfinance): may take minutes; must print progress and be resumable
  (skip a leaderboard row already present).
- No page holds > ~50 MB of a raw parquet in memory at once.

## 0.10 Phase completion protocol — **every phase is human-verified before the next**

Same discipline as `IMPLEMENTATION_PLAN.md` §0.7. A phase is done when the owner has run it and said so.

### Required: `reports/dash_p<N>_handoff.md`

```markdown
# Dashboard Phase D<N> handoff — <name>

## 1. What was built
| File | Lines | Purpose |

## 2. Acceptance criteria — every one, with a MEASURED value
| # | Criterion | Result | Measured value |
| 1 | Home page cold-loads < 3s | ✅ PASS | 1.8s (3 runs, median) |
| 2 | coverage_chart trend slope near zero | ✅ PASS | slope = 0.7 names/yr, verdict FLAT |
(NEVER write PASS without the number/screenshot that proves it)

## 3. Verify it yourself
Exact commands + what to look at:
```
python dashboard/build_cache.py
streamlit run dashboard/Home.py        # then open "01 Universe" — the top chart must be flat at ~200
pytest tests/test_dash_p<N>_*.py -q
```
Screenshots saved to reports/dash_shots/dash_p<N>_*.png

## 4. What I could NOT verify, and why
## 5. Failures and open issues
## 6. Anything that contradicts this plan
## 7. Decisions I made that the plan left open
```

### Rules

1. Every acceptance criterion reports a measured value or a screenshot path.
2. Report failures honestly. A page with 2 of 6 charts stubbed, disclosed, beats a claimed 6/6 that
   breaks on the owner's machine.
3. Never fabricate a number or a screenshot.
4. Flag every judgement call in §7.
5. Do not start the next phase. Stop and wait for sign-off.
6. Expect rework.
7. **A multi-page phase reports its acceptance criteria per page** — a partial pass ("Universe done,
   Prices has an open issue in §5") is fine and expected.

## 0.11 Why Streamlit (decision record)

| Option | Verdict |
|---|---|
| **Streamlit** ✅ | Pure Python — it can `import src.backtester / src.gates / src.redteam` and run them live, which several pages require (formula sandbox, DSR calculator, red-team runner). One dependency family, no API server, no second codebase — matches `IMPLEMENTATION_PLAN.md` §0.2 ("every extra dependency is something that breaks during a live demo"). Multipage = the tab structure for free. `@st.cache_data` handles the big parquets. `st.graphviz_chart` renders the flowcharts with no extra binary. `streamlit run` locally for the presentation; free deploy on Streamlit Community Cloud or HF Spaces if a link is wanted. |
| Dash (Plotly) | Also pure Python, more layout control, no full-rerun model — but ~2–3× the boilerplate for the same surface. Reconsider only if this becomes a maintained internal tool. |
| Next.js + FastAPI | Best-looking; React Flow gives the nicest interactive graphs — but two codebases, an API layer to keep in sync with `src/`, more to break in a live demo. Out of scope here; the right move *later* if it graduates to a product. |
| Single-file HTML artifact | Shareable with no setup, but static: no Python, so no live backtester/gates/red-team, and the raw data (4.9M price rows, 539k panel rows) would need full pre-aggregation. Viable only as a narrative-plus-precomputed companion, not a replacement. |
| Marimo | Reactive pure-Python, cleaner than Streamlit's rerun — but smaller ecosystem and less battle-tested for a one-shot deliverable. |

---

# PHASE D0 — Scaffolding and shared contracts

**Objective:** the app skeleton, every `lib/` module with its real public signatures, the theme, the
cache-builder registry, the fixture generators, and a smoke test. Everything else depends on this.

**Depends on:** the signed-off `src/` (P0–**P10**). **Blocks:** D1–D8.

## Inputs
- The project as it stands. `src/` modules per §0.5. `IMPLEMENTATION_PLAN.md` §0.

## Outputs
- `dashboard/` tree per §0.3 (all files present; page files may be one-line placeholders that call
  `ui.page_header` + `st.info("Built in D<n>.")`).
- `dashboard/lib/ui.py`, `dashboard/lib/fixtures.py` — **fully implemented**.
- `dashboard/lib/data.py` — every function in §0.4 present. Cache readers (`load_cache`, `try_cache`,
  `cache_manifest`, `available`) fully implemented. Project-data readers implemented against real files
  where they exist; each must degrade to a clear `FileNotFoundError`/`None` if the file is absent.
- `dashboard/lib/charts.py` — `PALETTE`, `TEMPLATE`, and every builder implemented and theme-consistent
  (thin wrappers over `plotly.express` are fine, but `coverage_chart` must really fit a trend line).
- `dashboard/lib/flow.py`, `dashboard/lib/narrative.py` — signatures present; `render`/`block` raise
  `NotImplementedError(name)` for names not yet done; `DIAGRAMS` / `BLOCKS` tuples complete;
  `region_dates()` implemented from `src.config.SPLITS`.
- `dashboard/lib/engine.py` — signatures present; `ensure_panel` fully implemented; compute helpers may
  raise `NotImplementedError` (D4/D5 fill them) but `dsr` / `expected_max_sr` (thin passthroughs to
  `src.gates`) implemented now; `run_backtest` at minimum implements the `split=="holdout"` rejection.
- `dashboard/build_cache.py` — a `@builder(name)` registry, a `main()` with `--only <names>`,
  `--heavy`, `--check`, `--list`; **two reference builders fully implemented**:
  `corpus_family_counts` and `agents_token_budget` (both cheap, no heavy source).
- `.streamlit/config.toml` — a dark-friendly theme, wide layout, `primaryColor` matching
  `PALETTE['accent']`.
- `dashboard/README.md` — skeleton (run commands, the phase map).
- `requirements-dashboard.txt` — `streamlit`, `plotly`, `altair`, `graphviz`.
- `tests/test_dash_p0_scaffold.py`.

## Steps
1. Create the tree. Every `pages/*.py` importable (a stub that renders a header + "built in D<n>").
2. `lib/ui.py`: implement all helpers. `pending_banner` and `data_missing` must be visually distinct
   (`st.warning` vs `st.info`) and copy-paste-accurate on the command they name.
3. `lib/fixtures.py`: hard-code `CACHE_SCHEMAS` for **every** file in §0.6 (including
   `loop_generations` and `loop_run_meta`). `fake_cache(name)` returns a frame with exactly those
   columns and plausible values (dates spanning 2015–2025 where a `date` column exists; `n_members`
   ~ 195–205 for coverage). `fake_cards(n, seed)` wraps `src.contracts.make_fake_card` (cycling
   `verdict`); `fake_loop_generations(n, seed)` builds a plausible run history. This module is one of
   the two `lib` modules allowed to import `src` (§0.4 import rule) — `src.contracts` only.
4. `lib/data.py`: implement the cache layer and the project-data readers. Use `pyarrow.parquet` with
   `filters=` for the sliced OHLCV/feature/label readers — **assert** a `symbols=` or date bound is
   given when the file is over a size threshold, or read a single column group; no reader ever pulls
   4.9M rows into pandas. Implement **`_readonly_sqlite` (§0.8.1)** and route every `.db` reader
   through it — `load_ledger_trials`, `load_holdout_peeks`, `load_lessons`, `load_cards` (store index),
   `load_loop_run_state`, `load_loop_generations`. `load_bandit` catches `JSONDecodeError`.
5. `lib/charts.py`: define `PALETTE` (one accent, a 6–8 colour categorical set, a sequential ramp, plus
   pos/neg/grid/text — legible on the dark theme), register `TEMPLATE`, implement every builder.
   `coverage_chart` fits an OLS line (`numpy.polyfit`) and returns the slope in names/year plus a
   `FLAT` (|slope| < 3) / `SLOPING` verdict.
6. `lib/flow.py` / `lib/narrative.py`: signatures + `NotImplementedError` bodies + the complete name
   tuples. Implement `region_dates()` and nothing else.
7. `lib/engine.py`: implement `ensure_panel()` (load `data/panel/*`, call `backtester.use_panel`; return
   `False` cleanly if absent), `dsr`, `expected_max_sr`, and the `run_backtest` holdout tripwire. Stub
   the rest.
8. `build_cache.py`: the registry, CLI, manifest writer, and the two reference builders. `--check`
   compares the manifest against the files on disk and against `CACHE_SCHEMAS`.
9. `.streamlit/config.toml`, `README.md` skeleton, `requirements-dashboard.txt`.
10. `tests/test_dash_p0_scaffold.py` (see Acceptance).

## Acceptance
- [ ] `streamlit run dashboard/Home.py` starts with no exception (headless: `--server.headless true`;
      assert the process stays up 5 s and serves HTTP 200 on `/`).
- [ ] `python dashboard/build_cache.py --list` prints the full builder registry (≥ 20 names).
- [ ] `python dashboard/build_cache.py --only corpus_family_counts,agents_token_budget` writes two
      parquets + a manifest; `--check` then passes.
- [ ] `pytest tests/test_dash_p0_scaffold.py -q` passes and asserts: every `lib` module imports; every
      function in §0.4 exists with the documented parameter names (`inspect.signature`); `fake_cache`
      returns the right columns for **all** §0.6 names; `flow.render`/`narrative.block` raise
      `NotImplementedError` for an un-done name (not `AttributeError`); `engine.ensure_panel()` returns
      a bool; `engine.run_backtest(..., split="holdout")` raises; `charts.coverage_chart(
      fixtures.fake_cache("universe_daily_coverage"))` returns `(Figure, dict)` with a `slope_per_year`
      key; `fixtures.fake_cards(2)` returns 2 dicts that both pass `src.contracts.validate_card`.
- [ ] **Signature-truth test** — the D0 test imports `src.redteam.run_redteam`, `src.gates.walk_forward`
      and `src.memory.Memory` and asserts, via `inspect.signature`, that (a) `run_redteam`'s `split` is
      `KEYWORD_ONLY` and its 2nd positional is `tests`, (b) `walk_forward` takes `start`/`end` and has
      no `split` parameter, (c) `lineage_path` is **not** a module-level attribute of `src.memory` but
      **is** a method on `Memory`. These are the three §0.5 contracts an earlier draft got wrong; the
      test exists so a future `src` change re-breaks loudly instead of silently.
- [ ] No `lib` module imports from `src` except `engine.py`, `fixtures.py` (`src.contracts` only) and
      `flow.py` (`src.config` only) — asserted by parsing each module's imports.
- [ ] `_readonly_sqlite` never opens a path under `data/` for write — test: point it at a copy of
      `data/ledger.db`, assert the source file's mtime is unchanged after a read.
- [ ] `data/dashboard/` is the only new data path written.

## Do NOT
Do not build any real page content (D2–D8). Do not implement the flow diagrams or narrative blocks. Do
not add a dependency outside §0.2.

**Effort:** ~2.5h

---

# PHASE D1 — Cache builder (the data-prep layer)

**Objective:** implement every cheap builder in §0.6 so the data pages have small, fast inputs.

**Depends on:** D0 (the registry, `CACHE_SCHEMAS`, `lib/data`). **Blocks:** D3 (data pages), and the
cache-backed panels of D4 (`zoo_leaderboard`) / D5 (`ledger_summary`) / D6 (`corpus_family_counts`,
`agents_token_budget`).

## Standalone context
`data/prices/ohlcv.parquet` is ~4.9M rows and `data/panel/features.parquet` ~539k. Reading either per
page is too slow. This phase computes the aggregates **once** into `data/dashboard/*.parquet` (each a
few hundred to a few thousand rows) and a manifest. Pages then read those instantly and only call into
`src/` for genuinely interactive work.

## Inputs
- `data/universe/*`, `data/prices/*`, `data/panel/*`, `data/ledger.db`, `data/corpus/anomalies.json`.
  *(Any missing → that builder writes an empty schema-correct frame, `status:"no_source"`.)*
- `src.universe`, `src.config`.

## Outputs
- Every file in §0.6 **except** `zoo_leaderboard` and `prices_yf_crosscheck` (leave those
  `status:"no_source"` unless `--heavy`).
- `data/dashboard/_manifest.json` fully populated.
- Update `dashboard/README.md` with the builder list and costs.
- `tests/test_dash_p1_cache.py`.

## Steps
1. One `@builder` function per file. Each: read its sources with sliced/columnar reads, compute, assert
   the output matches `fixtures.CACHE_SCHEMAS[name]`, return the frame; the harness writes it + the
   manifest row.
2. `universe_daily_coverage`: `members(D)` from the membership panel, `traded(D)` from distinct symbols
   in `ohlcv` that day, `n_panel = |members ∩ traded|`, `gap` the residual.
3. `universe_intervals`: for each symbol in `CANARIES ∪ HEAVYWEIGHTS`, collapse the daily `in_universe`
   flag into `(start, end)` runs.
4. `universe_sector_comp`: join monthly membership to `features[['symbol','sector']]` (dedup latest),
   count per sector per month.
5. `panel_feature_ic`: for each feature × horizon in `{1,2,3,5,10,21}`, daily Spearman of the feature
   vs `fwd_ret_h_demeaned`, mean and t-stat over days. Reuse `src.backtester._daily_ic` **or**
   `src.gates.daily_rank_ic` if callable standalone; otherwise a local Spearman is fine — document
   which.
6. `panel_feature_ic_shift`: recompute at horizon 1 with the feature panel shifted `+1` trading day;
   store `base` and `shift1` per feature. (They must differ — that is P3's look-ahead self-test.)
7. `panel_leaky_check`: RankIC of `fwd_ret_1` used as its own predictor (expect ≈ 1.0).
8. `prices_extreme_returns`: every `|adjusted daily return| > 0.5`; tag `explained_by` = a corporate
   action within ±1 day if one exists, else `""`.
9. `ledger_summary`: read the `trials` table **through `data._readonly_sqlite` (§0.8.1)** — a P11 run
   may hold `data/ledger.db` open; cumulative count over `timestamp`; cumulative effective count via
   `src.gates.effective_trial_count` on the running set (or a documented cheaper proxy).
10. `loop_generations` / `loop_run_meta`: `data.load_loop_run_state()` → flatten `generations` to the
    §0.6 schema; the scalars to key/value rows. Loop not run → empty frame + `status:"no_source"`.
11. `corpus_family_counts`, `agents_token_budget`: already in D0 — verify still pass.
    `agents_token_budget` reads `src.config` live; also surface `LLM_MODEL_LIMITS` if a per-model row
    is cheap to add.
12. **Staleness metadata (§0.8.1 #3):** every manifest row records `sources: [{path, mtime, size}]`.
    `--check` compares them against disk and exits non-zero listing every stale builder. This is the
    normal state while P11 is running — `--check` failing is information, not a bug.
13. Determinism: seed once; assert re-running produces byte-identical parquets (or identical after a
    stable sort) — a test covers this. *(Exempt the ledger/loop builders from the byte-identical
    assertion if a P11 run is live — compare schema and non-decreasing row counts instead, and say so
    in the handoff.)*
14. `--heavy` path: `zoo_leaderboard` (loop `src.zoo.ZOO`, `eval` each formula on the real panel,
    `backtest(split="val_a")`, collect metrics; skip a row already present) and `prices_yf_crosscheck`
    (only if `reports/p2_*` has no stored table — then it may hit yfinance for ~30 large caps).

## Acceptance
- [ ] `python dashboard/build_cache.py` (cheap pass) completes in **< 90 s**; report the measured time.
- [ ] `--check` passes: every manifest row's `cols` matches `CACHE_SCHEMAS`; every file's dtypes match.
- [ ] Re-running is idempotent (test: hash the parquets before/after a second run).
- [ ] `universe_daily_coverage.n_panel` has **near-zero linear trend** across 2015→2025 — report the
      slope (names/year). *(If it slopes, that is a finding about P1/P2, not a bug in this phase — say
      so in the handoff.)*
- [ ] `panel_feature_ic_shift`: for `mom_21`, `base` and `shift1` RankIC differ by > 20% relative —
      report both.
- [ ] `panel_leaky_check`: `fwd_ret_1` predictor RankIC > 0.9 — report it.
- [ ] Every builder with a missing source writes an empty frame + `status:"no_source"`, no exception.
- [ ] `loop_generations` builds from `data/loop_checkpoint.db` if a run exists, else `no_source` —
      report which, and the row count.
- [ ] Every `.db` read goes through `data._readonly_sqlite`; a test asserts the source `.db` mtimes are
      unchanged after a full `build_cache.py` run (proves it is safe beside a live P11 run).
- [ ] `--check` reports staleness per builder and exits non-zero when a source is newer.
- [ ] `pytest tests/test_dash_p1_cache.py -q` passes.

## Do NOT
Do not build page UIs. Do not run `zoo_leaderboard` in the cheap pass. Do not hit the network outside
`--heavy`. Do not modify anything under `data/` other than `data/dashboard/`.

**Effort:** ~3.5h

---

# PHASE D2 — Home page, the six flowcharts, the narrative library

**Objective:** the "Start here" page and the reusable diagram + prose modules the whole dashboard draws
on.

**Depends on:** D0. **Blocks:** D5, D7 (they call `flow.render` / `narrative.block`) — soft; they can
ship against the `NotImplementedError` and light up when this lands.

## Inputs
- `FLOW_EXPLAINED.md` (Parts 0–10), `IMPLEMENTATION_PLAN.md` (§0, Phase 10, execution-order section),
  `INITIAL_PLAN.md` §3/§6, `reports/p0`–`p9_handoff.md` (for the build-status board).
- `src.config.SPLITS`, `src.zoo.ZOO`, `src.redteam.REDTEAM_MENU`, `data/corpus/anomalies.json`,
  `src.config` LLM constants (for the key-numbers row).

## Outputs
- `dashboard/lib/flow.py` — all 6 `DIAGRAMS` implemented + `data_regions_timeline()`.
- `dashboard/lib/narrative.py` — all `BLOCKS` implemented, each ending with a `_Source:_` line.
- `dashboard/Home.py` — the full landing page.
- `tests/test_dash_p2_home.py`.

## Steps
1. **`flow.render("pipeline")`** — the nine stages S1→S9 with the four gates (A Economics, pre-filter,
   B Honesty, C Red-Team) and the "reject → Memory" edges, as a `graphviz.Digraph`. Match
   `FLOW_EXPLAINED.md` Part 2.
2. **`flow.render("loop_graph")`** — the P10 LangGraph state machine from `IMPLEMENTATION_PLAN.md`
   Phase 10: `orchestrate→retrieve→brief→ideate→gate_a` … the inner `judge→code` loop labelled
   "≤ 20 / thesis", `freshfold` on VAL_B, `gate_b_novelty→gate_b_stats`, `gate_c_redteam`, `emit_card`,
   `reflect→should_continue`.
3. **`flow.render("gate_b")`** — orthogonalize → novelty → statistics (DSR/t/PBO on the residual) →
   rationed holdout peek, with the "novelty is free, a peek is 1 of 12" annotation.
4. **`flow.render("data_lineage")`** — raw NSE bhavcopy + CA API → `ohlcv.parquet` →
   {`membership.parquet`, `features/labels`} → `backtester` → `gates`+`redteam` → `Alpha Cards` +
   `ledger` + `book`.
5. **`flow.render("phase_dag")`** — P0 → P2 → P1 → P3 → P4 → P6 → P10 → P11 → P13 with the
   P5/P7/P8/P9 parallel branch, and a "done / pending" colour per node.
6. **`flow.render("card_lifecycle")`** — an Alpha Card as a stack of sections, each added at a stage
   (thesis+sign → formula → tier1 → freshfold → tier2 → audit → redteam → verdict+lineage).
7. **`data_regions_timeline()`** — a Plotly horizontal bar per region from `region_dates()`, coloured
   by role (warm-up buffer / search / confirm / sealed), with the "12 counted peeks" note on HOLDOUT.
8. **`narrative.block(...)`** — write each block from the source docs (do not invent; quote/condense
   and cite). `five_failures` and `sqrt_2lnN` return Markdown tables with the measured numbers.
   ⚠️ **Citation note: `FLOW_EXPLAINED.md` has no PART 3.** Its parts are 0, 1, 2, 4, 5, 6, 7, 8, 9, 10.
   The P(best-of-N noise t>3) table is in **PART 2** (the S6 section, ~line 350); the five-failure-modes
   table is **PART 6** ("The slide that carries the design", ~line 710). Cite those.
9. **`Home.py`** sections, in order:
   - Title + one-liner (`block("one_liner")`).
   - **Key numbers** KPI row: universe size (200), date span, #features (10 + size_proxy), #operators,
     #zoo formulas (`len(ZOO)`), #corpus anomalies (`len(load_corpus())`), #red-team tests (11),
     token budget/thesis (`LLM_TOKENS_PER_THESIS_PROJECTION`), tests passing (from the latest handoff).
   - The **pipeline** flowchart + `block("nine_stages")`.
   - The **card_lifecycle** diagram + `block("alpha_card")`.
   - The **data_regions_timeline** + `block("four_regions")`.
   - `block("five_failures")` table.
   - `block("three_budgets")`.
   - `block("sqrt_2lnN")` (with a pointer to the interactive version on the Gates page).
   - `block("pre_registered_sign")`, `block("variant_cap_fresh_fold")`, `block("gate_b_order")`.
   - `block("walkthrough")` — one idea end to end.
   - `block("novelty_claims")`, `block("weak_points")`.
   - **Build status board**: `block("build_status")` + the `phase_dag` diagram (P0–P9 done, P10–P13
     pending) + a table rendering each `reports/p*_handoff.md`'s headline pass count.
   - `block("nav_guide")` — what each of the 14 pages contains.

## Acceptance
- [ ] All 6 `flow.render(name)` return a `graphviz.Digraph` or DOT string that `st.graphviz_chart`
      accepts; `data_regions_timeline()` returns a Plotly `Figure`. A test renders each without
      exception.
- [ ] Every `narrative.BLOCKS` name returns non-empty Markdown ending in a `_Source:_` line — asserted.
- [ ] `Home.py` cold-loads in **< 3 s** (measure, 3 runs).
- [ ] The build-status board shows **P0–P10 = done, P11–P13 = pending** — and is **derived, not
      hard-coded**: the page globs `reports/p*_handoff.md` and marks a phase done iff its handoff
      exists. P11/P12 may land while the dashboard is being built, so a literal status list would go
      stale within days. A test asserts the derived status matches `reports/` at test time.
- [ ] The `phase_dag` node colours come from that same derived status.
- [ ] `sqrt_2lnN` block contains the measured P(best-of-N noise t>3) table: 5→0.7%, 20→2.7%,
      100→12.6%, 200→23.6%, 500→49.1% (`FLOW_EXPLAINED.md` **PART 2**; cross-check
      `reports/p6_handoff.md` §"measured", which is the primary source).
- [ ] `pytest tests/test_dash_p2_home.py -q` passes.

## Do NOT
Do not build any data page. Do not compute anything from `data/` (the key-numbers row reads only cheap
counts / config). Do not invent architecture — every claim traces to a doc.

**Effort:** ~3.5h

---

# PHASE D3 — Data pages: Universe, Prices, Feature Panel

**Objective:** the three read-only data-exploration pages. Same pattern throughout — read a `D1` cache,
render charts, offer a sliced per-symbol drill-down.

**Depends on:** D0, D1 (the `universe_*`, `prices_*`, `panel_*` caches). **Blocks:** nothing (D7's Bad
Examples page reuses these data helpers).

## Standalone context
These three pages carry the survivorship / point-in-time / no-look-ahead evidence — the material the
presentation opens on. They share `charts.py` heavily (coverage lines, Gantt timelines, heatmaps,
histograms) so one agent builds all three. Each page is still one `.py` file; report acceptance per
page and a partial pass is fine.

## Inputs
- Caches: all `universe_*`, `prices_*`, `panel_*` files from §0.6.
- `data/universe/*`, `data/prices/ohlcv.parquet` (**sliced only**), `corporate_actions.parquet`,
  `delivery.parquet`, `data/panel/{features,labels}.parquet` (**sliced only**), `splits.json`.
- `src.universe` (optional, for the live look-ahead recompute). `reports/p2_coverage_report.md`,
  `reports/p3_panel_report.md` (rendered as reference text).
  *(Cache missing → `ui.data_missing(...)` naming the exact `build_cache` command, then `st.stop()`.)*

## Outputs
- `dashboard/pages/01_Universe.py`, `dashboard/pages/02_Prices.py`,
  `dashboard/pages/03_Feature_Panel.py`.
- `tests/test_dash_p3_data.py`.

## Steps — `01_Universe.py`
1. **The decisive coverage chart** — `charts.coverage_chart(universe_daily_coverage, target=200)`:
   `n_panel` per day, the constant-200 reference line, the fitted OLS trend, a prominent
   **FLAT / SLOPING verdict** + the slope (names/year). "An upward slope would mean survivorship bias
   survived P1 — a hard stop." (`IMPLEMENTATION_PLAN.md` P1 TEST B.)
2. **Liquidity floor** — `turnover_cutoff_200` and `median_turnover` over time (dual line).
3. **Monthly churn** — `churn_pct` bar per rebalance; a reference band at 2–5%.
4. **Canary timeline** — `charts.gantt(universe_intervals[kind=="canary"])`: DHFL, RCOM, JPASSOCIAT,
   YESBANK, SUZLON, IDEA — each a bar that **ends when the company stops trading**. "Nothing in the
   pipeline ever asks 'does this company still exist?'"
5. **Heavyweight timeline** — same for RELIANCE, TCS, SBIN, TATASTEEL, MARUTI, ONGC — in for most of
   the period. "Their absence would signal a turnover-computation bug."
6. **Sector composition** — `charts.stacked_area(universe_sector_comp)`. Note: sector labels are
   current, not point-in-time (disclosed in P3).
7. **Index overlap** — `universe_overlap` lines. "We call this 'the 200 most liquid Indian equities,
   reconstructed point-in-time from NSE daily bhavcopy', not 'NIFTY 200'."
8. **Membership explorer** — a date picker → the 200 names + their turnover rank; a symbol picker →
   its membership intervals + first/last seen.
9. *(optional, behind a button)* **Live look-ahead check** — `src.universe.lookahead_check` truncated
   at 2020-01-01; "every prior month bit-identical: PASS/FAIL".

## Steps — `02_Prices.py`
1. **Coverage by year** — `covered_pct` + `n_symbols` bars. "We need every stock ever in the universe,
   including the ~115 that were dropped or went bankrupt."
2. **Corporate actions** — `prices_ca_counts` stacked bar (splits / bonuses / dividends by year) + a
   table. "bhavcopy is unadjusted; a 1:10 split reads as −90% until corrected. Demergers are flagged,
   not attempted."
2b. **Symbol-vs-ISIN identity** — read `data/prices/isin_map.parquet`: the count of symbols whose ISIN
   changed (renames/mergers) and of ISINs carrying more than one symbol. This is the evidence for the
   symbol-keyed CA-adjustment decision P2 disclosed, and for the ~7 splits the CA parser missed that
   P3 surfaced — link both handoffs. `data/prices/size_proxy.parquet` gets a one-line coverage note
   here too (it is the source of the panel's `size_proxy` feature).
3. **Extreme returns** — `prices_extreme_returns` table (`|ret| > 50%`), each tagged explained-by-CA or
   flagged; a count-by-year bar. "Not winsorized — Indian mid-caps genuinely move like that."
4. **Source eras** — `prices_source_eras` timeline: `bhavcopy_legacy` → 2019-09-27, then
   `sec_bhavdata_full`.
5. **Delivery availability** — first available date + a coverage line. "NaN before ~2020, disclosed."
6. **VWAP sanity** — `prices_vwap_sanity` gauge: % rows with `low ≤ vwap ≤ high` (target ~100%).
7. **Quality board** — `prices_quality`: `close ≤ 0`, `high < low`, negative volume — each should be 0,
   as pass/fail pills.
8. **yfinance cross-check** — if `prices_yf_crosscheck` has data, a correlation histogram
   (target > 0.99); else `ui.pending_banner` + a "compute now (`--heavy`, hits yfinance)" note. Never
   call yfinance on load.
9. **Per-symbol explorer** — a symbol picker → `charts.candlestick` of the adjusted series (a
   **sliced** `load_ohlcv(symbols=[sym])` read) with CA ex-dates as markers, plus a raw-vs-adjusted
   toggle.

## Steps — `03_Feature_Panel.py`
1. **The ten features** — a reference table (name, definition from `IMPLEMENTATION_PLAN.md` P3 step 2,
   window, availability lag).
2. **Distributions** — `panel_feature_stats` → a violin/box per feature, "by year" toggle.
3. **Correlation** — `panel_feature_corr` → `charts.heatmap` (diverging, centred at 0).
4. **Cross-section size** — `panel_xsec_size` line; a reference at 100; flag days below it after 2016.
5. **Raw feature IC** — `charts.ic_bar(panel_feature_ic[horizon==1])` with a noise band (±~0.005).
   ⚠️ **Do not claim a planted signal here.** The IC ≈ 0.04 plant lives in
   `src.contracts.make_fake_features` (`_planted_latent`) — it is in the **fixture** panel, not in the
   real `data/panel/features.parquet`. On real data expect small, honest ICs. Caption it that way:
   "these are real-data ICs — small is what a true cross-sectional equity factor looks like; the
   planted-signal check that proves the machinery *can* see a real effect runs on the fixture panel
   (Backtester page)." Report whatever the real values are, including if none clears the band.
6. **IC decay** — `panel_feature_ic` multi-line across `h ∈ {1,2,3,5,10,21}`, one line per feature.
7. **The look-ahead self-test** — `panel_feature_ic_shift`: a grouped bar of `base` vs `shift1` RankIC
   per feature. "If a feature's IC were invariant to a one-day shift, the pipeline would be leaking. It
   is not."
8. **The leakage-detector sanity check** — `panel_leaky_check`: `fwd_ret_1` predicting itself → IC ≈
   1.0. "This proves the measurement can *see* leakage when present — which is what makes the small,
   honest IC on real features meaningful."
9. **NaN coverage** — `panel_nan_coverage` heatmap (date × feature); `delivery_pct` dark before ~2020.
10. **Labels** — `panel_label_dist` histograms, raw vs cross-sectionally demeaned, per horizon.
11. **Per-symbol series** — a symbol picker → its feature time series (sliced read).

## Acceptance
- [ ] **Universe:** the coverage chart renders with the reference line **and** the trend line; the
      verdict string is shown; report the measured slope. The canary Gantt shows all 6 names, each
      with a finite end date before 2025. The heavyweight Gantt shows RELIANCE/TCS/SBIN present for
      > 80% of the span.
- [ ] **Prices:** the candlestick renders from a sliced read — a test asserts `load_ohlcv` is never
      called with no filter and the page never hits the network on load. The quality board shows all
      three checks with counts.
- [ ] **Feature Panel:** the IC bar shows at least one feature clearly outside the noise band (report
      its value); the shift-test bars show `base ≠ shift1` for `mom_21` (report both); `panel_leaky_
      check` value > 0.9 is displayed.
- [ ] Every page's missing-cache path shows `data_missing` and stops — no traceback (test with the
      cache dir empty).
- [ ] Each page cold-loads in **< 3 s** with the cache present.
- [ ] `pytest tests/test_dash_p3_data.py -q` passes.

## Do NOT
Do not recompute the universe / ICs on every load (use the caches; live checks are opt-in). Do not read
`ohlcv.parquet` / `features.parquet` / `labels.parquet` whole. Do not hit yfinance on a page load. Do
not call it "NIFTY 200". Do not winsorize or hide extreme returns.

**Effort:** ~7h  (≈ 2.5h Universe + 2.5h Prices + 2h Feature Panel; commit them one at a time)

---

# PHASE D4 — Formula tooling: Backtester + Operators & Zoo

**Objective:** the two interactive "write a formula, see what happens" pages — the backtester runner
and the operator/zoo/AST toolbox.

**Depends on:** D0 (`lib/engine`), `src.backtester` / `src.zoo` / `src.operators` / `src.ast_tools`, a
real `data/panel/*`. Optional D1 (`zoo_leaderboard`). **Blocks:** D7 (Bad Examples uses
`engine.run_backtest` / `engine.eval_formula`).

## Standalone context
The backtest runner and the formula sandbox are nearly the same widget — pick/type a formula, evaluate
it on the panel, show a result. Building them together keeps `lib/engine`'s `eval_formula` /
`run_backtest` consistent.

## Inputs
- `data/panel/{features,labels}.parquet`, `splits.json` via `engine.ensure_panel()`.
  *(Panel absent → `ui.data_missing` + `st.stop()`.)*
- `src.zoo.ZOO` (formula dropdown + the zoo table), `src.ast_tools`, `src.operators`.
- Cache `zoo_leaderboard` (may be `no_source` → offer a "compute now" button).

## Outputs
- `dashboard/pages/04_Backtester.py`, `dashboard/pages/05_Operators_and_Zoo.py`.
- `dashboard/lib/engine.py` — `eval_formula`, `run_backtest` implemented.
- `tests/test_dash_p4_tooling.py`.

## Steps — `04_Backtester.py`
1. **The interface** — a table of the `backtest(...)` switches (split, horizon, extra_lag, cost_bps,
   neutralize, subsample, purge/embargo) and the `Metrics` dict shape (`IMPLEMENTATION_PLAN.md` §0.5).
   "One engine, called from eight places downstream."
2. **The runner** — controls: formula (a `ZOO` dropdown **or** free text), `split ∈
   {train, val_a, val_b, train+val_a}` (**never holdout** — `run_backtest` rejects it), `horizon`,
   `cost_bps`, `neutralize`. On **Run**: `engine.eval_formula` → `engine.run_backtest` →
   a KPI row (`rank_ic`, `icir`, `t_stat`, `sharpe`, `ann_return`, `turnover`, `mdd`, `n_days`),
   `charts.decay_curve(metrics["decay"])`, `charts.equity_curve(...)`, the realised `sign`.
3. **Purge/embargo visualiser** — for a chosen horizon, show (as a small timeline) which training rows
   near a test boundary are dropped; pull the count from `purge_embargo_mask`.
4. **The acceptance-evidence board** — run live and show the numbers:
   - random-noise signal → `|rank_ic| < 0.01`, `|t_stat| < 2`;
   - the planted fixture feature → recovers IC ≈ 0.04 (use a `make_fake_*` panel via a toggle, or note
     it if the real panel has no planted feature);
   - `engine.leaky_signal()` (`fwd_ret_1`) → `rank_ic > 0.9`;
   - a signal and its negation → `rank_ic` flips sign exactly;
   - `cost_bps ∈ {0, 5, 15, 30}` → `sharpe` monotonically decreasing.
5. Cache every run (`@st.cache_data`) so re-selecting is instant; spinner on first compute.

## Steps — `05_Operators_and_Zoo.py`
1. **Operator catalog** — grouped (cross-sectional / time-series / element-wise), each with a one-line
   description and its arity. Callout: "every operator is **causal** — `delay` looks back, `ts_mean`
   averages a trailing window, `rank` compares today to today. No operator reaches forward. This makes
   formula-level look-ahead structurally impossible, not hopefully caught." (`FLOW_EXPLAINED.md` S5.)
2. **Causality evidence** — for a couple of time-series operators, show (from a tiny panel) that
   changing a *future* input value leaves earlier outputs unchanged.
3. **The zoo** — a sortable table of `ZOO`: name, source (`Alpha101 #N` / `classical`), formula,
   `complexity` (`nodes`, `depth`, `free_params`). Note: Alpha #56 skipped (needs true market cap).
4. **AST viewer** — pick a formula → render `parse(formula)` as a `graphviz` tree.
5. **Formula sandbox** — a text box → `parse(formula, strict=True)`: show accept/reject, then
   `canonical`, `fingerprint`, `complexity`, and (via `engine.eval_formula` + a quick RankIC on
   `val_a`) a one-number signal preview. Handle `ParseError` cleanly.
6. **Parser-rejection demo** — buttons for `__import__('os')`, `close.values`, `[x for x in y]`,
   `lambda x: x` — each shows the parser refusing it.
7. **Duplicate detection** — enter a formula → `is_zoo_duplicate` → show the matched zoo name (or
   "novel"); a pre-filled example of a zoo formula with operands commuted (`a*b` → `b*a`) to show it
   still matches. "A signal that is a known published alpha in disguise is, by definition, crowded."
8. **Zoo IC leaderboard** — from `zoo_leaderboard` if present (bar, sorted by `rank_ic`); else a
   "Compute now" button that runs the `--heavy` builder inline with a progress bar.

## Acceptance
- [ ] **Backtester:** running a `ZOO` momentum formula on `val_a` returns a full Metrics dict, all
      fields rendered. The noise-signal evidence shows `|rank_ic| < 0.01` live — report the value.
      `engine.run_backtest(split="holdout")` raises a clear error (test it). The cost-sweep board shows
      monotonically decreasing Sharpe — report the four values. Second run of the same inputs returns
      in < 200 ms (cache hit).
- [ ] **Operators & Zoo:** the AST viewer renders a tree for 3 different formulas without exception.
      The sandbox **rejects** all four bad strings in step 6 and shows the reason. `is_zoo_duplicate`
      returns a match for a zoo formula with commuted operands — shown in the UI. The leaderboard
      renders from cache, or the "compute now" path produces it (report row count + time).
- [ ] Each page cold-loads in **< 3 s** (runners compute on demand).
- [ ] `pytest tests/test_dash_p4_tooling.py -q` passes.

## Do NOT
Do not call `backtest` with `split="holdout"`. Do not implement DSR/PBO here (that is D5). Do not add or
modify an operator. Do not let the sandbox `eval` anything outside `src.ast_tools.parse`. Do not
recompute on every rerun — cache.

**Effort:** ~5h  (≈ 3h Backtester + 2h Operators/Zoo)

---

# PHASE D5 — Honesty machinery: Gates & Ledger + Red-Team

**Objective:** the two pages that carry the anti-self-deception story — Gate B (over-searching, the
Deflated Sharpe, PBO, the ledger, the rationed holdout) and Gate C (the eleven falsification tests).

**Depends on:** D0 (`lib/engine`), `src.gates` / `src.ledger` / `src.redteam`, D2
(`flow.render("gate_b")`). **Blocks:** nothing.

## Standalone context
These are Gate B and Gate C — conceptually one "did we fool ourselves?" argument, and both pages are
interactive "kill a signal / price in the search" tools. `IMPLEMENTATION_PLAN.md` Phase 6 update box
and Phase 9. This is the densest phase; report acceptance per page.

## Inputs
- `src.gates` (`deflated_sharpe_ratio`, `expected_max_sharpe`, `effective_trial_count`, `walk_forward`,
  `cscv_pbo`, `marginal_ic`, `check_sign`), `src.ledger.Ledger` on `data/ledger.db`,
  `src.ledger.assert_no_row_removal_sql`, `src.redteam` (`run_redteam`, `REDTEAM_MENU`,
  `DECISIVE_TESTS`).
- Cache `ledger_summary`. `engine.ensure_panel()` for walk-forward and the red-team runner.
- `src.zoo.ZOO` for signal choices.

## Outputs
- `dashboard/pages/06_Gates_and_Ledger.py`, `dashboard/pages/09_Red_Team.py`.
- `dashboard/lib/engine.py` — `run_redteam_ui`, `leaky_signal` implemented.
- `tests/test_dash_p5_honesty.py`.

## Steps — `06_Gates_and_Ledger.py`
1. **Gate B order** — `flow.render("gate_b")` + `narrative.block("gate_b_order")`. "Novelty is free and
   already computed; a holdout peek is 1 of 12 for the system's lifetime."
2. **The over-searching explainer** — an `N` slider (2…1000). Plot three curves: the √(2 ln N) ceiling,
   the realised `E[max]` (seeded Monte-Carlo, cached), and Bailey-LdP `E[max SR]` via
   `expected_max_sharpe`. Below it, the measured **P(best-of-N noise t > 3.0)** table
   (5→0.7%, 20→2.7%, 100→12.6%, 200→23.6%, 500→49.1%) with the slider's N highlighted.
3. **DSR calculator** — sliders: observed Sharpe, `n_trials`, `sr_std`, skew, kurtosis, sample length
   `T` → `engine.dsr(...)`. Pre-load the **headline case**: 200 pure-noise signals, best t ≈ 2.74 →
   DSR ≈ 0.477 → **reject**; and a real signal found in 5 trials, t ≈ 7 → DSR ≈ 0.995 → **pass**.
4. **Effective trial count** — a demo: 20 knob-variants of one shape (`vol / ts_mean(vol, k)`,
   k = 5…25) → `effective_trial_count` ≈ 2, next to raw N = 20. "Deflated by the effective count, not
   raw N — and scoped run-wide, not per-thesis."
5. **PBO** — `cscv_pbo` on a noise matrix (≈ 0.5) and on a planted signal (low); render the
   in-sample-winner vs out-of-sample-rank distribution.
6. **Walk-forward** — pick a `ZOO` formula → `walk_forward` over `train+val_a` → the sequential OOS IC
   series (line) + per-fold metrics (table). ⚠️ **`walk_forward` takes dates, not a split name**:
   `start, end = config.SPLITS["train"][0], config.SPLITS["val_a"][1]` — there is no `split=`
   parameter. "The workhorse OOS method; CSCV exists only for one honest PBO number."
7. **The trial ledger** — `ledger_summary` cumulative-count line; a filterable table of
   `Ledger().trial_records()` (thesis_id, formula_hash, split, rank_ic, sharpe, t_stat,
   `counts_as_trial`, `rejection_reason`). If the ledger is near-empty (likely — the loop has not
   run), **say so plainly** and show a fixture preview of a populated one.
8. **Holdout peeks** — `charts.gauge(Ledger().holdout_peeks_used(), HOLDOUT_PEEK_BUDGET, "peeks used")`
   + the peek log.
9. **Append-only guarantee** — run `assert_no_row_removal_sql()` live and show "no DELETE statement in
   `ledger.py`: PASS".
10. **Thresholds** — the fixed table: `T_STAT_BAR 3.0`, `MIN_MARGINAL_IC 0.01`, `DSR_MIN 0.95`,
    `PBO_MAX 0.50`, `MIN_DSR_SAMPLE 60`.

## Steps — `09_Red_Team.py`
1. **The menu** — a table of all 11: `#`, name, what it hunts, **decisive** (1, 2, 4, 5, 10) vs
   **diagnostic**. "The agent picks *which* attacks fit; the attacks themselves are pre-written
   parameterised backtests. It never writes code."
2. **The survive rule** — killed iff any decisive test flags; RankIC must stay positive and
   significant across 1/2/5, not collapse under 4 at 15 bps or under 5, and hold a consistent sign in
   ≥ 70% of folds (test 10). The 5 decisive tests always run.
3. **Rejection-only** — "All 11 can only kill, never promote. A filter that only rejects cannot raise
   the false-discovery rate, so every red-team backtest is logged with `counts_as_trial = 0`. This is
   the answer to 'doesn't running 11 backtests per candidate blow up your trial count?'"
4. **Regime definition** — bull (63-day return > +5%), bear (< −5%), high-vol (top expanding-window
   tercile). "Expanding thresholds only — a full-sample volatility threshold is look-ahead."
5. **The runner** — pick a signal: a `ZOO` formula, or "leaky (`fwd_ret_1`)", or "one-lucky-year"
   (a synthetic). On **Run** (`engine.run_redteam_ui`, ~1–2 min, spinner + note): a per-test
   pass/flag **heatmap**, the `verdict`, `failed_tests`, `flagged_diagnostics`, and the baseline
   RankIC/t.
   ⚠️ **Call it with keywords.** `run_redteam`'s `split` is keyword-only and its 2nd positional is
   `tests` (§0.5) — `run_redteam(sig, "val_a")` passes the split as a test list and fails obscurely.
   And **pass `liquidity_ranks=data.load_liquidity_ranks()`**: test 11 (`universe_edge`) derives the
   illiquid fringe from that frame and degrades to a no-op without it. The heatmap must show test 11
   as *run*, not silently skipped — if it reports insufficient data, say so on screen.
6. **Evidence board** — cached:
   - leaky `fwd_ret_1` → killed by test 5 (`extra_lag`): baseline RankIC ~1.0 → ~0.002;
   - a one-lucky-year signal → killed by test 1;
   - a thin-gross-edge high-turnover signal → killed by test 4 (net Sharpe at 15 bps < 0);
   - a clean momentum `ZOO` formula → survives all 11.

## Acceptance
- [ ] **Gates:** the DSR calculator at the headline preset returns DSR < `DSR_MIN` — report the value;
      the 5-trial real-signal preset returns DSR > `DSR_MIN`. The N-slider's P(t>3) readout matches the
      measured table at N ∈ {5, 20, 100, 200, 500}. `effective_trial_count` on the 20 knob-variants
      returns materially < 20 — report it. `assert_no_row_removal_sql()` passes and is shown. The
      ledger table reads `data/ledger.db` (or shows the empty state + fixture preview) with no
      traceback.
- [ ] **Red-Team:** running "leaky (`fwd_ret_1`)" → `verdict == "killed"`, `failed_tests` contains
      `extra_lag` (report before/after RankIC). Running a clean `ZOO` momentum formula → the full
      11-test heatmap renders with a verdict. Every red-team run uses `Ledger(":memory:")` — assert
      `data/ledger.db` is never written.
- [ ] Both pages cold-load in **< 3 s** (Monte-Carlo for the N curve is cached; runners on demand).
- [ ] `pytest tests/test_dash_p5_honesty.py -q` passes.

## Do NOT
Do not read HOLDOUT. Do not re-implement any statistic — call `src.gates`. Do not let the ledger be
written from either page. Do not let the red-team page generate test code — the 11 are fixed.

**Effort:** ~6h  (≈ 3.5h Gates + 2.5h Red-Team)

---

# PHASE D6 — Memory + LLM Agents

**Objective:** the two "read a store / config and display it" pages — the six memory stores with their
guards, and the eight agents with their routing and the research corpus.

**Depends on:** D0, `src.memory` / `src.config` / `src.agents` (**import only — no live client**), the
memory files, `data/corpus/anomalies.json`, `src/agents/prompts/*.txt`. Cache: `corpus_family_counts`,
`agents_token_budget`. **Blocks:** nothing.

## Standalone context
Both pages are mostly non-interactive: they render what a store or a config already contains. The
memory stores are likely **empty** (the loop has not run) — both pages must show that honestly plus a
fixture example.

## Inputs
- `src.memory` (`Memory`, `LessonStore`, `BanditState`, `AlphaCardStore`, `AcceptedBook`) —
  `lineage_path` is a **method** on `Memory` / `AlphaCardStore`, not a module function (§0.5).
  `data/memory.db` / `data/lessons.db` / `data/bandit_state.json`, all read via
  `data._readonly_sqlite` / the JSON-tolerant `load_bandit` (§0.8.1).
- `src.config` LLM block (`LLM_MODEL_CHAINS`, `LLM_ROLE_TIER`, `LLM_TPM`, `LLM_TPD_CAP`, `LLM_RPM`,
  `LLM_RPD`, `LLM_MODEL_LIMITS`, `LLM_TOKENS_PER_THESIS_PROJECTION`) and **`src.config.AGENT_ROLES`**
  — it is *not* exported by `src.agents`. Plus `src.agents.load_corpus`, `src.agents.retrieve`,
  `src.agents.RED_TEAM_MENU`, the prompt files.

## Outputs
- `dashboard/pages/07_Memory.py`, `dashboard/pages/08_LLM_Agents.py`.
- `tests/test_dash_p6_memory_agents.py`.

## Steps — `07_Memory.py`
1. **The six stores** — a diagram/table: formula index + card store + lineage (in `memory.db`), the
   lesson store (physically separate `lessons.db`), the bandit (`bandit_state.json`), the book
   (`book.parquet`). "Exact stores and semantic stores are physically separate — a multiple-testing
   count cannot be 'approximately right'."
2. **Lesson store** — a table of every lesson: `motif`, `parent_context`, `outcome`, `p_helps`,
   `confidence`, `n_observations`, `family`, `veto`. Empty is fine — show it + a fixture example.
3. **The guards** — callouts: **confidence gating** (not applied as a prior until `n_observations ≥ 3`)
   and the **asymmetric, sticky veto** (`n_obs ≥ 3` **and** ≥ 2 high-confidence failures; successes
   never lift it). "`confidence` is reliability, not direction — a reliably-harmful motif has high
   `confidence`, low `p_helps`."
4. **Second-order overfitting** — the explainer: "if Reflection writes 'momentum fails' after three
   failures and the Planner defunds momentum, an irreversible call was made on n = 3, and it never
   shows up in any backtest." The two defences: confidence gating + the exploration floor.
5. **Bandit** — `BanditState.allocation()` as a bar per family, with a horizontal line at the **5%
   exploration floor**; `last_k_deltas` sparkline per family; `n_pulls` / `cumulative_reward` /
   `tokens_spent` in a table.
6. **Lineage** — pick a card → `Memory(...).lineage_path(card_id)` (a **method**) → render the parent
   chain as a tree. Handle the no-cards case; render a fixture 3-generation chain from
   `fixtures.fake_cards(3)` on demand.
7. **The book** — if `AcceptedBook` is non-empty: the accepted factors + their pairwise correlation
   heatmap. Else the empty state.

## Steps — `08_LLM_Agents.py`
1. **The eight agents** — a table: role, tier (`LLM_ROLE_TIER`), model chain (`LLM_MODEL_CHAINS`), one
   line on what it does, output schema keys, calls/thesis (`agents_token_budget`). Callout:
   "Deterministic computations are **not** agents — the backtester, the statistics, the novelty check
   are plain code, so their verdicts cannot be talked around."
2. **Model routing** — the fallback-chain idea, the startup availability probe, why no model ID is
   hard-coded. ⚠️ **Render the chains from `src.config.LLM_MODEL_CHAINS` — never type a model ID into
   this page.** (An earlier draft of this plan named `llama-3.1-8b-instant` as the cheap tier; that
   model now 404s and the chain has changed twice. Naming one in prose is exactly the failure the
   config comment warns about.) Do show the *story*: PRE_BUILD_TASKS T3 guessed, `models.list()`
   settled it on 2026-09-04, and three of the originally-planned IDs were already gone — which is the
   argument for a probed fallback chain rather than a pinned model. Provider: **Groq**;
   `LLM_MODE=mock` runs everything offline.
3. **The token budget** — `agents_token_budget` bar (tokens/thesis per role, large vs small tier); the
   projection: ~16.6 calls, ~26,500 tokens/thesis, ~20 theses/day ceiling; the TPM bucket + TPD
   counter + `BudgetExhausted` → resumable checkpoint. Also render **`src.config.LLM_MODEL_LIMITS`** —
   the per-*model* measured TPM/RPD table. It is stronger evidence than the per-tier constants
   (measured live, and it shows limits genuinely vary by model), and it is why the budget is modelled
   per model rather than per tier.
4. **The pre-registered sign** — a diagram: thesis → canonical JSON → `sha256` → timestamp (stored
   **before** any backtest) → later `check_sign(pre, realized)`; a mismatch is a **thesis failure**,
   not a sign flip. "Every factor `f` has a mirror `−f`; without pre-commitment you test both and log
   one. And an LLM shown the result first will narrate a mechanism for noise."
5. **Corpus browser** — `load_corpus()` as a filterable table (family, `tradeable_with_our_data`
   toggle); click an entry → its full record (mechanism, counterparty, horizon, evidence,
   known_decay). `corpus_family_counts` bar. "53 entries, 17 not tradeable — the flag lets the
   Librarian tell the Hypothesis agent 'real anomaly, but we have no fundamentals — don't propose it'."
6. **Retrieval demo** — a family + keyword box → `src.agents.retrieve(...)` → the returned entries.
   "Keyword + family filtering. ~53 entries — embeddings unnecessary, no vector DB."
7. **Prompt viewer** — a role dropdown → the `prompts/<role>.txt` contents, with the
   `=== DYNAMIC ===` split highlighted.

## Acceptance
- [ ] **Memory:** every store renders (real data or a labelled empty state) with no traceback. The
      bandit chart shows the 5% floor line even when all families are at 0 pulls. The lineage viewer
      handles "0 cards" and renders a fixture chain on demand.
- [ ] **LLM Agents:** all 8 roles appear with the tier that `src.config.LLM_ROLE_TIER` assigns (test
      asserts equality). The corpus browser shows `len(load_corpus())` entries and the count of
      `tradeable_with_our_data == False` (report both). The retrieval demo on `family="liquidity"`
      returns only liquidity-family entries. The prompt viewer renders all 8 files.
- [ ] **No hard-coded model ID anywhere in `08_LLM_Agents.py`** — a test greps the page source for
      `gpt-oss`, `llama`, `qwen` and asserts zero literal matches; every ID on screen comes from
      `src.config.LLM_MODEL_CHAINS` / `LLM_MODEL_LIMITS` at render time.
- [ ] **No network, no `groq` import, no `LLMClient` constructed** — a test asserts the LLM Agents page
      module does not import `groq` and does not call `build_agents` / `get_client` / any agent
      `.run()`.
- [ ] Both pages cold-load in **< 3 s**.
- [ ] `pytest tests/test_dash_p6_memory_agents.py -q` passes.

## Do NOT
Do not write to any memory store. Do not install a vector DB. Do not construct a live LLM client or
call an agent's `run()`. Do not hard-code a model ID in the page — read `src.config`.

**Effort:** ~4h  (≈ 2h Memory + 2h LLM Agents)

---

# PHASE D7 — Narrative & example pages: The Loop, Alpha Cards, System Evaluation, Bad Examples

**Objective:** the four curated-story pages — **one for the built-and-verified P10 loop**, two for
parts of the system P11/P12 will fill in, and one for the three failure examples Trexquant asked for.

**Depends on:** D0 (`lib/engine`), D2 (`flow.render`, `narrative.block`), D4
(`engine.eval_formula` / `run_backtest`), `src.loop` (**metadata + checkpoint read only — never
`run_loop`**), `src.gates.check_sign`, `src.redteam`, `src.contracts.validate_card`, `src.memory`,
the supplied constituent CSV. **Blocks:** nothing.

> ⚠️ **Sequencing (read before starting).** This phase splits cleanly and *should* be split while
> P11/P12 are in flight:
> - **`10_The_Loop.py` and `13_Bad_Examples.py` can be built now.** P10 is done and signed off
>   (`reports/p10_handoff.md`), so 10 is a real data page, not a placeholder. 13 needs only the
>   supplied CSV, `engine.leaky_signal()` and `check_sign` — nothing from P11.
> - **`11_Alpha_Cards.py` and `12_System_Evaluation.py` should wait for P11/P12.** Building them
>   against "0 cards / pending banner" and then rebuilding against real cards is the same total effort
>   twice. If you are told to build them anyway, build them fixture-first per the steps below.

## Standalone context
`10_The_Loop` is a **live page over P10's checkpoint** — it is the dashboard's answer to "how does the
system improve over iterations", one of the four graded questions, and it must not be shipped as prose.
`11`/`12` are "design now, live data later" pages with a `pending_banner`; `11_Alpha_Cards` is
**fully functional the moment a card JSON exists**. `13_Bad_Examples` is the three-beat failure story
(`IMPLEMENTATION_PLAN.md` Phase 11 §②③④, `FLOW_EXPLAINED.md` **PART 8**) — example ① is data-backed
today, ②③ are reproducible live demos. Grouped because all four are curated narrative rather than data
plumbing.

## Inputs
- `IMPLEMENTATION_PLAN.md` Phase 10 / 11 / 12, `INITIAL_PLAN.md` §10, `FLOW_EXPLAINED.md`
  **PARTS 7 and 8** *(there is no PART 3 — see the D2 citation note)*, `reports/p10_handoff.md`.
- `src.loop` (`RunResult`, `portfolio_combine`, `curriculum_regimes`, `rolling_fdr`, `MAX_VARIANTS`,
  `FRESHFOLD_MIN_T`, `CURRICULUM_ROTATION`, `FDR_TIGHTEN_THRESHOLD`), `data/loop_checkpoint.db` and
  `reports/p10_loop_report.md` via `data.load_loop_run_state()` / the `loop_generations` cache.
- `artifacts/cards/*.json`, `data/memory.db` card store, `reports/p11_demo.md` / `p12_*` when they land.
- The supplied CSV (`src.universe.SUPPLIED_CSV`), `src.universe.NSE_CURRENT_LIST`, `data/universe/*`.
  `engine.ensure_panel()`, `src.gates`, `src.redteam`.

## Outputs
- `dashboard/pages/10_The_Loop.py`, `dashboard/pages/11_Alpha_Cards.py`,
  `dashboard/pages/12_System_Evaluation.py`, `dashboard/pages/13_Bad_Examples.py`.
- `tests/test_dash_p7_narrative.py`.

## Steps — `10_The_Loop.py`  *(P10 is BUILT — this is a live page, not a placeholder)*

**No `pending_banner`.** P10 is signed off. If no run has happened yet (`data.available()["loop"]`
is False) the page shows `ui.data_missing("a loop run", "python -m src.loop  (P11 owns the real run)")`
for the *data* sections only and still renders every design section below.

1. `flow.render("loop_graph")` + framing prose, annotated with the real node names from
   `src/loop.py` so the diagram and the code agree: `orchestrate → retrieve → brief → ideate →
   gate_a_economics → code → prefilter → tier1 → judge → {refine ↺ code | promote | force_decision}
   → freshfold → tier2 → gate_b_novelty → gate_b_stats → gate_c_redteam → emit_card → reflect`.
   Note the one structural subtlety from `reports/p10_handoff.md` §7: **`reflect → should_continue →
   orchestrate` is the OUTER loop (`run_loop`), not a graph edge.**
2. The **three enforcement points**, each with the constant read live from `src.loop`:
   the variant cap (`MAX_VARIANTS` = 20, the `judge→code` counter, `force_decision` when it trips;
   why — best of N noise ≈ √(2 ln N)); the fresh fold (search on VAL_A, the one winner confirmed on
   VAL_B at `FRESHFOLD_MIN_T`, no holdout peek spent); Gate B ordering (novelty before statistics).
   State that these are **verified by test, not asserted**: `RunResult.max_variant_count()`,
   `.val_b_before_promote()`, `.novelty_always_before_stats()`, `.holdout_only_with_token()` — quote
   the measured values from `reports/p10_handoff.md` §2 and name the test that proves each.
3. **Run summary** (from `data.load_loop_run_state()`): status, `stopped_reason`, generations run,
   accepted card ids, `n_trials`, holdout peeks used / 12, the **final** `t_stat_bar` and
   `min_marginal_ic` next to their starting values, token spend (`large_used` / `small_used`,
   `budget_day`), and the `state_digest`. A KPI row.
4. **Per-generation table + charts** from the `loop_generations` cache: one row per generation with
   `family`, `verdict`, `reject_reason`, `variant_count`, `tier1_rank_ic`, `fresh_fold_rank_ic`,
   `marginal_ic`, `redteam_verdict`. Charts:
   - `variant_count` per generation with a reference line at 20 — does the cap actually bind?
   - **rejection reasons stacked by generation** — the fake-learning read (see `12_System_Evaluation`):
     falling *volume* = genuine improvement; same volume in new clothes = drift. Say which one this
     run shows, including if it is the unflattering answer.
   - the funnel: theses → passed Gate A → promoted → held the fresh fold → passed Gate B → survived
     Gate C → accepted.
5. **Curriculum rotation** — `curriculum_regimes(gen)` / `CURRICULUM_ROTATION`: the mandatory regime
   per generation next to `mandatory_regimes` actually recorded in each row. "The Planner cannot spend
   a whole run in the market it likes."
6. **FDR auto-tightening** — plot `rolling_fdr(generations)` against `FDR_TIGHTEN_THRESHOLD` (0.33) and
   mark every generation where `t_stat_bar` / `min_marginal_ic` stepped up. "The bar rises when the
   system starts being wrong — a control loop on the gate, not a fixed constant."
7. **The stop rule** — budget exhausted (`BudgetExhausted` → checkpoint, resumable) OR `STOP_K_DEFAULT`
   consecutive generations under the novelty-adjusted marginal-IC epsilon OR the generation cap. Show
   which one fired.
8. **Checkpoint / resume** — the `SqliteSaver` design and *why* it exists: the ~20-thesis/day free-tier
   ceiling means a real run spans days. Show `next_gen` / `incomplete_gen` and the last `updated`
   timestamp. Note the deliberate choice not to use `langgraph-checkpoint-sqlite`
   (`reports/p10_handoff.md` §6).
9. **Portfolio combination (off-loop)** — `src.loop.portfolio_combine`'s output: the accepted-signal
   correlation matrix (heatmap), the inverse-correlation weights (bar), and combined vs individual
   RankIC with the `beats_best_individual` flag. Explain **why it is off the main loop**: Trexquant
   grades the signal, not the portfolio, and "does this add new information?" is already Gate B's job.
   With < 2 accepted cards the function returns `status:"insufficient"` — render that honestly and note
   that P11 demonstrates the mechanism (including **regime weight-gating**) on a synthetic set.
   *(If P11 has landed, prefer `artifacts/portfolio_report.md` and show the regime-gated weights too.)*
10. If no run exists: every design section above still renders; the data sections show the empty state
    plus a `fixtures.fake_loop_generations()` preview behind a "preview with a sample run" toggle,
    clearly labelled as fake.

## Steps — `11_Alpha_Cards.py`
1. `ui.pending_banner("Alpha Cards", "P11 (a run that produces a card)")` — P10 is built, so the only
   thing missing is a run. The page is **fully functional** the moment a card JSON exists, and the
   banner must disappear on its own when `data.available()["cards"]` turns True.
2. The card **schema walkthrough** (`IMPLEMENTATION_PLAN.md` §0.5) — every field explained.
3. A **gallery**: read `artifacts/cards/*.json` **and** the `AlphaCardStore` index; best-effort
   `validate_card`; cards as tiles filterable by `verdict ∈ {accept, reject, revise, provisional}`,
   thesis, generation.
4. A **detail view**: thesis (mechanism / counterparty / why-not-arbitraged / horizon / regime /
   falsifiable claim), the pre-registered sign + hash, the formula + its AST tree (`flow`/`ast_tools`),
   `complexity`, tier1 / fresh-fold / tier2 metrics, `charts.decay_curve`, the audit block (marginal
   IC, DSR, t, PBO, `n_trials_global`, `n_trials_effective`, `holdout_peek_id`), the red-team report,
   the lineage chain, `provenance.fields_used`.
5. If **0 cards**: say so, and render `fixtures.fake_cards(1)` behind a "preview with a sample card"
   toggle.

## Steps — `12_System_Evaluation.py`
1. `ui.pending_banner("System evaluation & ablation", "P12 (src/evaluation.py)")`.
2. The metric definitions: **Yield** (hypotheses → accepted cards, tokens per accepted alpha, marginal
   IC per generation, diversity); **Honesty** (FDR = accepted-but-fails-holdout ÷ accepted, DSR
   distribution, sign-agreement rate); **Efficiency** (real alpha per token).
3. The **ablation table** format: per gate — catch rate, false-kill rate, FDR gate-on vs gate-off,
   with the seeded-pool description (~10 predictive / 10 noise / 10 overfit / 10 leaky).
4. The **fake-learning** check: rejections per generation, per-gate pass rate over time,
   rejection-reason distribution — "genuine improvement = falling error *volume*; drift = the same
   volume in new clothes." Placeholder chart shapes, visibly labelled.
5. Live placeholder: render `reports/p12_system_evaluation.md` (and glob any `reports/p12_*.parquet` /
   `.csv`) if it appears — but do **not** hard-code a schema P12 has not committed to; discover
   columns at read time. Cross-link the fake-learning chart to `10_The_Loop` step 4, which computes
   the same rejection-volume trend from the real P10 checkpoint — that part is live today.

## Steps — `13_Bad_Examples.py`
1. **① DATA — the universe source was structurally broken.**
   - *Naive:* load the supplied CSV; show it passes every superficial check — 37 snapshots, exactly
     200 names per row, dead companies (DHFL, RCOM, SUZLON) retained.
   - *Caught:* compute and show — **N of today's NIFTY 200 heavyweights never appear in it** (name the
     list: RELIANCE, TCS, SBIN, MARUTI, TATASTEEL, ONGC …), each with **zero inclusion/exclusion
     events**; the padded-to-200-with-mid-caps pattern. "Caught by external reconciliation against
     NSE's own list — **not** by any statistical gate. DSR, PBO, purge/embargo and the lag test would
     all pass it silently, because it contaminates the *universe*, not any one factor."
   - *Fix:* Phase 1 — rebuild from bhavcopy as the top 200 by trailing turnover; link to the Universe
     page's flat-coverage chart as the proof.
2. **② STATISTICS — look-ahead leakage.**
   - *Naive:* `engine.leaky_signal()` → `engine.run_backtest` on `val_a` → a spectacular RankIC.
   - *Caught:* `src.redteam` test 5 (`extra_lag=1`) → RankIC collapses to ~0. Show that
     `deflated_sharpe_ratio` on the pre-lag series would have **passed** it. "Statistical gates catch
     over-searching, not cheating — different problems, different mechanisms."
   - *Fix:* the causal operator library + per-field timing rules (link to the Operators page).
3. **③ ECONOMICS — right answer, wrong reason.**
   - *Naive:* a data-mined signal with a good IC whose **realised sign is opposite** its pre-registered
     sign. Construct one deterministically; show the IC.
   - *Caught:* `check_sign(pre_registered_sign=+1, realized_sign=-1)` → `False` → **rejected as a
     thesis failure**. "No purely statistical gate would ever have flagged it."
   - *Fix:* reject, and record that this mechanism family produces direction-unstable stories (link to
     the Memory page).
4. Each example: a clear three-beat layout, every number computed live or from a seeded cache, a
   "reproduce this" code snippet.

## Acceptance
- [ ] `10`/`11`/`12` render with no traceback on a clean repo (`11`/`12` with their pending banner;
      **`10` has no pending banner** — P10 is built).
- [ ] `11_Alpha_Cards.py` correctly shows "0 cards" now, and — with `fixtures.fake_cards(1)` written to
      `artifacts/cards/` in the test — renders a full detail view including the AST tree. Test both.
- [ ] `flow.render("loop_graph")` displays on `10_The_Loop.py` and its node names **match the routers
      in `src/loop.py`** — a test asserts every node label in the DOT string is a real key of
      `_make_nodes(...)` (or an explicitly allow-listed label like `START`/`END`). The `12`
      ablation-table format matches `IMPLEMENTATION_PLAN.md` Phase 12.
- [ ] **`10_The_Loop.py` reads the real P10 artifacts**: with `data/loop_checkpoint.db` absent it shows
      the empty state and the fake-run preview; with a checkpoint present (use the one from
      `tests/test_p10_loop.py`'s smoke run, or `src.loop.run_loop(run_id="dash_smoke",
      max_generations=2, checkpoint_path=<tmp>)` in the test **with `LLM_MODE=mock`**) it renders the
      per-generation table, the variant-cap chart and the FDR trace. Report the generation count.
- [ ] The three enforcement points quote the **measured** values from `reports/p10_handoff.md` §2
      (variant cap hit exactly 20; `val_b_before_promote() is False`), not restated prose.
- [ ] `portfolio_combine`'s `status:"insufficient"` path renders cleanly with < 2 accepted cards.
- [ ] The page **never** calls `src.loop.run_loop` — a test greps the page source and asserts zero
      matches.
- [ ] **Bad Examples ①** shows a concrete integer count of heavyweights missing from the **real**
      supplied CSV, plus the named list — report the count.
- [ ] **Bad Examples ②** shows the leaky signal's `rank_ic` (> 0.5) and its post-`extra_lag` `rank_ic`
      (< 0.05), both live — report both.
- [ ] **Bad Examples ③** shows `check_sign(+1, -1) == False` rendered, with the constructed signal's IC.
- [ ] Each Bad-Examples beat is explicitly labelled and has a reproduce snippet.
- [ ] All four pages cold-load in **< 3 s** (heavy computes behind buttons / cached).
- [ ] `pytest tests/test_dash_p7_narrative.py -q` passes.

## Do NOT
Do not fabricate metrics — placeholders must be visibly labelled. Do not block the Alpha Cards page
behind the pending banner. Do not fabricate the ① numbers — read the real CSV. Do not touch HOLDOUT for
②. Do not present ③ as a sign to flip and keep — it is a rejection.

**Effort:** ~6h  (≈ 1h Loop + 1.5h Cards + 1h System Eval + 2.5h Bad Examples)

---

# PHASE D8 — Build Log, polish, deploy

**Objective:** the build-log page, a cross-dashboard consistency pass, docs, and a deploy path.

**Depends on:** D0–D7. **Blocks:** nothing (final phase).

## Inputs
- `reports/p0`–`p9_handoff.md`, `reports/dash_p0`–`dash_p7_handoff.md`, the pytest summary.
- All `dashboard/` code.

## Outputs
- `dashboard/pages/14_Build_Log.py`.
- `dashboard/README.md` — complete (run, build cache, deploy, the phase map, troubleshooting).
- `.streamlit/config.toml` — finalised theme.
- `run_dashboard.ps1` (and a `Makefile`/`justfile` target if one exists in the repo).
- `tests/test_dash_e2e.py` — imports every `pages/*.py` and `Home.py`, asserts no import-time
  exception; runs `build_cache.py --check`.
- `reports/dash_p8_handoff.md`.

## Steps
1. **`14_Build_Log.py`**: the phase timeline (system P0–P13 + dashboard D0–D8, each with a status
   pill **derived by globbing `reports/`, never hard-coded** — P11/P12 may land after this page is
   written and it must light up on its own); render each `reports/*_handoff.md` in an expander; the
   acceptance-criteria pass counts as a summary table; the current `pytest -q` result (parse a stored
   summary or run a quick subset).
2. **Consistency pass** — one reviewer-agent walk of every page against §0.7: header present, every
   chart has context + `source_note`, colours from `PALETTE`, prose from `narrative`, missing-data
   paths use `ui.data_missing` + `st.stop()`, no raw full-parquet read, no `src` import outside
   `engine.py` (except the two allowed pages), page-triggered runs use `Ledger(":memory:")`. Fix
   violations; list them in the handoff.
3. **README** — a fresh clone must run the dashboard in **three commands**:
   `pip install -r requirements-dashboard.txt` → `python dashboard/build_cache.py` →
   `streamlit run dashboard/Home.py`. Document `--heavy`, the deploy options, and what each page needs.
4. **Deploy notes** — Streamlit Community Cloud and HF Spaces. State the data-size implication: the
   dashboard needs only the `data/dashboard/` caches + sliced reads, so document a **caches-only**
   deploy that does not ship the multi-GB `ohlcv.parquet` (which pages that page still degrades
   gracefully — the per-symbol candlestick shows `data_missing`).
5. **Theme** — finalise `config.toml`; verify legibility of every chart type in both the default dark
   theme and a forced light theme; fix `PALETTE` if needed. Screenshots to `reports/dash_shots/`.
6. **`test_dash_e2e.py`** + a `run_dashboard.ps1` that builds the cache if stale then launches.

## Acceptance
- [ ] `pytest tests/test_dash_e2e.py -q` passes — every page module imports with no exception.
- [ ] `python dashboard/build_cache.py --check` is green.
- [ ] A fresh-clone dry run (document it) reaches a working dashboard in the three README commands —
      report the wall time.
- [ ] `14_Build_Log.py` renders **every** `reports/p*_handoff.md` present at run time (p0–p10 today,
      p11/p12 automatically once they land — glob, never a hard-coded list) plus dash_p0–dash_p7.
- [ ] The consistency checklist is in the handoff with every item ticked or an issue filed.
- [ ] Every page still cold-loads in **< 3 s**.
- [ ] Both themes are legible (screenshots in `reports/dash_shots/`).

## Do NOT
Do not add a dependency to make it prettier. Do not commit a deploy that ships a paid key or the raw
multi-GB parquet where a caches-only deploy would do.

**Effort:** ~2.5h

---

# EXECUTION ORDER AND PARALLELISM

```
D0 ──┬── D1 ─────────── (cache builder)  ─────┐
     │                                        ├── D3  (Universe + Prices + Feature Panel)
     ├── D2 ─────────── (Home + flow + narrative)
     │        │
     │        ├─(soft)─→ D5  (Gates & Ledger + Red-Team)
     │        └─(soft)─→ D7  (Loop + Cards + System Eval + Bad Examples)
     │
     ├── D4  (Backtester + Operators & Zoo)  ── needs src/ only (exists)
     ├── D5  (Gates & Ledger + Red-Team)     ── needs src/ + D2's flow.render (soft)
     ├── D6  (Memory + LLM Agents)           ── needs src/ only
     └── D7  (narrative & example pages)     ── needs D2 (soft) + D4's engine helpers
                                                        │
              all of the above ────────────────────────┴── D8 (Build Log + polish + deploy)
```

- **D0 first — blocks everything.**
- **D1 and D2 next**, in parallel (D1 = data prep, D2 = narrative/diagrams; no overlap).
- **After D0**: D4 and D6 can start immediately (they need only `src/`). **After D1**: D3.
  **After D2**: D5 and D7 are unblocked cleanly (they can be coded earlier against the
  `NotImplementedError` stubs and will light up when D2 lands). D7 also wants D4's
  `engine.eval_formula` / `run_backtest` for the Bad Examples demos — start D7 after D4, or stub those
  two calls.
- **D8 last.**

| Phase | Pages built | Effort | Parallel-safe with | Model / thinking |
|---|---|---:|---|---|
| D0 Scaffolding | — | 2.5h | — (blocks all) | Sonnet / medium |
| D1 Cache builder | — | 3.5h | D2 | Sonnet / medium–high |
| D2 Home + flow + narrative | Home | 3.5h | D1, D4, D6 | Sonnet / medium |
| D3 Data pages | 01, 02, 03 | 7h | D4, D5, D6, D7 | Sonnet / medium |
| D4 Formula tooling | 04, 05 | 5h | D3, D5, D6 | Sonnet / medium |
| D5 Honesty machinery | 06, 09 | 6h | D3, D4, D6, D7 | Sonnet / high |
| D6 Memory + LLM Agents | 07, 08 | 4h | D3, D4, D5, D7 | Sonnet / medium |
| D7 Narrative & examples | 10, 11, 12, 13 | 6h | D3, D5, D6 (after D2 + D4). **Split it: 10 + 13 now; 11 after P11; 12 after P12** | Sonnet / medium–high |
| D8 Build Log + deploy | 14 | 2.5h | — (last) | Sonnet / medium |

**Total ≈ 40h sequential; ≈ 11–13h with 5 parallel agents** (D0 → {D1, D2} → {D3, D4, D5, D6, D7} → D8).

**Minimum viable path** (the narrative, the three flagship data pages, the honesty machinery, and the
bad examples): `D0 → D1 → D2 → D3 → D5 → D7 → D8` (skip D4 and D6 first pass; D7's Bad Examples then
stubs `engine.eval_formula` / `run_backtest` or borrows them from D5's work).

## Running this dashboard **in parallel with system phases P11 and P12**

**Verified safe — the write sets are disjoint.**

| Track | Writes |
|---|---|
| **P11** (demo run) | `artifacts/cards/*.json`, `artifacts/portfolio_report.md`, `reports/p11_demo.md`, and — via a real loop run — `data/{ledger,memory,lessons}.db`, `data/bandit_state.json`, `data/book.parquet`, `data/loop_checkpoint.db` |
| **P12** (evaluation) | `src/evaluation.py`, `reports/p12_system_evaluation.md`, plots |
| **Dashboard (D0–D8)** | `dashboard/**`, `data/dashboard/**`, `reports/dash_*`, `tests/test_dash_*`, `requirements-dashboard.txt`, `.streamlit/config.toml`, `run_dashboard.ps1` |

No path collides. The dashboard reads P11/P12's outputs and never writes them. **§0.8.1 is what makes
this true in practice** — read-only SQLite snapshots, JSON-tolerant `load_bandit`, staleness reporting,
and no config value copied at author time. A dashboard phase that skips §0.8.1 can stall or crash a
live P11 run; treat it as load-bearing, not defensive polish.

**Recommended split while P11/P12 run:**

```
now, in parallel with P11 + P12:   D0 → D1 → D2 → { D3, D4, D5, D6 }   and D7's 10_The_Loop + 13_Bad_Examples
after P11 lands:                   D7's 11_Alpha_Cards
after P12 lands:                   D7's 12_System_Evaluation
last, after both:                  D8
```

- **D0–D6 touch nothing P11/P12 produce** beyond reading it, and every one of their pages already has
  a defined empty state.
- **`10_The_Loop.py` is buildable today** — P10 is signed off; it reads the checkpoint.
- **`13_Bad_Examples.py` is buildable today** — ① needs only the supplied CSV, ②③ are constructed live.
- **`11_Alpha_Cards` / `12_System_Evaluation` should wait.** Built against "0 cards", they are banners;
  built against real output they are the two most persuasive pages in the deck — same effort, once.
- **D8 must be last** regardless: its consistency pass and build log describe the finished set, and its
  status board should be generated when P11/P12's handoffs exist.

P11 is bounded by the ~20-thesis/day token ceiling and will span days of wall-clock, so parallel
execution here is not merely safe — it is the only way the dashboard is ready when the run finishes.

---

# EXPLICITLY OUT OF SCOPE

| Excluded | Why |
|---|---|
| A React/Next.js frontend + FastAPI backend | Two codebases and an API layer to keep in sync with `src/`; more to break in a live demo. The right move only if this graduates to a maintained product — see §0.11. |
| A separate database / API server | The data is parquet + SQLite + JSON on disk; Streamlit reads it directly. |
| Editing / writing project data from the dashboard | It is a read-only view. The only writes are `data/dashboard/` (cache) and `reports/dash_*`. |
| Live LLM calls / an in-dashboard agent run | P10 **is** built (`src/loop.py`, signed off) — but a run costs tokens, spends real holdout peeks from a lifetime budget of 12, and takes days at the ~20-thesis/day free-tier ceiling. It belongs to P11. The dashboard **reads** the checkpoint (`10_The_Loop.py`) and never calls `run_loop`. The LLM Agents page shows the design, the routing and the corpus — not a run. |
| Running P11 / P12 from the dashboard | Same reason. The dashboard is a read-only view of whatever they have produced so far, and is designed to be safe to open *while* they are running (§0.8.1). |
| Authentication / multi-user / persistence of user state | It is a single-presenter local tool. |
| Real-time / streaming data | The universe of dates is fixed and historical. |
| A vector database for the corpus browser | 53 entries. Keyword + family filtering is instant. |
| Reading HOLDOUT | Sealed. `lib/engine.run_backtest` rejects `split="holdout"`. |
| Splitting the dashboard into more than 9 phases | An earlier 15-phase draft was consolidated — see the header note. If you want maximum agent parallelism back, the merged phases (D3, D4, D5, D6, D7) each split cleanly along their page boundaries. |
