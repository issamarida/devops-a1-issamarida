# Architecture Decision Records

## 1. Backend language and framework

Date: 2026-09-28

Status: Decided (revised 2026-10-03 and 2026-10-04)

Context: I have one week to build this and then explain it at a closed-book check with no notes. It has to run as one process with no outside database, yet still show live prices and check alerts in the background.

Decision: Python 3 with Flask, the built-in sqlite3 module with plain SQL, Jinja templates and waitress as the server. Background work runs as daemon threads that only app.py starts: one alert poller and one server-side WebSocket to Finnhub, which the pages read through a session-protected JSON endpoint polled every second.

Alternatives considered: FastAPI was rejected because nothing here needs async, Django because it is far too big for two small domains and SQLAlchemy so every query stays SQL I can read out. Server-sent events were rejected because each open stream would hold one of waitress's few worker threads. Letting the browser connect to Finnhub directly was rejected because the API key would end up in the page.

Consequences: There is less framework to explain, but I write the SQL and form handling by hand so the tests have to catch more mistakes. The threads add concurrency, which is why every repository call opens its own short-lived connection.

## 2. Keeping the watchlist and alerts domains separate

Date: 2026-09-29

Status: Decided (revised 2026-10-03). This entry was first committed on 2026-09-30 and its displayed date was later edited in commit ab1ef81.

Context: The brief wants two domains that could each become their own service later, with a seam I can point to. Alerts needs to know whether a ticker is watched and what it costs, which could easily tie it to the watchlist code.

Decision: Alerts depends only on the WatchlistReader and PriceSource interfaces in app/ports.py, and create_app is the only module that plugs in the real classes, scoped to the signed-in account. A test parses every import under app/ and fails if any module crosses these boundaries.

Alternatives considered: Importing WatchlistService straight into alerts, or a foreign key from alert_rules to watchlist_items. Both were rejected because splitting alerts into its own service would then mean rewriting it.

Consequences: Alerts can move to its own service by swapping WatchlistReader for an HTTP client. The cost is no joins across domains, and rules for a removed ticker stay in the table as dormant rows.

## 3. Trigger history as its own snapshot table

Date: 2026-09-30

Status: Decided (revised 2026-10-03)

Context: A user needs to see which alerts fired, at what price and when, even after deleting the rule. The schema also has to keep each domain's data apart and keep each investor's data private.

Decision: Watchlist owns watchlist_items and alerts owns alert_rules plus alert_events, each with an owner_id and the ticker stored as plain text. When a rule fires, alert_events copies its ticker, condition, threshold and the observed price, and rule_id becomes NULL if the rule is deleted later.

Alternatives considered: Storing the last fire time and price on the alert_rules row. Rejected because it only keeps one firing and loses it when the rule is deleted. A foreign key from alert_rules.ticker to watchlist_items was already rejected in ADR-2.

Consequences: History survives rule deletion and can be listed without a join, at the cost of some duplicated values. A random rule_token on each rule stops a stale evaluation from firing a new rule that reused a deleted rule's ID.

## 4. Testing approach

Date: 2026-10-01

Status: Decided (revised 2026-10-03 and 2026-10-04)

Context: The brief asks for 70% coverage on core logic, not on routing, and I only have a week. The riskiest code is how a rule fires, what happens when a price is missing and what happens when two checks run at once.

Decision: Coverage measures the app package except the Flask route files and create_app, and the tests use fake PriceSource and WatchlistReader classes so they run offline. On top of the unit tests, one end-to-end test drives a watchlist entry to a fired alert and a contract test starts python app.py and waits for /health.

Alternatives considered: Measuring every file including the routes. Rejected because route handlers are thin glue, so the number would reward tests that check nothing important.

Consequences: 240 tests reach 100% coverage of 868 statements in about 12 seconds without touching the network. The fakes would not notice if Finnhub changed its response format, so I checked the real API by hand.

## 5. Scope boundaries and account access

Date: 2026-10-01

Status: Decided (revised 2026-10-03, replacing my first choice of no login)

Context: The intended users are retail investors with separate private workspaces on one small instance. The brief makes authentication a choice I have to justify, and every extra feature is code I must secure and explain.

Decision: I added username and password accounts as supporting access control around the two domains. I deliberately did not build email or push notifications, password recovery or trading.

Alternatives considered: My first version had one shared workspace with no login, which I rejected once it was clear investors could read and change each other's notes. An email or push delivery service was rejected because it adds an outside runtime dependency beyond the price API.

Consequences: Fired alerts are only visible inside the app, and a forgotten password cannot be recovered. HTTPS and network access controls are still needed before any public use.
