"""Phase 0 — schema validators + synthetic fixture generators.

Two things live here, one per artifact in IMPLEMENTATION_PLAN.md Section 0.5:

* ``validate_<name>(df) -> None`` — raises ``SchemaError`` with a message that
  names the exact offending column on any violation.
* ``make_fake_<name>(...) -> DataFrame`` — the **fixture generators**. Every
  downstream phase is built and tested against these instead of waiting for real
  upstream data, so they aim to be realistic, not merely schema-valid.

No business logic (no features, no backtester, no agents) — contracts + fixtures
only.

Planted signal
--------------
``make_fake_features`` and ``make_fake_labels`` share a deterministic latent
(keyed only by ``seed``/shape, independent of call order). Feature column
``mom_21`` is set to the per-day cross-sectional z-score of that latent, and the
fake forward returns are ``PLANTED_IC * latent + noise``. Consequently
``mom_21`` has a genuine mean-daily RankIC of ~``PLANTED_IC`` (= 0.04) against
``fwd_ret_1_demeaned``. Downstream phases use this to prove their machinery can
detect a real signal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import RANDOM_SEED

# Forward-return horizons (days). Matches P3 step 3 and the Metrics decay keys.
HORIZONS: tuple[int, ...] = (1, 2, 3, 5, 10, 21)

# The genuine RankIC planted into the fake panel (mom_21 vs fwd_ret_1_demeaned).
PLANTED_IC: float = 0.04

# NSE's 22 official industries (Section 0.5 / P3), used to label fake sectors.
NSE_SECTORS: tuple[str, ...] = (
    "Automobile and Auto Components", "Capital Goods", "Chemicals",
    "Construction", "Construction Materials", "Consumer Durables",
    "Consumer Services", "Diversified", "Fast Moving Consumer Goods",
    "Financial Services", "Forest Materials", "Healthcare",
    "Information Technology", "Media Entertainment & Publication",
    "Metals & Mining", "Oil Gas & Consumable Fuels", "Power", "Realty",
    "Services", "Telecommunication", "Textiles", "Utilities",
)

_LEGACY_ERA_END = pd.Timestamp("2019-09-30")


class SchemaError(AssertionError):
    """Raised by ``validate_*`` when a frame violates its Section 0.5 contract."""


# --------------------------------------------------------------------------- #
# Generic validation helpers                                                   #
# --------------------------------------------------------------------------- #
def _is_datetime(s: pd.Series) -> bool:
    return pd.api.types.is_datetime64_ns_dtype(s) and getattr(s.dt, "tz", None) is None


def _is_float64(s: pd.Series) -> bool:
    return s.dtype == np.float64


def _is_bool(s: pd.Series) -> bool:
    return pd.api.types.is_bool_dtype(s)


def _is_string(s: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)


_DTYPE_CHECKS = {
    "datetime": (_is_datetime, "timezone-naive datetime64[ns]"),
    "float64": (_is_float64, "float64"),
    "bool": (_is_bool, "bool"),
    "string": (_is_string, "string/object"),
}


def _validate_frame(df, name: str, dtypes: dict[str, str],
                    allow_all_nan: frozenset[str] = frozenset()) -> None:
    """Shared checks: type, columns present, dtypes, sort order, dup keys, NaN.

    ``allow_all_nan`` names columns that may legitimately be entirely NaN — a
    genuinely partial-coverage field (e.g. ``delivery_pct``, which does not exist
    before 2019-09-30 and is NaN for all of TRAIN even on real data, and is NaN
    everywhere when P3 runs on the synthetic fixture per the spec's Inputs note).
    """
    if not isinstance(df, pd.DataFrame):
        raise SchemaError(f"[{name}] expected a pandas DataFrame, got {type(df)!r}")

    for col, kind in dtypes.items():
        if col not in df.columns:
            raise SchemaError(f"[{name}] missing required column: {col!r}")
        check, human = _DTYPE_CHECKS[kind]
        if not check(df[col]):
            raise SchemaError(
                f"[{name}] column {col!r} must be {human}, got dtype "
                f"{df[col].dtype!r}"
            )

    # No all-NaN columns (except explicitly allowed partial-coverage fields).
    for col in dtypes:
        if col in allow_all_nan:
            continue
        if len(df) > 0 and df[col].isna().all():
            raise SchemaError(f"[{name}] column {col!r} is entirely NaN")

    # (date, symbol) key discipline.
    if "date" in dtypes and "symbol" in dtypes:
        dup = df.duplicated(["date", "symbol"])
        if dup.any():
            first = df.loc[dup, ["date", "symbol"]].iloc[0].to_dict()
            raise SchemaError(
                f"[{name}] duplicate (date, symbol) key(s): "
                f"{int(dup.sum())} row(s), e.g. {first}"
            )
        ordered = df.sort_values(["date", "symbol"]).reset_index(drop=True)
        if not df.reset_index(drop=True).equals(ordered):
            raise SchemaError(
                f"[{name}] rows are not sorted by (date, symbol) with a reset "
                f"index"
            )


# --------------------------------------------------------------------------- #
# Per-artifact validators                                                      #
# --------------------------------------------------------------------------- #
_MEMBERSHIP_DTYPES = {"date": "datetime", "symbol": "string", "in_universe": "bool"}

_OHLCV_DTYPES = {
    "date": "datetime", "symbol": "string",
    "open": "float64", "high": "float64", "low": "float64", "close": "float64",
    "volume": "float64", "close_raw": "float64", "volume_raw": "float64",
    "vwap": "float64", "n_trades": "float64",
    "isin": "string", "source": "string", "series": "string",
}

# NSE series retained in the panel (P2 decision — see reports/p2_handoff.md).
OHLCV_SERIES_ALLOWED: frozenset[str] = frozenset({"EQ", "BE"})

_FEATURE_COLS = (
    "mom_21", "mom_126", "rev_5", "vol_21", "beta_63", "amihud_21",
    "turnover_21", "dist_52wh", "max_ret_21", "delivery_pct", "size_proxy",
)
_FEATURES_DTYPES = {
    "date": "datetime", "symbol": "string",
    **{c: "float64" for c in _FEATURE_COLS},
    "sector": "string",
}

_LABEL_COLS = tuple(f"fwd_ret_{h}" for h in HORIZONS) + tuple(
    f"fwd_ret_{h}_demeaned" for h in HORIZONS
)
_LABELS_DTYPES = {
    "date": "datetime", "symbol": "string",
    **{c: "float64" for c in _LABEL_COLS},
}


def validate_membership(df) -> None:
    _validate_frame(df, "membership", _MEMBERSHIP_DTYPES)


def validate_ohlcv(df) -> None:
    _validate_frame(df, "ohlcv", _OHLCV_DTYPES)
    if len(df) == 0:
        return
    if (df["close"] <= 0).any():
        raise SchemaError("[ohlcv] column 'close' has non-positive values")
    if (df["high"] < df["low"]).any():
        raise SchemaError("[ohlcv] column 'high' is below 'low' on some rows")
    if (df["volume"] < 0).any():
        raise SchemaError("[ohlcv] column 'volume' has negative values")
    bad_vwap = (df["vwap"] < df["low"]) | (df["vwap"] > df["high"])
    if bad_vwap.any():
        raise SchemaError(
            f"[ohlcv] column 'vwap' outside [low, high] on {int(bad_vwap.sum())} "
            f"row(s)"
        )
    bad_series = set(df["series"].dropna().unique()) - OHLCV_SERIES_ALLOWED
    if bad_series:
        raise SchemaError(
            f"[ohlcv] column 'series' has values outside {sorted(OHLCV_SERIES_ALLOWED)}: "
            f"{sorted(bad_series)}"
        )


# delivery_pct is a genuinely partial field: NSE delivery data starts 2019-09-30,
# so it is all-NaN for TRAIN even on real data, and all-NaN when P3 runs on the
# synthetic fixture (spec P3 Inputs: "emit delivery_pct ... as NaN and note it").
_FEATURES_ALLOW_ALL_NAN = frozenset({"delivery_pct"})


def validate_features(df) -> None:
    _validate_frame(df, "features", _FEATURES_DTYPES,
                    allow_all_nan=_FEATURES_ALLOW_ALL_NAN)
    if len(df) and (df["dist_52wh"].dropna() > 1e-9).any():
        raise SchemaError("[features] column 'dist_52wh' must be <= 0 by construction")


def validate_labels(df) -> None:
    _validate_frame(df, "labels", _LABELS_DTYPES)


def validate_symbols_json(payload: dict) -> None:
    name = "symbols.json"
    if not isinstance(payload, dict):
        raise SchemaError(f"[{name}] expected a dict, got {type(payload)!r}")
    for key in ("symbols", "n", "renames"):
        if key not in payload:
            raise SchemaError(f"[{name}] missing required key: {key!r}")
    if not isinstance(payload["symbols"], list) or not all(
        isinstance(s, str) for s in payload["symbols"]
    ):
        raise SchemaError(f"[{name}] key 'symbols' must be a list of strings")
    if payload["n"] != len(payload["symbols"]):
        raise SchemaError(
            f"[{name}] key 'n' ({payload['n']}) != len(symbols) "
            f"({len(payload['symbols'])})"
        )
    if len(set(payload["symbols"])) != len(payload["symbols"]):
        raise SchemaError(f"[{name}] key 'symbols' contains duplicates")
    if not isinstance(payload["renames"], dict):
        raise SchemaError(f"[{name}] key 'renames' must be a dict")


# --------------------------------------------------------------------------- #
# Fixture generation helpers                                                   #
# --------------------------------------------------------------------------- #
def _bdays(n_days: int, start: str = "2015-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start=start, periods=n_days).normalize()


def _symbol_list(n_symbols: int) -> list[str]:
    return [f"SYM{i:03d}" for i in range(n_symbols)]


def _planted_latent(dates: pd.DatetimeIndex, symbols: list[str], seed: int) -> pd.DataFrame:
    """Deterministic date x symbol standard-normal latent shared by features/labels.

    Depends only on ``seed`` and shape, so ``make_fake_features`` and
    ``make_fake_labels`` agree regardless of call order.
    """
    rng = np.random.default_rng(seed + 90_210)
    arr = rng.standard_normal((len(dates), len(symbols)))
    return pd.DataFrame(arr, index=dates, columns=symbols)


def _xs_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    mu = frame.mean(axis=1)
    sd = frame.std(axis=1, ddof=0).replace(0.0, np.nan)
    return frame.sub(mu, axis=0).div(sd, axis=0)


def _long(frame: pd.DataFrame, value_name: str) -> pd.DataFrame:
    out = (
        frame.stack(future_stack=True)
        .rename_axis(["date", "symbol"])
        .rename(value_name)
        .reset_index()
    )
    return out


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize().astype("datetime64[ns]")
    df["symbol"] = df["symbol"].astype(str)
    return df.sort_values(["date", "symbol"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Fixture generators                                                           #
# --------------------------------------------------------------------------- #
def make_fake_ohlcv(
    n_days: int = 800, n_symbols: int = 40, seed: int = RANDOM_SEED
) -> pd.DataFrame:
    """Geometric-random-walk OHLCV, ~25% annualized vol.

    Realism features downstream survivorship / gap logic can bite on:

    * ~25% annualized volatility geometric random walk per symbol.
    * occasional missing (symbol, day) rows (~1.5%) — trading gaps.
    * ~1 in 12 symbols stops trading partway through and never returns
      (delisting-like).
    * ``vwap`` always within ``[low, high]``; ``close`` strictly positive.
    * ``source`` tagged by era (legacy bhavcopy vs sec_bhavdata_full).
    """
    rng = np.random.default_rng(seed)
    dates = _bdays(n_days)
    symbols = _symbol_list(n_symbols)

    daily_sigma = 0.25 / np.sqrt(252.0)
    frames = []
    for j, sym in enumerate(symbols):
        p0 = float(rng.uniform(40.0, 2000.0))
        drift = float(rng.normal(0.0, 0.0002))
        rets = rng.normal(drift, daily_sigma, size=n_days)
        close = p0 * np.exp(np.cumsum(rets))

        prev_close = np.concatenate([[p0], close[:-1]])
        overnight = rng.normal(0.0, daily_sigma * 0.6, size=n_days)
        open_ = prev_close * np.exp(overnight)
        intraday = np.abs(rng.normal(0.0, daily_sigma, size=n_days)) + 1e-4
        hi = np.maximum(open_, close) * (1.0 + intraday)
        lo = np.minimum(open_, close) * (1.0 - intraday)

        base_vol = float(rng.uniform(5e4, 5e6))
        volume = base_vol * np.exp(rng.normal(0.0, 0.5, size=n_days))
        avg_trade = float(rng.uniform(400.0, 6000.0))
        n_trades = np.maximum(np.round(volume / avg_trade), 1.0)

        vwap = (open_ + hi + lo + close) / 4.0
        vwap = np.clip(vwap, lo, hi)

        df = pd.DataFrame({
            "date": dates,
            "symbol": sym,
            "open": open_, "high": hi, "low": lo, "close": close,
            "volume": volume,
            "close_raw": close,          # fixture: adjusted == raw
            "volume_raw": volume,
            "vwap": vwap,
            "n_trades": n_trades,
            "isin": f"INFAKE{j:05d}01",
            "source": np.where(dates < _LEGACY_ERA_END,
                               "bhavcopy_legacy", "sec_bhavdata_full"),
            # ~1 symbol in 8 sits on the BE (trade-to-trade) series — a distress
            # signal P2 deliberately keeps; the rest are EQ.
            "series": "BE" if (j % 8 == 0) else "EQ",
        })

        # ~1 in 12 symbols stops trading partway through.
        if n_days > 20 and rng.random() < (1.0 / 12.0):
            cutoff = int(rng.integers(n_days // 2, n_days - 1))
            df = df.iloc[:cutoff]

        frames.append(df)

    out = pd.concat(frames, ignore_index=True)

    # Occasional single-day gaps (~1.5% of rows).
    keep = rng.random(len(out)) > 0.015
    out = out.loc[keep].reset_index(drop=True)

    for col in ("open", "high", "low", "close", "volume", "close_raw",
                "volume_raw", "vwap", "n_trades"):
        out[col] = out[col].astype(np.float64)
    return _finalize(out)


def make_fake_membership(
    n_days: int = 800, n_symbols: int = 40, seed: int = RANDOM_SEED
) -> pd.DataFrame:
    """Daily boolean membership panel with genuine rotation.

    Most symbols are members throughout; a handful join late or leave early so
    downstream survivorship logic sees a moving universe.
    """
    rng = np.random.default_rng(seed + 7)
    dates = _bdays(n_days)
    symbols = _symbol_list(n_symbols)

    in_uni = pd.DataFrame(True, index=dates, columns=symbols)
    n_movers = max(1, n_symbols // 6)
    movers = rng.choice(symbols, size=n_movers, replace=False)
    for sym in movers:
        if rng.random() < 0.5:                       # joins late
            start = int(rng.integers(1, max(2, n_days // 2)))
            in_uni.iloc[:start, in_uni.columns.get_loc(sym)] = False
        else:                                        # leaves early
            stop = int(rng.integers(max(2, n_days // 2), n_days))
            in_uni.iloc[stop:, in_uni.columns.get_loc(sym)] = False

    out = _long(in_uni, "in_universe")
    out["in_universe"] = out["in_universe"].astype(bool)
    return _finalize(out)


def make_fake_features(
    n_days: int = 800, n_symbols: int = 40, seed: int = RANDOM_SEED
) -> pd.DataFrame:
    """Correlated feature panel. ``mom_21`` carries the planted signal.

    Features load on a small set of latent factors so they are cross-sectionally
    correlated (as real style factors are). ``mom_21`` is set exactly to the
    per-day z-score of the shared planted latent (see module docstring), so its
    RankIC against ``make_fake_labels`` fwd returns is ~``PLANTED_IC`` (0.04).
    """
    rng = np.random.default_rng(seed + 11)
    dates = _bdays(n_days)
    symbols = _symbol_list(n_symbols)
    shape = (n_days, n_symbols)

    n_factors = 3
    factors = [rng.standard_normal(shape) for _ in range(n_factors)]

    def styled(scale: float, noise: float) -> np.ndarray:
        loads = rng.normal(0.0, 1.0, size=n_factors)
        base = sum(l * f for l, f in zip(loads, factors))
        return scale * (base + noise * rng.standard_normal(shape))

    planted = _xs_zscore(_planted_latent(dates, symbols, seed))

    cols: dict[str, np.ndarray] = {
        "mom_126": styled(0.15, 0.8),
        "rev_5": styled(0.05, 1.0),
        "vol_21": np.abs(styled(0.15, 0.6)) + 0.05,
        "beta_63": 1.0 + styled(0.4, 0.7),
        "amihud_21": np.abs(styled(2.0, 0.9)) + 0.01,
        "turnover_21": 15.0 + styled(1.5, 0.8),
        "max_ret_21": np.abs(styled(0.04, 0.7)) + 0.005,
        "delivery_pct": np.clip(45.0 + styled(15.0, 0.9), 1.0, 99.0),
        "size_proxy": 18.0 + styled(1.2, 0.7),
    }

    frame_cols = {"mom_21": planted}
    for name, arr in cols.items():
        frame_cols[name] = pd.DataFrame(arr, index=dates, columns=symbols)

    # dist_52wh <= 0 by construction.
    frame_cols["dist_52wh"] = pd.DataFrame(
        -np.abs(styled(0.15, 0.8)), index=dates, columns=symbols
    )

    merged = None
    for name, frame in frame_cols.items():
        piece = _long(frame, name)
        merged = piece if merged is None else merged.merge(piece, on=["date", "symbol"])

    # static (non point-in-time) sector label per symbol
    sec_rng = np.random.default_rng(seed + 13)
    sector_map = {s: NSE_SECTORS[int(sec_rng.integers(len(NSE_SECTORS)))] for s in symbols}
    merged["sector"] = merged["symbol"].map(sector_map).astype(str)

    for c in _FEATURE_COLS:
        merged[c] = merged[c].astype(np.float64)
    return _finalize(merged)


def make_fake_labels(
    n_days: int = 800, n_symbols: int = 40, seed: int = RANDOM_SEED
) -> pd.DataFrame:
    """Forward-return labels with a planted RankIC of ~``PLANTED_IC`` (0.04).

    For each horizon ``h``: ``fwd_ret_h = PLANTED_IC * latent + noise_h`` where
    ``latent`` is the shared planted latent (module docstring) and ``noise_h``
    scales with ``sqrt(h)``. ``fwd_ret_h_demeaned`` is the cross-sectional
    (per-day) demean and **is the label**. Feature ``mom_21`` from
    ``make_fake_features`` — the per-day z-score of the same latent — therefore
    has mean-daily RankIC ~0.04 against ``fwd_ret_1_demeaned``.
    """
    rng = np.random.default_rng(seed + 17)
    dates = _bdays(n_days)
    symbols = _symbol_list(n_symbols)

    latent = _xs_zscore(_planted_latent(dates, symbols, seed))
    latent_arr = latent.to_numpy()

    merged = None
    for h in HORIZONS:
        # corr(PLANTED_IC*latent, PLANTED_IC*latent + sqrt(h)*noise) = PLANTED_IC
        # / sqrt(PLANTED_IC**2 + h)  ->  ~PLANTED_IC for h=1. The 0.02 scale just
        # puts the labels at a plausible daily-return magnitude.
        noise = rng.normal(0.0, np.sqrt(h), size=(n_days, n_symbols))
        raw = 0.02 * (PLANTED_IC * latent_arr + noise)
        raw_df = pd.DataFrame(raw, index=dates, columns=symbols)
        dem_df = raw_df.sub(raw_df.mean(axis=1), axis=0)

        for frame, col in ((raw_df, f"fwd_ret_{h}"), (dem_df, f"fwd_ret_{h}_demeaned")):
            piece = _long(frame, col)
            merged = piece if merged is None else merged.merge(
                piece, on=["date", "symbol"]
            )

    for c in _LABEL_COLS:
        merged[c] = merged[c].astype(np.float64)
    return _finalize(merged)


def make_fake_symbols(n: int = 315, seed: int = RANDOM_SEED) -> dict:
    """A plausible symbols.json payload (Section 0.5 shape).

    Used by P2 as a fallback when P1 has not run. Includes the four canonical
    renames and a sample known-defect entry.
    """
    rng = np.random.default_rng(seed + 19)
    base = [f"SYM{i:03d}" for i in range(n)]
    # sprinkle a few special-character tickers like the real universe
    for i, special in enumerate(("M&M", "J&KBANK", "BAJAJ-AUTO", "ARE&M", "COX&KINGS")):
        if i < n:
            base[i] = special
    rng.shuffle(base)
    return {
        "symbols": base,
        "n": len(base),
        "renames": {
            "CAIRN": "VEDL", "GRUH": "BANDHANBNK",
            "CMC": "TCS", "BHARATFIN": "INDUSINDBK",
        },
        "known_defects": [
            {"symbol": "IREDA", "issue": "phantom constituent", "action": "removed"}
        ],
    }
