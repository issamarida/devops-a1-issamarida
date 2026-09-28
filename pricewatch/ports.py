"""Neutral interfaces shared across domains, owned by neither of them.

The alerts domain depends only on these Protocols, never on the concrete
watchlist or market code. Any class with matching methods satisfies a
Protocol structurally; it does not need to import or subclass it.
"""

from typing import Protocol


class PriceUnavailable(Exception):
    """Raised when a current price cannot be obtained for a ticker."""


class PriceSource(Protocol):
    def get_price(self, ticker: str) -> float:
        """Return the latest price for ticker, or raise PriceUnavailable."""
        ...


class WatchlistReader(Protocol):
    def is_watched(self, ticker: str) -> bool:
        """Return True if ticker is currently on the watchlist."""
        ...
