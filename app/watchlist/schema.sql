-- Watchlist domain. Only app/watchlist/ reads or writes this table.
CREATE TABLE IF NOT EXISTS watchlist_items (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 0,
    ticker   TEXT    NOT NULL,
    name     TEXT    NOT NULL,
    notes    TEXT    NOT NULL DEFAULT '',
    added_at TEXT    NOT NULL,
    UNIQUE (owner_id, ticker)
);
