"""Watchlist rules: clean up the ticker, check the input, block duplicates."""

import re
import sqlite3
from datetime import datetime, timezone

from app.watchlist.repository import (
    WatchlistItem,
    WatchlistLimitReached,
    WatchlistRepository,
)

# 1 to 10 characters. Uppercase letters, digits or dots (like BRK.B).
TICKER_PATTERN = re.compile(r"^[A-Z0-9.]{1,10}$")


class InvalidWatchlistItemError(ValueError):
    pass


class DuplicateTickerError(Exception):
    pass


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


class WatchlistService:
    def __init__(self, repository: WatchlistRepository):
        self.repository = repository

    def add_item(self, ticker: str, name: str, notes: str = "") -> WatchlistItem:
        ticker = normalize_ticker(ticker)
        name = name.strip()
        notes = notes.strip()

        if not TICKER_PATTERN.fullmatch(ticker) or not any(c.isalnum() for c in ticker):
            raise InvalidWatchlistItemError(
                "Ticker must be 1-10 letters, digits or dots."
            )
        if name == "":
            raise InvalidWatchlistItemError("Name can't be blank.")

        if len(name) > 100 or len(notes) > 500:
            raise InvalidWatchlistItemError(
                "Use at most 100 characters for the name and 500 for notes."
            )

        added_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            return self.repository.add(ticker, name, notes, added_at)
        except WatchlistLimitReached as error:
            raise InvalidWatchlistItemError(str(error)) from None
        except sqlite3.IntegrityError:
            # The UNIQUE constraint on ticker rejected it
            raise DuplicateTickerError(f"{ticker} is already on the watchlist.")

    def list_items(self) -> list[WatchlistItem]:
        return self.repository.list_all()

    def remove_item(self, ticker: str) -> bool:
        return self.repository.delete(normalize_ticker(ticker))

    def is_watched(self, ticker: str) -> bool:
        return self.repository.exists(normalize_ticker(ticker))
