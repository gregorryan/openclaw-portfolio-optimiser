"""Natural-language → structured request parser.

Turns free-text portfolio requests into a typed object the CLI can consume.

Design choices:
- Pure-Python regex matching; no LLM dependency. Tests run in milliseconds
  and parsing is deterministic.
- Sector resolution uses optimiser.data.SECTORS — single source of truth
  so a universe change is automatically reflected here.
- Returns a confidence score so the agent layer can decide whether to
  trust the parsed result or fall back to LLM interpretation.
- Input is bounded and sanitised before extraction (length cap, control
  character rejection, soft prompt-injection flagging). The parser is a
  trust boundary between user-supplied Telegram text and the GA layer;
  cheap defence here is much better than relying on downstream
  components to handle weird input gracefully.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from optimiser.data import SECTORS
from optimiser.fitness import Objective


# ---------------------------------------------------------------------------
# Input bounds
# ---------------------------------------------------------------------------
# A typical legitimate portfolio request is 30–150 characters. Hard-cap well
# above that so legitimate users never hit the limit, but low enough that
# pasted document dumps, log spew, or megabyte-sized junk strings are
# rejected before they hit the regex engine.
MAX_INPUT_LENGTH = 500

# Control characters except space (0x20), horizontal tab (0x09) and newline
# (0x0a). Their presence in a "natural language request" is a strong signal
# that the input was machine-generated or attempting to confuse downstream
# layers.
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# Soft prompt-injection detection. Not a security guarantee — a determined
# attacker can phrase around these. The purpose is to (a) lower confidence,
# (b) record a note for the operator, (c) make the agent reconsider blindly
# trusting the parsed result. The parser still returns a structured object
# so legitimate-looking parts of the request are not silently dropped.
_SUSPICIOUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b", re.I),
     "prompt-injection attempt: 'ignore previous instructions'"),
    (re.compile(r"\bsystem\s*[:>]\s*", re.I),
     "prompt-injection attempt: 'system:' prefix"),
    (re.compile(r"```|<\|im_start\|>|<\|im_end\|>", re.I),
     "code-fence or chat-template markers in input"),
    (re.compile(r"\b(?:run|exec|execute|eval)\s+(?:command|shell|code|bash)\b", re.I),
     "suspicious instruction to execute code"),
    (re.compile(r"</?(?:script|iframe|object)", re.I),
     "HTML/script tags in input"),
]


# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------
OBJECTIVE_PATTERNS: list[tuple[re.Pattern[str], Objective]] = [
    (re.compile(r"\bmax(?:imise|imize)?\s+sharpe\b", re.I), Objective.MAX_SHARPE),
    (re.compile(r"\bhighest\s+sharpe\b", re.I), Objective.MAX_SHARPE),
    (re.compile(r"\bbest\s+sharpe\b", re.I), Objective.MAX_SHARPE),
    (re.compile(r"\bsharpe\b", re.I), Objective.MAX_SHARPE),
    (re.compile(r"\bmin(?:imise|imize)?\s+var(?:iance)?\b", re.I), Objective.MIN_VARIANCE),
    (re.compile(r"\bmin(?:imise|imize)?\s+vol(?:atility)?\b", re.I), Objective.MIN_VARIANCE),
    (re.compile(r"\blowest\s+vol(?:atility)?\b", re.I), Objective.MIN_VARIANCE),
    (re.compile(r"\bdefensive\b", re.I), Objective.MIN_VARIANCE),
    (re.compile(r"\bmax(?:imise|imize)?\s+return\b", re.I), Objective.MAX_RETURN),
    (re.compile(r"\bhighest\s+return\b", re.I), Objective.MAX_RETURN),
    (re.compile(r"\baggressive\b", re.I), Objective.MAX_RETURN),
]

CAP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bmax(?:imum)?\s+(\d+(?:\.\d+)?)\s*%", re.I),
    re.compile(r"\bcap(?:ped)?\s+(?:at\s+)?(\d+(?:\.\d+)?)\s*%", re.I),
    re.compile(r"\bno\s+more\s+than\s+(\d+(?:\.\d+)?)\s*%", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s*%\s+(?:per\s+name|per\s+stock|max)", re.I),
    re.compile(r"\bmax\s+weight\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*%", re.I),
]

MIN_HOLDINGS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bat\s+least\s+(\d+)\s+(?:holdings?|names?|positions?|stocks?)", re.I),
    re.compile(r"\bmin(?:imum)?\s+(\d+)\s+(?:holdings?|names?|positions?|stocks?)", re.I),
    re.compile(r"\b(\d+)\+\s+(?:holdings?|names?|positions?|stocks?)", re.I),
]

TICKER_PATTERN = re.compile(r"\b([A-Z]{1,5}(?:-[A-Z])?\.L|[A-Z]{2,5})\b")

TICKER_BLOCKLIST: set[str] = {
    "FTSE", "GA", "AI", "ML", "USD", "GBP", "EUR", "EU", "UK", "US",
    "FAANG", "MAG", "NYSE", "LSE", "ETF", "API", "CLI", "JSON", "CEO",
    "CFO", "ESG", "VIX", "GDP", "CPI", "PMI", "PE", "EPS",
}

EXCLUSION_TRIGGERS = re.compile(
    r"\b(?:exclude|excluding|no|without|drop|skip|remove)\s+"
    r"(.+?)"
    r"(?=[,;]|$|\s+(?:cap|max|min|at\s+least|with|but|that|which))",
    re.I,
)


@dataclass(frozen=True)
class StructuredRequest:
    """Parsed portfolio request, ready for the CLI."""

    objective: Objective | None = None
    tickers: tuple[str, ...] = ()
    max_weight: float | None = None
    min_holdings: int | None = None
    excluded_tickers: tuple[str, ...] = ()
    confidence: float = 1.0
    notes: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_input(text: str) -> tuple[bool, list[str]]:
    """Run cheap checks before parsing.

    Returns (is_safe_to_parse, notes). If is_safe_to_parse is False, the
    caller should return an empty StructuredRequest with confidence 0
    and the notes attached. If True, the notes may still contain soft
    warnings the parser should propagate.
    """
    notes: list[str] = []

    if not text or not text.strip():
        notes.append("empty input")
        return False, notes

    if len(text) > MAX_INPUT_LENGTH:
        notes.append(
            f"input too long ({len(text)} chars, max {MAX_INPUT_LENGTH}); rejected"
        )
        return False, notes

    if _CONTROL_CHARS_PATTERN.search(text):
        notes.append("control characters in input; rejected")
        return False, notes

    return True, notes


def _flag_suspicious_content(text: str) -> list[str]:
    """Return notes for soft prompt-injection signals.

    Does not reject — the parser still tries to extract legitimate
    intent from the rest of the text. The notes propagate to the
    StructuredRequest so the agent layer can see them and the operator
    can audit usage.
    """
    flagged: list[str] = []
    for pattern, description in _SUSPICIOUS_PATTERNS:
        if pattern.search(text):
            flagged.append(description)
    return flagged


# ---------------------------------------------------------------------------
# Extraction helpers (unchanged from original parser)
# ---------------------------------------------------------------------------

def _normalise_pct(raw: str) -> float:
    value = float(raw)
    if value > 1.0:
        value = value / 100.0
    return min(value, 1.0)


def _extract_objective(text: str) -> tuple[Objective | None, list[str]]:
    notes: list[str] = []
    for pattern, obj in OBJECTIVE_PATTERNS:
        if pattern.search(text):
            return obj, notes
    notes.append("no objective phrase detected")
    return None, notes


def _extract_max_weight(text: str) -> float | None:
    for pattern in CAP_PATTERNS:
        m = pattern.search(text)
        if m:
            return _normalise_pct(m.group(1))
    return None


def _extract_min_holdings(text: str) -> int | None:
    for pattern in MIN_HOLDINGS_PATTERNS:
        m = pattern.search(text)
        if m:
            return int(m.group(1))
    return None


def _extract_tickers(text: str) -> tuple[str, ...]:
    matches = TICKER_PATTERN.findall(text)
    seen: list[str] = []
    for t in matches:
        if t in TICKER_BLOCKLIST:
            continue
        if t not in seen:
            seen.append(t)
    return tuple(seen)


def _resolve_sector_to_tickers(phrase: str) -> tuple[str, ...]:
    lowered = phrase.strip().lower()
    sorted_keys = sorted(SECTORS.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key in lowered:
            return SECTORS[key]
    return ()


def _extract_exclusions(text: str) -> tuple[tuple[str, ...], list[str]]:
    notes: list[str] = []
    excluded: list[str] = []

    for match in EXCLUSION_TRIGGERS.finditer(text):
        phrase = match.group(1).strip()

        sector_tickers = _resolve_sector_to_tickers(phrase)
        if sector_tickers:
            for t in sector_tickers:
                if t not in excluded:
                    excluded.append(t)
            notes.append(f"resolved '{phrase}' as sector → {list(sector_tickers)}")
            continue

        ticker_tokens = _extract_tickers(phrase)
        if ticker_tokens:
            for t in ticker_tokens:
                if t not in excluded:
                    excluded.append(t)
        else:
            notes.append(f"could not interpret exclusion phrase: '{phrase}'")

    return tuple(excluded), notes


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_request(text: str) -> StructuredRequest:
    """Parse a free-text portfolio request into structured fields.

    Inputs that fail validation (empty / too long / control chars) are
    rejected with confidence 0 and a descriptive note. Inputs that pass
    validation but look like prompt-injection attempts have a low
    confidence and notes flagging the suspicious content.
    """
    is_safe, validation_notes = _validate_input(text)
    if not is_safe:
        return StructuredRequest(
            confidence=0.0,
            notes=tuple(validation_notes),
        )

    notes: list[str] = list(validation_notes)

    # Soft prompt-injection signals: lower confidence and propagate notes,
    # but still attempt to extract legitimate intent. The agent layer can
    # decide what to do with the flag.
    suspicious_notes = _flag_suspicious_content(text)
    notes.extend(suspicious_notes)

    objective, obj_notes = _extract_objective(text)
    notes.extend(obj_notes)

    max_weight = _extract_max_weight(text)
    min_holdings = _extract_min_holdings(text)

    excluded, exc_notes = _extract_exclusions(text)
    notes.extend(exc_notes)

    all_tickers = _extract_tickers(text)
    excluded_set = set(excluded)
    tickers = tuple(t for t in all_tickers if t not in excluded_set)

    extracted = sum(
        [
            objective is not None,
            max_weight is not None,
            min_holdings is not None,
            bool(tickers) or bool(excluded),
        ]
    )
    confidence = max(0.0, extracted / 4.0)

    # Halve confidence if suspicious content was flagged. Still non-zero
    # because the legitimate part of the request may be useful.
    if suspicious_notes:
        confidence = confidence / 2.0

    return StructuredRequest(
        objective=objective,
        tickers=tickers,
        max_weight=max_weight,
        min_holdings=min_holdings,
        excluded_tickers=excluded,
        confidence=round(confidence, 2),
        notes=tuple(notes),
    )
