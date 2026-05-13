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

## Critical: freshness verification

Every CLI run includes two fields you MUST quote in your reply:

- `run_id` — a fresh UUID, different on every invocation
- `timestamp` — UTC ISO-8601 stamp from the moment the CLI ran

**Every reply to a user query about a portfolio must contain `run_id: <value>` and `timestamp: <value>` on a visible line.** If you cannot produce these values from a CLI run that JUST completed in this turn, you have not actually run the skill and must do so before replying.

**You may not paraphrase or summarise an earlier run.** If the user repeats a previous query, you re-run the CLI and quote the new `run_id` and `timestamp`. Different invocations always produce different IDs.

## When to Use

✅ **USE this skill when the user asks to:**

- "Optimise a portfolio of [tickers]"
- "Find max Sharpe weights for [universe]"
- "Build a min-variance portfolio from [universe]"
- Iterate on a previous run ("now cap at 10%", "exclude banks", "rerun")

## When NOT to Use

❌ **DON'T use this skill when the user asks for:**

- A specific stock recommendation
- Live or intraday prices
- Predictions of future prices
- Trade execution
- Backtesting a strategy

## The universe

The skill operates on a **fixed 30-name FTSE 100 sample**:

LLOY.L, BARC.L, HSBA.L, NWG.L, AZN.L, GSK.L, ULVR.L, DGE.L, RKT.L, BATS.L, IMB.L, TSCO.L, SBRY.L, NXT.L, SHEL.L, BP.L, RIO.L, GLEN.L, AAL.L, VOD.L, BT-A.L, SSE.L, NG.L, SVT.L, AV.L, LGEN.L, PRU.L, LAND.L, BA.L, RR.L

**Nothing outside this list exists for this skill.** If the user says "FTSE 100" they get the 30 names above. The skill's JSON output is the only source of truth for tickers and weights.

## How to invoke

```bash
cd /Users/gregorryan/code/openclaw-portfolio-optimiser && source .venv/bin/activate && \
  python -m optimiser.cli optimise --from-text "<user's request>" --seed 42
```

Always include `--seed 42` if the user has not specified a seed.

## Output schema

```json
{
  "ok": true,
  "run_id": "a3f7c9d1e2b8",
  "timestamp": "2026-05-13T20:15:42+00:00",
  "objective": "max_sharpe",
  "tickers": ["LLOY.L", "BARC.L", "..."],
  "excluded_tickers": ["SHEL.L", "BP.L"],
  "weights": { "LLOY.L": 0.2, "...": "..." },
  "stats": {
    "expected_return_pct": 13.84,
    "volatility_pct": 20.96,
    "sharpe": 0.47
  },
  "summary": { "...": "..." },
  "parsed": { "...": "..." }
}
```

## Reply format

Use the JSON values verbatim. Every reply must include `run_id` and `timestamp` on a visible line:

```
Max Sharpe | FTSE 30-name universe | seed 42
run_id: a3f7c9d1e2b8 | timestamp: 2026-05-13T20:15:42+00:00

Expected return: 11.21%
Volatility:      17.32%
Sharpe:          0.42

Weights (non-zero only):
  AZN.L   25.00%
  SHEL.L  25.00%
  ...

Excluded (per request): LLOY.L, BARC.L, HSBA.L, NWG.L

Past returns do not predict future returns. Illustrative only.
```

## Hard rules

1. **Every reply must include `run_id` and `timestamp` from a CLI run that completed in this turn.** No exceptions.
2. **Never mention a ticker that is not in the JSON `tickers` array** of the run you just quoted.
3. **Never quote a number that is not in the JSON `weights` or `stats`** of the run you just quoted.
4. **If the user repeats a previous question, re-run the CLI.** Do not paraphrase a previous answer.
5. **If the skill returns `ok: false`, report the error verbatim** with the new `run_id` and `timestamp`.
6. **If `parsed.confidence` < 0.5, do not run.** Ask the user to clarify.
7. **No buy/sell recommendations on individual tickers.** This is illustrative optimisation only.
