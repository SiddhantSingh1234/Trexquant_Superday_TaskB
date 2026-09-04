"""System Evaluation - dashboard page (built in D7).

D0 placeholder: renders the header only. D7 fills in the real content.
"""
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[2]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import streamlit as st

from dashboard.lib import ui

st.set_page_config(page_title="System Evaluation", layout="wide")
ui.page_header("System Evaluation", "Yield / Honesty / Efficiency and the ablation table.", phase_tag="D7")
st.info("This page is built in phase D7. The scaffold (header, nav slot) is in place.")
