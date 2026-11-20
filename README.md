# Stock watchlist and price alerts

An app for retail investors who follow US stocks. Each investor keeps a private watchlist and sets price rules that fire once and leave a record. It monitors prices. It does not place trades or send email or push notifications.

Assignment 1 was one Flask process with one SQLite file. Assignment 2 splits it into two services along the seam from ADR-2 and ADR-6:

| Service | Folder | Owns | Default port |
|---|---|---|---|
| watchlist | `services/watchlist` | tracked assets, Finnhub prices, accounts and sign in | 8001 |
| alerts | `services/alerts` | price rules, trigger history, the background check | 8002 |

The alerts service calls the watchlist service over HTTP. The watchlist service never calls alerts. The static UI in `ui/` will call both from the browser.

## Status

Assignment 2 is in progress. This table is kept honest against the brief.

| Brief section | State |
|---|---|
| 1a Two services, own folders, own manifests | Done |
| 1a HTTP between services through an environment variable | Done |
| 3 Cross-seam flow on the server side, timeout on every call | Done |
| 3 Partial failure handled in a designed way | Done in the API. The UI part is not built yet |
| 3 `/health` with status, db and version, one log line per request | Done |
| 1a CORS only from the UI's origin, in code | Done |
| 5 CI: lint, tests and coverage per service | Done. Schema validation and image builds are not added yet |
| 1a SQL Server and one database per service | Started. Compose starts SQL Server and `db/init.sql` creates the two databases and logins. The services still use their own SQLite file |
| 4 Versioned migrations | Not yet |
| 1a Dockerfiles and `docker compose up --build` | Started. `docker-compose.yml` starts the database side only. No Dockerfiles yet |
| 1a Static UI in `ui/` | Not yet. `ui/` still holds the Assignment 1 Jinja templates as the starting point |
| 5 and 7 CD and the Azure deployment | Not yet |
| 8a `openapi.yaml` per service and `system.yaml` | Not yet. `system.schema.json` is in place |

## Run the two services

Python 3.14. One virtual environment can serve both services while working locally.

```sh
uv venv
source .venv/bin/activate.fish
uv pip install -r services/watchlist/requirements.txt
uv pip install -r services/alerts/requirements.txt
```

Both services need the same `TOKEN_SECRET`, at least 32 characters. It is a secret, so it has no default and is never written in this repository. Make one up for your own machine:

```sh
set -x TOKEN_SECRET (python -c "import secrets; print(secrets.token_urlsafe(48))")
```

Then start each service from its own folder, in two terminals that share that variable:

```sh
cd services/watchlist; python app.py
cd services/alerts; env WATCHLIST_URL=http://localhost:8001 python app.py
```

To run a single service, start only that one. The watchlist service does not need alerts at all. The alerts service starts and serves its own data without the watchlist, as described under "When the watchlist is down".

Prices come from Finnhub. Set `PRICE_API_KEY` for the watchlist service to get them. Without a key the service still runs and every price is reported as unavailable. No price is ever made up.

## The local SQL Server

`docker-compose.yml` starts one SQL Server container that holds one database per service. The services are not connected to it yet, so this part is the groundwork for the move away from SQLite.

```sh
docker compose up -d
sh db/check-logins.sh
```

| Compose service | What it does |
|---|---|
| `secrets` | Runs once. Makes up the local passwords on the first start and keeps them in the `local-secrets` volume |
| `db` | SQL Server 2022. Its data is in the `db-data` volume and survives `docker compose down` |
| `db-init` | Runs `db/init.sql` on every start. Creates the `watchlist` and `alerts` databases and one login for each, if they are missing |

- No password is written in this repository, not even a local one. `db/make-secrets.sh` makes them up on your machine.
- `db/init.sql` checks before it creates, so running it again changes nothing.
- `watchlist_user` has a user in the `watchlist` database only, and `alerts_user` in `alerts` only. `db/check-logins.sh` proves each login opens its own database and is refused on the other. CI runs it on every push.
- `docker compose down -v` deletes both volumes, which deletes the data and the passwords. It is never needed to restart or rebuild.

## API

Every request and answer is JSON. Errors are always `{"error": "..."}`. Apart from `/health` and the two `/auth` endpoints, a request needs the header `Authorization: Bearer <token>` with the token from sign in.

**watchlist**

| Method and path | What it does |
|---|---|
| `GET /health` | 200 with `status`, `db` and `version`, or 503 |
| `POST /auth/register` | Create an account |
| `POST /auth/login` | Answer with a signed token that lasts `TOKEN_SECONDS` |
| `GET /watchlist` | The account's assets |
| `POST /watchlist` | Add an asset: 201, 400 if invalid, 409 if already there |
| `DELETE /watchlist/<ticker>` | Remove an asset: 204 or 404 |
| `GET /api/quotes` | Live prices for the account's assets, and the market session |
| `GET /api/search?q=` | Ticker suggestions |
| `GET /api/details/<ticker>` | Company details for an asset on the watchlist |
| `GET /internal/snapshot?tickers=` | For the alerts service only: who watches what, and the asked prices |

**alerts**

| Method and path | What it does |
|---|---|
| `GET /health` | 200 with `status`, `db` and `version`, or 503 |
| `GET /alerts` | The account's rules with a status, and `watchlist_available` |
| `POST /alerts` | Add a rule: 201, 400 if invalid, 503 if the watchlist can't be reached |
| `DELETE /alerts/<id>` | Delete a rule: 204 or 404. Its history stays |
| `GET /alerts/events` | The latest 100 trigger events and the total count |
| `POST /alerts/evaluate` | Check the account's rules now: 200 with what fired, or 503 |

## The seam, and when the watchlist is down

The alerts service needs two facts it does not own: is this ticker on the account's watchlist, and what does it cost now. It gets both from one request to `GET /internal/snapshot` on the watchlist service.

- The address comes from `WATCHLIST_URL`. No hostname is written in the code.
- Every call has a timeout, `WATCHLIST_TIMEOUT_SECONDS`.
- Listing and creating rules ask who watches what. Only a check also asks for prices, and only for tickers that have an active rule.
- The background check makes one request per run for all accounts, and none when no rule is active.

When the watchlist service is stopped, too slow or answers nonsense:

| Request to alerts | Answer |
|---|---|
| `GET /alerts` | 200. Open rules get the status `unknown` and `watchlist_available` is `false` |
| `POST /alerts` | 503 with "The watchlist can't be reached right now, so the rule was not saved. Try again in a moment." |
| `POST /alerts/evaluate` | 503. No rule fires on a price nobody could confirm |
| history, delete, `/health` | Unchanged. They only use the alerts service's own data |

The background check skips that run and logs one warning. Every rule stays active and is checked again on the next run.

## Sign in and access

- The watchlist service holds the accounts. Passwords are salted and hashed with scrypt and must be 15 to 128 characters.
- Sign in answers with a JSON Web Token signed with `TOKEN_SECRET` (HS256). It holds the account ID, the username and an expiry time. There are no cookies and no server-side sessions.
- Both services check the token's signature themselves. The alerts service never calls the watchlist to learn who is asking, so it keeps working when the watchlist is stopped.
- A token cannot be withdrawn before it expires. That is the cost of keeping no session state, and why the default lifetime is one hour.
- Every query uses the account ID from the token. An account ID sent in a request body is ignored.
- `/internal/snapshot` only opens for a one-minute token with the `snapshot` scope, which the alerts service signs with the same secret.
- Sign-in attempts and registrations are rate limited in the watchlist database, so the limits survive a restart.
- Each service allows browser requests from the addresses in `CORS_ORIGINS` only.

## Configuration

Every setting is an environment variable. Each service also reads an optional git-ignored `.env` file in its own folder. A variable set in the shell always wins.

**watchlist**

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8001` | Port the service listens on |
| `DATA_DIR` | `./data` | Folder for the SQLite file, until SQL Server replaces it |
| `TOKEN_SECRET` | none, required | Secret that signs the tokens. The same value in both services |
| `PRICE_API_KEY` | none | Finnhub key. A secret. Without it prices are unavailable |
| `CORS_ORIGINS` | `http://localhost:8080` | The UI's address. A comma-separated list is allowed |
| `GIT_SHA` | `dev` | The commit the service was built from, shown by `/health` |
| `TOKEN_SECONDS` | `3600` | How long a sign-in token lasts |
| `PRICE_CACHE_TTL_SECONDS` | `30` | How long a REST quote is reused |
| `QUOTE_REQUESTS_PER_MINUTE` | `50` | Budget for calls to Finnhub. Its free plan allows 60 |
| `LIVE_SYMBOL_LIMIT` | `50` | Most tickers streamed at once |
| `AUTH_ATTEMPTS` | `5` | Sign-in attempts per username, and registrations per address, per window |
| `AUTH_WINDOW_SECONDS` | `900` | Length of that window |
| `MAX_ACCOUNTS` | `50` | Most accounts |
| `MAX_WATCHLIST_ITEMS` | `30` | Most assets per account |

**alerts**

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8002` | Port the service listens on |
| `DATA_DIR` | `./data` | Folder for the SQLite file, until SQL Server replaces it |
| `TOKEN_SECRET` | none, required | The same secret as the watchlist service |
| `WATCHLIST_URL` | `http://watchlist:8001` | Base address of the watchlist service |
| `WATCHLIST_TIMEOUT_SECONDS` | `3` | Timeout for each call to the watchlist. At most 30 |
| `POLL_INTERVAL_SECONDS` | `15` | Wait between background checks. 0 turns them off |
| `CORS_ORIGINS` | `http://localhost:8080` | The UI's address |
| `GIT_SHA` | `dev` | The commit the service was built from, shown by `/health` |
| `MAX_ALERT_RULES` | `100` | Most rules per account, fired ones included |

A wrong value stops the service at start with a message that names the variable.

## Tests

Each service has its own tests and its own coverage gate. Run them from the service's folder:

```sh
cd services/watchlist; pytest --cov
cd services/alerts; pytest --cov
ruff check services
```

Verified on 20 November 2026: watchlist 222 tests and alerts 201 tests, both at 100% statement coverage of their measured modules. Coverage below 70% fails the run. As in Assignment 1 the thin route files and `create_app` are left out of the measure and are exercised through the API tests instead.

No test touches the internet. Finnhub is mocked. The cross-seam tests in `services/alerts/tests` replace the watchlist service with `StubWatchlist`, a real HTTP server on localhost that checks the service token as the real one does. The tests stop it, slow it down and make it answer nonsense to prove the answers in the table above.

CI in `.github/workflows/ci.yml` runs the linter and both test suites on every push and pull request. A third job starts the compose database, runs `db/init.sql` twice and runs `db/check-logins.sh`.

## Rules of the domain

- Tickers are stored in upper case. A ticker can be on an account's watchlist once.
- A rule fires when the price is strictly above or below its threshold. A price equal to the threshold does not fire it.
- A rule fires once. Firing deactivates it and writes the history row in the same transaction.
- Removing a ticker from the watchlist leaves its rules dormant. Adding it back resumes them.
- Deleting a rule keeps its history.
- A ticker with no fresh price is skipped and its rules stay active.

## Documents

- `ADR.md`: the decisions, including ADR-6 on the split.
- `AI_USAGE.md`: every AI session and what it produced.
- `docs/`: the Assignment 1 report and diagrams. The Assignment 2 report will replace them.
- `system.schema.json`: the course's schema for `system.yaml`, unchanged.
