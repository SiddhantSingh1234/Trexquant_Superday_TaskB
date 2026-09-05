"""Phase 11 — BAD example (1) DATA: the universe source was structurally broken.

Reproducible from a seed and a single command:
    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/p11_bad_data.py

Beat 1 (naive result): rebuild the Phase-3 feature/label panel using the
SUPPLIED constituent file (`nifty200_2015-01-01_to_2026-09-01.csv`) as the
universe source instead of Phase 1's liquidity-reconstructed one, and run a
liquidity/turnover factor through it. It looks like a normal, healthy result:
a real formula, a real backtest, a real DSR/PBO/purge-embargo/lag-test pass.

Beat 2 (the system catches it): NOT via any statistical gate. External
reconciliation of the CSV's union of names against today's real 200-name
universe shows 80 names are simply absent, every one with zero
inclusion/exclusion events -- the signature of a change-log replayed onto an
incomplete base seed. DSR, PBO, purge/embargo, and the red-team lag test all
ran clean on this broken panel and none of them flagged it, because they
operate on TIME (does the edge survive a lag / a different sample window),
not on the CROSS-SECTION the universe defines.

Beat 3 (the fix): Phase 1 abandoned the supplied file for selection entirely
and rebuilds the universe from daily bhavcopy by trailing turnover -- already
built and in production (`reports/p1_universe_report.md`,
`data/universe/membership.parquet`).

Nothing here touches HOLDOUT: `gates.gate_b` is called with
`do_holdout_peek=False`, so only VAL_A statistics are exercised.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from src import backtester as bt
from src import gates as G
from src import loop as L
from src import panel as P
from src import redteam as RT
from src.config import RANDOM_SEED
from src.ledger import Ledger
from src.sectors import build_sector_map

np.random.seed(RANDOM_SEED)

OUT_DIR = REPO_ROOT / "artifacts" / "p11_bad_data"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SUPPLIED_CSV = REPO_ROOT / "nifty200_2015-01-01_to_2026-09-01.csv"


def log(msg: str) -> None:
    print(msg)


# --------------------------------------------------------------------------- #
# 1. Build the BROKEN membership panel from the supplied CSV (naive use: the  #
#    file AS SUPPLIED, forward-filled between its own snapshot dates -- the   #
#    obvious, superficially-reasonable thing to do with a "constituent file") #
# --------------------------------------------------------------------------- #
def build_broken_membership(ohlcv: pd.DataFrame) -> pd.DataFrame:
    csv = pd.read_csv(SUPPLIED_CSV)
    csv["effective_date"] = pd.to_datetime(csv["effective_date"]).dt.normalize()
    csv = csv.sort_values("effective_date").reset_index(drop=True)
    trading_days = pd.DatetimeIndex(sorted(ohlcv["date"].unique()))

    rows = []
    for i, row in csv.iterrows():
        start = row["effective_date"]
        end = csv["effective_date"].iloc[i + 1] if i + 1 < len(csv) else trading_days.max() + pd.Timedelta(days=1)
        syms = [s.strip() for s in str(row["symbols"]).split(",") if s.strip()]
        span = trading_days[(trading_days >= start) & (trading_days < end)]
        for d in span:
            for s in syms:
                rows.append((d, s))
    memb = pd.DataFrame(rows, columns=["date", "symbol"])
    memb["date"] = memb["date"].astype("datetime64[ns]")
    memb["in_universe"] = True
    memb = memb.drop_duplicates(["date", "symbol"]).sort_values(["date", "symbol"]).reset_index(drop=True)
    return memb


def build_broken_panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Mirrors src/panel.py `run()`'s exact recipe, with the CSV's membership
    substituted for Phase 1's real one. Returns (features, labels, membership)."""
    inp = P.load_inputs()
    ohlcv = inp["ohlcv"]
    membership = build_broken_membership(ohlcv)

    union = sorted(membership["symbol"].unique())
    log(f"[broken] CSV-derived union: {len(union)} symbols ever 'in universe'")

    wide = P.build_wide(ohlcv, union)
    idx, cols = wide["close"].index, wide["close"].columns
    memb_w = P.membership_wide(membership, idx, cols)

    feat_frames, mkt = P.compute_features(wide, memb_w)
    label_frames = P.compute_labels(wide["open"], memb_w)

    features = P.assemble_long(feat_frames)
    isin_last = (ohlcv.sort_values("date").groupby("symbol")["isin"].last()
                 if "isin" in ohlcv.columns else pd.Series(dtype=str))
    isin_map = {s: str(isin_last.get(s, "")) for s in union}
    sector_map, _ = build_sector_map(union, isin_map)

    features, _ = P.join_external(features, inp["delivery"], inp["size_proxy"], inp["is_real"])
    if features["size_proxy"].isna().all():
        turn63 = (wide["close_raw"] * wide["volume_raw"]).rolling(63, min_periods=63).median()
        sp_long = P._stack(np.log(turn63.replace(0.0, np.nan)), "size_proxy").reset_index()
        sp_long = P._to_ns(sp_long)
        features = features.drop(columns=["size_proxy"]).merge(sp_long, on=["date", "symbol"], how="left")

    features["sector"] = features["symbol"].map(sector_map).astype(str)
    features = P.mask_to_universe(features, membership)

    labels = P.assemble_long(label_frames)
    labels = P.mask_to_universe(labels, membership)

    from src.panel import FEATURE_COLS
    from src.contracts import HORIZONS
    features = features[["date", "symbol", *FEATURE_COLS, "size_proxy", "sector"]]
    label_order = ["date", "symbol"] + [f"fwd_ret_{h}" for h in HORIZONS] + \
        [f"fwd_ret_{h}_demeaned" for h in HORIZONS]
    labels = labels[label_order]
    for df in (features, labels):
        for c in df.columns:
            if c.startswith(("fwd_ret", "mom", "rev", "vol", "beta", "amihud",
                              "turnover", "dist", "max_ret", "delivery", "size_proxy")):
                df[c] = df[c].astype(np.float64)

    from src.contracts import validate_features, validate_labels
    validate_features(features)
    validate_labels(labels)
    log(f"[broken] validate_features / validate_labels PASS on the broken-universe panel "
        f"({len(features):,} feature rows, {len(labels):,} label rows)")
    return features, labels, membership


# --------------------------------------------------------------------------- #
# 2. External reconciliation -- the ONLY thing that catches it                #
# --------------------------------------------------------------------------- #
def reconcile_against_real_universe(broken_membership: pd.DataFrame) -> dict:
    real_membership_path = REPO_ROOT / "data" / "universe" / "membership.parquet"
    today_real = set()
    if real_membership_path.exists():
        real = pd.read_parquet(real_membership_path)
        real = real[real["in_universe"]]
        last_day = real["date"].max()
        today_real = set(real.loc[real["date"] == last_day, "symbol"])
    csv_union = set(broken_membership["symbol"].unique())
    missing = sorted(today_real - csv_union)

    csv = pd.read_csv(SUPPLIED_CSV)
    incl = set()
    excl = set()
    for v in csv["inclusions"].dropna():
        incl |= {s.strip() for s in str(v).split(",") if s.strip()}
    for v in csv["exclusions"].dropna():
        excl |= {s.strip() for s in str(v).split(",") if s.strip()}
    missing_with_events = [s for s in missing if s in incl or s in excl]

    return {
        "today_real_n": len(today_real),
        "csv_union_n": len(csv_union),
        "missing_from_csv_n": len(missing),
        "missing_sample": missing[:15],
        "missing_with_zero_events_n": len(missing) - len(missing_with_events),
        "missing_with_zero_events_pct": round(
            100 * (len(missing) - len(missing_with_events)) / len(missing), 1) if missing else None,
    }


# --------------------------------------------------------------------------- #
# 3. Run the factor through the panel: DSR / PBO / purge-embargo / lag test   #
# --------------------------------------------------------------------------- #
def main() -> None:
    log("=" * 78)
    log("BAD EXAMPLE 1 -- DATA: broken universe source")
    log("=" * 78)

    features, labels, membership = build_broken_panel()
    bt.use_panel(features, labels)

    price_panel = L.build_price_panel()
    formula = "mul(-1, ts_std(returns, 42))"  # low-volatility factor: strong, real
    #   signal on the CORRECT universe (VAL_A t~7.2) -- picked here specifically
    #   so it clears Gate B novelty on the BROKEN universe too, reaching the
    #   DSR/PBO computation this example needs to show "passing".
    sig = L.evaluate_signal(formula, price_panel)

    m_a = bt.backtest(sig, "val_a", horizon=5)
    m_b = bt.backtest(sig, "val_b", horizon=5)
    pre_sign = 1 if m_a["rank_ic"] >= 0 else -1
    log(f"\n[naive result] formula = {formula!r}")
    log(f"  VAL_A rank_ic={m_a['rank_ic']:.4f}  t_stat={m_a['t_stat']:.2f}  n_days={m_a['n_days']}")
    log(f"  VAL_B rank_ic={m_b['rank_ic']:.4f}  t_stat={m_b['t_stat']:.2f}  n_days={m_b['n_days']}")

    # -- DSR / PBO / novelty via Gate B statistics, HOLDOUT untouched ---------
    card = {
        "card_id": "diag_bad_data", "thesis_id": "th_bad_data",
        "thesis": {"horizon_days": 5}, "ast_canonical": formula,
        "formula": formula, "pre_registered": {"sign": pre_sign},
    }
    ledger = Ledger(":memory:")
    verdict, reasons, audit = G.gate_b(
        card, None, ledger, signal=sig, split="val_a",
        horizon=5, do_holdout_peek=False,
    )
    def _f(x):
        return f"{x:.4f}" if isinstance(x, (int, float)) else str(x)

    log(f"\n[Gate B statistics — HOLDOUT NOT touched (do_holdout_peek=False)]")
    log(f"  verdict={verdict}  reasons={reasons or '(none — clears novelty+stats)'}")
    log(f"  marginal_ic={_f(audit.get('marginal_ic'))}  deflated_sharpe={_f(audit.get('deflated_sharpe'))}"
        f"  (DSR_MIN={G.DSR_MIN})  t_stat={_f(audit.get('t_stat'))} (T_STAT_BAR={G.T_STAT_BAR})"
        f"  pbo={_f(audit.get('pbo'))} (PBO_MAX={G.PBO_MAX})")

    # -- purge/embargo: baked into EVERY _bt.backtest call above already ------
    log(f"\n[purge/embargo] applied inside every backtest call above "
        f"(embargo_days from config); no anomaly — it masks TRAIN/TEST overlap "
        f"in time, and this bug is cross-sectional, not temporal.")

    # -- red-team: the lag test (+ the other 4 always-run decisive tests) -----
    rt_report = RT.run_redteam(
        sig, tests=["extra_lag"], split="val_a", horizon=5, sign=pre_sign,
        formula=formula, prices=None, ledger=None,
    )
    log(f"\n[Red-team — decisive tests, forced regardless of selection]")
    log(f"  tests_run={rt_report['tests_run']}")
    log(f"  verdict={rt_report['verdict']}  failed_tests={rt_report['failed_tests']}")
    el = rt_report["results"]["extra_lag"]
    log(f"  extra_lag: base_rank_ic={el['base_rank_ic']:.4f} -> lagged={el['rank_ic_lagged']:.4f}"
        f"  t_lagged={el['t_stat_lagged']:.2f}  flag={el['flag']}")

    # -- reconciliation: the ONLY thing that catches it ------------------------
    recon = reconcile_against_real_universe(membership)
    log(f"\n[External reconciliation against today's real universe — THE catch]")
    log(f"  today's real universe: {recon['today_real_n']} names")
    log(f"  CSV-derived union: {recon['csv_union_n']} names")
    log(f"  missing from CSV entirely: {recon['missing_from_csv_n']} "
        f"({recon['missing_sample']} ...)")
    log(f"  of those, zero inclusion/exclusion events: {recon['missing_with_zero_events_n']} "
        f"({recon['missing_with_zero_events_pct']}%)")

    result = {
        "formula": formula,
        "val_a": {k: (float(m_a[k]) if isinstance(m_a[k], (int, float, np.floating)) else m_a[k])
                  for k in ("rank_ic", "t_stat", "n_days")},
        "val_b": {k: (float(m_b[k]) if isinstance(m_b[k], (int, float, np.floating)) else m_b[k])
                  for k in ("rank_ic", "t_stat", "n_days")},
        "gate_b_statistics": {
            "verdict": verdict, "reasons": reasons,
            "marginal_ic": audit.get("marginal_ic"),
            "deflated_sharpe": audit.get("deflated_sharpe"),
            "dsr_min": G.DSR_MIN, "t_stat": audit.get("t_stat"),
            "t_stat_bar": G.T_STAT_BAR, "pbo": audit.get("pbo"), "pbo_max": G.PBO_MAX,
            "holdout_touched": False,
        },
        "redteam_lag_test": {
            "verdict": rt_report["verdict"], "failed_tests": rt_report["failed_tests"],
            "extra_lag": el,
        },
        "reconciliation": recon,
        "fix": "Phase 1 abandoned the supplied CSV for selection; universe rebuilt "
               "from daily bhavcopy by trailing 63d turnover (reports/p1_universe_report.md).",
    }
    (OUT_DIR / "result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    log(f"\nWrote {OUT_DIR / 'result.json'}")


if __name__ == "__main__":
    main()
