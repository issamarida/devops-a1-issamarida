"""Watchlist business rules: ticker normalization, validation, duplicates."""

import re
import sqlite3
from datetime import datetime, timezone

from pricewatch.watchlist.repository import WatchlistItem, WatchlistRepository

TICKER_PATTERN = re.compile(r"^[A-Z0-9.]{1,10}$")


class InvalidWatchlistItemError(ValueError):
    """Raised when a ticker or name fails validation."""


class DuplicateTickerError(Exception):
    """Raised when adding a ticker that is already on the watchlist."""


def normalize_ticker(ticker: str) -> str:
    return (ticker or "").strip().upper()


class WatchlistService:
    def __init__(self, repository: WatchlistRepository):
        self._repository = repository

    def add_item(self, ticker: str, name: str, notes: str = "") -> WatchlistItem:
        ticker = normalize_ticker(ticker)
        if not TICKER_PATTERN.match(ticker):
            raise InvalidWatchlistItemError(
                "Ticker must be 1-10 characters: letters, digits or dots."
            )
        name = (name or "").strip()
        if not name:
            raise InvalidWatchlistItemError("Name must not be blank.")
        notes = (notes or "").strip()

        if self._repository.exists(ticker):
            raise DuplicateTickerError(f"{ticker} is already on the watchlist.")
        added_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            return self._repository.add(ticker, name, notes, added_at)
        except sqlite3.IntegrityError as exc:
            # Another request inserted the same ticker after our exists() check.
            raise DuplicateTickerError(f"{ticker} is already on the watchlist.") from exc

    def list_items(self) -> list[WatchlistItem]:
        return self._repository.list_all()

    def remove_item(self, ticker: str) -> bool:
        """Remove ticker from the watchlist. Returns False if it was not there."""
        return self._repository.delete(normalize_ticker(ticker))

    def is_watched(self, ticker: str) -> bool:
        return self._repository.exists(normalize_ticker(ticker))
