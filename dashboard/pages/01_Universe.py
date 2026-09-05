"""Universe — 01_Universe.py.

Proves the universe is survivorship-free, point-in-time, and flat at ~200
names throughout 2015-2025.

Sections
--------
1. THE DECISIVE COVERAGE CHART — n_panel per day, 200-name reference,
   OLS trend, FLAT/SLOPING verdict.
2. Liquidity floor — turnover_cutoff_200 + median_turnover over time.
3. Monthly churn — churn_pct bar, 2–5 % reference band.
4. Canary Gantt — DHFL, RCOM, JPASSOCIAT, YESBANK, SUZLON, IDEA.
5. Heavyweight Gantt — RELIANCE, TCS, SBIN, TATASTEEL, MARUTI, ONGC.
6. Sector composition — stacked area (labels are current, not point-in-time).
7. Index overlap — two overlap lines.
8. Membership explorer — date picker → 200 names; symbol picker → intervals.
9. (optional, behind a button) Live look-ahead check via src.universe.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from dashboard.lib import charts, data, ui

st.set_page_config(page_title="Universe", layout="wide")
ui.page_header(
    "Universe",
    "Survivorship-free · Point-in-time · Flat at ~200 names · 2015-2025",
)

# --------------------------------------------------------------------------- #
# Staleness banner                                                             #
# --------------------------------------------------------------------------- #
ui.stale_banner(data.cache_staleness())

# --------------------------------------------------------------------------- #
# Cache guard — must never raise; call data_missing + st.stop()               #
# --------------------------------------------------------------------------- #
_REQUIRED = [
    "universe_daily_coverage",
    "universe_monthly",
    "universe_intervals",
    "universe_sector_comp",
    "universe_overlap",
]
_missing = [n for n in _REQUIRED if data.try_cache(n) is None]
if _missing:
    ui.data_missing(
        f"Universe caches ({', '.join(_missing)})",
        "python dashboard/build_cache.py --only " + ",".join(_REQUIRED),
    )
    st.stop()

daily = data.load_cache("universe_daily_coverage")
monthly = data.load_cache("universe_monthly")
intervals = data.load_cache("universe_intervals")
sector_comp = data.load_cache("universe_sector_comp")
overlap = data.load_cache("universe_overlap")

# =========================================================================== #
# Section 1 — THE DECISIVE COVERAGE CHART                                     #
# =========================================================================== #
ui.section(
    "1. The decisive coverage chart",
    help_text=(
        "n_panel per day: symbols that were (a) in the universe AND "
        "(b) had a price on that date.  "
        "An upward slope would mean survivorship bias survived P1 — a hard stop."
    ),
)

st.write(
    "The chart below plots the number of names in the backtester panel each trading day. "
    "A flat series proves that the universe is reconstructed point-in-time — we never "
    "peek at whether a company survived to today."
)

fig_cov, meta_cov = charts.coverage_chart(daily, target=200)

# Verdicts are prominent
slope = meta_cov["slope_per_year"]
verdict = meta_cov["verdict"]
vcol = "green" if verdict == "FLAT" else "red"
st.markdown(
    f"**Verdict: :{vcol}[{verdict}]** — OLS slope = **{slope:+.2f} names/year** "
    f"(|slope| {'<' if verdict == 'FLAT' else '≥'} 3 names/yr threshold)",
)

st.plotly_chart(fig_cov, use_container_width=True)
ui.source_note("data/dashboard/universe_daily_coverage.parquet")

# KPI row
if len(daily):
    n_min = int(daily["n_panel"].min())
    n_max = int(daily["n_panel"].max())
    n_med = int(daily["n_panel"].median())
    gap_max = int(daily["gap"].max())
    charts.kpi_row([
        ("Median panel size", str(n_med), None),
        ("Min panel size", str(n_min), None),
        ("Max panel size", str(n_max), None),
        ("Max daily gap (members − panel)", str(gap_max), None),
    ])

# =========================================================================== #
# Section 2 — Liquidity floor                                                  #
# =========================================================================== #
ui.section(
    "2. Liquidity floor",
    help_text="turnover_cutoff_200 is the minimum daily turnover the 200th name needed; "
              "median_turnover shows how liquid the median name is.",
)

st.write(
    "The 200th-rank liquidity cutoff (red dashed) sets the membership bar. "
    "The median universe member (blue) sits comfortably above it. "
    "Both rising together confirm that overall market liquidity, not our filter, "
    "drives any trend."
)

if len(monthly):
    fig_liq = charts.line(
        monthly,
        x="month_end",
        y=["turnover_cutoff_200", "median_turnover"],
        title="Liquidity floor over time (₹ daily turnover)",
        y_title="₹ turnover",
    )
    st.plotly_chart(fig_liq, use_container_width=True)
else:
    st.info("Monthly cache is empty — run the builder.")
ui.source_note("data/dashboard/universe_monthly.parquet ← data/universe/universe_stats.parquet")

# =========================================================================== #
# Section 3 — Monthly churn                                                    #
# =========================================================================== #
ui.section(
    "3. Monthly churn",
    help_text="churn_pct = (names added this month) / universe_size × 100.  "
              "Target band: 2–5 %.",
)

st.write(
    "Churn measures how many new names enter the universe each month (exits mirror entries "
    "because total size is held at 200). A healthy universe has 2–5 % monthly turnover — "
    "enough for the point-in-time constraint to matter, not so much that it is unstable."
)

if len(monthly) and "churn_pct" in monthly.columns:
    import plotly.graph_objects as go

    fig_churn = charts.bar(monthly, x="month_end", y="churn_pct",
                           title="Monthly universe churn (%)")
    # 2–5 % reference band
    fig_churn.add_hrect(
        y0=2, y1=5, line_width=0,
        fillcolor=charts.PALETTE["pos"], opacity=0.10,
        annotation_text="2–5 % target band", annotation_position="top right",
    )
    st.plotly_chart(fig_churn, use_container_width=True)
else:
    st.info("Monthly cache is empty.")
ui.source_note("data/dashboard/universe_monthly.parquet")

# =========================================================================== #
# Section 4 — Canary Gantt                                                     #
# =========================================================================== #
ui.section(
    "4. Canary timeline — the universe is not survivorship-free by assumption",
    help_text="Each bar ends when the company stopped trading.  "
              "Nothing in the pipeline ever asks 'does this company still exist?'",
)

st.write(
    "The canaries are companies that were large and liquid when the period began but "
    "later went bankrupt, were delisted, or became penny stocks. "
    "They appear in the universe for exactly the period they were eligible — "
    "no implicit survivorship filter removed them prospectively."
)

canary_rows = intervals[intervals["kind"] == "canary"] if len(intervals) else intervals
if len(canary_rows):
    fig_canary = charts.gantt(
        canary_rows, start="start", end="end", label="symbol",
        title="Canary symbols — in-universe membership (end = last eligible date)",
    )
    st.plotly_chart(fig_canary, use_container_width=True)
else:
    st.info("No canary intervals in cache yet. Build with `python dashboard/build_cache.py`.")
ui.source_note("data/dashboard/universe_intervals.parquet ← src.universe.CANARIES")

# =========================================================================== #
# Section 5 — Heavyweight Gantt                                                #
# =========================================================================== #
ui.section(
    "5. Heavyweight timeline — anchor names present for most of the period",
    help_text="Their absence would signal a turnover-computation bug.",
)

st.write(
    "The blue-chip names — RELIANCE, TCS, SBIN, TATASTEEL, MARUTI, ONGC — "
    "are always the most liquid equities on NSE and must be in the universe "
    "for almost the entire 2015-2025 span. A gap here would indicate a data-ingestion error."
)

hw_rows = intervals[intervals["kind"] == "heavyweight"] if len(intervals) else intervals
if len(hw_rows):
    fig_hw = charts.gantt(
        hw_rows, start="start", end="end", label="symbol",
        title="Heavyweight symbols — continuous membership",
    )
    st.plotly_chart(fig_hw, use_container_width=True)
else:
    st.info("No heavyweight intervals in cache yet.")
ui.source_note("data/dashboard/universe_intervals.parquet ← src.universe.HEAVYWEIGHTS")

# =========================================================================== #
# Section 6 — Sector composition                                               #
# =========================================================================== #
ui.section(
    "6. Sector composition over time",
    help_text="Stacked area — sector labels are the company's CURRENT sector, "
              "not the point-in-time sector (P3 disclosure). "
              "Broadly stable shares confirm no sector-timing artifacts.",
)

st.write(
    "Sector weights are relatively stable over 2015–2025, dominated by Financial Services "
    "and Information Technology. Sudden shifts would indicate a data or labelling issue. "
    "**Note:** sector labels are derived from today's sector classification, not the "
    "historical sector on each date — this is disclosed in P3."
)

if len(sector_comp):
    fig_sec = charts.stacked_area(
        sector_comp, x="month_end", y="n_members", color="sector",
        title="Universe sector composition (current labels, not point-in-time)",
    )
    st.plotly_chart(fig_sec, use_container_width=True)
else:
    st.info("Sector composition cache is empty.")
ui.source_note("data/dashboard/universe_sector_comp.parquet")

# =========================================================================== #
# Section 7 — Index overlap                                                    #
# =========================================================================== #
ui.section(
    "7. Index overlap",
    help_text=(
        "Overlap with the NSE 'current' list and the supplied CSV snapshot. "
        "We call this 'the 200 most liquid Indian equities, reconstructed point-in-time "
        "from NSE daily bhavcopy' — NOT 'NIFTY 200'."
    ),
)

st.write(
    "The overlap lines show how similar our membership is to external lists at each month. "
    "~70–90 % overlap with the NIFTY 200 snapshots is expected: we select on daily "
    "liquidity rather than free-float market cap, so some divergence is structural, "
    "not a bug. This is why we explicitly call it **'the 200 most liquid Indian equities, "
    "reconstructed point-in-time from NSE daily bhavcopy'**, not 'NIFTY 200'."
)

if len(overlap):
    ov_cols = [c for c in ["overlap_nse_current_pct", "overlap_supplied_csv_pct"]
               if c in overlap.columns]
    if ov_cols:
        fig_ov = charts.line(
            overlap, x="month_end", y=ov_cols,
            title="Universe overlap with external index lists (%)",
            y_title="overlap (%)",
        )
        st.plotly_chart(fig_ov, use_container_width=True)
    else:
        st.info("Overlap columns not present in cache.")
else:
    st.info("Overlap cache is empty.")
ui.source_note("data/dashboard/universe_overlap.parquet")

# =========================================================================== #
# Section 8 — Membership explorer                                              #
# =========================================================================== #
ui.section(
    "8. Membership explorer",
    help_text="Pick a date to see the 200 names + their turnover rank. "
              "Or pick a symbol to see its membership intervals.",
)

tab_date, tab_sym = st.tabs(["📅 By date", "🔍 By symbol"])

with tab_date:
    st.write("Select a date to inspect the point-in-time universe membership.")
    try:
        mem = data.load_universe_membership()
        has_mem = True
    except FileNotFoundError:
        has_mem = False
        mem = None

    if has_mem and mem is not None and len(mem):
        import pandas as pd

        mem["date"] = pd.to_datetime(mem["date"])
        avail_dates = sorted(mem["date"].unique())
        # Date slider
        pick_date = st.date_input(
            "Select date",
            value=avail_dates[len(avail_dates) // 2].date(),
            min_value=avail_dates[0].date(),
            max_value=avail_dates[-1].date(),
        )
        pick_ts = pd.Timestamp(pick_date)
        # Nearest available date
        nearest = min(avail_dates, key=lambda d: abs(d - pick_ts))
        in_u = mem[(mem["date"] == nearest) & mem["in_universe"]]
        st.caption(f"Showing {len(in_u)} members on {nearest.date()} (nearest available date)")
        # Merge turnover rank if liquidity_ranks is available
        try:
            liq = data.load_liquidity_ranks()
            liq["month_end"] = pd.to_datetime(liq["month_end"])
            liq_month = pd.Timestamp(nearest.year, nearest.month, 1) + pd.offsets.MonthEnd(0)
            liq_snap = liq[liq["month_end"] == liq_month][["symbol", "liquidity_rank",
                                                              "trailing_turnover"]]
            in_u = in_u.merge(liq_snap, on="symbol", how="left")
            in_u = in_u.sort_values("liquidity_rank")
        except (FileNotFoundError, Exception):
            in_u = in_u.sort_values("symbol")
        st.dataframe(in_u.reset_index(drop=True), use_container_width=True, height=350)
    else:
        st.info(
            "Membership file not yet built. Run:\n\n"
            "```\npython dashboard/build_cache.py\n```"
        )
    ui.source_note("data/universe/membership.parquet · data/universe/liquidity_ranks.parquet")

with tab_sym:
    st.write("Select a symbol to see its membership intervals.")
    if len(intervals):
        all_syms = sorted(intervals["symbol"].unique())
        sym_pick = st.selectbox("Symbol", all_syms)
        sym_rows = intervals[intervals["symbol"] == sym_pick]
        st.dataframe(sym_rows.reset_index(drop=True), use_container_width=True)
        # Gantt for just this symbol
        if len(sym_rows):
            fig_sym = charts.gantt(sym_rows, start="start", end="end", label="symbol",
                                   title=f"{sym_pick} — membership spans")
            st.plotly_chart(fig_sym, use_container_width=True)
    else:
        st.info("Intervals cache is empty.")
    ui.source_note("data/dashboard/universe_intervals.parquet")

# =========================================================================== #
# Section 9 — Live look-ahead check (optional, behind a button)               #
# =========================================================================== #
ui.section(
    "9. Live look-ahead check (optional)",
    help_text="Calls src.universe.lookahead_check — truncated at 2020-01-01. "
              "Bit-identical reproduction means the point-in-time guarantee is enforced "
              "structurally, not by convention.",
)

st.write(
    "The look-ahead check re-runs the universe selection logic for every month up to "
    "2020-01-01 and compares the result to the stored membership. If every month is "
    "bit-identical, it proves that the pipeline was not peeking at future membership "
    "information when it computed features or labels."
)

if st.button("▶ Run look-ahead check (may take ~30s)"):
    with st.spinner("Running src.universe.lookahead_check up to 2020-01-01 …"):
        try:
            from src.universe import lookahead_check  # type: ignore[import]
            result = lookahead_check(up_to="2020-01-01")
            if result.get("ok"):
                st.success(
                    f"✅ PASS — {result.get('n_months', '?')} months checked, "
                    "all bit-identical."
                )
            else:
                st.error(
                    f"❌ FAIL — mismatch in months: {result.get('mismatches', [])}"
                )
            if "detail" in result:
                with st.expander("Detail"):
                    st.json(result["detail"])
        except ImportError:
            st.warning("`src.universe.lookahead_check` is not available on this install.")
        except Exception as exc:
            st.error(f"Error running look-ahead check: {exc}")
ui.source_note("src.universe.lookahead_check (live computation — not cached)")
