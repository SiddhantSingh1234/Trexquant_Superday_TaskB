# FLOW_EXPLAINED — The Whole Machine, in Plain English

> **Read this first.** It explains the system we finally decided on, from start to finish, in simple
> words. Every technical term is explained the first time it appears, in a box like this:
>
> 📖 **Term** — what it means, in one or two plain sentences.
>
> The other two files: **`INITIAL_PLAN.md`** is the architecture spec (slide source).
> **`PLAN_EXPLAINED.md`** is the decision record (why we chose each thing) plus the full dictionary.

---

## PART 0 — What are we even making?

Trexquant did not ask for a trading signal. They asked for a **factory** — run by AI agents — that
keeps *inventing* trading signals, *testing* them, *throwing out the bad ones*, and *getting better
over time*. Then they asked two more things: how would you **measure** that factory, and how would you
**improve** it?

### What the factory produces

One thing, over and over: a **daily cross-sectional alpha signal**. Unpacking that:

> 📖 **Signal / score** — one number for each stock, each day.
>
> 📖 **Cross-sectional** — "across all the stocks, on one day." The number only matters *relative to
> the other stocks today*. It is a **ranking**. We are not predicting "will the market go up." We are
> predicting "which stocks will beat which."
>
> 📖 **Alpha** — the part of a stock's return that comes from *skill* — from actually predicting
> something — rather than from just being in the market while it rose.

So each day the system outputs a column of numbers:

```
Reliance  +1.2      ← I expect this to beat its peers tomorrow
TCS       −0.4      ← I expect this to lag its peers
Infosys   +0.7
HDFC Bank −1.1
...
```

You buy the top-ranked names, short the bottom-ranked ones, and you make money **if your ranking was
right on average, across many stocks and many days**. Being wrong on any single stock is fine and
expected. Being right on average is the whole game.

### But a signal alone is not the deliverable

Trexquant's spec says the output must contain **an economic thesis AND the alpha implementation**.

> 📖 **Economic thesis** — the *story* for *why* this should work. Not "the numbers say so," but "here
> is the human behaviour or market structure that creates this mispricing, here is who is losing money
> to me, and here is why they keep doing it."

That requirement drives a large part of our design. A signal with no story is a coincidence you have
not noticed yet.

### The one-line summary of our system

> A team of specialised AI agents — a manager, a librarian, a researcher, an engineer, a critic, a
> statistician, a prosecutor, and a historian — runs in a **loop**: *propose an idea → turn it into a
> formula → test it → attack it → keep it only if it survives every check → remember what happened →
> propose a better idea next time.* A limited AI budget forces it to be economical.

---

## PART 1 — The one thing that flows through the machine

Everything in this system is about **one object** travelling through **nine stages**. That object is
called an **Alpha Card**. It starts nearly empty and gains a new section at each stage.

```
        ┌─ thesis, mechanism, counterparty, horizon, regime
        ├─ PRE-REGISTERED SIGN          ← committed before any data is touched
        ├─ the formula (and its tree)
        ├─ quick test results
        ├─ full test results
        ├─ honesty audit
        ├─ attack report
        └─ verdict + family tree + which data fields it used
```

**Important:** a card that gets **rejected** is *not* thrown away. It carries its "death certificate"
into memory — *what was tried, and exactly why it died*. That record is what makes the factory improve
over time. A factory that only remembers its wins learns nothing.

---

## PART 2 — The nine stages, one at a time

Here is the whole flow. Then we walk each stage.

```
  INPUTS
    │
  S1 PLANNER ──────────── what should we work on, and how much can we spend?
    │
  S2 LIBRARIAN ────────── what does the research (and our own memory) already say?
    │
  S3 HYPOTHESIS ───────── write the economic story + COMMIT TO A DIRECTION
    │
  ▼ GATE A · ECONOMICS ── is this a real story, or hand-waving?          → reject
    │
  S5 IMPLEMENTATION ───── turn the story into a formula (max 20 attempts)
    │
    ▼ FRESH-FOLD CHECK ── does the winner hold on data it never saw?     → reject
    │
  S6 BACKTESTER ───────── the full, rigorous test battery
    │
  ▼ GATE B · HONESTY ──── is it NEW? and is it REAL, given how hard we looked?  → reject
    │
  ▼ GATE C · RED-TEAM ─── 11 attacks. survive all of them.               → reject
    │
  ★ ALPHA CARD ★
    │
  S9 MEMORY ───────────── write the lesson, update the plan
    │
    └──────────────► back to S1, next generation
```

Everything that gets rejected goes to **S9 Memory** too. Nothing is wasted.

---

### 🔵 S1 · THE PLANNER — the manager

**What it does:** decides *what to work on next* and *how much to spend on it*.

It groups ideas into **families** — momentum, liquidity, reversal, seasonality, microstructure — and
decides which family gets the next slice of budget. It does that using a classic method:

> 📖 **Multi-armed bandit** — imagine a row of slot machines. You don't know which pays best, and you
> have limited coins. So you balance **exploiting** the machines that have paid well with **exploring**
> the ones you haven't tried much. Our manager does exactly this with idea-families.

**It also enforces two hard budgets** — and this is one of the most important ideas in the whole design:

| Budget | What it limits |
|---|---|
| **Token budget** | how much AI thinking we can buy |
| **Variant budget** | how many formula attempts each idea gets (**max 20** — see Part 3) |

> 📖 **Token** — the unit LLMs read and write in, roughly ¾ of a word. Every AI call costs tokens =
> money and time. Trexquant explicitly gave us a *finite* token budget, so being economical is part of
> the grade.

**Why it exists:** with a limited budget, undirected search is waste. The manager makes the factory
spend where the payoff actually is.

---

### 🔵 S2 · THE LIBRARIAN — the research assistant

**What it does:** before anyone has an idea, it goes and reads.

It searches two things: the research paper collection, **and the factory's own memory of what it has
already tried**. Then it writes a short briefing.

> 📖 **RAG (Retrieval-Augmented Generation)** — instead of letting the AI answer from vague memory, you
> first *retrieve* the relevant documents and hand them to it. The AI then reasons from real sources.

**Why the memory half matters more than the papers half:** the papers stop the system reinventing what
academia already published. The memory stops it re-proposing the idea it killed three generations ago.
Without memory, an agent loop rediscovers the same dead ends forever and burns your entire budget doing
it.

---

### 🔵 S3 · THE HYPOTHESIS AGENT — the researcher

This is where the **economic thesis** gets written, and it is the most important creative step.

The agent must produce **all five** of these, or the idea is dead:

1. **A named mechanism** — *why* does this mispricing exist?
2. **The counterparty** — *who is on the other side of this trade, and why do they keep losing?*
3. **Why it isn't already arbitraged away** — if it's so obvious, why hasn't it been traded flat?
4. **Horizon and regime** — how long does the edge last, and in what kind of market?
5. **A falsifiable prediction — including the direction.**

That fifth item is our most distinctive mechanism, so it gets its own section.

#### 📌 The pre-registered sign

> 📖 **Pre-registered sign** — before any data is touched, the agent writes down and **locks** which
> *direction* it expects: "**high** value of this factor should mean **high** future return" (sign
> `+1`), or the reverse (`−1`). This is timestamped into the record. Later, when we test it, the actual
> direction must match. **If it doesn't, we reject the idea — even if the numbers are excellent.**

**Why this matters so much.** Two problems it kills:

**Problem 1 — the sign is free.** Every factor `f` has an exact mirror image `−f`. If you don't commit
in advance, you effectively test *both* and keep whichever worked. You have quietly run two experiments
while recording one, and every honesty calculation downstream is now wrong.

**Problem 2 — the AI will write you a beautiful story for anything.** This is the big one. If you let
the model see the result first, it will produce a completely plausible economic mechanism to explain
whatever the data happened to show. Your "economic thesis" — the thing Trexquant is actually grading —
quietly degenerates into a nice paragraph written *about noise*.

Pre-registration turns the thesis from a **description** into a **prediction that can be wrong**. That
is the entire difference between science and storytelling.

**A bonus:** because you committed to one direction, the statistics can honestly use a *one-sided* test,
which is slightly less punishing than a two-sided one. Rigor that *buys* you power instead of costing
it — a nice thing to be able to say.

**Its honest limit:** it binds *one idea* to *one direction*. It gives **zero** protection *inside* an
idea, because all 20 formula attempts inherit that same direction and pass the check trivially. That
gap is exactly what Part 3 is about.

---

### 🟩 GATE A · ECONOMICS — the first rejection point

**What it does:** a **different** AI instance reads the thesis and scores it against the five-point
rubric — harshly. Missing any one item → **rejected, before a single line of code is written.**

**Why a different instance?** Because models grade their own work generously. If the same agent that
wrote the thesis also judges it, you get a rubber stamp. Splitting author from judge is a small change
that removes a large bias.

**Why put it first?** It is the cheapest possible rejection. No code, no testing, no wasted budget.

---

### 🔵 S5 · THE IMPLEMENTATION LOOP — the engineer and the critic

Now the story becomes something a computer can run.

The **Coder** translates words into a formula, built from a fixed toolbox:

> 📖 **Operator library** — a set of safe, pre-built mathematical building blocks (from WorldQuant's
> famous "101 Formulaic Alphas"): `rank(...)` puts today's stocks in order, `ts_mean(x, 20)` takes a
> 20-day rolling average, `delay(x, 5)` looks back 5 days, `correlation(...)`, `sign(...)`, and so on.
> The Coder assembles formulas from these blocks rather than writing arbitrary code.

A finished formula looks like:

```
rank( ts_mean(volume, 1) / ts_mean(volume, 20) ) * sign( prev_close − close )
```

Readable in one line: *"stocks whose volume today is unusually high compared to their 20-day average,
**and** whose price fell."*

> 📖 **AST (Abstract Syntax Tree)** — a formula drawn as a tree: the division on top, the averages
> below it, the raw data fields as leaves. Comparing two formulas' *trees* is a rigorous way to ask
> "are these secretly the same idea?"

#### 🛡️ Why the operator library is a *safety* feature, not just a convenience

This is a point worth understanding properly.

> 📖 **Look-ahead bias** — accidentally letting your strategy see the future. It is the single most
> common reason backtests lie. Example: using a stock's full-year high to make a decision in January.

**Every operator in our library is "causal"** — `delay` looks backward, `ts_mean` averages a *trailing*
window, `rank` compares today's stocks to each other today. **There is no operator that can reach
forward in time.** So the Coder *cannot write* a formula that peeks at the future, even if it tried.

That is much stronger than testing for look-ahead afterwards. It is **structurally impossible** rather
than **hopefully caught**. (The newest research says this is exactly the right approach — see Part 5.)

#### The refinement cycle

```
Coder writes a formula
   ↓
Does it compile? Too complicated? A duplicate of something we already own?   → junk, kill it (free)
   ↓
Quick test on the practice data. Get a number.
   ↓
Judge reads the number: does it match the story? What single change would help?
   ↓
back to the Coder ... up to 20 times, then promote the best one
```

The **Judge**'s real job is not to score — the test already produced a number. Its job is to **name the
change**: "the window is too short for a multi-week thesis, widen it to 20 days."

> 📖 **Edit motif** — the *kind* of change made (widen the window · add a rank · swap volume for
> turnover). Research shows the genuinely reusable knowledge is *which kinds of change help, in which
> situations* — so our memory stores motifs, not just finished formulas.

---

### 🚨 PART 3 — THE MOST IMPORTANT IDEA IN THE DESIGN

Read this section twice. It is what separates this design from a naive one.

#### The problem: searching harder makes you *more* likely to fool yourself

Here is a fact that surprises most people.

Suppose you test **N formulas that are all completely worthless** — pure noise, no predictive power at
all. How good will the *best* one look?

> 📖 **t-statistic** — a measure of "how many standard errors is this result away from zero?" Higher =
> stronger evidence it isn't luck. The traditional bar is t > 2. Because so many fake factors have been
> published, serious researchers (Harvey, Liu & Zhu) now demand **t > 3** for anything new.

The maths says the best of N worthless signals will show a t-statistic of about **√(2 × ln N)**:

| Formulas tried | Best t-stat expected, **from pure noise** |
|---:|---|
| 1 | ~0.0 |
| **20** | **2.45** |
| 100 | 3.03 |
| **200** | **3.26** ← **clears the "t > 3" bar with nothing there at all** |

**So if you let the system try 200 variations of one idea and keep the best, you will produce something
that passes your strictest test, every single time, even if the idea is worthless.**

And notice: **the pre-registered sign does not save you here.** All 200 variants share the same idea, so
they all share the same predicted direction. The sign check passes for every one of them. The mechanism
that protects you *between* ideas is completely silent *within* one.

#### Why this is worse with "smarter" search

There is a technique called **MCTS** (Monte Carlo Tree Search) that several papers use for exactly this
job. It is genuinely clever: it explores a tree of formula edits and concentrates its effort on the
branches that are scoring well.

But think about what that means here. **Its entire purpose is to find the maximum in fewer tries.** When
the thing you're maximising is *real signal*, that's excellent. When it's *noise*, MCTS finds the lucky
tail of the noise **faster than random guessing would**. Efficiency at maximising a noisy score *is*
efficiency at overfitting.

> 📖 **Overfitting** — building something that fits the past by *luck* rather than by capturing a real
> cause. It looks brilliant on history and fails the moment you trade it.

**This is why we put MCTS on the roadmap instead of in the loop.** Not because it's bad — because it is
a *multiplier*, and you want your measuring instruments verified before you attach a multiplier to them.

#### The three fixes

**Fix 1 — a hard cap: 20 formula attempts per idea.** Enforced by the Planner. Twenty leaves enough
room to find a decent expression of a good idea, while keeping the noise-derived best t-stat at ~2.45 —
comfortably below the 3.0 bar, so a real signal still has to earn its way past.

**Fix 2 — count every attempt.** All 20 go into the ledger.

> 📖 **Trial ledger** — a running count of every test we have ever run against the data. It feeds the
> honesty maths: **the more you tried, the higher the bar a survivor must clear.** Backtests are free in
> money and nearly free in time, but they are *not* free here.

We count *effectively*, not naively: 20 variations of "volume divided by its k-day average" for
k = 5…25 are not 20 independent bets — they're maybe three. The maths we use (Deflated Sharpe) handles
this automatically, because it takes the number of trials **and how similar their results were**.

**Fix 3 — the fresh fold. Confirm the winner on data no variant ever touched.**

This is the elegant one. We split our practice data into two pieces:

```
|<-- TRAIN 3y -->|<----- VAL-A 3.5y ----->|<- VAL-B 1y ->|<=== HOLDOUT 3.5y ===>|
  2015-01→2017-12     2018-01→2021-06        2021-07→        2022-07→2025-12
  warm-up buffer      all 20 attempts        2022-06         sealed vault,
  + CSCV folds        are scored here        only the        opened a counted
  (never selects)     (the search plays)     WINNER          number of times
                                             is scored
                                             here
```

> 📖 **What Train is actually for** — it is *not* where the formula "learns." Nothing is fitted:
> the Coder picks the windows, not the data. Train has two humble jobs: **(1)** give a 252-day rolling
> feature enough history to be computable on day 1 of Val-A, and **(2)** supply extra folds for the
> PBO calculation. **It never picks a winner.** We shrank it from 5 years to 3 and gave the time to
> Val-A, so the search now spans two stress regimes (the 2018 credit crisis *and* COVID) instead of one.

Because **VAL-B is never used to choose anything**, testing the winner there is a genuinely honest
out-of-sample check — **and it costs us nothing from the precious sealed data.**

The cap bounds how much noise-fishing can happen. The fresh fold verifies that the fish is real.
**Neither one alone is enough; together they're strong.**

#### And this becomes our best argument

Here is the flip side, and it belongs on a slide:

> **Because our search is guided by economic theory, it tries far fewer candidates than brute-force
> formula mining. Fewer trials → a smaller honesty penalty → the survivors are genuinely more
> believable.**

A brute-force system that tests 100,000 formulas has to clear an enormous bar. A theory-first system
that tests 200 clears a modest one. **Same statistical machinery, hugely different burden of proof.**

---

### ⚙️ S6 · THE BACKTESTER — one engine, used everywhere

> 📖 **Backtest** — replaying history: "if I had used this signal every day from 2015 to 2024, what
> would have happened?"

The diagram draws it in two places, but it is **one program**, called in eight different situations:

| # | Where | How often |
|---|---|---|
| 1 | Quick test in the implementation loop | **most often** — up to 20× per idea |
| 2 | Fresh-fold confirmation | once per promoted winner |
| 3 | Full rigorous battery | once per finalist |
| 4 | The "leftover information" check | once per finalist |
| 5 | The sealed-vault peek | rarely, and counted |
| 6 | Red-Team attacks | 11 per surviving candidate |
| 7 | Combining the final book | at the very end |
| 8 | Testing our own gates (the ablation) | offline |

One function with switches: *which data slice · how much lag · what trading costs · neutralise by
sector or not · which subset of stocks.*

#### 🎯 The subtle rule: only *choosing* runs count as trials

This is worth having ready, because a sharp reviewer will ask *"doesn't running 11 attacks per candidate
destroy your trial count?"*

**No — and here's the principle.** A test only inflates your risk of a false discovery if you use it to
**pick a winner**. The quick tests in the implementation loop are selection: you take the best of 20, so
they count. The Red-Team attacks can only **kill** a candidate — they can never promote one. A filter
that only rejects **cannot possibly increase your false-discovery rate**, so it needs no penalty at all.

| Runs | Counts as a trial? |
|---|---|
| Quick tests across 20 variants | ✅ yes — you take the best |
| Full battery on the finalist | ✅ yes |
| Sealed-vault peek | counted separately, against its own strict budget |
| **All 11 Red-Team attacks, cost sweeps, lag tests** | ❌ **no — they can only reject** |

---

### 🟩 GATE B · HONESTY — is it NEW, and is it REAL?

Four steps, in this exact order. The order matters, and we changed it deliberately.

#### Step 1 — Remove what we already own

> 📖 **Orthogonalisation / marginal IC** — "orthogonal" means "uncorrelated." If we already own a
> momentum signal, a new signal that's just momentum in disguise adds nothing. So we mathematically
> subtract the part explained by our existing signals, and ask: **does what's left still predict
> anything?** That leftover predictive power is the **marginal IC** — the genuinely *new* information.

> 📖 **IC (Information Coefficient)** — the core score. Each day, correlate your predicted ranking with
> what actually happened, then average across all days. 0 = useless. **0.03–0.05 is already good** in
> daily equities. We use **RankIC** (the version based on ranks) because it's robust to a few crazy
> outliers.

#### Step 2 — Novelty check (**this now runs first**)

Is the leftover information meaningful? If marginal IC ≈ 0, it's a copy of something we own. Reject.

#### Step 3 — The honesty maths, computed on the **leftover** signal

> 📖 **Deflated Sharpe Ratio** — a *corrected* performance number that penalises you for (a) how many
> things you tried before finding this and (b) lumpy, non-normal returns. Try 500 formulas and a raw
> score of 2.0 might deflate to an honest 0.7. It answers: **"given how hard I searched, is this still
> impressive?"**

> 📖 **PBO (Probability of Backtest Overfitting)** — the estimated chance that whatever looked best on
> your practice data is actually *below average* in reality. High PBO means your whole selection process
> is picking lucky noise — a warning about the *method*, not one signal.

#### Step 4 — Only now, one counted peek at the sealed vault

> 📖 **Holdout / lockbox** — the slice of history the search never sees. It stays honest only if you
> touch it almost never. We allow a **fixed, counted number of peeks in the system's lifetime**. When
> they're spent, they're spent.

#### 🔧 Why we reordered this (we caught our own bug)

The design originally ran the maths *first* and the novelty check *second*. Two problems:

1. **The maths step ends by spending a sealed-vault peek** — the scarcest thing we own — while the
   novelty check is essentially free and *already computed*. Under the old order you could burn an
   irreplaceable peek on a signal that novelty was about to reject as a momentum clone. **Free filters
   that protect scarce resources must go first.**

2. **We were measuring the wrong object.** Our stated goal was always *"deflated, vault-checked,
   **leftover** predictive power"* — one combined thing. Doing the maths on the raw signal and *then*
   separately glancing at the leftover is **not the same calculation**. A signal can pass the honesty
   maths on its raw form and have essentially nothing left once you subtract what we already own.
   **The correct object to deflate is the leftover.**

*(One honest nuance: strictly killing every near-duplicate would throw away a clone that's genuinely
**better** than what we own. Real portfolios handle that by **replacement**, not rejection.)*

---

### 🟩 GATE C · RED-TEAM — the prosecutor

**What it does:** actively tries to **destroy** the signal.

The AI agent *chooses* which attacks fit this particular signal; the attacks themselves are
pre-written, parameterised backtests. The agent decides **what**; the code computes **how much**. It
never writes free-form code.

**The full menu — 11 attacks:**

| # | Attack | The failure it hunts |
|---:|---|---|
| 1 | Test each year separately | "it was one lucky year" |
| 2 | Split by market regime (bull / bear / high-volatility) | "it only works in a bull market" |
| 3 | Split by company size | "it's really a small-cap artefact" |
| 4 | Trading costs at 5, 15, 30 bps | "great on paper, loses money in reality" |
| 5 | Delay the whole signal by one extra day | **hidden look-ahead** |
| 6 | Delay just the `delivery %` field | **which specific field is the edge leaning on?** |
| 7 | Neutralise within sector | "it's just a bet on one industry" |
| 8 | Filter out illiquid names | "you couldn't actually trade this" |
| 9 | Decay curve across holding periods | "the claimed horizon is fiction" |
| 10 | Is the direction stable across time slices? | "the sign flips around" |
| 11 | Re-run with known data defects removed | "it depends on a data bug" |

**It survives only if** the signal stays positive and meaningful through the core attacks, and does not
collapse under the extra delay or under realistic trading costs.

> 📖 **Regime** — a type of market environment: bull vs bear, calm vs panicky, high vs low rates. A
> signal that only worked in the 2021 bull run isn't robust; it's a memory of one market.

**Why this exists:** *an idea that has survived a determined attack is far more trustworthy than one
that merely "passed a test."*

---

### 🔵 S9 · MEMORY & REFLECTION — the historian

Every card lands here — accepted **and** rejected.

The Reflection agent writes down what happened and, crucially, *what kind of lesson it is*: which
mechanisms keep working, which keep failing, which formula shapes tend to overfit, which **edit motifs**
help in which situations. It then updates the agents' instructions and tells the Planner which families
deserve more budget.

**This stage is the entire answer to "how does it improve over iterations?"** — one of the four graded
questions. Without it, every run starts from zero and makes the same mistakes.

---

### ⚙️ PORTFOLIO — off to the side

Once several signals have been accepted, a separate step combines them into a low-correlation team and
leans on the ones suited to current conditions.

**We deliberately took this *out* of the main loop**, because Trexquant grades the *signal*, not the
portfolio — and the thing that matters *inside* the loop ("does this add new information?") is already
handled at Gate B. The capability is fully kept; it just runs at the end.

---

## PART 4 — One idea, walked all the way through

**1 · Planner** — the "liquidity" family has been productive; allocate it some budget and a cap of 20
formula attempts.

**2 · Librarian** — pulls papers on the illiquidity premium and volume shocks; checks memory: *we tried
plain volume spikes in generation 3 and they failed without a price-direction filter.* Briefs the team.

**3 · Hypothesis** — writes:
> *"Stocks that just had an abnormal one-day volume spike **on a falling price** are being dumped by
> forced sellers — funds meeting redemptions, margin calls, panic retail. Other investors underreact to
> forced selling because it carries no information about the company. So the price tends to rebound over
> the next 3–5 days."*
>
> Mechanism = underreaction to forced selling. Counterparty = forced and panicking sellers. Not
> arbitraged away because absorbing forced selling requires capital exactly when capital is scarce.
> Horizon = 3–5 days. Regime = works best in calm markets.
> **Pre-registered sign: `+1`** (higher score → higher future return). **Locked.**

**4 · Gate A** — a different AI checks the rubric. All five present, mechanism is specific, counterparty
is named and plausible. **Pass.**

**5 · Implementation loop** — the Coder writes
`rank( ts_mean(volume,1) / ts_mean(volume,20) ) * sign(prev_close − close)`.
Compiles, simple, not a duplicate. Quick test on VAL-A: RankIC 0.031. The Judge says: *"the thesis
claims a 3–5 day horizon but you're measuring 1 day — try a 3-day forward window."* Attempt 2: 0.038.
Attempt 5 adjusts the volume window to 10 days: 0.041. **Attempts used: 7 of 20.** Promote the best.

**6 · Fresh-fold check** — score the winner on VAL-B, which none of those 7 attempts ever touched.
RankIC 0.034. Lower than 0.041 — as expected, some of that was selection luck — but clearly alive.
**Pass.**

**7 · Full battery** — RankIC 0.036, ICIR 0.6, Sharpe 1.4, turnover moderate, decay curve fades by day
6 (consistent with the 3–5 day story ✓). **And the sign is positive, matching the pre-registration ✓.**

> 📖 **ICIR** — how *consistent* the IC is: the average IC divided by how much it wobbles. A signal with
> IC 0.03 *every* day beats one that's +0.20 half the time and −0.14 the rest.

**8 · Gate B** —
Subtract our existing momentum and reversal factors → leftover marginal IC **0.025**. Genuinely new. ✓
Ledger says 143 trials this run, 7 within this thesis. Deflated Sharpe on the leftover = **0.9** —
still positive after the penalty. t = 3.2, clears 3.0. PBO low. ✓
**Spend holdout peek #4 of 12.** Holds up. **Pass.**

**9 · Gate C · Red-Team** — the agent picks 6 of the 11 attacks:
*"Is this just small caps?"* → large-cap only: holds.
*"One lucky year?"* → positive in 7 of 9 years.
*"Survives costs?"* → yes at 15 bps, marginal at 30.
*"Hidden look-ahead?"* → +1-day lag: RankIC 0.029, degraded but alive. ✓
*"Depends on `delivery %` timing?"* → shift it: barely moves. ✓
*"One sector?"* → sector-neutral: holds.
**Survives.**

**10 · Alpha Card issued.** Thesis, locked sign, formula, all reports, full family tree, and the list of
data fields used.

**11 · Memory** — *"Forced-seller underreaction works when combined with a price-direction filter;
plain volume spikes alone failed in gen 3. Useful edit motif: widen the window to match the thesis's
stated horizon. Keep exploring this family."* Planner gets a nudge.

**If it had failed any gate**, the historian would still record exactly *why*, and that lesson would
steer the next idea.

---

## PART 5 — What is genuinely ours

We re-checked our claims against the literature as of September 2026 and found that **two of our four
original "novel" ideas had already been published.** We are conceding those with citations. This is a
strength: a researcher who knows the paper *will* ask, and *"that was published last month — here's what
I claim instead"* is a far better answer than a bluff.

### ① Pre-registered sign + counterparty gate — **genuinely novel** ← our lead

Committing to a direction *before* seeing data, and rejecting on mismatch. The closest existing work
checks whether the formula matches the story *afterwards*, or audits sign logic *after the fact*. **We
found nothing that pre-commits and then rejects.**

### ② Three budgets — and the fact that two of them fight each other — **novel**

Most people see one budget. There are three:

| Budget | Who spends it | Is a backtest expensive here? |
|---|---|---|
| **AI tokens** | the thinking agents | **No** — a backtest is a Python call, ~0 tokens |
| **Computer time** | the backtests | barely |
| **Statistical integrity** | *every* test = one trial; every vault peek is irreplaceable | **Yes — invisibly** |

**The key realisation:** the reason to filter cheaply *before* testing is **budget 3**, not 1 or 2. Ten
thousand careless backtests raise the honesty penalty for *every* signal in the run.

**And budgets 1 and 3 actively conflict.** Token efficiency rewards you for finding the winner in
*fewer* tries. Statistical integrity punishes you for *every* try you made along the way. Any technique
that makes search cleverer at maximising a noisy score is, by the identical mechanism, cleverer at
fooling you. **We haven't found this stated in any paper**, and it's the reason for the variant cap, the
fresh fold, and MCTS being on the roadmap.

### ③ Fixed-menu, rejection-only Red-Team — **differentiated**

Adversarial review exists elsewhere. Ours is different in two defensible ways: the attacks are a **fixed
menu of parameterised tests**, never free-form AI code, so every attack is reproducible; and it is
**rejection-only**, so it *provably cannot* inflate the trial count.

### ④ Statistical gates in the scoring function — **already published. Concede it.**

A 2026 paper (arXiv 2608.27734) already does the trial ledger → Deflated Sharpe → PBO pipeline
integrated into search. **But it hands us something better than the claim we lose.** Its headline
result:

> **A deliberately "leaky" strategy — one that cheats by peeking at the future — posted a Sharpe ratio
> of 35 and sailed through Deflated Sharpe and PBO completely untouched.**

**Statistical gates do not catch cheating. They catch over-searching. Those are different problems.**

Leakage has to be made **impossible by construction** — which is precisely what our causal operator
library does. This reframes our whole pitch around a much better slide:

---

## PART 6 — The slide that carries the design

**Five ways to be wrong. Five different mechanisms. And — the part that shows real understanding — what
each mechanism does *not* cover.**

| How you get fooled | What catches it | What definitely does **not** |
|---|---|---|
| **Cheating (look-ahead)** | Causal operators (structurally impossible) · timing rules · purge & embargo · lag attacks | **Deflated Sharpe and PBO** — proven: a Sharpe-35 cheat survives both |
| **Over-searching** | Deflated Sharpe vs effective trial count · PBO · **20-variant cap** · fresh fold · rationed vault | any amount of economic reasoning |
| **Story-fitting** ("right answer, wrong reason") | **Pre-registered sign** · counterparty rubric · author ≠ judge | IC, Sharpe and DSR all pass it happily |
| **Reinventing what you own** | Formula-tree duplicate check + leftover-IC check | all of the above |
| **Fragility** (one regime, dies on costs) | The 11 Red-Team attacks | everything measured in-sample |

---

## PART 7 — How we grade the FACTORY (not the signal)

Trexquant asked how we'd evaluate the *system*. Different questions entirely:

| Question | Measure |
|---|---|
| **Is it productive?** | ideas → accepted cards · **tokens per accepted alpha** · new information added per generation |
| **Is it honest?** | **False Discovery Rate** = accepted-but-fails-the-vault ÷ accepted |
| **Is it efficient?** | real alpha per token — our headline objective |
| **Do the gates earn their place?** | **ablation** — see below |
| **Is it *actually* learning?** | **error volume**, not error type — see below |

### Ablation — the answer to "isn't this over-engineered?"

> 📖 **Ablation** — turn one component **off** and measure how much worse things get. That *proves* it
> was earning its keep.

We seed the pool with **known-good and known-junk** factors (random ones, deliberately overfit ones,
deliberately cheating ones), then for each gate we report:
- **Catch rate** — how much junk it correctly rejects
- **False-kill rate** — how many good signals it wrongly rejects
- **The headline: FDR with the gate on vs off**

This makes complexity **self-justifying instead of asserted**: *we didn't add gates because papers have
them — we measured what each one catches.*

**We accept the corollary honestly:** you can only make this argument for gates you actually ablate.
That's the real reason the design is presented as nine stages rather than sixteen boxes.

### 🕵️ Detecting *fake* learning

There's a well-argued critique that factor-mining agents only *look* like they're learning: their
mistakes get more sophisticated over time — conceptual → technical → strategic — while **the total
number of mistakes barely moves.**

So we don't just watch the *flavour* of failures. **We track the rejection *volume* per generation and
the pass-rate per gate over time.** Real improvement means fewer errors. Drift means the same number of
errors wearing better clothes. Answering this pre-emptively matters, because "improves over iterations"
is one of the four things being graded.

---

## PART 8 — When things go wrong: our three bad examples

Trexquant explicitly asked to see the system produce something bad. We show three — one from each
family of failure. Each in three beats: **naive result → the system catches it → the fix.**

### ① DATA — our universe source was structurally broken ← open with this

**Naive result.** We were handed a NIFTY 200 constituent file: 37 rebalance snapshots, exactly 200
names in every row, and it *keeps the dead companies* — DHFL, RCOM, SUZLON are all there. It looks
survivorship-free and internally consistent. Every backtest built on it would have run without a
single error.

**What was actually wrong.** **80 of today's 200 NIFTY 200 constituents never appear in it at all** —
RELIANCE, TCS, SBIN, MARUTI, TATASTEEL, ONGC among them. And every one of those 80 has **zero
inclusion/exclusion events**. That is the diagnostic signature: the file was built by replaying a
change-log onto a base seed, so any stock already in the index before the log begins — and never
subsequently churning — was silently never added. Permanent heavyweights fit exactly that profile.
Each row was then padded back up to 200 with mid-caps, which is why the counts look perfect.

**How we caught it.** By checking the file against NSE's own current constituent list — an external
reconciliation. **Not** by any statistical gate. Deflated Sharpe, PBO, purge/embargo and the lag test
would all have passed it silently, because it contaminates the **universe itself** rather than any
single factor. Nothing would ever have thrown an error.

**Why it would have quietly ruined the results.** The missing names are systematically the largest and
most liquid stocks in India. Every liquidity, size and capacity feature would have been computed on a
biased sample, and the size-tercile robustness test would have had no genuine large caps to test on.

**The fix.** We stopped using constituent data altogether and rebuilt the universe from the exchange's
own daily files: each month, the top 200 by trailing 63-day median turnover. Point-in-time by
construction, survivorship-free by construction, and reproducible from primary source by anyone.

### ② STATISTICS — look-ahead leakage

**Naive result.** A factor that accidentally lets same-day information into the return window posts a
spectacular quick-test score. **Caught by** purge & embargo plus the Red-Team's +1-day-lag attack.
**The lesson:** the Deflated Sharpe would have *passed* it — see the Sharpe-35 cheat above. **Leakage is
caught structurally, never statistically.** **The fix:** the causal operator library and the per-field
timing rules.

### ③ ECONOMICS — "right answer, wrong reason"

**Naive result.** A data-mined signal passes the basic IC test handsomely. **Caught by** the
pre-registered sign: it only works in the **opposite** direction to its own stated story. **It's a
thesis failure, not a discovery** — and *no* statistical gate would ever have flagged it. **The fix:**
reject, and record that this mechanism family produces direction-unstable stories.

---

## PART 9 — The honest weak points

Stated openly, because pretending otherwise is worse:

1. **Free open-source models** reason a notch below frontier ones, so our theses will be weaker than a
   production version's. Swapping in a frontier API is a one-line change.
2. **No point-in-time fundamentals** — free Indian fundamental data isn't trustworthy for backtesting,
   so whole factor families (valuation, earnings surprise) are out of reach. This is a **deliberate
   rigor choice**, not an oversight: using bad fundamental data would inject exactly the look-ahead we
   built this system to catch.
3. **Small-sample ablation** — a few-hour prototype gives illustrative, not conclusive, gate statistics.
4. **~1% residual universe inconsistency** we measured but did not fully repair.
5. **`delivery %` publish time** still needs one direct verification.
6. **Sector labels aren't point-in-time** — reclassifications untracked. Minor, since sector is only
   used for optional neutralisation.

---

## PART 10 — What we'd add next, and why not yet

| Extension | What it buys | Why not yet |
|---|---|---|
| **MCTS formula search** | a better formula per test | it's a multiplier on search efficiency — **verify the measuring instruments first** (Part 3) |
| **Code-based evolution** (arbitrary Python instead of formulas) | far more expressive | unbounded complexity, weakens duplicate detection, and **re-opens the look-ahead hole** that the operator library currently closes |
| **Point-in-time fundamentals** | entire new factor families | needs a paid vendor — and *this* is where a per-field data registry would finally earn its keep |
| **Bigger operator library · full-scale run · live-forward test** | scale and an honest forward read | time |

**The sequencing is deliberate, not an omission.** Saying *"we know exactly what we'd add next and
exactly what has to be true first"* reads as judgement. Adding it now and being unable to defend the
statistics would read as the opposite.

---

## APPENDIX — Everything in one page

**The product:** one number per stock per day; the ranking predicts relative next-day returns. Plus an
economic thesis. Both are required.

**The loop:** Planner → Librarian → Hypothesis (+ locked direction) → **Gate A: Economics** →
Implementation (≤20 attempts) → **Fresh-fold check** → Full battery → **Gate B: Honesty** (new? real?)
→ **Gate C: Red-Team** (11 attacks) → Alpha Card → Memory → back to the Planner.

**The four gates:** Economics (before any code) · Pre-filter (free) · Honesty (new, then real, then one
counted peek) · Red-Team (rejection-only).

**The three budgets:** AI tokens · computer time · **statistical integrity** — and the first and third
fight each other.

**The four data regions:** Train (build) · Val-A (search) · Val-B (confirm, never selected against) ·
Holdout (sealed, counted peeks).

**The five failures:** cheating · over-searching · story-fitting · reinventing · fragility — each with
its own mechanism, and each mechanism honest about what it doesn't cover.

**The one principle behind all of it:**

> **Agency where there is a *decision*. Deterministic code where it is a *fixed computation*. All
> verdict maths is code with a fixed threshold — so nothing in the system can talk its way past a gate.**
