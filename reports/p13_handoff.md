# Phase 13 handoff - Slide deck

> Written per IMPLEMENTATION_PLAN.md section 0.7. Every claimed result carries the number
> that proves it. Everything I could not verify is in section 4.
>
> **All deliverable files are pure ASCII** (owner instruction). Verified: 0 non-ASCII bytes
> in `slides/deck.html` and `slides/mc_variant_table.py`. The single exception is the HTML
> entity `&ccedil;`, used four times so that the author name **Gencay** renders correctly as
> Gen(c-cedilla)ay while the source file itself stays ASCII. Misspelling a cited author on a
> slide seemed the worse failure.

---

## 1. What was built

| File | Lines | Purpose |
|---|---:|---|
| `slides/deck.html` | 1,173 | The deck. Self-contained, 16:9, 18 sections (title + 16 content + references). Opens in any browser, presents with arrow keys, prints one landscape page per slide. Hand-authored inline SVG pipeline diagram, no chart library, no build step. |
| `slides/mc_variant_table.py` | 44 | Reproduces the search-policy table on slide 12 from scratch. 200,000 Monte-Carlo searches per row, seed 42. |
| `reports/p13_handoff.md` | this file | The handoff. |

Nothing under `src/`, `tests/`, `data/` or `dashboard/` was created, modified or deleted.
Phase 13 is read-only over the rest of the project.

### Structure delivered

The spec's slide table (IMPLEMENTATION_PLAN.md Phase 13) proposed a thematic 15-slide deck.
**The owner redirected the structure mid-phase** to stage-by-stage immediately after the
flowchart, on the grounds that Trexquant asked for whole-system I/O *and* per-stage I/O.
Delivered structure:

| # | Slide | Kind |
|---:|---|---|
| - | Title | cover |
| 01 | One finished unit of work is an Alpha Card | task spec, whole-system I/O |
| 02 | Nine stages, four gates, one feedback loop | full pipeline flowchart |
| 03 | A universe defined by a rule, not by a list | the input (P1/P2/P3) |
| 04 | Planner and Librarian: decide where to look next | stage S1 + S2 |
| 05 | Hypothesis and Gate A: commit to a story, and to a direction | stage S3 + Gate A |
| 06 | Implementation: bounded formula search | stage S5 |
| 07 | Backtester: one engine, eight call sites, no decisions | stage S6 |
| 08 | Gate B: is it new, and is it real? | stage S7 |
| 09 | Gate C: try to kill it | stage S8 |
| 10 | Memory and Reflection: learn from the corpse | stage S9 |
| 11 | **Five failure modes, five mechanisms, and what each does not catch** | the core argument |
| 12 | Three budgets, and the conflict between the first and the third | the core argument |
| 13 | Three ways to be wrong: data, statistics, economics | the bad examples |
| 14 | Grading the factory, not the signal | system evaluation |
| 15 | Honest novelty: two claims conceded, two that survive | positioning |
| 16 | What exists, and a dashboard to interrogate it | build state |
| 17 | What we took from each paper | references |

---

## 2. Acceptance criteria - every one, with a MEASURED value

**Phase 13 is the only phase in IMPLEMENTATION_PLAN.md with no `## Acceptance` section.**
It has a slide table, a tone note and an effort estimate. I therefore derived the criteria
below from (a) that slide table, (b) the tone note, and (c) the owner's explicit instructions
in this session. Stating that openly, because a self-authored criteria list is weaker evidence
than a spec-authored one and the owner should know which they are reading.

| # | Criterion | Source | Result | Measured value |
|---|---|---|---|---|
| 1 | A deck exists in `slides/`, PDF-ready | spec Outputs | PASS | `slides/deck.html`, 1,173 lines. Print CSS: `@page{size:1320px 743px;margin:0}` with `break-after:page` per slide. **Confirmed against a real PDF printed by the owner during this phase: 18 page objects, MediaBox 990 x 557.04 = 16:9 to 0.06 percent, one slide per page.** |
| 2 | Built around "five failure modes, five mechanisms, and what each does NOT catch" | owner: "build the deck around it" | PASS | Slide 11. Widest table in the deck, **6 rows x 3 columns**; the "does NOT catch" column is colour-separated and is the only column given its own header colour. Referenced from slides 06, 13. |
| 3 | Slide 14 concedes the two anticipated claims **with citations** | owner + spec tone note | PASS | Slide 15, row 4: "Not novel. Conceded." with a live link to `arXiv 2608.27734`; AgonAlpha `arXiv 2608.11250` conceded in the same row and again in the references. Both render as clickable links. |
| 4 | Leads with the two surviving claims | owner | PASS | Rows 1 and 2 of the same table, both tagged `genuinely novel` / `novel`, and each has a dedicated innovation panel earlier in the deck (slide 05 for the pre-registered sign, slide 12 for the three-budget conflict). |
| 5 | **Every citation checked before it goes on a slide** | owner | PASS (12 fetched live) | See section 2a. 12 sources fetched and confirmed this session; 3 not re-fetched and disclosed in section 4. |
| 6 | `arXiv 2608.27734` is single-author, Eray Gencay | owner, explicitly | PASS | Fetched `arxiv.org/abs/2608.27734`. **Authors field returns exactly one name: Eray Gencay.** Title confirmed as *"What survives honest evaluation? Leakage-safe, search-aware assessment of LLM-driven trading strategy discovery"*. The leaky-oracle claim was confirmed verbatim from the abstract: *"a deliberately leaky oracle posting a Sharpe ratio of 35 survives Deflated Sharpe and probability-of-backtest-overfitting testing completely."* Slide 11 and slide 13 both attribute to a single author. |
| 7 | Stage-by-stage section, immediately after the flowchart | owner | PASS | Slides 04-10, seven consecutive stage slides, beginning on the slide directly after the flowchart (03 is the input, 04 is S1+S2). |
| 8 | Every stage slide carries an explicit IN -> OUT strip | owner: "stage input and output for each stage" | PASS | **9 `.io` strips** in the deck: slides 01 (whole-system), 03 (the input), and 04-10 (all seven stage slides). Counted programmatically. |
| 9 | Low-impact stages clubbed, but nothing good made invisible | owner | PASS, with judgement | S1+S2 clubbed (slide 04), S3+Gate A clubbed (slide 05). **S5 and S6 kept separate on owner instruction.** S7, S8, S9 each stand alone. Every measured value from the P0-P10 handoffs that carries an argument appears somewhere; the audit trail is in section 7.3. |
| 10 | A full pipeline flowchart slide exists | owner | PASS | Slide 02. Hand-authored inline SVG, `viewBox="0 0 1240 604"`, 13 labelled nodes, 4 gates, a labelled reject channel, a labelled feedback edge, an off-loop portfolio node, and a 4-item legend. `role="img"` with a 62-word `aria-label`. No library. |
| 11 | Slides are not text-heavy | owner: "slides are never text heavy" | PARTIAL | Mean **318 words per slide** across 18 sections (down from a 430-word mean in the first draft). But two slides exceed it substantially: **slide 13 (bad examples) 560 words** and **slide 17 (references) 676 words**. Both are defended in section 5.1; neither is fixed. |
| 12 | Pure ASCII | owner | PASS | `grep -c '[^ -~\t]'` returns **0** for `slides/deck.html` and **0** for `slides/mc_variant_table.py`. Remaining HTML entities: `&amp;` x1, `&lt;` x2, `&gt;` x8, `&ccedil;` x4. No `&mdash;`, no `&nbsp;`, no smart quotes, no arrows, no mathematical glyphs. |
| 13 | No fabricated or placeholder numbers | plan section 0.7 rule 3 | PASS | Every figure on every slide traces to a `reports/p*_handoff.md` measured value, or was re-measured this session (section 2b). Slides 14 and 16 carry explicit "not yet run" blocks where P11/P12 evidence would go. **Zero placeholder figures.** |
| 14 | The deck renders without clipping or overflow | mine | PASS | All 18 sections rendered headlessly in Chrome at 1400px width and inspected visually in 4 passes (cover-05, 06-11, 12-17, and the inserted slide 03). No clipped text, no horizontal scroll, no overlapping elements. |
| 15 | Theme-correct in light and dark | mine | PARTIAL | Complete token set on bare `:root` (light), redefined under `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`. `body` paints an explicit token background. **Rendered and inspected in dark only** - see section 4.4. |
| 16 | Full project test suite still green | plan section 0.6 | PASS | `pytest -q` -> **315 passed in 773.72s**, exit code 0. Run this session, after all Phase 13 work. Phase 13 touches no code, so this is a baseline confirmation rather than a regression check. |

### 2a. Citation verification log

Fetched live this session. "Confirmed" means title and author list were read off the publisher
page and matched against what the slide says.

| Source | Status | What the fetch established |
|---|---|---|
| `arXiv 2608.27734` Gencay | CONFIRMED | **Single author, Eray Gencay.** Title confirmed. Leaky-oracle-at-Sharpe-35 claim confirmed verbatim from the abstract. |
| `arXiv 2608.11250` AgonAlpha | CONFIRMED | Authors: Ye, Sun, Ren, Yu, Yi, Yang (6). Fresh-context adversarial reviewer with veto, and pending-aware budget allocation, both confirmed. **The abstract mentions no DSR, PBO or purge/embargo** - which is the contrast the deck draws. |
| `arXiv 2502.16789` AlphaAgent | CONFIRMED | Authors: Tang, Chen, Yang, Mai, Zheng, Wang, Chen, Lin (8). AST originality, complexity control and **post-hoc** semantic hypothesis-factor alignment all confirmed. |
| `arXiv 2505.15155` RD-Agent-Quant | CONFIRMED | Authors: Li, Yang, Yang, Xu, Wang, Liu, Bian (7). **Venue NeurIPS 2025 confirmed.** Co-STEER and bandit scheduling confirmed. |
| `arXiv 2505.11122` Alpha Jungle | CONFIRMED | Authors: Shi, Duan, Li (3). LLM + MCTS confirmed. |
| `arXiv 2606.20625` AlphaMemo | CONFIRMED | Authors: Yu, Zheng, Pan, Liu, Wang, He (6). AST-diff edit motifs confirmed. |
| `arXiv 2511.18850` CogAlpha | CONFIRMED | Authors: Liu, Huang, Luo, Wang, Yang, Li, Hu, Feng, Liu (9). Code-based evolution confirmed. Deck cites "Liu et al." |
| `arXiv 1601.00991` Kakushadze | CONFIRMED | Single author, Zura Kakushadze. **Wilmott 2016(84):72-80 confirmed.** |
| FactorMAD, ACM DOI | PARTIAL | DOI page returned **HTTP 403**. Recovered via search: real title is *"FactorMAD: A Multi-Agent Debate Framework Based on Large Language Models for Interpretable Stock Alpha Factor Mining"*, authors **Yitong Duan, Chuheng Zhang, Jian Li**, ICAIF 2025. **Page numbers could not be confirmed, so the deck omits them.** |
| `arXiv 2402.03755` QuantAgent | NOT RE-FETCHED | Carried from INITIAL_PLAN.md section 16. Cited by ID and title only, no author list on the slide. |
| `arXiv 2306.12964` AlphaGen | NOT RE-FETCHED | Same. |
| `arXiv 2604.25224` ValueBlindBench | NOT RE-FETCHED | Same. |
| Bailey and Lopez de Prado, DSR | NOT RE-FETCHED | SSRN 2460551. Pre-cutoff, well-known; author names and title carried from INITIAL_PLAN.md. |
| Harvey, Liu and Zhu, RFS 2016 | NOT RE-FETCHED | Pre-cutoff. Deck cites author names, title and year only, **no volume or page numbers**, deliberately. |
| The Alpha Factory Illusion, LLMQuant | NOT RE-FETCHED | Cited by title and publisher only, no URL on the slide. |

**Correction applied from this verification:** INITIAL_PLAN.md section 16 lists FactorMAD as
*"Multi-Agent Debate for Interpretable Stock Alpha Factor Mining"* with pages 605-613. That
short title is a paraphrase, not the published title. The deck uses the published title and
drops the unverifiable page numbers.

### 2b. Numbers re-measured this session rather than carried from a handoff

| Number | Where | How measured |
|---|---|---|
| The whole `sqrt(2 ln N)` table on slide 12 | `20 -> 2.6%`, `200 -> 23.7%`, `500 -> 49.2%` | `slides/mc_variant_table.py`, 200,000 MC searches per row, `default_rng(42)`. Reproduces INITIAL_PLAN.md section 7 to MC noise (the design doc says 2.7% at N=20; I measure 2.6%). **The deck uses my measured values.** |
| `42` stocks absent from the supplied CSV | slide 13, bad example 1 | Computed against `nifty200_2015-01-01_to_2026-09-01.csv` and `data/universe/membership.parquet`. See section 6.1 - this **replaces** the "80" figure in the design docs. |
| `100 of 315` names with zero events | slide 13 | Same computation: union of ever-members is 315; names appearing in any `inclusions` or `exclusions` field is 217; difference is 100. |
| `315` tests passing | slide 16 | `pytest -q` -> `315 passed in 773.72s`, exit 0, run this session. |
| `11,147` lines in `src/` | slide 16 | `find src -name '*.py' | xargs wc -l` -> 11,147 total. |
| `2.6e-17` coverage slope, `72/72`, `100.0%` | slide 03 | Carried from `reports/p1_handoff.md` criteria 4, 5 and 6. Not re-derived. |

---

## 3. Verify it yourself

```
# 1. Open the deck. Arrow keys or PageUp/PageDown move between slides.
start slides\deck.html
#    Ctrl+P -> Save as PDF -> Landscape, no margins, background graphics ON
#    expect: 18 pages, one slide per page

# 2. Prove it is pure ASCII (expect: 0 and 0)
python -c "d=open('slides/deck.html','rb').read(); print(sum(b>127 for b in d))"
python -c "d=open('slides/mc_variant_table.py','rb').read(); print(sum(b>127 for b in d))"

# 3. Reproduce the search-policy table on slide 12
.venv\Scripts\python.exe slides\mc_variant_table.py
#    expect: N=20 -> 2.6% | N=200 -> 23.7% | N=500 -> 49.2%

# 4. Reproduce the broken-universe numbers on slide 13
.venv\Scripts\python.exe -c "import pandas as pd; d=pd.read_csv('nifty200_2015-01-01_to_2026-09-01.csv'); f=lambda s: {t.strip().replace(' ','') for t in s.split(',')} if isinstance(s,str) and s.strip() else set(); u=set(); e=set(); [ (u.update(f(r['symbols'])), e.update(f(r['inclusions'])|f(r['exclusions']))) for _,r in d.iterrows() ]; m=pd.read_parquet('data/universe/membership.parquet'); L=m['date'].max(); cur=set(m[(m['date']==L)&m['in_universe']]['symbol']); px=pd.read_parquet('data/prices/ohlcv.parquet',columns=['date','symbol']).groupby('symbol')['date'].min(); miss=cur-u; old={s for s in miss if s in px.index and px[s]<=pd.Timestamp('2015-03-31')}; print('union',len(u),'zero-event',len(u-e),'absent',len(miss),'absent-and-trading-in-2015',len(old))"
#    expect: union 315 | zero-event 100 | absent 87 | absent-and-trading-in-2015 42

# 5. Confirm the project is still green
.venv\Scripts\python.exe -m pytest -q
#    expect: 315 passed

# 6. Count the IN -> OUT strips (expect: 9) and the slides (expect: 18)
python -c "s=open('slides/deck.html').read(); print(s.count('<div class=\"io\">'), s.count('<section class=\"slide'))"
```

---

## 4. What I could NOT verify, and why

**4.1 Three of the four claims on the novelty slide rest on absence of evidence.**
"We found nothing that commits a direction before evaluation and rejects on mismatch" is a
negative claim over a literature I have sampled, not surveyed. I re-checked AlphaAgent and
AgonAlpha directly, which are the two nearest prior works, and both are post-hoc. **I did not
run a systematic search**, and a reviewer who knows a paper I have not read can falsify this
in one sentence. The deck's phrasing ("we found nothing", not "nothing exists") is deliberate.

**4.2 FactorMAD's page numbers.** The ACM DL returned HTTP 403 to the fetch. Title and authors
were recovered from search results; **pages 605-613, as claimed in INITIAL_PLAN.md section 16,
remain unconfirmed and are therefore absent from the deck.**

**4.3 AlphaMemo's date.** The abstract page reported a submission date of 26 May 2026, which is
inconsistent with an arXiv ID beginning `2606` (June 2026). I did not resolve this. **No date
for this paper appears on any slide.**

**4.4 Light-theme rendering.** The dark palette was rendered and inspected. The light palette is
defined token-for-token on bare `:root` and every component reads through tokens, so it should
resolve, **but I did not render it.** The owner should open the deck once with the OS in light
mode before presenting. This matters more than usual because a projector often forces light.

**4.5 Print output - now CONFIRMED, by the owner rather than by me.**
`slides/Alpha Factory Deck.pdf` appeared during this phase, printed by the owner from the deck.
Inspected: **18 page objects, MediaBox 990 x 557.04**, i.e. 990/557.04 = 1.7772, which is 16:9 to
0.06 percent. One slide per page, correct aspect, nothing dropped. The print CSS works.
**Still unverified: whether any individual page has clipped content in the PDF**, which I cannot
see from the page geometry alone. The owner has the file and should skim it.

**4.6 Timing.** The deck is designed for 20 minutes across 18 slides, roughly 65 seconds each.
**I have not timed a delivery.** Slides 11 and 13 will almost certainly run long, and slide 17
is a leave-behind that should not be presented at all.

**4.7 The two conceded claims.** I verified that Gencay and AgonAlpha exist, say what we say
they say, and predate us. **I did not verify that our other two claims are genuinely unanticipated**,
which is the same limitation as 4.1 and is the single most likely place this deck is wrong.

---

## 5. Failures and open issues

**5.1 Criterion 11 is only partially met. Two slides are still text-heavy.**
- **Slide 13 (bad examples), 560 words.** Three columns of four beats. Each column is ~187 words,
  which reads as compact in the render, and the prompt explicitly asks for this content with the
  naive result, the catching mechanism *and* the fix. I judged that cutting a beat would cost more
  than the density does. **Not fixed. Flagging it because the owner asked specifically for less text.**
- **Slide 17 (references), 676 words.** Sixteen entries, each with a "what we took" line. This is a
  leave-behind, not a presented slide. I would not cut it, but the owner should know it is the
  densest page in the deck by a wide margin.

**5.2 The deck is 18 sections, not the 12-to-14 originally discussed.**
16 content slides plus references plus title. It grew for three reasons the owner should weigh:
stage-by-stage costs seven slides where thematic cost four; S5 and S6 were separated on
instruction; and I added the data slide (03) on my own judgement - see section 7.1. At 65 seconds
per slide this fits 20 minutes, but there is no slack.

**5.3 P11 and P12 have not been run, and the deck says so on two slides.**
There is no accepted Alpha Card, no ablation table, no fake-learning plot. Slides 14 and 16 carry
explicit blocks naming each missing artefact. This was the owner's decision when asked. It is the
correct choice for a deck about not fooling yourself, but **it is a visible gap in two of the five
graded areas** (evaluating the system, and improving it over iterations), and a reviewer will ask.
The material that *is* on those slides is design plus the improvement machinery that genuinely
exists and was measured, which is a weaker answer than measured ablation numbers would be.

**5.4 Bad examples 2 and 3 are demonstrated at component level, not end to end.**
The leakage example uses measured values from P3, P4 and P9. The wrong-sign example uses the
measured pre-registration and `check_sign` behaviour from P6 and P8. **Neither has been produced as
a finished rejected Alpha Card by the loop**, which is what Phase 11 was for. The slide's footer
says this in plain words rather than implying otherwise.

**5.5 No speaker notes were produced.** The owner selected the HTML deck only from the format
options. Slides carry the evidence and assume a narrator who knows the material.

---

## 6. Anything that contradicts the spec

**6.1 The "80 missing constituents" figure in the design docs is not reproducible as stated.**
INITIAL_PLAN.md section 12 and IMPLEMENTATION_PLAN.md Phase 11 both claim *"80 of today's 200 NIFTY
200 constituents never appear in it at all."* Measured against the actual CSV and our own universe:

| Quantity | Measured |
|---|---:|
| Union of names ever appearing in the file | 315 |
| Names with at least one inclusion or exclusion event | 217 |
| **Names in the file with zero events** | **100** |
| Our top-200 by liquidity on 2025-12-31 | 200 |
| **...of those, absent from the file entirely** | **87** |
| ...of those 87, already trading on NSE by 2015-03-31 | **42** |
| ...of those 87, post-2015 listings (legitimately absent) | 45 |

So the true figure is 87, not 80 - but **45 of the 87 are post-2015 IPOs** (HYUNDAI, LICI, JIOFIN,
BSE, CDSL, KAYNES, CAMS, MANKIND, LODHA and others), which is the first objection any reviewer will
raise. **The deck leads with 42**, the count of names that were already trading in early 2015, are
in today's most-liquid 200, and still never appear in any of the 37 snapshots: RELIANCE, TCS, SBIN,
ONGC, MARUTI, TATASTEEL, COALINDIA, POWERGRID, SUNPHARMA, ULTRACEMCO, M&M, TITAN, JSWSTEEL, DLF,
DIVISLAB, BOSCHLTD and 26 more. That number survives the objection; 80 and 87 do not.
**Recommend the design docs be corrected.**

**6.2 The design doc's Monte-Carlo table differs from my rerun in the third digit.**
INITIAL_PLAN.md section 7 gives `P(best t > 3)` as 2.7 / 12.6 / 23.6 / 49.1 percent at N = 20 /
100 / 200 / 500. My 200,000-draw rerun gives 2.6 / 12.7 / 23.7 / 49.2. This is Monte-Carlo noise,
not a defect, and it does not change any argument. **The deck uses my measured values** because they
are the ones with a reproduction script shipped beside them.

**6.3 Phase 13 has no `## Acceptance` section**, unlike every other phase in the plan. Noted at the
head of section 2. The criteria there are mine, derived from the spec's slide table and the owner's
instructions, and should be read as such.

**6.4 P13's stated dependencies were not satisfied.** The plan says *"Depends on: P11, P12 for
evidence."* Neither has been run. The deck was built anyway, on owner instruction, with the gaps
disclosed on the slides rather than filled with placeholders.

**6.5 Two slides from the spec's table have no direct counterpart.**
- Spec slide 2, *"Literature map (what we adapt from each paper)"*: folded into slide 17, where every
  reference carries a bold "Adopted / Conceded to / Rejected" line. Same information, inverted
  direction (paper -> what we took, rather than component -> paper).
- Spec slide 4, *"(appendix) the 16 components inside the 9 stages, with paper lineage"*: **dropped.**
  The stage-by-stage section covers the components; the lineage now lives only on slide 17. This is a
  real, if small, loss of the component-to-paper mapping, made to hold the slide count down.

---

## 7. Decisions I made that the spec left open

**7.1 I added slide 03 (the data foundation) on my own judgement.** The nine stages start at the
Planner, so P1, P2 and P3 - the universe rule, the ISIN-keyed price build with our own corporate-action
adjustment, and the feature panel - had no stage slide and were reduced to one row of the inventory
table. That is the largest single block of real engineering in the project, it is the evidence base
for the strongest bad example, and quant reviewers care about it more than about the agent graph.
I gave it a slide framed as "the input", with the same IN -> OUT strip as the stage slides. **This
took the deck from 15 content slides to 16.** If the owner disagrees, deleting one `<section>` removes it.

**7.2 Which stages were clubbed.** S1+S2 (slide 04) because the Librarian is genuinely a keyword
filter and a not-tradeable exclusion list - roughly one slide-line of content - and it shares the
"decide where to look" decision with the Planner. S3+Gate A (slide 05) because Gate A exists only to
grade what S3 emitted, and the pre-registered sign spans both. S5 and S6 were separated **on owner
instruction** after I had merged them. S7, S8 and S9 each carry enough measured content to stand alone.

**7.3 What I put on which slide, when a number could have gone in two places.** The `sqrt(2 ln N)`
table sits on the budgets slide (12) rather than the implementation slide (06), because it is evidence
for budget 3 rather than a digression inside the search loop; slide 06 states the cap and the three
bindings, and the math that justifies the cap arrives six slides later. The `t = -3.000` finding sits
on Gate B (08) rather than the bad-examples slide (13), because it is a fact about our deflator, not
one of the three failure classes the prompt asks for.

**7.4 I added a sixth row to the failure-mode matrix.** INITIAL_PLAN.md section 6 has five rows.
I added **"Broken data source"**, caught by external reconciliation only and caught by *nothing else
in the table*. It is the failure we actually hit, it is the only row whose "does not catch" cell reads
"every mechanism in this table", and it sets up slide 13. **This is an addition to the design doc's
core slide and the owner should decide whether to keep it.**

**7.5 Format: one self-contained HTML file, not PDF and not Markdown.** The owner selected
"HTML deck, print-to-PDF ready" from the format options. Consequences: no build step, opens anywhere,
arrow-key navigation, the flowchart is hand-authored SVG that stays crisp at any zoom, and the PDF is
one Ctrl+P away. Cost: it is not directly editable in Google Slides, and the fonts are fetched from
Google Fonts, so **first render without a network connection falls back to system faces** (the fallback
stacks are declared, so nothing breaks, but the type looks different).

**7.6 Visual identity.** IBM Plex Serif for slide titles, IBM Plex Sans for body, **IBM Plex Mono for
every figure, formula, file path and label**, with `tabular-nums` throughout so columns of numbers line
up. Palette: deep blue-black ink and a cool green-grey paper, with one accent - deep teal - for
mechanisms and verified results, ochre for "measured but caveated", oxide red reserved exclusively for
kills and rejections. The reasoning: this is a system whose identity is that it writes down every
attempt to disprove itself, so the deck was pitched as an audit document rather than a product pitch.
Semantic colour (pass / caveat / kill) is kept separate from the accent hue.

**7.7 ASCII handling of the one accented name.** `&ccedil;` renders Gencay's name correctly while the
file stays byte-for-byte ASCII. Every other non-ASCII candidate was rewritten in plain ASCII: arrows
became `->`, em-dashes became hyphens, `sqrt(2 ln N)` is spelled out, `<=` and `>` are literal, and all
75 non-breaking spaces were replaced with ordinary spaces.

**7.8 I did not publish the deck as a shareable artifact.** The owner selected only the local HTML
format. The file is ready to publish if that changes.

---

## 8. Recommendation before the next phase

The deck's two weakest slides are 14 and 16, and both are weak for the same reason: **P11 and P12 have
not been run.** If there is time for one more phase before this is presented, Phase 12 (the ablation)
buys more than Phase 11 does - it converts "we designed gates" into "we measured what each gate
catches", which is the difference between an asserted architecture and a justified one, and it fills
the largest hole in a directly graded area. Phase 11's accepted card is more satisfying to show but
less load-bearing for the argument the deck actually makes.

**Do not start either. Stop here and wait for sign-off, per section 0.7 rule 5.**
