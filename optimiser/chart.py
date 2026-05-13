"""Render portfolio weights as a PNG bar chart.

Used to attach a visual summary to Telegram replies. The image format
and dimensions are chosen for legibility in a phone chat window
(~600 px wide on most devices).

Design choices:
- Horizontal bars, sorted descending by weight. Easier to read on a
  narrow screen than vertical bars with rotated labels.
- Zero-weight tickers are omitted; cluttering the chart with empty bars
  hides the actual allocation.
- Output to ~/.openclaw/media/ — OpenClaw's allowlist of safe media
  paths includes this directory, so the agent can attach charts to
  Telegram replies via `openclaw message send --media <path>` without
  hitting LocalMediaAccessError.
- Headless backend (`Agg`) so matplotlib doesn't try to open a window
  when the CLI runs non-interactively.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")  # must be set before importing pyplot
import matplotlib.pyplot as plt


CHART_OUTPUT_DIR = os.path.expanduser("~/.openclaw/media")


def _ensure_output_dir() -> str:
    os.makedirs(CHART_OUTPUT_DIR, exist_ok=True)
    return CHART_OUTPUT_DIR


def render_weights_chart(
    weights: dict[str, float],
    title: str,
    subtitle: str | None = None,
    run_id: str | None = None,
) -> str:
    """Render a horizontal bar chart of portfolio weights.

    Args:
        weights: {ticker: weight} mapping. Zero/near-zero entries are dropped.
        title: chart title, e.g. "Max Sharpe portfolio".
        subtitle: optional second line (objective, universe, seed, etc.).
        run_id: included in the filename so concurrent runs don't collide.

    Returns:
        Absolute path to the written PNG file.
    """
    _ensure_output_dir()

    # Filter and sort
    non_zero = [(t, w) for t, w in weights.items() if w > 1e-4]
    non_zero.sort(key=lambda kv: kv[1], reverse=True)
    tickers = [t for t, _ in non_zero]
    values = [w * 100.0 for _, w in non_zero]  # render as percentages

    if not tickers:
        raise ValueError("no non-zero weights to chart")

    # Build figure
    height_per_bar = 0.45
    fig_height = max(3.0, height_per_bar * len(tickers) + 1.5)
    fig, ax = plt.subplots(figsize=(7.0, fig_height), dpi=140)

    y_pos = range(len(tickers))
    bars = ax.barh(
        list(y_pos),
        values,
        color="#1f6feb",
        edgecolor="white",
        height=0.7,
    )

    # Annotate each bar with the percentage value
    for bar, v in zip(bars, values):
        ax.text(
            v + 0.3,
            bar.get_y() + bar.get_height() / 2,
            f"{v:.1f}%",
            va="center",
            fontsize=10,
            color="#0d1117",
        )

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(tickers, fontsize=11)
    ax.invert_yaxis()  # largest at top
    ax.set_xlabel("Weight (%)", fontsize=10)
    ax.set_xlim(0, max(values) * 1.20)

    # Styling
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)

    # Title block
    fig.suptitle(title, fontsize=13, fontweight="bold", y=0.98)
    if subtitle:
        ax.set_title(subtitle, fontsize=10, color="#57606a", pad=10)

    plt.tight_layout(rect=(0, 0, 1, 0.96))

    # Output path: include UTC timestamp for uniqueness if no run_id
    suffix = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = os.path.join(CHART_OUTPUT_DIR, f"weights-{suffix}.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)

    return path
