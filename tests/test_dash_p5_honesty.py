"""tests/test_dash_p5_honesty.py — D5 acceptance tests (DASHBOARD_PLAN.md §D5 Acceptance)

Run with:
    pytest tests/test_dash_p5_honesty.py -q

Fast tests (no project data needed) always run: signatures, the DSR presets
(analytic), the measured P(t>3) table, the append-only guarantee, the
over-searching curve, and every page-convention / import-fence check.

A handful of tests exercise the real red-team runner end-to-end against the
real project panel (``data/panel/*``) when it is present — these are the
acceptance criteria that need live data (e.g. "leaky killed by extra_lag") —
and are skipped, not failed, when that data is absent (a fresh clone).
"""
from __future__ import annotations

import ast
import inspect
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PAGES_DIR = PROJECT_ROOT / "dashboard" / "pages"
LIB_DIR = PROJECT_ROOT / "dashboard" / "lib"


def _page_src(name: str) -> str:
    return (PAGES_DIR / name).read_text(encoding="utf-8")


def _has_panel() -> bool:
    from src.config import FEATURES_PARQUET, LABELS_PARQUET
    return Path(FEATURES_PARQUET).exists() and Path(LABELS_PARQUET).exists()


_NEEDS_PANEL = pytest.mark.skipif(not _has_panel(), reason="data/panel/*.parquet absent on this clone")

_D5_PAGES = ["06_Gates_and_Ledger.py", "09_Red_Team.py"]


# ---------------------------------------------------------------------------#
# 1. lib.engine — signatures + import-fence                                  #
# ---------------------------------------------------------------------------#
class TestEngineSignatures:
    def test_run_redteam_ui_signature(self):
        from dashboard.lib import engine as eng

        sig = inspect.signature(eng.run_redteam_ui)
        params = list(sig.parameters)
        assert params == ["formula", "split"], params
        assert sig.parameters["split"].default == "val_a"

    def test_leaky_signal_takes_no_required_args(self):
        from dashboard.lib import engine as eng

        sig = inspect.signature(eng.leaky_signal)
        assert not [p for p in sig.parameters.values() if p.default is inspect.Parameter.empty]

    def test_run_redteam_ui_rejects_holdout(self):
        from dashboard.lib import engine as eng

        with pytest.raises(PermissionError):
            eng.run_redteam_ui("close", "holdout")

    def test_only_engine_imports_src_among_lib_modules(self):
        """Section 0.4 import rule — re-asserted here for the D5 additions
        specifically (flow.py may import src.config only; fixtures.py may
        import src.contracts only; engine.py is the only one with a free hand)."""
        for name in ("charts.py", "data.py", "narrative.py", "ui.py"):
            src = (LIB_DIR / name).read_text(encoding="utf-8")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name.split(".")[0] != "src", f"{name} imports {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        assert node.module.split(".")[0] != "src", f"{name} imports from {node.module}"


# ---------------------------------------------------------------------------#
# 2. The red-team menu — mirrors src.redteam exactly                         #
# ---------------------------------------------------------------------------#
class TestRedteamMenu:
    def test_menu_matches_src_redteam(self):
        from dashboard.lib import engine as eng
        from src.redteam import DECISIVE_TESTS, REDTEAM_MENU

        got = eng.redteam_menu()
        assert got["menu"] == list(REDTEAM_MENU)
        assert got["decisive"] == list(DECISIVE_TESTS)
        assert len(got["menu"]) == 11
        assert len(got["decisive"]) == 5


# ---------------------------------------------------------------------------#
# 3. Thresholds — read live, match src.gates / src.config exactly            #
# ---------------------------------------------------------------------------#
class TestThresholds:
    def test_thresholds_match_src_live(self):
        from dashboard.lib import engine as eng
        from src import gates as _g
        from src.config import HOLDOUT_PEEK_BUDGET, T_STAT_BAR

        th = eng.thresholds()
        assert th == {
            "T_STAT_BAR": T_STAT_BAR,
            "MIN_MARGINAL_IC": _g.MIN_MARGINAL_IC,
            "DSR_MIN": _g.DSR_MIN,
            "PBO_MAX": _g.PBO_MAX,
            "MIN_DSR_SAMPLE": _g.MIN_DSR_SAMPLE,
            "HOLDOUT_PEEK_BUDGET": HOLDOUT_PEEK_BUDGET,
        }


# ---------------------------------------------------------------------------#
# 4. The DSR calculator presets — the headline claim, reproduced exactly     #
# ---------------------------------------------------------------------------#
class TestDsrPresets:
    def test_headline_200_noise_rejects(self):
        """best-of-200 pure-noise: observed_sr=0.0908, n_trials=200,
        sr_std=0.0335, T=913 -> DSR ~ 0.477 < DSR_MIN (reports/p6_handoff.md
        criterion 3)."""
        from dashboard.lib import engine as eng
        from src.gates import DSR_MIN

        dsr = eng.dsr(0.0908, 200, 0.0335, 0.0, 3.0, 913)
        assert 0.40 < dsr < 0.55, dsr
        assert dsr < DSR_MIN

    def test_five_trial_real_signal_passes(self):
        """A real signal found in 5 trials: observed_sr=0.2338, n_trials=5,
        t~7.07 -> DSR ~ 0.995 >= DSR_MIN (reports/p6_handoff.md criterion 4)."""
        from dashboard.lib import engine as eng
        from src.gates import DSR_MIN, expected_max_sharpe

        sr_std = 0.1463 / expected_max_sharpe(5, 1.0)
        dsr = eng.dsr(0.2338, 5, sr_std, 0.0, 3.0, 913)
        assert dsr > 0.98, dsr
        assert dsr >= DSR_MIN


# ---------------------------------------------------------------------------#
# 5. The over-searching curve + the measured P(t>3) table                    #
# ---------------------------------------------------------------------------#
class TestOversearchingCurve:
    def test_curve_shape_and_monotonic_N(self):
        from dashboard.lib import engine as eng

        df = eng.oversearching_curve(draws=500)   # small draw count — fast, deterministic (seeded)
        assert list(df["N"]) == sorted(df["N"])
        assert (df["sqrt_2lnN"] >= df["bailey_ldp_E_max"]).all()

    def test_bailey_curve_matches_src_gates(self):
        from dashboard.lib import engine as eng
        from src.gates import expected_max_sharpe

        df = eng.oversearching_curve(draws=500)
        for n, v in zip(df["N"], df["bailey_ldp_E_max"]):
            assert v == pytest.approx(expected_max_sharpe(int(n), 1.0))

    def test_measured_p_table_matches_plan(self):
        from dashboard.lib import engine as eng

        assert eng.MEASURED_P_T_GT_3 == {5: 0.7, 20: 2.7, 100: 12.6, 200: 23.6, 500: 49.1}


# ---------------------------------------------------------------------------#
# 6. The append-only guarantee                                               #
# ---------------------------------------------------------------------------#
class TestAppendOnly:
    def test_assert_ledger_append_only_passes(self):
        from dashboard.lib import engine as eng

        ok, msg = eng.assert_ledger_append_only()
        assert ok is True
        assert "PASS" in msg


# ---------------------------------------------------------------------------#
# 7. Never touches data/ledger.db for write — asserted structurally          #
# ---------------------------------------------------------------------------#
class TestLedgerNeverWritten:
    def test_run_redteam_ui_uses_in_memory_ledger(self):
        src = (LIB_DIR / "engine.py").read_text(encoding="utf-8")
        # the run_redteam(...) call inside run_redteam_ui must pass an
        # in-memory Ledger and liquidity_ranks=, never a bare Ledger()/LEDGER_DB
        assert 'Ledger(":memory:")' in src
        assert "liquidity_ranks=ranks" in src or "liquidity_ranks=" in src

    def test_pbo_and_effective_trial_count_never_construct_a_live_ledger(self):
        src = (LIB_DIR / "engine.py").read_text(encoding="utf-8")
        assert "Ledger(LEDGER_DB)" not in src
        assert "Ledger()" not in src


# ---------------------------------------------------------------------------#
# 8. Page conventions (mirrors the D3 test style)                            #
# ---------------------------------------------------------------------------#
class TestPageConventions:
    @pytest.mark.parametrize("page", _D5_PAGES)
    def test_page_parses(self, page):
        ast.parse(_page_src(page))

    @pytest.mark.parametrize("page", _D5_PAGES)
    def test_has_set_page_config(self, page):
        assert "st.set_page_config" in _page_src(page)

    @pytest.mark.parametrize("page", _D5_PAGES)
    def test_has_phase_tag_d5(self, page):
        src = _page_src(page)
        assert 'phase_tag="D5"' in src or "phase_tag='D5'" in src

    @pytest.mark.parametrize("page", _D5_PAGES)
    def test_has_data_missing_and_stop(self, page):
        src = _page_src(page)
        assert "data_missing" in src
        assert "st.stop()" in src

    @pytest.mark.parametrize("page", _D5_PAGES)
    def test_no_inline_hex_colours(self, page):
        """Colours come from charts.PALETTE — no inline hex in a page (§0.7 rule 9)."""
        src = _page_src(page)
        hits = re.findall(r"""['"]#[0-9A-Fa-f]{3,8}['"]""", src)
        assert not hits, hits

    @pytest.mark.parametrize("page", _D5_PAGES)
    def test_pages_do_not_import_src_directly(self, page):
        """Only pages 05/08 may import src.* directly (Section 0.4) — 06/09 must not."""
        src = _page_src(page)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] != "src", f"{page} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert node.module.split(".")[0] != "src", f"{page} imports from {node.module}"

    @pytest.mark.parametrize("page", _D5_PAGES)
    def test_never_writes_data_ledger_db(self, page):
        """Neither page constructs Ledger(...) itself — all red-team access goes
        through dashboard.lib.engine.run_redteam_ui, which uses ':memory:'.
        (Prose mentioning ``Ledger(":memory:")`` inside a string literal is
        fine — only an actual call node counts.)"""
        tree = ast.parse(_page_src(page))
        calls = [n for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and ((isinstance(n.func, ast.Name) and n.func.id == "Ledger")
                     or (isinstance(n.func, ast.Attribute) and n.func.attr == "Ledger"))]
        assert not calls, [ast.dump(c) for c in calls]

    def test_gates_page_shows_gate_b_diagram_and_narrative(self):
        src = _page_src("06_Gates_and_Ledger.py")
        assert 'flow.render("gate_b")' in src
        assert 'narrative.block("gate_b_order")' in src

    def test_redteam_page_never_reads_holdout(self):
        src = _page_src("09_Red_Team.py")
        assert '"holdout"' in src  # only in the rejection guard
        assert "st.selectbox(\"Split\", [\"val_a\", \"val_b\"]" in src \
            or 'st.selectbox("Split", ["val_a", "val_b"]' in src


# ---------------------------------------------------------------------------#
# 9. Live acceptance criteria — need the real project panel                  #
# ---------------------------------------------------------------------------#
class TestLiveRedteam:
    @_NEEDS_PANEL
    def test_leaky_signal_is_killed_by_extra_lag(self):
        from dashboard.lib import engine as eng
        from src.config import LEDGER_DB

        mtime_before = Path(LEDGER_DB).stat().st_mtime if Path(LEDGER_DB).exists() else None

        result = eng.run_redteam_ui("__leaky__", "val_a")

        assert result["verdict"] == "killed"
        assert "extra_lag" in result["failed_tests"]
        assert result["baseline"]["rank_ic"] > 0.9          # leaked look-ahead: RankIC ~ 1
        assert result["results"]["extra_lag"]["rank_ic_lagged"] < 0.3 * result["baseline"]["rank_ic"]
        assert result["counts_as_trial"] == 0

        mtime_after = Path(LEDGER_DB).stat().st_mtime if Path(LEDGER_DB).exists() else None
        assert mtime_before == mtime_after, "data/ledger.db was touched by a red-team run"

    @_NEEDS_PANEL
    def test_one_lucky_year_is_killed_by_subsample_year(self):
        from dashboard.lib import engine as eng

        result = eng.run_redteam_ui("__one_lucky_year__", "val_a")
        assert result["verdict"] == "killed"
        assert "subsample_year" in result["failed_tests"]

    @_NEEDS_PANEL
    def test_thin_edge_is_killed_by_cost_sweep(self):
        from dashboard.lib import engine as eng

        result = eng.run_redteam_ui("__thin_edge__", "val_a")
        assert result["verdict"] == "killed"
        assert "cost_sweep" in result["failed_tests"]

    @_NEEDS_PANEL
    def test_assert_ledger_append_only_via_engine_matches_src(self):
        from dashboard.lib import engine as eng
        from src.ledger import assert_no_row_removal_sql

        assert_no_row_removal_sql()   # would raise if it failed
        ok, _ = eng.assert_ledger_append_only()
        assert ok
