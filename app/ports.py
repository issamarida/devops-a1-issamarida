"""Interfaces shared between domains. Neither domain owns this file.

The alerts domain only knows about these interfaces. Any class that has
the right method fits the interface without importing this file.
"""

from typing import Protocol


class PriceUnavailable(Exception):
    """Raised when we can't get a price for a ticker."""


class PriceSource(Protocol):
    def get_price(self, ticker: str) -> float: ...


class WatchlistReader(Protocol):
    def is_watched(self, ticker: str) -> bool: ...
