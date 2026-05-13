"""Command-line interface to the portfolio optimiser.

Two ways to invoke the optimiser:

1. Structured flags  — explicit --objective, --max-weight, --excluded, etc.
2. Natural language  — --from-text "max sharpe, exclude banks, cap 10%"

When --from-text is supplied, the parser extracts whatever it can and
fills in defaults for anything missing. Explicit flags override parsed
values, so you can mix: --from-text "..." --seed 42.

Output is always JSON on stdout (success, exit 0) or stderr (error,
exit 1) — no Python stack traces ever reach the caller.

Examples:
    python -m optimiser.cli optimise --objective max_sharpe
    python -m optimiser.cli optimise --from-text "min variance, no banks"
    python -m optimiser.cli optimise \\
        --from-text "max sharpe, cap 15%" --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys

from optimiser.constraints import Constraints, InfeasibleConstraints
from optimiser.data import DEFAULT_UNIVERSE_FTSE, DataError, load
from optimiser.fitness import Objective
from optimiser.ga import GAConfig, optimise
from optimiser.parser import StructuredRequest, parse_request


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
        "--from-text",
        type=str,
        default=None,
        help='Free-text request, e.g. "max sharpe, exclude banks, cap 10%%"',
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
        default=None,
        help="What the GA optimises for (default: max_sharpe)",
    )
    opt.add_argument(
        "--max-weight",
        type=float,
        default=None,
        help="Maximum weight per name (0 < w <= 1)",
    )
    opt.add_argument(
        "--excluded",
        nargs="*",
        default=None,
        help="Tickers to forcibly exclude (weight = 0)",
    )
    opt.add_argument(
        "--min-holdings",
        type=int,
        default=None,
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
    print(json.dumps({"ok": False, "error": kind, "message": message}), file=sys.stderr)
    return 1


def _merge_with_parsed(
    args: argparse.Namespace,
    parsed: StructuredRequest,
) -> argparse.Namespace:
    """Apply parsed values to any flag the user did NOT specify explicitly.

    Explicit flags always win over parsed values. This is what 'mix' looks
    like: --from-text "max sharpe, exclude banks" --max-weight 0.05 means
    "use the natural-language request but override the cap".
    """
    if args.objective is None and parsed.objective is not None:
        args.objective = parsed.objective.value
    if args.max_weight is None and parsed.max_weight is not None:
        args.max_weight = parsed.max_weight
    if args.min_holdings is None and parsed.min_holdings is not None:
        args.min_holdings = parsed.min_holdings
    if args.excluded is None and parsed.excluded_tickers:
        args.excluded = list(parsed.excluded_tickers)
    if args.tickers is None and parsed.tickers:
        args.tickers = list(parsed.tickers)
    return args


def _apply_defaults(args: argparse.Namespace) -> argparse.Namespace:
    """Final defaults after parsing + explicit flags have been merged."""
    if args.objective is None:
        args.objective = Objective.MAX_SHARPE.value
    if args.max_weight is None:
        args.max_weight = 1.0
    if args.min_holdings is None:
        args.min_holdings = 1
    if args.excluded is None:
        args.excluded = []
    # Tickers stays as None here; _cmd_optimise applies the FTSE default.
    return args


def _cmd_optimise(args: argparse.Namespace) -> int:
    try:
        parse_info: dict | None = None
        if args.from_text:
            parsed = parse_request(args.from_text)
            args = _merge_with_parsed(args, parsed)
            parse_info = {
                "input": args.from_text,
                "confidence": parsed.confidence,
                "notes": list(parsed.notes),
            }

        args = _apply_defaults(args)

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

        output: dict = {
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
        if parse_info is not None:
            output["parsed"] = parse_info

        print(json.dumps(output, indent=2))
        return 0

    except DataError as e:
        return _err(str(e), kind="data_error")
    except InfeasibleConstraints as e:
        return _err(str(e), kind="infeasible_constraints")
    except ValueError as e:
        return _err(str(e), kind="value_error")
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", kind="unknown")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "optimise":
        return _cmd_optimise(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
