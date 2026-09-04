"""Gates & Ledger — 06_Gates_and_Ledger.py  (built in D5)

Gate B — "did we fool ourselves?" — as an interactive argument, not just a
static description: the over-searching explainer, a live Deflated-Sharpe
calculator, the effective-trial-count demo, PBO, walk-forward, the trial
ledger, the rationed holdout-peek gauge, and the append-only guarantee.

Sections
--------
1. Gate B order (the flowchart + the "why novelty runs first" narrative).
2. The over-searching explainer — sqrt(2lnN) vs realised E[max] vs Bailey-LdP.
3. The Deflated Sharpe Ratio calculator.
4. Effective trial count — 20 knob-variants of one shape.
5. PBO — probability of backtest overfitting, noise vs. a planted signal.
6. Walk-forward — the sequential OOS IC series for a ZOO formula.
7. The trial ledger.
8. Holdout peeks — the rationed-vault gauge + peek log.
9. The append-only guarantee.
10. Thresholds.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.lib import charts, data, fixtures, flow, narrative, ui
from dashboard.lib import engine as eng

st.set_page_config(page_title="Gates & Ledger", layout="wide")
ui.page_header(
    "Gates & Ledger",
    "Gate B, end to end: is it NEW? then — given how hard we looked — is it REAL?",
    phase_tag="D5",
)
ui.stale_banner(data.cache_staleness())

if not eng.ensure_panel():
    ui.data_missing(
        "The feature/label panel (data/panel/features.parquet + labels.parquet)",
        "python -m src.panel   # (P3) — builds data/panel/*",
    )
    st.stop()

TH = eng.thresholds()

# =========================================================================== #
# 1 — Gate B order                                                             #
# =========================================================================== #
ui.section(
    "1. Gate B order",
    help_text="Four steps, in this exact order — changed deliberately after the "
              "build caught its own bug (reports/p6_handoff.md).",
)
st.graphviz_chart(flow.render("gate_b"))
st.markdown(narrative.block("gate_b_order"))
ui.source_note("src/gates.py gate_b() · reports/p6_handoff.md §6")

st.markdown(
    "**Novelty is free and already computed; a holdout peek is 1 of "
    f"{TH['HOLDOUT_PEEK_BUDGET']} for the system's lifetime.** That asymmetry is "
    "why novelty runs before the peek, never after."
)

# =========================================================================== #
# 2 — The over-searching explainer                                            #
# =========================================================================== #
ui.section(
    "2. The over-searching explainer",
    help_text="Test N pure-noise signals, keep the best — its t-statistic climbs "
              "with N even though nothing is there. Three views of the same fact.",
)

n_slider = st.slider("N — things tried", min_value=2, max_value=1000, value=200, step=1)

curve = eng.oversearching_curve()   # cached grid, seeded Monte-Carlo

fine_n = np.unique(np.round(np.geomspace(2, 1000, 120)).astype(int))
sqrt_curve = [math.sqrt(2.0 * math.log(n)) for n in fine_n]
bailey_curve = [eng.expected_max_sr(int(n), 1.0) for n in fine_n]

fig = go.Figure()
fig.add_scatter(x=fine_n, y=sqrt_curve, mode="lines", name="√(2 ln N) — ceiling",
                line=dict(color=charts.PALETTE["muted"], dash="dot"))
fig.add_scatter(x=fine_n, y=bailey_curve, mode="lines", name="Bailey-LdP E[max SR]",
                line=dict(color=charts.PALETTE["accent"]))
fig.add_scatter(x=curve["N"], y=curve["realised_E_max"], mode="lines+markers",
                name="realised E[max] (seeded Monte-Carlo)",
                line=dict(color=charts.PALETTE["accent2"], dash="dash"))
fig.add_vline(x=n_slider, line_color=charts.PALETTE["neg"], line_dash="dash",
              annotation_text=f"N={n_slider}", annotation_position="top")
fig.update_layout(
    template=charts.TEMPLATE, xaxis_type="log", xaxis_title="N (things tried)",
    yaxis_title="t-statistic of the best-of-N pure-noise signal",
    title="Searching harder makes you more likely to fool yourself",
    legend=dict(orientation="h", y=-0.25),
)
st.plotly_chart(fig, use_container_width=True)
st.caption(
    ":grey[The realised expected max sits ~0.5 below the √(2 ln N) ceiling at every "
    "N (measured, 20,000-draw Monte-Carlo per grid point, reports/p6_handoff.md). "
    "The Bailey-LdP term tracks the realised curve to ≤0.03 — that is the deflator "
    "`gate_b` actually uses, never the ceiling.]"
)

st.markdown("**Measured: P(best-of-N pure-noise t-stat > 3.0)** — 200,000 Monte-Carlo draws per row.")
p_table = pd.DataFrame(
    {"N": list(eng.MEASURED_P_T_GT_3), "P(best t > 3.0) on pure noise":
     [f"{v:.1f}%" for v in eng.MEASURED_P_T_GT_3.values()]}
)
nearest = min(eng.MEASURED_P_T_GT_3, key=lambda x: abs(x - n_slider))
p_table.insert(0, "◀ current N", ["◀" if n == nearest else "" for n in eng.MEASURED_P_T_GT_3])
st.dataframe(p_table, use_container_width=True, hide_index=True)
st.caption(
    f":grey[Slider N={n_slider} — nearest measured point is N={nearest} "
    f"({eng.MEASURED_P_T_GT_3[nearest]:.1f}%). At the 20-variant cap it is 2.7%; "
    "at 500 attempts it is a coin flip against pure noise.]"
)
ui.source_note("src.gates.expected_max_sharpe · reports/p6_handoff.md §6 (measured table)")

# =========================================================================== #
# 3 — The Deflated Sharpe Ratio calculator                                    #
# =========================================================================== #
ui.section(
    "3. The Deflated Sharpe Ratio calculator",
    help_text="P(true per-period Sharpe > 0), after deflating for how many trials "
              "produced the winner and for non-normal returns.",
)

_PRESETS = {
    "Headline — best of 200 pure-noise signals (reject)": dict(
        observed_sr=0.0908, n_trials=200, sr_std=0.0335, skew=0.0, kurt=3.0, n_obs=913,
    ),
    "A real signal found in 5 trials (pass)": dict(
        observed_sr=0.2338, n_trials=5, sr_std=0.1227, skew=0.0, kurt=3.0, n_obs=913,
    ),
    "Custom": None,
}
preset_name = st.radio("Preset", list(_PRESETS), horizontal=True)
defaults = _PRESETS[preset_name] or _PRESETS["Headline — best of 200 pure-noise signals (reject)"]

c1, c2, c3 = st.columns(3)
with c1:
    observed_sr = st.slider("observed_sr (per-period)", 0.0, 0.5, float(defaults["observed_sr"]), 0.001)
    n_trials = st.slider("n_trials (effective)", 1, 500, int(defaults["n_trials"]))
with c2:
    sr_std = st.slider("sr_std (cross-trial SR std)", 0.001, 0.5, float(defaults["sr_std"]), 0.001)
    skew = st.slider("skew", -2.0, 2.0, float(defaults["skew"]), 0.05)
with c3:
    kurt = st.slider("kurtosis (non-excess)", 1.0, 10.0, float(defaults["kurt"]), 0.1)
    n_obs = st.slider("n_obs (scored days, T)", 10, 3000, int(defaults["n_obs"]))

dsr_val = eng.dsr(observed_sr, n_trials, sr_std, skew, kurt, n_obs)
sr0 = eng.expected_max_sr(n_trials, sr_std)
verdict = "✅ PASS" if np.isfinite(dsr_val) and dsr_val >= TH["DSR_MIN"] else "❌ REJECT"

charts.kpi_row([
    ("Deflated Sharpe", f"{dsr_val:.4f}", None),
    ("E[max SR] deflator", f"{sr0:.4f}", None),
    ("t-stat (undeflated)", f"{observed_sr * math.sqrt(max(n_obs - 1, 1)):.2f}", None),
    ("Verdict", verdict, None),
])
st.caption(f":grey[Bar: DSR_MIN = {TH['DSR_MIN']}. Same gate scores both presets — only the trial count and the observed edge differ.]")
ui.source_note("src.gates.deflated_sharpe_ratio via dashboard.lib.engine.dsr · reports/p6_handoff.md criterion 3/4")

# =========================================================================== #
# 4 — Effective trial count                                                   #
# =========================================================================== #
ui.section(
    "4. Effective trial count",
    help_text="20 knob-variants of one shape (`vol / ts_mean(vol, k)`, k=5..24) — "
              "are they 20 independent bets, or fewer?",
)
st.write(
    "Raw N over-penalises: 20 near-identical formulas that only differ in a "
    "window length are mostly the same bet. `effective_trial_count` clusters by "
    "**canonical AST shape** and splits a cluster back apart only as far as its "
    "members' *return series* actually decorrelate."
)
if st.button("▶ Compute effective trial count (≈ 10 s — 20 live backtests)"):
    with st.spinner("Evaluating 20 knob-variants on VAL_A …"):
        etc = eng.effective_trial_count_demo()
    charts.kpi_row([
        ("Raw N", f"{etc['raw_n']}", None),
        ("Effective N", f"{etc['effective_n']:.2f}", None),
        ("Scored days", f"{etc['n_days']}", None),
    ])
    st.caption(
        ":grey[Deflated by the **effective** count, not raw N, and scoped "
        "**run-wide** — opening a new thesis must not reset the counter "
        "(reports/p6_handoff.md criterion 5/6).]"
    )
else:
    st.caption("Press the button to compute live on the real VAL_A panel.")
ui.source_note("src.gates.effective_trial_count · src.ast_tools.canonical")

# =========================================================================== #
# 5 — PBO                                                                     #
# =========================================================================== #
ui.section(
    "5. Probability of Backtest Overfitting (PBO)",
    help_text="CSCV (Bailey/Borwein/Lopez de Prado/Zhu 2015): does the "
              "in-sample winner keep winning out-of-sample?",
)
st.write(
    "On a pure-noise T×8 return matrix there is no true winner, so PBO should sit "
    "near 0.5 (a coin flip). On a matrix with one persistently-real column — a "
    "real ZOO momentum formula's daily VAL_A RankIC — against noise columns of "
    "the same scale, the real column should keep winning out-of-sample too, so "
    "PBO should be materially lower. A single 8-block CSCV split is noisy (only "
    "~110 rows/block), so this averages several seeded draws."
)
if st.button("▶ Run the PBO demo (≈ 5-10 s — 60 CSCV splits)"):
    with st.spinner("Running CSCV on noise and on a planted-signal matrix …"):
        pbo = eng.pbo_demo()
    charts.kpi_row([
        ("Noise PBO (mean of 30 draws)", f"{pbo['noise_pbo_mean']:.3f}", None),
        ("Planted-signal PBO (mean of 30 draws)", f"{pbo['planted_pbo_mean']:.3f}", None),
        ("PBO_MAX", f"{TH['PBO_MAX']}", None),
    ])
    st.plotly_chart(
        charts.box(
            pd.DataFrame(
                {"pbo": pbo["noise_pbo_draws"] + pbo["planted_pbo_draws"],
                 "matrix": ["noise"] * len(pbo["noise_pbo_draws"])
                           + ["planted"] * len(pbo["planted_pbo_draws"])}
            ),
            x="matrix", y="pbo", title="PBO across 30 seeded CSCV draws each",
        ),
        use_container_width=True,
    )
else:
    st.caption("Press the button to run CSCV live on the real VAL_A panel.")
ui.source_note("src.gates.cscv_pbo · src.gates.daily_rank_ic")

# =========================================================================== #
# 6 — Walk-forward                                                            #
# =========================================================================== #
ui.section(
    "6. Walk-forward",
    help_text="The workhorse OOS method — CSCV above exists only for one honest "
              "PBO number. Expanding-window, sequential, on TRAIN + VAL_A.",
)
zoo = eng.zoo_formulas()
zoo_names = [e["name"] for e in zoo]
zoo_by_name = {e["name"]: e for e in zoo}
wf_pick = st.selectbox(
    "ZOO formula", zoo_names,
    index=zoo_names.index("classical_momentum_12_1") if "classical_momentum_12_1" in zoo_names else 0,
    key="wf_pick",
)
st.code(zoo_by_name[wf_pick]["formula"], language="python")
st.caption(
    ":grey[`walk_forward` takes **dates**, not a split name — "
    "`start, end = config.SPLITS[\"train\"][0], config.SPLITS[\"val_a\"][1]`.]"
)
if st.button("▶ Run walk-forward (≈ 5-10 s)"):
    with st.spinner("Expanding-window walk-forward over TRAIN + VAL_A …"):
        wf = eng.walk_forward_ui(zoo_by_name[wf_pick]["formula"])
    if wf["oos_ic"]:
        oos_df = pd.DataFrame({"date": pd.to_datetime(wf["oos_dates"]), "oos_ic": wf["oos_ic"]})
        st.plotly_chart(
            charts.line(oos_df, x="date", y="oos_ic", title="Sequential OOS RankIC", ref=0.0),
            use_container_width=True,
        )
    else:
        st.info("No OOS days were produced — the window may be too short after purge+embargo.")
    st.markdown("**Per-fold metrics**")
    st.dataframe(pd.DataFrame(wf["folds"]), use_container_width=True, hide_index=True)
else:
    st.caption("Press the button to run walk-forward live on the real panel.")
ui.source_note("src.gates.walk_forward")

# =========================================================================== #
# 7 — The trial ledger                                                        #
# =========================================================================== #
ui.section(
    "7. The trial ledger",
    help_text="Every selection trial that ever ran, append-only — the honest "
              "count the Deflated Sharpe deflates by.",
)
ledger_summary = data.try_cache("ledger_summary")
trials = data.load_ledger_trials()

if trials.empty:
    st.warning(
        "**`data/ledger.db` has no trials yet** — the orchestration loop (P10/P11) "
        "has not run a real search in this environment, so the ledger is honestly "
        "empty. The chart and table below show a **fixture preview** of what a "
        "populated ledger looks like — labelled, never mixed with real numbers."
    )
    fx_summary = fixtures.fake_cache("ledger_summary")
    st.plotly_chart(
        charts.line(fx_summary, x="t", y="cumulative_trials",
                    title="Cumulative trial count over time — FIXTURE PREVIEW"),
        use_container_width=True,
    )
    st.caption(":grey[FIXTURE — not data/ledger.db]")
else:
    if ledger_summary is not None and len(ledger_summary):
        st.plotly_chart(
            charts.line(ledger_summary, x="t", y="cumulative_trials",
                        title="Cumulative trial count over time"),
            use_container_width=True,
        )
    thesis_filter = st.multiselect(
        "Filter by thesis_id", sorted(trials["thesis_id"].dropna().unique().tolist())
    )
    view = trials[trials["thesis_id"].isin(thesis_filter)] if thesis_filter else trials
    st.dataframe(
        view[["trial_id", "thesis_id", "formula_hash", "split_used", "rank_ic",
              "sharpe", "t_stat", "n_days", "counts_as_trial", "rejection_reason"]],
        use_container_width=True, hide_index=True,
    )
ui.source_note("data/ledger.db `trials` table (via _readonly_sqlite) · data/dashboard/ledger_summary.parquet")

# =========================================================================== #
# 8 — Holdout peeks                                                           #
# =========================================================================== #
ui.section(
    "8. Holdout peeks",
    help_text=f"A fixed, counted budget of {TH['HOLDOUT_PEEK_BUDGET']} peeks at sealed HOLDOUT "
              "data, for the system's entire lifetime.",
)
peeks = data.load_holdout_peeks()
used = int(len(peeks))
budget = int(TH["HOLDOUT_PEEK_BUDGET"])
st.plotly_chart(
    charts.gauge(used, budget, "peeks used",
                thresholds={"bands": [(0, budget * 0.5, charts.PALETTE["pos"]),
                                      (budget * 0.5, budget * 0.85, charts.PALETTE["accent2"]),
                                      (budget * 0.85, budget, charts.PALETTE["neg"])]}),
    use_container_width=True,
)
if used:
    st.dataframe(peeks, use_container_width=True, hide_index=True)
else:
    st.caption(":grey[No peeks spent yet in this environment's `data/ledger.db`.]")
ui.source_note("data/ledger.db `holdout_peeks` table (via _readonly_sqlite) · src.config.HOLDOUT_PEEK_BUDGET")

# =========================================================================== #
# 9 — The append-only guarantee                                               #
# =========================================================================== #
ui.section(
    "9. The append-only guarantee",
    help_text="If a row could be removed, the trial count would be gameable and "
              "the whole deflation meaningless.",
)
if st.button("▶ Run assert_no_row_removal_sql()"):
    ok, msg = eng.assert_ledger_append_only()
    (st.success if ok else st.error)(msg)
else:
    st.caption("Press the button to structurally scan `src/ledger.py` for DELETE / DROP TABLE / TRUNCATE, live.")
ui.source_note("src.ledger.assert_no_row_removal_sql()")

# =========================================================================== #
# 10 — Thresholds                                                             #
# =========================================================================== #
ui.section("10. Thresholds", help_text="Read live from `src.gates` / `src.config` — never retyped.")
th_df = pd.DataFrame(
    [("T_STAT_BAR", TH["T_STAT_BAR"], "one-sided |t| the residual must clear"),
     ("MIN_MARGINAL_IC", TH["MIN_MARGINAL_IC"], "novelty floor — below this the residual is a clone"),
     ("DSR_MIN", TH["DSR_MIN"], "P(true SR > 0) the residual must clear"),
     ("PBO_MAX", TH["PBO_MAX"], "probability-of-backtest-overfitting ceiling"),
     ("MIN_DSR_SAMPLE", TH["MIN_DSR_SAMPLE"], "minimum scored days for a DSR to be trusted")],
    columns=["threshold", "value", "what it gates"],
)
st.dataframe(th_df, use_container_width=True, hide_index=True)
ui.source_note("src.gates.{MIN_MARGINAL_IC,DSR_MIN,PBO_MAX,MIN_DSR_SAMPLE} · src.config.T_STAT_BAR")
