"""Tests for optimiser.parser.

Covers every regex path, common phrasings, edge cases, and a couple of
real-world-ish queries to make sure the parser holds together end-to-end.
"""

from __future__ import annotations

import pytest

from optimiser.data import SECTORS
from optimiser.fitness import Objective
from optimiser.parser import (
    StructuredRequest,
    parse_request,
)


# ---------------------------------------------------------------------
# Objective detection
# ---------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected", [
    ("max sharpe", Objective.MAX_SHARPE),
    ("maximise sharpe", Objective.MAX_SHARPE),
    ("maximize sharpe", Objective.MAX_SHARPE),
    ("highest sharpe", Objective.MAX_SHARPE),
    ("best sharpe", Objective.MAX_SHARPE),
    ("sharpe", Objective.MAX_SHARPE),
    ("min variance", Objective.MIN_VARIANCE),
    ("minimise variance", Objective.MIN_VARIANCE),
    ("min vol", Objective.MIN_VARIANCE),
    ("lowest volatility", Objective.MIN_VARIANCE),
    ("defensive", Objective.MIN_VARIANCE),
    ("max return", Objective.MAX_RETURN),
    ("maximise return", Objective.MAX_RETURN),
    ("highest return", Objective.MAX_RETURN),
    ("aggressive", Objective.MAX_RETURN),
])
def test_objective_phrases(phrase, expected):
    result = parse_request(phrase)
    assert result.objective is expected


def test_no_objective_yields_none_and_note():
    result = parse_request("just a portfolio of LLOY.L")
    assert result.objective is None
    assert any("no objective" in n for n in result.notes)


# ---------------------------------------------------------------------
# Max-weight cap detection
# ---------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected", [
    ("max 10%", 0.10),
    ("maximum 25%", 0.25),
    ("cap 5%", 0.05),
    ("cap at 15%", 0.15),
    ("capped at 8%", 0.08),
    ("no more than 12%", 0.12),
    ("10% per name", 0.10),
    ("20% per stock", 0.20),
    ("max weight of 30%", 0.30),
])
def test_max_weight_phrases(phrase, expected):
    result = parse_request(f"max sharpe, {phrase}")
    assert result.max_weight == pytest.approx(expected)


def test_max_weight_already_decimal_not_doubled():
    result = parse_request("max sharpe, max 10%")
    assert result.max_weight == 0.10


def test_max_weight_above_100_pct_clamps():
    result = parse_request("max sharpe, max 200%")
    assert result.max_weight == 1.0


# ---------------------------------------------------------------------
# Min-holdings detection
# ---------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected", [
    ("at least 5 holdings", 5),
    ("at least 8 names", 8),
    ("at least 3 positions", 3),
    ("minimum 6 stocks", 6),
    ("min 4 holdings", 4),
    ("10+ holdings", 10),
])
def test_min_holdings_phrases(phrase, expected):
    result = parse_request(f"max sharpe, {phrase}")
    assert result.min_holdings == expected


# ---------------------------------------------------------------------
# Ticker extraction
# ---------------------------------------------------------------------

def test_picks_up_uk_listings_with_dot_l():
    result = parse_request("max sharpe with LLOY.L BARC.L AZN.L")
    assert set(result.tickers) == {"LLOY.L", "BARC.L", "AZN.L"}


def test_picks_up_us_style_tickers():
    result = parse_request("max sharpe portfolio of AAPL MSFT NVDA")
    assert set(result.tickers) == {"AAPL", "MSFT", "NVDA"}


def test_blocklist_excludes_common_acronyms():
    result = parse_request("max sharpe on FTSE 100, in the UK")
    assert "FTSE" not in result.tickers
    assert "UK" not in result.tickers


def test_universe_minus_exclusions():
    result = parse_request(
        "max sharpe with LLOY.L BARC.L AZN.L, exclude BARC.L"
    )
    assert set(result.tickers) == {"LLOY.L", "AZN.L"}
    assert set(result.excluded_tickers) == {"BARC.L"}


# ---------------------------------------------------------------------
# Exclusion phrases — sectors and tickers
# ---------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected_excluded", [
    ("exclude banks", SECTORS["banks"]),
    ("no banks", SECTORS["banks"]),
    ("without banks", SECTORS["banks"]),
    ("exclude pharma", SECTORS["pharma"]),
    ("no oil", SECTORS["oil"]),
    ("drop energy", SECTORS["energy"]),
    ("skip miners", SECTORS["miners"]),
])
def test_sector_exclusions(phrase, expected_excluded):
    result = parse_request(f"max sharpe, {phrase}")
    assert set(result.excluded_tickers) == set(expected_excluded)


def test_ticker_exclusion_single():
    result = parse_request("max sharpe, exclude LLOY.L")
    assert result.excluded_tickers == ("LLOY.L",)


def test_ticker_exclusion_with_and():
    result = parse_request(
        "max sharpe, exclude SHEL.L and BP.L, cap 25%"
    )
    assert set(result.excluded_tickers) == {"SHEL.L", "BP.L"}


def test_multiple_separate_exclusion_clauses():
    result = parse_request(
        "max sharpe, exclude banks; no oil"
    )
    expected = set(SECTORS["banks"]) | set(SECTORS["oil"])
    assert set(result.excluded_tickers) == expected


def test_exclude_unknown_sector_records_note():
    result = parse_request("max sharpe, exclude crypto")
    assert result.excluded_tickers == ()
    assert any("could not interpret" in n for n in result.notes)


# ---------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------

def test_confidence_high_when_all_fields_extracted():
    result = parse_request(
        "max sharpe, exclude banks, cap 10%, at least 5 holdings"
    )
    assert result.confidence == 1.0


def test_confidence_zero_for_empty_input():
    result = parse_request("")
    assert result.confidence == 0.0


def test_confidence_zero_for_whitespace_only():
    result = parse_request("   \n\t  ")
    assert result.confidence == 0.0


def test_confidence_partial_when_only_some_fields_present():
    result = parse_request("max sharpe")
    assert result.confidence == 0.25


# ---------------------------------------------------------------------
# Real-world phrasing — integration-style tests
# ---------------------------------------------------------------------

def test_realistic_query_1():
    r = parse_request("max sharpe, exclude banks, cap 10% per name")
    assert r.objective is Objective.MAX_SHARPE
    assert r.max_weight == 0.10
    assert set(r.excluded_tickers) == set(SECTORS["banks"])


def test_realistic_query_2():
    r = parse_request("defensive FTSE portfolio without pharma, at least 8 names")
    assert r.objective is Objective.MIN_VARIANCE
    assert r.min_holdings == 8
    assert set(r.excluded_tickers) == set(SECTORS["pharma"])


def test_realistic_query_3():
    r = parse_request("aggressive bet on LLOY.L BARC.L HSBA.L, max weight of 40%")
    assert r.objective is Objective.MAX_RETURN
    assert r.max_weight == 0.40
    assert set(r.tickers) == {"LLOY.L", "BARC.L", "HSBA.L"}


# ---------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------

def test_returns_structured_request():
    r = parse_request("max sharpe")
    assert isinstance(r, StructuredRequest)
    assert hasattr(r, "objective")
    assert hasattr(r, "tickers")
    assert hasattr(r, "max_weight")
    assert hasattr(r, "min_holdings")
    assert hasattr(r, "excluded_tickers")
    assert hasattr(r, "confidence")
    assert hasattr(r, "notes")
