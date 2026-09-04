# Phase 10 loop report — run_id=run

- status: **completed** (reached generation cap)
- generations run: 2
- accepted cards: 0
- trials (counts_as_trial=1): 0
- holdout peeks used: 0
- final T_STAT_BAR: 3.0   final MIN_MARGINAL_IC: 0.01
- state digest: `sha256:475b67fde978da143173111106dfb4df71c027612e0976373e465a2311dd1215`

## Per-generation

| gen | family | verdict | variants | forced | redteam | reject reason |
|---|---|---|---|---|---|---|
| 0 | liquidity | reject | 0 | False | None | fresh fold: VAL_B oriented RankIC=nan (t=None) did not hold |
| 1 | momentum | reject | 0 | False | None | fresh fold: VAL_B oriented RankIC=nan (t=None) did not hold |

## Pre-registration log (sign hash stored before any backtest)

- `th_run_g0` sha256:4ba468b6c9e33dc5… — before_backtest
- `th_run_g1` sha256:2e5f415f39b5f44a… — before_backtest

## Portfolio (post-process, off-graph)

```json
{
  "status": "insufficient",
  "n_accepted": 0,
  "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"
}
```

## Event log tail

- {'kind': 'prereg_stored', 'thesis_id': 'th_run_g0', 'hash': 'sha256:4ba468b6c9e33dc5d2f899ff339ccd5fd3f0fc8b777d5a9a07500af9bc362352', 'seq': 0}
- {'kind': 'prereg_stored', 'thesis_id': 'th_run_g1', 'hash': 'sha256:2e5f415f39b5f44a61c662e410c904695adfdb2f5acb899d66c85914195bb7d4', 'seq': 1}

## Run log

- # Phase 10 loop — run_id=run  started 2026-09-04T13:57:30+00:00
- [gen 0] liquidity -> reject  (fresh fold: VAL_B oriented RankIC=nan (t=None) did not hold)
- [gen 1] momentum -> reject  (fresh fold: VAL_B oriented RankIC=nan (t=None) did not hold)
- [portfolio] {"status": "insufficient", "n_accepted": 0, "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"}