#!/usr/bin/env bash
# sharpe-optimise.sh — agent-facing wrapper around the optimiser CLI.
#
# Why this exists:
# The agent (Sharpe) reads SKILL.md and follows the runbook for HOW to
# call the optimiser. But chaining "run the CLI then send the chart"
# across two separate commands proved unreliable — the agent would
# sometimes skip the second command. This wrapper makes the two steps
# atomic from the agent's perspective: it sees one command, gets one
# JSON payload back, and the chart is delivered inline as a side effect
# rather than as a second action the agent has to remember to take.
#
# Inputs: forwards all arguments to `python -m optimiser.cli optimise`.
# Outputs:
#   - stdout: the JSON from the optimiser CLI (unchanged, so the agent
#     can still parse run_id, weights, stats, etc.)
#   - side effect: a Telegram message with the chart PNG attached,
#     delivered to the operator's chat (TELEGRAM_TARGET below).

set -euo pipefail

# Operator's Telegram user ID — the only person allowed to talk to the bot
# per channels.telegram.allowFrom in openclaw.json. Hard-coded for the
# DataVita Challenge submission; would be parameterised in production.
TELEGRAM_TARGET="8860847516"

PROJECT_DIR="/Users/gregorryan/code/openclaw-portfolio-optimiser"
cd "$PROJECT_DIR"

# Activate the project's venv so matplotlib, yfinance, and pandas resolve.
# shellcheck disable=SC1091
source .venv/bin/activate

# Run the optimiser. Forward every argument the agent passed verbatim.
# We capture the JSON so we can both reprint it AND extract chart_path
# without paying for a second invocation.
JSON_OUTPUT="$(python -m optimiser.cli optimise "$@")"

# Print the JSON to stdout so the agent's parsing flow is unchanged.
echo "$JSON_OUTPUT"

# Best-effort chart delivery. Parse chart_path from the JSON; if it's
# missing or null (e.g. --no-chart was passed, or chart rendering failed),
# just exit cleanly — we already emitted the JSON.
CHART_PATH="$(echo "$JSON_OUTPUT" | python -c '
import json, sys
try:
    data = json.load(sys.stdin)
    path = data.get("chart_path")
    if path:
        print(path)
except Exception:
    pass
')"

if [[ -z "$CHART_PATH" ]]; then
    # No chart to send. Not an error — the JSON itself is the result.
    exit 0
fi

if [[ ! -f "$CHART_PATH" ]]; then
    # Chart path was reported but the file isn't there. Surface this in
    # stderr so the agent's tool output captures it, but don't fail the
    # whole run.
    echo "warning: chart file missing at $CHART_PATH; chart not sent" >&2
    exit 0
fi

# Send the chart inline. If openclaw message send fails (gateway down,
# scope issue, network blip), we warn but don't abort — the user still
# gets the text reply from the agent.
if ! openclaw message send \
        --channel telegram \
        --target "$TELEGRAM_TARGET" \
        --message "Portfolio weights chart" \
        --media "$CHART_PATH" \
        >/dev/null 2>&1; then
    echo "warning: chart delivery via openclaw message send failed" >&2
fi
