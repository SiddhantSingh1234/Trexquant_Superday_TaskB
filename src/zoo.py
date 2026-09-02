"""Phase 5 — the alpha zoo (REQUIRED, not a test fixture).

The pre-filter's structural-novelty check (P6 Gate B, step 2) asks *"is this
formula secretly one that already exists?"* — which needs a real reference set.
This module is that set: **35 formulas** —

* **25 transcribed from Kakushadze, *101 Formulaic Alphas* (arXiv:1601.00991).**
  The T5 audit confirmed ~39 of Alpha #1-60 are expressible with our operator
  set once ``if_else`` and ``ts_product`` are added; ``vwap`` is a real field
  (P2 derives it) and ``adv{d}`` is the idiom ``ts_mean(mul(volume, close), d)``.
  **Alpha #56 is skipped — it needs true market capitalisation, which we do not
  have** (``size_proxy`` is a trailing-turnover stand-in, not shares x price).
* **10 classical factors** — 12-1 momentum, short-term reversal, low-volatility,
  illiquidity (Amihud), lottery, 52-week-high proximity, turnover, beta, size,
  volume-shock — every one expressible in our operators.

This doubles as the **crowding defence**: a candidate that is a known published
alpha in disguise is, by definition, crowded, and crowded signals decay fast.

Each entry: ``{"name", "formula", "canonical", "fingerprint", "source"}``.
``is_zoo_duplicate(formula, threshold)`` runs the two-stage
fingerprint -> canonical comparison.
"""
from __future__ import annotations

from difflib import SequenceMatcher

import numpy as np
import pandas as pd

from . import contracts as _contracts
from .ast_tools import canonical, evaluate, fingerprint, parse

# --------------------------------------------------------------------------- #
# Raw formulas                                                                 #
# --------------------------------------------------------------------------- #
# adv{d} idiom  ->  ts_mean(mul(volume, close), d)
_ALPHA101: list[tuple[str, str]] = [
    ("alpha101_002",
     "mul(-1, correlation(rank(delta(log(volume), 2)), "
     "rank(div(sub(close, open), open)), 6))"),
    ("alpha101_003",
     "mul(-1, correlation(rank(open), rank(volume), 10))"),
    ("alpha101_004",
     "mul(-1, ts_rank(rank(low), 9))"),
    ("alpha101_005",
     "mul(rank(sub(open, div(ts_sum(vwap, 10), 10))), "
     "mul(-1, abs(rank(sub(close, vwap)))))"),
    ("alpha101_006",
     "mul(-1, correlation(open, volume, 10))"),
    ("alpha101_008",
     "mul(-1, rank(sub(mul(ts_sum(open, 5), ts_sum(returns, 5)), "
     "delay(mul(ts_sum(open, 5), ts_sum(returns, 5)), 10))))"),
    ("alpha101_012",
     "mul(sign(delta(volume, 1)), mul(-1, delta(close, 1)))"),
    ("alpha101_013",
     "mul(-1, rank(covariance(rank(close), rank(volume), 5)))"),
    ("alpha101_014",
     "mul(mul(-1, rank(delta(returns, 3))), correlation(open, volume, 10))"),
    ("alpha101_016",
     "mul(-1, rank(covariance(rank(high), rank(volume), 5)))"),
    ("alpha101_018",
     "mul(-1, rank(add(add(ts_std(abs(sub(close, open)), 5), sub(close, open)), "
     "correlation(close, open, 10))))"),
    ("alpha101_019",
     "mul(mul(-1, sign(add(sub(close, delay(close, 7)), delta(close, 7)))), "
     "add(1, rank(add(1, ts_sum(returns, 250)))))"),
    ("alpha101_020",
     "mul(mul(mul(-1, rank(sub(open, delay(high, 1)))), "
     "rank(sub(open, delay(close, 1)))), rank(sub(open, delay(low, 1))))"),
    ("alpha101_022",
     "mul(-1, mul(delta(correlation(high, volume, 5), 5), "
     "rank(ts_std(close, 20))))"),
    ("alpha101_026",
     "mul(-1, ts_max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))"),
    ("alpha101_029",
     "add(min(ts_product(rank(rank(scale(log(ts_sum(ts_min(rank(rank(mul(-1, "
     "rank(delta(sub(close, 1), 5))))), 2), 1))))), 1), 5), "
     "ts_rank(delay(mul(-1, returns), 6), 5))"),
    ("alpha101_033",
     "rank(mul(-1, pow(sub(1, div(open, close)), 1)))"),
    ("alpha101_034",
     "rank(add(sub(1, rank(div(ts_std(returns, 2), ts_std(returns, 5)))), "
     "sub(1, rank(delta(close, 1)))))"),
    ("alpha101_035",
     "mul(mul(ts_rank(volume, 32), sub(1, ts_rank(sub(add(close, high), low), "
     "16))), sub(1, ts_rank(returns, 32)))"),
    ("alpha101_038",
     "mul(mul(-1, rank(ts_rank(close, 10))), rank(div(close, open)))"),
    ("alpha101_040",
     "mul(mul(-1, rank(ts_std(high, 10))), correlation(high, volume, 10))"),
    ("alpha101_044",
     "mul(-1, correlation(high, rank(volume), 5))"),
    # --- conditional (if_else) ---
    ("alpha101_001",
     "sub(rank(ts_argmax(signed_power(if_else(lt(returns, 0), "
     "ts_std(returns, 20), close), 2), 5)), 0.5)"),
    ("alpha101_007",
     "if_else(lt(ts_mean(mul(volume, close), 20), volume), "
     "mul(mul(-1, ts_rank(abs(delta(close, 7)), 60)), sign(delta(close, 7))), -1)"),
    ("alpha101_009",
     "if_else(lt(0, ts_min(delta(close, 1), 5)), delta(close, 1), "
     "if_else(lt(ts_max(delta(close, 1), 5), 0), delta(close, 1), "
     "mul(-1, delta(close, 1))))"),
]

_CLASSICAL: list[tuple[str, str]] = [
    ("classical_momentum_12_1",
     "sub(div(delay(close, 21), delay(close, 252)), 1)"),
    ("classical_short_term_reversal",
     "mul(-1, sub(div(close, delay(close, 5)), 1))"),
    ("classical_low_volatility",
     "mul(-1, ts_std(returns, 21))"),
    ("classical_illiquidity_amihud",
     "ts_mean(div(abs(returns), mul(close, volume)), 21)"),
    ("classical_lottery_max_ret",
     "mul(-1, ts_max(returns, 21))"),
    ("classical_52w_high_proximity",
     "div(close, ts_max(close, 252))"),
    ("classical_turnover",
     "mul(-1, ts_mean(mul(volume, close), 21))"),
    ("classical_beta",
     "correlation(returns, sub(returns, demean_cs(returns)), 63)"),
    ("classical_size",
     "mul(-1, size_proxy)"),
    ("classical_volume_shock",
     "div(volume, ts_mean(volume, 21))"),
]

# Alpha101 numbers deliberately NOT transcribed (disclosed):
#   #56 — needs true market cap (cap); we only have size_proxy.
SKIPPED_ALPHA101: dict[str, str] = {
    "alpha101_056": "requires true market capitalisation (cap); "
                    "size_proxy is a trailing-turnover proxy, not shares x price",
}


# --------------------------------------------------------------------------- #
# Build the zoo                                                                #
# --------------------------------------------------------------------------- #
def _build() -> list[dict]:
    entries: list[dict] = []
    for name, formula in _ALPHA101:
        parse(formula)  # fail loudly at import if a transcription is malformed
        entries.append({
            "name": name,
            "formula": formula,
            "canonical": canonical(formula),
            "fingerprint": fingerprint(formula),
            "source": "Kakushadze 2016 (arXiv:1601.00991)",
        })
    for name, formula in _CLASSICAL:
        parse(formula)
        entries.append({
            "name": name,
            "formula": formula,
            "canonical": canonical(formula),
            "fingerprint": fingerprint(formula),
            "source": "classical factor literature",
        })
    return entries


ZOO: list[dict] = _build()
ZOO_BY_NAME: dict[str, dict] = {e["name"]: e for e in ZOO}


# --------------------------------------------------------------------------- #
# Duplicate detection                                                          #
# --------------------------------------------------------------------------- #
def is_zoo_duplicate(formula: str, threshold: float = 1.0) -> tuple[bool, str | None]:
    """Is ``formula`` structurally the same as a zoo entry?

    Two-stage (P5 step 5): compare fingerprints first (a cheap reject), then
    canonical strings.  An exact canonical match is always a duplicate.  With
    ``threshold < 1.0`` a near-match (``SequenceMatcher`` ratio on the canonical
    strings ``>= threshold``) also counts — this is the knob P6's novelty check
    turns down.

    Returns ``(is_duplicate, matched_zoo_name_or_None)``.
    """
    fp = fingerprint(formula)
    canon = canonical(formula)
    best: tuple[float, str] | None = None
    for entry in ZOO:
        if entry["fingerprint"] != fp:
            continue
        if entry["canonical"] == canon:
            return True, entry["name"]
        if threshold < 1.0:
            ratio = SequenceMatcher(None, entry["canonical"], canon).ratio()
            if ratio >= threshold and (best is None or ratio > best[0]):
                best = (ratio, entry["name"])
    if best is not None:
        return True, best[1]
    return False, None


# --------------------------------------------------------------------------- #
# Evaluation panel (for tests / demos — dense, so long windows resolve)        #
# --------------------------------------------------------------------------- #
def demo_panel(n_days: int = 1000, n_symbols: int = 25, seed: int = 42) -> dict:
    """A clean ``{field: date x symbol}`` dict every zoo formula can evaluate on.

    Built from ``contracts.make_fake_ohlcv`` then **densified** (interior gaps
    forward-filled within symbol, symbols with < 300 observations dropped) so
    that the long trailing windows in Alpha #8/#19/#29 resolve to finite values.
    ``returns`` is the adjusted-close pct-change; ``size_proxy`` is
    ``log(ts_mean(close_raw * volume_raw, 63))``; ``sector`` is a static
    round-robin label.
    """
    raw = _contracts.make_fake_ohlcv(n_days=n_days, n_symbols=n_symbols, seed=seed)

    fields: dict[str, pd.DataFrame] = {}
    for col in ("open", "high", "low", "close", "volume", "vwap", "n_trades",
                "close_raw", "volume_raw"):
        wide = raw.pivot(index="date", columns="symbol", values=col).sort_index()
        wide = wide.ffill()
        fields[col] = wide

    # drop symbols that never had enough history
    enough = fields["close"].notna().sum() >= 300
    keep = enough[enough].index
    for k in list(fields):
        fields[k] = fields[k][keep]

    fields["returns"] = fields["close"].pct_change()
    dollar = fields["close_raw"] * fields["volume_raw"]
    fields["size_proxy"] = np.log(
        dollar.rolling(63, min_periods=63).mean().where(lambda d: d > 0)
    )
    rng = np.random.default_rng(seed + 5)
    fields["delivery_pct"] = pd.DataFrame(
        rng.uniform(20.0, 85.0, size=fields["close"].shape),
        index=fields["close"].index, columns=fields["close"].columns,
    )
    sectors = list(_contracts.NSE_SECTORS)
    sec_map = pd.Series(
        [sectors[i % len(sectors)] for i in range(len(keep))], index=keep
    )
    fields["sector"] = pd.DataFrame(
        np.repeat(sec_map.to_numpy()[None, :], len(fields["close"].index), axis=0),
        index=fields["close"].index, columns=keep,
    )
    return fields


if __name__ == "__main__":  # pragma: no cover
    panel = demo_panel()
    print(f"zoo: {len(ZOO)} formulas "
          f"({sum(e['source'].startswith('Kakushadze') for e in ZOO)} Alpha101 "
          f"+ {sum(e['source'].startswith('classical') for e in ZOO)} classical)")
    for e in ZOO:
        out = evaluate(e["formula"], panel)
        n_finite = int(np.isfinite(np.asarray(out, dtype=float)).sum())
        print(f"  {e['name']:<32} finite={n_finite:>7}  fp={e['fingerprint']}")
