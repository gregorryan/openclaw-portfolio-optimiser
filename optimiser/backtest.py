"""Out-of-sample backtest for GA-selected portfolios.

The GA fits portfolio weights to a returns matrix. Backtesting answers a
different question: would those weights have worked on data the GA
didn't see?

This module implements the simplest defensible test — a train/test
split on the time axis:

1. Take T days of returns
2. Use the first `train_fraction * T` days to run the GA (in-sample)
3. Apply the resulting weights to the remaining days (out-of-sample)
4. Report stats for both windows

The gap between in-sample and out-of-sample Sharpe is informative: a
large gap suggests the GA overfit to the training window. A small or
flipped gap suggests the weights generalised — or that you got lucky.

What this module does NOT do:
- Walk-forward refitting (a single fit, a single test)
- Transaction costs (assume free trades, single rebalance at t=0)
- Survivorship bias (uses the current universe back-projected, which is
  unrealistic — listed in README as a known limitation)

For tonight's scope, this honest minimum is the right deliverable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from optimiser.constraints import Constraints
from optimiser.fitness import (
    DEFAULT_RISK_FREE_RATE,
    Objective,
    PortfolioStats,
    portfolio_stats,
)
from optimiser.ga import GAConfig, GAResult, optimise


@dataclass(frozen=True)
class BacktestResult:
    """In-sample fit + out-of-sample evaluation of GA weights."""

    weights: np.ndarray            # the weights the GA found in-sample
    tickers: tuple[str, ...]
    train_stats: PortfolioStats    # performance on the in-sample window
    test_stats: PortfolioStats     # performance on the out-of-sample window
    train_days: int                # number of training observations
    test_days: int                 # number of test observations
    train_fraction: float          # the split ratio used
    objective: Objective
    ga_result: GAResult            # full GA output for inspection

    @property
    def in_sample_sharpe(self) -> float:
        return self.train_stats.sharpe

    @property
    def out_of_sample_sharpe(self) -> float:
        return self.test_stats.sharpe

    @property
    def sharpe_gap(self) -> float:
        """Positive = in-sample beat out-of-sample (typical overfit pattern)."""
        return self.in_sample_sharpe - self.out_of_sample_sharpe


def _validate_split(n_rows: int, train_fraction: float, min_test_days: int) -> int:
    if not 0.0 < train_fraction < 1.0:
        raise ValueError(
            f"train_fraction must be in (0, 1); got {train_fraction}"
        )
    cut = int(n_rows * train_fraction)
    test_days = n_rows - cut
    if test_days < min_test_days:
        raise ValueError(
            f"train_fraction={train_fraction} on {n_rows} rows leaves only "
            f"{test_days} test days; need at least {min_test_days}"
        )
    if cut < min_test_days:
        raise ValueError(
            f"train_fraction={train_fraction} on {n_rows} rows leaves only "
            f"{cut} train days; need at least {min_test_days}"
        )
    return cut


def backtest(
    returns: pd.DataFrame,
    objective: Objective,
    constraints: Constraints | None = None,
    config: GAConfig | None = None,
    train_fraction: float = 0.80,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    min_test_days: int = 60,
) -> BacktestResult:
    """Fit weights on the first slice of `returns`, evaluate on the rest.

    Args:
        returns: T × N DataFrame of asset returns, time-ordered ascending.
        objective: what the GA maximises in-sample.
        constraints: feasibility rules for the GA.
        config: GA hyperparameters.
        train_fraction: portion of the time axis used for fitting (default 0.80).
        risk_free_rate: passed through to fitness calculations.
        min_test_days: minimum required size for both halves (default 60).

    Returns:
        BacktestResult with weights, in-sample stats, and out-of-sample stats.
    """
    if returns.shape[0] < 2 * min_test_days:
        raise ValueError(
            f"returns has {returns.shape[0]} rows; need at least "
            f"{2 * min_test_days} for a meaningful split"
        )

    cut = _validate_split(returns.shape[0], train_fraction, min_test_days)

    train = returns.iloc[:cut]
    test = returns.iloc[cut:]

    # Fit on the training window
    ga_result = optimise(
        train,
        objective,
        constraints=constraints,
        config=config,
        risk_free_rate=risk_free_rate,
    )
    weights = ga_result.weights

    # Evaluate the same weights on both windows. The training-window stats
    # should match the GA's own reported stats (and we re-compute as a
    # sanity check rather than trust the GA's internal numbers).
    train_stats = portfolio_stats(weights, train, risk_free_rate=risk_free_rate)
    test_stats = portfolio_stats(weights, test, risk_free_rate=risk_free_rate)

    return BacktestResult(
        weights=weights,
        tickers=ga_result.tickers,
        train_stats=train_stats,
        test_stats=test_stats,
        train_days=int(cut),
        test_days=int(returns.shape[0] - cut),
        train_fraction=train_fraction,
        objective=objective,
        ga_result=ga_result,
    )
