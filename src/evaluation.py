"""Phase 12 - grading the factory, not the signal.

This module answers two questions with numbers, never assertions:

1. **Gate value** (the ablation).  A seeded pool of ~40 synthetic factors with
   *known* ground truth (genuinely predictive / pure noise / overfit-to-a-
   subsample / leaky-look-ahead) is scored with each gate on and off.  Per gate
   we report a **catch rate** (junk correctly rejected), a **false-kill rate**
   (good factors wrongly rejected), and the run's **FDR with that gate removed**
   vs the full pipeline.  The pool needs no LLM calls (Gate A - the Economics
   Reviewer - is out of scope here on purpose: PRE_BUILD_TASKS.md T3's ~20
   theses/day ceiling means an LLM-hungry ablation could never be re-run) so it
   is built entirely from ``src/contracts.py`` fixtures plus hand-planted
   distortions, and scored with the real ``src/gates.py`` and ``src/redteam.py``
   primitives against a *dedicated*, throw-away ``Ledger`` -- nothing here
   touches ``data/ledger.db`` or real project data.

2. **Real vs fake learning.**  A published critique of factor-mining agents is
   that their error *types* mature across generations while total error
   *volume* stays flat.  We report what the **real** system's ledger shows
   (every recorded thesis is generation 0 -- the LLM budget ceiling has never
   let a real run reach a second generation, so real multi-generation learning
   is simply *unmeasured*, not confirmed or refuted) and, separately, what a
   synthetic proxy loop over the seeded pool shows (a random partition of a
   fixed pool into four batches -- by construction it cannot exhibit genuine
   learning, and is reported as exactly that: a proxy, not evidence).

Everything downstream of :func:`run_evaluation` is read-only over the rest of
the project; the only writes are the ablation ledger (``data/eval/*.db``,
throw-away) and the report artifacts under ``reports/``.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import backtester as _bt  # noqa: E402
from . import contracts  # noqa: E402
from . import gates as gt  # noqa: E402
from . import redteam as rt  # noqa: E402
from .config import REPO_ROOT, RANDOM_SEED, T_STAT_BAR  # noqa: E402
from .ledger import Ledger  # noqa: E402

# --------------------------------------------------------------------------- #
# Pool construction parameters (documented judgement calls -- see             #
# reports/p12_handoff.md S7)                                                  #
# --------------------------------------------------------------------------- #
N_DAYS = 1750           # -> 2015-01-01 .. 2021-09-15, comfortably spans val_a
N_SYMBOLS = 50
N_PER_CATEGORY = 10
CATEGORIES = ("genuine", "noise", "overfit", "leaky")
OVERFIT_N_CANDIDATES = 100
SCORE_SPLIT = "val_a"
SCORE_HORIZON = 1
N_GENERATIONS = 4
LATENT_AR1_RHO = 0.92   # day-to-day persistence of the planted latent (momentum-like)
TRUE_IC = 0.06          # target mean daily RankIC of a "genuine" factor vs fwd_ret_1

ABLATION_LEDGER_DB = REPO_ROOT / "data" / "eval" / "p12_ablation_ledger.db"
PLOTS_DIR = REPO_ROOT / "reports" / "p12_plots"
REAL_LEDGER_DB = REPO_ROOT / "data" / "ledger.db"
REAL_CARDS_DIR = REPO_ROOT / "artifacts" / "cards"


# =========================================================================== #
# 1. Synthetic world + seeded pool                                            #
# =========================================================================== #
@dataclass
class World:
    features: pd.DataFrame
    labels: pd.DataFrame
    latent_wide: pd.DataFrame     # date x symbol, z-scored -- mom_21, the planted latent
    fwd1_wide: pd.DataFrame       # date x symbol -- fwd_ret_1_demeaned, the scoring label
    dates: pd.DatetimeIndex
    symbols: list[str]


def _long_frame(frame: pd.DataFrame, value_name: str) -> pd.DataFrame:
    return (
        frame.stack(future_stack=True).rename_axis(["date", "symbol"])
        .rename(value_name).reset_index()
    )


def _finalize_long(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize().astype("datetime64[ns]")
    df["symbol"] = df["symbol"].astype(str)
    return df.sort_values(["date", "symbol"]).reset_index(drop=True)


def build_world(seed: int = RANDOM_SEED) -> World:
    """A hand-built, schema-compliant panel with a **persistent** (AR(1),
    ``rho=LATENT_AR1_RHO``) planted latent -- built from scratch here rather
    than reused from ``contracts.make_fake_features``/``make_fake_labels``.

    Those fixtures' planted latent is redrawn i.i.d. every day (see
    ``contracts._planted_latent``): fine for testing that a signal *at* day
    *t* predicts the return at *t*, but it makes a correctly-timed causal
    factor and a one-day-look-ahead leak collapse identically under the
    red-team's ``extra_lag`` test (both would show zero correlation once
    shifted a day, since nothing in that world persists day to day). A real
    momentum-style factor is autocorrelated across days, so it should *decay*
    gracefully under an extra lag, not vanish -- and only that gives the
    ablation a fair test of whether Gate C's causality check earns its keep
    against a genuine leak. Hence the local AR(1) latent.
    """
    rng = np.random.default_rng(seed)
    # cast to datetime64[ns] explicitly -- pandas/numpy now default
    # `bdate_range` to [us] resolution, which silently mismatches every [ns]
    # frame this project's contracts (Section 0.5) require.
    dates = pd.DatetimeIndex(
        pd.bdate_range(start="2015-01-01", periods=N_DAYS).normalize()
    ).as_unit("ns")
    symbols = [f"E{i:03d}" for i in range(N_SYMBOLS)]
    shape = (N_DAYS, N_SYMBOLS)

    innov = rng.standard_normal(shape)
    latent = np.empty(shape)
    latent[0] = innov[0]
    rho = LATENT_AR1_RHO
    for t in range(1, N_DAYS):
        latent[t] = rho * latent[t - 1] + np.sqrt(1.0 - rho ** 2) * innov[t]
    latent_df = pd.DataFrame(latent, index=dates, columns=symbols)
    mu = latent_df.mean(axis=1)
    sd = latent_df.std(axis=1, ddof=0).replace(0.0, np.nan)
    latent_z = latent_df.sub(mu, axis=0).div(sd, axis=0)

    # -- labels: fwd_ret_h_demeaned = TRUE_IC * latent(t) + fresh per-h noise --
    label_pieces = []
    fwd1_wide = None
    for h in contracts.HORIZONS:
        noise = rng.normal(0.0, np.sqrt(h), size=shape)
        raw = 0.02 * (TRUE_IC * latent_z.to_numpy() + noise)
        raw_df = pd.DataFrame(raw, index=dates, columns=symbols)
        dem_df = raw_df.sub(raw_df.mean(axis=1), axis=0)
        if h == 1:
            fwd1_wide = dem_df
        label_pieces.append(_long_frame(raw_df, f"fwd_ret_{h}"))
        label_pieces.append(_long_frame(dem_df, f"fwd_ret_{h}_demeaned"))
    labels = label_pieces[0]
    for p in label_pieces[1:]:
        labels = labels.merge(p, on=["date", "symbol"])
    for h in contracts.HORIZONS:
        labels[f"fwd_ret_{h}"] = labels[f"fwd_ret_{h}"].astype(np.float64)
        labels[f"fwd_ret_{h}_demeaned"] = labels[f"fwd_ret_{h}_demeaned"].astype(np.float64)
    labels = _finalize_long(labels)
    contracts.validate_labels(labels)

    # -- features: mom_21 IS the latent; the rest are schema-filler noise --
    filler = {
        "mom_126": 0.15 * latent_z.to_numpy() + 0.8 * rng.standard_normal(shape),
        "rev_5": 0.05 * rng.standard_normal(shape),
        "vol_21": np.abs(0.15 * rng.standard_normal(shape)) + 0.05,
        "beta_63": 1.0 + 0.4 * rng.standard_normal(shape),
        "amihud_21": np.abs(2.0 * rng.standard_normal(shape)) + 0.01,
        "turnover_21": 15.0 + 1.5 * rng.standard_normal(shape),
        "max_ret_21": np.abs(0.04 * rng.standard_normal(shape)) + 0.005,
        "delivery_pct": np.clip(45.0 + 15.0 * rng.standard_normal(shape), 1.0, 99.0),
        "size_proxy": 18.0 + 1.2 * rng.standard_normal(shape),
        "dist_52wh": -np.abs(0.15 * rng.standard_normal(shape)),
    }
    feat_cols = {"mom_21": latent_z.to_numpy(), **filler}
    feat_pieces = [_long_frame(pd.DataFrame(arr, index=dates, columns=symbols), name)
                   for name, arr in feat_cols.items()]
    features = feat_pieces[0]
    for p in feat_pieces[1:]:
        features = features.merge(p, on=["date", "symbol"])
    sec_rng = np.random.default_rng(seed + 999)
    sector_map = {s: contracts.NSE_SECTORS[int(sec_rng.integers(len(contracts.NSE_SECTORS)))]
                  for s in symbols}
    features["sector"] = features["symbol"].map(sector_map).astype(str)
    for c in contracts._FEATURE_COLS:
        features[c] = features[c].astype(np.float64)
    features = _finalize_long(features)
    contracts.validate_features(features)

    return World(
        features=features, labels=labels, latent_wide=latent_z, fwd1_wide=fwd1_wide,
        dates=dates, symbols=symbols,
    )


def _mk(arr: np.ndarray, world: World) -> pd.DataFrame:
    return pd.DataFrame(arr, index=world.dates, columns=world.symbols)


def _genuine_signals(world: World, seed: int) -> dict[str, pd.DataFrame]:
    """Real signal: scaled planted latent + noise. True relationship is stable
    over the whole period by construction (no fitting to any subsample)."""
    rng = np.random.default_rng(seed)
    lat = world.latent_wide.to_numpy()
    shape = lat.shape
    out = {}
    for i in range(N_PER_CATEGORY):
        scale = float(rng.uniform(0.3, 1.5))
        # Kept modest relative to `scale` (unlike noise/overfit/leaky) so the
        # day-to-day RANK ordering doesn't churn -- a real, persistent factor
        # has low turnover; a factor whose noise dominates its true signal
        # would legitimately fail the red-team's cost_sweep test even though
        # its raw RankIC is real, which is a fair outcome, just not the one
        # this category is meant to illustrate.
        noise_scale = float(rng.uniform(0.05, 0.35))
        sig = scale * lat + noise_scale * rng.standard_normal(shape)
        out[f"genuine_{i}"] = _mk(sig, world)
    return out


def _noise_signals(world: World, seed: int) -> dict[str, pd.DataFrame]:
    """Pure iid noise, unrelated to anything. Ground truth: no real edge."""
    rng = np.random.default_rng(seed)
    shape = world.latent_wide.shape
    return {f"noise_{i}": _mk(rng.standard_normal(shape), world) for i in range(N_PER_CATEGORY)}


def _leaky_signals(world: World, seed: int) -> dict[str, pd.DataFrame]:
    """Signal := (a sign-flipped, lightly-perturbed copy of) the actual scoring
    label itself -- a textbook look-ahead leak. Stable and huge in-sample (it
    IS the answer), but built from information not available at signal time,
    so it should collapse once the signal is shifted forward one extra day
    (red-team test 5, extra_lag) -- Gate B's statistics alone cannot see this,
    since it never re-times the signal."""
    rng = np.random.default_rng(seed)
    y = world.fwd1_wide.to_numpy()
    shape = y.shape
    out = {}
    for i in range(N_PER_CATEGORY):
        flip = 1.0 if i % 2 == 0 else -1.0
        noise_scale = 0.02 + 0.01 * i
        sig = flip * y + noise_scale * rng.standard_normal(shape)
        out[f"leaky_{i}"] = _mk(sig, world)
    return out


def _overfit_signals(world: World, seed: int, panel: tuple) -> dict[str, pd.DataFrame]:
    """Best-of-N pure-noise draws, selected by brute-force search to maximize
    mean RankIC on the *exact* window (val_a) it will later be scored on -- a
    hidden multiple-comparisons problem the ledger never sees (only the winner
    is ever recorded as "one trial"). This is precisely the "if you test N
    worthless signals, the best clears t>3 by chance" scenario gates.py's own
    docstring describes -- CSCV/PBO and the red-team's year-by-year folds are
    the mechanisms that do NOT rely on the ledger's trial count to catch it."""
    rng = np.random.default_rng(seed)
    shape = world.latent_wide.shape
    y_wide = world.fwd1_wide
    val_a_dates = world.dates[
        (world.dates >= pd.Timestamp("2018-01-01")) & (world.dates <= pd.Timestamp("2021-06-30"))
    ]
    y_fit = y_wide.loc[val_a_dates]
    out = {}
    for i in range(N_PER_CATEGORY):
        best_score, best_arr = -np.inf, None
        for _ in range(OVERFIT_N_CANDIDATES):
            cand = rng.standard_normal(shape)
            cand_df = _mk(cand, world).loc[val_a_dates]
            ic = gt._wide_rank_ic(cand_df, y_fit, min_names=20)
            score = float(ic.mean()) if len(ic) else -np.inf
            if np.isfinite(score) and score > best_score:
                best_score, best_arr = score, cand
        out[f"overfit_{i}"] = _mk(best_arr, world)
    return out


def build_pool(world: World, seed: int = RANDOM_SEED) -> list[tuple[str, str, pd.DataFrame]]:
    """Round-robin-ordered ``[(name, category, signal_df), ...]`` -- 40 members,
    10 per category, interleaved so each contiguous block of 4 (and later, each
    generation-sized slice) is a representative mix rather than one category at
    a time."""
    panel = (world.features, world.labels)
    genuine = _genuine_signals(world, seed + 1)
    noise = _noise_signals(world, seed + 2)
    leaky = _leaky_signals(world, seed + 3)
    overfit = _overfit_signals(world, seed + 4, panel)
    by_cat = {"genuine": genuine, "noise": noise, "overfit": overfit, "leaky": leaky}
    pool = []
    for i in range(N_PER_CATEGORY):
        for cat in CATEGORIES:
            name = f"{cat}_{i}"
            pool.append((name, cat, by_cat[cat][name]))
    return pool


# =========================================================================== #
# 2. Per-member gate scoring (independent booleans -- see module docstring)   #
# =========================================================================== #
def score_member(
    name: str, category: str, sig_wide: pd.DataFrame, world: World, ledger: Ledger,
) -> dict[str, Any]:
    panel = (world.features, world.labels)
    raw_ic = gt.daily_rank_ic(sig_wide, SCORE_SPLIT, SCORE_HORIZON, panel=panel)
    marg = float(raw_ic.mean()) if len(raw_ic) else float("nan")
    pre_sign = -1 if (np.isfinite(marg) and marg < 0) else 1

    novelty_pass = bool(np.isfinite(marg) and abs(marg) >= gt.MIN_MARGINAL_IC)

    oriented = raw_ic * pre_sign
    n_eff = gt.effective_trial_count(ledger.trial_canonical_asts(None) + [name])
    # NOTE: trial_irs deliberately NOT passed here (see reports/p12_handoff.md
    # S7). The ablation ledger's prior trials mix pathological categories
    # (leaky t-stats run into the hundreds) with legitimate ones in one
    # sequence; feeding that as the trial-SR variance sample would let one
    # look-ahead artifact poison the DSR deflation for every later signal
    # regardless of category. n_trials_effective (count-based) still grows
    # across the whole pool -- only the empirical-variance term is skipped in
    # favour of its documented 1/T sampling-noise floor.
    dsr_block = gt.dsr_from_ic_series(oriented, n_trials=n_eff, trial_irs=None)
    pbo_block = gt._pbo_from_signal(sig_wide, SCORE_SPLIT, SCORE_HORIZON, panel)

    stats_pass = bool(
        dsr_block["n_days"] >= gt.MIN_DSR_SAMPLE
        and np.isfinite(dsr_block["dsr"]) and dsr_block["dsr"] >= gt.DSR_MIN
        and np.isfinite(dsr_block["t_stat"]) and abs(dsr_block["t_stat"]) >= T_STAT_BAR
        and (not np.isfinite(pbo_block["pbo"]) or pbo_block["pbo"] <= gt.PBO_MAX)
    )

    ledger.record_trial(
        thesis_id=None, formula_hash=name, canonical_ast=name, split_used=SCORE_SPLIT,
        rank_ic=float(oriented.mean()) if len(oriented) else float("nan"),
        sharpe=float("nan"), t_stat=dsr_block["t_stat"], n_days=dsr_block["n_days"],
        counts_as_trial=1,
        rejection_reason=None if (novelty_pass and stats_pass) else "ablation:gate_b_metrics",
    )

    rt_res = rt.run_redteam(
        sig_wide, tests=[], split=SCORE_SPLIT, horizon=SCORE_HORIZON, sign=pre_sign,
        ledger=ledger, thesis_id=None, formula_hash=name, canonical_ast=name,
    )
    redteam_pass = rt_res["verdict"] != "killed"

    return dict(
        name=name, category=category, pre_sign=pre_sign, marginal_ic=marg,
        dsr=dsr_block["dsr"], t_stat=dsr_block["t_stat"], pbo=pbo_block["pbo"],
        n_days_scored=dsr_block["n_days"], n_trials_effective=n_eff,
        novelty_pass=novelty_pass, stats_pass=stats_pass, redteam_pass=redteam_pass,
        redteam_failed_tests=list(rt_res["failed_tests"]),
    )


def score_pool(pool: list[tuple[str, str, pd.DataFrame]], world: World) -> pd.DataFrame:
    ABLATION_LEDGER_DB.parent.mkdir(parents=True, exist_ok=True)
    if ABLATION_LEDGER_DB.exists():
        ABLATION_LEDGER_DB.unlink()
    ledger = Ledger(ABLATION_LEDGER_DB)
    try:
        rows = []
        for order, (name, cat, sig) in enumerate(pool):
            rec = score_member(name, cat, sig, world, ledger)
            rec["order"] = order
            rows.append(rec)
    finally:
        ledger.close()
    return pd.DataFrame(rows)


# =========================================================================== #
# 3. Ablation: catch rate / false-kill rate / FDR on-vs-off                   #
# =========================================================================== #
GATE_COLS = {"novelty": "novelty_pass", "stats": "stats_pass", "redteam": "redteam_pass"}


def build_ablation(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    junk = df["category"] != "genuine"
    good = df["category"] == "genuine"

    rows = []
    for gate, col in GATE_COLS.items():
        catch = float((~df.loc[junk, col]).mean()) if junk.any() else float("nan")
        false_kill = float((~df.loc[good, col]).mean()) if good.any() else float("nan")
        rows.append({
            "gate": gate, "catch_rate": catch, "false_kill_rate": false_kill,
            "n_junk": int(junk.sum()), "n_good": int(good.sum()),
        })
    catch_df = pd.DataFrame(rows)

    all_on = df["novelty_pass"] & df["stats_pass"] & df["redteam_pass"]

    def _fdr(mask: pd.Series) -> tuple[float, int]:
        total = int(mask.sum())
        if total == 0:
            return float("nan"), 0
        return float((mask & junk).sum() / total), total

    fdr_all, n_all = _fdr(all_on)
    fdr_rows = [{"variant": "all_gates_on", "fdr": fdr_all, "n_accepted": n_all}]
    for gate, col in GATE_COLS.items():
        other_cols = [c for g, c in GATE_COLS.items() if g != gate]
        mask = df[other_cols[0]] & df[other_cols[1]]
        fdr_val, n_acc = _fdr(mask)
        fdr_rows.append({"variant": f"{gate}_off", "fdr": fdr_val, "n_accepted": n_acc})
    fdr_df = pd.DataFrame(fdr_rows)

    return catch_df, fdr_df, all_on


# =========================================================================== #
# 4. Fake-learning detection                                                  #
# =========================================================================== #
def pseudo_generations(df: pd.DataFrame, n_gen: int = N_GENERATIONS) -> pd.DataFrame:
    """Slice the pool, IN ITS ORIGINAL ROUND-ROBIN SUBMISSION ORDER, into
    ``n_gen`` equal batches and report per-batch volume/pass-rate.

    This is a **proxy**, not a real multi-generation agent run (see module
    docstring): each batch is a fixed random slice of a fixed pool, so it
    cannot, by construction, show genuine improvement. It exists only to
    exercise the plotting/reporting machinery the spec asks for; the honest
    finding is in :func:`real_ledger_snapshot`.
    """
    d = df.sort_values("order").reset_index(drop=True)
    chunk = len(d) // n_gen
    out = []
    for g in range(n_gen):
        sub = d.iloc[g * chunk: (g + 1) * chunk]
        all_on = sub["novelty_pass"] & sub["stats_pass"] & sub["redteam_pass"]
        novelty_fail = int((~sub["novelty_pass"]).sum())
        stats_fail = int((sub["novelty_pass"] & ~sub["stats_pass"]).sum())
        redteam_fail = int((sub["novelty_pass"] & sub["stats_pass"] & ~sub["redteam_pass"]).sum())
        out.append(dict(
            generation=g, n=int(len(sub)), rejections=int((~all_on).sum()),
            novelty_pass_rate=float(sub["novelty_pass"].mean()),
            stats_pass_rate=float(sub["stats_pass"].mean()),
            redteam_pass_rate=float(sub["redteam_pass"].mean()),
            novelty_fail=novelty_fail, stats_fail=stats_fail, redteam_fail=redteam_fail,
        ))
    return pd.DataFrame(out)


def real_ledger_snapshot(db_path: Path = REAL_LEDGER_DB) -> dict[str, Any]:
    """Read-only inspection of the REAL project ledger (never written to)."""
    if not db_path.exists():
        return {"exists": False}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("SELECT thesis_id, timestamp FROM trials ORDER BY trial_id")
        rows = cur.fetchall()
        gens = set()
        for thesis_id, _ts in rows:
            m = re.search(r"_g(\d+)", thesis_id or "")
            gens.add(m.group(1) if m else "?")
        cur.execute("SELECT COUNT(*) FROM trials")
        n_trials = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT thesis_id) FROM trials")
        n_theses = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM holdout_peeks")
        n_peeks = cur.fetchone()[0]
        return {
            "exists": True, "n_trials": int(n_trials), "n_theses": int(n_theses),
            "generation_tags": sorted(gens), "n_holdout_peeks_used": int(n_peeks),
        }
    finally:
        con.close()


def real_cards_snapshot(cards_dir: Path = REAL_CARDS_DIR) -> dict[str, Any]:
    """Read-only inspection of the real Alpha Cards written by P8-P11."""
    files = sorted(cards_dir.glob("*.json")) if cards_dir.exists() else []
    cards = []
    for f in files:
        try:
            cards.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    verdicts = [c.get("verdict") for c in cards]
    accepted = [c for c in cards if c.get("verdict") == "accept"]
    dsrs = [c.get("audit", {}).get("deflated_sharpe") for c in accepted
            if c.get("audit", {}).get("deflated_sharpe") is not None]
    sign_checks = []
    for c in cards:
        pre = c.get("pre_registered", {}).get("sign")
        real = c.get("audit", {}).get("realized_sign")
        if pre is not None and real is not None:
            sign_checks.append(int(np.sign(pre)) == int(np.sign(real)))
    return {
        "n_cards": len(cards), "verdicts": verdicts, "n_accepted": len(accepted),
        "accepted_dsr": dsrs, "n_sign_checks": len(sign_checks),
        "sign_agreement_rate": (float(np.mean(sign_checks)) if sign_checks else None),
    }


# =========================================================================== #
# 5. Plots                                                                     #
# =========================================================================== #
def plot_gate_ablation(catch_df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    x = np.arange(len(catch_df))
    w = 0.35
    ax.bar(x - w / 2, catch_df["catch_rate"], w, label="catch rate (junk rejected)")
    ax.bar(x + w / 2, catch_df["false_kill_rate"], w, label="false-kill rate (good rejected)")
    ax.set_xticks(x)
    ax.set_xticklabels(catch_df["gate"])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("rate")
    ax.set_title("Phase 12 ablation - per-gate catch / false-kill rate")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_fake_learning(gen_df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    ax1.bar(gen_df["generation"], gen_df["rejections"], color="firebrick")
    ax1.set_xlabel("pseudo-generation")
    ax1.set_ylabel("total rejections (of 10)")
    ax1.set_title("Rejection VOLUME per generation")
    ax1.set_xticks(gen_df["generation"])

    for col, label in (
        ("novelty_pass_rate", "novelty"), ("stats_pass_rate", "stats"),
        ("redteam_pass_rate", "redteam"),
    ):
        ax2.plot(gen_df["generation"], gen_df[col], marker="o", label=label)
    ax2.set_xlabel("pseudo-generation")
    ax2.set_ylabel("pass rate")
    ax2.set_ylim(-0.05, 1.05)
    ax2.set_title("Per-gate pass rate over generations")
    ax2.set_xticks(gen_df["generation"])
    ax2.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


# =========================================================================== #
# 6. Orchestration                                                             #
# =========================================================================== #
def run_evaluation(seed: int = RANDOM_SEED) -> dict[str, Any]:
    world = build_world(seed)
    _bt.use_panel(world.features, world.labels)
    try:
        pool = build_pool(world, seed)
        df = score_pool(pool, world)
        catch_df, fdr_df, all_on = build_ablation(df)
        gen_df = pseudo_generations(df)
        real_ledger = real_ledger_snapshot()
        real_cards = real_cards_snapshot()

        plot_gate_ablation(catch_df, PLOTS_DIR / "gate_ablation.png")
        plot_fake_learning(gen_df, PLOTS_DIR / "learning.png")
    finally:
        _bt.clear_panel()

    return dict(
        pool_df=df, catch_df=catch_df, fdr_df=fdr_df, all_on=all_on,
        gen_df=gen_df, real_ledger=real_ledger, real_cards=real_cards,
    )


if __name__ == "__main__":  # pragma: no cover
    out = run_evaluation()
    print(out["catch_df"])
    print(out["fdr_df"])
    print(out["gen_df"])
    print(out["real_ledger"])
    print(out["real_cards"])
