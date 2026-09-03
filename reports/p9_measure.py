"""Measured values for reports/p9_handoff.md."""
import sys
sys.path.insert(0, r"E:\Trexquant_Superday")
import numpy as np, pandas as pd
from src import backtester as bt, contracts as C, redteam as RT
from src.ledger import Ledger
import tests.test_p9_redteam as T

feats, labs, latz = T._persistent_panel()
bt.use_panel(feats, labs)
prices = C.make_fake_ohlcv(n_days=T.N_DAYS, n_symbols=T.N_SYMBOLS, seed=T.SEED)

def line(k, v): print(f"{k:<48} {v}")

# --- clean survivor ---
lg = Ledger(":memory:")
out = RT.run_redteam(latz, split=T.SPLIT, horizon=1, prices=prices, ledger=lg)
line("survivor verdict", out["verdict"])
line("survivor failed_tests", out["failed_tests"])
line("survivor flagged_diagnostics", out["flagged_diagnostics"])
line("survivor baseline rank_ic", round(out["baseline"]["rank_ic"], 5))
line("survivor baseline t_stat", round(out["baseline"]["t_stat"], 3))
line("survivor n_backtests", out["n_backtests"])
line("ledger n_trials (must be 0)", lg.n_trials())
line("ledger total rows", len(lg.trial_records(counts_only=False)))
line("all rows counts_as_trial==0",
     all(r["counts_as_trial"] == 0 for r in lg.trial_records(counts_only=False)))
cs = out["results"]["cost_sweep"]
line("survivor cost_sweep gross/net15 sharpe",
     (round(cs["gross_sharpe"], 2), round(cs["net_sharpe_15bps"], 2)))
el = out["results"]["extra_lag"]
line("survivor extra_lag base/lagged rank_ic",
     (round(el["base_rank_ic"], 4), round(el["rank_ic_lagged"], 4)))
ue = out["results"]["universe_edge"]
line("survivor universe_edge n_fringe / ic (fallback path)",
     (ue["n_fringe_names"], round(ue["rank_ic_without_fringe"], 4)))
line("universe_edge fringe_source (fallback)", ue["fringe_source"][:70])

# primary path: pass a P1-shaped liquidity_ranks frame built from the fixture prices
from src import universe as U
_ranks = U.build_liquidity_ranks(U.compute_selection(prices))
uep = RT.run_redteam(latz, tests=["universe_edge"], split=T.SPLIT, horizon=1,
                     liquidity_ranks=_ranks, ledger=Ledger(":memory:"))["results"]["universe_edge"]
line("universe_edge PRIMARY path source", uep["fringe_source"][:55])
line("universe_edge PRIMARY n_fringe / ic",
     (uep["n_fringe_names"], round(uep["rank_ic_without_fringe"], 4)))

# --- leaky killed by extra_lag ---
leaky = labs.pivot_table(index="date", columns="symbol", values="fwd_ret_1")
o2 = RT.run_redteam(leaky, split=T.SPLIT, horizon=1, prices=prices, ledger=Ledger(":memory:"))
line("leaky verdict / failed", (o2["verdict"], o2["failed_tests"]))
line("leaky extra_lag base/lagged",
     (round(o2["results"]["extra_lag"]["base_rank_ic"], 3),
      round(o2["results"]["extra_lag"]["rank_ic_lagged"], 4)))

# --- one lucky year killed by subsample_year ---
rng = np.random.default_rng(T.SEED + 5)
noise = pd.DataFrame(rng.standard_normal(latz.shape), index=latz.index, columns=latz.columns)
sig = noise.copy(); yr = sig.index.year
sig.loc[yr == 2019] = latz.loc[yr == 2019]
o3 = RT.run_redteam(sig, split=T.SPLIT, horizon=1, prices=prices, ledger=Ledger(":memory:"))
r3 = o3["results"]["subsample_year"]
line("one-year verdict / failed", (o3["verdict"], o3["failed_tests"]))
line("one-year dropped_year / ic_without_best",
     (r3["dropped_year"], round(r3["rank_ic_without_best_year"], 5)))

# --- high turnover thin edge killed by cost_sweep ---
churn = pd.DataFrame(np.random.default_rng(T.SEED + 9).standard_normal(latz.shape),
                     index=latz.index, columns=latz.columns)
thin = 0.05 * latz + churn
o4 = RT.run_redteam(thin, split=T.SPLIT, horizon=1, prices=prices, ledger=Ledger(":memory:"))
c4 = o4["results"]["cost_sweep"]
line("thin verdict / failed", (o4["verdict"], o4["failed_tests"]))
line("thin cost_sweep gross/net15 sharpe",
     (round(c4["gross_sharpe"], 3), round(c4["net_sharpe_15bps"], 3)))

# --- sign flip killed by sign_stability ---
flip = np.where(latz.index.year % 2 == 0, 1.0, -1.0)
o5 = RT.run_redteam(latz.mul(flip, axis=0), split=T.SPLIT, horizon=1, prices=prices,
                    ledger=Ledger(":memory:"))
line("flip verdict / failed", (o5["verdict"], o5["failed_tests"]))
line("flip sign consistency", round(o5["results"]["sign_stability"]["consistency"], 3))

# --- delivery_lag localization mechanic ---
ff = C.make_fake_features(n_days=900, n_symbols=T.N_SYMBOLS, seed=7)
fl = C.make_fake_labels(n_days=900, n_symbols=T.N_SYMBOLS, seed=7)
planted = ff.pivot_table(index="date", columns="symbol", values="mom_21")
ff = ff.merge(planted.stack(future_stack=True).rename_axis(["date", "symbol"])
              .rename("dp").reset_index(), on=["date", "symbol"])
ff["delivery_pct"] = ff.pop("dp").astype(float)
ff["date"] = ff["date"].astype("datetime64[ns]")
bt.clear_panel(); bt.use_panel(ff, fl)
od = RT.run_redteam(planted, tests=["delivery_lag"], split=T.SPLIT, horizon=1,
                    formula="delivery_pct",
                    panel={"delivery_pct": planted, "close": planted.abs() + 1,
                           "volume": planted.abs() + 1},
                    prices=prices, ledger=Ledger(":memory:"))
d = od["results"]["delivery_lag"]
line("delivery_lag base/shifted rank_ic",
     (round(d["base_rank_ic"], 4), round(d["rank_ic_delivery_lagged"], 4)))

# --- expanding-regime look-ahead proof (labeller lives in the backtester now) ---
bt.clear_panel(); bt.use_panel(feats, labs)
full = bt._regime_labels(labs)
months = np.sort(labs["date"].unique())
tr = bt._regime_labels(labs[labs["date"].isin(months[: int(len(months) * 0.55)])])
line("regime bull/bear/highvol days (full)",
     (int(full['bull'].sum()), int(full['bear'].sum()), int(full['highvol'].sum())))
line("regime truncation-invariant on overlap", full.loc[tr.index].equals(tr))
rs = RT.run_redteam(latz, split=T.SPLIT, horizon=1, prices=prices,
                    ledger=Ledger(":memory:"))["results"]["regime_split"]
line("regime_split decisive_comparable / flag",
     (rs.get("decisive_comparable"), rs["flag"]))
