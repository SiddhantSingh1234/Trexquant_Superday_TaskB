"""Phase 1 — Universe construction (liquidity-defined).

**Runs AFTER Phase 2.** Execution order is P0 -> P2 -> P1 -> P3.

The supplied index file `nifty200_2015-01-01_to_2026-09-01.csv` was verified
unusable as an index (80 of today's constituents never appear; 21/36 rebalances
internally inconsistent — it was a change-log replay onto a broken base seed).
So P1 no longer reads it for selection. Instead:

> **THE RULE.** On the last trading day of each month, using only data available
> that day:
>   1. Take every `SERIES == 'EQ'` stock present in that day's bhavcopy.
>   2. Require >= 252 trading days of prior history.
>   3. Rank by median daily turnover over the trailing 63 trading days.
>   4. The top 200 are the universe for the following month.

Survivorship-free by construction: selection uses only trailing information as of
date D, and a stock exits simply by ceasing to appear in the daily files.

Outputs
-------
* `data/universe/membership.parquet`   — daily long boolean panel (Section 0.5)
* `data/universe/universe_stats.parquet`— `date · n_members · median_turnover · turnover_cutoff_200`
* `data/universe/liquidity_ranks.parquet` — `month_end · symbol · liquidity_rank · trailing_turnover`
  (per-symbol monthly ranking; Phase 9's red-team `universe_edge` test reads it)
* `data/universe/symbols.json`          — union of every symbol ever selected + ISIN map
* `reports/p1_universe_report.md`
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    LIQUIDITY_RANKS_PARQUET,
    OHLCV_PARQUET,
    RANDOM_SEED,
    REPORTS_DIR,
    SYMBOLS_JSON,
    UNIVERSE_DIR,
    UNIVERSE_STATS_PARQUET,
)
from .contracts import make_fake_ohlcv, validate_membership, validate_ohlcv, validate_symbols_json

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
SUPPLIED_CSV: Path = REPO_ROOT / "nifty200_2015-01-01_to_2026-09-01.csv"
NSE_CURRENT_LIST: Path = REPO_ROOT / "data" / "raw" / "ind_nifty200list.csv"
P1_REPORT: Path = REPORTS_DIR / "p1_universe_report.md"

# THE RULE parameters.
TARGET_N = 200
HISTORY_MIN_DAYS = 252
TURNOVER_WINDOW = 63

# Fixture shape when P2 output is absent (must exceed TARGET_N symbols and carry
# enough history for the 252 + 63 warm-up).
_FIXTURE_DAYS = 2900
_FIXTURE_SYMBOLS = 260

# Whether the trade-to-trade 'BE' series is kept alongside 'EQ'. P2 keeps BE
# (see reports/p2_handoff.md §7.2) and P1 mirrors it: a stock demoted to BE is a
# distress signal, and if it was liquid enough to be in the top-200 the month
# before, dropping it exactly when it starts to fail is itself a survivorship
# filter. THE RULE's literal "SERIES == 'EQ'" is relaxed here for that reason.
KEEP_BE_SERIES = True

DECISIONS_LOG: list[str] = []


def _log(msg: str) -> None:
    DECISIONS_LOG.append(msg)


# --------------------------------------------------------------------------- #
# Load prices                                                                  #
# --------------------------------------------------------------------------- #
# P1 only needs these columns — reading the full 14-col panel wastes ~2x memory.
_NEEDED_COLS = ["date", "symbol", "isin", "close_raw", "volume_raw", "series"]


def load_prices() -> tuple[pd.DataFrame, str]:
    if OHLCV_PARQUET.exists():
        import pyarrow.parquet as pq
        have = set(pq.ParquetFile(OHLCV_PARQUET).schema.names)
        cols = [c for c in _NEEDED_COLS if c in have]
        df = pd.read_parquet(OHLCV_PARQUET, columns=cols)
        for c in ("close_raw", "volume_raw"):
            df[c] = df[c].astype(np.float64)
        src = f"data/prices/ohlcv.parquet ({len(df):,} rows)"
        _log(f"loaded P2 price panel: {src} — cols {cols} only (memory)")
        # P2 already ran validate_ohlcv on the full frame at write time; here we
        # only assert what P1 depends on, to avoid materialising all 14 columns.
        miss = [c for c in ("date", "symbol", "close_raw", "volume_raw") if c not in df]
        if miss:
            raise AssertionError(f"[p1] ohlcv.parquet missing columns P1 needs: {miss}")
        if df.duplicated(["date", "symbol"]).any():
            raise AssertionError("[p1] ohlcv.parquet has duplicate (date, symbol)")
    else:
        df = make_fake_ohlcv(
            n_days=_FIXTURE_DAYS, n_symbols=_FIXTURE_SYMBOLS, seed=RANDOM_SEED
        )
        src = (f"contracts.make_fake_ohlcv(n_days={_FIXTURE_DAYS}, "
               f"n_symbols={_FIXTURE_SYMBOLS}) — P2 output not present")
        _log(f"P2 price panel missing -> using fixture: {src}")
        validate_ohlcv(df)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize().astype("datetime64[ns]")
    return df, src


def filter_series(df: pd.DataFrame) -> pd.DataFrame:
    if "series" not in df.columns:
        _log("no 'series' column in price panel (fixture) — treating every row as "
             "SERIES=='EQ'")
        return df
    keep = {"EQ"} | ({"BE"} if KEEP_BE_SERIES else set())
    before = len(df)
    out = df[df["series"].str.upper().isin(keep)].drop(columns=["series"])
    _log(f"SERIES filter {sorted(keep)}: kept {len(out):,} / {before:,} rows")
    return out


# --------------------------------------------------------------------------- #
# THE RULE                                                                     #
# --------------------------------------------------------------------------- #
def _month_end_trading_days(dates: np.ndarray) -> list[pd.Timestamp]:
    s = pd.Series(pd.to_datetime(np.sort(np.unique(dates))))
    return list(s.groupby([s.dt.year, s.dt.month]).max())


def compute_selection(prices: pd.DataFrame, as_of: pd.Timestamp | None = None) -> dict:
    """Apply THE RULE. Returns per-month selections and stats.

    ``as_of`` truncates the panel to ``date <= as_of`` (used by the no-look-ahead
    test). Trailing windows and history counts are strictly per-symbol and
    ordered, so truncating the future never alters a past month's selection.
    """
    cols = [c for c in ("date", "symbol", "close_raw", "volume_raw") if c in prices]
    p = prices[cols]
    if as_of is not None:
        p = p[p["date"] <= pd.Timestamp(as_of)]
    p = p.sort_values(["symbol", "date"]).reset_index(drop=True)
    turnover = (p["close_raw"].to_numpy() * p["volume_raw"].to_numpy())
    p = p.drop(columns=["close_raw", "volume_raw"])
    p["turnover"] = turnover
    g = p.groupby("symbol", sort=False)
    p["tt63"] = g["turnover"].transform(
        lambda s: s.rolling(TURNOVER_WINDOW, min_periods=TURNOVER_WINDOW).median()
    )
    p["hist"] = g.cumcount() + 1
    p = p.drop(columns=["turnover"])

    month_ends = _month_end_trading_days(p["date"].to_numpy())
    selections: list[dict] = []
    for d in month_ends:
        day = p[p["date"] == d]
        cand = day[(day["hist"] >= HISTORY_MIN_DAYS) & day["tt63"].notna()]
        # deterministic tie-break: turnover desc, then symbol asc
        cand = cand.sort_values(["tt63", "symbol"], ascending=[False, True])
        top = cand.head(TARGET_N)
        picks = top["symbol"].tolist()
        picks_tt = [float(x) for x in top["tt63"].tolist()]   # parallel to picks, turnover-desc
        cutoff = float(top["tt63"].iloc[-1]) if len(top) >= TARGET_N else float("nan")
        selections.append({
            "month_end": pd.Timestamp(d),
            "symbols": picks,
            "turnover": picks_tt,
            "n_members": len(picks),
            "median_turnover": float(top["tt63"].median()) if picks else float("nan"),
            "turnover_cutoff_200": cutoff,
            "n_candidates": int(len(cand)),
        })
    return {"selections": selections, "all_dates": np.sort(p["date"].unique())}


# --------------------------------------------------------------------------- #
# Daily panel                                                                  #
# --------------------------------------------------------------------------- #
def build_membership(prices: pd.DataFrame, sel: dict) -> pd.DataFrame:
    selections = [s for s in sel["selections"] if s["n_members"] > 0]
    if not selections:
        raise RuntimeError("no month produced a non-empty selection — panel too short")

    all_dates = pd.DatetimeIndex(sel["all_dates"])
    # each month-end selection applies to the trading days AFTER it, until the
    # next month-end selection (the last one applies to everything after it).
    first_apply = all_dates[all_dates > selections[0]["month_end"]][0]
    panel_dates = all_dates[all_dates >= first_apply]

    bounds = [s["month_end"] for s in selections]
    # for each panel date, index of the most recent selection strictly before it
    pos = np.searchsorted(np.array(bounds, dtype="datetime64[ns]"),
                          panel_dates.to_numpy(), side="left") - 1
    pos = np.clip(pos, 0, len(selections) - 1)

    union = sorted({s for sel_ in selections for s in sel_["symbols"]})
    sym_ix = {s: j for j, s in enumerate(union)}
    mat = np.zeros((len(panel_dates), len(union)), dtype=bool)
    for k, sel_ in enumerate(selections):
        rows = np.where(pos == k)[0]
        cols = [sym_ix[s] for s in sel_["symbols"]]
        if len(rows) and cols:
            mat[np.ix_(rows, cols)] = True

    df = pd.DataFrame(mat, index=panel_dates, columns=union)
    out = (
        df.stack(future_stack=True)
        .rename_axis(["date", "symbol"])
        .rename("in_universe")
        .reset_index()
    )
    out["date"] = pd.to_datetime(out["date"]).dt.normalize().astype("datetime64[ns]")
    out["symbol"] = out["symbol"].astype(str)
    out["in_universe"] = out["in_universe"].astype(bool)
    _log(f"daily panel: {out['date'].nunique()} trading days "
         f"({panel_dates[0].date()}..{panel_dates[-1].date()}) x {len(union)} "
         f"ever-selected symbols; forward-filled from each monthly selection")
    _log("a stock that stops trading mid-month keeps in_universe==True until the "
         "next selection; it has no price rows so P3's join drops it")
    return out.sort_values(["date", "symbol"]).reset_index(drop=True)


def build_liquidity_ranks(sel: dict) -> pd.DataFrame:
    """Per-symbol trailing-liquidity ranking for every non-empty monthly selection.

    One row per (month_end, symbol) among that month's top-``TARGET_N`` picks.
    ``liquidity_rank`` is 1 for the most liquid name that month; the symbols are
    already sorted turnover-descending inside ``compute_selection``.  This is the
    exact ranking that produced ``universe_stats.parquet``'s
    ``turnover_cutoff_200`` — Phase 9's red-team reads it to identify the names
    ranked 150-200 that month (``universe_edge`` test) rather than recomputing.

    | column | type | notes |
    |---|---|---|
    | ``month_end`` | datetime64[ns] | the selection date the rank was fixed on |
    | ``symbol`` | string | uppercase, no ``.NS`` |
    | ``liquidity_rank`` | int64 | 1 = most liquid; max == that month's ``n_members`` |
    | ``trailing_turnover`` | float64 | trailing-63d median ``close_raw x volume_raw`` |
    """
    rows: list[dict] = []
    for s in sel["selections"]:
        if s["n_members"] == 0:
            continue
        for rank, (sym, tt) in enumerate(zip(s["symbols"], s["turnover"]), start=1):
            rows.append({
                "month_end": s["month_end"],
                "symbol": str(sym),
                "liquidity_rank": rank,
                "trailing_turnover": float(tt),
            })
    df = pd.DataFrame(rows, columns=["month_end", "symbol", "liquidity_rank",
                                     "trailing_turnover"])
    df["month_end"] = pd.to_datetime(df["month_end"]).dt.normalize().astype("datetime64[ns]")
    df["liquidity_rank"] = df["liquidity_rank"].astype("int64")
    df["trailing_turnover"] = df["trailing_turnover"].astype("float64")
    return df.sort_values(["month_end", "liquidity_rank"]).reset_index(drop=True)


def build_universe_stats(sel: dict) -> pd.DataFrame:
    rows = [{
        "date": s["month_end"],
        "n_members": s["n_members"],
        "median_turnover": s["median_turnover"],
        "turnover_cutoff_200": s["turnover_cutoff_200"],
    } for s in sel["selections"]]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize().astype("datetime64[ns]")
    return df.sort_values("date").reset_index(drop=True)


def build_symbols_json(prices: pd.DataFrame, membership: pd.DataFrame) -> dict:
    union = sorted(membership.loc[membership["in_universe"], "symbol"].unique())
    last_isin = (
        prices.sort_values("date")
        .groupby("symbol")["isin"].last()
    )
    isin_map = {s: str(last_isin.get(s, "")) for s in union}
    return {
        "symbols": union,
        "n": len(union),
        "renames": {},          # ISIN is the stable key now — see isin_map
        "isin_map": isin_map,
        "selection_rule": (
            f"top-{TARGET_N} by trailing {TURNOVER_WINDOW}-day median turnover, "
            f">= {HISTORY_MIN_DAYS} days history, monthly, from NSE bhavcopy"
        ),
    }


# --------------------------------------------------------------------------- #
# Diagnostics                                                                  #
# --------------------------------------------------------------------------- #
def _supplied_csv_union() -> set[str] | None:
    if not SUPPLIED_CSV.exists():
        return None
    df = pd.read_csv(SUPPLIED_CSV)
    u: set[str] = set()
    for cell in df["symbols"].dropna():
        u |= {t.strip().upper().replace("& ", "&").replace(" &", "&")
              for t in cell.split(",") if t.strip()}
    return u


def _nse_current_union() -> set[str] | None:
    if not NSE_CURRENT_LIST.exists():
        return None
    df = pd.read_csv(NSE_CURRENT_LIST)
    col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
    return set(df[col].str.strip().str.upper()) if col else None


def overlap_diagnostic(membership: pd.DataFrame) -> dict:
    our_union = set(membership.loc[membership["in_universe"], "symbol"].unique())
    latest_day = membership["date"].max()
    our_current = set(
        membership.loc[(membership["date"] == latest_day) & membership["in_universe"],
                       "symbol"]
    )
    out = {"our_union_n": len(our_union), "our_current_n": len(our_current)}

    csv_u = _supplied_csv_union()
    if csv_u is not None:
        out["supplied_csv"] = {
            "n": len(csv_u),
            "in_both_union": len(our_union & csv_u),
            "pct_of_csv_covered": round(100 * len(our_union & csv_u) / len(csv_u), 1),
            "only_in_csv_sample": sorted(csv_u - our_union)[:15],
            "only_in_ours_sample": sorted(our_union - csv_u)[:15],
        }
    else:
        out["supplied_csv"] = None

    nse_u = _nse_current_union()
    if nse_u is not None:
        out["nse_current_list"] = {
            "n": len(nse_u),
            "overlap_with_our_current": len(our_current & nse_u),
            "pct": round(100 * len(our_current & nse_u) / len(nse_u), 1),
        }
    else:
        out["nse_current_list"] = "not available (NSE publishes only the current list; file absent)"
    return out


def monthly_turnover_rate(sel: dict) -> dict:
    sels = [s for s in sel["selections"] if s["n_members"] > 0]
    rates = []
    for a, b in zip(sels[:-1], sels[1:]):
        sa, sb = set(a["symbols"]), set(b["symbols"])
        churn = len(sb - sa)
        rates.append(churn / max(len(sb), 1))
    arr = np.array(rates) if rates else np.array([np.nan])
    return {"mean_pct": round(100 * float(np.nanmean(arr)), 2),
            "min_pct": round(100 * float(np.nanmin(arr)), 2),
            "max_pct": round(100 * float(np.nanmax(arr)), 2)}


def lookahead_check(prices: pd.DataFrame, full_sel: dict,
                    as_of: str = "2020-01-01") -> dict:
    """TEST C — truncating the future must not change any past month's selection."""
    cut = pd.Timestamp(as_of)
    trunc = compute_selection(prices, as_of=cut)
    tmap = {s["month_end"]: s for s in trunc["selections"]}
    mismatches = []
    compared = 0
    for s in full_sel["selections"]:
        d = s["month_end"]
        if d >= cut or d not in tmap:
            continue
        compared += 1
        t = tmap[d]
        if (s["symbols"] != t["symbols"]
                or not np.allclose(s["turnover_cutoff_200"], t["turnover_cutoff_200"],
                                   equal_nan=True)):
            mismatches.append(d.date().isoformat())
    return {"as_of": as_of, "months_compared": compared,
            "bit_identical": not mismatches, "mismatches": mismatches}


# --------------------------------------------------------------------------- #
# Report                                                                       #
# --------------------------------------------------------------------------- #
CANARIES = ("DHFL", "RCOM", "JPASSOCIAT", "YESBANK", "SUZLON", "IDEA")
HEAVYWEIGHTS = ("RELIANCE", "TCS", "SBIN", "TATASTEEL", "MARUTI", "ONGC")


def _canary_report(membership: pd.DataFrame) -> list[dict]:
    rows = []
    piv = membership[membership["in_universe"]].groupby("date")["symbol"].agg(set)
    for c in CANARIES:
        days = membership.loc[(membership["symbol"] == c) & membership["in_universe"], "date"]
        rows.append({
            "symbol": c,
            "in_union": bool(len(days)),
            "first_in": days.min().date().isoformat() if len(days) else None,
            "last_in": days.max().date().isoformat() if len(days) else None,
        })
    return rows


def _heavyweight_report(membership: pd.DataFrame) -> list[dict]:
    out = []
    n_days = membership["date"].nunique()
    for h in HEAVYWEIGHTS:
        d = membership.loc[(membership["symbol"] == h) & membership["in_universe"], "date"]
        out.append({"symbol": h, "days_in_universe": int(d.nunique()),
                    "pct_of_history": round(100 * d.nunique() / n_days, 1)})
    return out


def write_report(*, price_src, sel, membership, stats, overlap, churn, la, sym_json) -> str:
    L: list[str] = []
    A = L.append
    A("# Phase 1 — Universe construction (liquidity-defined)\n")
    A("## 0. Naming — use this wording everywhere\n")
    A("> **\"The 200 most liquid Indian equities, reconstructed point-in-time from "
      "NSE daily bhavcopy.\"**\n")
    A("**Not \"NIFTY 200.\"** The index label was never load-bearing for a "
      "cross-sectional ranking exercise; a coherent, survivorship-free, "
      "point-in-time universe reproducible from primary source is the stronger claim.\n")
    A("## 1. Why the supplied index file is not used for selection\n")
    A("`nifty200_2015-01-01_to_2026-09-01.csv` was verified unusable as an index:\n")
    A("- **80 of today's 200 NIFTY 200 constituents never appear in it** — "
      "RELIANCE, TCS, SBIN, MARUTI, TATASTEEL, TATAMOTORS, SUNPHARMA, TITAN, "
      "ULTRACEMCO, ONGC among them.")
    A("- **All 80 have zero inclusion/exclusion events** — the signature of a "
      "change-log replayed onto an incomplete base seed. Permanent heavyweights "
      "were never added; each row was padded back to 200 with mid-caps.")
    A("- **21 of 36 rebalances are internally inconsistent** (declared "
      "inclusions/exclusions do not reconcile against the `symbols` deltas).")
    A("- Replay cannot repair it: forward replay needs a correct 2015 base "
      "(ours is broken); backward replay needs a complete change log (ours is "
      "21/36 inconsistent). NSE publishes only the current list.\n")
    A("The file is read here **only** for the §5 overlap diagnostic — never for selection.\n")
    A("## 2. THE RULE (what we do instead)\n")
    A(f"On the **last trading day of each month**, using only data available that day:\n")
    A(f"1. Take every `SERIES == 'EQ'` stock present in that day's bhavcopy "
      f"(`BE` kept as well: **{KEEP_BE_SERIES}**).")
    A(f"2. Require **>= {HISTORY_MIN_DAYS} trading days** of prior history.")
    A(f"3. Rank by **median daily turnover (`close_raw x volume_raw`) over the "
      f"trailing {TURNOVER_WINDOW} trading days** — trailing only, never centred.")
    A(f"4. The **top {TARGET_N}** are the universe for the following month, "
      f"forward-filled to daily.\n")
    A("Survivorship-free by construction: selection uses only trailing "
      "information as of date *D*; a stock exits automatically when it stops "
      "appearing in the daily files — no delisting-date list, no judgement call.\n")
    A("## 3. Inputs actually used\n")
    A(f"- Price panel: `{price_src}`")
    if OHLCV_PARQUET.exists():
        A("  (real P2 output)")
    else:
        A("  ⚠️ **P2 has not run.** This run is against the synthetic fixture — "
          "structural logic only. Canary / flat-coverage / heavyweight criteria "
          "cannot be verified until P2 produces `data/prices/ohlcv.parquet`; "
          "re-run P1 then.")
    A("")
    A("## 4. Monthly selection results\n")
    n_full = sum(1 for s in sel["selections"] if s["n_members"] == TARGET_N)
    n_short = [s for s in sel["selections"] if 0 < s["n_members"] < TARGET_N]
    A(f"- Month-end selections: **{len(sel['selections'])}**")
    A(f"- Months at exactly {TARGET_N} members: **{n_full}**")
    if n_short:
        A(f"- Months below {TARGET_N} (252-day history not yet satisfied for enough "
          f"names): **{len(n_short)}** — "
          + ", ".join(f"{s['month_end'].date()} (n={s['n_members']})" for s in n_short[:12])
          + (" ..." if len(n_short) > 12 else ""))
    A(f"- Monthly membership turnover: mean **{churn['mean_pct']}%**, "
      f"range {churn['min_pct']}–{churn['max_pct']}% (expected ~2–5%)")
    A(f"- Union of every symbol ever selected: **{sym_json['n']}**\n")
    A("### universe_stats.parquet (head + tail)\n")
    A("| date | n_members | median_turnover | turnover_cutoff_200 |")
    A("|---|---|---|---|")
    show = pd.concat([stats.head(6), stats.tail(6)])
    for _, r in show.iterrows():
        A(f"| {r['date'].date()} | {int(r['n_members'])} | "
          f"{r['median_turnover']:.3e} | "
          f"{'nan' if pd.isna(r['turnover_cutoff_200']) else format(r['turnover_cutoff_200'], '.3e')} |")
    A("\nThe rank-200 turnover cutoff is the liquidity floor; it should drift "
      "upward over the sample.\n")
    A("### liquidity_ranks.parquet\n")
    A(f"Per-symbol trailing-turnover ranking, one row per (month_end, symbol) "
      f"among each month's top-{TARGET_N} picks (`month_end · symbol · "
      f"liquidity_rank · trailing_turnover`; rank 1 = most liquid). This is the "
      f"same ranking that fixes `turnover_cutoff_200` above; **Phase 9's "
      f"red-team reads it** to identify the names ranked 150–200 that month "
      f"(`universe_edge` test) instead of recomputing.\n")
    A("## 5. Index-overlap diagnostic (context only — never a selection input)\n")
    o = overlap
    A(f"- Our union: {o['our_union_n']} symbols; our current-day universe: {o['our_current_n']}.")
    if o["supplied_csv"]:
        s = o["supplied_csv"]
        A(f"- Supplied CSV union: {s['n']}. In both: {s['in_both_union']} "
          f"(**{s['pct_of_csv_covered']}%** of the CSV's names).")
        A(f"  - sample only in CSV: {s['only_in_csv_sample']}")
        A(f"  - sample only in ours: {s['only_in_ours_sample']}")
    if isinstance(o["nse_current_list"], str):
        A(f"- NSE current `ind_nifty200list.csv`: {o['nse_current_list']}")
    else:
        n = o["nse_current_list"]
        A(f"- NSE current list: {n['n']} names; overlap with our current universe "
          f"{n['overlap_with_our_current']} (**{n['pct']}%**).")
    A("")
    A("## 6. Acceptance checks\n")
    A("### TEST A — survivorship canaries\n")
    A("| symbol | in union | first in | last in |")
    A("|---|---|---|---|")
    for r in _canary_report(membership):
        A(f"| {r['symbol']} | {r['in_union']} | {r['first_in']} | {r['last_in']} |")
    if not OHLCV_PARQUET.exists():
        A("\n⚠️ Fixture has no real DHFL/RCOM/... — this table is empty by "
          "construction. Verify against real P2 data.\n")
    A("### TEST B — flat coverage\n")
    piv = membership[membership["in_universe"]].groupby("date")["symbol"].count()
    yrs = piv.groupby(piv.index.year).mean().round(1)
    A("Mean `n_members` per year: " + ", ".join(f"{y}: {v}" for y, v in yrs.items()))
    x = np.arange(len(piv)); slope = float(np.polyfit(x, piv.to_numpy(), 1)[0])
    A(f"\nLinear trend slope: **{slope:.4e}** members/day "
      f"({slope*252:.3f}/year). Near-zero => no survivorship slope.")
    if not OHLCV_PARQUET.exists():
        A("(fixture: flat by construction once history warm-up passes; the real "
          "test is on P2 data.)")
    A("\n### TEST C — no look-ahead in selection\n")
    A(f"- Recomputed with data only up to **{la['as_of']}**; compared "
      f"**{la['months_compared']}** prior month-ends.")
    A(f"- Bit-identical: **{la['bit_identical']}**"
      + ("" if la["bit_identical"] else f" — mismatches: {la['mismatches']}"))
    A("\n### Heavyweights present\n")
    A("| symbol | days in universe | % of history |")
    A("|---|---|---|")
    for r in _heavyweight_report(membership):
        A(f"| {r['symbol']} | {r['days_in_universe']} | {r['pct_of_history']} |")
    if not OHLCV_PARQUET.exists():
        A("\n⚠️ Not in the fixture. Verify against real P2 data.\n")
    A("## 7. Decision log\n")
    for d in DECISIONS_LOG:
        A(f"- {d}")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #
def run(write: bool = True) -> dict:
    DECISIONS_LOG.clear()
    prices, price_src = load_prices()
    prices = filter_series(prices)

    sel = compute_selection(prices)
    membership = build_membership(prices, sel)
    validate_membership(membership)
    stats = build_universe_stats(sel)
    ranks = build_liquidity_ranks(sel)
    # keep the ranking consistent with the daily panel: the final month-end
    # selection is never "in force" if no trading day follows it (P1 §7.7), so
    # its brand-new picks never enter membership — drop them here too.
    member_syms = set(membership.loc[membership["in_universe"], "symbol"])
    dropped = sorted(set(ranks["symbol"]) - member_syms)
    ranks = ranks[ranks["symbol"].isin(member_syms)].reset_index(drop=True)
    _log(f"liquidity_ranks.parquet: {len(ranks):,} rows "
         f"({ranks['month_end'].nunique()} months x up to {TARGET_N} names), "
         f"per-symbol trailing-turnover rank read by P9 universe_edge"
         + (f"; dropped {len(dropped)} name(s) only in the unapplied final "
            f"selection: {dropped[:8]}" if dropped else ""))
    sym_json = build_symbols_json(prices, membership)
    validate_symbols_json(sym_json)

    overlap = overlap_diagnostic(membership)
    churn = monthly_turnover_rate(sel)
    la = lookahead_check(prices, sel)
    report = write_report(price_src=price_src, sel=sel, membership=membership,
                          stats=stats, overlap=overlap, churn=churn, la=la,
                          sym_json=sym_json)

    if write:
        UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        membership.to_parquet(UNIVERSE_DIR / "membership.parquet", index=False)
        stats.to_parquet(UNIVERSE_STATS_PARQUET, index=False)
        ranks.to_parquet(LIQUIDITY_RANKS_PARQUET, index=False)
        SYMBOLS_JSON.write_text(json.dumps(sym_json, indent=2), encoding="utf-8")
        P1_REPORT.write_text(report, encoding="utf-8")

    return {"prices": prices, "selection": sel, "membership": membership,
            "stats": stats, "ranks": ranks, "symbols": sym_json, "overlap": overlap,
            "churn": churn, "lookahead": la, "report": report,
            "price_src": price_src}


if __name__ == "__main__":
    r = run(write=True)
    m = r["membership"]
    print(f"membership.parquet : {len(m):,} rows, {m['symbol'].nunique()} symbols, "
          f"{m['date'].nunique()} trading days")
    print(f"universe_stats     : {len(r['stats'])} monthly rows")
    print(f"liquidity_ranks    : {len(r['ranks']):,} rows "
          f"({r['ranks']['month_end'].nunique()} months)")
    print(f"symbols.json       : n={r['symbols']['n']}")
    print(f"monthly turnover   : mean {r['churn']['mean_pct']}%")
    print(f"look-ahead check   : bit_identical={r['lookahead']['bit_identical']} "
          f"({r['lookahead']['months_compared']} months)")
    print(f"price source       : {r['price_src']}")
