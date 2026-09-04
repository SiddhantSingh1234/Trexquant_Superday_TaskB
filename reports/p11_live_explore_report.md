# Phase 10 loop report — run_id=live_explore

- status: **stopped_early** (3 consecutive generations added < 0.001 novelty-adjusted marginal IC)
- generations run: 3
- accepted cards: 0
- trials (counts_as_trial=1): 30
- holdout peeks used: 0
- final T_STAT_BAR: 3.0   final MIN_MARGINAL_IC: 0.01
- state digest: `sha256:e73eddb62c3002ec6b475098df9d77862ba85f3d5665aeb4e760d5c02db48e60`

## Per-generation

| gen | family | verdict | variants | forced | redteam | reject reason |
|---|---|---|---|---|---|---|
| 0 | liquidity | reject | 6 | False | None | fresh fold: VAL_B oriented RankIC=-0.0097 (t=1.7283776172771774) did not hold |
| 1 | liquidity | reject | 20 | True | None | fresh fold: VAL_B oriented RankIC=0.0031 (t=0.38231040280887) did not hold |
| 2 | liquidity | reject | 4 | False | None | fresh fold: VAL_B oriented RankIC=-0.0017 (t=0.29367558711810005) did not hold |

## Pre-registration log (sign hash stored before any backtest)

- `th_live_explore_g0` sha256:9fd5cf5305bd2c77… — before_backtest
- `th_live_explore_g1` sha256:f27ec8248e02bd9e… — before_backtest
- `th_live_explore_g2` sha256:47841ef031f04fed… — before_backtest

## Portfolio (post-process, off-graph)

```json
{
  "status": "insufficient",
  "n_accepted": 0,
  "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"
}
```

## Event log tail

- {'kind': 'prereg_stored', 'thesis_id': 'th_live_explore_g0', 'hash': 'sha256:9fd5cf5305bd2c77078af116aec11bc92e44c4199a1a3be50efe13c9c0608f43', 'seq': 0}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g0', 'has_token': False, 'seq': 1}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g0', 'has_token': False, 'seq': 2}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g0', 'has_token': False, 'seq': 3}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g0', 'has_token': False, 'seq': 4}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g0', 'has_token': False, 'seq': 5}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g0', 'has_token': False, 'seq': 6}
- {'kind': 'promote', 'thesis_id': 'th_live_explore_g0', 'seq': 7}
- {'kind': 'backtest', 'split': 'val_b', 'thesis_id': 'th_live_explore_g0', 'has_token': False, 'seq': 8}
- {'kind': 'prereg_stored', 'thesis_id': 'th_live_explore_g1', 'hash': 'sha256:f27ec8248e02bd9e3d68c92686e6459045dcdf72f964f6ca88f43329394c011f', 'seq': 9}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 10}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 11}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 12}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 13}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 14}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 15}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 16}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 17}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 18}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 19}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 20}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 21}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 22}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 23}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 24}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 25}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 26}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 27}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 28}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 29}
- {'kind': 'promote', 'thesis_id': 'th_live_explore_g1', 'seq': 30}
- {'kind': 'backtest', 'split': 'val_b', 'thesis_id': 'th_live_explore_g1', 'has_token': False, 'seq': 31}
- {'kind': 'prereg_stored', 'thesis_id': 'th_live_explore_g2', 'hash': 'sha256:47841ef031f04fed0ce60954697e684a3d778379deb65b5dd292fd591b4e82e1', 'seq': 32}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g2', 'has_token': False, 'seq': 33}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g2', 'has_token': False, 'seq': 34}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g2', 'has_token': False, 'seq': 35}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_explore_g2', 'has_token': False, 'seq': 36}
- {'kind': 'promote', 'thesis_id': 'th_live_explore_g2', 'seq': 37}
- {'kind': 'backtest', 'split': 'val_b', 'thesis_id': 'th_live_explore_g2', 'has_token': False, 'seq': 38}

## Run log

- # Phase 10 loop — run_id=live_explore  started 2026-09-04T09:17:22+00:00
- [gen 0] liquidity -> reject  (fresh fold: VAL_B oriented RankIC=-0.0097 (t=1.7283776172771774) did not hold)
- [cap] thesis th_live_explore_g1 hit the 20-variant cap; best oriented RankIC=0.0017698383358797185
- [gen 1] liquidity -> reject  (fresh fold: VAL_B oriented RankIC=0.0031 (t=0.38231040280887) did not hold)
- [gen 2] liquidity -> reject  (fresh fold: VAL_B oriented RankIC=-0.0017 (t=0.29367558711810005) did not hold)
- [portfolio] {"status": "insufficient", "n_accepted": 0, "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"}