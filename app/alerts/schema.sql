-- Alerts domain. Only app/alerts/ reads or writes these tables.
-- ticker is plain text with no foreign key to watchlist_items, so alerts can move to its own service.
CREATE TABLE IF NOT EXISTS alert_rules (
    id         INTEGER PRIMARY KEY,
    owner_id   INTEGER NOT NULL DEFAULT 0,
    rule_token TEXT NOT NULL,
    ticker     TEXT    NOT NULL,
    condition  TEXT    NOT NULL CHECK (condition IN ('above', 'below')),
    threshold  REAL    NOT NULL CHECK (threshold > 0),
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL
);

-- One row per fired rule. ticker, condition and threshold are copied from the rule
-- so the history still reads correctly after the rule is deleted.
CREATE TABLE IF NOT EXISTS alert_events (
    id             INTEGER PRIMARY KEY,
    owner_id       INTEGER NOT NULL DEFAULT 0,
    rule_id        INTEGER REFERENCES alert_rules(id) ON DELETE SET NULL,
    ticker         TEXT    NOT NULL,
    condition      TEXT    NOT NULL,
    threshold      REAL    NOT NULL,
    observed_price REAL    NOT NULL,
    triggered_at   TEXT    NOT NULL
);
