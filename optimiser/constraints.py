"""Portfolio constraints and repair operator.

Represents user constraints as a structured object and projects any
candidate weight vector back into the feasible region. This is the
'repair' strategy for constraint handling: rather than penalising
infeasible solutions, we transform them into feasible ones before
evaluation.

Repair operations applied, in order:
1. Zero out weights for excluded tickers
2. Clip negative weights to zero (long-only enforcement)
3. Renormalise to sum to 1
4. Where any weight exceeds max_weight, pin it at the cap and
   redistribute the excess across the remaining feasible names;
   iterate until stable.

If the constraints are infeasible (e.g. max_weight too low for the
universe size, or excluded set too aggressive), we raise
InfeasibleConstraints rather than silently producing nonsense.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


class InfeasibleConstraints(Exception):
    """Raised when no weight vector can satisfy the constraints."""


@dataclass(frozen=True)
class Constraints:
    """User-specified portfolio constraints.

    Attributes:
        long_only: if True, weights must be >= 0
        max_weight: maximum weight per name (e.g. 0.10 for 10% cap)
        min_holdings: minimum number of non-zero positions
        excluded_tickers: tickers that must have zero weight
    """

    long_only: bool = True
    max_weight: float = 1.0
    min_holdings: int = 1
    excluded_tickers: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not 0.0 < self.max_weight <= 1.0:
            raise ValueError(
                f"max_weight must be in (0, 1]; got {self.max_weight}"
            )
        if self.min_holdings < 1:
            raise ValueError(
                f"min_holdings must be >= 1; got {self.min_holdings}"
            )

    def feasible_universe_size(self, total_tickers: int) -> int:
        """How many tickers are available after exclusions."""
        return total_tickers - len(self.excluded_tickers)

    def check_feasibility(self, tickers: tuple[str, ...] | list[str]) -> None:
        """Verify these constraints can be satisfied for the given universe."""
        available = self.feasible_universe_size(len(tickers))

        if available < self.min_holdings:
            raise InfeasibleConstraints(
                f"min_holdings={self.min_holdings} but only {available} "
                f"tickers remain after exclusions"
            )

        # max_weight * available must be >= 1 for weights to sum to 1
        if self.max_weight * available < 1.0:
            raise InfeasibleConstraints(
                f"max_weight={self.max_weight} across {available} available "
                f"tickers caps total weight at {self.max_weight * available:.2f}, "
                f"below the required 1.0"
            )


def default_constraints() -> Constraints:
    """Sensible defaults: long-only, no concentration limit, no exclusions."""
    return Constraints()


def repair(
    weights: np.ndarray,
    tickers: tuple[str, ...] | list[str],
    constraints: Constraints,
) -> np.ndarray:
    """Project an arbitrary weight vector into the constraint set.

    Args:
        weights: 1-D array, same length as `tickers`. May be infeasible.
        tickers: ordered ticker symbols, used to apply exclusions by name.
        constraints: the rules to enforce.

    Returns:
        A feasible weight vector that sums to 1.0 (within float tolerance).

    Raises:
        InfeasibleConstraints: if no feasible solution exists.
    """
    constraints.check_feasibility(tickers)

    w = np.asarray(weights, dtype=float).copy()

    if w.shape[0] != len(tickers):
        raise ValueError(
            f"weights length {w.shape[0]} does not match tickers length {len(tickers)}"
        )

    # Step 1: zero out excluded tickers
    excluded_set = set(constraints.excluded_tickers)
    excluded_mask = np.array([t in excluded_set for t in tickers], dtype=bool)
    available_mask = ~excluded_mask
    w[excluded_mask] = 0.0

    # Step 2: long-only — clip negatives
    if constraints.long_only:
        w = np.maximum(w, 0.0)

    # Pathological input: all zeros across the available universe.
    # Fall back to equal-weight over the available names.
    if w[available_mask].sum() <= 0.0:
        n_available = int(available_mask.sum())
        w = np.where(available_mask, 1.0 / n_available, 0.0)

    # Step 3-4: iterate clip-and-redistribute until weights are stable.
    # A single pass isn't sufficient: clipping a weight down redistributes
    # mass to others, which may push them over the cap. Iterate until
    # no more clipping is needed (typically 2-4 iterations).
    for _ in range(50):
        # Always start each iteration with weights summing to 1.
        total = w[available_mask].sum()
        if total <= 0.0:
            n_available = int(available_mask.sum())
            w = np.where(available_mask, 1.0 / n_available, 0.0)
            continue
        w[available_mask] = w[available_mask] / total
        w[excluded_mask] = 0.0

        over_cap = w > constraints.max_weight
        if not over_cap.any():
            break

        # Pin all over-cap weights at max_weight.
        excess_mass = float(w[over_cap].sum() - over_cap.sum() * constraints.max_weight)
        w[over_cap] = constraints.max_weight

        # Distribute released mass across non-excluded, non-capped names.
        # Use the *positive* names proportionally if any exist; otherwise
        # spread equally across all remaining available names so that
        # zero-valued names that were clipped from negatives can still
        # absorb mass and reach feasibility.
        absorbers = (~over_cap) & available_mask
        if not absorbers.any():
            # All available names are at the cap — feasibility already
            # checked, so this means we're done.
            break

        positive_absorbers = absorbers & (w > 0.0)
        if positive_absorbers.any() and w[positive_absorbers].sum() > 0.0:
            share = w[positive_absorbers] / w[positive_absorbers].sum()
            w[positive_absorbers] += excess_mass * share
        else:
            # Spread equally across all available absorbers (incl. zeros).
            n_absorb = int(absorbers.sum())
            w[absorbers] += excess_mass / n_absorb

    # Final defensive renormalisation across the available universe.
    total = w[available_mask].sum()
    if total > 0.0:
        w[available_mask] = w[available_mask] / total
    w[excluded_mask] = 0.0

    return w
