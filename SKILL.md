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

## The universe

The skill operates on a **fixed 30-name FTSE 100 sample**, defined in `optimiser/data.py` as `DEFAULT_UNIVERSE_FTSE`. The names are:

LLOY.L, BARC.L, HSBA.L, NWG.L, AZN.L, GSK.L, ULVR.L, DGE.L, RKT.L, BATS.L, IMB.L, TSCO.L, SBRY.L, NXT.L, SHEL.L, BP.L, RIO.L, GLEN.L, AAL.L, VOD.L, BT-A.L, SSE.L, NG.L, SVT.L, AV.L, LGEN.L, PRU.L, LAND.L, BA.L, RR.L

**Anything outside this list does not exist for this skill.** If the user says "FTSE 100" they get the 30 names above, not the full index. If they want a different universe they must list it explicitly via `--tickers`.

**Do not mention or assign weights to any ticker that is not in this list, unless the user explicitly provided different tickers via `--tickers`.** This rule is mechanical: if a ticker name appears in your output that is not in the JSON `tickers` array returned by the skill, you have hallucinated and must rerun.

## How to Invoke

The skill is a Python CLI. The project lives at `/Users/gregorryan/code/openclaw-portfolio-optimiser` with a virtualenv at `.venv`.

```bash
cd /Users/gregorryan/code/openclaw-portfolio-optimiser && source .venv/bin/activate && \
  python -m optimiser.cli optimise [flags]
```

The CLI prints a single JSON object to stdout. **You must parse this JSON and use its values verbatim.** Do not paraphrase, round, substitute, or extend the values. The `weights`, `tickers`, and `stats` fields are the source of truth for your reply.

## Natural-language mode (preferred for chat)

When the user has stated the request in plain English, pass the entire request via `--from-text`:

```bash
cd /Users/gregorryan/code/openclaw-portfolio-optimiser && source .venv/bin/activate && \
  python -m optimiser.cli optimise --from-text "max sharpe, exclude banks, cap 25% per name" --seed 42
```

The response includes a `parsed` block showing what was extracted. If `parsed.confidence` is below 0.5 or `parsed.objective` is null, ask the user to clarify rather than running.

## Flags

- `--from-text "..."` — natural-language request
- `--tickers SYM1 SYM2 ...` — universe (default: the 30-name FTSE list)
- `--objective {max_sharpe,min_variance,max_return}`
- `--max-weight FLOAT` — per-name cap, 0 < w <= 1
- `--excluded SYM1 SYM2 ...` — tickers to force to zero weight
- `--min-holdings INT`
- `--seed INT` — random seed
- `--population INT` — GA population size (default 100)
- `--generations INT` — GA generations (default 200)

## Output schema

Success — stdout, exit 0. **These keys are your only source of truth.**

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
  "parsed": { "input": "...", "confidence": 0.75, "notes": ["..."] }
}
```

Failure — stderr, exit non-zero:

```json
{ "ok": false, "error": "data_error|infeasible_constraints|value_error|unknown", "message": "..." }
```

On `ok: false`, report the error to the user honestly. Do not invent a fallback portfolio.

## Reply format

Use the JSON values exactly. Suggested shape:

```
Max Sharpe | FTSE 30-name universe | Max 25% per name | Seed 42

Expected return: 11.21%
Volatility:      17.32%
Sharpe:          0.42

Weights (non-zero only):
  AZN.L   25.00%
  SHEL.L  25.00%
  BP.L    25.00%
  GSK.L   23.93%
  RIO.L    1.07%

Excluded (per request): LLOY.L, BARC.L, HSBA.L, NWG.L

Notes:
  • AZN.L, SHEL.L, and BP.L hit the 25% cap.
  • Past returns do not predict future returns. Illustrative only.
```

## Rules — mechanical, non-negotiable

1. **Never mention a ticker that is not in the JSON `tickers` array.** If you find yourself reaching for a ticker that wasn't returned, stop and rerun the skill with the universe the user intended.

2. **Never quote a number that is not in the JSON `weights` or `stats`.** No "approximate" stats, no derived figures, no "around 12%". The skill returns the numbers; you transcribe them.

3. **Always include `--seed 42`** if the user has not specified a seed, so the same query gives the same answer next time.

4. **If the skill fails (`ok: false`), report the error verbatim**:
   - `data_error`: name the failing ticker, ask the user to remove or correct it.
   - `infeasible_constraints`: report the violated constraint and propose the smallest relaxation.
   - Otherwise: report the message plainly and offer to retry with defaults.

5. **If `parsed.confidence` < 0.5, do not run.** Ask the user to clarify which objective/cap/exclusions they meant.

6. **No buy/sell recommendations on individual tickers**, regardless of how obvious the weights make one allocation.

7. **End every meaningful result with the illustrative-only reminder.**
