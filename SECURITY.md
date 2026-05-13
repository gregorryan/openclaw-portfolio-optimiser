# Security policy

## Threat model

This project exposes a portfolio optimiser via Telegram. The realistic threats are:

1. **Credential exfiltration** — gateway token, Telegram bot token, or device tokens being read by an attacker, allowing impersonation of the operator's bot.
2. **Prompt injection** — a Telegram message crafted to manipulate the agent (Sharpe) into doing something it shouldn't (e.g. revealing operator information, ignoring constraints).
3. **Resource exhaustion** — a malicious message causing the optimiser to consume excessive CPU, network, or LLM API quota.
4. **Output manipulation** — the agent describing results that the underlying CLI never actually produced (LLM hallucination).

Threats explicitly **out of scope**:

- Compromise of the operator's host machine (OS-level access). The gateway is loopback-only by design; if an attacker is already executing code as the operator, the gateway is the smaller of their concerns.
- Compromise of upstream services (Yahoo Finance, Anthropic, Telegram). The project assumes these are trustworthy.
- Targeted attacks against the operator's identity (e.g. SIM-swap of the Telegram account). Out of project scope.

## Mitigations in place

| Threat | Mitigation |
|---|---|
| Credential exfiltration | Pre-commit secret scanning (`detect-secrets`), CI-side baseline check, tokens in `~/.openclaw/*` with permissions `600`, never committed |
| Prompt injection | Parser-layer trust boundary: length cap (500 chars), control-character rejection, heuristic flagging of common injection patterns (lowers confidence, adds notes) |
| Resource exhaustion | Telegram channel allowlist (`channels.telegram.allowFrom`); GA hyperparameters capped (population ≤ 100, generations ≤ 200); single-process gateway |
| Output manipulation | Every CLI invocation emits a fresh `run_id` (UUID) and ISO-8601 timestamp; agent SOUL.md / SKILL.md require quoting both. A reply without a fresh `run_id` did not actually run the optimiser. |

## Reporting a vulnerability

Email the operator at the address on the GitHub profile. Include:

- A description of the issue and its impact.
- A proof-of-concept if possible.
- Whether you've disclosed publicly elsewhere.

Expected response time: 5 business days for acknowledgement. I'll aim to ship a fix or workaround within 30 days for high-severity issues.

## Token rotation runbook

### Gateway token

The gateway uses a bearer token stored at `gateway.auth.token` in `~/.openclaw/openclaw.json`. To rotate:

```bash
