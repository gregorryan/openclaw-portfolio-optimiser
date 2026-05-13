# Sharpe — Natural-language Portfolio Optimisation

An AI agent you can talk to on Telegram to construct optimal portfolios. Tell it what you want — *"FTSE max Sharpe, exclude banks, cap 10% per name, backtest"* — and a genetic algorithm finds weights that satisfy those constraints, then reports how the strategy would have performed out-of-sample.

Submission for the [DataVita OpenClaw Challenge 2026](https://jobs.datavita.co.uk/openclaw-challenge).

## The problem

Portfolio optimisation is a textbook discipline with serious practical friction. The maths is well-understood — Markowitz, Black-Litterman, risk-parity, all decades old — but the tooling is either Excel sheets that don't compose, expensive licensed software, or Python notebooks that nobody outside quant teams can use.

The natural-language barrier matters. A trader who can articulate *"I want max Sharpe but no more than 10% in any single name, exclude oil, and at least 8 holdings"* in seconds will spend half an hour translating that into code or a Bloomberg query.

Sharpe collapses that translation. You describe the portfolio you want in plain English; a genetic algorithm finds it; the agent explains what it did, shows the out-of-sample numbers, and tells you honestly whether the result generalised.

## What it does

- **Pulls 5 years of daily-close prices** from Yahoo Finance for any universe of tickers
- **Parses constraints from plain English** via a deterministic rule-based layer — objectives, caps, sector exclusions, min-holdings — with a confidence score
- **Runs a genetic algorithm** to maximise one of three objectives: Sharpe, expected return, or negative variance
- **Backtests with an 80/20 train/test split** so you see in-sample *and* out-of-sample performance, plus the Sharpe gap (the overfitting diagnostic)
- **Reports results in a Telegram-friendly format** with weights, annualised stats, and an explanation of why the GA landed where it did
- **Iterates conversationally** — *"now exclude pharma"*, *"rerun with backtest"*, *"cap 8% instead"*

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
                    │   in/out)     │     structured output + run_id
                    └──────┬────────┘
                           │
       ┌──────────┬────────┼──────────┬──────────┐
       ▼          ▼        ▼          ▼          ▼
   ┌───────┐  ┌───────┐ ┌───────┐ ┌───────┐ ┌────────┐
   │ data  │  │parser │ │fitness│ │  ga   │ │backtest│
   │ (yf)  │  │(regex)│ │ (np)  │ │(numpy)│ │(split) │
   └───────┘  └───────┘ └───────┘ └───────┘ └────────┘
```

Six production modules:

- **`optimiser/data.py`** — yfinance wrapper, log-returns, 30-name FTSE universe + sector groupings
- **`optimiser/parser.py`** — deterministic NLP layer: objectives, caps, sector-aware exclusions, min-holdings, confidence score
- **`optimiser/fitness.py`** — annualised mean/vol/Sharpe, three objectives, UK-gilt-anchored risk-free rate (~4%)
- **`optimiser/constraints.py`** — feasibility checks + iterative clip-and-renormalise repair operator
- **`optimiser/ga.py`** — tournament selection, single-point crossover, gaussian mutation, elitism
- **`optimiser/backtest.py`** — train/test split with in-sample / out-of-sample stats and the Sharpe gap diagnostic

Plus the agent layer:

- **`SOUL.md`** — Sharpe's identity, scope, and tone (anti-chatbot-ese, anti-investment-advice, finance-literate)
- **`SKILL.md`** — runbook teaching the agent when to call the CLI, how to format results, and the rules that prevent hallucination

## Results

### Single-fit optimisation, 10-name FTSE, 5-year window, max-Sharpe, 25% cap

| Portfolio       | Annual return | Annual vol | Sharpe |
|-----------------|---------------|-----------|--------|
| Equal-weighted  | 8.45%         | 14.60%    | 0.31   |
| GA-optimised    | 15.83%        | 17.02%    | **0.70** |

The GA produced 2.3× the risk-adjusted return of the naive baseline, converging in ~25 generations.

### Backtest: 30-name FTSE, max-Sharpe, 25% cap, 80/20 split

| Window                         | Days | Return | Vol    | Sharpe |
|--------------------------------|------|--------|--------|--------|
| In-sample (training)           | 1000 | 27.99% | 17.34% | 1.384  |
| Out-of-sample (held-out)       |  251 | 14.77% | 17.34% | **0.621** |
| Sharpe gap (in − out)          |   —  |   —    |   —    | 0.763  |

A positive Sharpe gap of this size is the textbook overfitting signature. **The honest number to evaluate this strategy by is 0.62, not 1.38** — the GA "won" on the training window but gave back about half the performance on data it never saw. This is exactly what a backtest is for: surfacing that gap so it can be reported, not hidden.

The strategy concentrated in BA.L (defence), IMB.L (tobacco), RR.L (defence), TSCO.L (retail), and NWG.L (banks). A different train/test split, or a different universe, would tell a different story — single splits are illustrative, not predictive.

## Try it

The bot lives at `@gregor_portfolio_bot` on Telegram. DM access is allowlisted to the operator (judges: contact the operator to request access).

Example prompts that work:

```
Optimise a max-Sharpe portfolio from the FTSE universe, cap 25% per name,
seed 42.

Build a min-variance portfolio with at least 8 holdings and 15% cap.

Backtest a max-Sharpe FTSE portfolio with 20% cap and exclude banks.

Now also exclude energy and rerun.
```

## Design rationale

### Why a genetic algorithm

Closed-form quadratic-programming solvers (e.g. Markowitz with `cvxpy`) are faster and more accurate for *clean* convex problems. The moment you add discrete constraints — "at least 8 holdings", "exclude this sector", "at least one bank" — the problem stops being convex and QP either fails or requires reformulation. A GA handles arbitrary constraints uniformly via the repair operator, at the cost of slightly suboptimal solutions. For an exploratory, conversational tool where users want to iterate over a constraint set, that trade-off is correct.

### Why repair, not penalty

The two standard approaches to GA constraint handling are *penalty* (subtract a cost proportional to violation from fitness) and *repair* (project infeasible candidates back into the feasible region before evaluation). Repair guarantees every evaluated individual is feasible, so the search budget isn't spent ranking infeasibilities. It also produces interpretable failure modes: an infeasible constraint set surfaces immediately as `InfeasibleConstraints` rather than as a low-fitness population the agent has to explain away.

### Why a rule-based NLP parser (not an LLM call)

The OpenClaw agent layer already provides LLM-grade interpretation — that's what Sonnet does when reading a user's message. Adding a *second* LLM-based parser would duplicate that work. What's missing in most "AI" projects is a *visible, testable, deterministic* layer that you can point to and verify: given input X, the parser always returns Y. Tests like `parse_request("exclude banks") → StructuredRequest(excluded=("LLOY.L","BARC.L","HSBA.L","NWG.L"))` read more rigorously than "the LLM figures it out". 56 parametrised tests cover the common phrasings; uncommon ones fall back to the LLM.

### Why honest backtesting, not "alpha"

A single fit, no rebalancing, no transaction costs, on a universe that wasn't curated for survivorship bias — that's an illustrative backtest, not a strategy. The Sharpe gap (in-sample minus out-of-sample) is the headline diagnostic precisely because most ML-finance projects hide it. We show it as the centre of the result.

### Why the run_id / timestamp pattern

Early in development the agent would sometimes describe results without actually running the skill — Sonnet would pull a plausible-looking answer from chat history rather than re-invoke the CLI. The fix: every CLI invocation now emits a fresh UUID and ISO-8601 timestamp, and SKILL.md requires the agent to quote both in every reply. **Hallucination is now mechanically detectable** — if the run_id isn't a fresh UUID minted in the current turn, the agent didn't run the skill. This is a small but genuine engineering response to a known LLM failure mode.

### Why local-first deployment

OpenClaw's design intent is a personal AI assistant on your own devices. This submission runs on the operator's machine as a LaunchAgent, surviving sleep/wake cycles, reachable from anywhere via Telegram's outbound polling model. The deployment story is deliberately aligned with OpenClaw's vision rather than retrofitted into a generic cloud-hosted-bot pattern.

### Compliance posture

Sharpe refuses buy/sell recommendations on individual securities and frames all outputs as illustrative. This is non-negotiable for any consumer-facing financial tool. The agent is configured (via SOUL.md) to redirect such requests toward defining an objective and constraints.

## Engineering

- **113 tests**, all passing, sub-2-second runtime, network calls mocked
- **Conventional Commits** throughout — `feat(ga):`, `fix(persona):`, `test(backtest):` — for legible history
- **Type hints, dataclasses, docstrings** across every module
- **JSON I/O at the CLI boundary** so the agent never has to parse Python tracebacks
- **Float-safety**: explicit guards against numpy edge cases (a known bug Caught and Fixed during testing — see `fix(fitness)` and `fix(constraints)` commits)

```bash
git clone https://github.com/gregorryan/openclaw-portfolio-optimiser.git
cd openclaw-portfolio-optimiser
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

You can drive the optimiser directly without the agent:

```bash
# Single-fit optimisation
python -m optimiser.cli optimise \
  --from-text "max sharpe, exclude banks, cap 25%" --seed 42

# Train/test backtest
python -m optimiser.cli optimise \
  --from-text "max sharpe, cap 25%" --backtest --seed 42
```

## Future work

- **Walk-forward backtesting** — re-fit weights every N months, rebalance, compound returns over the full window. The current backtest is single-split.
- **Transaction costs** in the backtest — slippage, commission, bid-ask spread.
- **Survivorship-bias correction** — historical FTSE constituents over time, not just the current 30.
- **Efficient-frontier sweep** — plot return vs. vol across multiple risk targets.
- **Chart image attachment** — send a matplotlib bar chart of the weights inline with the Telegram reply.
- **Cloud deployment** with secrets via a managed secret store, for operators who'd rather not host locally.

## Stack

- [OpenClaw](https://openclaw.ai) (gateway, skills, persona)
- Anthropic Claude Sonnet 4.6 (language reasoning via Claude Code subscription auth)
- Telegram Bot API (channel)
- Python 3.13 — numpy, pandas, yfinance, pytest

## Acknowledgements

Built for the [DataVita OpenClaw Challenge 2026](https://jobs.datavita.co.uk/openclaw-challenge). Submitted by Gregor Ryan, Glasgow.
