"""Tests for optimiser.data.

These tests mock yfinance's network calls so they:
- Run in milliseconds, not seconds
- Pass identically offline, on CI, or on a judge's machine
- Don't break when Yahoo Finance has an outage

We still test the *real* logic — return computation, error paths, dropna
behaviour, dataclass packaging — just against synthetic price series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from optimiser import data as data_mod
from optimiser.data import (
    DataError,
    PriceData,
    compute_returns,
    fetch_prices,
    load,
)


def _fake_yf_frame(tickers: list[str], n_days: int = 250) -> pd.DataFrame:
    """Build a multi-ticker yfinance-shaped DataFrame for monkeypatching.

    yfinance returns a MultiIndex column frame when given multiple tickers:
    columns are (ticker, field) where field includes 'Close', 'Open', etc.
    We only need 'Close' for our pipeline.
    """
    dates = pd.bdate_range(end="2026-05-12", periods=n_days)
    rng = np.random.default_rng(seed=42)

    # Random walks starting at £1.00, modest daily vol
    frames = {}
    for t in tickers:
        steps = rng.normal(loc=0.0005, scale=0.015, size=n_days)
        prices = 100.0 * np.exp(np.cumsum(steps))
        frames[t] = pd.DataFrame({"Close": prices}, index=dates)

    return pd.concat(frames, axis=1)  # MultiIndex columns: (ticker, 'Close')


# ---------------------------------------------------------------------
# fetch_prices
# ---------------------------------------------------------------------

def test_fetch_prices_returns_dataframe(monkeypatch):
    tickers = ["AAA.L", "BBB.L"]
    fake = _fake_yf_frame(tickers)
    monkeypatch.setattr(data_mod.yf, "download", lambda *args, **kwargs: fake)

    prices = fetch_prices(tickers)

    assert isinstance(prices, pd.DataFrame)
    assert list(prices.columns) == tickers
    assert len(prices) == 250
    assert not prices.isna().any().any()


def test_fetch_prices_empty_tickers_raises():
    with pytest.raises(DataError, match="empty"):
        fetch_prices([])


def test_fetch_prices_yfinance_returns_nothing(monkeypatch):
    empty = pd.DataFrame()
    monkeypatch.setattr(data_mod.yf, "download", lambda *args, **kwargs: empty)

    with pytest.raises(DataError, match="no data"):
        fetch_prices(["NOPE.L"])


# ---------------------------------------------------------------------
# compute_returns
# ---------------------------------------------------------------------

def test_compute_returns_log_default():
    prices = pd.DataFrame(
        {"X": [100.0, 110.0, 121.0]},
        index=pd.bdate_range(end="2026-05-12", periods=3),
    )
    returns = compute_returns(prices)

    # log(110/100) ≈ 0.0953, log(121/110) ≈ 0.0953 (same +10% steps)
    assert len(returns) == 2
    assert returns["X"].iloc[0] == pytest.approx(np.log(1.1), rel=1e-6)
    assert returns["X"].iloc[1] == pytest.approx(np.log(1.1), rel=1e-6)


def test_compute_returns_simple():
    prices = pd.DataFrame(
        {"X": [100.0, 110.0, 121.0]},
        index=pd.bdate_range(end="2026-05-12", periods=3),
    )
    returns = compute_returns(prices, method="simple")

    assert returns["X"].iloc[0] == pytest.approx(0.10)
    assert returns["X"].iloc[1] == pytest.approx(0.10)


def test_compute_returns_unknown_method_raises():
    prices = pd.DataFrame({"X": [100.0, 110.0]}, index=pd.bdate_range(end="2026-05-12", periods=2))
    with pytest.raises(ValueError, match="unknown method"):
        compute_returns(prices, method="cumulative")


# ---------------------------------------------------------------------
# load (end-to-end)
# ---------------------------------------------------------------------

def test_load_returns_pricedata_dataclass(monkeypatch):
    tickers = ["AAA.L", "BBB.L"]
    fake = _fake_yf_frame(tickers)
    monkeypatch.setattr(data_mod.yf, "download", lambda *args, **kwargs: fake)

    result = load(tickers=tickers)

    assert isinstance(result, PriceData)
    assert result.method == "log"
    assert len(result.returns) == len(result.prices) - 1
    assert list(result.prices.columns) == tickers
    assert list(result.returns.columns) == tickers
