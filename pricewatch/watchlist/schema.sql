-- Watchlist domain: owned exclusively by pricewatch/watchlist/.
CREATE TABLE IF NOT EXISTS watchlist_items (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker   TEXT    NOT NULL UNIQUE,
    name     TEXT    NOT NULL,
    notes    TEXT    NOT NULL DEFAULT '',
    added_at TEXT    NOT NULL
);
