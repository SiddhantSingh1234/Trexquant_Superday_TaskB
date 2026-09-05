# Portfolio post-process — Phase 11 deliverable ⑤

Reproducible: `PYTHONUTF8=1 .venv/Scripts/python.exe scripts/p11_portfolio.py`
Full numbers: `artifacts/portfolio_report.json`

## Status

`Memory().book.get_book_wide()` (the real accepted-card book) currently holds
**1** card — the loop is designed to reject almost everything, and Phase 11
accepted exactly one card (`good_p11.json`, under disclosed threshold
overrides — see `reports/p11_handoff.md`). Per the spec ("if fewer than 3
cards were accepted, say so plainly and demonstrate both mechanisms on a
synthetic set"), this report demonstrates the two mechanisms on a
**documented set**: four zoo-family formulas, real panel, real daily rank-IC.

**This is a mechanism demonstration, not a claim that all four have cleared
Gate B.** Only `good_p11.json` is an accepted card with a full audit trail.

## The four formulas

| Name | Formula | Family |
|---|---|---|
| `reversal_pv_covar` | `mul(-1, rank(covariance(rank(high), rank(volume), 6)))` | reversal/liquidity |
| `momentum_12_1` | `sub(div(delay(close, 21), delay(close, 252)), 1)` | momentum |
| `low_volatility` | `mul(-1, ts_std(returns, 21))` | low-vol anomaly |
| `illiquidity_amihud` | `ts_mean(div(abs(returns), mul(close, volume)), 21)` | illiquidity |

## Individual RankIC / ICIR (VAL_A)

| Formula | mean RankIC | ICIR |
|---|---:|---:|
| reversal_pv_covar | 0.0186 | 0.204 |
| momentum_12_1 | 0.0286 | 0.135 |
| low_volatility | 0.0521 | **0.251** (best individual) |
| illiquidity_amihud | -0.0202 | -0.132 |

## Correlation matrix

|  | reversal_pv_covar | momentum_12_1 | low_volatility | illiquidity_amihud |
|---|---:|---:|---:|---:|
| reversal_pv_covar | 1.000 | -0.084 | 0.059 | -0.278 |
| momentum_12_1 | -0.084 | 1.000 | 0.583 | -0.330 |
| low_volatility | 0.059 | 0.583 | 1.000 | -0.617 |
| illiquidity_amihud | -0.278 | -0.330 | -0.617 | 1.000 |

## Low-correlation combination (inverse-mean-|corr| weights)

| Formula | weight |
|---|---:|
| reversal_pv_covar | 0.476 |
| momentum_12_1 | 0.201 |
| illiquidity_amihud | 0.164 |
| low_volatility | 0.159 |

**Combined ICIR = 0.289**, vs. best individual (low_volatility) = 0.251.
**The combined book beats the best single member** (`beats_best_individual:
true`) — the mechanism works: reversal_pv_covar is the least-correlated
member (|corr| ≤ 0.28 with everything else) and gets the largest weight.

## Regime weight-gating

Weights recomputed per regime (P9's expanding-window labels — bull/bear/calm/
volatile/highvol), compared against applying the single static weighting
inside the same regime-restricted days.

| Regime | n_days | gated ICIR | static ICIR | gating improves? |
|---|---:|---:|---:|---|
| bull | 377 | 0.197 | 0.247 | ❌ no |
| bear | 281 | 0.327 | 0.278 | ✅ yes |
| calm | 340 | 0.317 | 0.333 | ❌ no |
| volatile | 523 | 0.264 | 0.259 | ✅ yes |
| highvol | 359 | 0.235 | 0.220 | ✅ yes |

**Honest finding: regime-gating helps in 3 of 5 regimes (bear, volatile,
highvol) and hurts in 2 (bull, calm).** It is not a free lunch — in the two
regimes where correlations across the four factors are already low relative
to their bull/calm structure, re-optimizing weights on a shorter, regime-
restricted sample adds estimation noise that outweighs the benefit of
adapting the mix. This is reported as measured, not tuned to look good — per
the "do not tune the gates to make the ablation look good" discipline this
project holds itself to (Phase 12).
