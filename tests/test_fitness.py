"""Tests for optimiser.fitness.

All tests use synthetic returns matrices with known properties so we can
check the maths against hand-calculable answers, not just "did it run".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from optimiser.fitness import (
    DEFAULT_RISK_FREE_RATE,
    TRADING_DAYS_PER_YEAR,
    Objective,
    PortfolioStats,
    evaluate,
    portfolio_stats,
)


# ---------------------------------------------------------------------
# portfolio_stats — annualisation correctness
# ---------------------------------------------------------------------

def test_zero_returns_give_zero_stats():
    """A flat returns matrix should produce zero return and zero vol."""
    returns = np.zeros((100, 3))
    weights = np.array([1 / 3, 1 / 3, 1 / 3])

    stats = portfolio_stats(weights, returns)

    assert stats.expected_return == pytest.approx(0.0, abs=1e-12)
    assert stats.volatility == pytest.approx(0.0, abs=1e-12)
    # By contract, Sharpe is 0 when vol is below the floating-point floor.
    assert stats.sharpe == 0.0


def test_constant_positive_return_annualises_correctly():
    """A constant 0.001 daily return should annualise to 0.252."""
    n_days = 500
    returns = np.full((n_days, 1), 0.001)
    weights = np.array([1.0])

    stats = portfolio_stats(weights, returns)

    expected_annual = 0.001 * TRADING_DAYS_PER_YEAR
    assert stats.expected_return == pytest.approx(expected_annual, rel=1e-10)
    # Std of a constant series should be effectively 0 (floating-point
    # noise means we cannot expect exact equality, but it should be tiny).
    assert stats.volatility < 1e-10
    # The production guard kicks in when vol < 1e-10, returning exact 0.
    assert stats.sharpe == 0.0


def test_known_vol_annualises_with_sqrt_252():
    """Daily std of 0.01 should annualise to 0.01 * sqrt(252) ≈ 0.1587."""
    rng = np.random.default_rng(seed=0)
    n_days = 10_000  # large sample so empirical std ≈ population std
    returns = rng.normal(loc=0.0, scale=0.01, size=(n_days, 1))
    weights = np.array([1.0])

    stats = portfolio_stats(weights, returns)

    expected_vol = 0.01 * np.sqrt(TRADING_DAYS_PER_YEAR)
    assert stats.volatility == pytest.approx(expected_vol, rel=0.02)


def test_weight_dot_product_combines_correctly():
    """Two assets with opposite returns and 50/50 weights should give zero."""
    n_days = 100
    asset_a = np.full(n_days, 0.002)
    asset_b = np.full(n_days, -0.002)
    returns = np.column_stack([asset_a, asset_b])
    weights = np.array([0.5, 0.5])

    stats = portfolio_stats(weights, returns)

    assert stats.expected_return == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------
# portfolio_stats — input validation
# ---------------------------------------------------------------------

def test_weight_length_mismatch_raises():
    returns = np.zeros((100, 3))
    weights = np.array([0.5, 0.5])  # wrong length

    with pytest.raises(ValueError, match="does not match"):
        portfolio_stats(weights, returns)


def test_1d_returns_raises():
    returns = np.zeros(100)  # 1-D, should be 2-D
    weights = np.array([1.0])

    with pytest.raises(ValueError, match="must be 2-D"):
        portfolio_stats(weights, returns)


def test_accepts_dataframe_input():
    """The function should accept a pandas DataFrame, not just a numpy array."""
    dates = pd.bdate_range(end="2026-05-12", periods=100)
    returns_df = pd.DataFrame(
        {"X": np.full(100, 0.001), "Y": np.full(100, 0.002)},
        index=dates,
    )
    weights = np.array([0.5, 0.5])

    stats = portfolio_stats(weights, returns_df)

    assert isinstance(stats, PortfolioStats)
    assert stats.expected_return == pytest.approx(0.0015 * TRADING_DAYS_PER_YEAR, rel=1e-10)


# ---------------------------------------------------------------------
# Sharpe ratio with custom risk-free rate
# ---------------------------------------------------------------------

def test_sharpe_uses_default_rf_rate():
    """Sharpe should reflect the DEFAULT_RISK_FREE_RATE when not overridden."""
    rng = np.random.default_rng(seed=1)
    returns = rng.normal(loc=0.0005, scale=0.01, size=(2000, 1))
    weights = np.array([1.0])

    stats = portfolio_stats(weights, returns)

    expected_sharpe = (stats.expected_return - DEFAULT_RISK_FREE_RATE) / stats.volatility
    assert stats.sharpe == pytest.approx(expected_sharpe, rel=1e-10)


def test_sharpe_respects_custom_rf_rate():
    """Passing a custom rf rate should shift the Sharpe accordingly."""
    rng = np.random.default_rng(seed=2)
    returns = rng.normal(loc=0.0005, scale=0.01, size=(2000, 1))
    weights = np.array([1.0])

    stats_default = portfolio_stats(weights, returns)
    stats_zero_rf = portfolio_stats(weights, returns, risk_free_rate=0.0)

    # Sharpe with rf=0 is just annual_return / annual_vol.
    expected_zero_rf = stats_default.expected_return / stats_default.volatility
    assert stats_zero_rf.sharpe == pytest.approx(expected_zero_rf, rel=1e-10)


# ---------------------------------------------------------------------
# evaluate — objective dispatch
# ---------------------------------------------------------------------

def test_evaluate_max_sharpe_matches_stats():
    rng = np.random.default_rng(seed=3)
    returns = rng.normal(loc=0.0005, scale=0.01, size=(500, 2))
    weights = np.array([0.6, 0.4])

    stats = portfolio_stats(weights, returns)
    fitness = evaluate(weights, returns, Objective.MAX_SHARPE)

    assert fitness == pytest.approx(stats.sharpe, rel=1e-10)


def test_evaluate_min_variance_returns_negative_variance():
    """Min-variance fitness should be -(volatility^2) — GA always maximises."""
    rng = np.random.default_rng(seed=4)
    returns = rng.normal(loc=0.0, scale=0.01, size=(500, 2))
    weights = np.array([0.5, 0.5])

    stats = portfolio_stats(weights, returns)
    fitness = evaluate(weights, returns, Objective.MIN_VARIANCE)

    assert fitness == pytest.approx(-(stats.volatility ** 2), rel=1e-10)
    assert fitness <= 0.0


def test_evaluate_max_return_matches_stats():
    rng = np.random.default_rng(seed=5)
    returns = rng.normal(loc=0.001, scale=0.01, size=(500, 1))
    weights = np.array([1.0])

    stats = portfolio_stats(weights, returns)
    fitness = evaluate(weights, returns, Objective.MAX_RETURN)

    assert fitness == pytest.approx(stats.expected_return, rel=1e-10)
