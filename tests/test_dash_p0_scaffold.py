"""D0 — dashboard scaffold + shared-contract smoke test.

Asserts the `lib/` module contracts (Section 0.4), the fixture schemas
(Section 0.6), the flow/narrative NotImplementedError discipline, the engine
HOLDOUT tripwire, the import fence, `_readonly_sqlite` safety, and the three
`src/` signature contracts an earlier draft got wrong (Section 0.5).
"""
from __future__ import annotations

import ast
import importlib
import inspect
import shutil
import sqlite3
import time
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "dashboard" / "lib"

LIB_MODULES = ["ui", "fixtures", "data", "charts", "flow", "narrative", "engine"]


# --------------------------------------------------------------------------- #
# every lib module imports                                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mod", LIB_MODULES)
def test_lib_module_imports(mod):
    importlib.import_module(f"dashboard.lib.{mod}")


# --------------------------------------------------------------------------- #
# Section 0.4 — function presence + documented parameter names                 #
# --------------------------------------------------------------------------- #
def _params(fn):
    return list(inspect.signature(fn).parameters)


def test_data_signatures():
    from dashboard.lib import data

    for name in [
        "available", "cache_manifest", "load_cache", "try_cache",
        "load_universe_membership", "load_universe_stats", "load_liquidity_ranks",
        "load_symbols", "load_splits", "load_ohlcv", "load_features", "load_labels",
        "load_corporate_actions", "load_delivery", "load_ledger_trials",
        "load_holdout_peeks", "load_lessons", "load_bandit", "load_cards",
        "load_corpus", "load_handoff", "load_loop_run_state", "load_loop_generations",
        "_readonly_sqlite",
    ]:
        assert hasattr(data, name), f"data.{name} missing"

    assert _params(data.load_ohlcv) == ["symbols", "start", "end", "columns"]
    assert _params(data.load_features) == ["symbols", "columns"]
    assert _params(data.load_labels) == ["symbols", "columns"]
    assert _params(data.load_cache) == ["name"]
    assert _params(data.load_handoff) == ["phase"]

    for const in ["PROJECT_ROOT", "DATA_DIR", "CACHE_DIR", "REPORTS_DIR"]:
        assert isinstance(getattr(data, const), Path)


def test_charts_signatures():
    from dashboard.lib import charts

    assert isinstance(charts.PALETTE, dict)
    for key in ["accent", "accent2", "pos", "neg", "grid", "text", "muted", "cat", "seq", "bg"]:
        assert key in charts.PALETTE
    assert isinstance(charts.TEMPLATE, str)
    for name in ["kpi_row", "line", "bar", "hist", "violin", "box", "heatmap",
                 "stacked_area", "candlestick", "gantt", "scatter", "gauge",
                 "coverage_chart", "decay_curve", "equity_curve", "ic_bar"]:
        assert callable(getattr(charts, name)), name
    assert _params(charts.coverage_chart) == ["daily", "target"]
    assert _params(charts.ic_bar) == ["df", "feature_col", "ic_col", "err_col", "noise_band"]


def test_engine_signatures():
    from dashboard.lib import engine

    assert _params(engine.run_backtest) == [
        "formula", "split", "horizon", "cost_bps", "neutralize", "extra_lag"]
    assert _params(engine.dsr) == [
        "observed_sr", "n_trials", "sr_std", "skew", "kurt", "n_obs"]
    assert _params(engine.expected_max_sr) == ["n_trials", "sr_std"]
    for name in ["ensure_panel", "eval_formula", "run_redteam_ui", "leaky_signal"]:
        assert callable(getattr(engine, name)), name


def test_flow_narrative_name_tuples():
    from dashboard.lib import flow, narrative

    assert flow.DIAGRAMS == (
        "pipeline", "loop_graph", "gate_b", "data_lineage", "phase_dag",
        "card_lifecycle")
    assert set(narrative.BLOCKS) >= {
        "one_liner", "nine_stages", "alpha_card", "three_budgets", "four_regions",
        "five_failures", "sqrt_2lnN", "pre_registered_sign",
        "variant_cap_fresh_fold", "gate_b_order", "novelty_claims", "weak_points",
        "walkthrough", "build_status", "nav_guide"}


# --------------------------------------------------------------------------- #
# Section 0.6 — fake_cache covers every cache file                             #
# --------------------------------------------------------------------------- #
def test_fake_cache_all_names():
    from dashboard.lib import fixtures

    # every §0.6 file is covered
    assert len(fixtures.CACHE_SCHEMAS) >= 26
    for name, schema in fixtures.CACHE_SCHEMAS.items():
        df = fixtures.fake_cache(name)
        assert list(df.columns) == list(schema), name
        for col, dt in schema.items():
            got = str(df[col].dtype)
            if dt == "datetime64[ns]":
                assert got.startswith("datetime64[ns"), (name, col, got)
            elif dt == "bool":
                assert got == "bool", (name, col, got)
            elif dt == "int64":
                assert got.startswith("int"), (name, col, got)
            elif dt == "float64":
                assert got.startswith("float"), (name, col, got)


def test_fake_cards_valid():
    from src.contracts import validate_card

    from dashboard.lib import fixtures

    cards = fixtures.fake_cards(2)
    assert len(cards) == 2
    for c in cards:
        validate_card(c)


def test_fake_loop_generations():
    from dashboard.lib import fixtures

    df = fixtures.fake_loop_generations(6)
    assert list(df.columns) == list(fixtures.CACHE_SCHEMAS["loop_generations"])
    assert len(df) == 6


# --------------------------------------------------------------------------- #
# flow / narrative raise NotImplementedError (not AttributeError)              #
# --------------------------------------------------------------------------- #
def test_flow_render_discipline():
    from dashboard.lib import flow

    # D2 implemented all six — an UNKNOWN name is a KeyError, never AttributeError
    with pytest.raises(KeyError):
        flow.render("does_not_exist")
    for name in flow.DIAGRAMS:
        g = flow.render(name)
        assert hasattr(g, "source") and len(g.source) > 50, name
    assert len(flow.data_regions_timeline().data) >= 1
    rd = flow.region_dates()
    assert set(rd) == {"warmup", "train", "val_a", "val_b", "holdout"}


def test_narrative_block_discipline():
    from dashboard.lib import narrative

    with pytest.raises(KeyError):
        narrative.block("does_not_exist")
    for name in narrative.BLOCKS:
        md = narrative.block(name)
        assert md.strip().splitlines()[-1].startswith("_Source:"), name


# --------------------------------------------------------------------------- #
# engine — ensure_panel bool, HOLDOUT tripwire, dsr passthrough                #
# --------------------------------------------------------------------------- #
def test_ensure_panel_returns_bool():
    from dashboard.lib import engine

    assert isinstance(engine.ensure_panel(), bool)


def test_run_backtest_rejects_holdout():
    from dashboard.lib import engine

    with pytest.raises((PermissionError, ValueError)):
        engine.run_backtest("rank(close)", "holdout")
    with pytest.raises((PermissionError, ValueError)):
        engine.run_redteam_ui("rank(close)", "holdout")


def test_dsr_passthrough():
    from dashboard.lib import engine

    v = engine.dsr(7.07, 5, 0.5, 0.0, 3.0, 800)
    assert 0.0 <= v <= 1.0
    assert engine.expected_max_sr(200, 0.1) > engine.expected_max_sr(5, 0.1)


# --------------------------------------------------------------------------- #
# coverage_chart really fits a trend line                                      #
# --------------------------------------------------------------------------- #
def test_coverage_chart_returns_fig_and_dict():
    import plotly.graph_objects as go

    from dashboard.lib import charts, fixtures

    fig, meta = charts.coverage_chart(fixtures.fake_cache("universe_daily_coverage"),
                                      target=200)
    assert isinstance(fig, go.Figure)
    assert "slope_per_year" in meta and "verdict" in meta
    assert meta["verdict"] in ("FLAT", "SLOPING")

    # a deliberately sloping series -> SLOPING, slope ~ +20/yr
    d = pd.DataFrame({
        "date": pd.bdate_range("2015-01-01", periods=2600),
        "n_members": [100 + i * (20 / 260) for i in range(2600)],
    })
    _, meta2 = charts.coverage_chart(d)
    assert meta2["verdict"] == "SLOPING"
    assert meta2["slope_per_year"] > 10


# --------------------------------------------------------------------------- #
# import fence — only engine/fixtures/flow may touch src, narrowly             #
# --------------------------------------------------------------------------- #
_ALLOWED_SRC = {
    "engine": None,                # any src compute
    "fixtures": {"src.contracts"},
    "flow": {"src.config"},
}


@pytest.mark.parametrize("mod", LIB_MODULES)
def test_import_fence(mod):
    tree = ast.parse((LIB / f"{mod}.py").read_text(encoding="utf-8"))
    src_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "src" or a.name.startswith("src."):
                    src_imports.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "src" or node.module.startswith("src.")):
                src_imports.add(node.module)

    if mod not in _ALLOWED_SRC:
        assert not src_imports, f"{mod} imports src: {src_imports}"
    else:
        allowed = _ALLOWED_SRC[mod]
        if allowed is not None:
            assert src_imports <= allowed, f"{mod} imports {src_imports - allowed}"


# --------------------------------------------------------------------------- #
# Section 0.5 — the three signature contracts an earlier draft got wrong        #
# --------------------------------------------------------------------------- #
def test_run_redteam_signature_truth():
    from src.redteam import run_redteam

    sig = inspect.signature(run_redteam)
    params = list(sig.parameters.values())
    assert params[1].name == "tests", "2nd positional must be `tests`"
    assert sig.parameters["split"].kind is inspect.Parameter.KEYWORD_ONLY


def test_walk_forward_signature_truth():
    from src.gates import walk_forward

    sig = inspect.signature(walk_forward)
    assert "start" in sig.parameters and "end" in sig.parameters
    assert "split" not in sig.parameters


def test_lineage_path_is_method_not_module_function():
    import src.memory as memory

    assert not hasattr(memory, "lineage_path"), "lineage_path must NOT be module-level"
    assert callable(getattr(memory.Memory, "lineage_path", None))


# --------------------------------------------------------------------------- #
# _readonly_sqlite never opens a path under data/ for write                    #
# --------------------------------------------------------------------------- #
def test_readonly_sqlite_does_not_mutate_source(tmp_path):
    from dashboard.lib import data

    src_db = tmp_path / "fake_ledger.db"
    conn = sqlite3.connect(src_db)
    conn.execute("CREATE TABLE trials (trial_id INTEGER PRIMARY KEY, x TEXT)")
    conn.execute("INSERT INTO trials (x) VALUES ('a')")
    conn.commit()
    conn.close()

    before = src_db.stat().st_mtime_ns
    time.sleep(0.01)
    ro = data._readonly_sqlite(src_db)
    rows = ro.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
    ro.close()
    after = src_db.stat().st_mtime_ns

    assert rows == 1
    assert before == after, "source db mtime changed — not read-only"


def test_readonly_sqlite_on_real_ledger_is_safe():
    from dashboard.lib import data

    led = data.DATA_DIR / "ledger.db"
    if not led.exists():
        pytest.skip("no data/ledger.db")
    before = led.stat().st_mtime_ns
    conn = data._readonly_sqlite(led)
    conn.execute("SELECT name FROM sqlite_master").fetchall()
    conn.close()
    assert led.stat().st_mtime_ns == before


# --------------------------------------------------------------------------- #
# build_cache registry + reference builders                                    #
# --------------------------------------------------------------------------- #
def test_build_cache_registry():
    from dashboard import build_cache

    assert len(build_cache._REGISTRY) >= 20
    assert "corpus_family_counts" in build_cache._REGISTRY
    assert "agents_token_budget" in build_cache._REGISTRY


def test_build_cache_reference_builders_and_check(tmp_path, monkeypatch):
    from dashboard import build_cache

    monkeypatch.setattr(build_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(build_cache, "MANIFEST", tmp_path / "_manifest.json")

    build_cache.run_builders(["corpus_family_counts", "agents_token_budget"], heavy=False)
    assert (tmp_path / "corpus_family_counts.parquet").exists()
    assert (tmp_path / "agents_token_budget.parquet").exists()
    manifest = build_cache._load_manifest()
    assert set(manifest) == {"corpus_family_counts", "agents_token_budget"}
    assert build_cache.check() == 0

    tb = pd.read_parquet(tmp_path / "agents_token_budget.parquet")
    assert list(tb.columns) == ["role", "tier", "calls_per_thesis", "tokens_per_thesis"]
    assert len(tb) == 8
    assert 24_000 <= tb["tokens_per_thesis"].sum() <= 29_000  # ~26,500


def test_build_cache_determinism(tmp_path, monkeypatch):
    from dashboard import build_cache

    monkeypatch.setattr(build_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(build_cache, "MANIFEST", tmp_path / "_manifest.json")
    build_cache.run_builders(["corpus_family_counts"], heavy=False)
    h1 = (tmp_path / "corpus_family_counts.parquet").read_bytes()
    build_cache.run_builders(["corpus_family_counts"], heavy=False)
    h2 = (tmp_path / "corpus_family_counts.parquet").read_bytes()
    assert h1 == h2
