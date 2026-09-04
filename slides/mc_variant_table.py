"""Reproduce the search-policy table on slide 11 of slides/deck.html.

If N candidate formulas are all genuinely worthless, the *best* of them still
posts a t-statistic of order sqrt(2 ln N).  That expression is the asymptotic
ceiling; the realised maximum sits about 0.5 below it.  Both belong on the
slide: the ceiling because it is the closed form everyone quotes, the realised
value because it is what a gate actually has to beat.

The decisive column is the last one -- the probability that a pure-noise search
of N variants clears the celebrated "t > 3" bar.

Run:  .venv/Scripts/python.exe slides/mc_variant_table.py
"""
from __future__ import annotations

import numpy as np

NREP = 200_000          # Monte-Carlo searches per row
SEED = 42               # slide states this seed
N_GRID = (1, 5, 20, 100, 200, 500)
CAP = 20                # MAX_VARIANTS_PER_THESIS in src/config.py
T_BAR = 3.0             # T_STAT_BAR in src/config.py


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(f"{NREP:,} Monte-Carlo searches per row, seed {SEED}\n")
    print(f"{'N':>6}  {'sqrt(2 ln N)':>13}  {'realised best t':>16}  {'P(best t > 3)':>14}")
    print("-" * 56)
    for n in N_GRID:
        # A pure-noise IC series of length T has t ~ N(0, 1); searching N of
        # them and keeping the best is the maximum of N standard normals.
        best = rng.standard_normal((NREP, n)).max(axis=1)
        ceiling = float(np.sqrt(2 * np.log(n))) if n > 1 else 0.0
        mark = "   <- our cap" if n == CAP else ""
        print(f"{n:>6}  {ceiling:>13.2f}  {best.mean():>16.2f}  "
              f"{(best > T_BAR).mean() * 100:>13.1f}%{mark}")


if __name__ == "__main__":
    main()
