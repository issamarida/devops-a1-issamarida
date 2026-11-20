"""The price interface the market code is written against.

Any class with the right method fits it without importing this file.
"""

from typing import Protocol


class PriceUnavailable(Exception):
    """Raised when we can't get a price for a ticker."""


class PriceSource(Protocol):
    def get_price(self, ticker: str) -> float: ...
