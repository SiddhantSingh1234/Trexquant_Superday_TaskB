"""Phase 6 acceptance tests — plain pytest, no network.

Everything runs against the Phase-0 synthetic fixtures via
``backtester.use_panel``.  The fixture is sized to 2,700 business days so it
spans into the HOLDOUT region (2022-07-01 →) — Gate B's rationed peek needs
real HOLDOUT rows to score.

The fixture's ``mom_21`` carries a planted mean-daily RankIC of ~0.04; every
independent random frame is a genuine pure-noise signal (its correlation with
the planted latent is ~0).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from src import backtester as bt
from src import contracts as C
from src import gates as G
from src import ledger as L
from src.config import HOLDOUT_PEEK_BUDGET, T_STAT_BAR
from src.contracts import PLANTED_IC
from src.ledger import Ledger

N_DAYS, N_SYMBOLS, SEED = 2700, 60, 42


@pytest.fixture(scope="module", autouse=True)
def _panel():
    feats = C.make_fake_features(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED)
    labs = C.make_fake_labels(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED)
    bt.use_panel(feats, labs)
    yield feats, labs
    bt.clear_panel()


@pytest.fixture(scope="module")
def planted(_panel):
    feats, _ = _panel
    return feats.pivot_table(index="date", columns="symbol", values="mom_21")


@pytest.fixture
def led(tmp_path):
    lg = Ledger(tmp_path / "ledger.db")
    yield lg
    lg.close()


def _noise_like(ref, rng):
    return pd.DataFrame(
        rng.standard_normal(ref.shape), index=ref.index, columns=ref.columns
    )


# ======================================================================= #
# Ledger                                                                   #
# ======================================================================= #
def test_ledger_module_contains_no_row_removal_sql():
    """Acceptance: the ledger module contains no DELETE (and no DROP/TRUNCATE)."""
    src = (L.__file__)
    text = open(src, encoding="utf-8").read()
    L.assert_no_row_removal_sql()  # structural guard
    # independent belt-and-braces grep for the SQL keyword as a statement
    for m in re.finditer(r"\bDELETE\b", text, flags=re.IGNORECASE):
        line = text[: m.start()].count("\n") + 1
        snippet = text.splitlines()[line - 1].strip()
        assert snippet.startswith("#") or "_FORBIDDEN_SQL" in snippet, (
            f"ledger.py:{line}: {snippet!r}"
        )


def test_ledger_is_append_only_and_persists(tmp_path):
    p = tmp_path / "l.db"
    lg = Ledger(p)
    t1 = lg.record_trial("th", "h1", "rank(close)", "val_a", 0.03, 1.1, 3.4, 800, 1)
    lg.record_trial("th", "h2", "rank(open)", "val_a", 0.01, 0.2, 1.1, 800, 0, "redteam")
    lg.close()

    lg2 = Ledger(p)                      # reopen — rows survive
    assert lg2.n_trials("th") == 1       # only the counts_as_trial=1 row
    assert lg2.n_trials() == 1
    assert len(lg2.trial_records("th", counts_only=False)) == 2
    assert t1 == 1
    lg2.close()


def test_selection_vs_rejection_only_distinction(led):
    led.record_trial("t", "a", "f_a", "val_a", 0.04, 1.0, 3.5, 800, counts_as_trial=1)
    led.record_trial("t", "b", "f_b", "val_a", 0.04, 1.0, 3.5, 800, counts_as_trial=1)
    # red-team / cost-sweep / lag rows never promote -> counts_as_trial=0
    for i in range(11):
        led.record_trial("t", f"rt{i}", "f_a", "val_a", 0.04, 1.0, 3.5, 800,
                         counts_as_trial=0, rejection_reason="redteam")
    assert led.n_trials("t") == 2                       # 11 stress runs do NOT inflate N
    assert len(led.trial_irs("t")) == 2


def test_holdout_peek_budget_is_hard(led):
    """Acceptance: request_holdout_peek returns a token exactly
    HOLDOUT_PEEK_BUDGET times, then None forever."""
    granted = [led.request_holdout_peek(f"card{i}") for i in range(HOLDOUT_PEEK_BUDGET + 5)]
    assert sum(t is not None for t in granted) == HOLDOUT_PEEK_BUDGET
    assert all(t is None for t in granted[HOLDOUT_PEEK_BUDGET:])
    assert led.request_holdout_peek("later") is None    # still None, forever
    assert led.holdout_peeks_used() == HOLDOUT_PEEK_BUDGET
    assert led.holdout_peeks_remaining() == 0


def test_finalize_holdout_peek_records_result(led):
    tok = led.request_holdout_peek("cardX")
    led.finalize_holdout_peek(tok, {"rank_ic": 0.021, "t_stat": 2.9})
    rec = led.holdout_peek_records()[0]
    assert rec["card_id"] == "cardX"
    assert rec["result"]["status"] == "used"
    assert rec["result"]["rank_ic"] == 0.021


# ======================================================================= #
# Deflated Sharpe — the governing √(2 ln N) fact                           #
# ======================================================================= #
def test_expected_max_sharpe_tracks_the_order_statistic():
    """The Bailey-LdP E[max SR] term is the *true* expected maximum of N standard
    normals — tighter than (and below) the crude √(2 ln N) upper bound the spec
    quotes.  Reference order-statistic means: N=20→1.87, N=100→2.51, N=200→2.75,
    N=500→3.04.
    """
    ref = {10: 1.54, 20: 1.87, 100: 2.51, 200: 2.75, 500: 3.04}
    prev = -1.0
    for n, want in ref.items():
        got = G.expected_max_sharpe(n, sr_std=1.0)
        assert abs(got - want) < 0.15, (n, got, want)
        assert got < np.sqrt(2 * np.log(n))          # below the loose bound
        assert got > prev                            # monotone in N
        prev = got
    assert G.expected_max_sharpe(1, 1.0) == 0.0
    assert G.expected_max_sharpe(200, 0.0) == 0.0    # zero trial-SR spread


def test_headline_200_noise_best_t_is_near_3_and_dsr_rejects(planted, tmp_path):
    """THE HEADLINE TEST.

    200 pure-noise signals → the best one's raw t-stat lands near √(2 ln 200) ≈
    3.26, and the Deflated Sharpe MUST reject it.
    """
    lg = Ledger(tmp_path / "noise.db")
    rng = np.random.default_rng(0)
    irs, series = [], []
    for i in range(200):
        ic = G.daily_rank_ic(_noise_like(planted, rng), "val_a", 1)
        T = len(ic)
        ir = ic.mean() / ic.std(ddof=1)
        irs.append(ir)
        series.append(ic)
        lg.record_trial("noise", f"h{i}", f"noise_{i}", "val_a",
                        float(ic.mean()), float("nan"), float(ir * np.sqrt(T)), int(T))

    t_stats = np.array([ir * np.sqrt(len(s)) for ir, s in zip(irs, series)])
    best = int(np.argmax(np.abs(t_stats)))
    best_t = float(t_stats[best])
    assert 2.5 < abs(best_t) < 4.2, f"best noise t-stat {best_t} not near √(2 ln 200)=3.26"

    block = G.dsr_from_ic_series(
        series[best] * np.sign(best_t), n_trials=200, trial_irs=irs
    )
    assert block["dsr"] < 0.90, f"DSR {block['dsr']:.3f} failed to reject best-of-200 noise"
    assert lg.n_trials("noise") == 200
    lg.close()


def test_real_signal_in_5_trials_passes_the_same_gate(planted, tmp_path):
    """A genuinely predictive signal found in 5 trials clears the Deflated Sharpe
    that just rejected the best of 200 noise trials."""
    lg = Ledger(tmp_path / "real.db")
    rng = np.random.default_rng(1)
    ic_real = G.daily_rank_ic(planted, "val_a", 1)
    T = len(ic_real)
    irs = [ic_real.mean() / ic_real.std(ddof=1)]
    lg.record_trial("real", "r0", "rank(mom_21)", "val_a", float(ic_real.mean()),
                    float("nan"), float(irs[0] * np.sqrt(T)), int(T))
    for i in range(4):
        ic = G.daily_rank_ic(_noise_like(planted, rng), "val_a", 1)
        ir = ic.mean() / ic.std(ddof=1)
        irs.append(ir)
        lg.record_trial("real", f"n{i}", f"noise_{i}", "val_a", float(ic.mean()),
                        float("nan"), float(ir * np.sqrt(len(ic))), int(len(ic)))

    block = G.dsr_from_ic_series(ic_real, n_trials=5, trial_irs=irs)
    assert block["dsr"] >= G.DSR_MIN, block
    assert abs(block["t_stat"]) > T_STAT_BAR
    lg.close()


def test_dsr_denominator_uses_non_normal_moments():
    """A fat left tail (negative skew, high kurtosis) lowers the DSR vs a normal
    series with the same Sharpe."""
    rng = np.random.default_rng(3)
    T = 900
    base = rng.standard_normal(T) * 0.01 + 0.002
    skewed = base.copy()
    skewed[rng.integers(0, T, 40)] -= 0.05         # rare big losses
    d_norm = G.deflated_sharpe_ratio(
        base.mean() / base.std(ddof=1), 10, 1e-4,
        float(pd.Series(base).skew()), 3.0 + float(pd.Series(base).kurt()), T)
    d_skew = G.deflated_sharpe_ratio(
        skewed.mean() / skewed.std(ddof=1), 10, 1e-4,
        float(pd.Series(skewed).skew()), 3.0 + float(pd.Series(skewed).kurt()), T)
    assert d_skew < d_norm


# ======================================================================= #
# Effective trial count                                                    #
# ======================================================================= #
def test_effective_count_of_20_near_identical_is_far_below_20():
    """Acceptance: effective trial count for 20 near-identical formulas is
    materially below 20."""
    asts = [f"div(volume,ts_mean(volume,{k}))" for k in range(5, 25)]
    eff = G.effective_trial_count(asts)
    assert eff < 5, eff
    # genuinely distinct structures are not collapsed
    distinct = [f"rank(mom_21)", "ts_mean(close,5)", "correlation(high,low,10)",
                "delta(vwap,3)", "sign(returns)"]
    assert G.effective_trial_count(distinct) == 5


def test_effective_count_splits_decorrelated_siblings():
    """Same AST shape but decorrelated return series → more than one effective bet."""
    rng = np.random.default_rng(4)
    asts = ["div(volume,ts_mean(volume,5))"] * 6
    corr_mat = rng.standard_normal((400, 6))               # ~uncorrelated
    eff = G.effective_trial_count(asts, return_matrix=corr_mat)
    assert eff > 4, eff
    # perfectly correlated siblings collapse back toward 1
    coll = np.tile(rng.standard_normal((400, 1)), (1, 6)) + 1e-6 * rng.standard_normal((400, 6))
    assert G.effective_trial_count(asts, return_matrix=coll) < 1.5


# ======================================================================= #
# Orthogonalisation / marginal IC                                          #
# ======================================================================= #
def test_marginal_ic_of_a_factor_against_itself_is_zero(planted):
    """Acceptance: marginal IC of a factor against itself as the book ≈ 0.

    The residual is numerically ~0; its RankIC is pure sampling noise (std
    ~0.004 over VAL_A), so "≈ 0" means "at the noise floor and far below the raw
    IC", not bit-zero.
    """
    raw = abs(G.daily_rank_ic(planted, "val_a", 1).mean())
    mi = G.marginal_ic(planted, {"self": planted}, "val_a", 1)
    assert abs(mi) < 0.012, mi
    assert abs(mi) < raw / 2, (mi, raw)


def test_marginal_ic_empty_book_equals_raw_ic(planted):
    raw = G.daily_rank_ic(planted, "val_a", 1).mean()
    assert G.marginal_ic(planted, None, "val_a", 1) == pytest.approx(raw)
    assert G.marginal_ic(planted, pd.DataFrame(), "val_a", 1) == pytest.approx(raw)


def test_orthogonalize_removes_a_correlated_book_factor(planted):
    """A signal that is (book factor + noise) has near-zero marginal IC once the
    book factor is projected out, even though its raw IC is real."""
    rng = np.random.default_rng(5)
    noisy = planted + 0.01 * _noise_like(planted, rng)
    raw = G.daily_rank_ic(noisy, "val_a", 1).mean()
    marg = G.marginal_ic(noisy, {"planted": planted}, "val_a", 1)
    assert abs(raw) > 0.02
    assert abs(marg) < abs(raw) / 2


# ======================================================================= #
# Walk-forward                                                             #
# ======================================================================= #
def test_walk_forward_real_vs_noise(planted):
    oos, folds = G.walk_forward(planted, "2018-01-01", "2021-06-30",
                                train_years=1, step_months=6)
    assert len(folds) >= 3
    assert len(oos) > 200
    assert oos.mean() == pytest.approx(PLANTED_IC, abs=0.02)

    rng = np.random.default_rng(6)
    oos_n, _ = G.walk_forward(_noise_like(planted, rng), "2018-01-01", "2021-06-30",
                              train_years=1, step_months=6)
    assert abs(oos_n.mean()) < 0.01


def test_walk_forward_refuses_holdout(planted):
    with pytest.raises(PermissionError):
        G.walk_forward(planted, "2021-01-01", "2023-01-01")


# ======================================================================= #
# CSCV → PBO                                                               #
# ======================================================================= #
def test_pbo_is_about_half_for_noise_and_low_for_a_real_signal():
    """Acceptance: PBO ≈ 0.5 for noise selection; low for a real signal."""
    rng = np.random.default_rng(7)
    noise_pbos = [G.cscv_pbo(rng.standard_normal((800, 12)))["pbo"] for _ in range(15)]
    assert 0.35 < np.mean(noise_pbos) < 0.65, np.mean(noise_pbos)

    real_pbos = []
    for _ in range(10):
        m = np.hstack([0.07 + 0.3 * rng.standard_normal((800, 1)),
                       rng.standard_normal((800, 11))])
        real_pbos.append(G.cscv_pbo(m)["pbo"])
    assert np.mean(real_pbos) < 0.15, np.mean(real_pbos)


def test_cscv_pbo_shape_and_guards():
    out = G.cscv_pbo(np.random.default_rng(0).standard_normal((800, 5)))
    assert set(out) == {"pbo", "n_splits", "logits", "median_oos_rank"}
    assert out["n_splits"] == 70                       # C(8, 4)
    with pytest.raises(ValueError):
        G.cscv_pbo(np.zeros((800, 1)))                 # need M >= 2
    with pytest.raises(ValueError):
        G.cscv_pbo(np.zeros((10, 5)))                  # too short


# ======================================================================= #
# Pre-registered sign                                                      #
# ======================================================================= #
def test_check_sign():
    """Acceptance: check_sign(+1, -1) is False."""
    assert G.check_sign(1, -1) is False
    assert G.check_sign(-1, 1) is False
    assert G.check_sign(1, 1) is True
    assert G.check_sign(-1, -1) is True
    assert G.check_sign(1, 0) is False


# ======================================================================= #
# Gate B — the load-bearing order, end to end                              #
# ======================================================================= #
def _card(cid, tid, ast, sign=1, horizon=1):
    return {
        "card_id": cid, "thesis_id": tid, "ast_canonical": ast, "formula": ast,
        "thesis": {"horizon_days": horizon},
        "pre_registered": {"sign": sign, "hash": f"sha256:{cid}"},
    }


def test_gate_b_accepts_a_real_signal_and_counts_one_trial(planted, led):
    for k in range(4):
        led.record_trial("th_real", f"v{k}", f"div(volume,ts_mean(volume,{5+k}))",
                         "val_a", 0.03, float("nan"), 3.4, 800, 1)
    verdict, reasons, audit = G.gate_b(
        _card("c_real", "th_real", "rank(mom_21)"), None, led, signal=planted
    )
    assert verdict == "accept", reasons
    assert audit["deflated_sharpe"] >= G.DSR_MIN
    assert abs(audit["t_stat"]) > T_STAT_BAR
    assert audit["pbo"] <= G.PBO_MAX
    assert audit["holdout_peek_id"] == 1
    assert led.n_trials("th_real") == 5          # the 4 priors + this Gate-B eval
    assert led.holdout_peeks_used() == 1


def test_gate_b_kills_a_clone_before_spending_a_peek(planted, led):
    """Novelty precedes statistics precedes the peek: a signal with no marginal
    IC over the book is rejected without a HOLDOUT peek being spent."""
    verdict, reasons, audit = G.gate_b(
        _card("c_clone", "th_clone", "rank(mom_21)"),
        {"book": planted}, led, signal=planted,
    )
    assert verdict == "reject"
    assert any("novelty" in r for r in reasons)
    assert audit.get("holdout_peek_id") is None
    assert led.holdout_peeks_used() == 0          # the free check killed it first


def test_gate_b_order_is_orthogonalize_novelty_statistics_peek(planted, led):
    _, _, audit = G.gate_b(_card("c_o", "th_o", "rank(mom_21)"), None, led, signal=planted)
    assert audit["gate_b_order"] == ["orthogonalize", "novelty", "statistics", "holdout_peek"]


def test_gate_b_rejects_pre_registered_sign_mismatch(planted, led):
    verdict, reasons, audit = G.gate_b(
        _card("c_sign", "th_sign", "rank(mom_21)", sign=-1), None, led, signal=planted
    )
    assert verdict == "reject"
    assert any("sign" in r for r in reasons)
    assert led.holdout_peeks_used() == 0


def test_gate_b_dsr_rejects_best_of_many_noise(planted, tmp_path):
    """Gate B end-to-end on the best of 40 noise variants sharing one thesis:
    the ledger's trial count deflates the Sharpe and the candidate is rejected."""
    lg = Ledger(tmp_path / "g.db")
    rng = np.random.default_rng(11)
    best_ic, best_t, best_sig = None, 0.0, None
    for i in range(40):
        sig = _noise_like(planted, rng)
        ic = G.daily_rank_ic(sig, "val_a", 1)
        t = ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic))
        lg.record_trial("th_n", f"v{i}", f"noise_{i}", "val_a", float(ic.mean()),
                        float("nan"), float(t), int(len(ic)))
        if abs(t) > abs(best_t):
            best_t, best_ic, best_sig = t, ic, sig
    verdict, reasons, audit = G.gate_b(
        _card("c_bn", "th_n", "noise_best", sign=int(np.sign(best_t))),
        None, lg, signal=best_sig,
    )
    assert verdict == "reject", audit
    assert any("statistics" in r or "novelty" in r for r in reasons)
    lg.close()


def test_gate_b_is_deterministic(planted, tmp_path):
    a = G.gate_b(_card("c1", "t1", "rank(mom_21)"), None,
                 Ledger(tmp_path / "a.db"), signal=planted)
    b = G.gate_b(_card("c1", "t1", "rank(mom_21)"), None,
                 Ledger(tmp_path / "b.db"), signal=planted)
    assert a[0] == b[0]
    for k in ("marginal_ic", "deflated_sharpe", "t_stat", "pbo"):
        assert a[2][k] == pytest.approx(b[2][k]), k


# ======================================================================= #
# Regressions — the four defects found in the P6 verification pass         #
# (see reports/p6_handoff.md §5.  Each of these FAILS on the pre-fix code.) #
# ======================================================================= #
def test_holdout_peek_scores_the_residual_not_the_raw_signal(planted, led):
    """FINDING A. The peek must confirm the SAME object steps 2-3 judged.

    A *partial* clone — real marginal IC over the book, but most of its raw IC
    explained by the book — clears novelty and statistics, so it reaches step 4.
    If the peek scored the raw signal it would be confirmed by the very book it
    was measured against, and the collapse check would be comparing a raw
    holdout IC with a residual VAL IC (mixed units, so it could never bite).
    """
    rng = np.random.default_rng(99)
    partial = planted + _noise_like(planted, rng)          # noisy copy of the signal
    book = {"partial": partial}
    verdict, reasons, audit = G.gate_b(
        _card("c_pc", "th_pc", "rank(mom_21)"), book, led, signal=planted
    )
    assert verdict == "accept", reasons                     # it does reach step 4
    assert audit["holdout_peek_id"] == 1
    assert audit["holdout_scored_on"] == "residual"

    resid = G.orthogonalize(planted, book)
    ic_resid = bt.backtest(resid, "holdout", horizon=1, i_have_a_peek_token=True)["rank_ic"]
    ic_raw = bt.backtest(planted, "holdout", horizon=1, i_have_a_peek_token=True)["rank_ic"]
    assert audit["holdout_rank_ic"] == pytest.approx(ic_resid)
    assert audit["holdout_rank_ic"] != pytest.approx(ic_raw, abs=1e-6)
    # and the two really are distinguishable, so the assertion has teeth
    assert abs(ic_raw) > 1.5 * abs(ic_resid)


def test_deflation_uses_the_global_ledger_not_just_the_thesis(planted, tmp_path):
    """FINDING B. Deflation is priced on the run-wide ledger.

    40 noise variants are searched, each recorded under its OWN thesis_id; the
    winner is then gated under a 41st, brand-new thesis.  Thesis-local deflation
    would see N=1 → E[max SR]=0 → no deflation at all → accept.  Global
    deflation sees the search that actually happened and rejects.
    """
    lg = Ledger(tmp_path / "global.db")
    rng = np.random.default_rng(1)   # this seed's winner has raw |t| = 3.00 —
    best_t, best_sig = 0.0, None     # it clears the naive "t > 3" bar from noise
    for i in range(40):
        sig = _noise_like(planted, rng)
        ic = G.daily_rank_ic(sig, "val_a", 1)
        t = ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic))
        lg.record_trial(f"th_{i}", f"v{i}", f"noise_{i}", "val_a", float(ic.mean()),
                        float("nan"), float(t), int(len(ic)))     # 40 DIFFERENT theses
        if abs(t) > abs(best_t):
            best_t, best_sig = t, sig
    verdict, reasons, audit = G.gate_b(
        _card("c_g", "th_fresh", "noise_best", sign=int(np.sign(best_t))),
        None, lg, signal=best_sig,
    )
    assert abs(best_t) > T_STAT_BAR                        # noise that clears "t > 3"
    assert audit["n_trials_within_thesis"] == 0            # brand-new thesis
    assert audit["n_trials_global"] == 40
    assert audit["n_trials_effective"] >= 40               # deflated on the run, not the thesis
    assert audit["expected_max_sr"] > 0.0
    assert verdict == "reject", audit
    assert lg.holdout_peeks_used() == 0                    # never reached step 4
    lg.close()


def test_deflation_uses_the_effective_count_not_raw_n(planted, led):
    """FINDING D. Step 2 of the spec exists to stop raw N over-penalising; the
    DSR must therefore be handed the EFFECTIVE count, not `max(n_eff, raw N)`
    (which is always raw N, since n_eff <= N)."""
    for k in range(20):                                    # 20 knob-variants, one shape
        led.record_trial("th_e", f"v{k}", f"div(volume,ts_mean(volume,{5+k}))",
                         "val_a", 0.02, float("nan"), 2.0, 900, 1)
    _, _, audit = G.gate_b(_card("c_e", "th_e", "rank(mom_21)"), None, led, signal=planted)
    assert audit["n_trials_global"] == 20
    assert audit["n_trials_effective"] < 5, audit          # 20 knobs are ~2 bets, not 20
    assert audit["n_trials_effective"] >= 2


def test_trial_sr_variance_has_a_sampling_floor():
    """FINDING E. Identical trial SRs give sample variance 0, which would set
    E[max SR]=0 and switch deflation off.  Floor it at 1/T."""
    rng = np.random.default_rng(21)
    ic = pd.Series(rng.standard_normal(900) * 0.13 + 0.012)
    flat = G.dsr_from_ic_series(ic, n_trials=100, trial_irs=[0.05] * 40)   # zero variance
    assert flat["sr0"] > 0.0
    assert flat["sr0"] == pytest.approx(
        G.expected_max_sharpe(100, np.sqrt(1.0 / flat["n_days"])), rel=1e-9
    )
    # a genuinely dispersed trial sample is used as-is (floor does not bind)
    wide = G.dsr_from_ic_series(ic, n_trials=100, trial_irs=list(rng.normal(0, 0.1, 40)))
    assert wide["sr0"] > flat["sr0"]


def test_label_cache_is_bounded_and_pins_its_panel(planted, _panel):
    """FINDING C. `backtester._load_panel()` returns a fresh frame on every disk
    read, so an id-keyed cache would add one never-hit entry per gate_b call
    (~12.5 MB on the real panel) and could hand back a stale pivot if CPython
    recycled a freed frame's id.  Bounded LRU + a strong ref to the panel."""
    import gc

    G.clear_label_cache()
    feats, _ = _panel
    for _ in range(G.LABEL_CACHE_MAXSIZE + 4):
        labs = C.make_fake_labels(n_days=N_DAYS, n_symbols=N_SYMBOLS, seed=SEED)
        G.daily_rank_ic(planted, "val_a", 1, panel=(feats, labs))
        del labs
        gc.collect()
    assert len(G._LABEL_WIDE_CACHE) <= G.LABEL_CACHE_MAXSIZE
    # every live entry pins the panel it was built from -> its id cannot be reused
    for (obj_id, _h), (labels_ref, wide) in G._LABEL_WIDE_CACHE.items():
        assert id(labels_ref) == obj_id
        assert isinstance(wide, pd.DataFrame) and not wide.empty
    G.clear_label_cache()
    assert len(G._LABEL_WIDE_CACHE) == 0
