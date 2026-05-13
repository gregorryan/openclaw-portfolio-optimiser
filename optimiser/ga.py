"""Genetic algorithm for portfolio weight optimisation.

The GA maintains a population of candidate weight vectors and evolves it
toward higher fitness over a series of generations. Each generation:

1. Evaluate fitness of every individual
2. Preserve the best individual (elitism) — guarantees fitness is non-decreasing
3. Fill the rest of the new generation by:
   a. Selecting two parents via tournament
   b. Combining them via single-point crossover (with probability p_crossover)
   c. Perturbing the child via gaussian mutation (per-gene probability p_mutation)
   d. Repairing back to feasibility
4. Track best-fitness history for convergence inspection

Design choices and why:

- Tournament selection (over roulette wheel): scale-invariant — works
  whether fitness is 0.5 or -0.0003. Roulette breaks on negative fitness.
- Single-point crossover (over uniform): preserves contiguous "groups"
  of weights, which loosely maps to sector blocks if the user passed
  tickers ordered by sector. Mild but real domain coupling.
- Gaussian mutation (over uniform): mutations near zero are more likely
  than large jumps, which fits the search space — we usually want small
  refinements, not random redrawing.
- Elitism: prevents the best solution from being lost to bad luck in
  crossover/mutation. One slot per generation, the most common choice.
- Per-generation repair: every candidate that enters the population
  is feasible, so fitness evaluation is always meaningful.

The GA is deterministic given a seed, which makes results reproducible
for tests and demos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from optimiser.constraints import Constraints, repair
from optimiser.fitness import (
    DEFAULT_RISK_FREE_RATE,
    Objective,
    PortfolioStats,
    evaluate,
    portfolio_stats,
)


@dataclass(frozen=True)
class GAConfig:
    """Hyperparameters for the GA.

    Defaults chosen for sub-second convergence on universes of 5-20 tickers.
    Bigger universes warrant bigger populations and more generations.
    """

    population_size: int = 100
    n_generations: int = 200
    tournament_size: int = 3
    p_crossover: float = 0.8
    p_mutation: float = 0.10
    mutation_sigma: float = 0.05  # std of gaussian noise applied per gene
    elitism: int = 1               # number of top individuals preserved each gen
    seed: int | None = None


@dataclass
class GAResult:
    """The outcome of a GA run, with diagnostics."""

    weights: np.ndarray              # best feasible weight vector found
    tickers: tuple[str, ...]
    stats: PortfolioStats
    objective: Objective
    fitness: float                   # objective fitness of `weights`
    fitness_history: list[float] = field(default_factory=list)  # best-so-far per gen
    config: GAConfig | None = None

    def as_dict(self) -> dict[str, float]:
        """Ticker → weight as plain floats, useful for logging and chat output."""
        return {t: float(w) for t, w in zip(self.tickers, self.weights)}


def _initial_population(
    pop_size: int,
    n_tickers: int,
    tickers: tuple[str, ...],
    constraints: Constraints,
    rng: np.random.Generator,
) -> np.ndarray:
    """Seed the population with feasible, diverse weight vectors.

    We sample from a Dirichlet(1, ..., 1) — uniform over the simplex —
    then repair to honour exclusions and caps.
    """
    raw = rng.dirichlet(alpha=np.ones(n_tickers), size=pop_size)
    population = np.empty_like(raw)
    for i in range(pop_size):
        population[i] = repair(raw[i], tickers, constraints)
    return population


def _tournament_select(
    population: np.ndarray,
    fitnesses: np.ndarray,
    k: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Pick k random individuals; return a copy of the fittest."""
    contender_idx = rng.integers(low=0, high=len(population), size=k)
    winner_idx = contender_idx[np.argmax(fitnesses[contender_idx])]
    return population[winner_idx].copy()


def _single_point_crossover(
    parent_a: np.ndarray,
    parent_b: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Take left of parent_a up to a random cut, right of parent_b after."""
    n = parent_a.shape[0]
    if n < 2:
        return parent_a.copy()
    cut = int(rng.integers(low=1, high=n))
    child = np.concatenate([parent_a[:cut], parent_b[cut:]])
    return child


def _gaussian_mutate(
    individual: np.ndarray,
    p_mutation: float,
    sigma: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Add gaussian noise to each gene with probability p_mutation."""
    mask = rng.random(size=individual.shape[0]) < p_mutation
    if not mask.any():
        return individual
    noise = rng.normal(loc=0.0, scale=sigma, size=int(mask.sum()))
    mutated = individual.copy()
    mutated[mask] = mutated[mask] + noise
    return mutated


def optimise(
    returns: pd.DataFrame,
    objective: Objective,
    constraints: Constraints | None = None,
    config: GAConfig | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> GAResult:
    """Run the GA and return the best feasible portfolio found.

    Args:
        returns: T × N DataFrame of asset returns. Column order is the
            order weights will be returned in.
        objective: what to maximise — Sharpe, return, or negative variance.
        constraints: feasibility rules. Defaults to long-only, no other limits.
        config: GA hyperparameters. Defaults to GAConfig().
        risk_free_rate: passed through to the fitness function.

    Returns:
        GAResult with weights, annualised stats, fitness, and convergence trace.
    """
    if constraints is None:
        constraints = Constraints()
    if config is None:
        config = GAConfig()

    tickers = tuple(returns.columns)
    n_tickers = len(tickers)
    rng = np.random.default_rng(config.seed)

    R = returns.to_numpy()  # cache the array form once

    def fitness_of(w: np.ndarray) -> float:
        return evaluate(w, R, objective, risk_free_rate=risk_free_rate)

    population = _initial_population(
        config.population_size, n_tickers, tickers, constraints, rng
    )
    fitnesses = np.array([fitness_of(ind) for ind in population])

    fitness_history: list[float] = []

    for _ in range(config.n_generations):
        new_population = np.empty_like(population)

        # Elitism: copy the top-k unchanged
        elite_idx = np.argsort(fitnesses)[-config.elitism :]
        for i, idx in enumerate(elite_idx):
            new_population[i] = population[idx]

        # Fill the rest
        for i in range(config.elitism, config.population_size):
            parent_a = _tournament_select(
                population, fitnesses, config.tournament_size, rng
            )
            if rng.random() < config.p_crossover:
                parent_b = _tournament_select(
                    population, fitnesses, config.tournament_size, rng
                )
                child = _single_point_crossover(parent_a, parent_b, rng)
            else:
                child = parent_a

            child = _gaussian_mutate(
                child, config.p_mutation, config.mutation_sigma, rng
            )
            child = repair(child, tickers, constraints)
            new_population[i] = child

        population = new_population
        fitnesses = np.array([fitness_of(ind) for ind in population])
        fitness_history.append(float(fitnesses.max()))

    best_idx = int(np.argmax(fitnesses))
    best_weights = population[best_idx]
    best_stats = portfolio_stats(best_weights, R, risk_free_rate=risk_free_rate)
    best_fitness = float(fitnesses[best_idx])

    return GAResult(
        weights=best_weights,
        tickers=tickers,
        stats=best_stats,
        objective=objective,
        fitness=best_fitness,
        fitness_history=fitness_history,
        config=config,
    )
