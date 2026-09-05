# Phase 10 loop report — run_id=p11_good_8

- status: **completed** (reached generation cap)
- generations run: 1
- accepted cards: 1
- trials (counts_as_trial=1): 28
- holdout peeks used: 4
- final T_STAT_BAR: 3.0   final MIN_MARGINAL_IC: 0.01
- state digest: `sha256:5f0a835a53c20b1c251463ce24116594ff6490de8093fd937a7fc485e5d21a35`

## Per-generation

| gen | family | verdict | variants | forced | redteam | reject reason |
|---|---|---|---|---|---|---|
| 0 | value_proxy | accept | 1 | False | survives |  |

## Pre-registration log (sign hash stored before any backtest)

- `th_p11_good_8_g0` sha256:e57580b3f572786a… — before_backtest

## Portfolio (post-process, off-graph)

```json
{
  "status": "insufficient",
  "n_accepted": 1,
  "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"
}
```

## Event log tail

- {'kind': 'prereg_stored', 'thesis_id': 'th_p11_good_8_g0', 'hash': 'sha256:e57580b3f572786aac2038032307f26dfd4bd3fbcc8c4cae0b932d0c440d155c', 'seq': 0}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 1}
- {'kind': 'promote', 'thesis_id': 'th_p11_good_8_g0', 'seq': 2}
- {'kind': 'backtest', 'split': 'val_b', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 3}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 4}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 5}
- {'kind': 'gate_step', 'step': 'novelty', 'thesis_id': 'th_p11_good_8_g0', 'seq': 6}
- {'kind': 'gate_step', 'step': 'statistics', 'thesis_id': 'th_p11_good_8_g0', 'seq': 7}
- {'kind': 'backtest', 'split': 'holdout', 'thesis_id': 'th_p11_good_8_g0', 'has_token': True, 'seq': 8}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 9}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 10}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 11}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 12}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 13}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 14}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 15}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 16}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 17}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 18}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 19}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 20}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 21}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 22}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 23}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 24}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 25}
- {'kind': 'backtest', 'split': 'val_a', 'thesis_id': 'th_p11_good_8_g0', 'has_token': False, 'seq': 26}

## Run log

- # Phase 10 loop — run_id=p11_good_8  started 2026-09-04T19:14:41+00:00
- [accept] card_p11_good_8_g0_acc  formula=mul(-1, ts_std(returns, 42))
- [gen 0] value_proxy -> accept
- [portfolio] {"status": "insufficient", "n_accepted": 1, "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"}