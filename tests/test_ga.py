"""Tests for optimiser.ga.

We use synthetic returns matrices throughout so the tests are
deterministic, fast, and don't hit yfinance. The point is to verify
the GA's *behaviour*, not its performance against real markets — that
gets validated by the smoke test, not the test suite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from optimiser.constraints import Constraints
from optimiser.fitness import Objective, portfolio_stats
from optimiser.ga import (
    GAConfig,
    GAResult,
    optimise,
)


def _synthetic_returns(
    n_days: int = 500,
    n_tickers: int = 4,
    seed: int = 0,
) -> pd.DataFrame:
    """Build a returns DataFrame where some assets are clearly better."""
    rng = np.random.default_rng(seed)
    # Asset i has mean return (i+1)*0.0005, all the same vol.
    means = np.array([(i + 1) * 0.0005 for i in range(n_tickers)])
    vols = np.full(n_tickers, 0.01)

    returns = rng.normal(loc=means, scale=vols, size=(n_days, n_tickers))
    cols = [f"A{i}" for i in range(n_tickers)]
    return pd.DataFrame(returns, columns=cols)


# ---------------------------------------------------------------------
# Reproducibility — same seed, same result
# ---------------------------------------------------------------------

def test_ga_is_deterministic_given_a_seed():
    returns = _synthetic_returns()
    config = GAConfig(seed=123, population_size=50, n_generations=30)

    result_a = optimise(returns, Objective.MAX_SHARPE, config=config)
    result_b = optimise(returns, Objective.MAX_SHARPE, config=config)

    np.testing.assert_allclose(result_a.weights, result_b.weights, rtol=1e-12)
    assert result_a.fitness == result_b.fitness


def test_different_seeds_explore_different_paths():
    returns = _synthetic_returns()
    config_a = GAConfig(seed=1, population_size=30, n_generations=20)
    config_b = GAConfig(seed=2, population_size=30, n_generations=20)

    result_a = optimise(returns, Objective.MAX_SHARPE, config=config_a)
    result_b = optimise(returns, Objective.MAX_SHARPE, config=config_b)

    # Different seeds should give different fitness histories. Both may
    # converge to the same neighbourhood, but the *trajectory* differs.
    assert result_a.fitness_history != result_b.fitness_history


# ---------------------------------------------------------------------
# Elitism — best fitness must never decrease
# ---------------------------------------------------------------------

def test_fitness_history_is_monotonically_non_decreasing():
    """Elitism (keeping the best individual each gen) guarantees this."""
    returns = _synthetic_returns()
    config = GAConfig(seed=42, population_size=50, n_generations=50, elitism=1)

    result = optimise(returns, Objective.MAX_SHARPE, config=config)

    history = result.fitness_history
    for i in range(1, len(history)):
        assert history[i] >= history[i - 1] - 1e-12, (
            f"fitness decreased at gen {i}: {history[i-1]} -> {history[i]}"
        )


# ---------------------------------------------------------------------
# Constraint compliance
# ---------------------------------------------------------------------

def test_ga_result_weights_sum_to_one():
    returns = _synthetic_returns()
    config = GAConfig(seed=7, population_size=30, n_generations=20)

    result = optimise(returns, Objective.MAX_SHARPE, config=config)

    assert result.weights.sum() == pytest.approx(1.0, rel=1e-9)


def test_ga_respects_max_weight_cap():
    returns = _synthetic_returns(n_tickers=6)
    config = GAConfig(seed=7, population_size=30, n_generations=20)
    constraints = Constraints(max_weight=0.25)

    result = optimise(
        returns, Objective.MAX_SHARPE,
        constraints=constraints, config=config,
    )

    assert result.weights.max() <= 0.25 + 1e-9


def test_ga_respects_excluded_tickers():
    returns = _synthetic_returns(n_tickers=5)
    config = GAConfig(seed=7, population_size=30, n_generations=20)
    constraints = Constraints(excluded_tickers=("A0", "A1"))

    result = optimise(
        returns, Objective.MAX_SHARPE,
        constraints=constraints, config=config,
    )

    # The excluded names must have exactly zero weight.
    weights_dict = result.as_dict()
    assert weights_dict["A0"] == 0.0
    assert weights_dict["A1"] == 0.0
    # The remaining weights still sum to 1.
    assert result.weights.sum() == pytest.approx(1.0, rel=1e-9)


# ---------------------------------------------------------------------
# Optimisation effectiveness — GA should actually do something
# ---------------------------------------------------------------------

def test_ga_beats_equal_weight_on_clearly_better_universe():
    """Synthetic returns are designed so concentrating in the best asset
    gives a higher Sharpe than equal-weighting. The GA should find this."""
    returns = _synthetic_returns(n_days=2000, n_tickers=4, seed=10)
    config = GAConfig(seed=42, population_size=80, n_generations=60)

    result = optimise(returns, Objective.MAX_SHARPE, config=config)

    # Equal-weight baseline
    n = len(returns.columns)
    ew = np.ones(n) / n
    ew_stats = portfolio_stats(ew, returns)

    assert result.stats.sharpe > ew_stats.sharpe, (
        f"GA Sharpe {result.stats.sharpe:.4f} did not beat "
        f"equal-weight {ew_stats.sharpe:.4f}"
    )


def test_max_sharpe_and_min_variance_disagree():
    """The two objectives should generally pick different portfolios.
    Max-Sharpe rewards return; min-variance rewards smoothness."""
    returns = _synthetic_returns(n_days=2000, n_tickers=4, seed=10)
    config = GAConfig(seed=42, population_size=80, n_generations=60)

    sharpe_result = optimise(returns, Objective.MAX_SHARPE, config=config)
    minvar_result = optimise(returns, Objective.MIN_VARIANCE, config=config)

    # If the two objectives produced *identical* weights we'd suspect a
    # bug. Some tolerance because GA outputs are stochastic across runs
    # but with fixed seed they're deterministic, so we can be strict.
    assert not np.allclose(sharpe_result.weights, minvar_result.weights, atol=0.01)


# ---------------------------------------------------------------------
# GAResult dataclass
# ---------------------------------------------------------------------

def test_ga_result_as_dict_pairs_tickers_with_weights():
    returns = _synthetic_returns()
    config = GAConfig(seed=0, population_size=20, n_generations=10)

    result = optimise(returns, Objective.MAX_SHARPE, config=config)

    weights_dict = result.as_dict()
    assert set(weights_dict.keys()) == set(returns.columns)
    assert sum(weights_dict.values()) == pytest.approx(1.0, rel=1e-9)


def test_ga_returns_proper_result_object():
    returns = _synthetic_returns()
    config = GAConfig(seed=0, population_size=20, n_generations=10)

    result = optimise(returns, Objective.MAX_SHARPE, config=config)

    assert isinstance(result, GAResult)
    assert result.objective == Objective.MAX_SHARPE
    assert len(result.fitness_history) == 10
    assert result.config is config
    assert result.tickers == tuple(returns.columns)


# ---------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------

def test_single_ticker_universe():
    """Degenerate but should not crash. Optimal weight is 1.0."""
    returns = _synthetic_returns(n_tickers=1)
    config = GAConfig(seed=0, population_size=10, n_generations=5)

    result = optimise(returns, Objective.MAX_SHARPE, config=config)

    assert result.weights[0] == pytest.approx(1.0, rel=1e-9)
