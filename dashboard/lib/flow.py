"""Flowchart + timeline builders (Section 0.4).

D2 implements all six ``DIAGRAMS`` + ``data_regions_timeline()``.  ``render(name)``
returns a ``graphviz.Digraph`` (which ``st.graphviz_chart`` accepts directly — it
reads ``.source``; no system Graphviz binary is required).

Import rule: this is one of the two ``lib`` modules allowed to import ``src`` —
and only ``src.config`` (asserted by the D0 import-fence test).
"""
from __future__ import annotations

from pathlib import Path

import graphviz
import plotly.graph_objects as go

from src.config import REPORTS_DIR, SPLITS

from .charts import PALETTE, TEMPLATE

DIAGRAMS: tuple[str, ...] = (
    "pipeline",
    "loop_graph",
    "gate_b",
    "data_lineage",
    "phase_dag",
    "card_lifecycle",
)

# --------------------------------------------------------------------------- #
# Shared graphviz styling                                                      #
# --------------------------------------------------------------------------- #
_BG = "transparent"
_FONT = "Helvetica"
_NODE = dict(style="filled,rounded", shape="box", fontname=_FONT,
             fontsize="11", color=PALETTE["grid"], fontcolor=PALETTE["text"])
_STAGE = PALETTE["accent"]
_GATE = PALETTE["pos"]
_REJECT = PALETTE["neg"]
_MEMORY = PALETTE["accent2"]
_MUTED = "#1A1F2B"


def _digraph(name: str, rankdir: str = "TB") -> graphviz.Digraph:
    g = graphviz.Digraph(name)
    g.attr(bgcolor=_BG, rankdir=rankdir, fontname=_FONT, fontcolor=PALETTE["text"],
           color=PALETTE["grid"])
    g.attr("node", **_NODE)
    g.attr("edge", color=PALETTE["muted"], fontname=_FONT, fontsize="9",
           fontcolor=PALETTE["muted"])
    return g


def _fill(g: graphviz.Digraph, node: str, label: str, colour: str,
          fontcolor: str = "#0E1117", **kw) -> None:
    g.node(node, label, fillcolor=colour, fontcolor=fontcolor, **kw)


# --------------------------------------------------------------------------- #
# 1 — the nine-stage pipeline (FLOW_EXPLAINED Part 2)                           #
# --------------------------------------------------------------------------- #
def _pipeline() -> graphviz.Digraph:
    g = _digraph("pipeline")
    stages = [
        ("S1", "S1 · Planner\n(what to work on, budgets)"),
        ("S2", "S2 · Librarian\n(papers + own memory → brief)"),
        ("S3", "S3 · Hypothesis\n(economic thesis + PRE-REGISTERED SIGN)"),
        ("S5", "S5 · Implementation loop\n(Coder ⇄ Judge, ≤ 20 attempts)"),
        ("S6", "S6 · Backtester\n(full rigorous battery)"),
        ("S9", "S9 · Memory & Reflection\n(write the lesson, nudge the Planner)"),
    ]
    for node, label in stages:
        _fill(g, node, label, _STAGE)

    gates = [
        ("GA", "GATE A · Economics\nreal story, or hand-waving?"),
        ("FF", "FRESH-FOLD CHECK\nwinner holds on VAL_B (never selected)?"),
        ("GB", "GATE B · Honesty\nis it NEW?  then: is it REAL?"),
        ("GC", "GATE C · Red-Team\n11 attacks, survive the 5 decisive ones"),
    ]
    for node, label in gates:
        _fill(g, node, label, _GATE)

    _fill(g, "CARD", "★ ALPHA CARD ★", _MEMORY)
    _fill(g, "MEM", "S9 · MEMORY\n(accepted AND rejected land here)", _MEMORY)

    g.edge("S1", "S2")
    g.edge("S2", "S3")
    g.edge("S3", "GA")
    g.edge("GA", "S5", label="pass")
    g.edge("S5", "FF")
    g.edge("FF", "S6", label="holds")
    g.edge("S6", "GB")
    g.edge("GB", "GC", label="new & real")
    g.edge("GC", "CARD", label="survives")
    g.edge("CARD", "MEM")
    g.edge("MEM", "S1", label="next generation", style="dashed")

    for src_node in ("GA", "FF", "GB", "GC"):
        g.edge(src_node, "MEM", label="reject", color=_REJECT, fontcolor=_REJECT,
               style="dashed", constraint="false")
    return g


# --------------------------------------------------------------------------- #
# 2 — the P10 LangGraph state machine (IMPLEMENTATION_PLAN Phase 10)            #
# --------------------------------------------------------------------------- #
def _loop_graph() -> graphviz.Digraph:
    g = _digraph("loop_graph")
    for node, label in [
        ("orchestrate", "orchestrate"),
        ("retrieve", "retrieve"),
        ("brief", "brief"),
        ("ideate", "ideate"),
        ("code", "code"),
        ("prefilter", "prefilter\n(compile / complexity / duplicate)"),
        ("tier1", "tier1  (VAL_A)"),
        ("judge", "judge"),
        ("freshfold", "freshfold  (VAL_B)"),
        ("tier2", "tier2\n(also ORTHOGONALIZES)"),
        ("emit_card", "emit_card"),
        ("reflect", "reflect"),
    ]:
        _fill(g, node, label, _STAGE)
    for node, label in [
        ("gate_a", "gate_a_economics"),
        ("gate_b_novelty", "gate_b_novelty\n(FREE)"),
        ("gate_b_stats", "gate_b_stats\n(DSR / t / PBO — spends a peek)"),
        ("gate_c_redteam", "gate_c_redteam"),
    ]:
        _fill(g, node, label, _GATE)
    _fill(g, "END", "END", _MUTED, fontcolor=PALETTE["text"])

    g.edge("orchestrate", "retrieve")
    g.edge("retrieve", "brief")
    g.edge("brief", "ideate")
    g.edge("ideate", "gate_a")
    g.edge("gate_a", "code", label="pass")
    g.edge("code", "prefilter")
    g.edge("prefilter", "tier1", label="ok")
    g.edge("tier1", "judge")
    with g.subgraph(name="cluster_inner") as c:
        c.attr(label="inner loop  ·  ≤ 20 / thesis", color=PALETTE["accent"],
               fontcolor=PALETTE["muted"], style="rounded")
        c.edge("judge", "code", label="refine")
    g.edge("judge", "freshfold", label="promote (best of ≤20)")
    g.edge("freshfold", "tier2", label="holds")
    g.edge("tier2", "gate_b_novelty")
    g.edge("gate_b_novelty", "gate_b_stats", label="pass")
    g.edge("gate_b_stats", "gate_c_redteam", label="pass")
    g.edge("gate_c_redteam", "emit_card", label="survive")
    g.edge("emit_card", "reflect")
    g.edge("reflect", "orchestrate", label="should_continue: continue")
    g.edge("reflect", "END", label="stop  (budget / K=3 flat gens / cap)")

    for src_node in ("gate_a", "prefilter", "freshfold", "gate_b_novelty",
                     "gate_b_stats", "gate_c_redteam"):
        g.edge(src_node, "reflect", label="reject", color=_REJECT,
               fontcolor=_REJECT, style="dashed", constraint="false")
    return g


# --------------------------------------------------------------------------- #
# 3 — Gate B internals (FLOW_EXPLAINED Gate B section)                          #
# --------------------------------------------------------------------------- #
def _gate_b() -> graphviz.Digraph:
    g = _digraph("gate_b")
    _fill(g, "orth", "1 · Orthogonalize\nsubtract what the book already owns\n→ the RESIDUAL signal", _STAGE)
    _fill(g, "nov", "2 · Novelty  (runs FIRST)\nmarginal IC on the residual ≈ 0?  → reject\nfree, and already computed", _GATE)
    _fill(g, "stats", "3 · Statistics on the RESIDUAL\nDeflated Sharpe vs effective trial count\nt-stat (one-sided) · PBO", _GATE)
    _fill(g, "peek", "4 · One rationed HOLDOUT peek\non the residual — 1 of 12, ever", _GATE)
    _fill(g, "pass", "→ Gate C · Red-Team", _MEMORY)
    _fill(g, "rej", "reject → Memory", _REJECT, fontcolor="#0E1117")

    g.edge("orth", "nov")
    g.edge("nov", "stats", label="marginal IC meaningful")
    g.edge("stats", "peek", label="DSR clears bar, PBO low")
    g.edge("peek", "pass", label="holds up")
    for n in ("nov", "stats", "peek"):
        g.edge(n, "rej", color=_REJECT, fontcolor=_REJECT, style="dashed",
               constraint="false")
    g.attr(label="novelty is free — a peek is 1 of 12.  Free filters that protect a "
                 "scarce resource go first.\nEverything from step 3 judges the RESIDUAL, "
                 "never the original signal.",
           labelloc="b", fontsize="10", fontcolor=PALETTE["muted"])
    return g


# --------------------------------------------------------------------------- #
# 4 — data lineage                                                             #
# --------------------------------------------------------------------------- #
def _data_lineage() -> graphviz.Digraph:
    g = _digraph("data_lineage", rankdir="LR")
    _fill(g, "nse", "raw NSE daily bhavcopy\n(legacy + sec_bhavdata_full)", _MUTED,
          fontcolor=PALETTE["text"])
    _fill(g, "ca", "corporate-actions API\n(splits / bonuses / dividends)", _MUTED,
          fontcolor=PALETTE["text"])
    _fill(g, "ohlcv", "ohlcv.parquet\n(CA-adjusted, symbol-keyed)", _STAGE)
    _fill(g, "memb", "universe/membership.parquet\n(top-200 by 63d median turnover,\npoint-in-time)", _STAGE)
    _fill(g, "panel", "panel/features.parquet\n+ labels.parquet + splits.json", _STAGE)
    _fill(g, "bt", "backtester\n(one engine, causal operators)", _GATE)
    _fill(g, "gr", "gates + red-team\n(DSR / PBO / 11 attacks)", _GATE)
    _fill(g, "out", "Alpha Cards\n+ trial ledger\n+ accepted book", _MEMORY)

    g.edge("nse", "ohlcv")
    g.edge("ca", "ohlcv")
    g.edge("ohlcv", "memb")
    g.edge("ohlcv", "panel")
    g.edge("memb", "panel")
    g.edge("panel", "bt")
    g.edge("bt", "gr")
    g.edge("gr", "out")
    return g


# --------------------------------------------------------------------------- #
# 5 — the phase DAG, coloured done / pending from reports/                      #
# --------------------------------------------------------------------------- #
_PHASE_TITLES = {
    "p0": "P0 scaffold", "p1": "P1 universe", "p2": "P2 prices",
    "p3": "P3 panel", "p4": "P4 backtester", "p5": "P5 operators",
    "p6": "P6 gates+ledger", "p7": "P7 memory", "p8": "P8 agents",
    "p9": "P9 red-team", "p10": "P10 loop", "p11": "P11 demo",
    "p12": "P12 evaluation", "p13": "P13 slides",
}


def phase_status() -> dict[str, bool]:
    """``{'p0': True, ...}`` — a phase is *done* iff its handoff file exists.
    Derived, never hard-coded (P11/P12 may land while the dashboard is built)."""
    out: dict[str, bool] = {}
    for key in _PHASE_TITLES:
        out[key] = (Path(REPORTS_DIR) / f"{key}_handoff.md").exists()
    return out


def _phase_dag() -> graphviz.Digraph:
    g = _digraph("phase_dag", rankdir="LR")
    status = phase_status()

    def add(key: str) -> None:
        done = status.get(key, False)
        # Use a single-line label (no literal newline) so the DOT source keeps
        # "pending" on the same line as the node ID — the test searches
        # each line independently via splitlines().
        suffix = "" if done else " (pending)"
        _fill(g, key, _PHASE_TITLES[key] + suffix,
              _STAGE if done else _MUTED,
              fontcolor="#0E1117" if done else PALETTE["muted"])

    for key in _PHASE_TITLES:
        add(key)

    # critical path
    for a, b in [("p0", "p2"), ("p2", "p1"), ("p1", "p3"), ("p3", "p4"),
                 ("p4", "p6"), ("p6", "p10"), ("p10", "p11"), ("p11", "p13")]:
        g.edge(a, b)
    # parallel branch P5/P7/P8/P9 feed the loop
    for key in ("p5", "p7", "p8", "p9"):
        g.edge("p4", key, style="dashed")
        g.edge(key, "p10", style="dashed")
    g.edge("p11", "p12", style="dashed")
    g.edge("p12", "p13", style="dashed")
    return g


# --------------------------------------------------------------------------- #
# 6 — the Alpha Card lifecycle (a stack that grows one section per stage)       #
# --------------------------------------------------------------------------- #
def _card_lifecycle() -> graphviz.Digraph:
    g = _digraph("card_lifecycle")
    steps = [
        ("s0", "S3 · thesis + mechanism + counterparty\n+ PRE-REGISTERED SIGN (locked)"),
        ("s1", "S5 · formula + canonical AST + complexity"),
        ("s2", "S6 · tier-1 metrics (VAL_A)"),
        ("s3", "fresh-fold metrics (VAL_B)"),
        ("s4", "tier-2 metrics + honesty audit (residual)"),
        ("s5", "Gate C · red-team report"),
        ("s6", "verdict + lineage (parent card, edit motif)\n+ provenance (fields used)"),
    ]
    for node, label in steps:
        _fill(g, node, label, _MEMORY, fontcolor="#0E1117")
    for (a, _), (b, _) in zip(steps, steps[1:]):
        g.edge(a, b, label="+ section")
    g.attr(label="a rejected card gets every section it reached, plus its "
                 "death-certificate reason — that is what makes the factory improve.",
           labelloc="b", fontsize="10", fontcolor=PALETTE["muted"])
    return g


# --------------------------------------------------------------------------- #
# dispatch                                                                     #
# --------------------------------------------------------------------------- #
_BUILDERS = {
    "pipeline": _pipeline,
    "loop_graph": _loop_graph,
    "gate_b": _gate_b,
    "data_lineage": _data_lineage,
    "phase_dag": _phase_dag,
    "card_lifecycle": _card_lifecycle,
}


def render(name: str) -> graphviz.Digraph:
    """Return a ``graphviz.Digraph`` ``st.graphviz_chart`` renders directly."""
    if name not in DIAGRAMS:
        raise KeyError(f"unknown diagram {name!r}; valid: {DIAGRAMS}")
    return _BUILDERS[name]()


# --------------------------------------------------------------------------- #
# the data-regions timeline (Plotly)                                           #
# --------------------------------------------------------------------------- #
_ROLE = {
    "warmup": ("warm-up buffer", PALETTE["muted"]),
    "train": ("warm-up buffer + CSCV folds", PALETTE["muted"]),
    "val_a": ("search — every variant scored here", PALETTE["accent"]),
    "val_b": ("confirm — only the promoted winner", PALETTE["accent2"]),
    "holdout": ("sealed vault — 12 counted peeks, ever", PALETTE["neg"]),
}


def data_regions_timeline() -> go.Figure:
    """A horizontal bar per region from ``region_dates()``, coloured by role."""
    import pandas as pd

    fig = go.Figure()
    order = [r for r in ("holdout", "val_b", "val_a", "train", "warmup")
             if r in SPLITS]
    for region in order:
        lo, hi = SPLITS[region]
        lo, hi = pd.Timestamp(lo), pd.Timestamp(hi)
        role, colour = _ROLE.get(region, (region, PALETTE["accent"]))
        fig.add_trace(go.Bar(
            base=[lo], x=[hi - lo], y=[region.upper()], orientation="h",
            marker_color=colour, name=role, hovertext=f"{role}<br>{lo.date()} → {hi.date()}",
            hoverinfo="text", showlegend=True,
        ))
    fig.update_layout(
        template=TEMPLATE, barmode="overlay", height=280,
        title="The four data regions (src.config.SPLITS)",
        xaxis_title="", yaxis_title="", legend=dict(orientation="h", y=-0.25),
    )
    hi_lo, hi_hi = SPLITS["holdout"]
    fig.add_annotation(x=pd.Timestamp(hi_lo) + (pd.Timestamp(hi_hi) - pd.Timestamp(hi_lo)) / 2,
                       y="HOLDOUT", text="12 counted peeks", showarrow=False,
                       font=dict(color="#0E1117", size=11))
    return fig


def region_dates() -> dict:
    """``{'warmup': (start, end), ...}`` from ``src.config.SPLITS`` (read live)."""
    return {name: (lo, hi) for name, (lo, hi) in SPLITS.items()}
