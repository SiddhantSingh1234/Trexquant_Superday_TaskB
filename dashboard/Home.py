"""Alpha Factory Dashboard — "Start here" (built in D2).

The narrative companion to the presentation: the one-liner, the key numbers, the
six flowcharts, the reusable prose library, and a build-status board derived live
from ``reports/``.

Cold-loads in < 3 s: nothing here reads ``data/`` — the key-numbers row uses only
cheap catalogue counts and ``src.config``.  (Per DASHBOARD_PLAN §0.4 a page may
import ``src`` for metadata only; this page constructs no LLM client and runs no
backtest.)
"""
import re
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import streamlit as st

from dashboard.lib import data, flow, narrative, ui
from dashboard.lib.charts import kpi_row

st.set_page_config(page_title="Alpha Factory Dashboard", layout="wide")

# --------------------------------------------------------------------------- #
# cheap catalogue counts (metadata only — no data/, no LLM client)             #
# --------------------------------------------------------------------------- #
from src import config as cfg
from src.operators import OPERATORS
from src.redteam import DECISIVE_TESTS, REDTEAM_MENU
from src.zoo import ZOO

_PHASE_TITLES = flow._PHASE_TITLES  # {'p0': 'P0 scaffold', ...}


@st.cache_data(show_spinner=False)
def _handoff_headline(phase: str) -> str:
    """Pull a headline pass count out of ``reports/<phase>_handoff.md``."""
    text = data.load_handoff(phase)
    if not text:
        return "—"
    for pat in (r"(\d+)\s*/\s*\1\s*(?:P\d+\s*)?tests",
                r"\*\*(\d+)\s+passed\*\*",
                r"(\d+)\s+passed\s+in",
                r"→\s*\*\*(\d+)\s+passed",
                r"(\d+)\s+passed"):
        m = re.search(pat, text)
        if m:
            return f"{m.group(1)} passed"
    return "handoff present"


@st.cache_data(show_spinner=False)
def _date_span() -> str:
    lo = min(v[0] for v in cfg.SPLITS.values())
    hi = max(v[1] for v in cfg.SPLITS.values())
    return f"{lo.year}–{hi.year}"


@st.cache_data(show_spinner=False)
def _corpus_count() -> int:
    try:
        return len(data.load_corpus())
    except Exception:
        return 0


@st.cache_data(show_spinner=False)
def _tests_passing() -> str:
    """The latest existing handoff's headline count (rough 'tests passing' KPI)."""
    for phase in reversed(list(_PHASE_TITLES)):
        h = _handoff_headline(phase)
        if h not in ("—", "handoff present"):
            return f"{h} ({phase})"
    return "—"


# --------------------------------------------------------------------------- #
# header + one-liner                                                           #
# --------------------------------------------------------------------------- #
ui.page_header(
    "Alpha Factory Dashboard",
    "The AI-agent loop that invents, tests and filters stock-market alpha "
    "signals — a companion to the 20-minute walkthrough.",
    phase_tag="D2",
)
ui.stale_banner(data.cache_staleness())
st.markdown(narrative.block("one_liner"))

# --------------------------------------------------------------------------- #
# key numbers                                                                  #
# --------------------------------------------------------------------------- #
ui.section("Key numbers")
kpi_row([
    ("Universe", "200", "most liquid"),
    ("Date span", _date_span(), None),
    ("Features", "11", "10 + size_proxy"),
    ("Operators", str(len(OPERATORS)), "all causal"),
    ("Zoo formulas", str(len(ZOO)), None),
])
kpi_row([
    ("Corpus anomalies", str(_corpus_count()), None),
    ("Red-team tests", str(len(REDTEAM_MENU)), f"{len(DECISIVE_TESTS)} decisive"),
    ("Tokens / thesis", f"{cfg.LLM_TOKENS_PER_THESIS_PROJECTION:,}", "measured"),
    ("Holdout peeks", str(cfg.HOLDOUT_PEEK_BUDGET), "ever"),
    ("Tests passing", _tests_passing(), None),
])
ui.source_note("src.config · src.operators · src.zoo · src.redteam · reports/p*_handoff.md")

# --------------------------------------------------------------------------- #
# the pipeline                                                                 #
# --------------------------------------------------------------------------- #
ui.section("The nine-stage pipeline")
st.caption("One object — the Alpha Card — travels through nine stages and four "
           "gates. Everything rejected still goes to Memory.")
st.graphviz_chart(flow.render("pipeline"), use_container_width=True)
st.markdown(narrative.block("nine_stages"))
ui.source_note("FLOW_EXPLAINED.md PART 2")

# --------------------------------------------------------------------------- #
# the card lifecycle                                                           #
# --------------------------------------------------------------------------- #
ui.section("The Alpha Card, section by section")
st.graphviz_chart(flow.render("card_lifecycle"), use_container_width=True)
st.markdown(narrative.block("alpha_card"))
ui.source_note("FLOW_EXPLAINED.md PART 1")

# --------------------------------------------------------------------------- #
# the four data regions                                                        #
# --------------------------------------------------------------------------- #
ui.section("The four data regions")
st.caption("The search plays only on VAL_A. VAL_B confirms the winner for free. "
           "HOLDOUT is sealed behind a counted-peek budget.")
st.plotly_chart(flow.data_regions_timeline(), use_container_width=True)
st.markdown(narrative.block("four_regions"))
ui.source_note("IMPLEMENTATION_PLAN.md §0.4 · FLOW_EXPLAINED.md PART 3")

# --------------------------------------------------------------------------- #
# the five failure modes                                                       #
# --------------------------------------------------------------------------- #
ui.section("Five ways to be wrong")
st.markdown(narrative.block("five_failures"))

# --------------------------------------------------------------------------- #
# the three budgets                                                            #
# --------------------------------------------------------------------------- #
ui.section("The three budgets — and the two that fight each other")
st.markdown(narrative.block("three_budgets"))

# --------------------------------------------------------------------------- #
# over-searching                                                               #
# --------------------------------------------------------------------------- #
ui.section("Why searching harder fools you")
st.markdown(narrative.block("sqrt_2lnN"))
st.info("The interactive version — pick N, watch the Deflated Sharpe deflator "
        "move — lives on the **06 Gates & Ledger** page.")

# --------------------------------------------------------------------------- #
# the three distinctive mechanisms                                             #
# --------------------------------------------------------------------------- #
ui.section("The pre-registered sign")
st.markdown(narrative.block("pre_registered_sign"))

ui.section("The variant cap + the fresh fold")
st.markdown(narrative.block("variant_cap_fresh_fold"))

ui.section("Gate B — novelty first, then the maths, then one peek")
st.graphviz_chart(flow.render("gate_b"), use_container_width=True)
st.markdown(narrative.block("gate_b_order"))
ui.source_note("FLOW_EXPLAINED.md PART 2 (Gate B)")

# --------------------------------------------------------------------------- #
# the walkthrough                                                              #
# --------------------------------------------------------------------------- #
ui.section("One idea, walked all the way through")
st.markdown(narrative.block("walkthrough"))

# --------------------------------------------------------------------------- #
# novelty + weak points                                                        #
# --------------------------------------------------------------------------- #
ui.section("What is genuinely ours")
st.markdown(narrative.block("novelty_claims"))

ui.section("The honest weak points")
st.markdown(narrative.block("weak_points"))

# --------------------------------------------------------------------------- #
# data lineage                                                                 #
# --------------------------------------------------------------------------- #
ui.section("Where the data comes from")
st.graphviz_chart(flow.render("data_lineage"), use_container_width=True)
ui.source_note("reports/p1_handoff.md · reports/p2_handoff.md · reports/p3_handoff.md")

# --------------------------------------------------------------------------- #
# the P10 loop graph                                                           #
# --------------------------------------------------------------------------- #
ui.section("The orchestration loop (P10)")
st.caption("The LangGraph state machine: the inner judge⇄code loop capped at 20 "
           "per thesis, fresh-fold on VAL_B, novelty before stats, "
           "rejection-only red-team, reflect → should_continue.")
st.graphviz_chart(flow.render("loop_graph"), use_container_width=True)
ui.source_note("IMPLEMENTATION_PLAN.md Phase 10 · reports/p10_handoff.md")

# --------------------------------------------------------------------------- #
# build status board — derived from reports/                                   #
# --------------------------------------------------------------------------- #
ui.section("Build status")
st.markdown(narrative.block("build_status"))

status = flow.phase_status()
st.graphviz_chart(flow.render("phase_dag"), use_container_width=True)

rows = []
for phase, title in _PHASE_TITLES.items():
    done = status.get(phase, False)
    rows.append({
        "Phase": title,
        "Status": "done" if done else "pending",
        "Handoff headline": _handoff_headline(phase),
    })
st.dataframe(rows, use_container_width=True, hide_index=True)
n_done = sum(status.values())
st.caption(f"{n_done} / {len(status)} phases have a handoff on disk "
           f"(derived from `reports/p*_handoff.md` at page-load time).")
ui.source_note("reports/p0_handoff.md … reports/p13_handoff.md")

# --------------------------------------------------------------------------- #
# nav guide                                                                    #
# --------------------------------------------------------------------------- #
ui.section("What each page contains")
st.markdown(narrative.block("nav_guide"))

with st.expander("Artifact availability (live)", expanded=False):
    st.json(data.available())
