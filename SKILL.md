---
name: portfolio-optimise
description: "Run a genetic algorithm to find optimal portfolio weights given a universe of tickers, an objective (max Sharpe, min variance, max return), and optional constraints (per-name cap, excluded tickers, minimum holdings). Optional train/test backtest mode reports both in-sample and out-of-sample performance. A chart of the weights is delivered to Telegram as a side effect of the wrapper."
metadata:
  {
    "openclaw":
      {
        "emoji": "📐",
        "requires": { "bins": ["bash"] },
      },
  }
---

# Portfolio Optimise Skill

Find optimal portfolio weights using a genetic algorithm against 5 years of daily-close adjusted prices from Yahoo Finance. Optionally hold out part of that history and report how the weights performed out-of-sample. A PNG chart of the weights is delivered to Telegram automatically.

## Critical: freshness verification

Every CLI run includes two fields you MUST quote in your reply:

- `run_id` — a fresh UUID, different on every invocation
- `timestamp` — UTC ISO-8601 stamp from the moment the CLI ran

**Every reply to a portfolio query must contain `run_id` and `timestamp` on a visible line.** If you cannot produce these values from a CLI run that JUST completed in this turn, you have not actually run the skill and must do so before replying.

**You may not paraphrase or summarise an earlier run.** If the user repeats a previous query, you re-run the CLI and quote the new `run_id` and `timestamp`. Different invocations always produce different IDs.

## When to Use

✅ **USE this skill when the user asks to:**

- "Optimise a portfolio of [tickers]"
- "Find max Sharpe weights for [universe]"
- "Build a min-variance portfolio from [universe]"
- "Backtest the strategy" or "How would these weights have done last year?"
- "Test the GA out-of-sample"
- Iterate on a previous run ("now cap at 10%", "exclude banks", "rerun with backtest")

## When NOT to Use

❌ **DON'T use this skill when the user asks for:**

- A specific stock recommendation
- Live or intraday prices
- Predictions of future prices
- Trade execution
- Walk-forward backtesting with rebalancing — this skill only does a single train/test split

## The universe

The skill operates on a **fixed 30-name FTSE 100 sample**:

LLOY.L, BARC.L, HSBA.L, NWG.L, AZN.L, GSK.L, ULVR.L, DGE.L, RKT.L, BATS.L, IMB.L, TSCO.L, SBRY.L, NXT.L, SHEL.L, BP.L, RIO.L, GLEN.L, AAL.L, VOD.L, BT-A.L, SSE.L, NG.L, SVT.L, AV.L, LGEN.L, PRU.L, LAND.L, BA.L, RR.L

**Nothing outside this list exists for this skill.** If the user says "FTSE 100" they get the 30 names above. The skill's JSON output is the only source of truth for tickers and weights.

## How to invoke

**Always call the wrapper script.** Do NOT call `python -m optimiser.cli` directly — the wrapper handles venv activation, JSON capture, and inline Telegram chart delivery in one atomic step.

**Optimisation mode (default):**

```bash
/Users/gregorryan/code/openclaw-portfolio-optimiser/scripts/sharpe-optimise.sh --from-text "<user's request>" --seed 42
```

**Backtest mode:**

```bash
/Users/gregorryan/code/openclaw-portfolio-optimiser/scripts/sharpe-optimise.sh --from-text "<user's request>" --backtest --seed 42
```

Backtest mode fits weights on the first 80% of the returns window and evaluates them on the held-out 20%. Use `--train-fraction 0.70` (or other) to adjust the split.

Always include `--seed 42` if the user has not specified a seed.

**The wrapper has two outputs:**
1. JSON to stdout — exactly what you'd get from the bare Python CLI; parse it as before.
2. A Telegram message with the chart PNG attached, delivered automatically to the user's chat. You do NOT need to send the chart yourself; that's handled by the wrapper. You only need to produce the text reply with the stats, weights, and interpretation.

## Output schema — optimise mode (default)

```json
{
  "ok": true,
  "mode": "optimise",
  "run_id": "a3f7c9d1e2b8",
  "timestamp": "2026-05-13T20:15:42+00:00",
  "chart_path": "/Users/gregorryan/.openclaw/media/weights-a3f7c9d1e2b8.png",
  "objective": "max_sharpe",
  "tickers": ["LLOY.L", "..."],
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

## Output schema — backtest mode

```json
{
  "ok": true,
  "mode": "backtest",
  "run_id": "39dc52e90c12",
  "timestamp": "2026-05-13T19:24:34+00:00",
  "chart_path": "/Users/gregorryan/.openclaw/media/weights-39dc52e90c12.png",
  "objective": "max_sharpe",
  "tickers": ["LLOY.L", "..."],
  "weights": { "BA.L": 0.25, "...": "..." },
  "train_stats": { "sharpe": 1.384, "...": "..." },
  "test_stats":  { "sharpe": 0.621, "...": "..." },
  "split": {
    "train_fraction": 0.8,
    "train_days": 1000,
    "test_days": 251
  },
  "summary": {
    "in_sample_sharpe": 1.384,
    "out_of_sample_sharpe": 0.621,
    "sharpe_gap": 0.763
  }
}
```

## Reply format — optimise mode

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

Past returns do not predict future returns. Illustrative only.
```

## Reply format — backtest mode

Include both in-sample and out-of-sample stats, with the sharpe_gap and an honest interpretation:

```
Max Sharpe | FTSE 30-name | 80/20 backtest | seed 42
run_id: 39dc52e90c12 | timestamp: 2026-05-13T19:24:34+00:00

In-sample (1000 days):       Sharpe 1.38, return 28.0%, vol 17.3%
Out-of-sample (251 days):    Sharpe 0.62, return 14.8%, vol 17.3%
Sharpe gap (in − out):       0.76

Weights:
  BA.L    25.0%
  IMB.L   25.0%
  RR.L    24.2%
  TSCO.L  16.3%
  NWG.L    9.6%

Interpretation: the GA found weights that performed strongly in 2021–2024
training data but gave back about half the Sharpe out-of-sample. This is
a typical overfitting signature — the weights are not a guaranteed
strategy, but the out-of-sample number (0.62) is the more honest estimate
of forward performance.

Past returns do not predict future returns. Illustrative only.
```

If the gap is negative or small, frame it as the test window happening to be unusually kind — not as evidence of "alpha". The point is to be honest about what the data does and doesn't show.

## Hard rules

1. **Every reply must include `run_id` and `timestamp` from a CLI run that completed in this turn.** No exceptions.
2. **Never mention a ticker that is not in the JSON `tickers` array** of the run you just quoted.
3. **Never quote a number that is not in the JSON `weights`, `stats`, `train_stats`, or `test_stats`** of the run you just quoted.
4. **If the user repeats a previous question, re-run the CLI.** Do not paraphrase a previous answer.
5. **If the user asks "how would this have done?"** or otherwise asks about historical performance, **use `--backtest`** rather than the default mode. The backtest is the honest answer; in-sample stats are not.
6. **You do not need to send the chart yourself.** The wrapper handles inline Telegram chart delivery. Just produce the text reply.
7. **If the wrapper returns `ok: false`, report the error verbatim** with the new `run_id` and `timestamp`.
8. **No buy/sell recommendations on individual tickers.**
9. **Always end with the illustrative-only reminder.**
