# Phase 11 demo — one good card, three bad examples, portfolio post-process

Every example below is reproducible from a single command (`PYTHONUTF8=1
.venv/Scripts/python.exe scripts/<name>.py`), against the real Phase 1-9
data and gates. Full numbers and the honest attempt history are in
`reports/p11_handoff.md`.

---

## ① The good card — `artifacts/cards/good_p11.json`

**Command:** `scripts/p11_good_card.py`

Rather than rely on live LLM search (four prior loop runs all rejected every
thesis at the fresh-fold stage — see `reports/p11_handoff.md §Attempt
history`), this card hands the *real, unmodified* nine-stage loop a
documented, published formula and lets the real gates decide.

- **Formula:** `mul(-1, ts_std(returns, 42))` — the low-volatility anomaly
  (Ang, Hodrick, Xing & Zhang 2006), window adapted from the zoo's 21 days to
  42 for lower turnover (also making it structurally novel — not an exact
  zoo-duplicate).
- **Mechanism:** leverage-constrained investors overpay for high-vol names
  seeking amplified returns, depressing their risk-adjusted expected return;
  low-vol names are under-owned and outperform correspondingly.
- **Tier-1 VAL_A:** rank_ic=0.0550, t=7.23 (n=863 days).
- **Fresh fold VAL_B:** rank_ic=0.0362, t=2.95 — holds.
- **Gate B statistics:** marginal_ic=0.0550, deflated_sharpe=**0.976**,
  pbo=**0.043**, t=7.23 — all comfortably clear real bars except DSR, which
  needed the disclosed 0.90 override (see below).
- **HOLDOUT (peek #4 of the project's 12):** rank_ic=0.0137, t=1.82 —
  24.9% retention vs. the real 30% floor; passed under the disclosed 0.20
  override.
- **Gate C red-team:** `verdict=survives`, **zero** failed tests across
  subsample_year, regime_split, cost_sweep, extra_lag, decay_curve,
  sign_stability.

**Disclosed threshold overrides (owner-directed):** `DSR_MIN` 0.95→0.90 and
`HOLDOUT_COLLAPSE_FLOOR` 0.30→0.20, both recorded in the card's
`provenance.threshold_overrides` block alongside the real numbers that would
have failed at project defaults. `T_STAT_BAR` (3.0) and `PBO_MAX` (0.50) were
**never** relaxed — this candidate cleared them on its own.

---

## ② BAD — DATA: the universe source was structurally broken

**Command:** `scripts/p11_bad_data.py` → `artifacts/cards/bad_data.json`

**Beat 1 — naive result.** Rebuild the Phase-3 feature/label panel using the
*supplied* constituent file (`nifty200_2015-01-01_to_2026-09-01.csv`,
forward-filled between its own snapshot dates — the obvious thing to do with
a "constituent file") instead of Phase 1's bhavcopy-reconstructed universe.
Run the low-volatility factor through it:
- Gate B statistics: **deflated_sharpe=1.000**, **pbo=0.000**, t=8.12 — accept.
- purge/embargo: applied inside every backtest call, no anomaly.
- Red-team decisive tests (subsample_year, regime_split, cost_sweep,
  extra_lag, sign_stability): **verdict=survives**, zero flags. `extra_lag`
  specifically: 0.0568 → 0.0552 (barely moves).

**Beat 2 — the system catches it, but not through any gate above.** External
reconciliation of the CSV's 314-symbol union against today's real 200-name
universe (`data/universe/membership.parquet`) shows **88 names absent
entirely** — including large, obviously-liquid names — **98.9% of them with
zero recorded inclusion/exclusion events**: the signature of a change-log
replayed onto an incomplete base seed, padded back to ~200 with mid-caps.
Every statistical and red-team mechanism above passed cleanly, because the
defect contaminates the *universe* (which names exist to rank), not any one
factor's time series.

**Beat 3 — the fix.** Phase 1 abandoned the supplied CSV for selection
entirely; the universe is rebuilt from daily bhavcopy by trailing 63-day
turnover (`reports/p1_universe_report.md`, `data/universe/membership.parquet`
— in production since Phase 1, not something this example changed).

---

## ③ BAD — STATISTICS: a leaky factor no statistical gate catches

**Command:** `scripts/p11_bad_stats.py` → `artifacts/cards/bad_stats.json`

**Beat 1 — naive result.** A "signal" standing in for a data-pipeline bug
(a field joined one day early) — 85% the 1-day-ahead label plus 15% noise
(an exact copy would give the daily IC series zero variance and break the
Sharpe ratio itself rather than illustrate the point). Tier-1 VAL_A:
**rank_ic=0.9697, t=2099** — spectacular.

**Beat 2 — the system catches it, but only at Gate C.** Gate B statistics
**ACCEPTS** it outright: deflated_sharpe=**1.000**, pbo=**0.000** — a
statistics-only gate has nothing to say against it (DSR/PBO measure
*over-searching*, not *causality*; a single, un-searched signal has
n_trials≈1 and passes DSR trivially). Red-team test 5 (`extra_lag`, shift the
whole signal forward one trading day) collapses it: rank_ic
**0.9697 → -0.0505**, t=-10.95, flagged, `verdict=killed`.

**Beat 3 — the fix.** This is exactly why Gate C (red-team) exists as a
mechanism *separate* from Gate B (statistics): DSR/PBO answer "did we search
too much for this?"; `extra_lag` answers "is this causal, or does it die
under a lag any honest trading process would incur?" — different failure
classes need different instruments. (Formula-level look-ahead via the
operator grammar itself is structurally impossible — `delay()` rejects
negative windows, `src/operators.py` — so this class of bug has to come from
the data pipeline, not the formula.)

---

## ④ BAD — ECONOMICS: right idea, wrong sign

**Command:** `scripts/p11_bad_economics.py` → `artifacts/cards/bad_economics.json`

**Beat 1 — naive result / the thesis.** Raw 2-day price change, pre-registered
**before any backtest** with a momentum mechanism ("investors underreact to
recent news; a stock that has just risen keeps rising as slower participants
catch up") and `pre_registered_sign = +1`.

**Beat 2 — the system catches it, and no statistical gate would have.** The
realized VAL_A direction, measured *after* pre-registration: **rank_ic=-0.0204,
t=-4.35** — decisively significant, easily clearing T_STAT_BAR=3.0, and the
**opposite** sign of what was committed (short-horizon Indian equities
mean-revert over 2 days here, not momentum-continue — the well-documented
liquidity-provision/bid-ask-bounce effect; `classical_short_term_reversal` in
the zoo is written with exactly this `× -1` orientation). `gates.check_sign`
hard-rejects: **not** because the |IC| is weak — oriented by the
pre-registered sign it is a strong, real, |t|=4.35 edge that would clear
DSR/PBO/red-team without complaint — but because the realized direction
contradicts the committed mechanism.

**Beat 3 — the fix.** A mechanism has to explain the *sign*, not just the
*existence*, of an edge. `commit_preregistration` freezes the sign before any
data is touched specifically so a thesis cannot be rationalized after seeing
the number; `check_sign` (`src/gates.py`) enforces it as a hard reject, never
an invitation to flip the label and keep the discovery.

---

## ⑤ Portfolio post-process

**Command:** `scripts/p11_portfolio.py` → `artifacts/portfolio_report.md` /
`.json`

Only 1 real card is on record (`good_p11.json`) — below the 2-card minimum
for `loop.portfolio_combine`. Per the spec, both mechanisms are demonstrated
on a documented set instead: four zoo-family formulas (reversal/liquidity,
momentum, low-volatility, illiquidity), real panel, real daily rank-IC.

- **Low-correlation combination:** inverse-mean-|corr| weights (dominated by
  `reversal_pv_covar` at 0.476, the least-correlated member). **Combined
  ICIR = 0.289**, beating the best individual member (low_volatility,
  ICIR=0.251) — `beats_best_individual: true`.
- **Regime weight-gating:** re-optimizing weights within each of P9's
  expanding-window regimes (bull/bear/calm/volatile/highvol) **improves ICIR
  in 3 of 5 regimes** (bear, volatile, highvol) and **hurts in 2** (bull,
  calm) — reported as measured, not tuned to look good.

Full table in `artifacts/portfolio_report.md`.
