# PriceWatch

A stock watchlist and price-alert web app (Assignment 1). It is a single Flask
process served by waitress, with SQLite storage.

Current status: the watchlist domain is implemented. The alerts domain is next.

## Setup

Requires Python 3.10+.

```sh
git clone https://github.com/issamarida/devops-a1-issamarida.git
cd devops-a1-issamarida
python -m venv .venv
source .venv/bin/activate        # fish: source .venv/bin/activate.fish
pip install -r requirements.txt
```

## Run

```sh
python app.py
```

Then open http://localhost:8080. You don't need to set anything up first: the
data directory and tables are created automatically on startup. `GET /health`
returns 200 once the schema exists.

## Configuration (environment variables, all optional)

| Variable                  | Default                        | Purpose                                   |
|---------------------------|--------------------------------|-------------------------------------------|
| `HOST`                    | `0.0.0.0`                      | Bind address                              |
| `PORT`                    | `8080`                         | Listen port                               |
| `DATA_DIR`                | `./data`                       | Directory holding the SQLite file         |
| `PRICE_API_KEY`           | unset                          | Key for the market price API (upcoming)   |
| `POLL_INTERVAL_SECONDS`   | `60`                           | Alert evaluation interval (upcoming)      |
| `PRICE_CACHE_TTL_SECONDS` | `30`                           | Price cache lifetime (upcoming)           |
| `SECRET_KEY`              | `dev-only-not-for-production`  | Flask session signing (flash messages)    |

The database is always at `$DATA_DIR/pricewatch.db`. Logs go to stdout only.

## Tests and coverage

```sh
pytest --cov=pricewatch --cov-report=term-missing
```

Latest result (2026-09-28): 15 passed. Coverage is 67% for the whole package.
The watchlist service is at 94% and the watchlist repository at 90%. The
uncovered lines are mostly the HTTP routes and the composition root.

## Project layout

```
app.py                     entry point (python app.py)
pricewatch/__init__.py     create_app: the composition root, wires domains together
pricewatch/config.py       env-var configuration
pricewatch/db.py           sqlite3 connection + schema init
pricewatch/ports.py        neutral Protocols shared between domains
pricewatch/watchlist/      watchlist domain (schema, repository, service, routes)
pricewatch/templates/      Jinja2 templates
tests/                     pytest unit tests
```
