"""Command-line interface to the portfolio optimiser.

Reads parameters from CLI flags, runs the GA, prints a JSON result to
stdout. Designed to be invoked by external orchestration — the OpenClaw
agent via its exec tool, or directly from a terminal for testing.

All output is JSON, including errors, so the agent can parse a single
stream reliably. Successful runs write to stdout with exit 0; errors
write to stderr with exit 1 and an `ok: false` JSON payload.

Examples:
    python -m optimiser.cli optimise --objective max_sharpe
    python -m optimiser.cli optimise \\
        --tickers LLOY.L BARC.L AZN.L GSK.L SHEL.L \\
        --objective max_sharpe \\
        --max-weight 0.25 \\
        --excluded BARC.L \\
        --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys

from optimiser.constraints import Constraints, InfeasibleConstraints
from optimiser.data import DEFAULT_UNIVERSE_FTSE, DataError, load
from optimiser.fitness import Objective
from optimiser.ga import GAConfig, optimise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="optimiser",
        description="Portfolio optimiser CLI (GA-based)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    opt = sub.add_parser(
        "optimise",
        help="Run the GA on a universe of tickers",
    )
    opt.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Ticker symbols (defaults to the bundled FTSE universe)",
    )
    opt.add_argument(
        "--objective",
        choices=[obj.value for obj in Objective],
        default=Objective.MAX_SHARPE.value,
        help="What the GA optimises for",
    )
    opt.add_argument(
        "--max-weight",
        type=float,
        default=1.0,
        help="Maximum weight per name (0 < w <= 1)",
    )
    opt.add_argument(
        "--excluded",
        nargs="*",
        default=[],
        help="Tickers to forcibly exclude (weight = 0)",
    )
    opt.add_argument(
        "--min-holdings",
        type=int,
        default=1,
        help="Minimum number of non-zero positions",
    )
    opt.add_argument(
        "--seed",
        type=int,
        default=None,
        help="GA random seed for reproducibility",
    )
    opt.add_argument(
        "--population",
        type=int,
        default=100,
        help="GA population size",
    )
    opt.add_argument(
        "--generations",
        type=int,
        default=200,
        help="Number of GA generations",
    )

    return parser


def _err(message: str, kind: str = "error") -> int:
    """Print a JSON error to stderr and return a non-zero exit code."""
    print(json.dumps({"ok": False, "error": kind, "message": message}), file=sys.stderr)
    return 1


def _cmd_optimise(args: argparse.Namespace) -> int:
    try:
        tickers = tuple(args.tickers) if args.tickers else DEFAULT_UNIVERSE_FTSE
        price_data = load(tickers=tickers)

        constraints = Constraints(
            max_weight=args.max_weight,
            min_holdings=args.min_holdings,
            excluded_tickers=tuple(args.excluded),
        )
        config = GAConfig(
            seed=args.seed,
            population_size=args.population,
            n_generations=args.generations,
        )

        result = optimise(
            price_data.returns,
            Objective(args.objective),
            constraints=constraints,
            config=config,
        )

        output = {
            "ok": True,
            "objective": args.objective,
            "tickers": list(result.tickers),
            "weights": {t: round(float(w), 4) for t, w in result.as_dict().items()},
            "stats": {
                "expected_return_pct": round(result.stats.expected_return * 100, 2),
                "volatility_pct": round(result.stats.volatility * 100, 2),
                "sharpe": round(result.stats.sharpe, 3),
            },
            "summary": {
                "n_holdings": int(sum(1 for w in result.weights if w > 1e-6)),
                "max_weight": round(float(result.weights.max()), 4),
                "n_generations": len(result.fitness_history),
                "final_fitness": round(result.fitness, 4),
            },
        }
        print(json.dumps(output, indent=2))
        return 0

    except DataError as e:
        return _err(str(e), kind="data_error")
    except InfeasibleConstraints as e:
        return _err(str(e), kind="infeasible_constraints")
    except ValueError as e:
        return _err(str(e), kind="value_error")
    except Exception as e:  # last-resort catch so CLI never spits a stack trace
        return _err(f"{type(e).__name__}: {e}", kind="unknown")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "optimise":
        return _cmd_optimise(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
