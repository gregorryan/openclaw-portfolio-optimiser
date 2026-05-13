"""Price data and returns for the portfolio optimiser.

This module wraps yfinance to fetch daily-close prices and converts them
into log or simple returns. The GA consumes the returns matrix produced
here; nothing else in the codebase should call yfinance directly.

Design choices:
- Adjusted close: accounts for dividends and splits, the correct series
  for return calculations.
- Log returns by default: additive over time, the textbook input for
  portfolio variance and Sharpe-style objectives.
- Strict on missing data: rather than silently filling, we raise a
  descriptive error so the caller can decide what to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yfinance as yf


# A small UK-equities universe used in tests and for the default
# demo if the user does not specify their own. FTSE 100 constituents
# spanning banks, pharma, energy, consumer staples, and miners.
DEFAULT_UNIVERSE_FTSE: tuple[str, ...] = (
    "LLOY.L",   # Lloyds Banking Group
    "BARC.L",   # Barclays
    "HSBA.L",   # HSBC
    "AZN.L",    # AstraZeneca
    "GSK.L",    # GSK
    "ULVR.L",   # Unilever
    "DGE.L",    # Diageo
    "SHEL.L",   # Shell
    "BP.L",     # BP
    "RIO.L",    # Rio Tinto
)

DEFAULT_LOOKBACK_YEARS: int = 5


class DataError(Exception):
    """Raised when price data cannot be obtained for one or more tickers."""


@dataclass(frozen=True)
class PriceData:
    """Aligned price and return series for a universe of tickers."""

    prices: pd.DataFrame   # rows = trading days, cols = tickers, values = adj close
    returns: pd.DataFrame  # rows = trading days, cols = tickers, values = period returns
    method: str            # "log" or "simple"


def _default_date_range(years: int) -> tuple[date, date]:
    """Inclusive [start, end] date range ending today, spanning `years` years."""
    end = date.today()
    start = end - timedelta(days=365 * years)
    return start, end


def fetch_prices(
    tickers: list[str] | tuple[str, ...],
    start: str | date | None = None,
    end: str | date | None = None,
) -> pd.DataFrame:
    """Fetch adjusted-close daily prices for a list of tickers.

    Args:
        tickers: ticker symbols, e.g. ["AAPL", "MSFT"] or ["LLOY.L", "BARC.L"].
        start: ISO date string or date object; defaults to 5 years ago.
        end: ISO date string or date object; defaults to today.

    Returns:
        DataFrame with one column per ticker and a daily DatetimeIndex.
        Rows where any ticker is missing data are dropped.

    Raises:
        DataError: if any ticker yields no usable data.
    """
    if not tickers:
        raise DataError("tickers list is empty")

    if start is None or end is None:
        default_start, default_end = _default_date_range(DEFAULT_LOOKBACK_YEARS)
        start = start or default_start
        end = end or default_end

    # auto_adjust=True returns adjusted prices in the 'Close' column.
    raw = yf.download(
        tickers=list(tickers),
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="ticker" if len(tickers) > 1 else None,
        threads=True,
    )

    if raw is None or raw.empty:
        raise DataError(f"yfinance returned no data for {list(tickers)} between {start} and {end}")

    # yfinance returns different shapes depending on ticker count.
    # Normalise to a flat DataFrame: rows=date, cols=ticker, values=adj close.
    if len(tickers) == 1:
        prices = raw[["Close"]].rename(columns={"Close": tickers[0]})
    else:
        # MultiIndex columns: (ticker, field). Pull the Close field per ticker.
        prices = pd.DataFrame({t: raw[t]["Close"] for t in tickers if t in raw.columns.get_level_values(0)})

    prices = prices.dropna(how="any")

    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        raise DataError(f"no data for ticker(s): {', '.join(missing)}")

    if prices.empty:
        raise DataError("price frame is empty after aligning dates")

    return prices


def compute_returns(prices: pd.DataFrame, method: str = "log") -> pd.DataFrame:
    """Convert a price DataFrame into a returns DataFrame.

    Args:
        prices: output of `fetch_prices`.
        method: "log" (default, additive over time) or "simple".

    Returns:
        DataFrame of period returns, one row shorter than the input prices.
    """
    if method not in {"log", "simple"}:
        raise ValueError(f"unknown method: {method!r}; expected 'log' or 'simple'")

    if method == "log":
        returns = np.log(prices / prices.shift(1))
    else:
        returns = prices.pct_change()

    return returns.dropna(how="any")


def load(
    tickers: list[str] | tuple[str, ...] | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
    method: str = "log",
) -> PriceData:
    """Convenience: fetch prices and compute returns in one call.

    Defaults to the FTSE universe over a 5-year window with log returns.
    This is the function the GA skill will call in production.
    """
    if tickers is None:
        tickers = DEFAULT_UNIVERSE_FTSE

    prices = fetch_prices(tickers, start=start, end=end)
    returns = compute_returns(prices, method=method)
    return PriceData(prices=prices, returns=returns, method=method)
