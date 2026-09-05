import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
import pandas as pd
from dashboard.lib import ui, narrative, data, flow
from src.loop import (
    MAX_VARIANTS,
    FRESHFOLD_MIN_T,
    FDR_TIGHTEN_THRESHOLD,
    STOP_K_DEFAULT,
    CURRICULUM_ROTATION
)

st.set_page_config(layout="wide")
ui.page_header("The Loop", "Orchestration graph & run metrics")

# 1. Flow render
ui.section("1. Orchestration Graph")
st.markdown("The reflect -> should_continue -> orchestrate cycle is the OUTER loop (run_loop), not a graph edge.")
st.graphviz_chart(flow.render("loop_graph").source)
ui.source_note("src.loop.build_graph")

# 2. Enforcement points
ui.section("2. Enforcement Points")
st.markdown(f"Variant cap: MAX_VARIANTS={MAX_VARIANTS}, the judge->code counter, force_decision when it trips. Best of N noise ~ sqrt(2 ln N). Verified by test: max variant count is exactly 20 (`test_variant_cap_enforced_when_judge_always_refines`).")
st.markdown(f"Fresh fold: search on VAL_A, one winner confirmed on VAL_B at FRESHFOLD_MIN_T={FRESHFOLD_MIN_T}, no holdout peek spent. Verified by test: val_b_before_promote() is False (`test_no_val_b_call_before_promote`).")
st.markdown("Gate B ordering: novelty before statistics. Verified by test: novelty_always_before_stats() is True (`test_gate_b_novelty_precedes_statistics`).")

run_state = data.load_loop_run_state()
gens = data.load_loop_generations()
has_run = run_state is not None and not gens.empty

if not has_run:
    st.write("No run yet. Previewing with fake loop generations.")
    from dashboard.lib import fixtures
    gens = pd.DataFrame(fixtures.fake_loop_generations(5))
    run_state = {
        "status": "completed",
        "stopped_reason": "preview",
        "accepted_card_ids": ["c1", "c2"],
        "token_spend": 1000,
        "n_trials": 20,
        "holdout_peeks": 1,
        "gate_thresholds": {"t_stat_bar": 3.0, "min_marginal_ic": 0.01},
        "state_digest": "abcdef123"
    }

# 3. KPI row
ui.section("3. Run Summary KPI")
if has_run:
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Status", run_state.get("status", ""))
    col2.metric("Generations", len(gens))
    col3.metric("Accepted Cards", len(run_state.get("accepted_card_ids", [])))
    col4.metric("Holdout Peeks / 12", run_state.get("holdout_peeks", 0))
    # Using the thresholds from state if available
    thres = run_state.get("gate_thresholds", {})
    col5.metric("Final t_stat_bar", thres.get("t_stat_bar", "3.0"))
else:
    st.write("Fake KPIs", run_state)

# 4. Per-generation table + charts
ui.section("4. Per-Generation Analysis")
st.dataframe(gens)
st.markdown("Falling volume = real improvement, same volume in new clothes = drift.")
st.line_chart(gens.set_index("generation")["variant_count"])
# Stacked rejections
if "reject_reason" in gens.columns:
    rejects = gens.groupby(["generation", "reject_reason"]).size().unstack(fill_value=0)
    st.bar_chart(rejects)

# 5. Curriculum rotation
ui.section("5. Curriculum Rotation")
st.markdown("The Planner cannot spend a whole run in the market it likes. Curriculum regimes rotate every N generations.")
if "mandatory_regimes" in gens.columns:
    st.write(gens[["generation", "mandatory_regimes"]])

# 6. FDR auto-tightening
ui.section("6. FDR Auto-Tightening")
st.markdown("A control loop on the gate, not a fixed constant.")
# fake or real
st.write(f"Threshold: {FDR_TIGHTEN_THRESHOLD}")

# 7. Stop rule
ui.section("7. Stop Rule & Checkpoint")
st.markdown(f"budget exhausted -> checkpoint / STOP_K_DEFAULT={STOP_K_DEFAULT} flat generations / generation cap.")

# 8. Portfolio combination
ui.section("8. Portfolio Combination (off-loop)")
st.markdown("Does this add new information? is already Gate B's job. Handled off-loop.")

