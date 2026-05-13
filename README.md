# OpenClaw Portfolio Optimiser

A Telegram-facing AI agent for natural-language portfolio optimisation, built on OpenClaw with a genetic algorithm under the hood.

Submission for the [DataVita OpenClaw Challenge 2026](https://jobs.datavita.co.uk/openclaw-challenge).

## Concept

Define a universe, objective, and constraints in plain English on Telegram — "FTSE 100, max Sharpe, exclude banks, cap 10% per name" — and a GA returns optimal weights with an explanation. Iterate by talking to the agent.

## Status

Under active development. See commit history for progress.

## Stack

- [OpenClaw](https://openclaw.ai) — AI agent gateway
- Python — optimisation logic (genetic algorithm)
- Telegram Bot API — user interface
- Anthropic Claude Sonnet 4.6 — natural-language reasoning
- yfinance — market data
