# Architecture Decision Records

## 1. Backend language and framework

Date: 2026-09-28

Status: Decided

Context: I have one week to build this and then explain it at a closed-book check with no notes. It has to run as one process with no outside database.

Decision: Python 3 with Flask. I use the built-in sqlite3 module with no ORM. Pages are Jinja2 templates and waitress serves the app.

Alternatives considered: FastAPI was rejected because nothing here needs async. Django was rejected because it's far too big for two small domains. SQLAlchemy was rejected so every query stays plain SQL that I can read out and explain.

Consequences: There's less framework to explain at the check. I write the SQL and form handling by hand so the tests have to catch more mistakes.

## 2. Keeping the watchlist and alerts domains separate

Date: 2026-09-30

Status: Decided

Context: The brief wants two domains that could each become their own service later, with a seam I can point to. Alerts needs to know whether a ticker is watched and what it costs, which could easily tie it to the watchlist code.

Decision: Alerts only talks to two small interfaces in app/ports.py, WatchlistReader and PriceSource, and create_app is the only place that plugs the real classes in. alert_rules stores the ticker as plain text with no foreign key to watchlist_items.

Alternatives considered: Importing WatchlistService straight into alerts, or a foreign key from alert_rules to watchlist_items. Both were rejected because splitting alerts into its own service would then mean rewriting it.

Consequences: Alerts can move to its own service by swapping WatchlistReader for an HTTP client. The cost is no joins across domains, and rules for a removed ticker stay in the table as dormant rows.
