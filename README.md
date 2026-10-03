# Stock watchlist and price alerts

A small web app for retail investors who follow US stocks and want private watchlists and a record of price conditions being met. It monitors prices; it does not place trades or send email/push notifications.

There are **two business domains**: `app/watchlist` owns tracked assets and notes; `app/alerts` owns one-shot rules and trigger history. Authentication is supporting access control in `app/security.py`, not another business feature. Everything runs in **one Python process**: waitress, a daemon thread that checks alert rules, two daemon threads that hold one live connection to Finnhub, and one SQLite file.

## Run locally

Python 3.10 or newer; verified with Python 3.14.7. From a clone of this repository:

```sh
uv venv
source .venv/bin/activate.fish
uv pip install -r requirements.txt
python app.py
```

For bash/zsh use `source .venv/bin/activate` instead. Plain pip also works: `python -m venv .venv`, activate it, then `python -m pip install -r requirements.txt`.

Open http://localhost:8080. Create an account in the browser, then sign in. There are no default credentials and no interactive server setup. Tables and compatible schema upgrades run automatically at startup. `GET /health` is public and returns 200 only when all five tables can be read.

Every price comes from Finnhub. A free key from finnhub.io is enough. Set it in your shell before starting the app, for example `set -x PRICE_API_KEY your-key` in fish or `export PRICE_API_KEY=your-key` in bash. To try it, add AAPL to your watchlist, create an **above 1.00** rule, and select **Check rules now**. The real AAPL price is above 1, so it fires once. Repeat the check to confirm there is no second event.

## Live prices

While US markets are open, prices tick in the watchlist and the alert rules table, and the status pill in the top right reads **Live**.

1. At startup `app.py` opens one WebSocket connection from the server to `wss://ws.finnhub.io` and subscribes to every ticker any account watches, most watched first, up to `LIVE_SYMBOL_LIMIT`. New tickers are picked up within a few seconds; removed ones are unsubscribed.
2. Each trade Finnhub pushes is kept in memory as the latest price for that ticker.
3. Each page polls `GET /api/quotes` on this server every two seconds. The endpoint needs a signed-in session and only returns the account's own tickers. It returns the latest trade, or the REST quote when no trade has arrived in the last minute (markets closed, quiet ticker), plus the change since the previous close.
4. The alert poller uses the same prices, so a rule fires on a live trade within one `POLL_INTERVAL_SECONDS` interval.

The browser never talks to Finnhub and never receives the key. The Content Security Policy only allows the page's own inline script and requests back to this server. The REST adapter sends the key in a header; the WebSocket needs it in the URL, which is never logged, and a log filter masks the key in every log line as a second safeguard. A dropped connection is retried after 1, 2, 4 and up to 60 seconds. If no key is set, the app still starts and serves the watchlist and rules, prices show as a dash, the pill reads Offline and the log says which setting is missing. No price is ever made up.

The official finnhub-python SDK was considered. It only wraps the REST API and puts the key in the URL query string, so the app keeps its own small REST adapter and uses `websocket-client` for the stream.

## Audience and boundaries

The intended audience is independent retail investors checking a few US stocks on a desktop or phone. Each person has a private account; one person's assets never activate another person's rules. The initial use is a local course demonstration or a small controlled pilot. Assignment 1 does not deploy the app publicly.

Default resource bounds are 50 accounts, 30 tracked assets per account and 100 retained rules per account. These are storage/abuse limits, **not a throughput claim**. Live monitoring should stay within 30 distinct active tickers across the instance at the default quote budget. A shared cache helps overlapping watchlists. Extra quotes are skipped and retried on subsequent checks; this is not guaranteed real-time monitoring. A run waits for quotes, then waits the configured polling interval, so a slow API extends the time between checks.

No brokerage integration, trading, portfolio valuation, password recovery, MFA, account deletion or external notification service is included. Fired alerts appear in the trigger history when you revisit or refresh. Outside market hours the last REST quote is shown and no trades stream. A rule tests the observed price, not whether a crossing occurred between two samples.

## Configuration

All settings come from optional environment variables. No `.env` file or source edit is required.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8080` | Integer from 1 to 65535 |
| `DATA_DIR` | `./data` | SQLite path is `$DATA_DIR/app.db` |
| `PRICE_API_KEY` | unset | Finnhub key, used for the live stream and REST quotes |
| `POLL_INTERVAL_SECONDS` | `15` | Wait between alert checks; 0 disables automatic checks |
| `PRICE_CACHE_TTL_SECONDS` | `30` | Cache live quotes; 0 disables reuse |
| `QUOTE_REQUESTS_PER_MINUTE` | `30` | Shared rolling limit on outbound REST quote requests |
| `LIVE_SYMBOL_LIMIT` | `50` | Most tickers streamed at once; Finnhub's free plan allows 50 |
| `SECRET_KEY` | random at startup | Session signing secret; an explicit value needs at least 32 characters |
| `SESSION_COOKIE_SECURE` | `false` | `true` for HTTPS; `false` permits local HTTP |
| `SESSION_SECONDS` | `3600` | Absolute session lifetime, in seconds |
| `AUTH_ATTEMPTS` | `5` | Login attempts per username and registrations per IP per window |
| `AUTH_WINDOW_SECONDS` | `900` | Authentication rate-limit window |
| `MAX_ACCOUNTS` | `50` | Registration capacity |
| `MAX_WATCHLIST_ITEMS` | `30` | Per-account asset limit |
| `MAX_ALERT_RULES` | `100` | Per-account rule limit, including fired rules |

The login IP limit is five times `AUTH_ATTEMPTS`. Authenticated POSTs are limited to 60 per minute per account; manual evaluation is additionally limited to four per minute. Forms are limited to 16 KiB and 12 multipart fields. Names are limited to 100 characters and notes to 500. These small fixed HTTP/input bounds are defined in code; the operating limits above are configurable.

Invalid configuration stops startup with a message naming the setting. The API key never reaches the browser and is never logged. A random default signing key means server restarts require signing in again. Set a strong stable `SECRET_KEY` when session continuity is needed.

## Access control and safety

- Passwords are salted and hashed with Werkzeug's scrypt implementation. Passwords must contain 15–128 characters; password managers and passphrases work.
- A signed, HttpOnly, SameSite=Lax cookie contains the account ID and a random session token. SQLite stores only its SHA-256 digest and expiry. Signing out revokes it; signing in again replaces the previous session, so one account has one active session.
- Every POST, including registration, login and logout, requires a session-bound CSRF token. Successful login clears the old session and token.
- SQLite rate limits reserve attempts atomically and survive process restarts. HTTP 429 includes `Retry-After`. Unknown usernames and incorrect passwords use the same login error and password-hash check.
- Repository queries always use the authenticated account ID supplied by the composition root. Submitted account IDs are ignored. Domain tables have no foreign keys to the account table and no cross-domain joins.
- Templates escape user content. A nonce-based Content Security Policy allows only the page's own script, limits fetch requests to this server and blocks framing. Responses prevent MIME sniffing and private-page caching. No third-party frontend assets are loaded.

For Assignment 2, HTTPS, `SESSION_COOKIE_SECURE=true`, a strong signing secret, a persistent data volume and network access restrictions are prerequisites. Proxy headers are deliberately not trusted; behind a proxy the IP limiter may group clients together. Configure trusted proxy handling only once the actual deployment topology is known. Application rate limiting does not replace network-level abuse protection.

## Domain behaviour and existing databases

Ticker matching is uppercase and case-insensitive at the service boundary. Duplicates are rejected **within an account**. Rules trigger strictly above or below the threshold; equality does not trigger. Firing deactivates the rule and records its event in the same transaction. A random generation token prevents stale evaluations from firing a new rule after SQLite reuses an ID.

Removing a ticker leaves its active rules **dormant**. Adding it back resumes them. Deleting a rule preserves event snapshots and sets `rule_id` to NULL. The UI shows the latest 100 events; older history stays in SQLite and the summary count includes it. A ticker without a fresh price is skipped and its rules stay active for the next check. Manual checks say how many tickers were skipped without exposing provider details.

Startup automatically upgrades the previous three-table shared schema. Existing rows keep their IDs, values and relationships under reserved `owner_id=0`; nobody can sign in as that owner, and its rules are not polled. The first registrant does **not** receive old private data. New accounts begin empty. Assigning legacy records requires a future deliberate administrative migration after ownership is established; there is no automatic claiming mechanism.

## Tests

```sh
pytest
pytest --cov=app --cov-report=term-missing
```

The coverage configuration measures services, repositories, rules, price adapters, configuration, database upgrades, polling and access control. Only domain route files and the composition root are excluded as framework wiring. Coverage below 70% fails the run. All quote calls and the WebSocket are faked in tests; the contract test uses local loopback HTTP only.

Verified on 3 October 2026: **221 tests passed; 100% statement coverage across 771 statements** in the measured modules. Tests include the WebSocket subscribe/unsubscribe cycle, malformed stream messages, reconnect backoff, key redaction, the `/api/quotes` ownership check, concurrent one-shot firing, deletion/ID reuse, rollback, private ownership, dormant rules, malformed quotes, cache expiry, quotas, password hashing, CSRF, session revocation/expiry, throttling and automatic legacy upgrades. Statement coverage does not prove every possible input or race is safe.

Browser verification covers registration, login, adding assets, firing alerts, prices ticking on both pages, and layouts at 1440, 1024, 768 and 390 pixels. The interface uses Jinja templates, local CSS, labelled controls and keyboard focus styles, with horizontally scrollable tables on small screens.

## Architecture and delivery

`app/__init__.py` is the only composition root. It supplies owner-scoped `WatchlistService` and `AlertService` instances to request handlers. Alerts depends on neutral `WatchlistReader` and `PriceSource` protocols, never the watchlist or market modules. The poller and the Finnhub stream are started only by `app.py`; create_app builds them but never opens a connection. The poller creates account-scoped evaluations through the composition root. Connections are short-lived and never shared across threads. SQLite uses its default journal mode.

`requirements.txt` is the sole dependency manifest, with seven direct packages. There is no Dockerfile, Compose file, CI workflow, IaC or public deployment. The repository is slightly above the suggested 50-file range because access control, its template/tests and a printable report are explicit artefacts; this is a soft cap.

Branch flow is **`feature/*` or `fix/*` → `develop` → `main`**. `develop` gathers tested features; `main` contains a reviewed release. Run the complete suite before integration and release. Branches are not a substitute for genuine work across days or remote push evidence.

See `ADR.md`, `docs/REPORT.md`, the printable `docs/REPORT.pdf`, and `docs/diagrams/` for decisions and diagrams. `AI_USAGE.md` remains the detailed disclosure log. Its outstanding personal explanations must be completed by the author; they are part of the assessment, alongside professor approval of the use case and the closed-book comprehension check.
