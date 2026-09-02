# Phase 3 — Feature panel, labels, splits

- Input source: **real (data/prices/*, data/universe/membership.parquet)**
- `features.parquet`: **539,400 rows**, 581 symbols, 2697 trading days (2015-02-02 … 2025-12-31)
- `labels.parquet`: **539,400 rows**

## Timing contract (obeyed exactly)

> features use data available *before* the trade -> **trade at the *t+1* open** -> return earned ***t+1* open to *t+2* open**.

`fwd_ret_h = open[t+1+h] / open[t+1] - 1`, then cross-sectionally demeaned within the in-universe set each day; the demeaned value **is the label**. Every feature window is strictly trailing and uses only rows dated <= *t* (`mom_21` / `mom_126` additionally skip the most recent day / 21 days).

## Per-field availability applied

| Field | Knowable at | Lag | Handling |
|---|---|---|---|
| OHLCV + derived (mom, rev, vol, beta, amihud, turnover, dist_52wh, max_ret) | day *t* 15:30 | 0 | trailing windows on the common NSE calendar |
| `delivery_pct` | day *t* ~19:00 (pre *t+1* open) | 0 | joined on date *t*; NaN before first available date |
| `size_proxy` | day *t* (trailing turnover) | 0 | joined on date *t* from P2 |
| `sector` | static — **NOT point-in-time** | 0 | see caveat below |
| `in_universe` | effective date, applied 1–3 d late | 0 | from P1 membership (already conservative) |

## `delivery_pct` availability decision

- Source: data/prices/delivery.parquet
- **First available date: 2019-10-01**. Before it, `delivery_pct` is left **NaN** — not fabricated, not back-filled (PRE_BUILD_TASKS.md T1: `sec_bhavdata_full` starts 2019-09-30; P2 measured the first usable `DELIV_PER` at 2019-10-01).
- Non-NaN share of `delivery_pct` in the masked panel: **57.1%** (0% of TRAIN, partial VAL_A, full VAL_B/HOLDOUT — consistent with T1).

## Sector mapping — caveat (disclosed, not hidden)

- 407 of 581 symbols classified by **ISIN join** against NSE's current `ind_niftytotalmarket_list.csv`, 36 more by symbol join, **138 by hand** (delisted / renamed names the current list cannot contain), 0 unresolved.
- NSE file present at build: **True**. Industries used: **22 / 22** (NSE's official names, verbatim).
- ⚠️ **The classification is current, not point-in-time.** A company reclassified since 2015 carries today's label throughout its history. Acceptable because `sector` drives only *optional* sector-neutralization and red-team test 7 — never a standalone scored feature.
- Hand-classified sample: ['8KMILES', 'ABAN', 'ABIRLANUVO', 'ALBK', 'AMTEKAUTO', 'AMTEKINDIA', 'ANDHRABANK', 'ANGELBRKG', 'APEX', 'APTECHT', 'ARCOTECH', 'ASTRAZEN', 'ATULAUTO', 'BCG', 'BEPL', 'BFUTILITIE', 'BHARATFIN', 'BLISSGVS', 'BODALCHEM', 'BOMDYEING']
- Judgement calls (business spans two NSE buckets — chosen label defensible, not unique):
  - `ABIRLANUVO`: Diversified — was telecom+fashion+financial holdco (→ merged into GRASIM)
  - `KESORAMIND`: Diversified — cement + tyres + rayon; could be Construction Materials
  - `RIIL`: Construction — Reliance Industrial Infrastructure leases pipeline infra; could be Services
  - `RELINFRA`: Power — power distribution + EPC; could be Utilities or Construction
  - `BCG`: Media Entertainment & Publication — Brightcom ad-tech; could be Information Technology
  - `ONMOBILE`: Telecommunication — telecom value-added services; could be Information Technology
  - `MIRZAINT`: Consumer Durables — footwear (Red Tape); NSE files footwear under Consumer Durables
  - `VAKRANGEE`: Consumer Services — e-governance / retail kiosks; could be Information Technology
  - `JISLJALEQS`: Capital Goods — Jain Irrigation micro-irrigation systems + agri-processing
  - `GOACARBON`: Chemicals — calcined petroleum coke; could be Oil Gas & Consumable Fuels
  - `MONSANTO`: Chemicals — agrochemicals + hybrid seeds; could be FMCG
  - `RUSHIL`: Construction Materials — decorative laminates / MDF boards

## Assertion suite (step 6)

- Min cross-section after 2016-01-01: **200** (spec floor 100). Days below 100: **0**
- `dist_52wh` max value: **0.00e+00** (<= 0 required) -> OK
- `vol_21` min value: **0.0037** (> 0 required) -> OK
- Duplicate (date, symbol): features **0**, labels **0**
- NaN label on in-universe **and traded** rows, well inside the sample (i.e. the stock stopped trading within the forward window — a legitimate NaN, kept not filled):
  - `fwd_ret_1`: 96 rows
  - `fwd_ret_2`: 142 rows
  - `fwd_ret_3`: 188 rows
  - `fwd_ret_5`: 275 rows
  - `fwd_ret_10`: 484 rows
  - `fwd_ret_21`: 933 rows
- Feature non-NaN coverage in the masked panel:
  - `mom_21`: 99.9%
  - `mom_126`: 100.0%
  - `rev_5`: 99.9%
  - `vol_21`: 99.9%
  - `beta_63`: 97.6%
  - `amihud_21`: 99.9%
  - `turnover_21`: 99.9%
  - `dist_52wh`: 99.8%
  - `max_ret_21`: 99.9%
  - `delivery_pct`: 57.1%
  - `size_proxy`: 99.9%

## Extreme daily returns (> 50%) — flagged, NOT winsorized, NOT dropped

- Flagged on the masked universe panel: **15**
  - `demerger` (P2 policy is *not* to adjust demergers — expected): **9**
  - `unadjusted_split` (**P2 corporate-action gap** — split/bonus CA near the date, or raw close jumps by a clean split fraction; see handoff §6): **0**
  - `genuine` (no CA, real distress move — e.g. JETAIRWAYS grounding): **6**
- Kept verbatim: Indian mid-caps genuinely move like this and clipping them would distort `max_ret_21`, which exists to capture exactly that.

| date | symbol | daily ret | category |
|---|---|---|---|
| 2019-06-20 | JETAIRWAYS | +89.9% | genuine |
| 2015-06-03 | ADANIENT | -82.8% | demerger |
| 2017-05-25 | SINTEX | -75.2% | demerger |
| 2016-03-15 | CROMPGREAV | -71.7% | demerger |
| 2018-09-28 | INFIBEAM | -70.8% | genuine |
| 2015-06-12 | MASTEK | -66.0% | demerger |
| 2018-11-28 | ARVIND | -65.1% | demerger |
| 2020-03-17 | YESBANK | +58.1% | genuine |
| 2016-01-20 | ABIRLANUVO | -57.3% | demerger |
| 2015-10-01 | IDFC | -57.2% | demerger |
| 2020-03-04 | TATACHEM | -56.5% | demerger |
| 2018-05-17 | RCOM | +56.2% | genuine |
| 2020-03-06 | YESBANK | -56.1% | genuine |
| 2019-10-11 | CENTURYTEX | -55.4% | demerger |
| 2015-09-11 | AMTEKAUTO | +53.9% | genuine |

## Step 7 — the look-ahead self-test (the most important test)

_Computed on non-HOLDOUT dates only — HOLDOUT is sealed._

### (a) shift the whole feature panel one day — a known factor's IC must change

- **rev_5 (primary — a genuine, fast signal)** RankIC vs `fwd_ret_1_demeaned`: **+0.02373**  → forward-shift 1d: **+0.00947** (abs Δ 0.01426, rel Δ 60%)  → backward-shift 1d: **-0.34054**
- **mom_21** RankIC vs `fwd_ret_1_demeaned`: **-0.00327**  → forward-shift 1d: **+0.00140** (abs Δ 0.00467, rel Δ 143%)  → backward-shift 1d: **-0.01154**
- **mom_126** RankIC vs `fwd_ret_1_demeaned`: **+0.00857**  → forward-shift 1d: **+0.00817** (abs Δ 0.00040, rel Δ 5%)  → backward-shift 1d: **+0.00843**

- **Primary-factor IC materially changes under the forward shift: True** → the pipeline is not time-symmetric anywhere (no leak). (`mom_126` is a 126-day window so a 1-day shift barely moves its *values*; `rev_5` is the decisive fast-signal test.)

### (b) deliberately leaky feature (fwd_ret_1 predicting itself)

- RankIC: **+1.00000** — |IC| > 0.9 required → **True**. The measurement machinery *can* detect leakage, which is what makes the negative result on real features meaningful.

### (c) that leaky feature shifted forward one day

- RankIC: **-0.06046** — collapses toward 0 (< half of |leaky IC|): **True**.

## splits.json (Section 0.4, verbatim)

```json
{
 "warmup": [
  "2014-01-01",
  "2014-12-31"
 ],
 "train": [
  "2015-01-01",
  "2017-12-31"
 ],
 "val_a": [
  "2018-01-01",
  "2021-06-30"
 ],
 "val_b": [
  "2021-07-01",
  "2022-06-30"
 ],
 "holdout": [
  "2022-07-01",
  "2025-12-31"
 ]
}
```

## Decision log

- loaded real P2 ohlcv.parquet (4,988,593 rows, cols=['date', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'close_raw', 'volume_raw', 'isin']) and P1 membership.parquet (1,580,442 rows)
- universe union: 581 symbols ever in-universe
- feature windows are trailing on the COMMON NSE trading calendar (wide date x symbol panel), not each symbol's own row count — every stock shares the same 21/63/252-day window; documented as a judgement call
- validate_features / validate_labels both pass on the masked panel
- fwd_ret_1: 96 in-universe+traded rows have NaN label well inside the sample (stock stopped trading within the forward window) — kept, not filled
- fwd_ret_2: 142 in-universe+traded rows have NaN label well inside the sample (stock stopped trading within the forward window) — kept, not filled
- fwd_ret_3: 188 in-universe+traded rows have NaN label well inside the sample (stock stopped trading within the forward window) — kept, not filled
- fwd_ret_5: 275 in-universe+traded rows have NaN label well inside the sample (stock stopped trading within the forward window) — kept, not filled
- fwd_ret_10: 484 in-universe+traded rows have NaN label well inside the sample (stock stopped trading within the forward window) — kept, not filled
- fwd_ret_21: 933 in-universe+traded rows have NaN label well inside the sample (stock stopped trading within the forward window) — kept, not filled
