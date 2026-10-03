# Architecture Decision Records

## 1. Backend language and framework

Date: 2026-09-28

Status: Decided

Context: I have one week to build this and then explain it at a closed-book check with no notes. It has to run as one process with no outside database.

Decision: Python 3 with Flask. I use the built-in sqlite3 module with no ORM. Pages are Jinja2 templates and waitress serves the app.

Alternatives considered: FastAPI was rejected because nothing here needs async. Django was rejected because it's far too big for two small domains. SQLAlchemy was rejected so every query stays plain SQL that I can read out and explain.

Consequences: There's less framework to explain at the check. I write the SQL and form handling by hand so the tests have to catch more mistakes.

Revision recorded on 2026-10-03: I kept Jinja and local CSS because the two form-based pages do not justify a JavaScript build system. I use one daemon thread for periodic checks because it fits the single-process contract; it starts only in app.py. The thread waits after each run, so slow API calls extend the checking interval.

Revision recorded on 2026-10-03, live prices: Users wanted prices that move while they watch, from the real market. I added one WebSocket connection from the server to Finnhub, run by two daemon threads that app.py starts, with websocket-client as the one new dependency. The pages poll a session-protected /api/quotes endpoint every two seconds, so the browser never sees the key. I rejected the official finnhub-python SDK because it only covers REST and puts the key in the URL. I rejected letting the browser connect to Finnhub directly because the key would be in the page. I rejected pushing to the browser with server-sent events because each open stream would hold one of waitress's few worker threads. The cost is up to two seconds of display delay and two more threads to explain.

## 2. Keeping the watchlist and alerts domains separate

Date: 2026-09-29

Status: Decided

Context: The brief wants two domains that could each become their own service later, with a seam I can point to. Alerts needs to know whether a ticker is watched and what it costs, which could easily tie it to the watchlist code.

Decision: Alerts only talks to two small interfaces in app/ports.py, WatchlistReader and PriceSource, and create_app is the only place that plugs the real classes in. alert_rules stores the ticker as plain text with no foreign key to watchlist_items.

Alternatives considered: Importing WatchlistService straight into alerts, or a foreign key from alert_rules to watchlist_items. Both were rejected because splitting alerts into its own service would then mean rewriting it.

Consequences: Alerts can move to its own service by swapping WatchlistReader for an HTTP client. The cost is no joins across domains, and rules for a removed ticker stay in the table as dormant rows.

Revision recorded on 2026-10-03: Each request now gets repositories scoped to the signed-in account. The WatchlistReader port stays unchanged because the supplied watchlist service already has the same owner scope. Access control is supporting infrastructure outside both business domains. Historical date clarification: ADR-2 entered Git on 2026-09-30 with that date; commit ab1ef81 later changed its displayed date to 2026-09-29. That discrepancy is retained here explicitly rather than presented as evidence of an earlier commit.

## 3. Trigger history as its own snapshot table

Date: 2026-09-30

Status: Decided

Context: A user needs to see which alerts fired, at what price and when, even after deleting the rule. The schema also has to keep each domain's data apart.

Decision: The schema has three tables: watchlist_items for the watchlist, and alert_rules plus alert_events for alerts. alert_events copies the ticker, condition, threshold and observed price when a rule fires, and its rule_id becomes NULL if that rule is deleted later.

Alternatives considered: Storing the last fire time and price on the alert_rules row. Rejected because it only keeps one firing and loses it when the rule is deleted. A foreign key from alert_rules.ticker to watchlist_items was already rejected in ADR-2.

Consequences: History survives rule deletion and can be listed without a join. Some values are duplicated between alert_rules and alert_events.

Revision recorded on 2026-10-03: The three business tables now include owner_id, and ticker uniqueness is per owner. Two supporting tables, accounts and rate_limits, provide access control without foreign keys into either domain. alert_rules also has a random rule_token so a stale evaluation cannot fire a replacement row with a reused ID. Startup preserves old shared rows under inaccessible owner 0; new accounts do not inherit them. These changes match the revised schema diagram.

## 4. Testing approach

Date: 2026-10-01

Status: Decided

Context: The brief asks for 70% coverage on core logic, not on routing, and I only have a week. The riskiest code is how a rule fires and what happens when a price is missing.

Decision: Coverage measures the app package but leaves out the Flask routes and create_app, and most tests target is_triggered, AlertService.evaluate_all, fire_rule and WatchlistService validation using fake PriceSource and WatchlistReader classes. Coverage is 100% with the command in the README.

Alternatives considered: Measuring every file including the routes. Rejected because route handlers are thin glue, so the number would reward tests that check nothing important.

Consequences: Route bugs are only caught by one end-to-end test and the contract test, not by unit tests. The fakes keep tests fast and offline, but they would not notice if Finnhub changed its response format.

Revision recorded on 2026-10-03: I added tests for private ownership, password hashing, CSRF, session expiry/revocation, SQLite throttling, schema upgrades and concurrent firing. Access-control code is included in coverage. The current README reports the new measured result. A real-browser check covers desktop and mobile layouts; it does not replace unit tests or imply real API compatibility.

## 5. Scope boundaries and account access

Date: 2026-10-01

Status: Decided

Context: The brief makes authentication a choice I have to justify. The app is built for one person tracking their own tickers.

Decision: No login and no users table. There is one shared watchlist and one set of alert rules.

Alternatives considered: Flask-Login with a users table and a user_id on every row. Rejected because it adds a dependency and a password store to secure and explain, with no benefit for a single user.

Consequences: Anyone who can reach the app can change its data, so Assignment 2 has to restrict network access or add auth before exposing it. Adding users later means a user_id column on all three tables.

Revision recorded on 2026-10-03, superseding the original no-login decision:

Context: The intended audience is retail investors using separate private workspaces on one small instance. A shared anonymous watchlist would expose their notes and allow them to change each other's rules.

Decision: I added username/password accounts as supporting access control and kept watchlist and alerts as the two business domains. I deliberately did not build trading, email/push notifications, password recovery or MFA for this local assignment.

Alternatives considered: Keeping a shared anonymous workspace was rejected because it does not provide private ownership. An external identity service or email delivery provider was rejected because it introduces external runtime/setup dependencies beyond the price API. A larger account-management framework was rejected to keep the code explainable.

Consequences: The app now needs password hashing, revocable expiring sessions, CSRF checks, rate limits and owner-scoped queries. One account has one active session, and a forgotten password cannot be recovered in this version; HTTPS and deployment access controls are still needed before any future public use.
