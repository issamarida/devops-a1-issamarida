"""All SQL for watchlist_items. Each method opens a connection and closes it when done."""

from contextlib import closing
from dataclasses import dataclass

from app.db import get_connection


@dataclass
class WatchlistItem:
    id: int
    ticker: str
    name: str
    notes: str
    added_at: str


class WatchlistRepository:
    def __init__(self, db_path):
        self.db_path = db_path

    def add(self, ticker, name, notes, added_at) -> WatchlistItem:
        """Raises sqlite3.IntegrityError if the ticker is already there (UNIQUE column)."""
        with closing(get_connection(self.db_path)) as conn:
            cursor = conn.execute(
                "INSERT INTO watchlist_items (ticker, name, notes, added_at) VALUES (?, ?, ?, ?)",
                (ticker, name, notes, added_at),
            )
            conn.commit()
        return WatchlistItem(cursor.lastrowid, ticker, name, notes, added_at)

    def get_by_ticker(self, ticker) -> WatchlistItem | None:
        with closing(get_connection(self.db_path)) as conn:
            row = conn.execute(
                "SELECT * FROM watchlist_items WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None:
            return None
        return WatchlistItem(**row)

    def list_all(self) -> list[WatchlistItem]:
        with closing(get_connection(self.db_path)) as conn:
            rows = conn.execute("SELECT * FROM watchlist_items ORDER BY ticker").fetchall()
        return [WatchlistItem(**row) for row in rows]

    def delete(self, ticker) -> bool:
        """Returns True if a row was deleted."""
        with closing(get_connection(self.db_path)) as conn:
            cursor = conn.execute("DELETE FROM watchlist_items WHERE ticker = ?", (ticker,))
            conn.commit()
        return cursor.rowcount > 0

    def exists(self, ticker) -> bool:
        return self.get_by_ticker(ticker) is not None
