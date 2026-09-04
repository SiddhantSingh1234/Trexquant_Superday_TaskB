"""Shared Streamlit UI helpers (DASHBOARD_PLAN.md Section 0.4).

Fully implemented in D0.  Every page uses these for a consistent header, the
two visually-distinct missing-data states, section headings, source captions
and the cache-staleness banner.

This module must not import ``src.*`` (asserted by the D0 test).
"""
from __future__ import annotations

import streamlit as st

# --------------------------------------------------------------------------- #
# Header + chrome                                                              #
# --------------------------------------------------------------------------- #
def page_header(title: str, subtitle: str = "", phase_tag: str | None = None) -> None:
    """A consistent H1 + caption.  ``phase_tag`` renders a small "built in D3" chip."""
    if phase_tag:
        st.markdown(
            f"<span style='background:#1A1F2B;border:1px solid #2E3646;"
            f"border-radius:10px;padding:2px 8px;font-size:0.75rem;"
            f"color:#9AA4B2'>built in {phase_tag}</span>",
            unsafe_allow_html=True,
        )
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def section(title: str, help_text: str = "") -> None:
    st.subheader(title)
    if help_text:
        st.caption(help_text)


def source_note(text: str) -> None:
    """A small grey caption naming the file(s) a chart came from."""
    st.caption(f":grey[Source: {text}]")


# --------------------------------------------------------------------------- #
# Missing / pending states — visually distinct (warning vs info)               #
# --------------------------------------------------------------------------- #
def pending_banner(what: str, blocked_on: str) -> None:
    st.warning(
        f"**{what}** is design-only until **{blocked_on}** ships. The layout below "
        f"is final; the live data will populate automatically once the artifact "
        f"exists."
    )


def data_missing(artifact: str, how_to_build: str) -> None:
    """``st.info`` with the exact command; the caller then calls ``st.stop()``."""
    st.info(
        f"**{artifact}** is not available yet.\n\n"
        f"Build it with:\n\n```\n{how_to_build}\n```"
    )


def stale_banner(names: list[str]) -> None:
    """No-op on an empty list; otherwise a single ``st.warning`` (Section 0.8.1 #3)."""
    if not names:
        return
    st.warning(
        f"cache is {len(names)} source(s) stale — run "
        f"`python dashboard/build_cache.py`  \n"
        f":grey[stale: {', '.join(sorted(names))}]"
    )


# --------------------------------------------------------------------------- #
# Small status vocabulary                                                      #
# --------------------------------------------------------------------------- #
_PILL = {
    "done": ("✅", "#2E7D32"),
    "pending": ("🕓", "#B26A00"),
    "partial": ("◐", "#1565C0"),
}


def status_pill(state: str) -> str:
    """``'done'|'pending'|'partial'`` → a coloured Markdown string."""
    icon, colour = _PILL.get(state, ("•", "#666"))
    return f"<span style='color:{colour}'>{icon} {state}</span>"
