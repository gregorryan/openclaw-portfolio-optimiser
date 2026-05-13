"""Command-line interface to the portfolio optimiser.

Two modes:

1. Optimisation (default)   — fit weights to the full history.
2. Backtest (--backtest)    — fit weights on the first 80% of history,
                              then evaluate them on the held-out tail.

Two input styles for either mode:

- Structured flags  — --objective, --max-weight, --excluded, etc.
- Natural language  — --from-text "max sharpe, exclude banks, cap 10%"

Output is always JSON: stdout on success (exit 0), stderr on error
(exit 1). Every successful run includes:

- a fresh `run_id` (UUID) and ISO-8601 `timestamp` so the agent layer
  has evidence the CLI actually ran in the current turn — chat-history
  caching is structurally detectable
- a `chart_path` pointing at a PNG bar chart of the weights, ready to
  be attached to a Telegram reply
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone

from optimiser.backtest import backtest
from optimiser.chart import render_weights_chart
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

    opt = sub.add_parser("optimise", help="Run the GA on a universe of tickers")
    opt.add_argument("--from-text", type=str, default=None)
    opt.add_argument("--tickers", nargs="+", default=None)
    opt.add_argument(
        "--objective",
        choices=[obj.value for obj in Objective],
        default=None,
    )
    opt.add_argument("--max-weight", type=float, default=None)
    opt.add_argument("--excluded", nargs="*", default=None)
    opt.add_argument("--min-holdings", type=int, default=None)
    opt.add_argument("--seed", type=int, default=None)
    opt.add_argument("--population", type=int, default=100)
    opt.add_argument("--generations", type=int, default=200)
    opt.add_argument("--backtest", action="store_true")
    opt.add_argument("--train-fraction", type=float, default=0.80)
    opt.add_argument(
        "--no-chart",
        action="store_true",
        help="Skip PNG chart rendering (default: chart is generated)",
    )

    return parser


def _run_id() -> str:
    return uuid.uuid4().hex[:12]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _err(message: str, kind: str = "error") -> int:
    print(
        json.dumps(
            {
                "ok": False,
                "error": kind,
                "message": message,
                "run_id": _run_id(),
                "timestamp": _timestamp(),
            }
        ),
        file=sys.stderr,
    )
    return 1


def _merge_with_parsed(
    args: argparse.Namespace, parsed: StructuredRequest
) -> argparse.Namespace:
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
    if args.objective is None:
        args.objective = Objective.MAX_SHARPE.value
    if args.max_weight is None:
        args.max_weight = 1.0
    if args.min_holdings is None:
        args.min_holdings = 1
    if args.excluded is None:
        args.excluded = []
    return args


def _stats_to_dict(stats) -> dict:
    return {
        "expected_return_pct": round(stats.expected_return * 100, 2),
        "volatility_pct": round(stats.volatility * 100, 2),
        "sharpe": round(stats.sharpe, 3),
    }


def _maybe_render_chart(
    weights: dict[str, float],
    objective: str,
    excluded: list[str],
    cap: float,
    seed: int | None,
    run_id: str,
    mode: str,
    disabled: bool,
) -> str | None:
    """Render a PNG chart of weights if not disabled; return path or None."""
    if disabled:
        return None
    cap_str = f"{cap * 100:.0f}% cap" if cap < 1.0 else "no cap"
    seed_str = f"seed {seed}" if seed is not None else "random seed"
    ex_str = f" | excluding {', '.join(excluded)}" if excluded else ""
    subtitle = f"{objective.replace('_', ' ')} | {cap_str} | {seed_str}{ex_str}"
    title = "Portfolio weights" if mode == "optimise" else "Portfolio weights (in-sample fit)"
    try:
        return render_weights_chart(
            weights=weights,
            title=title,
            subtitle=subtitle,
            run_id=run_id,
        )
    except Exception:
        # Chart failure must never break the optimisation itself.
        return None


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

        run_id = _run_id()
        timestamp = _timestamp()

        if args.backtest:
            bt = backtest(
                price_data.returns,
                Objective(args.objective),
                constraints=constraints,
                config=config,
                train_fraction=args.train_fraction,
            )
            weights_dict = {
                t: round(float(w), 4) for t, w in zip(bt.tickers, bt.weights)
            }
            chart_path = _maybe_render_chart(
                weights=weights_dict,
                objective=args.objective,
                excluded=list(args.excluded),
                cap=args.max_weight,
                seed=args.seed,
                run_id=run_id,
                mode="backtest",
                disabled=args.no_chart,
            )
            output: dict = {
                "ok": True,
                "mode": "backtest",
                "run_id": run_id,
                "timestamp": timestamp,
                "chart_path": chart_path,
                "objective": args.objective,
                "tickers": list(bt.tickers),
                "excluded_tickers": list(args.excluded),
                "weights": weights_dict,
                "train_stats": _stats_to_dict(bt.train_stats),
                "test_stats": _stats_to_dict(bt.test_stats),
                "split": {
                    "train_fraction": bt.train_fraction,
                    "train_days": bt.train_days,
                    "test_days": bt.test_days,
                },
                "summary": {
                    "in_sample_sharpe": round(bt.in_sample_sharpe, 3),
                    "out_of_sample_sharpe": round(bt.out_of_sample_sharpe, 3),
                    "sharpe_gap": round(bt.sharpe_gap, 3),
                },
            }
        else:
            result = optimise(
                price_data.returns,
                Objective(args.objective),
                constraints=constraints,
                config=config,
            )
            weights_dict = {
                t: round(float(w), 4) for t, w in result.as_dict().items()
            }
            chart_path = _maybe_render_chart(
                weights=weights_dict,
                objective=args.objective,
                excluded=list(args.excluded),
                cap=args.max_weight,
                seed=args.seed,
                run_id=run_id,
                mode="optimise",
                disabled=args.no_chart,
            )
            output = {
                "ok": True,
                "mode": "optimise",
                "run_id": run_id,
                "timestamp": timestamp,
                "chart_path": chart_path,
                "objective": args.objective,
                "tickers": list(result.tickers),
                "excluded_tickers": list(args.excluded),
                "weights": weights_dict,
                "stats": _stats_to_dict(result.stats),
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
