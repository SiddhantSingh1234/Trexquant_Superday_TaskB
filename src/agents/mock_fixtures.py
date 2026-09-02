"""Phase 8 — canned, deterministic agent responses for ``LLM_MODE=mock``.

Every fixture is ``fn(prompt, schema) -> dict`` and returns a **schema-valid**
object.  They sniff a few hints out of the prompt (``family=…``, ``rank_ic=…``,
``iteration=…``) so the mock refinement loop actually converges and the Coder
returns a formula that parses under the Phase-5 grammar.

``COMPLETION_TOKENS`` is the per-role completion size the mock bills.  The
values are the PRE_BUILD_TASKS T3 "tokens/call" figures (Coder/Judge trimmed
slightly for the static-prefix cache), so a full mock thesis lands near the
26,500-token projection.
"""
from __future__ import annotations

import re

COMPLETION_TOKENS: dict[str, int] = {
    "hypothesis": 3300,
    "redteam": 2400,
    "coder": 1400,
    "judge": 1100,
    "economics": 1900,
    "planner": 1000,
    "librarian": 1000,
    "reflection": 1000,
}

# Pre-registered direction the mock Hypothesis agent commits to, by family.
_SIGN_BY_FAMILY = {
    "momentum": 1, "trend": 1, "liquidity": 1, "quality_proxy": 1,
    "value_proxy": 1, "seasonality": 1, "size": 1, "microstructure": 1,
    "reversal": -1, "volatility": -1, "sentiment": -1, "sentiment_proxy": -1,
}

# A known-good, Phase-5-parseable formula per family.
_FORMULA_BY_FAMILY = {
    "momentum": "rank(sub(delay(close,1), delay(close,21)))",
    "trend": "sign(sub(ts_mean(close,10), ts_mean(close,50)))",
    "reversal": "mul(-1, rank(sub(close, delay(close,5))))",
    "liquidity": "rank(div(ts_mean(volume,5), ts_mean(volume,20)))",
    "volatility": "mul(-1, rank(ts_std(returns,21)))",
    "microstructure": "rank(div(volume, n_trades))",
    "seasonality": "rank(ts_mean(returns,5))",
    "value_proxy": "mul(-1, rank(size_proxy))",
    "quality_proxy": "mul(-1, rank(ts_std(returns,63)))",
    "sentiment_proxy": "rank(delivery_pct)",
    "size": "mul(-1, rank(size_proxy))",
}
_DEFAULT_FORMULA = "rank(div(ts_mean(volume,5), ts_mean(volume,20)))"

_REFINE_MOTIFS = ("widen_ts_window", "add_sector_neutral", "switch_level_to_rank")


# --------------------------------------------------------------------------- #
# prompt sniffers                                                              #
# --------------------------------------------------------------------------- #
def _sniff(prompt: str, key: str, default: str = "") -> str:
    m = re.search(rf"{re.escape(key)}\s*[:=]\s*([A-Za-z0-9_./+-]+)", prompt)
    return m.group(1) if m else default


def _sniff_float(prompt: str, key: str, default: float = 0.0) -> float:
    m = re.search(rf"{re.escape(key)}\s*[:=]\s*(-?[0-9]*\.?[0-9]+)", prompt)
    return float(m.group(1)) if m else default


def _sniff_int(prompt: str, key: str, default: int = 0) -> int:
    m = re.search(rf"{re.escape(key)}\s*[:=]\s*(-?[0-9]+)", prompt)
    return int(m.group(1)) if m else default


def _sniff_bool(prompt: str, key: str, default: bool = True) -> bool:
    v = _sniff(prompt, key, str(default)).lower()
    return v in ("1", "true", "yes", "helped", "y")


def _names_from_prompt(prompt: str) -> list[str]:
    return re.findall(r'"name"\s*:\s*"([^"]+)"', prompt)


# --------------------------------------------------------------------------- #
# the eight fixtures                                                           #
# --------------------------------------------------------------------------- #
def _planner(prompt, schema) -> dict:
    fam = _sniff(prompt, "top_family") or _sniff(prompt, "family") or "liquidity"
    return {
        "family": fam,
        "token_budget": 40_000,
        "max_variants": 8,
        "rationale": (
            f"bandit allocation favours {fam}; recent deltas positive and the "
            f"family is under-explored this generation"
        ),
    }


def _librarian(prompt, schema) -> dict:
    names = _names_from_prompt(prompt)
    angles = names[:3]
    if angles:
        brief = (
            "Tradeable angles from the corpus: "
            + "; ".join(angles)
            + ". These rely only on price/volume/turnover we actually have. "
            "Anomalies needing fundamentals, short interest or options are "
            "excluded below and must not be proposed."
        )
    else:
        brief = (
            "No tradeable corpus anomaly matches this family with our data "
            "(price/volume/turnover only). Do not propose fundamentals- or "
            "sentiment-data ideas; consider a price-based mechanism instead."
        )
    return {
        "brief": brief,
        "suggested_angles": angles,
        "rationale": "keyword+family retrieval over the free-abstract corpus",
    }


def _hypothesis(prompt, schema) -> dict:
    fam = _sniff(prompt, "family") or "liquidity"
    horizon = _sniff_int(prompt, "horizon_hint", 5) or 5
    sign = _SIGN_BY_FAMILY.get(fam, 1)
    return {
        "mechanism": (
            f"{fam} pressure: constrained intermediaries widen the price of "
            f"immediacy, so recent {fam} imbalance predicts a partial reversal "
            f"as inventory normalises over ~{horizon} days"
        ),
        "counterparty": (
            "rule-based rebalancers and liquidity demanders who trade on a "
            "schedule regardless of price"
        ),
        "why_not_arbitraged": (
            "capacity-constrained: the effect lives in mid-cap names where "
            "position limits and turnover costs deter large arbitrageurs"
        ),
        "horizon_days": horizon,
        "regime": "calm",
        "falsifiable_claim": (
            f"a cross-sectional {fam} signal has RankIC of sign {sign} and "
            f"t-stat > 3 on VAL_A, and the sign holds on the fresh fold VAL_B"
        ),
        "pre_registered_sign": sign,
    }


def _economics(prompt, schema) -> dict:
    return {
        "verdict": "pass",
        "scores": {
            "mechanism": 2, "counterparty": 2, "why_not_arbitraged": 2,
            "falsifiable_claim": 2, "horizon_plausibility": 2,
        },
        "reasons": [
            "identifies a specific counterparty and a capacity constraint",
            "claim is falsifiable with a pre-committed sign and horizon",
        ],
    }


def _coder(prompt, schema) -> dict:
    fam = _sniff(prompt, "family") or ""
    formula = _FORMULA_BY_FAMILY.get(fam, _DEFAULT_FORMULA)
    return {
        "formula": formula,
        "rationale": (
            f"encodes the {fam or 'liquidity'} mechanism as a cross-sectional "
            f"rank of a trailing ratio; all operators are causal"
        ),
    }


def _judge(prompt, schema) -> dict:
    rank_ic = _sniff_float(prompt, "rank_ic", 0.0)
    iteration = _sniff_int(prompt, "iteration", 1)
    horizon = _sniff_int(prompt, "horizon", 5)
    if rank_ic >= 0.02 or iteration >= 3:
        return {
            "action": "promote",
            "edit_motif": "promote_as_is",
            "reason": (
                f"RankIC {rank_ic:.3f} clears the screening bar (or the variant "
                f"cap is near); stop refining and send to the fresh fold"
            ),
        }
    return {
        "action": "refine",
        "edit_motif": _REFINE_MOTIFS[iteration % len(_REFINE_MOTIFS)],
        "reason": (
            f"RankIC {rank_ic:.3f} is thin; widen the trailing window toward the "
            f"stated {horizon}-day horizon before giving up"
        ),
    }


def _redteam(prompt, schema) -> dict:
    return {
        # includes one hallucinated name on purpose — the agent must drop it.
        "tests": [
            "subsample_year", "regime_split", "extra_lag", "cost_sweep",
            "decay_curve", "sign_stability", "custom_montecarlo",
        ],
        "rationale": (
            "cross-sectional price/volume signal: probe one-lucky-year, "
            "regime dependence, hidden look-ahead, net-of-cost survival and "
            "whether the claimed horizon and sign are real"
        ),
    }


def _reflection(prompt, schema) -> dict:
    fam = _sniff(prompt, "family") or "liquidity"
    motif = _sniff(prompt, "edit_motif") or "widen_ts_window"
    helped = _sniff_bool(prompt, "helped", True)
    delta = _sniff_float(prompt, "rank_ic_delta", 0.005)
    return {
        "lesson": {
            "motif": motif,
            "helped": helped,
            "confidence": 0.6,
            "family": fam,
            "parent_context": f"{fam} volume-ratio factor, thesis horizon 3-5d",
            "outcome": f"{'helped' if helped else 'hurt'}: RankIC delta {delta:+.3f}",
        },
        "edit_motif": motif,
        "bandit_update": {"family": fam, "reward": float(delta), "tokens": 1200},
    }


FIXTURES: dict = {
    "planner": _planner,
    "librarian": _librarian,
    "hypothesis": _hypothesis,
    "economics": _economics,
    "coder": _coder,
    "judge": _judge,
    "redteam": _redteam,
    "reflection": _reflection,
}
