# PRE-BUILD TASKS — resolve before Phase 0

> Five open items surfaced by the final design audit. Each is small, and each could change a phase spec
> if answered badly. Working through them in order.
>
> **Status key:** ⬜ open · 🔄 in progress · ✅ resolved · ⏸ deferred to its phase

---

## T1 ✅ — Does NSE delivery data reach back to 2014? → **No: starts 2019-09-30. But the investigation found something much better.**

**Why it matters.** `delivery_pct` is one of our ten features and has a dedicated red-team test (#6 —
the only field with genuine timing ambiguity). If `sec_bhavdata_full` only starts ~2020, the feature
covers the Holdout but barely touches Val-A, where the search actually happens. That would weaken both
the feature and the test.

**Task.** Determine the earliest available date and the correct endpoint(s). Note that NSE historically
published delivery data as `MTO_DDMMYYYY.DAT` before the `sec_bhavdata_full` format existed — if so,
P2 needs two parsers, not one.

**Decision it drives.** Keep `delivery_pct` as a full feature · keep it but disclose partial coverage ·
or drop it and remove red-team test 6.

---

## T2 ✅ — Sector classification → **full NSE mapping, and it's 78% automated**

**Why it matters.** P3 says "hard-code a `dict[symbol → sector]`" for ~315 symbols. That is real tedium,
and sector is used only for (a) optional sector-neutralization and (b) red-team test 7.

**Options.**
| Option | Cost | Consequence |
|---|---|---|
| Full NSE sector mapping, ~315 names | ~1h | Best fidelity |
| **Coarse 8-sector split** | ~20 min | Adequate for neutralization; disclose the coarseness |
| Drop sector entirely | 0 | Lose red-team test 7 and sector-neutral robustness |

**DECISION: full NSE mapping.** ✅ Resolved — see below; it is far cheaper than feared.

### Method (verified live 2026-09-02)

`https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv` → HTTP 200,
**752 names**, header `Company Name, Industry, Symbol, Series, ISIN Code`.

**It carries both `Industry` and `ISIN`** — and our panel is ISIN-keyed (T1), so the join is by
identifier, not by name.

**Measured coverage against our 315-symbol union:**

| | Count | Share |
|---|---:|---:|
| Auto-classified from the NSE file | **246** | **78%** |
| Need manual classification | **69** | 22% |

The 69 are precisely the delisted and renamed names — `DHFL, CAIRN, CMC, GRUH, COX&KINGS, AMTEKAUTO,
HDIL, BHARATFIN, …` — which is expected: NSE's current list cannot contain companies that no longer
exist. Four of them (CAIRN→VEDL, GRUH→BANDHANBNK, CMC→TCS, BHARATFIN→INDUSINDBK) resolve through the
rename map, leaving **~65 genuine manual assignments** — roughly 20–30 minutes, and most are obvious
(DHFL → Financial Services, AMTEKAUTO → Automobile and Auto Components).

**NSE's official taxonomy — 22 industries** (use these verbatim, do not invent categories):
Automobile and Auto Components · Capital Goods · Chemicals · Construction · Construction Materials ·
Consumer Durables · Consumer Services · Diversified · Fast Moving Consumer Goods · Financial Services ·
Forest Materials · Healthcare · Information Technology · Media Entertainment & Publication ·
Metals & Mining · Oil Gas & Consumable Fuels · Power · Realty · Services · Telecommunication ·
Textiles · Utilities

### ⚠️ Limitation to disclose
The classification is **current, not point-in-time.** A company reclassified since 2015 carries today's
label throughout history. This is acceptable because sector is used only for *optional*
neutralization and red-team test 7 — but it must be stated, not hidden. (Consistent with decision
**B6-UPDATE**, which already flags `sector` as non-PIT.)

---

## T3 ✅ — Will the Groq free tier survive a full run? → **Not a 50-thesis one. ~20 theses/day is the ceiling. And our two named models are deprecated.**

**Why it matters.** ~14,400 req/day sounds ample, but a 20-variant inner loop across many generations
multiplies fast, and **per-minute rate limits bite long before daily caps**. Finding this out during a
demo is the bad outcome.

**Task.** Compute a call/token projection for a target run (e.g. 10 generations × 5 theses × up to 20
variants), per agent role, against Groq's published free limits. Decide whether P8 needs request
throttling and a resumable checkpoint.

### ⚠️ FINDING 1 — our two named models are deprecated

`PLAN_EXPLAINED.md` (Infrastructure) specifies **`llama-3.3-70b-versatile`** and
**`llama-3.1-8b-instant`**. Multiple sources report both were **deprecated 17 June 2026**, with Groq
recommending `openai/gpt-oss-120b` / `qwen/qwen3-32b` and `openai/gpt-oss-20b` as replacements.

**Caveat, stated honestly:** Groq's own models page still *listed* both at time of checking, so the
sources conflict and I could not resolve it without an API key. **Do not hard-code a model.** P8 must
read the model ID from config and **probe availability at startup**, falling back down a list.

### Free-tier limits (per organisation, not per key — extra keys do not multiply capacity)

| Model | RPM | RPD | TPM | **TPD** |
|---|---:|---:|---:|---:|
| `llama-3.3-70b-versatile` | 30 | 1,000 | 12,000 | **100,000** |
| `openai/gpt-oss-120b` | 30 | 1,000 | 8,000 | **200,000** |
| `openai/gpt-oss-20b` | 30 | 1,000 | 8,000 | **200,000** |
| `qwen/qwen3-32b` | 60 | 1,000 | 6,000 | **500,000** |
| `llama-3.1-8b-instant` | 30 | 14,400 | 6,000 | **500,000** |

**Tokens-per-day is the binding constraint, not requests.** You hit whichever limit comes first.

### FINDING 2 — the projection

Per thesis, assuming 70% pass Gate A and 20% reach the Red-Team, with an average of 8 variants (cap 20):

| Role | Calls/thesis | Model | Tokens/call | Tokens/thesis |
|---|---:|---|---:|---:|
| Hypothesis | 1 | **large** | 3,300 | 3,300 |
| Red-Team | 0.4 | **large** | 2,400 | 960 |
| Coder | 5.6 | small | 1,700 | 9,520 |
| Judge | 5.6 | small | 1,400 | 7,840 |
| Economics reviewer | 1 | small | 1,900 | 1,900 |
| Planner · Brief · Reflection | 3 | small | 1,000 | 3,000 |
| **Total** | **~16.6** | | | **large 4,260 · small 22,260** |

**Scaled:**

| Run size | Large tokens | Small tokens | Fits in one day? |
|---|---:|---:|---|
| 10 generations × 5 theses = **50** | 213,000 | 1,113,000 | ❌ **exceeds TPD by ~2×** on both |
| **20 theses** | 85,200 | 445,000 | ✅ fits (tight) — **the practical ceiling** |

**Wall clock is the other constraint:** 445,000 small-model tokens ÷ 6,000 TPM ≈ **74 minutes minimum**,
purely from throttling. A 50-thesis run would take ~3 hours *and* need to span multiple days.

### DECISION

1. **Target ~20 theses per run.** That is ample for the deliverable — one good card, three bad examples,
   and a working loop. It is *not* enough for a statistically strong ablation, so P12's seeded pool
   (~40 pre-written factors) must stay **LLM-free**, which it already is.
2. **P8 must add a token-bucket throttle** respecting TPM, and track TPD against a configured cap.
3. **P10's checkpointing becomes essential, not nice-to-have.** If TPD is exhausted mid-run, the loop
   must resume the next day from the last checkpoint rather than restart.
4. **Exploit prompt caching** — cached tokens reportedly do not count toward limits. Our prompts share a
   large static preamble (rubric, operator list, corpus brief). Put the static part first so it caches.
5. **Shrink the Judge prompt** — it and the Coder are called ~11× per thesis and dominate token spend.
6. **Model IDs go in config with a fallback chain**, probed at startup.

**This also strengthens a slide.** "Alpha per token" stops being a slogan and becomes a measured
constraint we designed around: ~22,000 tokens per hypothesis explored, ~1,000 tokens per formula
variant, and a hard ceiling of ~20 theses/day on free infrastructure.

---

## T4 ✅ — Is P13 (slide deck) mine or yours? → **Stays in scope; collaborative.**

**DECISION:** P13 remains a phase with its ~4h intact. No hours redirected from P11/P12. Assistance
with building the deck will be requested when we reach it.

---

## T5 ✅ — Are ~20 Alpha101 formulas expressible? → **Yes, ~39 are. And `vwap` turns out to be available.**

**Why it matters.** P5's alpha zoo (~30 formulas) is what the pre-filter's structural novelty check
compares against. Many Alpha101 formulas need `vwap`, `cap`, `adv20`, or industry-neutralization
operators we do not have. If only 8 survive, the zoo shrinks and the duplicate check weakens.

**Task.** Audit Alpha101 against our operator list and our available fields
(`open/high/low/close/volume/returns/delivery_pct/size_proxy/sector`). Count how many transcribe
cleanly. If the number is low, decide: add the missing operators, add `vwap` as a derived field, or
lean harder on the ~10 classical factors.

### ⭐ FINDING 1 — `vwap` IS available across the full history (verified 2026-09-02)

This was the field I assumed we lacked, and it blocks ~10 Alpha101 formulas on its own.

| Era | Source | Derivation |
|---|---|---|
| 2015 → 2019-09 | legacy bhavcopy | `TOTTRDVAL / TOTTRDQTY` |
| 2019-09-30 → now | `sec_bhavdata_full` | `AVG_PRICE` directly (cross-check: `TURNOVER_LACS / TTL_TRD_QNTY`) |

**Validated on the 2018-03-15 file — every derived VWAP falls inside its day's [low, high] range:**

| Symbol | Low | **VWAP** | High | ✓ |
|---|---:|---:|---:|:--:|
| RELIANCE | 910.00 | **918.37** | 929.45 | ✓ |
| TCS | 2,855.60 | **2,876.92** | 2,902.55 | ✓ |
| DHFL | 513.00 | **519.46** | 524.90 | ✓ |
| SUZLON | 11.45 | **11.65** | 11.75 | ✓ |

### FINDING 2 — field coverage

| Alpha101 field | Status |
|---|---|
| `open, high, low, close, volume, returns` | ✅ have |
| **`vwap`** | ✅ **derived — see above** |
| `adv{d}` (avg daily dollar volume) | ✅ expressible as `ts_mean(mul(volume, close), d)` |
| `IndClass.{sector,industry}` | ✅ our 22 NSE industries → `sector_neutral` covers `IndNeutralize` (coarser, still valid) |
| `cap` (market cap) | ❌ not available → `size_proxy` substitutes. **Blocks only Alpha#56** |

### FINDING 3 — the count

**~39 of Alpha #1–60 transcribe cleanly with no change to the operator set**, including
#2, 3, 4, 5, 6, 8, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 25, 26, 28, 30, 32, 33, 34, 35, 38, 40,
41, 42, 43, 44, 45, 50, 52, 53, 54, 55, 57, 60.

**We need 20. Comfortably met.**

**What blocks the rest — and it is almost entirely one missing operator:**

| Blocker | Formulas blocked | Fix |
|---|---|---|
| **no `if_else` / ternary** | ~11 (#1, 7, 9, 10, 21, 23, 24, 27, 46, 49, 51) | **Add `if_else(cond, a, b)`** — element-wise, trivially causal, ~10 lines |
| no `product` | #29 | Add `ts_product(x, d)` — trailing, causal |
| no `cap` | #56 | Skip it, or substitute `size_proxy` |

### DECISION

1. **Add `vwap` as a derived field in P2** (both eras), and `adv{d}` as a documented idiom.
2. **Add two operators to P5: `if_else` and `ts_product`.** Both are element-wise/trailing and pass the
   causality test trivially. `if_else` alone unlocks ~11 more formulas — the best ratio of effort to
   coverage in the whole library.
3. **Transcribe 25 Alpha101 formulas, not 20** — the ceiling is ~50 with `if_else`, so 25 is
   comfortable and makes the duplicate check meaningfully stronger.
4. **Skip Alpha#56** (needs true market cap) and disclose.

**Side benefit for the deck:** `vwap` and `TOTALTRADES` give us genuine intraday-microstructure inputs
(average trade size = `TOTTRDQTY / TOTALTRADES`) that a yfinance-only pipeline simply cannot produce.
That is a real, defensible edge from choosing the exchange as the source.

---

# RESOLUTIONS

## T1 — RESOLVED 2026-09-02. All findings are from live endpoint probes, not documentation.

### Finding 1 — `delivery_pct` starts **2019-09-30**, pinned exactly

`https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_<DDMMYYYY>.csv`

| Probe date | Result |
|---|---|
| 2016-02-01, 2018-06-15, 2019-01-15, 2019-06-14, 2019-09-16, 2019-09-27 | **404** |
| **2019-09-30** onwards (tested through 2025-06) | **200** |

Also confirmed: the format **survived** NSE's July-2024 UDiFF migration (2024-07-15 → 200), so one
parser covers 2019-09-30 → present.

**Coverage against our split:** Train ❌ none · Val-A ~48% (Oct 2019 → Jun 2021 of a Jan 2018 start) ·
Val-B ✅ full · Holdout ✅ full.

**Decision:** **keep `delivery_pct`**, NaN before 2019-09-30, disclosed. Red-team test 6 still works —
it just runs on the covered window. A thesis that *depends* on delivery data is simply restricted to
post-2019 evaluation, which the Hypothesis agent should be told via the corpus's
`tradeable_with_our_data` mechanism.

### Finding 2 ⭐ — the **legacy bhavcopy archive works back to 2015, and it contains the delisted names**

`https://nsearchives.nseindia.com/content/historical/EQUITIES/<YYYY>/<MON>/cm<DDMONYYYY>bhav.csv.zip`
→ 200 for 2015-01-01, 2016-06-15, 2018-03-15, 2019-09-16.

Downloaded 2018-03-15 (1,854 rows). **Survivorship canaries — all present with real prices:**

| Symbol | Close on 2018-03-15 |
|---|---|
| DHFL | 515.45 |
| RCOM | 23.60 |
| JPASSOCIAT | 19.20 |
| YESBANK | 311.85 |
| SUZLON | 11.65 |
| IDEA | 80.15 |
| COX&KINGS | 251.25 |
| CAIRN | *absent — correct*, it merged into Vedanta in April 2017 |

That last row is a **validation, not a failure**: the archive is genuinely point-in-time.

**This is the single most valuable finding of the whole audit.** yfinance drops delisted names, which
was the acknowledged hole in our survivorship claim. NSE bhavcopy **is a per-day, all-symbols snapshot**,
so it closes that hole from the official source.

Schema: `SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP,
TOTALTRADES, ISIN`. Two bonuses:
- **`ISIN`** is stable across ticker renames → CAIRN→VEDL, GRUH→BANDHANBNK etc. can be tracked by
  identifier instead of a hand-written name map. Strictly more reliable.
- **`TOTALTRADES`** is a free microstructure feature (average trade size = `TOTTRDQTY / TOTALTRADES`)
  we did not previously have.

### Finding 3 — the corporate-actions API works, so we can do our own adjustment

`https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=..&to_date=..`
→ HTTP 200, **2,012 records for 2018**, with `symbol · exDate · subject`, e.g.
*"IOC | 15-Mar-2018 | Bonus 1:1"*, *"INDNIPPON | 21-Mar-2018 | Face Value Split From Rs 10 To Rs 5"*.
Requires a session cookie from `nseindia.com` plus a browser `User-Agent` and `Referer`.

This matters because **bhavcopy is unadjusted** — a 1:10 split reads as a −90% return unless corrected.
With this API we build our own split/bonus adjustment factors rather than inheriting Yahoo's opaque,
retroactively-mutating adjustments.

### ⇒ Consequence: **NSE becomes the PRIMARY price source; yfinance becomes the cross-check**

The original plan had this backwards. Revised stack:

| Source | Role |
|---|---|
| **NSE legacy bhavcopy** (2015 → 2019-09) | primary OHLCV — **includes delisted names**, ISIN-keyed |
| **NSE `sec_bhavdata_full`** (2019-09-30 → now) | primary OHLCV **+ delivery %** + trade counts |
| **NSE corporate-actions API** | our own split/bonus adjustment factors |
| **yfinance** | cross-check only — validate our adjusted series against Yahoo's for surviving names |

**Cost:** ~2,900 daily HTTP requests (cacheable, resumable, one-time) plus adjustment logic. **Benefit:**
the survivorship claim moves from *"we disclose a gap"* to *"we recovered it from the exchange"* — and
that is our headline data claim.

**Open sub-question for T1b:** building the adjustment factors is genuinely new work (~2h) not in the
current P2 spec. Alternative: use bhavcopy for *coverage* (which names existed and traded) and yfinance
for *adjusted prices* where available, accepting raw prices only for the delisted names. Cheaper, but
mixes two adjustment conventions in one panel. **Recommend doing it properly. Awaiting your call.**
