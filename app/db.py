"""SQLite helpers used by every domain.

We keep SQLite's default journal mode. WAL mode breaks on network drives.
"""

import sqlite3
from pathlib import Path


def get_connection(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # lets us read columns by name: row["ticker"]
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")  # wait up to 10s if the db is locked
    return conn


def init_db(db_path, schema_paths) -> None:
    """Create the data folder and run each schema.sql file.

    The schema files use CREATE TABLE IF NOT EXISTS so this is safe on every start.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    for schema_path in schema_paths:
        conn.executescript(Path(schema_path).read_text())
    conn.close()
