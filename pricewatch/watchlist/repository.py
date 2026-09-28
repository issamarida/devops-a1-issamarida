"""SQL access for watchlist_items. One short-lived connection per call."""

from contextlib import closing
from dataclasses import dataclass

from pricewatch.db import get_connection


@dataclass(frozen=True)
class WatchlistItem:
    id: int
    ticker: str
    name: str
    notes: str
    added_at: str


def _row_to_item(row) -> WatchlistItem:
    return WatchlistItem(
        id=row["id"],
        ticker=row["ticker"],
        name=row["name"],
        notes=row["notes"],
        added_at=row["added_at"],
    )


class WatchlistRepository:
    def __init__(self, db_path):
        self._db_path = db_path

    def add(self, ticker: str, name: str, notes: str, added_at: str) -> WatchlistItem:
        """Insert a row. Raises sqlite3.IntegrityError if ticker already exists."""
        with closing(get_connection(self._db_path)) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO watchlist_items (ticker, name, notes, added_at) VALUES (?, ?, ?, ?)",
                (ticker, name, notes, added_at),
            )
            return WatchlistItem(cursor.lastrowid, ticker, name, notes, added_at)

    def get_by_ticker(self, ticker: str) -> WatchlistItem | None:
        with closing(get_connection(self._db_path)) as conn:
            row = conn.execute(
                "SELECT id, ticker, name, notes, added_at FROM watchlist_items WHERE ticker = ?",
                (ticker,),
            ).fetchone()
        return _row_to_item(row) if row else None

    def list_all(self) -> list[WatchlistItem]:
        with closing(get_connection(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT id, ticker, name, notes, added_at FROM watchlist_items ORDER BY ticker"
            ).fetchall()
        return [_row_to_item(row) for row in rows]

    def delete(self, ticker: str) -> bool:
        """Delete by ticker. Returns True if a row was removed."""
        with closing(get_connection(self._db_path)) as conn, conn:
            cursor = conn.execute("DELETE FROM watchlist_items WHERE ticker = ?", (ticker,))
            return cursor.rowcount > 0

    def exists(self, ticker: str) -> bool:
        with closing(get_connection(self._db_path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM watchlist_items WHERE ticker = ?", (ticker,)
            ).fetchone()
        return row is not None
