"""LLM Agents dashboard page.

The eight agents, model routing, the token budget.
"""
import importlib
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[2]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from dashboard.lib import charts, data, ui
from src import config
from src.agents import retrieve, load_corpus

st.set_page_config(page_title="LLM Agents", layout="wide")
ui.page_header(
    "LLM Agents", 
    "The eight agents, model routing, the token budget.", 
)
ui.stale_banner(data.cache_staleness())

# =========================================================================== #
# Section 1 - The eight agents                                                #
# =========================================================================== #
ui.section("1. The eight agents", help_text="The loop's AI participants.")

st.info("Deterministic computations (the backtester, the statistics, the novelty check) are NOT agents and do not appear here.")

budget_df = data.load_cache("agents_token_budget")

agent_rows = []
for role in config.AGENT_ROLES:
    tier = config.LLM_ROLE_TIER[role]
    chain = config.LLM_MODEL_CHAINS[tier]
    
    # Get schema keys
    try:
        mod = importlib.import_module(f"src.agents.{role}")
        schema_keys = mod.SCHEMA.get("required", []) if hasattr(mod, "SCHEMA") else []
    except Exception:
        schema_keys = []
        
    # Get calls per thesis
    calls = 0.0
    if not budget_df.empty and "role" in budget_df.columns:
        row = budget_df[budget_df["role"] == role]
        if not row.empty:
            calls = row.iloc[0]["calls_per_thesis"]
            
    agent_rows.append({
        "Role": role,
        "Tier": tier,
        "Model Chain": " → ".join(chain),
        "Output Schema Keys": ", ".join(schema_keys),
        "Calls / Thesis": float(calls)
    })

st.dataframe(pd.DataFrame(agent_rows), use_container_width=True, hide_index=True)
ui.source_note("src/config.py (AGENT_ROLES) + src/agents/* (schemas)")

# =========================================================================== #
# Section 2 - Model routing                                                   #
# =========================================================================== #
ui.section("2. Model routing", help_text="Fallback chain over pinned model.")

st.write(
    "PRE_BUILD_TASKS T3 guessed the model IDs. But when `models.list()` was actually called on "
    "2026-09-04 to settle it, three originally-planned IDs were already gone (a 404). "
    "This is the case for a probed fallback chain over a pinned model."
)
st.write(
    "At startup, the system probes the chain, skipping models that are missing or down. "
    "There is no hard-coded model ID anywhere in the core logic."
)

st.write("**Provider**: Groq (or `LLM_MODE=mock` for offline testing)")

st.write("**Current configured chains (rendered at run-time):**")
chains_df = pd.DataFrame([
    {"Tier": tier, "Models (ordered fallback)": ", ".join(chain)}
    for tier, chain in config.LLM_MODEL_CHAINS.items()
])
st.table(chains_df)
ui.source_note("src/config.py — LLM_MODEL_CHAINS")

# =========================================================================== #
# Section 3 - Token budget                                                    #
# =========================================================================== #
ui.section("3. Token budget", help_text="TPM bucket + TPD counter.")

st.write(
    f"Projected per thesis: ~16.6 LLM calls, ~{config.LLM_TOKENS_PER_THESIS_PROJECTION:,} tokens. "
    "At the free-tier limit, this gives a ceiling of ~20 theses/day."
)

if not budget_df.empty:
    _fig = charts.bar(budget_df, x="role", y="tokens_per_thesis", title="Tokens per thesis (by role)")
    st.plotly_chart(_fig, use_container_width=True)

st.markdown(
    "When a rate limit is hit, the system handles it:\n"
    "* **TPM (minute) exhausted**: The client bucket simply waits/throttles.\n"
    "* **TPD (day) exhausted**: A `BudgetExhausted` exception is raised, causing the loop to safely halt "
    "and write a resumable checkpoint."
)

st.write("**Measured per-model limits (overrides per-tier constants):**")
limits_rows = []
for m, lims in config.LLM_MODEL_LIMITS.items():
    limits_rows.append({
        "Model": m,
        "TPM (Tokens/Min)": lims.get("tpm", ""),
        "RPD (Reqs/Day)": lims.get("rpd", ""),
        "TPD Cap": lims.get("tpd_cap", "")
    })
st.table(pd.DataFrame(limits_rows))
st.caption(
    "These are stronger evidence than the per-tier constants, and the reason "
    "the budget is modelled per-model. Measured live from response headers."
)
ui.source_note("src/config.py — LLM_MODEL_LIMITS")

# =========================================================================== #
# Section 4 - The pre-registered sign                                         #
# =========================================================================== #
ui.section("4. The pre-registered sign", help_text="Preventing post-hoc narrative fitting.")

st.markdown("""
```mermaid
flowchart LR
    A[Hypothesis] --> B[Canonical JSON]
    B --> C[SHA256 Hash]
    C --> D[Timestamp]
    D --> E((Backtest))
    E --> F[check_sign]
```
""")

st.write(
    "The hypothesis agent must commit to a sign (-1 or 1) BEFORE any backtest runs. "
    "Later, `check_sign(pre, realized)` compares them. A mismatch is a THESIS FAILURE, "
    "not a sign flip."
)
ui.source_note("src/agents/hypothesis.py — commit_preregistration()")

# =========================================================================== #
# Section 5 - Corpus browser                                                  #
# =========================================================================== #
ui.section("5. Corpus browser", help_text="Knowledge base of alpha anomalies.")

_corpus = load_corpus()
st.write(f"**53 entries, 17 not tradeable.** (Actually loaded: {len(_corpus)} entries)")

_tradeable = st.toggle("Show only tradeable_with_our_data", value=False)
if _tradeable:
    _view_corpus = [c for c in _corpus if c.get("tradeable_with_our_data")]
else:
    _view_corpus = _corpus
    
if _view_corpus:
    _df = pd.DataFrame(_view_corpus)
    st.dataframe(_df, use_container_width=True)
    
    # corpus_family_counts bar
    family_counts = pd.Series([c.get("family", "unknown") for c in _corpus]).value_counts().reset_index()
    family_counts.columns = ["family", "count"]
    _fig2 = charts.bar(family_counts, x="family", y="count", title="Corpus entries per family")
    st.plotly_chart(_fig2, use_container_width=True)
else:
    st.info("Corpus is empty.")
    
ui.source_note("data/corpus/anomalies.json")

# =========================================================================== #
# Section 6 - Retrieval demo                                                  #
# =========================================================================== #
ui.section("6. Retrieval demo", help_text="Simulate the Librarian's search.")

_fam = st.text_input("Family", value="momentum")
_kw = st.text_input("Keyword box", value="price")

if st.button("Retrieve"):
    _results = retrieve(_fam, _kw)
    st.write(f"Returned {len(_results)} entries:")
    for r in _results:
        with st.expander(r.get("name", "Unknown")):
            st.json(r)
ui.source_note("src/agents/librarian.py — retrieve()")

# =========================================================================== #
# Section 7 - Prompt viewer                                                   #
# =========================================================================== #
ui.section("7. Prompt viewer", help_text="Static vs dynamic prompt parts.")

_pick_role = st.selectbox("Role", config.AGENT_ROLES)
if _pick_role:
    p_path = config.AGENT_PROMPTS_DIR / f"{_pick_role}.txt"
    if p_path.exists():
        text = p_path.read_text("utf-8")
        if "=== DYNAMIC ===" in text:
            parts = text.split("=== DYNAMIC ===")
            st.markdown("**Static Prefix (Cacheable):**")
            st.code(parts[0], language="markdown")
            st.markdown("**=== DYNAMIC ===**")
            st.code(parts[1], language="markdown")
        else:
            st.code(text, language="markdown")
    else:
        st.error(f"Prompt file not found at {p_path}")
        
ui.source_note("src/agents/prompts/*.txt")
