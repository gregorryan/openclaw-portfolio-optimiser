# Sharpe — Natural-language Portfolio Optimisation

An AI agent you can talk to on Telegram to construct optimal portfolios. Tell it what you want — *"FTSE max Sharpe, exclude banks, cap 10% per name, backtest"* — and a genetic algorithm finds weights that satisfy those constraints, then reports how the strategy would have performed out-of-sample. The reply arrives as text plus an inline PNG chart of the weights.

Submission for the [DataVita OpenClaw Challenge 2026](https://jobs.datavita.co.uk/openclaw-challenge).

[![CI](https://github.com/gregorryan/openclaw-portfolio-optimiser/actions/workflows/ci.yml/badge.svg)](https://github.com/gregorryan/openclaw-portfolio-optimiser/actions/workflows/ci.yml)

## The problem

Portfolio optimisation is a textbook discipline with serious practical friction. The maths is well-understood — Markowitz, Black-Litterman, risk-parity, all decades old — but the tooling is either Excel sheets that don't compose, expensive licensed software, or Python notebooks that nobody outside quant teams can use.

The natural-language barrier matters. A trader who can articulate *"I want max Sharpe but no more than 10% in any single name, exclude oil, and at least 8 holdings"* in seconds will spend half an hour translating that into code or a Bloomberg query.

Sharpe collapses that translation. You describe the portfolio you want in plain English; a genetic algorithm finds it; the agent explains what it did, shows the out-of-sample numbers, and tells you honestly whether the result generalised.

## What it does

- **Pulls 5 years of daily-close prices** from Yahoo Finance for any universe of tickers
- **Parses constraints from plain English** via a deterministic rule-based layer — objectives, caps, sector exclusions, min-holdings — with a confidence score
- **Runs a genetic algorithm** to maximise one of three objectives: Sharpe, expected return, or negative variance
- **Backtests with an 80/20 train/test split** so you see in-sample *and* out-of-sample performance, plus the Sharpe gap (the overfitting diagnostic)
- **Renders a PNG chart** of the weights and delivers it inline alongside the text reply on Telegram
- **Iterates conversationally** — *"now exclude pharma"*, *"rerun with backtest"*, *"cap 8% instead"*

## Architecture

```
                    ┌──────────────┐
                    │   Telegram   │  ← User talks here
                    │   (mobile)   │
                    └──────┬───────┘
                           │ Bot API
                    ┌──────▼────────┐
                    │   OpenClaw    │  ← Agent gateway (systemd user service)
                    │    Gateway    │  ← persona = Sharpe (SOUL.md)
                    └──────┬────────┘
                           │ exec
                    ┌──────▼────────┐
                    │ portfolio-    │  ← SKILL.md teaches Sharpe
                    │ optimise      │     when/how to call the wrapper
                    │ (skill)       │
                    └──────┬────────┘
                           │ scripts/sharpe-optimise.sh
                    ┌──────▼────────┐
                    │  Wrapper      │  ← runs CLI, parses JSON,
                    │  (bash)       │     sends chart inline
                    └──────┬────────┘
                           │ python -m optimiser.cli
                    ┌──────▼────────┐
                    │  CLI (JSON    │  ← argparse, returns structured
                    │   in/out)     │     output + run_id + chart_path
                    └──────┬────────┘
                           │
   ┌──────────┬──────┬─────┴───┬──────────┬──────────┐
   ▼          ▼      ▼         ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌────────┐ ┌─────────┐
│ data │ │parser│ │fitnss│ │  ga  │ │backtest│ │  chart  │
│ (yf) │ │(regx)│ │ (np) │ │(numpy│ │ (split)│ │ (mpl)   │
└──────┘ └──────┘ └──────┘ └──────┘ └────────┘ └─────────┘
```

Seven production modules:

- **`optimiser/data.py`** — yfinance wrapper, log-returns, 30-name FTSE universe + sector groupings
- **`optimiser/parser.py`** — deterministic NLP layer: objectives, caps, sector-aware exclusions, min-holdings, confidence score, and a defended trust boundary (length cap, control-character rejection, prompt-injection flagging)
- **`optimiser/fitness.py`** — annualised mean/vol/Sharpe, three objectives, UK-gilt-anchored risk-free rate (~4%)
- **`optimiser/constraints.py`** — feasibility checks + iterative clip-and-renormalise repair operator
- **`optimiser/ga.py`** — tournament selection, single-point crossover, gaussian mutation, elitism
- **`optimiser/backtest.py`** — train/test split with in-sample / out-of-sample stats and the Sharpe gap diagnostic
- **`optimiser/chart.py`** — matplotlib bar chart of weights, written to an OpenClaw-allowlisted media path

Plus the agent layer:

- **`SOUL.md`** — Sharpe's identity, scope, and tone (anti-chatbot-ese, anti-investment-advice, finance-literate)
- **`SKILL.md`** — runbook teaching the agent when to call the wrapper, how to format results, and the rules that prevent hallucination
- **`scripts/sharpe-optimise.sh`** — atomic wrapper: runs the CLI, parses `chart_path` from JSON, sends the chart inline to Telegram, with a 60-second throttle to deduplicate within-turn re-invocations

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

The bot lives at `@gregor_portfolio_bot` on Telegram. To request access for evaluation, send the operator your numeric Telegram user ID via the email on the GitHub profile. You'll be added to the allowlist and can then DM the bot directly.

Example prompts that work:

```
Optimise a max-Sharpe portfolio from the FTSE universe, cap 25% per name,
seed 42.

Build a min-variance portfolio with at least 8 holdings and 15% cap.

Backtest a max-Sharpe FTSE portfolio with 20% cap and exclude banks.

Now also exclude energy and rerun.
```

## Hosting & access

The bot runs on an **always-free Oracle Cloud ARM instance** (Ubuntu 22.04, 1 OCPU, 6 GB RAM, UK South region), managed as a systemd user service that auto-restarts on crash and survives reboots. Telegram polling is outbound from the server, so no inbound ports are exposed to the public internet — the entire reachable surface is the Telegram Bot API mediated by the allowlist.

The local-loopback gateway model from OpenClaw is preserved on the server: the gateway binds to `127.0.0.1`, only the Telegram channel reaches outbound. This is OpenClaw's local-first philosophy applied to a small cloud VM rather than retrofitted into a generic cloud-hosted-bot pattern. From a security and architecture standpoint the bot is "one operator's machine"; the operator just happens to be a 24/7 cloud VM rather than a laptop.

The Anthropic backend uses Claude Code's CLI bridge (`agentRuntime.id: "claude-cli"`) which delegates inference to a long-lived OAuth subscription. This keeps deployment cost predictable (Claude Max subscription, no per-token API spend) and aligns with Anthropic's recommended path for headless OpenClaw operation.

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

### Why a wrapper script for chart delivery

The agent (Sonnet, then Opus) reliably ran the optimiser when prompted by SKILL.md, but inconsistently chained the follow-up `openclaw message send --media` call needed to attach the chart inline. Wrapping both calls into a single bash script removes that decision from the agent. The wrapper runs the Python CLI, parses `chart_path` from the JSON, and delivers the chart as a side effect — with a 60-second throttle to deduplicate within-turn re-invocations. Same pattern as the run_id fix: replace "trust the agent" with mechanical guarantees at the side-effect layer.

### Why local-first-as-cloud-VM deployment

OpenClaw's design intent is a personal AI assistant on your own devices, with a loopback-only gateway and the operator as the single trust boundary. This submission honours that model literally — the gateway binds to `127.0.0.1`, all reachable surface is mediated by the Telegram allowlist — but runs the "device" on an always-free Oracle Cloud ARM VM so the bot is internet-reachable 24/7 without depending on the operator's laptop. The deployment is the OpenClaw model, not a generic cloud-bot retrofit; the only thing different from a laptop deployment is that the device never sleeps.

### Compliance posture

Sharpe refuses buy/sell recommendations on individual securities and frames all outputs as illustrative. This is non-negotiable for any consumer-facing financial tool. The agent is configured (via SOUL.md) to redirect such requests toward defining an objective and constraints.

## Security

A finance-adjacent tool exposed via Telegram has a real security surface. The project takes the following measures:

**Gateway**: bound to loopback (`127.0.0.1`) only, never `0.0.0.0`. No inbound traffic from the network can reach the OpenClaw gateway directly; Telegram polls outbound. The `controlUi.allowInsecureAuth` flag is disabled, so even local dashboard access requires a token.

**Telegram channel**: DM access is restricted by `channels.telegram.allowFrom`, an explicit allowlist of Telegram user IDs. Group access requires the bot to be `@`-mentioned. Anyone else messaging the bot directly is ignored.

**No buy/sell recommendations on individual securities.** Sharpe is configured at the SOUL.md layer to refuse this and redirect to constraint definition. Every reply ends with an illustrative-only disclaimer. The optimiser does not connect to any broker, exchange, or order-execution system.

**LLM output verification**: each CLI invocation emits a fresh UUID (`run_id`) and ISO-8601 timestamp. SKILL.md requires the agent to quote both in every reply. If a reply lacks a fresh `run_id`, the agent didn't actually run the optimiser — it cached a previous result. This makes a class of LLM hallucination *mechanically* detectable rather than relying on trust.

**Parser input bounds**: the natural-language parser caps inputs at 500 characters, rejects control characters, and flags common prompt-injection patterns (lowering confidence and emitting a note for the agent to handle). 16 dedicated tests in `tests/test_parser_validation.py` cover the trust-boundary behaviour. Not a guarantee against motivated attackers — raises the bar.

**Tokens** are stored in `~/.openclaw/openclaw.json` (permissions 600) and `~/.openclaw/devices/paired.json`. All tokens were rotated as part of preparing this submission. No tokens are committed to the repository. Pre-commit (`detect-secrets`) and CI (`detect-secrets-hook` baseline check) both run on every commit and every push.

**No write access to external systems**: the optimiser reads market data (Yahoo Finance, public) and writes only to its own workspace and a designated media directory. It does not write to email, calendars, files outside the project, or any third-party service.

**Known limitations**: the agent runs on a single VM with a single operator trust boundary — same model as a laptop deployment, just on a cloud instance. If the VM is compromised at the OS level, the gateway is too. This is by design and aligned with OpenClaw's philosophy, but is not appropriate for multi-tenant cloud deployment without additional hardening (per-user isolation, secret-store integration, audit logging).

See [SECURITY.md](SECURITY.md) for the full threat model, mitigations table, and token rotation runbook.

## Engineering

- **129 tests**, all passing, sub-2-second runtime, network calls mocked
- **Conventional Commits** throughout — `feat(ga):`, `fix(persona):`, `test(backtest):` — for legible history
- **Type hints, dataclasses, docstrings** across every module
- **JSON I/O at the CLI boundary** so the agent never has to parse Python tracebacks
- **Float-safety**: explicit guards against numpy edge cases (a known bug caught and fixed during testing — see `fix(fitness)` and `fix(constraints)` commits)
- **CI on every push**: pytest (Python 3.13 on Ubuntu) and `detect-secrets-hook` baseline check, both must pass before merge

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
- **Per-user rate limiting** — currently blocked by OpenClaw issue #29474 (Telegram sender ID not exposed to skill exec environment for text/photo messages). Access control falls back to the channel allowlist.
- **Multi-tenant deployment** with per-user isolation, secret-store integration, and audit logging — out of scope for a one-operator submission.

## Stack

- [OpenClaw](https://openclaw.ai) (gateway, skills, persona)
- Anthropic Claude Opus 4.7 (language reasoning via Claude Code subscription auth, CLI bridge)
- Telegram Bot API (channel)
- Python 3.13 — numpy, pandas, yfinance, matplotlib, pytest
- Oracle Cloud Free Tier ARM (host) — Ubuntu 22.04, systemd user service

## Acknowledgements

Built for the [DataVita OpenClaw Challenge 2026](https://jobs.datavita.co.uk/openclaw-challenge). Submitted by Gregor Ryan, Glasgow.
