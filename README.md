# Stock watchlist and price alerts

Assignment 1. One Flask process served by waitress. Data lives in SQLite.

You keep a list of stocks you care about, then set alerts like "tell me when AAPL goes above 200". When the price crosses the line the alert fires once and lands in the trigger history.

The app has two domains:

- **Watchlist** (`app/watchlist/`) holds the tickers you track, with a name and notes.
- **Alerts** (`app/alerts/`) holds the price rules and the history of rules that fired.

## Where the seam is

Alerts never imports the watchlist or the price code. It only knows two small interfaces in `app/ports.py`:

- `WatchlistReader` with `is_watched(ticker)`
- `PriceSource` with `get_price(ticker)`, which raises `PriceUnavailable` when there's no price

`create_app` in `app/__init__.py` is the one place that plugs the real classes in. It passes `WatchlistService` in as the `WatchlistReader` and a price adapter from `app/market/` in as the `PriceSource`. `alert_rules.ticker` is plain text with no foreign key to `watchlist_items`, so alerts could move to its own service by swapping `WatchlistReader` for an HTTP client. `tests/test_architecture.py` fails if any import breaks these rules.

## Requirements

Python 3.10 or newer. Tested on Python 3.14.7.

## Setup

With plain pip:

```sh
git clone https://github.com/issamarida/devops-a1-issamarida.git
cd devops-a1-issamarida
python -m venv .venv
source .venv/bin/activate          # bash or zsh
source .venv/bin/activate.fish     # fish
pip install -r requirements.txt
python app.py
```

Or with uv:

```sh
uv venv
source .venv/bin/activate          # bash or zsh
source .venv/bin/activate.fish     # fish
uv pip install -r requirements.txt
python app.py
```

Open http://localhost:8080. There's nothing to set up first. The app makes the data folder and tables when it starts. `GET /health` returns 200 once it can read all three tables.

## Configuration

All settings are environment variables and all are optional. They're read in `app/config.py`.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `0.0.0.0` | Address to listen on |
| `PORT` | `8080` | Port to listen on. Must be a whole number from 1 to 65535 |
| `DATA_DIR` | `./data` | Folder for the SQLite file. The database is `$DATA_DIR/app.db` |
| `PRICE_API_KEY` | unset | Finnhub API key. Unset or empty means demo prices |
| `POLL_INTERVAL_SECONDS` | `60` | How often the poller checks the rules. 0 turns the poller off |
| `PRICE_CACHE_TTL_SECONDS` | `30` | How long a live price is cached. 0 means no caching |
| `SECRET_KEY` | `dev-only-not-for-production` | Signs the session cookie for flash messages |

A bad number stops the app at start with an error that names the variable.

## How alerts are checked

Rules get checked in two ways:

- A background thread started in `app.py` calls `AlertService.evaluate_all` every `POLL_INTERVAL_SECONDS`.
- The **Check rules now** button on `/alerts` runs the same check straight away.

Each check looks up every active rule. A rule whose ticker is no longer on the watchlist is dormant, so it gets skipped and kept. A rule fires when the price is strictly above or below its threshold. Firing turns the rule off and writes a row to `alert_events` in the same transaction, so each rule fires once.

**Demo or live prices.** Without `PRICE_API_KEY` the app uses `DemoPriceSource`. It makes up a steady price per ticker that moves by up to 5% every 30 seconds and needs no network. The alerts page shows a banner while demo prices are on. With a key set, prices come from the Finnhub quote API through a short cache. The key goes in a request header and never appears in logs or error messages.

## Testing

```sh
pytest --cov=app --cov-report=term-missing
```

Coverage settings live in `.coveragerc`. The Flask routes (`app/*/routes.py`) and the composition root (`app/__init__.py`) are left out because they're framework glue, which brief section 4 excludes. The run fails if coverage drops below 70%. Tests never touch the network.

Last run (2026-10-01):

```
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.14.7-final-0 ________________

Name                          Stmts   Miss  Cover   Missing
-----------------------------------------------------------
app/alerts/__init__.py            0      0   100%
app/alerts/repository.py         62      0   100%
app/alerts/rules.py               6      0   100%
app/alerts/service.py            56      0   100%
app/config.py                    25      0   100%
app/db.py                        14      0   100%
app/market/__init__.py            0      0   100%
app/market/cache.py              20      0   100%
app/market/demo.py               15      0   100%
app/market/finnhub.py            22      0   100%
app/poller.py                    23      0   100%
app/ports.py                      4      0   100%
app/watchlist/__init__.py         2      0   100%
app/watchlist/repository.py      30      0   100%
app/watchlist/service.py         33      0   100%
-----------------------------------------------------------
TOTAL                           312      0   100%
Required test coverage of 70.0% reached. Total coverage: 100.00%
============================= 119 passed in 0.72s ==============================
```

## Project layout

```
app.py                    start command: python app.py
app/__init__.py           create_app, the composition root
app/config.py             settings from environment variables
app/db.py                 SQLite connections and schema setup
app/ports.py              WatchlistReader, PriceSource, PriceUnavailable
app/poller.py             background thread that checks the rules
app/watchlist/            watchlist schema, repository, service, routes
app/alerts/               alerts schema, rule check, repository, service, routes
app/market/               demo prices, Finnhub adapter, price cache
app/templates/            HTML templates
tests/                    unit, architecture, contract and end-to-end tests
```

## Notes for Assignment 2 deployment

- Start command is `python app.py`.
- The port comes from `PORT`.
- `DATA_DIR` must point at a persistent volume. The container filesystem is lost on restart and the database would go with it.
- Run exactly one replica. Each replica would run its own poller and they'd all check the same rules.
- Use `GET /health` for the health probe. It returns 200 with `{"status": "ok"}` when it can read all three tables and 503 with `{"status": "error"}` when it can't. The cause goes to the log only.
- Supply `PRICE_API_KEY` as a secret at runtime. Never bake it into the image.
- Logs go to stdout.
