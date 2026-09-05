# Phase 10 loop report — run_id=run

- status: **completed** (reached generation cap)
- generations run: 1
- accepted cards: 0
- trials (counts_as_trial=1): 6
- holdout peeks used: 0
- final T_STAT_BAR: 3.0   final MIN_MARGINAL_IC: 0.01
- state digest: `sha256:2295308e40d07bcd1c1815003f4d705b78529fed1b643bb5de81f64ea9387c3d`

## Per-generation

| gen | family | verdict | variants | forced | redteam | reject reason |
|---|---|---|---|---|---|---|
| 0 | microstructure | reject | 0 | False | None | fresh fold: VAL_B oriented RankIC=nan (t=None) did not hold |

## Pre-registration log (sign hash stored before any backtest)

- `th_run_g0` sha256:fb1cdd03c77cded8… — before_backtest

## Portfolio (post-process, off-graph)

```json
{
  "status": "insufficient",
  "n_accepted": 0,
  "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"
}
```

## Event log tail

- {'kind': 'prereg_stored', 'thesis_id': 'th_run_g0', 'hash': 'sha256:fb1cdd03c77cded8fd8124a2e5fb3044b1bb979af7ee71b42ca50f1cbd785365', 'seq': 0}

## Run log

- # Phase 10 loop — run_id=run  started 2026-09-04T16:47:44+00:00
- [gen 0] microstructure -> reject  (fresh fold: VAL_B oriented RankIC=nan (t=None) did not hold)
- [portfolio] {"status": "insufficient", "n_accepted": 0, "note": "fewer than 2 accepted cards \u2014 no combination performed (Phase 11 demonstrates the mechanism on a synthetic set)"}