# Phase 10 loop report — run_id=live_fixed

- status: **stopped_early** (stop_after_generation hook)
- generations run: 1
- accepted cards: 0
- trials (counts_as_trial=1): 6
- holdout peeks used: 0
- final T_STAT_BAR: 3.0   final MIN_MARGINAL_IC: 0.01
- state digest: `sha256:781cc2698dba5da6af70ccc214965fdb73dec3d89d9857bfce22450045f8110a`

## Per-generation

| gen | family | verdict | variants | forced | redteam | reject reason |
|---|---|---|---|---|---|---|
| 0 | liquidity | reject | 4 | False | None | Gate B statistics: statistics: deflated_sharpe=0.599 < 0.95 (t=3.84, E[max SR]-a |

## Pre-registration log (sign hash stored before any backtest)

- `th_live_fixed_g0` sha256:91747499fd3b0d5a… — before_backtest

## Portfolio (post-process, off-graph)

```json
{
  "status": "insufficient",
  "n_accepted": 0,
  "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"
}
```

## Event log tail

- {'kind': 'prereg_stored', 'thesis_id': 'th_live_fixed_g0', 'hash': 'sha256:91747499fd3b0d5a699fd88ccbc605685a427441536678a44a69a603bea8bd53', 'seq': 0}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_fixed_g0', 'has_token': False, 'seq': 1}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_fixed_g0', 'has_token': False, 'seq': 2}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_fixed_g0', 'has_token': False, 'seq': 3}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_fixed_g0', 'has_token': False, 'seq': 4}
- {'kind': 'promote', 'thesis_id': 'th_live_fixed_g0', 'seq': 5}
- {'kind': 'backtest', 'split': 'val_b', 'thesis_id': 'th_live_fixed_g0', 'has_token': False, 'seq': 6}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_fixed_g0', 'has_token': False, 'seq': 7}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_live_fixed_g0', 'has_token': False, 'seq': 8}
- {'kind': 'gate_step', 'step': 'novelty', 'thesis_id': 'th_live_fixed_g0', 'seq': 9}
- {'kind': 'gate_step', 'step': 'statistics', 'thesis_id': 'th_live_fixed_g0', 'seq': 10}

## Run log

- # Phase 10 loop — run_id=live_fixed  started 2026-09-04T13:45:27+00:00
- [gen 0] liquidity -> reject  (Gate B statistics: statistics: deflated_sharpe=0.599 < 0.95 (t=3.84, E[max SR]-adjusted))
- [portfolio] {"status": "insufficient", "n_accepted": 0, "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"}