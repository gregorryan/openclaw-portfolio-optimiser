"""Tests for optimiser.backtest.

We use synthetic returns so the tests are fast and deterministic. The
point is to verify the train/test split *mechanics* and the *contract*
of BacktestResult — not whether real markets generalise, which is a
property of markets, not of our code.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from optimiser.backtest import BacktestResult, backtest
from optimiser.constraints import Constraints
from optimiser.fitness import Objective, portfolio_stats
from optimiser.ga import GAConfig


def _synthetic_returns(
    n_days: int = 600,
    n_tickers: int = 4,
    seed: int = 0,
) -> pd.DataFrame:
    """Build returns where each asset has a slightly different mean."""
    rng = np.random.default_rng(seed)
    means = np.array([(i + 1) * 0.0004 for i in range(n_tickers)])
    vols = np.full(n_tickers, 0.01)
    arr = rng.normal(loc=means, scale=vols, size=(n_days, n_tickers))
    cols = [f"A{i}" for i in range(n_tickers)]
    return pd.DataFrame(arr, columns=cols)


# ---------------------------------------------------------------------
# Split mechanics — the input/output shape contract
# ---------------------------------------------------------------------

def test_train_test_days_sum_to_total():
    returns = _synthetic_returns(n_days=500)
    config = GAConfig(seed=42, population_size=30, n_generations=15)
    result = backtest(returns, Objective.MAX_SHARPE, config=config)

    assert result.train_days + result.test_days == 500


def test_train_fraction_respected():
    returns = _synthetic_returns(n_days=500)
    config = GAConfig(seed=42, population_size=30, n_generations=15)
    result = backtest(
        returns, Objective.MAX_SHARPE, config=config, train_fraction=0.70
    )

    expected_train = int(500 * 0.70)
    assert result.train_days == expected_train
    assert result.test_days == 500 - expected_train


def test_returns_proper_result_object():
    returns = _synthetic_returns()
    config = GAConfig(seed=42, population_size=30, n_generations=15)
    result = backtest(returns, Objective.MAX_SHARPE, config=config)

    assert isinstance(result, BacktestResult)
    assert result.weights.shape == (returns.shape[1],)
    assert result.tickers == tuple(returns.columns)
    assert result.objective is Objective.MAX_SHARPE
    assert 0.0 < result.train_fraction < 1.0


# ---------------------------------------------------------------------
# Weight invariants — the GA's output should still be feasible
# ---------------------------------------------------------------------

def test_weights_sum_to_one():
    returns = _synthetic_returns()
    config = GAConfig(seed=7, population_size=30, n_generations=15)
    result = backtest(returns, Objective.MAX_SHARPE, config=config)

    assert result.weights.sum() == pytest.approx(1.0, rel=1e-9)


def test_constraints_respected():
    returns = _synthetic_returns(n_tickers=6)
    config = GAConfig(seed=7, population_size=30, n_generations=15)
    result = backtest(
        returns,
        Objective.MAX_SHARPE,
        constraints=Constraints(max_weight=0.25),
        config=config,
    )

    assert result.weights.max() <= 0.25 + 1e-9


# ---------------------------------------------------------------------
# Stats consistency — train_stats should match what portfolio_stats says
# when given the same weights and training window
# ---------------------------------------------------------------------

def test_train_stats_match_independent_calculation():
    returns = _synthetic_returns()
    config = GAConfig(seed=42, population_size=30, n_generations=15)
    result = backtest(returns, Objective.MAX_SHARPE, config=config)

    train = returns.iloc[: result.train_days]
    independent = portfolio_stats(result.weights, train)

    assert result.train_stats.sharpe == pytest.approx(independent.sharpe, rel=1e-9)
    assert result.train_stats.expected_return == pytest.approx(
        independent.expected_return, rel=1e-9
    )


def test_test_stats_match_independent_calculation():
    """Same check for the held-out window."""
    returns = _synthetic_returns()
    config = GAConfig(seed=42, population_size=30, n_generations=15)
    result = backtest(returns, Objective.MAX_SHARPE, config=config)

    test = returns.iloc[result.train_days:]
    independent = portfolio_stats(result.weights, test)

    assert result.test_stats.sharpe == pytest.approx(independent.sharpe, rel=1e-9)


def test_sharpe_gap_is_train_minus_test():
    returns = _synthetic_returns()
    config = GAConfig(seed=42, population_size=30, n_generations=15)
    result = backtest(returns, Objective.MAX_SHARPE, config=config)

    assert result.sharpe_gap == pytest.approx(
        result.in_sample_sharpe - result.out_of_sample_sharpe, rel=1e-12
    )


# ---------------------------------------------------------------------
# Validation paths
# ---------------------------------------------------------------------

def test_too_few_rows_raises():
    """If returns is too short to split meaningfully, raise rather than guess."""
    returns = _synthetic_returns(n_days=50)
    config = GAConfig(seed=0, population_size=10, n_generations=5)

    with pytest.raises(ValueError, match="at least"):
        backtest(returns, Objective.MAX_SHARPE, config=config)


@pytest.mark.parametrize("bad_fraction", [0.0, 1.0, -0.1, 1.1])
def test_train_fraction_out_of_range_raises(bad_fraction):
    returns = _synthetic_returns()
    config = GAConfig(seed=0, population_size=10, n_generations=5)

    with pytest.raises(ValueError, match="train_fraction"):
        backtest(
            returns,
            Objective.MAX_SHARPE,
            config=config,
            train_fraction=bad_fraction,
        )


def test_extreme_train_fraction_with_short_test_raises():
    """A 99% train fraction on 500 days leaves only 5 test days — should refuse."""
    returns = _synthetic_returns(n_days=500)
    config = GAConfig(seed=0, population_size=10, n_generations=5)

    with pytest.raises(ValueError, match="test days"):
        backtest(
            returns,
            Objective.MAX_SHARPE,
            config=config,
            train_fraction=0.99,
        )
