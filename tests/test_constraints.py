"""Tests for optimiser.constraints.

Exercise the repair operator across the full matrix of constraint
combinations: long-only, max-weight caps, exclusions, min holdings.
Also cover the explicit infeasibility paths.
"""

from __future__ import annotations

import numpy as np
import pytest

from optimiser.constraints import (
    Constraints,
    InfeasibleConstraints,
    default_constraints,
    repair,
)


# ---------------------------------------------------------------------
# Constraints dataclass — validation in __post_init__
# ---------------------------------------------------------------------

def test_default_constraints_are_permissive():
    c = default_constraints()
    assert c.long_only is True
    assert c.max_weight == 1.0
    assert c.min_holdings == 1
    assert c.excluded_tickers == ()


def test_max_weight_must_be_in_unit_interval():
    with pytest.raises(ValueError, match="max_weight"):
        Constraints(max_weight=0.0)
    with pytest.raises(ValueError, match="max_weight"):
        Constraints(max_weight=1.5)
    with pytest.raises(ValueError, match="max_weight"):
        Constraints(max_weight=-0.1)


def test_min_holdings_must_be_at_least_one():
    with pytest.raises(ValueError, match="min_holdings"):
        Constraints(min_holdings=0)


# ---------------------------------------------------------------------
# repair — basic correctness
# ---------------------------------------------------------------------

def test_repair_already_feasible_weights_unchanged():
    """A clean equal-weight vector should pass through untouched."""
    tickers = ("A", "B", "C", "D")
    w = np.array([0.25, 0.25, 0.25, 0.25])
    result = repair(w, tickers, default_constraints())

    np.testing.assert_allclose(result, w, rtol=1e-12)


def test_repair_sums_to_one():
    """Whatever the input, output must sum to 1.0 within tolerance."""
    tickers = ("A", "B", "C")
    w = np.array([0.5, 2.0, -1.0])
    result = repair(w, tickers, default_constraints())

    assert result.sum() == pytest.approx(1.0, rel=1e-10)


def test_repair_long_only_clips_negatives():
    tickers = ("A", "B", "C")
    w = np.array([0.5, -0.3, 0.8])
    result = repair(w, tickers, default_constraints())

    assert (result >= 0.0).all()


def test_repair_respects_max_weight():
    tickers = ("A", "B", "C", "D")
    w = np.array([0.9, 0.05, 0.03, 0.02])
    constraints = Constraints(max_weight=0.40)
    result = repair(w, tickers, constraints)

    assert result.max() <= 0.40 + 1e-10
    assert result.sum() == pytest.approx(1.0, rel=1e-10)


def test_repair_zeros_excluded_tickers():
    tickers = ("LLOY.L", "BARC.L", "AZN.L", "GSK.L")
    w = np.array([0.3, 0.3, 0.2, 0.2])
    constraints = Constraints(excluded_tickers=("LLOY.L", "BARC.L"))
    result = repair(w, tickers, constraints)

    assert result[0] == 0.0  # LLOY.L
    assert result[1] == 0.0  # BARC.L
    assert result[2:].sum() == pytest.approx(1.0, rel=1e-10)


def test_repair_handles_all_zero_input():
    """An all-zero weight vector should be replaced with equal weights."""
    tickers = ("A", "B", "C", "D")
    w = np.zeros(4)
    result = repair(w, tickers, default_constraints())

    np.testing.assert_allclose(result, np.full(4, 0.25), rtol=1e-12)


def test_repair_combines_constraints():
    """Exclude banks + cap at 35% + handle ragged input — all at once."""
    tickers = ("LLOY.L", "BARC.L", "AZN.L", "GSK.L", "SHEL.L")
    w = np.array([0.4, 0.4, -0.1, 0.5, 0.8])
    constraints = Constraints(
        max_weight=0.35,
        excluded_tickers=("LLOY.L", "BARC.L"),
    )
    result = repair(w, tickers, constraints)

    # Excluded
    assert result[0] == 0.0
    assert result[1] == 0.0
    # All non-negative
    assert (result >= 0.0).all()
    # Cap respected
    assert result.max() <= 0.35 + 1e-10
    # Sums to 1
    assert result.sum() == pytest.approx(1.0, rel=1e-10)


# ---------------------------------------------------------------------
# repair — infeasibility paths
# ---------------------------------------------------------------------

def test_repair_raises_when_max_weight_too_low():
    """5 tickers × 10% cap = 50% max total — infeasible."""
    tickers = ("A", "B", "C", "D", "E")
    w = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    constraints = Constraints(max_weight=0.10)

    with pytest.raises(InfeasibleConstraints, match="caps total weight"):
        repair(w, tickers, constraints)


def test_repair_raises_when_too_few_holdings_available():
    """Excluding too many leaves fewer than min_holdings."""
    tickers = ("A", "B", "C")
    w = np.array([1 / 3, 1 / 3, 1 / 3])
    constraints = Constraints(
        min_holdings=3,
        excluded_tickers=("A", "B"),  # only 1 left, need 3
    )

    with pytest.raises(InfeasibleConstraints, match="min_holdings"):
        repair(w, tickers, constraints)


def test_repair_raises_when_weights_length_mismatches_tickers():
    tickers = ("A", "B", "C")
    w = np.array([0.5, 0.5])  # too short

    with pytest.raises(ValueError, match="does not match"):
        repair(w, tickers, default_constraints())
