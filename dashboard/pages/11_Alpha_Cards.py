import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
from dashboard.lib import ui, narrative, data, charts
from dashboard.lib import fixtures
import json

st.set_page_config(layout="wide")
ui.page_header("Alpha Cards", "The accepted (and rejected) output of the factory")

ui.pending_banner("Alpha Cards", "P11 (a run that produces a card)")

ui.section("Card Schema")
st.markdown("A JSON document combining the economic thesis, the generated formula, the empirical metrics across all three data regions, the full red-team report, and the exact lineage and provenance.")

all_cards = data.load_cards()

if not all_cards:
    st.write("0 cards found.")
    preview = st.toggle("Preview with a sample card")
    if preview:
        all_cards = fixtures.fake_cards(1)
        st.write("Showing fake card.")

if all_cards:
    # filterable by verdict / thesis / generation
    verdicts = list(set([c.get("verdict") for c in all_cards]))
    theses = list(set([c.get("thesis_id") for c in all_cards]))
    gens = list(set([c.get("generation") for c in all_cards]))
    
    col1, col2, col3 = st.columns(3)
    selected_verdict = col1.selectbox("Verdict", ["All"] + verdicts)
    selected_thesis = col2.selectbox("Thesis ID", ["All"] + theses)
    selected_gen = col3.selectbox("Generation", ["All"] + [str(g) for g in gens])
    
    filtered_cards = all_cards
    if selected_verdict != "All":
        filtered_cards = [c for c in filtered_cards if c.get("verdict") == selected_verdict]
    if selected_thesis != "All":
        filtered_cards = [c for c in filtered_cards if c.get("thesis_id") == selected_thesis]
    if selected_gen != "All":
        filtered_cards = [c for c in filtered_cards if str(c.get("generation")) == selected_gen]
        
    for card in filtered_cards:
        with st.expander(f"Card {card.get('card_id')} - {card.get('verdict')}"):
            ui.section("Thesis")
            st.json(card.get("thesis", {}))
            
            ui.section("Pre-registered Sign & Hash")
            st.json(card.get("pre_registered", {}))
            
            ui.section("Formula & AST Tree")
            st.write("Formula:", card.get("formula"))
            st.write("AST Tree Canonical:", card.get("ast_canonical"))
            
            ui.section("Complexity")
            st.json(card.get("complexity", {}))
            
            ui.section("Metrics: Tier 1, Fresh Fold, Tier 2")
            st.json(card.get("tier1_metrics", {}))
            st.json(card.get("fresh_fold_metrics", {}))
            st.json(card.get("tier2_metrics", {}))
            
            ui.section("Audit Block")
            st.json(card.get("audit", {}))
            
            ui.section("Red-Team Report")
            st.json(card.get("redteam", {}))
            
            ui.section("Lineage Chain")
            st.json(card.get("lineage", {}))
            
            ui.section("Provenance")
            prov = card.get("provenance", {})
            st.write("Fields Used:", prov.get("fields_used", []))
            
            try:
                if "charts" in globals() and hasattr(charts, "decay_curve"):
                    fig = charts.decay_curve(card)
                    st.plotly_chart(fig)
            except Exception as e:
                pass
