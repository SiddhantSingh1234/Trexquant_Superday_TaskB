"""Phase 1 (liquidity-defined universe) acceptance tests — plain pytest, no network.

P2 has not run, so these exercise the *selection logic* against the synthetic
fixture. Criteria that need real delisted names (canaries, heavyweights,
real flat-coverage) are checked structurally here and must be re-verified once
`data/prices/ohlcv.parquet` exists — see reports/p1_universe_report.md §3/§6.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.config import OHLCV_PARQUET
from src.contracts import validate_membership, validate_symbols_json
from src.universe import (
    HISTORY_MIN_DAYS,
    TARGET_N,
    TURNOVER_WINDOW,
    compute_selection,
    run,
)


@pytest.fixture(scope="module")
def res():
    return run(write=False)


def test_membership_validates(res):
    validate_membership(res["membership"])
    assert res["membership"]["date"].dtype == "datetime64[ns]"


def test_symbols_json_validates(res):
    validate_symbols_json(res["symbols"])
    assert res["symbols"]["isin_map"]
    assert set(res["symbols"]["isin_map"]) == set(res["symbols"]["symbols"])


def test_every_selection_is_200_or_documented_short(res):
    for s in res["selection"]["selections"]:
        n = s["n_members"]
        assert n == TARGET_N or n == 0, (
            f"{s['month_end'].date()}: n_members={n} — only 0 (warm-up) or "
            f"{TARGET_N} expected on the fixture"
        )
    assert any(s["n_members"] == TARGET_N for s in res["selection"]["selections"])


def test_daily_panel_is_flat_at_200(res):
    m = res["membership"]
    per_day = m[m["in_universe"]].groupby("date")["symbol"].count()
    assert per_day.min() == TARGET_N and per_day.max() == TARGET_N
    x = np.arange(len(per_day))
    slope = np.polyfit(x, per_day.to_numpy(), 1)[0]
    assert abs(slope) < 1e-6, f"coverage slope {slope:.2e} — expected ~0"


def test_no_lookahead_bit_identical(res):
    la = res["lookahead"]
    assert la["months_compared"] >= 12
    assert la["bit_identical"], f"look-ahead mismatches: {la['mismatches']}"


def test_lookahead_holds_at_a_second_cut(res):
    """Truncating at a different date must also leave earlier months unchanged."""
    from src.universe import lookahead_check
    la = lookahead_check(res["prices"], res["selection"], as_of="2022-06-30")
    assert la["bit_identical"], la["mismatches"]


def test_monthly_turnover_is_plausible(res):
    c = res["churn"]
    assert 0.5 <= c["mean_pct"] <= 15.0, c


def test_selection_ranks_by_trailing_turnover(res):
    """Higher trailing 63d median turnover => selected before lower."""
    sel = res["selection"]["selections"]
    picked = next(s for s in sel if s["n_members"] == TARGET_N)
    d = picked["month_end"]
    p = res["prices"]
    present_on_d = set(p.loc[p["date"] == d, "symbol"])          # in bhavcopy on D
    p = p[p["date"] <= d].sort_values(["symbol", "date"])
    p["to"] = p["close_raw"] * p["volume_raw"]
    tt = (p.groupby("symbol")["to"]
          .apply(lambda s: s.tail(TURNOVER_WINDOW).median()
                 if len(s) >= HISTORY_MIN_DAYS else np.nan)
          .dropna())
    tt = tt[tt.index.isin(present_on_d)]
    chosen = tt[tt.index.isin(picked["symbols"])]
    rejected = tt[~tt.index.isin(picked["symbols"])]
    if len(rejected):
        assert chosen.min() >= rejected.max() - 1e-6


def test_stock_that_stops_trading_leaves_universe(res):
    """A symbol whose price rows end mid-sample is eventually out of the panel."""
    p = res["prices"]
    last_price_day = p.groupby("symbol")["date"].max()
    panel_end = res["membership"]["date"].max()
    stoppers = last_price_day[last_price_day < panel_end - pd.Timedelta(days=90)].index
    m = res["membership"]
    checked = 0
    for sym in stoppers:
        rows = m[(m["symbol"] == sym)]
        if not rows["in_universe"].any():
            continue
        checked += 1
        last_in = rows.loc[rows["in_universe"], "date"].max()
        # out for good after ~2 monthly selections past its last trade
        assert last_in <= last_price_day[sym] + pd.Timedelta(days=75)
    assert checked >= 1, "fixture produced no delisting-like symbols to test"


def test_deterministic(res):
    """Recomputing the selection from the same in-memory panel is bit-identical.

    (Uses ``res['prices']`` rather than a second full ``run()`` — reloading and
    re-transforming the ~5M-row real panel a second time inside one pytest
    process exhausts memory on small machines; the determinism claim is about
    the algorithm, which this exercises fully.)"""
    from src.universe import build_membership, compute_selection

    sel2 = compute_selection(res["prices"])
    mem2 = build_membership(res["prices"], sel2)
    assert res["membership"].equals(mem2)


def test_supplied_csv_not_used_for_selection(res, monkeypatch, tmp_path):
    """Selection must not depend on the supplied CSV in any way.

    The CSV is only touched by ``_supplied_csv_union`` (the §5 overlap
    diagnostic). Point the module at a non-existent path, recompute the
    selection + membership from the same prices, and assert it is bit-identical
    to the real run. (The earlier `overlap < 10` check was a fixture-only proxy —
    with real P2 prices our liquidity universe *should* overlap the nominal
    NIFTY 200 heavily, which is the correct outcome.)"""
    import src.universe as U

    monkeypatch.setattr(U, "SUPPLIED_CSV", tmp_path / "does_not_exist.csv")
    monkeypatch.setattr(U, "NSE_CURRENT_LIST", tmp_path / "also_missing.csv")
    assert U._supplied_csv_union() is None          # really unavailable now

    sel = U.compute_selection(res["prices"])
    mem = U.build_membership(res["prices"], sel)
    assert mem.equals(res["membership"]), (
        "recomputed membership differs with the CSV removed — it is leaking "
        "into the universe construction"
    )


def test_universe_stats_has_cutoff(res):
    s = res["stats"]
    assert {"date", "n_members", "median_turnover", "turnover_cutoff_200"} <= set(s.columns)
    live = s[s["n_members"] == TARGET_N]
    assert live["turnover_cutoff_200"].notna().all()
    assert (live["median_turnover"] >= live["turnover_cutoff_200"]).all()


def test_liquidity_ranks_emitted(res):
    """Per-symbol monthly trailing-liquidity ranking (read by P9's universe_edge)."""
    r = res["ranks"]
    assert list(r.columns) == ["month_end", "symbol", "liquidity_rank", "trailing_turnover"]
    assert pd.api.types.is_datetime64_ns_dtype(r["month_end"])
    assert r["liquidity_rank"].dtype == "int64"
    assert not r.duplicated(["month_end", "symbol"]).any()

    live_months = {s["month_end"] for s in res["selection"]["selections"]
                   if s["n_members"] > 0}
    # every ranked month is a live selection; at most the final selection can be
    # absent (never in force — no trading day follows it, P1 §7.7)
    assert set(r["month_end"]) <= live_months
    assert 0 <= len(live_months) - r["month_end"].nunique() <= 1

    sel_by_month = {s["month_end"]: s for s in res["selection"]["selections"]}
    last_month = max(r["month_end"])
    for me, g in r.groupby("month_end"):
        g = g.sort_values("liquidity_rank")
        # rank orders by DESCENDING trailing turnover; rank 1 = most liquid
        assert g["trailing_turnover"].is_monotonic_decreasing
        assert g["liquidity_rank"].is_monotonic_increasing
        assert g["liquidity_rank"].iloc[0] == 1
        assert set(g["symbol"]) <= set(sel_by_month[me]["symbols"])
        # ranks are contiguous 1..n except the final month-end selection, which
        # is never in force so its fresh-listing names are dropped (leaving gaps)
        if me != last_month:
            assert list(g["liquidity_rank"]) == list(range(1, len(g) + 1))

    # every ranked name is a real universe member (post the final-month drop)
    members = set(res["membership"].loc[res["membership"]["in_universe"], "symbol"])
    assert set(r["symbol"]) <= members

    # the rank-200 turnover matches universe_stats' turnover_cutoff_200
    stats = res["stats"].set_index("date")["turnover_cutoff_200"]
    full = r[r["liquidity_rank"] == TARGET_N]
    for me, tt in full.set_index("month_end")["trailing_turnover"].items():
        if me in stats.index and pd.notna(stats[me]):
            assert abs(tt - stats[me]) < 1e-6
