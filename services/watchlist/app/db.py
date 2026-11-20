"""Short SQLite connections, the tables at first boot and the health check."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def get_connection(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db(db_path, schema_paths) -> None:
    """Create this service's tables if they are not there yet."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(get_connection(db_path)) as conn:
        for schema_path in schema_paths:
            conn.executescript(Path(schema_path).read_text())
        conn.execute(
            """CREATE TABLE IF NOT EXISTS health_check (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                checked_at TEXT NOT NULL)"""
        )


def check_database(db_path) -> None:
    """Write one row and read it back. Raises sqlite3.Error if either fails."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(get_connection(db_path)) as conn, conn:
        # The table only ever holds the row with id 1.
        conn.execute(
            "INSERT OR REPLACE INTO health_check (id, checked_at) VALUES (1, ?)", (now,)
        )
        conn.execute("SELECT checked_at FROM health_check WHERE id = 1").fetchone()
