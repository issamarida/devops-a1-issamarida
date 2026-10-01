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

## 3. Trigger history as its own snapshot table

Date: 2026-09-30

Status: Decided

Context: A user needs to see which alerts fired, at what price and when, even after deleting the rule. The schema also has to keep each domain's data apart.

Decision: The schema has three tables: watchlist_items for the watchlist, and alert_rules plus alert_events for alerts. alert_events copies the ticker, condition, threshold and observed price when a rule fires, and its rule_id becomes NULL if that rule is deleted later.

Alternatives considered: Storing the last fire time and price on the alert_rules row. Rejected because it only keeps one firing and loses it when the rule is deleted. A foreign key from alert_rules.ticker to watchlist_items was already rejected in ADR-2.

Consequences: History survives rule deletion and can be listed without a join. Some values are duplicated between alert_rules and alert_events.

## 4. Testing approach

Date: 2026-10-01

Status: Decided

Context: The brief asks for 70% coverage on core logic, not on routing, and I only have a week. The riskiest code is how a rule fires and what happens when a price is missing.

Decision: Coverage measures the app package but leaves out the Flask routes and create_app, and most tests target is_triggered, AlertService.evaluate_all, fire_rule and WatchlistService validation using fake PriceSource and WatchlistReader classes. Coverage is 100% with the command in the README.

Alternatives considered: Measuring every file including the routes. Rejected because route handlers are thin glue, so the number would reward tests that check nothing important.

Consequences: Route bugs are only caught by one end-to-end test and the contract test, not by unit tests. The fakes keep tests fast and offline, but they would not notice if Finnhub changed its response format.
