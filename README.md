# Stock watchlist and price alerts

Assignment 1. One Flask process served by waitress. Data lives in SQLite.

Right now only the watchlist works and alerts come next.

## Setup

You need Python 3.10 or newer.

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

Open http://localhost:8080. There's nothing to set up first. The app makes the data folder and tables when it starts. `GET /health` returns 200 once the tables exist.

## Settings

All of these are environment variables and all are optional.

| Variable                  | Default                        | What it does                          |
|---------------------------|--------------------------------|---------------------------------------|
| `HOST`                    | `0.0.0.0`                      | Address to listen on                  |
| `PORT`                    | `8080`                         | Port to listen on                     |
| `DATA_DIR`                | `./data`                       | Folder for the SQLite file            |
| `PRICE_API_KEY`           | unset                          | Price API key (used later by alerts)  |
| `POLL_INTERVAL_SECONDS`   | `60`                           | How often alerts get checked (later)  |
| `PRICE_CACHE_TTL_SECONDS` | `30`                           | How long a price is cached (later)    |
| `SECRET_KEY`              | `dev-only-not-for-production`  | Signs the session for flash messages  |

The database file is `$DATA_DIR/app.db`. Logs go to stdout.

## Tests and coverage

```sh
pytest --cov=app --cov-report=term-missing
```

Last run (2026-09-29): 14 passed. Total coverage is 70%. The watchlist service and repository are both at 100%. Most of what's left uncovered is the Flask routes and `create_app`.

## Files

```
app.py                start the app: python app.py
app/__init__.py       create_app builds the app and connects the domains
app/config.py         reads settings from env vars
app/db.py             opens SQLite connections and creates tables
app/ports.py          interfaces shared between domains
app/watchlist/        watchlist domain (schema, repository, service, routes)
app/templates/        HTML templates
tests/                unit tests
```
