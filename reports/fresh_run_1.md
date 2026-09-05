# Phase 10 loop report — run_id=fresh_run_1

- status: **completed** (reached generation cap)
- generations run: 1
- accepted cards: 0
- trials (counts_as_trial=1): 7
- holdout peeks used: 0
- final T_STAT_BAR: 3.0   final MIN_MARGINAL_IC: 0.01
- state digest: `sha256:cf38631733bd316b24132f4fcdef952f15c479d4878a68ca1701a61c2a27cf07`

## Per-generation

| gen | family | verdict | variants | forced | redteam | reject reason |
|---|---|---|---|---|---|---|
| 0 | momentum | reject | 1 | False | None | fresh fold: VAL_B oriented RankIC=-0.0025 (t=-0.2211727186821474) did not hold |

## Pre-registration log (sign hash stored before any backtest)

- `th_fresh_run_1_g0` sha256:0b19416f42fb5405… — before_backtest

## Portfolio (post-process, off-graph)

```json
{
  "status": "insufficient",
  "n_accepted": 0,
  "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"
}
```

## Event log tail

- {'kind': 'prereg_stored', 'thesis_id': 'th_fresh_run_1_g0', 'hash': 'sha256:0b19416f42fb5405658a4acb0e0625e0647fb03778f09cfa1b21e2f79c45547b', 'seq': 0}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_fresh_run_1_g0', 'has_token': False, 'seq': 1}
- {'kind': 'promote', 'thesis_id': 'th_fresh_run_1_g0', 'seq': 2}
- {'kind': 'backtest', 'split': 'val_b', 'thesis_id': 'th_fresh_run_1_g0', 'has_token': False, 'seq': 3}

## Run log

- # Phase 10 loop — run_id=fresh_run_1  started 2026-09-04T17:03:07+00:00
- [gen 0] momentum -> reject  (fresh fold: VAL_B oriented RankIC=-0.0025 (t=-0.2211727186821474) did not hold)
- [portfolio] {"status": "insufficient", "n_accepted": 0, "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"}