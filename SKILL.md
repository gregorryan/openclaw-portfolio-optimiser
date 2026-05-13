---
name: portfolio-optimise
description: "Run a genetic algorithm to find optimal portfolio weights given a universe of tickers, an objective (max Sharpe, min variance, max return), and optional constraints (per-name cap, excluded tickers, minimum holdings)."
metadata:
  {
    "openclaw":
      {
        "emoji": "📐",
        "requires": { "bins": ["python3"] },
      },
  }
---

# Portfolio Optimise Skill

Find optimal portfolio weights using a genetic algorithm against 5 years of daily-close adjusted prices from Yahoo Finance.

## When to Use

✅ **USE this skill when the user asks to:**

- "Optimise a portfolio of [tickers]"
- "Find max Sharpe weights for [universe]"
- "Build a min-variance portfolio from [universe]"
- "Run the GA on [tickers] with [constraints]"
- "What's the optimal weight on [tickers]?"
- Iterate on a previous run ("now cap at 10%", "exclude banks", "rerun")

## When NOT to Use

❌ **DON'T use this skill when the user asks for:**

- A specific stock recommendation ("should I buy AAPL?") — refuse and redirect to defining an objective
- Live or intraday prices — this skill uses daily close only
- Predictions of future prices or returns — this is optimisation, not forecasting
- Trade execution — there is no brokerage integration
- Backtesting a strategy — this skill only fits weights, it does not simulate

## How to Invoke

The skill is a Python CLI. The project lives at `/Users/gregorryan/code/openclaw-portfolio-optimiser` with a virtualenv at `.venv`. Always:

1. `cd` into the project directory
2. Activate the venv: `source .venv/bin/activate`
3. Run `python -m optimiser.cli optimise [flags]`

The CLI prints a single JSON object to stdout. Parse it, then summarise it for the user in plain English. Do not paste the raw JSON back — Telegram users want a readable answer.

## Command Reference

```bash
