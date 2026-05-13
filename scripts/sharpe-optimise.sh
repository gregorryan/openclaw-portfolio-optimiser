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
# Within-turn throttling:
# We observed Sharpe occasionally invoking the wrapper twice within a
# single Telegram turn (e.g. re-running to verify a result, or after
# self-correction mid-turn). Each invocation produces a fresh run_id
# and a real chart, but the user only wants one chart per question. We
# throttle: if a chart was sent in the last THROTTLE_SECONDS, skip the
# next send. Crude but reliable — and uniqueness is enforced at the
# side-effect layer where the agent can't talk its way around it.
#
# Inputs: forwards all arguments to `python -m optimiser.cli optimise`.
# Outputs:
#   - stdout: the JSON from the optimiser CLI (unchanged).
#   - side effect: a Telegram message with the chart PNG attached,
#     subject to within-turn throttling.

set -euo pipefail

# Operator's Telegram user ID — the only person allowed to talk to the bot
# per channels.telegram.allowFrom in openclaw.json. Hard-coded for the
# DataVita Challenge submission; would be parameterised in production.
TELEGRAM_TARGET="8860847516"

PROJECT_DIR="/Users/gregorryan/code/openclaw-portfolio-optimiser"
THROTTLE_FILE="/tmp/sharpe-last-chart-sent"
THROTTLE_SECONDS=60  # one chart per 60s window; covers a single agent turn

cd "$PROJECT_DIR"

# Activate the project's venv so matplotlib, yfinance, and pandas resolve.
# shellcheck disable=SC1091
source .venv/bin/activate

# Run the optimiser. Forward every argument the agent passed verbatim.
JSON_OUTPUT="$(python -m optimiser.cli optimise "$@")"

# Print the JSON to stdout — agent's parsing flow is unchanged.
echo "$JSON_OUTPUT"

# Pull chart_path from the JSON in a single python invocation.
CHART_PATH="$(echo "$JSON_OUTPUT" | python -c '
import json, sys
try:
    data = json.load(sys.stdin)
    path = data.get("chart_path") or ""
    print(path)
except Exception:
    print("")
')"

if [[ -z "$CHART_PATH" ]]; then
    exit 0
fi

if [[ ! -f "$CHART_PATH" ]]; then
    echo "warning: chart file missing at $CHART_PATH; chart not sent" >&2
    exit 0
fi

# Throttle. If we sent a chart recently, skip this one. The user gets
# the first chart from the agent's turn and not the duplicates.
now="$(date +%s)"
if [[ -f "$THROTTLE_FILE" ]]; then
    last="$(cat "$THROTTLE_FILE" 2>/dev/null || echo 0)"
    elapsed="$((now - last))"
    if (( elapsed < THROTTLE_SECONDS )); then
        # Silent skip — not an error, by design.
        exit 0
    fi
fi

# Mark "send in progress" BEFORE the actual send. If two parallel calls
# both reach this point in the same millisecond they'll both think the
# field is clear, but the bigger picture is fine — the bash-level race
# window is much shorter than the agent's re-invocation cadence.
echo "$now" > "$THROTTLE_FILE"

# Send the chart. If openclaw message send fails, warn but don't abort —
# the text reply still goes out. Clear the throttle on failure so a
# manual retry can succeed immediately.
if ! openclaw message send \
        --channel telegram \
        --target "$TELEGRAM_TARGET" \
        --message "Portfolio weights chart" \
        --media "$CHART_PATH" \
        >/dev/null 2>&1; then
    rm -f "$THROTTLE_FILE"
    echo "warning: chart delivery via openclaw message send failed" >&2
fi
