"""Operators & Zoo — 05_Operators_and_Zoo.py  (built in D4)

The formula toolbox: the causal operator library, the published-alpha zoo, the
AST parser, and a live sandbox.

This page MAY import ``src.operators`` / ``src.ast_tools`` / ``src.zoo`` /
``src.config`` directly (metadata + parsing only — DASHBOARD_PLAN §0.4).  It never
constructs an LLM client and never ``eval``s anything outside
``src.ast_tools.parse``.

Sections
--------
1. Operator catalog — grouped, with arity + the causality guarantee.
2. Causality evidence — a future input value cannot move an earlier output.
3. The zoo — 35 published / classical formulas, sortable, with complexity.
4. AST viewer — any formula rendered as a graphviz tree.
5. Formula sandbox — parse (strict) → canonical / fingerprint / complexity / preview.
6. Parser-rejection demo — four unsafe strings, each refused.
7. Duplicate detection — a commuted zoo formula still matches.
8. Zoo IC leaderboard — from cache, or computed inline.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import graphviz
import numpy as np
import pandas as pd
import streamlit as st

from dashboard.lib import charts, data, ui
from dashboard.lib import engine as eng
from src import operators as ops
from src.ast_tools import ParseError, canonical, complexity, fingerprint, parse
from src.zoo import ZOO, ZOO_BY_NAME, SKIPPED_ALPHA101, is_zoo_duplicate

st.set_page_config(page_title="Operators & Zoo", layout="wide")
ui.page_header(
    "Operators & Zoo",
    "Every operator is causal — formula-level look-ahead is structurally impossible.",
    phase_tag="D4",
)
ui.stale_banner(data.cache_staleness())

# =========================================================================== #
# Section 1 — operator catalog                                                 #
# =========================================================================== #
ui.section(
    "1. The operator catalog",
    help_text="Every formula the Coder agent builds is assembled from these — "
              "grouped by how they touch the data.",
)

st.write(
    "**Every operator is causal.** `delay` looks back, `ts_mean` averages a "
    "trailing window, `rank` compares today to today. No operator reaches forward "
    "— so formula-level look-ahead is *structurally impossible*, not hopefully caught."
)

_GROUPS = [
    ("Cross-sectional (same-day, no time axis)", sorted(ops.CROSS_SECTIONAL_OPS)),
    ("Time-series (strictly trailing)", sorted(ops.TIME_SERIES_OPS)),
    ("Element-wise (no time axis)", sorted(ops.ELEMENTWISE_OPS)),
]


def _describe(name: str) -> tuple[str, str]:
    fn = ops.OPERATORS[name]
    doc = (fn.__doc__ or "").strip().splitlines()
    desc = doc[0] if doc else ""
    params = list(inspect.signature(fn).parameters)
    return desc, ", ".join(params)


for title, names in _GROUPS:
    st.markdown(f"**{title}** — {len(names)} operators")
    rows = [(n, *_describe(n)) for n in names]
    st.dataframe(
        pd.DataFrame(rows, columns=["operator", "what it does", "arguments"]),
        use_container_width=True, hide_index=True,
    )
ui.source_note("src/operators.py — OPERATORS registry (causality asserted in tests/test_p5_operators.py)")

# =========================================================================== #
# Section 2 — causality evidence                                               #
# =========================================================================== #
ui.section(
    "2. Causality evidence",
    help_text="Change a FUTURE input value; every EARLIER output stays bit-identical.",
)

st.write(
    "A tiny 10-day, 3-name panel. We compute a trailing operator, then overwrite "
    "the **last** input row and recompute. If the operator were peeking, earlier "
    "outputs would move. They do not."
)

_op_pick = st.selectbox("Trailing operator", ["ts_mean", "ts_std", "delta", "delay", "decay_linear"])
_win = st.slider("Window `d`", 2, 5, 3, key="caus_win")

_rng = np.random.default_rng(eng.RANDOM_SEED)
_idx = pd.date_range("2020-01-01", periods=10, freq="B")
_x = pd.DataFrame(_rng.standard_normal((10, 3)).round(3),
                  index=_idx, columns=["AAA", "BBB", "CCC"])
_fn = ops.OPERATORS[_op_pick]
_before = _fn(_x, _win)
_x2 = _x.copy()
_x2.iloc[-1] = _x2.iloc[-1] + 99.0            # a wild change to the LAST day only
_after = _fn(_x2, _win)

_earlier_before = _before.iloc[:-1]
_earlier_after = _after.iloc[:-1]
_identical = _earlier_before.equals(_earlier_after) or np.allclose(
    _earlier_before.to_numpy(), _earlier_after.to_numpy(), equal_nan=True
)

c1, c2 = st.columns(2)
with c1:
    st.caption("Output — original input")
    st.dataframe(_before.round(4), use_container_width=True)
with c2:
    st.caption("Output — after the LAST input row was changed by +99")
    st.dataframe(_after.round(4), use_container_width=True)

if _identical:
    st.success(
        f"✅ Every output row before the last is **bit-identical** — "
        f"`{_op_pick}` cannot see the future."
    )
else:
    st.error("❌ An earlier output changed — this would be a look-ahead bug.")
ui.source_note("src/operators.py — evaluated on an in-memory fixture panel")

# =========================================================================== #
# Section 3 — the zoo                                                          #
# =========================================================================== #
ui.section(
    "3. The zoo — 35 published & classical formulas",
    help_text="The structural-novelty reference set (P6 Gate B step 2). A candidate "
              "that is a known published alpha in disguise is, by definition, crowded.",
)

st.write(
    "25 transcribed from Kakushadze, *101 Formulaic Alphas* (arXiv:1601.00991), plus "
    "10 classical factors. Sort any column. Complexity = the overfitting surface."
)

_zoo_rows = []
for e in ZOO:
    cx = complexity(e["formula"])
    _zoo_rows.append({
        "name": e["name"],
        "source": "Alpha101" if e["source"].startswith("Kakushadze") else "classical",
        "nodes": cx["nodes"], "depth": cx["depth"], "free_params": cx["free_params"],
        "formula": e["formula"],
    })
st.dataframe(pd.DataFrame(_zoo_rows), use_container_width=True, hide_index=True, height=380)

for skipped, why in SKIPPED_ALPHA101.items():
    st.caption(f":grey[**{skipped} skipped** — {why}.]")
ui.source_note("src/zoo.py — ZOO")

# =========================================================================== #
# Section 4 — AST viewer                                                       #
# =========================================================================== #
ui.section(
    "4. AST viewer",
    help_text="`src.ast_tools.parse(formula)` → a tuple tree, drawn as a graph.",
)


def _ast_graph(node: tuple, name: str = "root") -> graphviz.Digraph:
    g = graphviz.Digraph()
    g.attr("node", style="filled", fontname="Helvetica", color=charts.PALETTE["grid"],
           fontcolor=charts.PALETTE["text"])
    g.attr("edge", color=charts.PALETTE["muted"])
    g.attr(bgcolor="transparent")
    counter = [0]

    def add(n: tuple) -> str:
        counter[0] += 1
        nid = f"n{counter[0]}"
        tag = n[0]
        if tag == "const":
            g.node(nid, f"{n[1]:g}", shape="box", fillcolor="#1E5285")
        elif tag == "field":
            g.node(nid, n[1], shape="box", fillcolor="#2E7D32")
        else:  # op
            g.node(nid, n[1], shape="ellipse", fillcolor="#173A5E")
            for child in n[2]:
                g.edge(nid, add(child))
        return nid

    add(node)
    return g


_ast_choices = ["— pick a zoo formula —"] + [e["name"] for e in ZOO] + ["(free text)"]
_ast_sel = st.selectbox("Formula", _ast_choices, index=1)
if _ast_sel == "(free text)":
    _ast_formula = st.text_input("Formula for the AST", "mul(-1, ts_std(returns, 21))",
                                 key="ast_free")
elif _ast_sel.startswith("—"):
    _ast_formula = ""
else:
    _ast_formula = ZOO_BY_NAME[_ast_sel]["formula"]

if _ast_formula:
    st.code(_ast_formula, language="python")
    try:
        _node = parse(_ast_formula, strict=False)
        st.graphviz_chart(_ast_graph(_node), use_container_width=True)
    except ParseError as exc:
        st.error(f"ParseError: {exc}")
ui.source_note("src.ast_tools.parse")

# =========================================================================== #
# Section 5 — formula sandbox                                                  #
# =========================================================================== #
ui.section(
    "5. Formula sandbox",
    help_text="`parse(formula, strict=True)` → accept / reject, then the "
              "canonical form, fingerprint, complexity, and a one-number preview.",
)

_sbx = st.text_input("Formula", "rank(mul(-1, delta(close, 5)))", key="sandbox")
if _sbx.strip():
    try:
        _node = parse(_sbx, strict=True)
        st.success("✅ Accepted — valid Phase-5 formula.")
        cx = complexity(_sbx)
        charts.kpi_row([
            ("nodes", str(cx["nodes"]), None),
            ("depth", str(cx["depth"]), None),
            ("free params", str(cx["free_params"]), None),
            ("fingerprint", fingerprint(_sbx)[:10], None),
        ])
        st.markdown(f"**Canonical:** `{canonical(_sbx)}`")

        dup, match = is_zoo_duplicate(_sbx)
        if dup:
            st.warning(f"⚠️ Structural duplicate of **{match}** in the zoo.")
        else:
            st.caption(":grey[Not a structural match to any zoo formula.]")

        if st.button("Compute a one-number RankIC preview (VAL_A, h=1)"):
            if not eng.ensure_panel():
                st.info("The panel is not built — preview unavailable.")
            else:
                with st.spinner("Evaluating and scoring on VAL_A …"):
                    try:
                        m = eng.run_backtest(_sbx, "val_a", horizon=1)
                        st.metric("RankIC (VAL_A, h=1)", f"{m['rank_ic']:+.4f}",
                                  f"t = {m['t_stat']:+.2f}")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"{type(exc).__name__}: {exc}")
    except ParseError as exc:
        st.error(f"❌ Rejected — ParseError: {exc}")
ui.source_note("src.ast_tools · dashboard.lib.engine.eval_formula")

# =========================================================================== #
# Section 6 — parser-rejection demo                                            #
# =========================================================================== #
ui.section(
    "6. Parser-rejection demo",
    help_text="The whitelist rejects everything that is not an arithmetic "
              "expression over known fields and operators.",
)

st.write("Each of these is refused *structurally* — the string is never executed:")

_BAD = ["__import__('os')", "close.values", "[x for x in y]", "lambda x: x",
        "close; import os", "eval('1+1')"]
_bad_rows = []
for s in _BAD:
    try:
        parse(s, strict=True)
        _bad_rows.append((s, "❌ ACCEPTED (bug!)", ""))
    except ParseError as exc:
        _bad_rows.append((s, "✅ rejected", str(exc)))
    except Exception as exc:  # noqa: BLE001
        _bad_rows.append((s, "✅ rejected", f"{type(exc).__name__}: {exc}"))
st.dataframe(pd.DataFrame(_bad_rows, columns=["input", "result", "reason"]),
            use_container_width=True, hide_index=True)
ui.source_note("src.ast_tools.parse — the AST whitelist")

# =========================================================================== #
# Section 7 — duplicate detection                                              #
# =========================================================================== #
ui.section(
    "7. Duplicate detection — commuted operands still match",
    help_text="`canonical` sorts commutative operands, so `mul(a, b)` and "
              "`mul(b, a)` collapse to the same string.",
)

_orig = ZOO_BY_NAME["alpha101_014"]["formula"]
_commuted = "mul(correlation(open, volume, 10), mul(-1, rank(delta(returns, 3))))"
st.markdown(f"**Zoo original (`alpha101_014`):** `{_orig}`")
st.markdown(f"**Operands commuted (`a*b → b*a`):** `{_commuted}`")
_dup, _match = is_zoo_duplicate(_commuted)
if _dup:
    st.success(
        f"✅ Still detected as a duplicate of **{_match}** — "
        f"canonical forms are identical:\n\n`{canonical(_commuted)}`"
    )
else:
    st.error("❌ Not detected — the canonicaliser missed the commutation.")

st.write("Try your own — does it collide with a published alpha?")
_dup_try = st.text_input("Formula", "div(volume, ts_mean(volume, 21))", key="dup_try")
if _dup_try.strip():
    try:
        d, mt = is_zoo_duplicate(_dup_try)
        if d:
            st.warning(f"⚠️ Structural duplicate of **{mt}**. "
                       "A known published alpha in disguise is, by definition, crowded.")
        else:
            st.info("Novel — no structural match in the zoo.")
    except ParseError as exc:
        st.error(f"ParseError: {exc}")
ui.source_note("src.zoo.is_zoo_duplicate")

# =========================================================================== #
# Section 8 — zoo IC leaderboard                                               #
# =========================================================================== #
ui.section(
    "8. Zoo IC leaderboard",
    help_text="Each zoo formula scored on VAL_A. From the `zoo_leaderboard` cache "
              "if present, else computed inline.",
)

_lb_cache = data.try_cache("zoo_leaderboard")
_lb_df = None
if _lb_cache is not None and len(_lb_cache):
    _lb_df = _lb_cache
    st.caption(":grey[Source: data/dashboard/zoo_leaderboard.parquet]")
else:
    st.info("The `zoo_leaderboard` cache is not built (it is a `--heavy` builder). "
            "Compute it here — ~35 backtests on VAL_A. A minute or more "
            "(machine-dependent; each is cached, so a second visit is instant).")
    if st.button("▶ Compute the leaderboard now"):
        if not eng.ensure_panel():
            ui.data_missing("The panel", "python -m src.panel")
        else:
            prog = st.progress(0.0, text="Scoring zoo formulas …")
            rows = []
            names = [e["name"] for e in ZOO]
            for i, nm in enumerate(names, 1):
                rows.append(eng.zoo_backtest(nm, "val_a", 1))
                prog.progress(i / len(names), text=f"{nm} ({i}/{len(names)})")
            prog.empty()
            _lb_df = pd.DataFrame(rows)
            st.session_state["_zoo_lb"] = _lb_df
    elif "_zoo_lb" in st.session_state:
        _lb_df = st.session_state["_zoo_lb"]

if _lb_df is not None and len(_lb_df):
    show = _lb_df.copy()
    if "ok" in show.columns:
        n_fail = int((~show["ok"]).sum())
        if n_fail:
            st.caption(f":grey[{n_fail} formula(s) could not be scored — see the `error` column.]")
    for c in ("rank_ic", "icir", "t_stat", "sharpe"):
        if c in show.columns:
            show[c] = pd.to_numeric(show[c], errors="coerce")
    show = show.sort_values("rank_ic", ascending=False, na_position="last")
    st.dataframe(show, use_container_width=True, hide_index=True, height=380)

    plot_df = show.dropna(subset=["rank_ic"])
    if len(plot_df):
        st.plotly_chart(
            charts.bar(plot_df, x="name", y="rank_ic", sort="desc",
                       title="Zoo formula RankIC on VAL_A"),
            use_container_width=True,
        )
        st.caption(
            f":grey[{len(plot_df)} formulas scored · "
            f"best {plot_df['rank_ic'].max():+.4f} ({plot_df.iloc[0]['name']}) · "
            f"median {plot_df['rank_ic'].median():+.4f}]"
        )
    ui.source_note("src.backtester via dashboard.lib.engine.zoo_backtest")
