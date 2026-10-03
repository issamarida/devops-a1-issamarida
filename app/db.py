"""Short SQLite connections and automatic, additive startup upgrades."""

import sqlite3
from contextlib import closing
from pathlib import Path


def get_connection(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db(db_path, schema_paths) -> None:
    """Create tables and preserve old shared data in an unassigned owner 0.

    Owner 0 cannot log in. Existing data is never given to the first registrant.
    The upgrade is transactional and requires no manual migration command.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(get_connection(db_path)) as conn:
        for schema_path in schema_paths:
            conn.executescript(Path(schema_path).read_text())
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            columns = {
                r["name"] for r in conn.execute("PRAGMA table_info(watchlist_items)")
            }
            if "owner_id" not in columns:
                # Rebuild only this table to replace global ticker uniqueness.
                conn.execute(
                    "ALTER TABLE watchlist_items RENAME TO legacy_watchlist_items"
                )
                conn.execute("""CREATE TABLE watchlist_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL DEFAULT 0,
                    ticker TEXT NOT NULL, name TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '', added_at TEXT NOT NULL,
                    UNIQUE(owner_id, ticker))""")
                conn.execute("""INSERT INTO watchlist_items (id, ticker, name, notes, added_at)
                    SELECT id, ticker, name, notes, added_at FROM legacy_watchlist_items""")
                conn.execute("DROP TABLE legacy_watchlist_items")
            for table in ("alert_rules", "alert_events"):
                columns = {
                    r["name"] for r in conn.execute(f"PRAGMA table_info({table})")
                }
                if "owner_id" not in columns:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN owner_id INTEGER NOT NULL DEFAULT 0"
                    )
                if table == "alert_rules" and "rule_token" not in columns:
                    conn.execute(
                        "ALTER TABLE alert_rules ADD COLUMN rule_token TEXT NOT NULL DEFAULT ''"
                    )
                    conn.execute(
                        "UPDATE alert_rules SET rule_token = lower(hex(randomblob(16)))"
                    )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS rules_by_owner ON alert_rules(owner_id, is_active)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS events_by_owner ON alert_events(owner_id, triggered_at)"
            )
