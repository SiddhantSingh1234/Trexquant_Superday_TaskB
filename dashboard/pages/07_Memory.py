"""Memory — 07_Memory.py.

The six persistent memory stores that keep the loop from overfitting its own
SEARCH PROCESS, not just the signals it finds.

Per DASHBOARD_PLAN.md D6 Inputs, this page MAY import ``src.memory`` /
``src.config`` directly (metadata + read access — not the general lib-only
import fence in Section 0.4). It never writes to the live ``data/memory.db`` /
``data/lessons.db`` / ``data/bandit_state.json`` / ``data/book.parquet``:
every real-store read goes through a SNAPSHOT COPY (Section 0.8.1 #1 — a
``Memory``/``AlphaCardStore`` may only be constructed on ``":memory:"`` or a
snapshot path), and the lineage-viewer fixture demo writes only under
``data/dashboard/`` (the one directory this dashboard is allowed to write to).
"""
from __future__ import annotations

import shutil
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[2]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from dashboard.lib import charts, data, fixtures, ui
from src.memory import (
    AcceptedBook,
    BanditState,
    EXPLORATION_FLOOR,
    LESSON_CONFIDENCE_GATE,
    Memory,
    VETO_CONFIDENCE,
)

st.set_page_config(page_title="Memory", layout="wide")
ui.page_header(
    "Memory",
    "Six stores keep the loop from overfitting its own search process — "
    "not just the signals it finds.",
)
ui.stale_banner(data.cache_staleness())

# =========================================================================== #
# Helpers — read-only access to the real stores, via a SNAPSHOT copy          #
# =========================================================================== #
_SNAP_DIR = data.CACHE_DIR / "_snap" / "memory_page"
_FIXTURE_DIR = data.CACHE_DIR / "_fixture_memory"


def _real_memory() -> Memory | None:
    """A ``Memory`` opened on a snapshot of ``memory.db`` / ``lessons.db`` —
    never on the live ``data/`` path (Section 0.8.1 #1)."""
    live_mem = data.DATA_DIR / "memory.db"
    if not live_mem.exists():
        return None
    _SNAP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(live_mem, _SNAP_DIR / "memory.db")
    live_les = data.DATA_DIR / "lessons.db"
    if live_les.exists():
        shutil.copy2(live_les, _SNAP_DIR / "lessons.db")
    return Memory(base_dir=_SNAP_DIR, cards_dir=data.ARTIFACTS_DIR / "cards")


def _render_chain(chain: list[dict]) -> None:
    if not chain:
        st.info("Empty chain.")
        return
    cols = st.columns(len(chain))
    for col, card in zip(cols, chain):
        with col:
            if card.get("missing"):
                st.error(f"`{card['card_id']}`\n\n(JSON missing on disk)")
                continue
            if card.get("cycle_detected"):
                st.error(f"`{card['card_id']}`\n\n(cycle — broken defensively)")
                continue
            st.markdown(f"**`{card['card_id']}`**")
            st.caption(
                f"verdict: {card.get('verdict', '?')} · gen "
                f"{card.get('generation', '?')}"
            )
            motif = (card.get("lineage") or {}).get("edit_motif")
            if motif:
                st.caption(f"← edit motif: *{motif}*")
    st.caption(
        "root → … → selected:  "
        + " → ".join(f"`{c.get('card_id', '?')}`" for c in chain)
    )


# =========================================================================== #
# Section 1 — the six stores                                                  #
# =========================================================================== #
ui.section(
    "1. The six stores",
    help_text="Exact and semantic stores are physically separate files.",
)
st.write(
    "A multiple-testing count cannot be \"approximately right\" — so every "
    "**exact** store (the formula index, the card index, lineage — which "
    "feeds P6's trial ledger) lives in `data/memory.db`, while the "
    "**semantic** (fuzzy-retrieval) lesson store is a physically separate "
    "file, `data/lessons.db`. The two can never be confused for one another."
)
_STORES = pd.DataFrame([
    {"#": "①", "store": "FormulaIndex", "file": "data/memory.db  (table `formulas`)",
     "kind": "exact", "answers": "have we tried this exact formula? near-duplicates?"},
    {"#": "②", "store": "LessonStore", "file": "data/lessons.db  (table `lessons`)",
     "kind": "semantic", "answers": "did this edit motif help or hurt, in this context?"},
    {"#": "③", "store": "BanditState", "file": "data/bandit_state.json",
     "kind": "semantic", "answers": "how much search budget does each idea-family get next?"},
    {"#": "④", "store": "AlphaCardStore", "file": "data/memory.db  (table `card_index`) + artifacts/cards/*.json",
     "kind": "exact", "answers": "the demo artifact — one readable card per accepted signal"},
    {"#": "⑤", "store": "Lineage", "file": "data/memory.db  (table `lineage`)",
     "kind": "exact", "answers": "which card is this a child of, and by what edit?"},
    {"#": "⑥", "store": "AcceptedBook", "file": "data/book.parquet",
     "kind": "exact", "answers": "date × symbol × factor values, for orthogonalisation"},
])
st.dataframe(_STORES, use_container_width=True, hide_index=True)
ui.source_note("src/memory.py — module docstring, the six stores")

# =========================================================================== #
# Section 2 — the lesson store                                                #
# =========================================================================== #
ui.section(
    "2. Lesson store",
    help_text="Reusable motif knowledge — \"widening the window helped/hurt "
              "this kind of factor.\"",
)
_lessons_df = data.load_lessons()
if _lessons_df.empty:
    st.info(
        "`data/lessons.db` has 0 rows — no generation has completed a "
        "reflect step yet. Honest empty state below, plus an illustrative "
        "(fabricated) example of the shape a populated store takes."
    )
    st.caption(":grey[ILLUSTRATIVE EXAMPLE — not real data]")
    _fixture_lessons = pd.DataFrame([
        {"motif": "widen_window", "parent_context": "mom_21 → mom_63",
         "outcome": "rank_ic +0.004 on refine", "p_helps": 0.83, "confidence": 0.74,
         "n_observations": 5, "family": "momentum", "veto": False},
        {"motif": "shrink_lag", "parent_context": "delay(close,1) → delay(close,3)",
         "outcome": "rank_ic -0.006 x3, consistently", "p_helps": 0.09, "confidence": 0.86,
         "n_observations": 4, "family": "liquidity", "veto": True},
        {"motif": "add_sector_neutral", "parent_context": "raw → neutralize(sector)",
         "outcome": "rank_ic +0.001, mixed", "p_helps": 0.55, "confidence": 0.20,
         "n_observations": 2, "family": "reversal", "veto": False},
    ])
    st.dataframe(_fixture_lessons, use_container_width=True, hide_index=True)
    st.caption(
        "Row 2 shows the veto rule firing: `n_observations >= "
        f"{LESSON_CONFIDENCE_GATE}` and 2+ confident failures. Row 3 shows "
        "why a veto needs the gate — 2 observations is not enough to block "
        "anything, whatever the confidence."
    )
else:
    _cols = [c for c in ("motif", "parent_context", "outcome", "p_helps",
                         "confidence", "n_observations", "family", "veto")
             if c in _lessons_df.columns]
    st.dataframe(_lessons_df[_cols], use_container_width=True, hide_index=True)
ui.source_note("data/lessons.db — table `lessons`")

# =========================================================================== #
# Section 3 — the guards                                                      #
# =========================================================================== #
ui.section("3. The guards", help_text="Two defences against second-order overfitting.")
_g1, _g2 = st.columns(2)
with _g1:
    st.markdown("**Confidence gating**")
    st.write(
        f"A lesson is not returned as an applicable prior until "
        f"`n_observations >= {LESSON_CONFIDENCE_GATE}` "
        f"(`LessonStore.applicable_priors`). One or two data points never "
        f"move the Planner."
    )
with _g2:
    st.markdown("**Asymmetric, sticky veto**")
    st.write(
        f"A motif is hard-blocked once `n_observations >= "
        f"{LESSON_CONFIDENCE_GATE}` **and** at least 2 independent failures "
        f"were reported at confidence `>= {VETO_CONFIDENCE:.2f}`. Successes "
        f"never trigger a veto and — critically — never clear one; a veto is "
        f"**sticky**, lifted only by an explicit `clear_veto()` (a logged "
        f"human / Planner decision)."
    )
st.info(
    "`confidence` is **reliability, not direction** — a reliably-*harmful* "
    "motif has high `confidence` and a low `p_helps`; the harm is not "
    "hidden behind a small observation count."
)
ui.source_note("src/memory.py — LessonStore._veto_rule / _reliability")

# =========================================================================== #
# Section 4 — second-order overfitting                                        #
# =========================================================================== #
ui.section(
    "4. Second-order overfitting",
    help_text="Overfitting the SEARCH PROCESS, not just the signal.",
)
st.warning(
    "If Reflection writes *\"momentum fails\"* after three failures and the "
    "Planner then defunds momentum, an irreversible call has been made on "
    "n = 3 — and it never shows up in any backtest. The backtester scores "
    "signals, not the policy that generated them."
)
st.write(
    f"Two defences, and they are the only defence: **confidence gating** "
    f"(above) and the **exploration floor** — a family may be starved to "
    f"`EXPLORATION_FLOOR = {EXPLORATION_FLOOR:.0%}` of the budget, never to "
    f"0%. However badly a family has done, the loop keeps sampling it, so a "
    f"premature verdict is self-correcting rather than terminal."
)
ui.source_note("src/memory.py — module docstring \"SECOND-ORDER OVERFITTING\"")

# =========================================================================== #
# Section 5 — the bandit                                                      #
# =========================================================================== #
ui.section(
    "5. Bandit — search-budget allocation",
    help_text="A softmax over mean family reward, clamped up to the "
              "exploration floor and renormalised.",
)
_bandit_df = data.load_bandit()
try:
    _alloc = BanditState(data.DATA_DIR / "bandit_state.json").allocation()
except Exception:
    _alloc = {}

if _bandit_df.empty and not _alloc:
    st.info("`data/bandit_state.json` has no families registered yet.")
else:
    if _alloc:
        _alloc_df = pd.DataFrame(
            {"family": list(_alloc), "allocation": list(_alloc.values())}
        ).sort_values("allocation", ascending=False)
    else:
        _alloc_df = _bandit_df[["family"]].assign(allocation=0.0)
    _fig = charts.bar(_alloc_df, x="family", y="allocation",
                      title="Next-round budget share per family")
    _fig.add_hline(
        y=EXPLORATION_FLOOR, line_dash="dash", line_color=charts.PALETTE["neg"],
        annotation_text=f"{EXPLORATION_FLOOR:.0%} exploration floor",
    )
    st.plotly_chart(_fig, use_container_width=True)
    st.caption(
        "However badly a family has done, it keeps this floor — a "
        "premature \"X always fails\" verdict is self-correcting, not terminal."
    )
    ui.source_note("data/bandit_state.json — BanditState.allocation()")

    st.write("Rolling reward-delta history per family (most recent pulls):")
    _spark_rows = []
    if not _bandit_df.empty and "last_k_deltas" in _bandit_df.columns:
        for _, r in _bandit_df.iterrows():
            for i, d in enumerate(r["last_k_deltas"] or []):
                _spark_rows.append({"family": r["family"], "pull #": i, "delta": d})
    if _spark_rows:
        st.plotly_chart(
            charts.line(pd.DataFrame(_spark_rows), x="pull #", y="delta",
                       color="family", title="last_k_deltas per family"),
            use_container_width=True,
        )
    else:
        st.caption(":grey[No pulls recorded yet — every family is at n_pulls = 0.]")

    if not _bandit_df.empty:
        st.dataframe(
            _bandit_df[["family", "n_pulls", "cumulative_reward", "tokens_spent"]],
            use_container_width=True, hide_index=True,
        )
    ui.source_note("data/bandit_state.json")

# =========================================================================== #
# Section 6 — lineage                                                         #
# =========================================================================== #
ui.section(
    "6. Lineage",
    help_text="Each card has at most one parent — Memory(...).lineage_path(card_id) "
              "(a METHOD) walks the tree to the root.",
)
_mem = _real_memory()
_real_cards = _mem.cards.list_cards() if _mem is not None else []

if _real_cards:
    _ids = [c["card_id"] for c in _real_cards]
    _pick = st.selectbox("Card", _ids, key="lineage_real_pick")
    _chain = _mem.lineage_path(_pick)
    _render_chain(_chain)
    ui.source_note("data/memory.db (snapshot) — Memory(...).lineage_path(card_id)")
else:
    st.info(
        "No cards yet — `data/memory.db` has 0 rows in `card_index`. The "
        "loop has not produced an accepted card."
    )
    if st.button("Preview a fixture 3-generation lineage chain"):
        if _FIXTURE_DIR.exists():
            shutil.rmtree(_FIXTURE_DIR)
        _FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        _fm = Memory(base_dir=_FIXTURE_DIR)
        _fake = fixtures.fake_cards(3)
        for _c in _fake:
            _fm.cards.save_card(_c)
        st.session_state["_lineage_fixture_leaf"] = _fake[-1]["card_id"]
        _fm.close()

    if st.session_state.get("_lineage_fixture_leaf") and _FIXTURE_DIR.exists():
        st.warning("FIXTURE DATA below — not a real run (fixtures.fake_cards(3)).")
        _fm2 = Memory(base_dir=_FIXTURE_DIR)
        _chain2 = _fm2.lineage_path(st.session_state["_lineage_fixture_leaf"])
        _render_chain(_chain2)
        _fm2.close()
        ui.source_note("dashboard/lib/fixtures.fake_cards(3) — Memory(...).lineage_path(card_id)")

# =========================================================================== #
# Section 7 — the book                                                        #
# =========================================================================== #
ui.section(
    "7. The book — accepted factors",
    help_text="date × symbol × factor values for orthogonalisation (Gate B step 1).",
)
_book = AcceptedBook(data.DATA_DIR / "book.parquet")
_factors = _book.factors()
if not _factors:
    st.info(
        "`data/book.parquet` does not exist yet — no card has been accepted "
        "into the book. `AcceptedBook.factors()` → `[]` (the honest empty state)."
    )
else:
    st.write(f"{len(_factors)} accepted factor(s) in the book: {', '.join(_factors)}")
    _long = _book.get_book()
    _wide = _long.pivot_table(index="date", columns="factor", values="value", aggfunc="mean")
    _corr = _wide.corr()
    st.plotly_chart(
        charts.heatmap(_corr, title="Pairwise correlation of accepted factors", zmid=0.0),
        use_container_width=True,
    )
    ui.source_note("data/book.parquet — AcceptedBook.get_book()")
