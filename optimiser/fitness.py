"""Portfolio fitness functions for the GA.

Given a weight vector w and a returns matrix R (T days × N tickers),
this module computes:

- portfolio mean return (annualised)
- portfolio volatility (annualised)
- Sharpe ratio (excess return over risk-free, divided by vol)

The `evaluate` function dispatches on an Objective enum so the GA can
call one function regardless of what the user asked for.

All numbers are returned in *annualised* units throughout. We assume
252 trading days per year, the standard convention.

Design notes:
- Pure functions. No state, no GA-specific dependencies. The GA imports
  these; tests can hit them directly without instantiating a GA.
- Numpy-first. The GA evaluates fitness thousands of times per run, so
  this code path needs to be fast. No pandas inside the hot loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR: int = 252

# Default risk-free rate (annual). 10y UK gilt is the right benchmark
# for an FTSE-focused tool; ~4% as of mid-2026. Users can override.
DEFAULT_RISK_FREE_RATE: float = 0.04


class Objective(str, Enum):
    """What the GA is trying to maximise (or, for variance, minimise)."""

    MAX_SHARPE = "max_sharpe"
    MIN_VARIANCE = "min_variance"
    MAX_RETURN = "max_return"


@dataclass(frozen=True)
class PortfolioStats:
    """Annualised performance summary for a weight vector."""

    expected_return: float    # annualised mean return
    volatility: float         # annualised standard deviation
    sharpe: float             # (return - rf) / volatility


def _to_array(returns: pd.DataFrame | np.ndarray) -> np.ndarray:
    """Accept a DataFrame (from data.compute_returns) or raw numpy."""
    if isinstance(returns, pd.DataFrame):
        return returns.to_numpy()
    return np.asarray(returns)


def portfolio_stats(
    weights: np.ndarray,
    returns: pd.DataFrame | np.ndarray,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> PortfolioStats:
    """Compute annualised return, vol, and Sharpe for a single weight vector.

    Args:
        weights: 1-D array of length N. Should sum to ~1.0; not enforced
            here, that's the constraint layer's job.
        returns: T × N returns matrix. DataFrame columns must already be
            aligned with `weights`.
        risk_free_rate: annual risk-free rate, e.g. 0.04 for 4%.

    Returns:
        PortfolioStats with three annualised numbers.
    """
    R = _to_array(returns)
    w = np.asarray(weights, dtype=float)

    if R.ndim != 2:
        raise ValueError(f"returns must be 2-D; got shape {R.shape}")
    if w.shape[0] != R.shape[1]:
        raise ValueError(
            f"weight vector length {w.shape[0]} does not match "
            f"returns column count {R.shape[1]}"
        )

    # Portfolio daily returns: each row dot w
    port_daily = R @ w

    mean_daily = float(np.mean(port_daily))
    std_daily = float(np.std(port_daily, ddof=1))

    # Annualise. Mean scales linearly with time, std scales with sqrt(time).
    annual_return = mean_daily * TRADING_DAYS_PER_YEAR
    annual_vol = std_daily * np.sqrt(TRADING_DAYS_PER_YEAR)

    # Guard against degenerate near-zero vol (floating-point noise on
    # constant series) producing astronomical Sharpe values.
    if annual_vol < 1e-10:
        sharpe = 0.0
    else:
        sharpe = (annual_return - risk_free_rate) / annual_vol

    return PortfolioStats(
        expected_return=annual_return,
        volatility=annual_vol,
        sharpe=sharpe,
    )


def evaluate(
    weights: np.ndarray,
    returns: pd.DataFrame | np.ndarray,
    objective: Objective,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """Single scalar fitness value the GA tries to maximise.

    For MIN_VARIANCE we return *negative* variance so the GA can always
    maximise. The wrapper is intentional: the GA is dumb, the objective
    layer is smart.
    """
    stats = portfolio_stats(weights, returns, risk_free_rate=risk_free_rate)

    if objective is Objective.MAX_SHARPE:
        return stats.sharpe
    if objective is Objective.MIN_VARIANCE:
        return -(stats.volatility ** 2)
    if objective is Objective.MAX_RETURN:
        return stats.expected_return

    raise ValueError(f"unknown objective: {objective!r}")
