"""SQLite helpers shared by every domain.

Journal mode is deliberately left at SQLite's default (no WAL): WAL relies
on shared memory and breaks on network-mounted volumes.
"""

import sqlite3
from pathlib import Path


def get_connection(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db(db_path, schema_paths) -> None:
    """Create the data directory if needed and apply each schema file.

    Schema files use CREATE TABLE IF NOT EXISTS, so this is safe to run on
    every startup and replaces any manual migration step.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        for schema_path in schema_paths:
            conn.executescript(Path(schema_path).read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
