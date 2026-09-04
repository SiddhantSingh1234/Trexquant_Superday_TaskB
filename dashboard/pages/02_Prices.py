"""Prices — 02_Prices.py  (built in D3)

Explores price data coverage, corporate-action adjustments, data quality
and the per-symbol candlestick drill-down.

Sections
--------
1. Coverage by year — covered_pct + n_symbols.
2. Corporate actions — stacked bar + table.
2b. Symbol-vs-ISIN identity (isin_map.parquet) + size_proxy note.
3. Extreme returns — table + count bar.
4. Source eras — timeline.
5. Delivery availability — first available date + coverage line.
6. VWAP sanity gauge — % rows with low ≤ vwap ≤ high (target ~100%).
7. Quality board — close≤0 / high<low / negative volume — pills.
8. yfinance cross-check — histogram if cache present, else pending_banner.
9. Per-symbol candlestick — sliced load_ohlcv(symbols=[sym]) + CA markers.

CONTRACT: load_ohlcv is NEVER called with no filter (tested by test_dash_p3_data.py).
The page NEVER hits the network on load.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from dashboard.lib import charts, data, ui

st.set_page_config(page_title="Prices", layout="wide")
ui.page_header(
    "Prices",
    "Coverage · CA adjustment · Data quality · Per-symbol candlesticks",
    phase_tag="D3",
)

ui.stale_banner(data.cache_staleness())

# --------------------------------------------------------------------------- #
# Cache guard                                                                  #
# --------------------------------------------------------------------------- #
_REQUIRED = [
    "prices_coverage_yearly",
    "prices_ca_counts",
    "prices_extreme_returns",
    "prices_source_eras",
    "prices_vwap_sanity",
    "prices_quality",
]
_missing = [n for n in _REQUIRED if data.try_cache(n) is None]
if _missing:
    ui.data_missing(
        f"Prices caches ({', '.join(_missing)})",
        "python dashboard/build_cache.py --only " + ",".join(_REQUIRED),
    )
    st.stop()

cov_yr = data.load_cache("prices_coverage_yearly")
ca_counts = data.load_cache("prices_ca_counts")
extreme = data.load_cache("prices_extreme_returns")
source_eras = data.load_cache("prices_source_eras")
vwap = data.load_cache("prices_vwap_sanity")
quality = data.load_cache("prices_quality")
yf_cross = data.try_cache("prices_yf_crosscheck")  # optional — may be None

# =========================================================================== #
# Section 1 — Coverage by year                                                #
# =========================================================================== #
ui.section(
    "1. Coverage by year",
    help_text="We need every stock ever in the universe, including the ~115 that "
              "were dropped or went bankrupt — that is survivorship-free coverage.",
)

st.write(
    "Each year's coverage shows the fraction of universe-days on which a stock "
    "had a price record. Coverage below 99 % indicates data gaps, not missing stocks — "
    "short trading halts are normal. The distinct-symbol count exceeds 200 because we "
    "carry every stock that *ever* appeared in the universe over the decade."
)

if len(cov_yr):
    col1, col2 = st.columns(2)
    with col1:
        fig_cov = charts.bar(cov_yr, x="year", y="covered_pct",
                             title="Price coverage per year (%)")
        st.plotly_chart(fig_cov, use_container_width=True)
    with col2:
        fig_nsym = charts.bar(cov_yr, x="year", y="n_symbols",
                              title="Distinct symbols with prices per year")
        st.plotly_chart(fig_nsym, use_container_width=True)
    # KPI
    avg_cov = float(cov_yr["covered_pct"].mean())
    charts.kpi_row([
        ("Average annual coverage", f"{avg_cov:.1f}%", None),
        ("Total distinct symbols", str(int(cov_yr["n_symbols"].max())), None),
        ("Years tracked", str(int(cov_yr["year"].nunique())), None),
    ])
else:
    st.info("Coverage cache is empty.")
ui.source_note("data/dashboard/prices_coverage_yearly.parquet")

# =========================================================================== #
# Section 2 — Corporate actions                                                #
# =========================================================================== #
ui.section(
    "2. Corporate actions (CA) adjustments",
    help_text="bhavcopy is unadjusted. A 1:10 split reads as −90% until corrected. "
              "Demergers are flagged, not attempted.",
)

st.write(
    "NSE bhavcopy provides unadjusted close prices. We apply backward-ratio adjustments "
    "for stock splits and bonus shares. Dividends are small and ignored (consistent with "
    "the short 1–21 day return horizons). Demergers create a structural discontinuity "
    "that a ratio-based approach cannot fix — those are flagged but not corrected; the "
    "CA parser noted ~7 splits it could not resolve in P3."
)

if len(ca_counts):
    fig_ca = charts.stacked_area(
        ca_counts, x="year", y="n", color="type",
        title="Corporate-action counts by year and type",
    )
    st.plotly_chart(fig_ca, use_container_width=True)
    with st.expander("Corporate action raw table"):
        st.dataframe(ca_counts, use_container_width=True)
else:
    st.info("CA counts cache is empty.")
ui.source_note(
    "data/dashboard/prices_ca_counts.parquet ← data/prices/corporate_actions.parquet"
)

# Section 2b — Symbol / ISIN identity
ui.section(
    "2b. Symbol-vs-ISIN identity",
    help_text="Renames and mergers mean one ISIN can carry multiple symbols (or vice versa). "
              "This is the evidence for the symbol-keyed CA-adjustment decision P2 disclosed.",
)

st.write(
    "NSE assigns ISINs to instruments. When a company renames or merges, the ISIN may "
    "transfer to a new symbol. The CA adjustment pipeline uses symbol-keyed lookups; "
    "P2 discloses and accepts the small number of cases where this misses an action "
    "across a rename. The `size_proxy` feature in the panel is derived from "
    "`data/prices/size_proxy.parquet` (market-cap proxy built from P2 data)."
)

_isin_path = data.DATA_DIR / "prices" / "isin_map.parquet"
_sp_path = data.DATA_DIR / "prices" / "size_proxy.parquet"

col_a, col_b = st.columns(2)
with col_a:
    if _isin_path.exists():
        isin_df = pd.read_parquet(_isin_path)
        n_isin_changed = int(
            isin_df.groupby("symbol")["isin"].nunique().gt(1).sum()
        ) if "isin" in isin_df.columns and "symbol" in isin_df.columns else 0
        n_isin_multi = int(
            isin_df.groupby("isin")["symbol"].nunique().gt(1).sum()
        ) if "isin" in isin_df.columns and "symbol" in isin_df.columns else 0
        st.metric("Symbols with ISIN change (renames/mergers)", n_isin_changed)
        st.metric("ISINs carrying > 1 symbol", n_isin_multi)
        with st.expander("isin_map sample"):
            st.dataframe(isin_df.head(20), use_container_width=True)
    else:
        st.info("`data/prices/isin_map.parquet` not present — P2 artefact.")

with col_b:
    if _sp_path.exists():
        sp = pd.read_parquet(_sp_path)
        st.metric("size_proxy rows", len(sp))
        st.caption(
            "data/prices/size_proxy.parquet — market-cap proxy used as the panel's "
            "`size_proxy` feature. Coverage tracks the price panel."
        )
    else:
        st.info("`data/prices/size_proxy.parquet` not present — P2 artefact.")

ui.source_note(
    "data/prices/isin_map.parquet · data/prices/size_proxy.parquet (P2 deliverables)"
)

# =========================================================================== #
# Section 3 — Extreme returns                                                  #
# =========================================================================== #
ui.section(
    "3. Extreme returns (|ret| > 50 %)",
    help_text="Not winsorized — Indian mid-caps genuinely move like that. "
              "Each row is tagged as explained-by-CA or left flagged.",
)

st.write(
    "Daily returns exceeding ±50 % almost always trace to a missed CA: a stock split "
    "whose ex-date hit before the adjustment script ran. Each row is tagged against "
    "the corporate-action table — rows without a nearby CA event are left as-is "
    "and are **not winsorized** (winsorizing would hide real data-quality gaps)."
)

if len(extreme):
    # Bar: count of extreme returns by year
    ext2 = extreme.copy()
    ext2["year"] = pd.to_datetime(ext2["date"]).dt.year
    cnt = ext2.groupby("year").size().rename("n").reset_index()
    fig_ext = charts.bar(cnt, x="year", y="n",
                         title="Count of |daily return| > 50% per year")
    st.plotly_chart(fig_ext, use_container_width=True)
    with st.expander(f"Extreme-return table ({len(extreme)} rows)"):
        st.dataframe(extreme.sort_values("date", ascending=False).reset_index(drop=True),
                     use_container_width=True)
else:
    st.success("No extreme returns found in the adjusted series — quality check passes.")
ui.source_note(
    "data/dashboard/prices_extreme_returns.parquet ← data/prices/ohlcv.parquet"
)

# =========================================================================== #
# Section 4 — Source eras                                                      #
# =========================================================================== #
ui.section(
    "4. Price source eras",
    help_text="bhavcopy_legacy → 2019-09-27, then sec_bhavdata_full. "
              "The cutover is documented in P2.",
)

st.write(
    "NSE migrated from the old bhavcopy format to the new securities market bhavcopy "
    "format on 2019-09-30. The two formats differ in column names and floating-point "
    "precision. P2 normalised both into a single `ohlcv.parquet` with a `source` column."
)

if len(source_eras):
    st.dataframe(source_eras, use_container_width=True)
    fig_eras = charts.gantt(
        source_eras, start="start", end="end", label="source",
        title="Price source eras",
    )
    st.plotly_chart(fig_eras, use_container_width=True)
else:
    st.info("Source eras cache is empty.")
ui.source_note("data/dashboard/prices_source_eras.parquet ← data/prices/ohlcv.parquet[source]")

# =========================================================================== #
# Section 5 — Delivery availability                                            #
# =========================================================================== #
ui.section(
    "5. Delivery data availability",
    help_text="NaN before ~2020 — disclosed. Delivery fraction is a proxy for "
              "retail / informed-trading activity.",
)

st.write(
    "The `delivery_pct` feature (fraction of traded volume delivered vs settlement) "
    "is available from NSE only from around 2020 onwards. "
    "The panel is NaN for earlier dates — this is disclosed in P3 and visible in the "
    "NaN coverage heatmap on the Feature Panel page. "
    "The feature panel treats NaN delivery transparently and the backtester handles sparse features."
)

_del_path = data.DATA_DIR / "prices" / "delivery.parquet"
if _del_path.exists():
    try:
        del_head = pd.read_parquet(_del_path, columns=["date"])
        del_head["date"] = pd.to_datetime(del_head["date"])
        first_del = del_head["date"].min()
        last_del = del_head["date"].max()
        charts.kpi_row([
            ("First delivery date", str(first_del.date()), None),
            ("Last delivery date", str(last_del.date()), None),
            ("Delivery rows", f"{len(del_head):,}", None),
        ])
    except Exception as e:
        st.info(f"Could not read delivery.parquet header: {e}")
else:
    st.info(
        "`data/prices/delivery.parquet` not present — "
        "delivery data was introduced in P2 and may not exist on this clone."
    )
ui.source_note("data/prices/delivery.parquet (P2 deliverable)")

# =========================================================================== #
# Section 6 — VWAP sanity gauge                                                #
# =========================================================================== #
ui.section(
    "6. VWAP sanity check",
    help_text="% rows with low ≤ vwap ≤ high (target ~100%).  "
              "Failures indicate bhavcopy parsing errors.",
)

st.write(
    "VWAP (volume-weighted average price) must lie between the day's low and high "
    "by definition. Any violation is a parsing or rounding error in the source data. "
    "The gauge shows the fraction of rows passing this check across all years."
)

if len(vwap):
    overall_pct = float(vwap["n_in_range"].sum() / vwap["n_rows"].sum() * 100) \
        if vwap["n_rows"].sum() > 0 else 0.0
    fig_gauge = charts.gauge(
        value=overall_pct, maximum=100.0,
        label="VWAP in [low, high] (%)",
        thresholds={"bands": [
            (0, 90, charts.PALETTE["neg"]),
            (90, 99, charts.PALETTE["accent2"]),
            (99, 100, charts.PALETTE["pos"]),
        ]},
    )
    col_g, col_t = st.columns([1, 2])
    with col_g:
        st.plotly_chart(fig_gauge, use_container_width=True)
    with col_t:
        st.dataframe(vwap, use_container_width=True)
else:
    st.info("VWAP sanity cache is empty.")
ui.source_note("data/dashboard/prices_vwap_sanity.parquet ← data/prices/ohlcv.parquet")

# =========================================================================== #
# Section 7 — Quality board                                                    #
# =========================================================================== #
ui.section(
    "7. Data-quality board",
    help_text="Each check should be 0 — violations are shown as red pills.",
)

st.write(
    "Three fundamental data-quality checks on the adjusted price series. "
    "Any violation count above zero requires investigation before backtesting."
)

if len(quality):
    n_cols = min(len(quality), 5)
    cols = st.columns(n_cols)
    for i, (_, row) in enumerate(quality.iterrows()):
        viol = int(row["n_violations"])
        col = cols[i % n_cols]
        colour = "green" if viol == 0 else "red"
        col.markdown(
            f"**{row['check']}**  \n"
            f":{colour}[{'✅ 0' if viol == 0 else f'❌ {viol:,}'}]",
        )
    with st.expander("Quality detail"):
        st.dataframe(quality, use_container_width=True)
else:
    st.info("Quality cache is empty.")
ui.source_note("data/dashboard/prices_quality.parquet ← data/prices/ohlcv.parquet")

# =========================================================================== #
# Section 8 — yfinance cross-check                                             #
# =========================================================================== #
ui.section(
    "8. yfinance cross-check",
    help_text="Correlation histogram between our adjusted close and Yahoo Finance. "
              "Target > 0.99. Heavy build only — never hits the network on load.",
)

if yf_cross is not None and len(yf_cross):
    st.write(
        "The histogram shows per-symbol Pearson correlation between our adjusted close "
        "and Yahoo Finance's adjusted close for the same period. "
        "High correlation (> 0.99) confirms our CA adjustments match a well-known reference."
    )
    fig_yf = charts.hist(yf_cross["corr"], title="yfinance correlation (our close vs YF)",
                         bins=30, x_title="Pearson r")
    st.plotly_chart(fig_yf, use_container_width=True)
    pct_99 = float((yf_cross["corr"] >= 0.99).mean() * 100)
    charts.kpi_row([
        ("Symbols cross-checked", str(len(yf_cross)), None),
        ("% with r ≥ 0.99", f"{pct_99:.1f}%", None),
        ("Median r", f"{yf_cross['corr'].median():.4f}", None),
    ])
else:
    ui.pending_banner(
        what="yfinance cross-check",
        blocked_on="--heavy build (downloads from Yahoo Finance)",
    )
    st.caption(
        "To compute: `python dashboard/build_cache.py --heavy` — "
        "this hits the yfinance network and may take several minutes."
    )
ui.source_note(
    "data/dashboard/prices_yf_crosscheck.parquet (opt-in --heavy build, network)"
)

# =========================================================================== #
# Section 9 — Per-symbol candlestick (sliced read)                            #
# =========================================================================== #
ui.section(
    "9. Per-symbol price explorer",
    help_text="Sliced OHLCV read (one symbol at a time) + CA ex-date markers. "
              "Raw vs adjusted toggle.",
)

st.write(
    "Pick a symbol to view its full adjusted price history as a candlestick chart. "
    "Corporate-action ex-dates are marked with orange triangles. "
    "Toggle to see the raw (unadjusted) vs adjusted series."
)

# Collect available symbols from the universe membership
_syms: list[str] = []
try:
    mem_light = pd.read_parquet(
        data.DATA_DIR / "universe" / "membership.parquet",
        columns=["symbol"],
    )
    _syms = sorted(mem_light["symbol"].unique().tolist())
except Exception:
    pass

if not _syms:
    # Fallback: get symbols from the universe_intervals cache
    if len(intervals):
        _syms = sorted(intervals["symbol"].unique().tolist())

if not _syms:
    st.info("No symbol list available — universe membership not built yet.")
else:
    _sym_pick = st.selectbox("Symbol", _syms, key="prices_sym")
    _raw_toggle = st.checkbox("Show raw (unadjusted) close instead", value=False)

    if st.button("Load candlestick", key="prices_load_candle"):
        with st.spinner(f"Loading prices for {_sym_pick} …"):
            try:
                # SLICED READ — symbols=[sym] is always passed (contract)
                ohlcv_sym = data.load_ohlcv(symbols=[_sym_pick])
                if ohlcv_sym.empty:
                    st.warning(f"No price data found for {_sym_pick}.")
                else:
                    ohlcv_sym = ohlcv_sym.sort_values("date")
                    # CA markers
                    ca_markers = None
                    try:
                        ca_all = data.load_corporate_actions()
                        ca_markers = ca_all[ca_all["symbol"] == _sym_pick][["ex_date"]].rename(
                            columns={"ex_date": "date"}
                        )
                        ca_markers["date"] = pd.to_datetime(ca_markers["date"])
                    except Exception:
                        pass

                    if _raw_toggle and "close_raw" in ohlcv_sym.columns:
                        # swap close for close_raw (P2 may provide it)
                        ohlcv_sym = ohlcv_sym.copy()
                        ohlcv_sym["close"] = ohlcv_sym["close_raw"]

                    fig_candle = charts.candlestick(
                        ohlcv_sym,
                        title=f"{_sym_pick} — {'raw' if _raw_toggle else 'adjusted'} close",
                        markers=ca_markers,
                    )
                    st.plotly_chart(fig_candle, use_container_width=True)
                    charts.kpi_row([
                        ("Days in series", str(len(ohlcv_sym)), None),
                        ("First date", str(ohlcv_sym["date"].min().date()), None),
                        ("Last date", str(ohlcv_sym["date"].max().date()), None),
                    ])
            except ValueError as exc:
                # load_ohlcv raises ValueError when called without a filter —
                # this should never happen but we guard it for safety
                st.error(f"Filtered read error: {exc}")
            except FileNotFoundError:
                ui.data_missing(
                    "data/prices/ohlcv.parquet",
                    "python dashboard/build_cache.py",
                )
    else:
        st.caption("Click **Load candlestick** to fetch the price series for the selected symbol.")

ui.source_note(
    f"data/prices/ohlcv.parquet (sliced: symbols=[symbol]) · "
    "data/prices/corporate_actions.parquet"
)
