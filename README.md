# Sharpe — Natural-language Portfolio Optimisation

An AI agent you can talk to on Telegram to construct optimal portfolios. Tell it what you want — *"FTSE max Sharpe, exclude banks, cap 10% per name"* — and a genetic algorithm finds the weights that satisfy those constraints.

Submission for the [DataVita OpenClaw Challenge 2026](https://jobs.datavita.co.uk/openclaw-challenge).

## The problem

Portfolio optimisation is a textbook discipline with serious practical friction. The maths is well-understood — Markowitz, Black-Litterman, risk-parity, all decades old — but the tooling is either Excel sheets that don't compose, expensive licensed software, or Python notebooks that nobody outside quant teams can use.

The natural-language barrier matters. A trader who can articulate *"I want max Sharpe but no more than 10% in any single name, exclude oil, and at least 8 holdings"* in seconds will spend half an hour translating that into code, parameter grids, or a Bloomberg query.

Sharpe collapses that translation. You describe the portfolio you want in plain English; a genetic algorithm finds it; the agent explains what it did and why.

## What it does

- **Pulls 5 years of daily-close prices** from Yahoo Finance for any universe of tickers
- **Runs a genetic algorithm** to maximise one of three objectives: Sharpe, expected return, or negative variance
- **Honours constraints** in plain language: long-only, max weight per name, ticker exclusions, minimum holdings
- **Reports results in a Telegram-friendly format** with weights, annualised stats, and an explanation of *why* the GA landed where it did
- **Iterates conversationally** — *"now cap at 8%"*, *"also exclude pharma"*, *"rerun"*

## Architecture

```
                    ┌──────────────┐
                    │   Telegram   │  ← User talks here
                    │   (mobile)   │
                    └──────┬───────┘
                           │ Bot API
                    ┌──────▼────────┐
                    │   OpenClaw    │  ← Agent gateway (LaunchAgent)
                    │    Gateway    │  ← persona = Sharpe (SOUL.md)
                    └──────┬────────┘
                           │ exec
                    ┌──────▼────────┐
                    │ portfolio-    │  ← SKILL.md teaches Sharpe
                    │ optimise      │     when/how to call the CLI
                    │ (skill)       │
                    └──────┬────────┘
                           │ python -m optimiser.cli
                    ┌──────▼────────┐
                    │  CLI (JSON    │  ← argparse wrapper, returns
                    │   in/out)     │     structured output
                    └──────┬────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   ┌─────────┐        ┌─────────┐        ┌─────────┐
   │  data   │        │ fitness │        │   ga    │
   │  (yf)   │        │  (np)   │        │ (numpy) │
   └─────────┘        └─────────┘        └─────────┘
```

Four production modules:

- **`optimiser/data.py`** — yfinance wrapper, log-returns, strict on missing data
- **`optimiser/fitness.py`** — annualised mean/vol/Sharpe, three objectives, UK-gilt-anchored risk-free rate (~4%)
- **`optimiser/constraints.py`** — feasibility checks + iterative clip-and-renormalise repair operator
- **`optimiser/ga.py`** — tournament selection, single-point crossover, gaussian mutation, elitism

Plus the agent layer:

- **`SOUL.md`** — Sharpe's identity, scope, and tone (anti-chatbot-ese, anti-investment-advice, finance-literate)
- **`SKILL.md`** — runbook teaching the agent when to call the CLI and how to format results

## Results

Measured on a 10-name FTSE universe over 5 years of daily returns, max-Sharpe objective, 25% per-name cap:

| Portfolio       | Annual return | Annual vol | Sharpe |
|-----------------|---------------|-----------|--------|
| Equal-weighted  | 8.45%         | 14.60%    | 0.31   |
| GA-optimised    | 15.83%        | 17.02%    | **0.70** |

**The GA produced 2.3× the risk-adjusted return of the naive baseline**, converging in ~25 generations.

## Try it

The bot lives at `@gregor_portfolio_bot` on Telegram. DM access is allowlisted to the operator (judges: contact the operator to request access).

Example prompts that work:

```
Optimise a max-Sharpe portfolio from LLOY.L, BARC.L, AZN.L
with max 40% per name and seed 42.

Build a min-variance FTSE portfolio with at least 8 holdings
and 15% max per name.

Now exclude all banks and rerun.

What would the same portfolio look like at max return instead?
```

## Design rationale

### Why a genetic algorithm

Closed-form quadratic-programming solvers (e.g. Markowitz with `cvxpy`) are faster and more accurate for *clean* convex problems. The moment you add discrete constraints — "at least 8 holdings", "exclude this sector", "at least one bank" — the problem stops being convex and QP either fails or requires reformulation. A GA handles arbitrary constraints uniformly via the repair operator, at the cost of slightly suboptimal solutions. For an exploratory, conversational tool where users want to iterate over a constraint set, that trade-off is correct.

### Why repair, not penalty

The two standard approaches to GA constraint handling are *penalty* (subtract a cost proportional to violation from fitness) and *repair* (project infeasible candidates back into the feasible region before evaluation). Repair guarantees every evaluated individual is feasible, so the search budget isn't spent ranking infeasibilities. It also produces interpretable failure modes: an infeasible constraint set surfaces immediately as `InfeasibleConstraints` rather than as a low-fitness population the agent has to explain away.

### Why local-first deployment

OpenClaw's design intent is a personal AI assistant on your own devices. Hosting Sharpe on a cloud VM is possible (the architecture is portable) but contradicts the framework's positioning. This submission runs on the operator's machine as a LaunchAgent, surviving reboots and sleep, reachable from anywhere via Telegram's outbound polling model. The deployment story is *deliberately* aligned with OpenClaw's vision rather than retro-fitted into a generic cloud-hosted-bot pattern.

### Compliance posture

Sharpe refuses buy/sell recommendations on individual securities and frames all outputs as illustrative. This is non-negotiable for any consumer-facing financial tool, lawyer or no lawyer. The agent is configured (via SOUL.md) to redirect such requests toward defining an objective and constraints.

## Engineering

- **43 tests**, all passing, sub-second runtime, all network calls mocked
- **Conventional Commits** throughout — `feat(ga):`, `fix(fitness):`, `test(constraints):` — for legible history
- **Type hints, dataclasses, docstrings** across every module
- **JSON I/O at the CLI boundary** so the agent never has to parse Python tracebacks

```bash
git clone https://github.com/gregorryan/openclaw-portfolio-optimiser.git
cd openclaw-portfolio-optimiser
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

You can drive the optimiser directly without the agent:

```bash
python -m optimiser.cli optimise \
  --tickers LLOY.L BARC.L AZN.L GSK.L SHEL.L \
  --objective max_sharpe --max-weight 0.25 --seed 42
```

## Future work

- **Backtesting** the GA's selections out-of-sample (currently fits weights only, no historical performance simulation)
- **Sector-aware exclusions** ("exclude banks" rather than naming individual banks — needs a sector lookup table)
- **Efficient-frontier sweep** — plot return vs. vol across multiple objective values, not just one
- **Multi-period optimisation** — rebalancing logic over a 12-month window
- **Cloud deployment** with secrets via a managed secret store, for operators who'd rather not host locally

## Stack

- [OpenClaw](https://openclaw.ai) (gateway, skills, persona)
- Anthropic Claude Sonnet 4.6 (language reasoning via Claude Code subscription auth)
- Telegram Bot API (channel)
- Python 3.13 — numpy, pandas, yfinance, pytest

## Acknowledgements

Built for the [DataVita OpenClaw Challenge 2026](https://jobs.datavita.co.uk/openclaw-challenge). Submitted by Gregor Ryan, Glasgow.
