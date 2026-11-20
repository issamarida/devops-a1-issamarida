"""What the alerts domain needs from the watchlist service, as interfaces.

The alerts domain only knows about these interfaces. RemoteWatchlist in
app/alerts/watchlist_client.py fits both of them over HTTP, and the tests use
small fakes. Any class that has the right method fits without importing this file.
"""

from typing import Protocol


class PriceUnavailable(Exception):
    """Raised when we can't get a price for a ticker."""


class WatchlistUnavailable(Exception):
    """Raised when we can't find out what is on the watchlist."""


class PriceSource(Protocol):
    def get_price(self, ticker: str) -> float: ...


class WatchlistReader(Protocol):
    def is_watched(self, ticker: str) -> bool: ...
