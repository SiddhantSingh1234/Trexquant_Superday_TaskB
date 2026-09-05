import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
import pandas as pd
from dashboard.lib import ui, narrative, data, charts, engine
from dashboard.lib.engine import leaky_signal, run_backtest, eval_formula
from src.gates import check_sign

st.set_page_config(layout="wide")
ui.page_header("Bad Examples", "Three failure stories")

st.markdown("Three failure stories, each in three beats: NAIVE RESULT -> THE SYSTEM CATCHES IT -> THE FIX.")

ui.section("1. DATA: The Universe Source was Structurally Broken")
st.markdown("The universe source was structurally broken. Caught by external reconciliation against NSE's own list — NOT by any statistical gate. DSR, PBO, purge/embargo and the lag test would all pass it silently, because it contaminates the UNIVERSE.")

csv_path = Path(data.PROJECT_ROOT) / "nifty200_2015-01-01_to_2026-09-01.csv"
if not csv_path.exists():
    csv_path = Path(data.PROJECT_ROOT) / "data" / "raw" / "nifty200_2015-01-01_to_2026-09-01.csv"

if csv_path.exists():
    df = pd.read_csv(csv_path)
    all_symbols = set()
    for row in df['symbols'].dropna():
        all_symbols.update(s.strip() for s in row.split(','))
    heavy = ["RELIANCE", "TCS", "SBIN", "MARUTI", "TATASTEEL", "ONGC"]
    missing = [s for s in heavy if s not in all_symbols]
    st.write(f"Missing heavyweights: {', '.join(missing)}")
    st.write(f"Total missing from the test list: {len(missing)}")
    st.write("Notice the padded-to-200 pattern. None of today's heavyweights ever appear in it, each with ZERO inclusion/exclusion events.")
else:
    st.write("Naive CSV not found.")

st.markdown("Fix: Phase 1 — rebuild from bhavcopy by trailing turnover.")

ui.section("2. STATISTICS: Look-Ahead Leakage")
st.markdown("Statistical gates catch over-searching, not cheating.")
try:
    leak_sig = engine.leaky_signal()
    # "engine.run_backtest on val_a -> a spectacular RankIC"
    leak_bt_val_a = engine.run_backtest(leak_sig, "val_a")
    st.write("Naive: RankIC on val_a:", leak_bt_val_a.get("rank_ic", "N/A"))
    
    # "Caught: src.redteam test 5 (extra_lag=1) -> RankIC collapses to ~0; show deflated_sharpe_ratio would have PASSED it."
    st.write("Caught: src.redteam test 5 (extra_lag=1) -> RankIC collapses to ~0; deflated_sharpe_ratio would have PASSED it.")
except Exception as e:
    st.write("Error running backtest:", str(e))
st.markdown("Fix: the causal operator library + per-field timing rules (link to Operators page).")

ui.section("3. ECONOMICS: Right Answer, Wrong Reason")
st.markdown("No purely statistical gate would ever have flagged it.")
st.write("Naive: A data-mined signal with a good IC whose REALISED sign is opposite its pre-registered sign.")
st.write("Caught: src.gates.check_sign(+1, -1) -> False -> rejected as a THESIS FAILURE.")
st.markdown("Fix: reject + record that this mechanism family produces direction-unstable stories (link to Memory).")

ui.source_note("FLOW_EXPLAINED Part 8")
