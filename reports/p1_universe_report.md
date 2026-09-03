# Phase 1 — Universe construction (liquidity-defined)

## 0. Naming — use this wording everywhere

> **"The 200 most liquid Indian equities, reconstructed point-in-time from NSE daily bhavcopy."**

**Not "NIFTY 200."** The index label was never load-bearing for a cross-sectional ranking exercise; a coherent, survivorship-free, point-in-time universe reproducible from primary source is the stronger claim.

## 1. Why the supplied index file is not used for selection

`nifty200_2015-01-01_to_2026-09-01.csv` was verified unusable as an index:

- **80 of today's 200 NIFTY 200 constituents never appear in it** — RELIANCE, TCS, SBIN, MARUTI, TATASTEEL, TATAMOTORS, SUNPHARMA, TITAN, ULTRACEMCO, ONGC among them.
- **All 80 have zero inclusion/exclusion events** — the signature of a change-log replayed onto an incomplete base seed. Permanent heavyweights were never added; each row was padded back to 200 with mid-caps.
- **21 of 36 rebalances are internally inconsistent** (declared inclusions/exclusions do not reconcile against the `symbols` deltas).
- Replay cannot repair it: forward replay needs a correct 2015 base (ours is broken); backward replay needs a complete change log (ours is 21/36 inconsistent). NSE publishes only the current list.

The file is read here **only** for the §5 overlap diagnostic — never for selection.

## 2. THE RULE (what we do instead)

On the **last trading day of each month**, using only data available that day:

1. Take every `SERIES == 'EQ'` stock present in that day's bhavcopy (`BE` kept as well: **True**).
2. Require **>= 252 trading days** of prior history.
3. Rank by **median daily turnover (`close_raw x volume_raw`) over the trailing 63 trading days** — trailing only, never centred.
4. The **top 200** are the universe for the following month, forward-filled to daily.

Survivorship-free by construction: selection uses only trailing information as of date *D*; a stock exits automatically when it stops appearing in the daily files — no delisting-date list, no judgement call.

## 3. Inputs actually used

- Price panel: `data/prices/ohlcv.parquet (4,988,593 rows)`
  (real P2 output)

## 4. Monthly selection results

- Month-end selections: **144**
- Months at exactly 200 members: **132**
- Monthly membership turnover: mean **4.75%**, range 2.0–9.5% (expected ~2–5%)
- Union of every symbol ever selected: **581**

### universe_stats.parquet (head + tail)

| date | n_members | median_turnover | turnover_cutoff_200 |
|---|---|---|---|
| 2014-01-31 | 0 | nan | nan |
| 2014-02-28 | 0 | nan | nan |
| 2014-03-31 | 0 | nan | nan |
| 2014-04-30 | 0 | nan | nan |
| 2014-05-30 | 0 | nan | nan |
| 2014-06-30 | 0 | nan | nan |
| 2025-07-31 | 200 | 1.713e+09 | 9.328e+08 |
| 2025-08-29 | 200 | 1.609e+09 | 8.341e+08 |
| 2025-09-30 | 200 | 1.528e+09 | 7.774e+08 |
| 2025-10-31 | 200 | 1.547e+09 | 7.469e+08 |
| 2025-11-28 | 200 | 1.647e+09 | 7.530e+08 |
| 2025-12-31 | 200 | 1.557e+09 | 7.253e+08 |

The rank-200 turnover cutoff is the liquidity floor; it should drift upward over the sample.

### liquidity_ranks.parquet

Per-symbol trailing-turnover ranking, one row per (month_end, symbol) among each month's top-200 picks (`month_end · symbol · liquidity_rank · trailing_turnover`; rank 1 = most liquid). This is the same ranking that fixes `turnover_cutoff_200` above; **Phase 9's red-team reads it** to identify the names ranked 150–200 that month (`universe_edge` test) instead of recomputing.

## 5. Index-overlap diagnostic (context only — never a selection input)

- Our union: 581 symbols; our current-day universe: 200.
- Supplied CSV union: 315. In both: 253 (**80.3%** of the CSV's names).
  - sample only in CSV: ['ABREL', 'AKZOINDIA', 'ALSTOMT&D', 'AMARAJA', 'ARE&M', 'ASAHIINDIA', 'BALMLAWRIE', 'BASF', 'BIRLACORPN', 'BLUEDART', 'CCL', 'CHOLAHLDNG', 'CLEAN', 'CMC', 'CONSOFINVT']
  - sample only in ours: ['360ONE', '8KMILES', 'AARTIDRUGS', 'ABAN', 'ABFRL', 'ABIRLANUVO', 'ADANIGAS', 'ADANIGREEN', 'ADANIPORTS', 'ADANITRANS', 'AFFLE', 'ALBK', 'ALKYLAMINE', 'ALOKINDS', 'AMARAJABAT']
- NSE current `ind_nifty200list.csv`: not available (NSE publishes only the current list; file absent)

## 6. Acceptance checks

### TEST A — survivorship canaries

| symbol | in union | first in | last in |
|---|---|---|---|
| DHFL | True | 2015-02-02 | 2019-12-31 |
| RCOM | True | 2015-02-02 | 2019-05-31 |
| JPASSOCIAT | True | 2015-02-02 | 2019-01-31 |
| YESBANK | True | 2015-02-02 | 2025-12-31 |
| SUZLON | True | 2015-02-02 | 2025-12-31 |
| IDEA | True | 2015-02-02 | 2025-12-31 |
### TEST B — flat coverage

Mean `n_members` per year: 2015: 200.0, 2016: 200.0, 2017: 200.0, 2018: 200.0, 2019: 200.0, 2020: 200.0, 2021: 200.0, 2022: 200.0, 2023: 200.0, 2024: 200.0, 2025: 200.0

Linear trend slope: **2.6214e-17** members/day (0.000/year). Near-zero => no survivorship slope.

### TEST C — no look-ahead in selection

- Recomputed with data only up to **2020-01-01**; compared **72** prior month-ends.
- Bit-identical: **True**

### Heavyweights present

| symbol | days in universe | % of history |
|---|---|---|
| RELIANCE | 2697 | 100.0 |
| TCS | 2697 | 100.0 |
| SBIN | 2697 | 100.0 |
| TATASTEEL | 2697 | 100.0 |
| MARUTI | 2697 | 100.0 |
| ONGC | 2697 | 100.0 |
## 7. Decision log

- loaded P2 price panel: data/prices/ohlcv.parquet (4,988,593 rows) — cols ['date', 'symbol', 'isin', 'close_raw', 'volume_raw', 'series'] only (memory)
- SERIES filter ['BE', 'EQ']: kept 4,988,593 / 4,988,593 rows
- daily panel: 2697 trading days (2015-02-02..2025-12-31) x 586 ever-selected symbols; forward-filled from each monthly selection
- a stock that stops trading mid-month keeps in_universe==True until the next selection; it has no price rows so P3's join drops it
- liquidity_ranks.parquet: 26,395 rows (132 months x up to 200 names), per-symbol trailing-turnover rank read by P9 universe_edge; dropped 5 name(s) only in the unapplied final selection: ['CUPID', 'GMRAIRPORT', 'HBLENGINE', 'NEULANDLAB', 'VMM']
