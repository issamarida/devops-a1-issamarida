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
    owner_id: int = 0


class WatchlistLimitReached(ValueError):
    pass


class WatchlistRepository:
    def __init__(self, db_path, owner_id=0, max_items=30):
        self.db_path = db_path
        self.owner_id = owner_id
        self.max_items = max_items

    def add(self, ticker, name, notes, added_at) -> WatchlistItem:
        """Raises sqlite3.IntegrityError if the ticker is already there (UNIQUE column)."""
        with closing(get_connection(self.db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute(
                "SELECT COUNT(*) FROM watchlist_items WHERE owner_id = ?",
                (self.owner_id,),
            ).fetchone()[0]
            if count >= self.max_items:
                raise WatchlistLimitReached(
                    f"Your watchlist is limited to {self.max_items} assets. Remove an asset first."
                )
            cursor = conn.execute(
                "INSERT INTO watchlist_items (ticker, name, notes, added_at, owner_id) VALUES (?, ?, ?, ?, ?)",
                (ticker, name, notes, added_at, self.owner_id),
            )
            conn.commit()
        return WatchlistItem(
            cursor.lastrowid, ticker, name, notes, added_at, self.owner_id
        )

    def get_by_ticker(self, ticker) -> WatchlistItem | None:
        with closing(get_connection(self.db_path)) as conn:
            row = conn.execute(
                "SELECT * FROM watchlist_items WHERE ticker = ? AND owner_id = ?",
                (ticker, self.owner_id),
            ).fetchone()
        if row is None:
            return None
        return WatchlistItem(**row)

    def list_all(self) -> list[WatchlistItem]:
        with closing(get_connection(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT * FROM watchlist_items WHERE owner_id = ? ORDER BY ticker",
                (self.owner_id,),
            ).fetchall()
        return [WatchlistItem(**row) for row in rows]

    def delete(self, ticker) -> bool:
        """Returns True if a row was deleted."""
        with closing(get_connection(self.db_path)) as conn:
            cursor = conn.execute(
                "DELETE FROM watchlist_items WHERE ticker = ? AND owner_id = ?",
                (ticker, self.owner_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def exists(self, ticker) -> bool:
        return self.get_by_ticker(ticker) is not None


def most_watched_tickers(db_path) -> list[str]:
    """Every ticker an account watches, most watched first. Owner 0 is legacy data nobody sees."""
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            """SELECT ticker FROM watchlist_items WHERE owner_id != 0
            GROUP BY ticker ORDER BY COUNT(*) DESC, ticker"""
        ).fetchall()
    return [row["ticker"] for row in rows]


def tickers_by_owner(db_path) -> dict[str, list[str]]:
    """Each account's tickers, for the snapshot the alerts service asks for.

    The keys are account IDs as text because JSON object keys are always text.
    """
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            "SELECT owner_id, ticker FROM watchlist_items WHERE owner_id != 0 ORDER BY owner_id, ticker"
        ).fetchall()
    owners = {}
    for row in rows:
        owners.setdefault(str(row["owner_id"]), []).append(row["ticker"])
    return owners
