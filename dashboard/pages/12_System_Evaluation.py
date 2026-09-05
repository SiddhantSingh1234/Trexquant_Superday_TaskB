import re
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from dashboard.lib import data, ui


def _markdown_table(report: str, heading: str) -> pd.DataFrame:
    """Return the first pipe table following a report heading."""
    parts = report.split(heading, 1)
    if len(parts) != 2:
        return pd.DataFrame()
    table_lines: list[str] = []
    for line in parts[1].splitlines():
        if line.startswith("|"):
            table_lines.append(line)
        elif table_lines:
            break
    if len(table_lines) < 3:
        return pd.DataFrame()

    def cells(line: str) -> list[str]:
        return [re.sub(r"\*", "", cell).strip() for cell in line.strip().strip("|").split("|")]

    headers = cells(table_lines[0])
    rows = [cells(line) for line in table_lines[2:]]
    return pd.DataFrame([row for row in rows if len(row) == len(headers)], columns=headers)


st.set_page_config(layout="wide")
ui.page_header("System Evaluation", "Overall factory metrics and ablation studies")

p12_content = data.load_report("p12_system_evaluation.md")
plots_dir = data.REPORTS_DIR / "p12_plots"

if not p12_content:
    ui.pending_banner("System evaluation & ablation", "P12 (src/evaluation.py)")
    st.info("Run `python scripts/p12_run_evaluation.py` to populate this page.")
    st.stop()

st.success("P12 evaluation completed. Results below are read from its generated report.")
ui.source_note("reports/p12_system_evaluation.md")

ui.section("1. Metric Definitions")
st.markdown("**Yield:** true positive alphas discovered per budget unit.  ")
st.markdown("**Honesty (FDR):** accepted cards that are actually junk, divided by all accepted cards.  ")
st.markdown("**Efficiency:** tokens and compute hours spent per accepted card.")

ui.section("2. Gate Ablation")
st.caption("Seeded pool: 10 genuine, 10 noise, 10 overfit, and 10 look-ahead-leaky factors.")
gate_table = _markdown_table(p12_content, "### 4.1 Per-gate catch rate / false-kill rate")
if not gate_table.empty:
    st.dataframe(gate_table, hide_index=True, width="stretch")

fdr_table = _markdown_table(p12_content, "### 4.2 Headline FDR, gate on vs. off")
if not fdr_table.empty:
    st.markdown("**Acceptance quality with each gate configuration**")
    st.dataframe(fdr_table, hide_index=True, width="stretch")

gate_plot = plots_dir / "gate_ablation.png"
if gate_plot.exists():
    st.image(str(gate_plot), caption="Per-gate catch and false-kill rates")
    ui.source_note("reports/p12_plots/gate_ablation.png")

ui.section("3. Real vs. Fake Learning")
st.markdown("Improvement means falling error **volume**; drift means the same volume in new clothes.")
learning_plot = plots_dir / "learning.png"
if learning_plot.exists():
    st.image(str(learning_plot), caption="Error-volume check across generations")
    ui.source_note("reports/p12_plots/learning.png")

with st.expander("Read the complete Phase 12 report"):
    st.markdown(p12_content)
