---
name: portfolio-optimise
description: "Run a genetic algorithm to find optimal portfolio weights given a universe of tickers, an objective (max Sharpe, min variance, max return), and optional constraints (per-name cap, excluded tickers, minimum holdings). Accepts either structured flags or a free-text request."
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

## Natural-language mode (preferred for chat)

When the user has stated the request in plain English, pass the entire request via `--from-text` rather than translating it into flags yourself. The CLI's deterministic parser handles objective phrasing, caps, exclusions (by sector or ticker), and min-holdings.

```bash
cd /Users/gregorryan/code/openclaw-portfolio-optimiser && source .venv/bin/activate && \
  python -m optimiser.cli optimise --from-text "max sharpe, exclude banks, cap 25% per name" --seed 42
```

The response will include a `parsed` block showing the input text, parser confidence, and any notes about how the request was interpreted. If `confidence` is below 0.5 or the parser couldn't extract an objective, ask the user to clarify rather than guessing.

You can mix modes: `--from-text "..."` plus explicit overriding flags. Explicit flags always win.

## Structured-flag mode

Use this when the user has given you well-separated parameters or you're scripting the call.

```bash
cd /Users/gregorryan/code/openclaw-portfolio-optimiser && source .venv/bin/activate && \
  python -m optimiser.cli optimise [flags]
```

### Flags

- `--from-text "..."` — natural-language request (see above)
- `--tickers SYM1 SYM2 ...` — universe (default: bundled FTSE 10-name universe)
- `--objective {max_sharpe,min_variance,max_return}` — what to optimise (default: max_sharpe)
- `--max-weight FLOAT` — per-name cap, 0 < w <= 1 (default: 1.0, no cap)
- `--excluded SYM1 SYM2 ...` — tickers to force to zero weight (default: none)
- `--min-holdings INT` — minimum non-zero positions (default: 1)
- `--seed INT` — random seed for reproducibility (default: random)
- `--population INT` — GA population size (default: 100)
- `--generations INT` — GA generations (default: 200)

### Output Schema

Success — stdout, exit 0:

```json
{
  "ok": true,
  "objective": "max_sharpe",
  "tickers": ["LLOY.L", "BARC.L", "..."],
  "weights": { "LLOY.L": 0.2, "BARC.L": 0.4, "...": "..." },
  "stats": {
    "expected_return_pct": 13.84,
    "volatility_pct": 20.96,
    "sharpe": 0.47
  },
  "summary": {
    "n_holdings": 3,
    "max_weight": 0.4,
    "n_generations": 200,
    "final_fitness": 0.4697
  },
  "parsed": {
    "input": "max sharpe, ...",
    "confidence": 0.75,
    "notes": ["..."]
  }
}
```

The `parsed` block only appears when `--from-text` was used.

Failure — stderr, exit non-zero:

```json
{ "ok": false, "error": "data_error|infeasible_constraints|value_error|unknown", "message": "..." }
```

## Example Invocations

**Plain-English request (preferred):**

```bash
cd /Users/gregorryan/code/openclaw-portfolio-optimiser && source .venv/bin/activate && \
  python -m optimiser.cli optimise \
    --from-text "max sharpe FTSE portfolio, exclude banks, cap 15% per name" \
    --seed 42
```

**Default FTSE universe, max Sharpe, no cap:**

```bash
cd /Users/gregorryan/code/openclaw-portfolio-optimiser && source .venv/bin/activate && \
  python -m optimiser.cli optimise --objective max_sharpe --seed 42
```

**Min-variance, fully diversified (at least 8 holdings, ≤15% each):**

```bash
cd /Users/gregorryan/code/openclaw-portfolio-optimiser && source .venv/bin/activate && \
  python -m optimiser.cli optimise \
    --objective min_variance \
    --max-weight 0.15 \
    --min-holdings 8 \
    --seed 42
```

## Reply Format

After running the skill, present results to the user as a short Telegram-friendly message. Suggested shape:

```
📐 Max Sharpe portfolio, FTSE 10-name universe, 5-year window

Expected return: 13.8%
Volatility:      21.0%
Sharpe:          0.47

Weights:
  AZN.L   40.0%
  BARC.L  40.0%
  LLOY.L  20.0%

Notes:
  • BARC.L and AZN.L hit the 20% cap — the GA wanted more in them.
  • Past returns do not predict future returns. Illustrative only.
```

Always include:
- a one-line headline with the objective, universe descriptor, and lookback
- the three stats (return, vol, Sharpe — vol omitted if min_variance was the objective)
- weights sorted highest to lowest, showing only non-zero positions
- any *notable* observations (binding caps, excluded names, low diversification) — keep this section to 1-3 bullets max
- a closing reminder about illustrative / not advice

## Rules

- **Prefer `--from-text` for Telegram messages.** The parser exists so that you don't have to translate phrasing yourself — and the visible `parsed` block in the JSON output is part of the project's transparency story.
- Always include `--seed` if the user has not specified one, so repeated calls give consistent answers across the conversation. Use a number the user can remember, like 42.
- Never invent tickers. If unsure whether a name resolves, ask the user to confirm.
- If the CLI returns `ok: false`:
  - `data_error`: a ticker probably doesn't resolve on Yahoo. Name the ticker in the error, ask the user to confirm or remove it.
  - `infeasible_constraints`: report the constraint that broke and propose the smallest relaxation (e.g. "max_weight=0.10 across 5 names can only reach 50% — try 0.20 or add more tickers").
  - `value_error` / `unknown`: report it plainly and offer to retry with the default config.
- If `parsed.confidence` is below 0.5, ask the user to clarify rather than running the optimisation blind.
- Do not run the CLI without a stated `--objective` (or one extracted via `--from-text`). If the user said "best portfolio" with no qualifier, ask whether they want max Sharpe, min variance, or max return.
- Do not give buy/sell recommendations on individual tickers, even when the weights make one allocation obvious.
- This is optimisation, not advice. Mention "illustrative only / not investment advice" at the end of meaningful results.

## Notes

- The CLI takes 5-15 seconds depending on universe size and generations.
- yfinance occasionally rate-limits or returns empty data for a ticker; this surfaces as `data_error`.
- The universe order does not matter for the optimisation but the GA's crossover operator loosely preserves contiguous blocks, so ordering tickers by sector can help the search early on.
