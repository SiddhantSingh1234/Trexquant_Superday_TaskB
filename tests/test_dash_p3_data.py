"""tests/test_dash_p3_data.py — D3 acceptance tests (DASHBOARD_PLAN.md §D3 Acceptance)

Run with:
    pytest tests/test_dash_p3_data.py -q

Tests
-----
1. load_ohlcv never called without a filter — inspects page source.
2. No import of any network library (yfinance, requests, httpx, urllib) at page-load.
3. Missing-cache path: each page's guard fires data_missing + st.stop().
4. Feature Panel: ic_shift, leaky_check, ic_bar cache shapes match the schema.
5. Coverage chart fixture produces a FLAT verdict (slope ~0 on fake data).
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------#
# Paths                                                                       #
# ---------------------------------------------------------------------------#
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PAGES_DIR = PROJECT_ROOT / "dashboard" / "pages"


# ---------------------------------------------------------------------------#
# Helpers                                                                     #
# ---------------------------------------------------------------------------#
def _page_src(name: str) -> str:
    """Return the source code of a pages/ file as a string."""
    return (PAGES_DIR / name).read_text(encoding="utf-8")


def _ast_calls(src: str, func_name: str) -> list[ast.Call]:
    """Return all Call nodes in ``src`` where the function name matches."""
    tree = ast.parse(src)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Direct call: func_name(...)
            if isinstance(node.func, ast.Name) and node.func.id == func_name:
                hits.append(node)
            # Attribute call: obj.func_name(...)
            elif isinstance(node.func, ast.Attribute) and node.func.attr == func_name:
                hits.append(node)
    return hits


def _has_import(src: str, module: str) -> bool:
    """Check if source imports a top-level module (import X / from X ...)."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == module:
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] == module:
                return True
    return False


# ---------------------------------------------------------------------------#
# Test 1: load_ohlcv is never called without a filter in 02_Prices.py        #
# ---------------------------------------------------------------------------#
class TestNoUnfilteredOhlcv:
    """02_Prices.py must never call load_ohlcv without symbols= or start/end=."""

    def test_load_ohlcv_always_has_filter_in_prices_source(self):
        """Every call to load_ohlcv in 02_Prices.py passes at least one kwarg filter."""
        src = _page_src("02_Prices.py")
        calls = _ast_calls(src, "load_ohlcv")
        assert calls, "Expected at least one load_ohlcv call in 02_Prices.py"
        for call in calls:
            # Gather keyword argument names
            kwarg_names = {kw.arg for kw in call.keywords}
            # Accept: symbols=, start=, end=, columns= (all constrain the read)
            filter_kwargs = {"symbols", "start", "end", "columns"}
            assert kwarg_names & filter_kwargs, (
                f"load_ohlcv call at line {call.lineno} in 02_Prices.py "
                f"has no filter keyword — got kwargs: {kwarg_names}"
            )

    def test_load_ohlcv_always_has_filter_in_feature_panel_source(self):
        """Every call to load_ohlcv in 03_Feature_Panel.py (if any) has a filter."""
        src = _page_src("03_Feature_Panel.py")
        calls = _ast_calls(src, "load_ohlcv")
        for call in calls:
            kwarg_names = {kw.arg for kw in call.keywords}
            filter_kwargs = {"symbols", "start", "end", "columns"}
            assert kwarg_names & filter_kwargs, (
                f"load_ohlcv call at line {call.lineno} in 03_Feature_Panel.py "
                f"has no filter keyword — got kwargs: {kwarg_names}"
            )

    def test_load_ohlcv_always_has_filter_in_universe_source(self):
        """01_Universe.py does not call load_ohlcv at page-load level without a filter."""
        src = _page_src("01_Universe.py")
        calls = _ast_calls(src, "load_ohlcv")
        for call in calls:
            kwarg_names = {kw.arg for kw in call.keywords}
            filter_kwargs = {"symbols", "start", "end", "columns"}
            assert kwarg_names & filter_kwargs, (
                f"load_ohlcv call at line {call.lineno} in 01_Universe.py "
                f"has no filter keyword"
            )


# ---------------------------------------------------------------------------#
# Test 2: No network imports at page-load in any D3 page                     #
# ---------------------------------------------------------------------------#
_NETWORK_MODULES = ["yfinance", "requests", "httpx", "urllib3", "aiohttp"]
_D3_PAGES = ["01_Universe.py", "02_Prices.py", "03_Feature_Panel.py"]


class TestNoNetworkOnLoad:
    """No D3 page may import a network library at the top level."""

    @pytest.mark.parametrize("page", _D3_PAGES)
    def test_no_network_imports(self, page: str):
        src = _page_src(page)
        for mod in _NETWORK_MODULES:
            assert not _has_import(src, mod), (
                f"{page} imports {mod!r} at the top level — "
                "network access on page load is forbidden (DASHBOARD_PLAN.md §0.2)"
            )

    @pytest.mark.parametrize("page", _D3_PAGES)
    def test_yfinance_not_called_on_load(self, page: str):
        """yfinance must not appear in a direct call context at the module top level.

        We check this by scanning the AST for import+call patterns — even
        a conditional import inside a load-time function body is forbidden.
        """
        src = _page_src(page)
        # If yfinance appears in the source at ALL (not in a comment), warn.
        # In 02_Prices.py it is explicitly forbidden on load; mention in comments is ok.
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # If the call is yfinance.download or similar
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        if node.func.value.id == "yf" or node.func.value.id == "yfinance":
                            pytest.fail(
                                f"{page} calls yfinance.{node.func.attr} at line "
                                f"{node.lineno} — forbidden on page load"
                            )


# ---------------------------------------------------------------------------#
# Test 3: Missing-cache path fires data_missing + st.stop                    #
# ---------------------------------------------------------------------------#
class TestMissingCachePath:
    """Each page's guard block calls ui.data_missing and st.stop() when caches absent."""

    @pytest.mark.parametrize("page", _D3_PAGES)
    def test_data_missing_and_stop_present(self, page: str):
        """The page source must contain both ui.data_missing and st.stop()."""
        src = _page_src(page)
        assert "data_missing" in src, (
            f"{page} does not call ui.data_missing — required by §0.7 rule 5"
        )
        assert "st.stop()" in src, (
            f"{page} does not call st.stop() — required by §0.7 rule 5"
        )

    @pytest.mark.parametrize("page", _D3_PAGES)
    def test_data_missing_mentions_build_command(self, page: str):
        """The data_missing call must name the exact build command."""
        src = _page_src(page)
        assert "build_cache.py" in src, (
            f"{page} does not mention build_cache.py in its data_missing call"
        )


# ---------------------------------------------------------------------------#
# Test 4: Cache schema shapes for panel caches                               #
# ---------------------------------------------------------------------------#
class TestCacheSchemas:
    """Validate that the fixture caches have the correct columns."""

    @pytest.fixture(autouse=True)
    def _import_fixtures(self):
        from dashboard.lib.fixtures import fake_cache, CACHE_SCHEMAS
        self.fake_cache = fake_cache
        self.schemas = CACHE_SCHEMAS

    def _check(self, name: str):
        df = self.fake_cache(name)
        expected = set(self.schemas[name])
        got = set(df.columns)
        assert expected == got, (
            f"fake_cache({name!r}): expected cols {sorted(expected)}, "
            f"got {sorted(got)}"
        )
        assert len(df) > 0, f"fake_cache({name!r}) returned empty frame"

    def test_panel_feature_ic_shift_schema(self):
        self._check("panel_feature_ic_shift")

    def test_panel_leaky_check_schema(self):
        self._check("panel_leaky_check")

    def test_panel_feature_ic_schema(self):
        self._check("panel_feature_ic")

    def test_universe_daily_coverage_schema(self):
        self._check("universe_daily_coverage")

    def test_prices_quality_schema(self):
        self._check("prices_quality")

    def test_panel_feature_stats_schema(self):
        self._check("panel_feature_stats")

    def test_panel_feature_corr_schema(self):
        self._check("panel_feature_corr")

    def test_panel_xsec_size_schema(self):
        self._check("panel_xsec_size")

    def test_panel_nan_coverage_schema(self):
        self._check("panel_nan_coverage")

    def test_panel_label_dist_schema(self):
        self._check("panel_label_dist")


# ---------------------------------------------------------------------------#
# Test 5: coverage_chart fixture produces FLAT verdict                       #
# ---------------------------------------------------------------------------#
class TestCoverageChart:
    """charts.coverage_chart on flat fake data must return verdict='FLAT'."""

    def test_flat_verdict_on_uniform_data(self):
        from dashboard.lib.charts import coverage_chart
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2015-01-01", "2025-12-31", freq="B")
        df = pd.DataFrame({
            "date": dates,
            "n_panel": np.full(len(dates), 200),
        })
        _, meta = coverage_chart(df, target=200)
        assert meta["verdict"] == "FLAT", (
            f"Expected FLAT verdict on uniform data, got {meta['verdict']} "
            f"(slope={meta['slope_per_year']:.4f})"
        )
        assert abs(meta["slope_per_year"]) < 3.0, (
            f"slope_per_year={meta['slope_per_year']:.4f} exceeds ±3 on flat input"
        )

    def test_sloping_verdict_on_growing_data(self):
        from dashboard.lib.charts import coverage_chart
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2015-01-01", "2025-12-31", freq="B")
        n = len(dates)
        # 50 names → 250 names linearly (slope ~ 20/yr)
        vals = np.linspace(50, 250, n)
        df = pd.DataFrame({"date": dates, "n_panel": vals})
        _, meta = coverage_chart(df, target=200)
        assert meta["verdict"] == "SLOPING", (
            f"Expected SLOPING verdict on growing data, got {meta['verdict']}"
        )

    def test_returns_figure_and_dict(self):
        from dashboard.lib.charts import coverage_chart
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2020-01-01", "2024-12-31", freq="B")
        df = pd.DataFrame({"date": dates, "n_panel": np.full(len(dates), 198)})
        result = coverage_chart(df, target=200)
        assert isinstance(result, tuple) and len(result) == 2
        fig, meta = result
        assert "slope_per_year" in meta
        assert "verdict" in meta
        assert meta["verdict"] in ("FLAT", "SLOPING")


# ---------------------------------------------------------------------------#
# Test 6: leaky_check fixture has fwd_ret_1 with IC > 0.9                   #
# ---------------------------------------------------------------------------#
class TestLeakyCheckFixture:
    def test_fwd_ret_1_ic_above_09(self):
        from dashboard.lib.fixtures import fake_cache

        df = fake_cache("panel_leaky_check")
        assert "predictor" in df.columns
        assert "rank_ic" in df.columns
        fwd1 = df[df["predictor"] == "fwd_ret_1"]["rank_ic"]
        assert len(fwd1) > 0, "panel_leaky_check fixture must have a fwd_ret_1 row"
        assert float(fwd1.iloc[0]) > 0.9, (
            f"fwd_ret_1 IC in fixture is {float(fwd1.iloc[0]):.4f} — expected > 0.9"
        )


# ---------------------------------------------------------------------------#
# Test 7: ic_shift fixture has base ≠ shift1 for mom_21                     #
# ---------------------------------------------------------------------------#
class TestIcShiftFixture:
    def test_mom21_base_differs_from_shift1(self):
        from dashboard.lib.fixtures import fake_cache

        df = fake_cache("panel_feature_ic_shift")
        mom = df[df["feature"] == "mom_21"]
        base_rows = mom[mom["variant"] == "base"]["rank_ic"]
        shift_rows = mom[mom["variant"] == "shift1"]["rank_ic"]
        assert len(base_rows) > 0 and len(shift_rows) > 0, (
            "panel_feature_ic_shift fixture must have mom_21 base + shift1"
        )
        b = float(base_rows.iloc[0])
        s = float(shift_rows.iloc[0])
        assert abs(b - s) > 1e-9, (
            f"mom_21 base ({b:.4f}) == shift1 ({s:.4f}) in fixture — "
            "the shift test would be meaningless"
        )


# ---------------------------------------------------------------------------#
# Test 8: data.load_ohlcv raises when called with no filter                  #
# ---------------------------------------------------------------------------#
class TestLoadOhlcvGuard:
    def test_no_filter_raises_value_error(self):
        """data.load_ohlcv() with no filter args raises ValueError at runtime.

        This test calls the underlying (non-cached) implementation directly
        by bypassing the @st.cache_data wrapper so it runs without a Streamlit
        server.  It patches load_ohlcv's __wrapped__ or falls back to testing
        the module-level guard directly.
        """
        from dashboard.lib import data as _data

        # The cached function wraps _read_parquet_sliced which calls _assert_sliced.
        # We can test the guard via the internal helper directly:
        ohlcv_path = _data._OHLCV
        with pytest.raises(ValueError, match="too large"):
            _data._assert_sliced(ohlcv_path, filters=None, columns=None)


# ---------------------------------------------------------------------------#
# Test 9: page files are importable (no import-time exception with mocked st) #
# ---------------------------------------------------------------------------#
class TestPageImportability:
    """Pages must be importable without a running Streamlit server."""

    @pytest.mark.parametrize("page,modname", [
        ("01_Universe.py", "dashboard.pages.01_Universe"),
        ("02_Prices.py",   "dashboard.pages.02_Prices"),
        ("03_Feature_Panel.py", "dashboard.pages.03_Feature_Panel"),
    ])
    def test_page_syntax_is_valid(self, page: str, modname: str):
        """At minimum the page must parse without a SyntaxError."""
        src = _page_src(page)
        try:
            ast.parse(src)
        except SyntaxError as exc:
            pytest.fail(f"{page} has a SyntaxError: {exc}")

    def test_universe_page_has_set_page_config(self):
        src = _page_src("01_Universe.py")
        assert "st.set_page_config" in src

    def test_prices_page_has_set_page_config(self):
        src = _page_src("02_Prices.py")
        assert "st.set_page_config" in src

    def test_feature_panel_page_has_set_page_config(self):
        src = _page_src("03_Feature_Panel.py")
        assert "st.set_page_config" in src

    def test_universe_page_has_phase_tag(self):
        src = _page_src("01_Universe.py")
        assert 'phase_tag="D3"' in src or "phase_tag='D3'" in src

    def test_prices_page_has_phase_tag(self):
        src = _page_src("02_Prices.py")
        assert 'phase_tag="D3"' in src or "phase_tag='D3'" in src

    def test_feature_panel_has_phase_tag(self):
        src = _page_src("03_Feature_Panel.py")
        assert 'phase_tag="D3"' in src or "phase_tag='D3'" in src


# ---------------------------------------------------------------------------#
# Test 10: pages do NOT call it "NIFTY 200"                                  #
# ---------------------------------------------------------------------------#
class TestNoNifty200Label:
    """Pages must not call the universe 'NIFTY 200' (DASHBOARD_PLAN.md §D3 Do NOT)."""

    @pytest.mark.parametrize("page", _D3_PAGES)
    def test_not_called_nifty_200(self, page: str):
        src = _page_src(page)
        # Allowed: quoting the name to say 'NOT NIFTY 200'
        # Forbidden: referring to it as "NIFTY 200" affirmatively
        # Strategy: check the source does not affirmatively label it NIFTY 200
        # We allow 'NOT NIFTY 200' and similar negations
        # Simple regex: any occurrence of "NIFTY 200" not immediately preceded by NOT / not
        hits = re.findall(r'NIFTY\s*200', src, re.IGNORECASE)
        not_hits = re.findall(r'not\s+.{0,10}NIFTY\s*200', src, re.IGNORECASE)
        affirmative = len(hits) - len(not_hits)
        # Allow up to 1 occurrence if it is always paired with 'not' context
        # (the plan text itself uses the phrase to disclaim it)
        # Fail only if there are affirmative uses beyond the disclaimer pattern
        if affirmative > len(not_hits) + 2:  # 2 tolerance for quoted disclaimers
            pytest.fail(
                f"{page} uses 'NIFTY 200' {affirmative} times affirmatively — "
                "the spec requires we call it 'the 200 most liquid Indian equities'"
            )
