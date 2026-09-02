# Phase 2 — Price data coverage report

## Source & window

- Window: **2014-01-01 .. 2025-12-31** (2026+ reserved for live-forward; not downloaded).
- Legacy bhavcopy zip through 2019-09-27; `sec_bhavdata_full` from 2019-09-30.
- SERIES kept: **EQ + BE** — `BE` (trade-to-trade) is retained deliberately: a stock demoted to `BE` is a distress signal, and dropping it would reintroduce a mild survivorship bias.
- **`sharesOutstanding` was NOT used** anywhere. `size_proxy` is `log(trailing-63d median of close_raw*volume_raw)` — a point-in-time, leak-free stand-in for market cap.

## Panel size

- Rows: **4,988,593**  |  distinct symbols: **3178**  |  distinct ISINs: **3116**
- Date span: 2014-01-01 .. 2025-12-31 (2961 trading days)
- Symbols with no ISIN from any source (keyed `UNK_<symbol>`): **202**

## TEST A — survivorship canaries

```
    symbol  n_days      first       last
      DHFL    1834 2014-01-01 2021-06-11
      RCOM    2665 2014-01-01 2025-12-31
JPASSOCIAT    2750 2014-01-01 2025-12-29
   YESBANK    2961 2014-01-01 2025-12-31
    SUZLON    2961 2014-01-01 2025-12-31
      IDEA    2961 2014-01-01 2025-12-31
 COX&KINGS    1470 2014-01-01 2019-12-24
     CAIRN     813 2014-01-01 2017-04-25
```

_CAIRN should be absent after 2017-04 (merged into Vedanta) — that absence validates the archive is genuinely point-in-time._

## TEST B — flat coverage (decisive diagnostic)

P2's true panel is `members(D) ∩ traded(D)`, but P1's membership does not exist yet (P1 runs after P2). The decisive curve here is a faithful **universe proxy**: on each month-end, the top-200 EQ names by trailing-63d median turnover among those with ≥252d history that traded that day — P1's exact RULE. A survivorship-biased panel cannot hold this flat at 200 in the early years; a correct one does.

- **Universe-proxy trend: +0.797 names/year** (slope +2.18e-03/day)
- Universe-proxy mean 2016: **200.0**, 2024: **200.0**, min year: **183.8**
- Universe-proxy per-year mean: {2015: 183.8, 2016: 200.0, 2017: 200.0, 2018: 200.0, 2019: 200.0, 2020: 200.0, 2021: 200.0, 2022: 200.0, 2023: 200.0, 2024: 200.0, 2025: 200.0}
- _Context_ — whole EQ+BE market listing count trend +67.5/year (2016≈1496, 2024≈2018). This slopes up because the NSE market genuinely grew; it is **not** the survivorship test.
- Plot: `p2_coverage_plot.png` (top panel = decisive, bottom = context)
- **An upward slope in the universe-proxy curve means survivorship bias remains — HARD STOP.** See handoff for the pass/fail call.

## Heavyweights (liquidity sanity)

- Day counts: {'RELIANCE': 2961, 'TCS': 2961, 'SBIN': 2961, 'TATASTEEL': 2961, 'MARUTI': 2961, 'ONGC': 2961, 'INFY': 2961, 'HDFCBANK': 2961}
- These are among the most liquid names in India; near-zero counts would indicate a parsing/turnover bug.

## Corporate actions & adjustment

- Events parsed: 26331  |  adjustable (split/bonus): 854  |  demergers flagged (NOT adjusted): 149
- Dividends are NOT adjusted (≈1% distortion, second-order at our horizons). Splits/bonuses (50–90% distortion) are adjusted.

<details><summary>Flagged demergers/mergers (disclosed, unadjusted)</summary>

```
    symbol    ex_date                                  raw_subject
    FELDVR 2016-05-11                        Scheme Of Arrangement
  RELIANCE 2023-07-20                                     Demerger
   SIEMENS 2025-04-07                                     Demerger
 COX&KINGS 2018-10-25                           Scheme Of Demerger
RELCAPITAL 2017-09-05                        Scheme Of Arrangement
  MANAKSIA 2014-12-04                        Scheme Of Arrangement
     GOKUL 2015-09-16 Annual General Meeting/Scheme Of Arrangement
IFGLREFRAC 2017-09-14                       Scheme Of Amalgamation
   BOROLTD 2023-12-05                                     Demerger
HINDUNILVR 2025-12-05                                     Demerger
    ARVIND 2015-05-28                        Scheme Of Arrangement
    ARVIND 2018-11-28                                     Demerger
       PTL 2017-03-27                        Scheme Of Arrangement
DHAMPURSUG 2022-05-13                                     Demerger
      IDFC 2015-09-29                                     Demerger
      IDFC 2015-10-01                                     Demerger
    GRASIM 2017-07-19                        Scheme Of Arrangement
 VAKRANGEE 2023-06-15                                     Demerger
     ABREL 2019-10-11                                     Demerger
    SANOFI 2024-06-13                                     Demerger
   CGPOWER 2016-03-15                        Scheme Of Arrangement
ABIRLANUVO 2016-01-20                        Scheme Of Arrangement
KESORAMIND 2019-12-24                                     Demerger
KESORAMIND 2025-03-10                                     Demerger
  MANDHANA 2016-09-22                           Scheme Of Demerger
   STLTECH 2025-04-24                                     Demerger
  TATACHEM 2020-03-04                                     Demerger
   TVSHLTD 2023-08-24                                     Demerger
    3PLAND 2016-02-11       Scheme Of Arrangement & Reconstruction
       SCI 2023-03-31                                     Demerger
  MHLXMIRU 2024-04-19                                     Demerger
       ABB 2019-12-20                                     Demerger
 IBULLSLTD 2022-09-01                                     Demerger
 AURIONPRO 2018-08-14                           Scheme Of Demerger
       PEL 2022-08-30                                     Demerger
  TATACOMM 2019-09-17                                     Demerger
       ITC 2025-01-06                                     Demerger
      TMPV 2025-10-14                                     Demerger
   NIITLTD 2023-06-08                                     Demerger
      MFSL 2016-01-27                        Scheme Of Arrangement
```

</details>

## Extreme daily returns (|ret| > 50%)

- Total: 453  |  not near a known corporate action: 415
- Not auto-dropped and not winsorized (per spec) — Indian mid-caps genuinely move like this; P3 flags them for review.

<details><summary>First 50 unexplained</summary>

```
      date     symbol       ret  near_corp_action
2023-01-23     4THDIM -0.795975             False
2016-10-10    8KMILES -0.592150             False
2020-09-07    8KMILES -0.593398             False
2015-09-16  AEGISCHEM -0.901056             False
2025-04-25     AMIORG -0.514279             False
2015-09-11  AMTEKAUTO  0.539344             False
2023-10-16       ASMS  1.046875             False
2024-12-27 ATLASCYCLE  0.759309             False
2018-10-24   ATNINTER  1.000000             False
2019-01-28   ATNINTER  1.000000             False
2019-02-11   ATNINTER  1.000000             False
2019-03-11   ATNINTER  1.000000             False
2019-04-08   ATNINTER  1.000000             False
2019-04-15   ATNINTER  1.000000             False
2019-06-24   ATNINTER  1.000000             False
2019-07-12   ATNINTER  1.000000             False
2020-03-17   ATNINTER  1.000000             False
2020-03-30   ATNINTER  1.000000             False
2020-04-15   ATNINTER  0.666667             False
2019-07-29  BINANIIND -0.574675             False
2014-03-12   BIRLACOT  1.000000             False
2014-03-18   BIRLACOT  1.000000             False
2014-03-20   BIRLACOT  1.000000             False
2014-03-27   BIRLACOT  1.000000             False
2014-03-31   BIRLACOT  1.000000             False
2015-02-11   BIRLACOT  1.000000             False
2015-02-19   BIRLACOT  1.000000             False
2015-02-24   BIRLACOT  1.000000             False
2015-03-02   BIRLACOT  1.000000             False
2015-03-04   BIRLACOT  1.000000             False
2015-03-12   BIRLACOT  1.000000             False
2015-03-16   BIRLACOT  1.000000             False
2015-03-20   BIRLACOT  1.000000             False
2015-03-24   BIRLACOT  1.000000             False
2015-03-30   BIRLACOT  1.000000             False
2015-06-22   BIRLACOT  1.000000             False
2015-06-25   BIRLACOT  1.000000             False
2015-07-03   BIRLACOT  1.000000             False
2015-07-07   BIRLACOT  1.000000             False
2015-07-16   BIRLACOT  1.000000             False
2015-07-22   BIRLACOT  1.000000             False
2015-07-24   BIRLACOT  1.000000             False
2015-07-30   BIRLACOT  1.000000             False
2015-08-04   BIRLACOT  1.000000             False
2015-08-07   BIRLACOT  1.000000             False
2015-08-11   BIRLACOT  1.000000             False
2015-08-13   BIRLACOT  1.000000             False
2015-11-13   BIRLACOT  1.000000             False
2015-11-20   BIRLACOT  1.000000             False
2015-11-24   BIRLACOT  1.000000             False
```

</details>

## yfinance cross-check (validation only, not a source)

- 30 large caps: median corr **0.9963**, 25/30 above 0.99
- Per-name: {'RELIANCE': 0.9955, 'ICICIBANK': 0.9881, 'HDFCBANK': 0.998, 'SBIN': 0.9977, 'INFY': 0.9963, 'AXISBANK': 0.9989, 'TCS': 0.9966, 'BAJFINANCE': 0.9996, 'JIOFIN': 0.9894, 'SWIGGY': 0.9952, 'MARUTI': 0.9968, 'TATASTEEL': 0.9956, 'WAAREEENER': 0.9968, 'KOTAKBANK': 0.9989, 'LT': 0.9958, 'ITC': 0.9904, 'BHARTIARTL': 0.9947, 'PAYTM': 0.991, 'SHRIRAMFIN': 0.9949, 'INDUSINDBK': 0.9984, 'VEDL': 0.9823, 'SUNPHARMA': 0.9981, 'HINDUNILVR': 0.9964, 'YESBANK': 0.9978, 'HCLTECH': 0.9965, 'HINDALCO': 0.999, 'IREDA': 0.9677, 'BANKBARODA': 0.9985, 'TECHM': 0.9956, 'OLAELEC': 0.9724}

## Log

- Phase 2 start — window 2014-01-01..2025-12-31, series kept ('EQ', 'BE')
- NOTE: P2 legitimately reads HOLDOUT dates (2022-07+) — it builds the full price panel; sealing applies to scoring, enforced in P4.
- REPORT-ONLY: reloading artifacts, regenerating tests + report
- canary table:
    symbol  n_days      first       last
      DHFL    1834 2014-01-01 2021-06-11
      RCOM    2665 2014-01-01 2025-12-31
JPASSOCIAT    2750 2014-01-01 2025-12-29
   YESBANK    2961 2014-01-01 2025-12-31
    SUZLON    2961 2014-01-01 2025-12-31
      IDEA    2961 2014-01-01 2025-12-31
 COX&KINGS    1470 2014-01-01 2019-12-24
     CAIRN     813 2014-01-01 2017-04-25
- flat coverage (universe proxy): slope +0.797/yr, mean 2016=200.0, mean 2024=200.0, min year mean=183.8  |  whole-market slope +67.5/yr (context)
- heavyweight day counts: {'RELIANCE': 2961, 'TCS': 2961, 'SBIN': 2961, 'TATASTEEL': 2961, 'MARUTI': 2961, 'ONGC': 2961, 'INFY': 2961, 'HDFCBANK': 2961}
- extreme daily returns >50%: 453 total, 415 not near a known corporate action (listed for review)
- yfinance cross-check: 30 names, median corr 0.9963, 25/30 above 0.99