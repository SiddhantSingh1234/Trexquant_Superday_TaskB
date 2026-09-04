"""Red Team — 09_Red_Team.py  (built in D5)

Gate C: eleven pre-written, parameterised falsification backtests. The agent
(Phase 8) picks *which* attacks fit a candidate; it never writes code — the
attacks are fixed. All eleven can only kill, never promote, so every
red-team backtest is logged `counts_as_trial=0`.

Sections
--------
1. The menu — all 11, what each hunts, decisive vs diagnostic.
2. The survive rule.
3. Rejection-only.
4. Regime definition.
5. The runner — pick a signal, run it live.
6. Evidence board — four canned signals, cached.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.lib import charts, data, ui
from dashboard.lib import engine as eng

st.set_page_config(page_title="Red Team", layout="wide")
ui.page_header(
    "Red Team",
    "Gate C — eleven falsification backtests; a candidate survives only if it "
    "beats all five decisive ones.",
    phase_tag="D5",
)
ui.stale_banner(data.cache_staleness())

if not eng.ensure_panel():
    ui.data_missing(
        "The feature/label panel (data/panel/features.parquet + labels.parquet)",
        "python -m src.panel   # (P3) — builds data/panel/*",
    )
    st.stop()

MENU = eng.redteam_menu()
DECISIVE = set(MENU["decisive"])

_WHAT_IT_HUNTS = {
    "subsample_year": ("It was one lucky year", "drop the single best calendar year; RankIC should survive"),
    "regime_split": ("It only works in a bull market", "score inside bull / bear / high-vol subsamples (expanding-window labels)"),
    "size_tercile": ("It's a small-cap artefact", "score by trailing-turnover size tercile, not market cap"),
    "cost_sweep": ("Great gross, loses money net", "cost_bps ∈ {5, 15, 30} — is the edge tradeable?"),
    "extra_lag": ("Hidden look-ahead", "shift the whole signal forward one extra day"),
    "delivery_lag": ("Which field is the edge leaning on?", "shift ONLY delivery_pct by one day, re-evaluate the formula"),
    "sector_neutral": ("It's one industry bet", "demean the signal within sector"),
    "liquidity_filter": ("Untradeable names", "impose a trailing-turnover floor"),
    "decay_curve": ("The claimed horizon is fiction", "RankIC at h ∈ {1,2,3,5,10,21} vs the claimed horizon"),
    "sign_stability": ("The direction flips around", "modal sign of RankIC per fold, ≥ 70% consistency required"),
    "universe_edge": ("It only works on the illiquid fringe", "drop the names ranked 150-200 by trailing liquidity that month"),
}

# =========================================================================== #
# 1 — The menu                                                                #
# =========================================================================== #
ui.section(
    "1. The menu — all eleven",
    help_text="The agent picks which attacks fit a candidate; the attacks "
              "themselves are pre-written, parameterised backtests. It never "
              "writes free-form code.",
)
menu_rows = []
for i, name in enumerate(MENU["menu"], start=1):
    label, hunts = _WHAT_IT_HUNTS.get(name, (name, ""))
    menu_rows.append((i, name, label, hunts, "decisive" if name in DECISIVE else "diagnostic"))
menu_df = pd.DataFrame(menu_rows, columns=["#", "test", "what it hunts", "how", "kind"])
st.dataframe(menu_df, use_container_width=True, hide_index=True)
ui.source_note("src.redteam.REDTEAM_MENU / DECISIVE_TESTS · src/redteam.py module docstring")

# =========================================================================== #
# 2 — The survive rule                                                        #
# =========================================================================== #
ui.section("2. The survive rule", help_text="")
st.markdown(
    "A candidate is **killed** iff **any** decisive test flags it. To survive, "
    "RankIC must stay positive and significant across tests **1, 2, 5**, must not "
    "collapse (> 50% degradation) under test **4** at 15 bps or under test **5**, "
    "and must hold a consistent sign in **≥ 70%** of folds (test **10**). "
    "**The five decisive tests always run**, unioned with whatever the agent "
    "selected — a falsification gate a candidate can opt out of is not one. "
    "Tests 3, 6, 7, 8, 9, 11 are diagnostic: run, reported, but they never flip "
    "the verdict on their own."
)
ui.source_note("src.redteam.run_redteam() docstring · IMPLEMENTATION_PLAN.md Phase 9")

# =========================================================================== #
# 3 — Rejection-only                                                          #
# =========================================================================== #
ui.section("3. Rejection-only", help_text="")
st.markdown(
    "All eleven can only **kill**, never promote. A filter that only rejects "
    "cannot raise the false-discovery rate, so every red-team backtest is logged "
    "with `counts_as_trial = 0` — this is the answer to *\"doesn't running 11 "
    "backtests per candidate blow up your trial count?\"*. It does not, by "
    "construction: nothing here can select a winner, only disqualify one."
)
ui.source_note("src/redteam.py module docstring · src.ledger.Ledger.record_trial(counts_as_trial=0)")

# =========================================================================== #
# 4 — Regime definition                                                       #
# =========================================================================== #
ui.section("4. Regime definition", help_text="")
st.markdown(
    "**Bull**: trailing 63-day compounded return > +5%. **Bear**: < -5%. "
    "**High-vol**: 21-day realised volatility in the top tercile — of an "
    "**expanding** window, computed only from data available up to that day. "
    "A full-sample volatility threshold would be look-ahead (it uses data from "
    "the future to label the past); the version that used to do this was fixed "
    "at its P4 source."
)
ui.source_note("src.backtester._regime_labels (expanding-window only) · tests/test_p4_backtester.py")

# =========================================================================== #
# 5 — The runner                                                              #
# =========================================================================== #
ui.section(
    "5. The runner",
    help_text="Pick a signal, choose a split (never HOLDOUT), press Run. "
              "~1-2 minutes — the red-team fires ~20-30 live backtests.",
)

zoo = eng.zoo_formulas()
zoo_names = [e["name"] for e in zoo]
zoo_by_name = {e["name"]: e for e in zoo}

_RUNNER_SPECIAL = {"leaky (fwd_ret_1)": "__leaky__", "one-lucky-year (synthetic)": "__one_lucky_year__"}

kind = st.radio("Signal", ["ZOO formula", *list(_RUNNER_SPECIAL)], horizontal=True, key="rt_kind")
if kind == "ZOO formula":
    pick = st.selectbox("ZOO formula", zoo_names,
                        index=zoo_names.index("classical_momentum_12_1") if "classical_momentum_12_1" in zoo_names else 0,
                        key="rt_zoo_pick")
    run_formula = zoo_by_name[pick]["formula"]
    st.code(run_formula, language="python")
else:
    run_formula = _RUNNER_SPECIAL[kind]
    st.caption(f":grey[{kind} — a synthetic acceptance signal, not a ZOO formula.]")

rt_split = st.selectbox("Split", ["val_a", "val_b"], index=0, key="rt_split")

if st.button("▶ Run red-team (~1-2 min)", type="primary"):
    if rt_split == "holdout":
        st.error("HOLDOUT is sealed — no page may score a signal on it.")
        st.stop()
    try:
        with st.spinner(f"Running the 11-test red-team on {rt_split} — this fires "
                        "~20-30 live backtests, ~1-2 minutes …"):
            result = eng.run_redteam_ui(run_formula, rt_split)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not run: `{type(exc).__name__}: {exc}`")
        st.stop()

    verdict_txt = "🟢 SURVIVES" if result["verdict"] == "survives" else "🔴 KILLED"
    st.markdown(f"### {verdict_txt}")
    b = result["baseline"]
    charts.kpi_row([
        ("Baseline RankIC", f"{b['rank_ic']:+.4f}", None),
        ("Baseline t-stat", f"{b['t_stat']:+.2f}", None),
        ("Baseline Sharpe", f"{b['sharpe']:+.3f}", None),
        ("Backtests fired", f"{result['n_backtests']}", None),
    ])
    if result["failed_tests"]:
        st.markdown(f"**Failed decisive tests:** {', '.join(result['failed_tests'])}")
    if result["flagged_diagnostics"]:
        st.markdown(f"**Flagged diagnostics (did not flip the verdict):** {', '.join(result['flagged_diagnostics'])}")
    if result.get("forced_decisive_tests"):
        st.caption(f":grey[Decisive tests forced on top of the selection: {', '.join(result['forced_decisive_tests'])}]")

    def _row(res: dict, menu: list[str]) -> dict:
        row = {}
        for t in menu:
            d = res["results"].get(t)
            if d is None or d.get("ran") is False:
                row[t] = np.nan
            else:
                row[t] = 1.0 if d.get("flag") else 0.0
        return row

    mat = pd.DataFrame([_row(result, MENU["menu"])], index=[kind if kind != "ZOO formula" else pick])
    st.write("Per-test outcome — red = flagged, green = passed, blank = not run "
             "(insufficient data for that test).")
    st.plotly_chart(
        charts.heatmap(mat, title="Red-team heatmap",
                       colorscale=[[0.0, charts.PALETTE["pos"]], [1.0, charts.PALETTE["neg"]]]),
        use_container_width=True,
    )
    ut = result["results"].get("universe_edge", {})
    if ut.get("ran"):
        st.caption(f":grey[Test 11 (universe_edge) ran genuinely — fringe source: {ut.get('fringe_source', '')[:120]}]")
    else:
        st.caption(f":grey[Test 11 (universe_edge) did not run: {ut.get('reason', 'unknown')}]")

    st.caption(
        ":grey[This run used `src.ledger.Ledger(\":memory:\")` — `data/ledger.db` "
        "was never opened for write. Every backtest fired here is `counts_as_trial=0`.]"
    )
    with st.expander("Full result dict"):
        st.json({k: v for k, v in result.items() if k != "results"})
        st.json(result["results"])
else:
    st.caption("Nothing runs until you press the button.")
ui.source_note("src.redteam.run_redteam via dashboard.lib.engine.run_redteam_ui")

# =========================================================================== #
# 6 — Evidence board                                                          #
# =========================================================================== #
ui.section(
    "6. Evidence board",
    help_text="Four canned signals, run live against the real VAL_A panel and "
              "cached — each illustrates a different way to die (or not).",
)
st.write(
    "**leaky** (`fwd_ret_1` as its own signal) should die to test 5 (`extra_lag`) — "
    "a one-day shift destroys a look-ahead signal but not a real one. "
    "**one-lucky-year** (noise everywhere except one deliberately-planted year) "
    "should die to test 1 (`subsample_year`). **thin-edge high-turnover** (a "
    "sliver of real reversal buried in near-maximal-turnover noise) should die "
    "to test 4 (`cost_sweep`) once trading costs are charged. The fourth row is "
    "a real ZOO formula — run live, verdict reported honestly, whatever it is: "
    "a few-hour prototype's gate statistics are illustrative, not conclusive "
    "(disclosed in `reports/p6_handoff.md` / `reports/p9_handoff.md`), so a "
    "flagship factor failing a decisive test here is itself evidence the "
    "red-team is not theater."
)
zoo_ev_pick = st.selectbox(
    "Real ZOO formula for the fourth row", zoo_names,
    index=zoo_names.index("classical_momentum_12_1") if "classical_momentum_12_1" in zoo_names else 0,
    key="ev_zoo_pick",
)

if st.button("▶ Run the evidence board (≈ 4-6 min — four full red-team runs)"):
    board = []
    labels_formulas = [
        ("leaky (fwd_ret_1)", "__leaky__", "extra_lag"),
        ("one-lucky-year (synthetic)", "__one_lucky_year__", "subsample_year"),
        ("thin-edge high-turnover (synthetic)", "__thin_edge__", "cost_sweep"),
        (f"ZOO: {zoo_ev_pick}", zoo_by_name[zoo_ev_pick]["formula"], None),
    ]
    prog = st.progress(0.0, text="Starting …")
    results = {}
    for i, (label, f, _expect) in enumerate(labels_formulas):
        prog.progress(i / len(labels_formulas), text=f"Running {label} …")
        results[label] = eng.run_redteam_ui(f, "val_a")
    prog.progress(1.0, text="Done.")

    rows = []
    for label, f, expect in labels_formulas:
        r = results[label]
        rows.append({
            "signal": label, "verdict": r["verdict"],
            "failed_tests": ", ".join(r["failed_tests"]) or "—",
            "baseline_rank_ic": r["baseline"]["rank_ic"],
            "baseline_t_stat": r["baseline"]["t_stat"],
            "expected_kill (plan)": expect or "n/a — real formula, reported as-is",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    def _row(res: dict, menu: list[str]) -> dict:
        row = {}
        for t in menu:
            d = res["results"].get(t)
            if d is None or d.get("ran") is False:
                row[t] = np.nan
            else:
                row[t] = 1.0 if d.get("flag") else 0.0
        return row

    mat = pd.DataFrame(
        [_row(results[label], MENU["menu"]) for label, _, _ in labels_formulas],
        index=[label for label, _, _ in labels_formulas],
    )
    st.plotly_chart(
        charts.heatmap(mat, title="Evidence board — per-test outcome (red=flag, green=pass)",
                       colorscale=[[0.0, charts.PALETTE["pos"]], [1.0, charts.PALETTE["neg"]]]),
        use_container_width=True,
    )

    for label, f, expect in labels_formulas:
        r = results[label]
        if expect is None:
            continue
        got_expected = expect in r["failed_tests"]
        icon = "✅" if got_expected else "⚠️"
        st.caption(f"{icon} **{label}**: verdict `{r['verdict']}` — "
                   f"expected kill via `{expect}`, "
                   f"{'confirmed' if got_expected else 'NOT confirmed on this run — see failed_tests above'}.")
else:
    st.caption("Nothing runs until you press the button. Results are cached per formula/split.")
ui.source_note("src.redteam.run_redteam via dashboard.lib.engine.run_redteam_ui — Ledger(\":memory:\") every time")
