"""Build Log - dashboard page (built in D8).

D0 placeholder: renders the header only. D8 fills in the real content.
"""
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[2]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import streamlit as st

from dashboard.lib import ui

st.set_page_config(page_title="Build Log", layout="wide")
ui.page_header("Build Log", "Phase timeline, handoffs, the current test result.", phase_tag="D8")
st.info("This page is built in phase D8. The scaffold (header, nav slot) is in place.")
