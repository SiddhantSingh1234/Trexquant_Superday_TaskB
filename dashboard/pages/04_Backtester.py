"""Backtester — 04_Backtester.py.

One deterministic engine — ``src.backtester.backtest`` — scores a daily
cross-sectional signal and returns the Section-0.5 Metrics dict.  Every
downstream stage (quick screen, fresh-fold, the full battery, marginal-IC, the
rationed peek, the red-team, portfolio combination, the ablation) calls it with
different switches.  This page lets a reviewer drive it directly.

Sections
--------
1. The interface — the ``backtest(...)`` switches + the Metrics dict shape.
2. The runner — pick / type a formula, choose a split (never holdout), Run.
3. Purge / embargo visualiser — training rows dropped near a test boundary.
4. The acceptance-evidence board — run live: noise, negation, leakage, cost sweep.
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

st.set_page_config(page_title="Backtester", layout="wide")
ui.page_header(
    "Backtester",
    "One engine, called from eight places downstream.",
)

ui.stale_banner(data.cache_staleness())

# --------------------------------------------------------------------------- #
# Data guard — the panel must exist                                            #
# --------------------------------------------------------------------------- #
if not eng.ensure_panel():
    ui.data_missing(
        "The feature/label panel (data/panel/features.parquet + labels.parquet)",
        "python -m src.panel   # (P3) — builds data/panel/*",
    )
    st.stop()

_SPLITS = ["train", "val_a", "val_b", "train+val_a"]   # NEVER holdout

# =========================================================================== #
# Section 1 — the interface                                                    #
# =========================================================================== #
ui.section(
    "1. The interface",
    help_text="`src.backtester.backtest(signal, split, ...)` — built once, "
              "parameterised, never forked.",
)

st.write(
    "Every switch below changes *how* a signal is measured, never *what counts "
    "as a pass* — the engine only measures. Accept/reject lives in the gates (P6)."
)

_switch_tbl = pd.DataFrame(
    [
        ("signal", "date × symbol frame", "one score per stock per day (wide or long)"),
        ("split", "train | val_a | val_b | train+val_a | holdout", "date window; holdout is sealed"),
        ("horizon", "1 | 2 | 3 | 5 | 10 | 21", "forward-return horizon for the headline IC"),
        ("extra_lag", "int ≥ 0", "shift the whole signal forward N extra days (red-team #5)"),
        ("cost_bps", "float", "charged on every unit of absolute weight change, both legs"),
        ("neutralize", "None | 'sector'", "demean the signal within sector first"),
        ("subsample", "dict", "{years} | {size_tercile} | {regime} | {min_turnover} | {exclude_symbols}"),
        ("purge_days", "int (default = horizon)", "label-overlap purge distance"),
        ("embargo_days", "int (default 5)", "embargo distance after the eval window"),
    ],
    columns=["switch", "values", "what it does"],
)
st.dataframe(_switch_tbl, use_container_width=True, hide_index=True)

st.markdown("**The `Metrics` dict — every backtest returns this shape** (IMPLEMENTATION_PLAN §0.5):")
st.code(
    '{"rank_ic": float, "ic": float, "icir": float, "t_stat": float,\n'
    ' "sharpe": float, "ann_return": float, "turnover": float, "mdd": float,\n'
    ' "n_days": int, "n_obs": int,\n'
    ' "decay": {1: float, 2: float, 3: float, 5: float, 10: float, 21: float},\n'
    ' "sign": int}   # +1 or -1, from the realised rank_ic',
    language="python",
)
ui.source_note("src/backtester.py · IMPLEMENTATION_PLAN.md §0.5")

# =========================================================================== #
# Section 2 — the runner                                                       #
# =========================================================================== #
ui.section(
    "2. The runner",
    help_text="Pick a zoo formula or type your own, choose a split, press Run. "
              "Results are cached — re-running the same inputs is instant.",
)

zoo = eng.zoo_formulas()
zoo_names = [e["name"] for e in zoo]
zoo_by_name = {e["name"]: e for e in zoo}

c1, c2 = st.columns([1, 1])
with c1:
    mode = st.radio("Formula source", ["Zoo formula", "Free text"], horizontal=True)
    if mode == "Zoo formula":
        pick = st.selectbox("Zoo formula", zoo_names,
                            index=zoo_names.index("classical_momentum_12_1")
                            if "classical_momentum_12_1" in zoo_names else 0)
        formula = zoo_by_name[pick]["formula"]
        st.caption(f":grey[{zoo_by_name[pick]['source']}]")
    else:
        formula = st.text_input(
            "Formula (Phase-5 grammar)",
            value="mul(-1, ts_std(returns, 21))",
        )
    st.code(formula, language="python")

with c2:
    split = st.selectbox("Split", _SPLITS, index=1)
    horizon = st.selectbox("Horizon (days)", [1, 2, 3, 5, 10, 21], index=0)
    cost_bps = st.slider("Cost (bps)", 0.0, 50.0, 0.0, 1.0)
    neutralize = st.selectbox("Neutralize", ["none", "sector"], index=0)
    extra_lag = st.number_input("extra_lag (advanced)", min_value=0, max_value=10, value=0)

run = st.button("▶ Run backtest", type="primary")

if run:
    if split == "holdout":                       # defence in depth — UI never offers it
        st.error("HOLDOUT is sealed — no page may score a signal on it.")
        st.stop()
    try:
        with st.spinner("Evaluating the formula and scoring it on the panel …"):
            m = eng.run_backtest(
                formula, split, horizon=int(horizon), cost_bps=float(cost_bps),
                neutralize=None if neutralize == "none" else neutralize,
                extra_lag=int(extra_lag),
            )
    except Exception as exc:  # noqa: BLE001 — surface any parse/eval/score failure in the UI
        st.error(f"Could not run: `{type(exc).__name__}: {exc}`")
        st.stop()

    sign_txt = "＋1 (long the high scores)" if m["sign"] > 0 else "−1 (short the high scores)"
    st.markdown(f"**Realised sign: `{m['sign']:+d}`** — {sign_txt}")

    charts.kpi_row([
        ("RankIC", f"{m['rank_ic']:+.4f}", None),
        ("ICIR", f"{m['icir']:+.3f}", None),
        ("t-stat", f"{m['t_stat']:+.2f}", None),
        ("Sharpe", f"{m['sharpe']:+.3f}", None),
        ("Ann. return", f"{m['ann_return']:+.1%}", None),
        ("Turnover (1-way)", f"{m['turnover']:.3f}", None),
        ("Max drawdown", f"{m['mdd']:.1%}", None),
        ("N days", f"{m['n_days']}", None),
    ])

    g1, g2 = st.columns(2)
    with g1:
        st.write("RankIC by forward-return horizon — a signal that decays fast is crowded.")
        st.plotly_chart(charts.decay_curve(m["decay"]), use_container_width=True)
    with g2:
        st.write("Dollar-neutral top/bottom-quintile book, growth of ₹1 (net of cost).")
        if m["_equity_returns"]:
            eq = pd.Series(m["_equity_returns"],
                           index=pd.to_datetime(m["_equity_dates"]))
            st.plotly_chart(charts.equity_curve(eq), use_container_width=True)
        else:
            st.info("The long-short book was empty for this split/signal.")

    with st.expander("Full Metrics dict"):
        st.json({k: v for k, v in m.items() if not k.startswith("_")})
    ui.source_note("src.backtester.backtest via dashboard.lib.engine.run_backtest")
else:
    st.caption("Press **Run backtest** to compute. First run ≈ 5–8 s (panel load); "
               "cached runs return in < 200 ms.")

# =========================================================================== #
# Section 3 — purge / embargo visualiser                                       #
# =========================================================================== #
ui.section(
    "3. Purge & embargo",
    help_text="Training rows whose label window overlaps a test block (purge) or "
              "fall within the embargo after it are dropped — "
              "`src.backtester.purge_embargo_mask`.",
)

st.write(
    "At the TRAIN → VAL_A boundary, a training row at day *t* earns its label over "
    "`open[t+1] → open[t+1+horizon]`; if that window reaches into VAL_A the row is "
    "**purged**. Rows within `embargo_days` after the block are **embargoed**."
)

pe_h = st.selectbox("Horizon for the purge window", [1, 2, 3, 5, 10, 21], index=3,
                    key="pe_h")
pe = eng.purge_embargo_demo(horizon=int(pe_h))

if pe["timeline"]:
    charts.kpi_row([
        ("TRAIN rows", f"{pe['n_train']}", None),
        ("Dropped near VAL_A", f"{pe['n_dropped']}", None),
        ("As % of TRAIN", f"{pe['dropped_pct']:.2f}%", None),
        ("Boundary", str(pe["boundary"])[:10], None),
    ])
    tl = pd.DataFrame(pe["timeline"])
    tl["date"] = pd.to_datetime(tl["date"])
    _state_colour = {
        "kept": charts.PALETTE["muted"],
        "purged": charts.PALETTE["neg"],
        "embargo": charts.PALETTE["accent2"],
        "test": charts.PALETTE["accent"],
    }
    import plotly.graph_objects as go

    fig_pe = go.Figure()
    for state, grp in tl.groupby("state"):
        fig_pe.add_bar(x=grp["date"], y=[1] * len(grp), name=state,
                       marker_color=_state_colour.get(state, charts.PALETTE["muted"]))
    fig_pe.update_layout(
        template=charts.TEMPLATE, barmode="stack", showlegend=True,
        yaxis=dict(visible=False), title="TRAIN→VAL_A boundary — day-by-day",
        margin=dict(l=20, r=20, t=50, b=30),
    )
    st.plotly_chart(fig_pe, use_container_width=True)
    st.caption(
        ":grey[Only one TRAIN→VAL_A boundary exists, so the dropped count is small "
        "relative to TRAIN. The purge window is `horizon + 1` days before the block; "
        "the embargo is 5 days after it (no TRAIN rows fall there at this boundary).]"
    )
else:
    st.info("Panel has no TRAIN or VAL_A rows.")
ui.source_note("src.backtester.purge_embargo_mask")

# =========================================================================== #
# Section 4 — the acceptance-evidence board                                    #
# =========================================================================== #
ui.section(
    "4. The acceptance-evidence board",
    help_text="Four live checks that the engine measures honestly. Computed on "
              "VAL_A when you press the button.",
)

st.write(
    "These are the P4 self-tests, run live: pure noise must look like noise, "
    "negation must flip the sign exactly, a look-ahead signal must be caught, and "
    "cost must monotonically erode Sharpe."
)

if st.button("▶ Run the evidence board (≈ 10 s)"):
    ev_formula = "sub(div(delay(close, 21), delay(close, 252)), 1)"  # 12-1 momentum
    with st.spinner("Running four checks on VAL_A …"):
        noise = eng.score_signal("noise", "val_a")
        leak = eng.score_signal("leaky", "val_a")
        pos = eng.run_backtest(ev_formula, "val_a", horizon=1)
        neg = eng.run_backtest(f"mul(-1, {ev_formula})", "val_a", horizon=1)
        sweep = [
            (c, eng.run_backtest(ev_formula, "val_a", horizon=1, cost_bps=float(c))["sharpe"])
            for c in (0, 5, 15, 30)
        ]

    rows = []
    ok_noise = abs(noise["rank_ic"]) < 0.01 and abs(noise["t_stat"]) < 2
    rows.append(("Random noise → |RankIC| < 0.01, |t| < 2",
                 f"RankIC = {noise['rank_ic']:+.4f}, t = {noise['t_stat']:+.2f}",
                 "✅" if ok_noise else "❌"))
    ok_neg = np.isclose(pos["rank_ic"], -neg["rank_ic"], atol=1e-9) and pos["sign"] == -neg["sign"]
    rows.append(("Signal vs its negation → RankIC flips exactly, sign flips",
                 f"{pos['rank_ic']:+.5f} (sign {pos['sign']:+d})  →  "
                 f"{neg['rank_ic']:+.5f} (sign {neg['sign']:+d})",
                 "✅" if ok_neg else "❌"))
    ok_leak = leak["rank_ic"] > 0.9
    rows.append(("Look-ahead signal `fwd_ret_1` → RankIC > 0.9 (engine sees leakage)",
                 f"RankIC = {leak['rank_ic']:.4f}",
                 "✅" if ok_leak else "❌"))
    sharpes = [s for _, s in sweep]
    ok_cost = all(a >= b - 1e-9 for a, b in zip(sharpes, sharpes[1:]))
    rows.append(("cost_bps ∈ {0,5,15,30} → Sharpe monotonically decreasing",
                 " → ".join(f"{s:.3f}" for s in sharpes),
                 "✅" if ok_cost else "❌"))

    st.dataframe(
        pd.DataFrame(rows, columns=["check", "measured", "result"]),
        use_container_width=True, hide_index=True,
    )
    st.plotly_chart(
        charts.bar(pd.DataFrame({"cost_bps": [str(c) for c, _ in sweep],
                                 "sharpe": sharpes}),
                   x="cost_bps", y="sharpe", title="Sharpe vs cost (12-1 momentum, VAL_A)"),
        use_container_width=True,
    )
    ui.source_note("src.backtester via dashboard.lib.engine — Ledger is never touched")
else:
    st.caption("Nothing is computed until you press the button (no network, no LLM).")
