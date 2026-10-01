# Report: stock watchlist and price alerts

Assignment 1.

## 1. Problem and users

My stakeholder is a part-time retail investor. They hold or follow 10 to 30 US stocks and have a day job, so they can't sit and watch charts. What they want is simple. Tell me when AAPL goes above 200 or when TSLA drops below 150, then leave me alone.

The app does that in two parts. The watchlist is the list of tickers they care about, each with a name and some notes. Alerts are price rules on those tickers. A rule says "above" or "below" a threshold. When the price crosses the line the rule fires once and the firing is saved in a trigger history they can read later.

Scale assumption: one user with under 100 rules. Prices are refreshed once a minute. With 30 tickers that is at most 30 quote calls a minute, which stays inside Finnhub's free-tier rate limit. A 30 second price cache cuts that further when the poller and the "Check rules now" button ask for the same ticker close together. At this size one Flask process and one SQLite file are plenty.

## 2. SDLC

### Model and why

I used an iterative and incremental model. Each step added one working slice on top of the last one and ended with green tests and a commit. The order was scaffold and config first, then the watchlist domain, then the alerts core, then price adapters and the poller, then the testing and contract work, then this report.

It fits the brief because the scope is fixed and the time is short. I knew from day one what had to exist: two domains on SQLite, 70% coverage, five ADRs and the section 7 contract. What I didn't know was how the code would look once the second domain had to talk to the first. Building in slices meant I always had something that ran, and I could change direction cheaply when I found a problem. That happened on 29 Sep, covered below.

Waterfall was rejected because it assumes the design is right before any code exists. I would have written the whole design up front and then found out late that alerts needed a seam to the watchlist. Scrum was rejected because it is built for a team. Sprint planning, daily stand-ups and retrospectives for one person in one week would be ceremony with nobody to talk to. I kept the useful part of it, which is short cycles that end in something working.

### SMART goals

1. Both domains read and write through SQLite, with their own schema files and tests, by 1 Oct.
2. Coverage of the core logic (services, repositories, rules, market adapters, config and poller) is at least 70% with the README command, by 1 Oct.
3. Every one of the ten deployment contract items in brief section 7 is covered by an automated test, by 2 Oct.
4. Five ADRs exist in ADR.md, written across at least three different dates, by 2 Oct.
5. This report is drafted by 2 Oct and revised on 3 Oct, one day before the 4 Oct deadline.

### How it went in practice

The git log tells the story better than my plan did.

I created the repo on 23 Sep and then did nothing on it for five days. That gap was not in the plan. It squeezed the real work into 28 Sep to 1 Oct.

On 28 Sep I built the scaffold, config, db helpers and the whole watchlist domain. I wrote it in one sitting and committed it as three commits a minute apart. The commits are honest about what changed, but they don't show the work spread over the day.

On 29 Sep I stopped adding features and refactored. The first version lived in a package with a product name and had code I couldn't explain cleanly. I renamed the package to app/, made the code plainer and fixed the tests and docs to match. It was one large commit touching 25 files. It cost me a day on the plan, but I'm glad I did it before alerts existed rather than after.

30 Sep was the biggest day. Starting just after midnight and through the day I built the alerts schema and rule logic, the fire-and-log transaction, AlertService behind the ports, the demo and Finnhub price sources, the cache, the poller and config validation. That is 8 of the 20 commits so far, which is right at the 40% limit for one day. ADR-2 and ADR-3 were written that day as I made those decisions.

On 1 Oct I added the architecture test, scoped coverage to core logic, wrote the contract and end-to-end tests and recorded ADR-4. One commit that day has the message "update". That message doesn't describe anything, and it doesn't count as a meaningful commit under section 5. It updated the README and AI_USAGE.md.

Against the goals: goal 1 was met on 30 Sep, a day early. Goal 2 was met on 1 Oct at 100%. Goal 3 was met on 1 Oct with tests/test_contract.py. Goal 4 is met with ADR-5 on 1 Oct, with entries dated 28 Sep, 30 Sep and 1 Oct. Goal 5 is half done. I drafted the report on 1 Oct and the revision on 3 Oct is still ahead of me as I write this.

The model held up. The 29 Sep refactor is the iterative part working as intended. The weak spot was the start, where an early gap turned a week into four working days.

## 3. Architecture

The app is one Flask process served by waitress and started with `python app.py`. Inside it there are two domains and a set of price adapters.

![Architecture diagram](diagrams/architecture.png)

Solid arrows are calls. Dotted arrows show what create_app wires together and which classes fit which interface. The source is `docs/diagrams/architecture.mmd`.

Each domain has the same layers:

- **Routes** (`routes.py`) are Flask blueprints. They read the form, call the service and redirect with a flash message. No rules live here.
- **Service** (`service.py`) holds the rules. WatchlistService normalises and validates tickers and turns a UNIQUE violation into DuplicateTickerError. AlertService validates new rules and runs `evaluate_all`.
- **Repository** (`repository.py`) holds all the SQL for that domain's tables. Every method opens its own short connection with `get_connection` and closes it when done, so no two threads ever share a connection.

Alerts also has `rules.py` with `is_triggered`, a pure function with no database or network.

### The seam

The seam between the domains is `app/ports.py`. It defines two Protocols and one exception:

- `PriceSource` with `get_price(ticker)`, which returns a float or raises `PriceUnavailable`
- `WatchlistReader` with `is_watched(ticker)`

AlertService only knows these. It never imports the watchlist or the market code. WatchlistService has an `is_watched` method, so it fits WatchlistReader without importing ports.py at all. The market adapters (DemoPriceSource, FinnhubSource and CachedPriceSource) import only ports.py. `tests/test_architecture.py` reads every file under app/ with `ast` and fails if any import breaks these rules.

### The composition root

`create_app` in `app/__init__.py` is the only module that imports more than one domain. It runs `init_db` with both schema files, builds WatchlistService and passes that same object into AlertService as the WatchlistReader. It picks the price source from the config. With `PRICE_API_KEY` set it wraps FinnhubSource in CachedPriceSource. Without it, it uses DemoPriceSource and the alerts page shows a demo banner. Tests pass their own fake price source through a keyword argument. It also defines `/` and `/health`.

### The poller

`app/poller.py` has `start_poller`, which starts one daemon thread that calls `AlertService.evaluate_all` every `POLL_INTERVAL_SECONDS`. Only `app.py` starts it, after `create_app` returns. `create_app` never does, so tests and the Flask test client never get a background thread. `run_once` catches any exception and logs it so one bad check can't kill the thread. The "Check rules now" button calls the same `evaluate_all`, so both paths share one code path. If both ever race on a rule, `fire_rule` uses `BEGIN IMMEDIATE` and only fires a rule that is still active, so it fires once.

### How alerts would split out

Alerts plus the market adapters would become their own service. The alert tables already have no foreign key to watchlist_items, so they move to their own SQLite file as they are. WatchlistReader would get a new class that calls the watchlist service over HTTP and returns True or False. That would need a small JSON endpoint on the watchlist side, which doesn't exist yet. AlertService, the repository and the tests would not change, because they only depend on the Protocol. The poller moves with alerts.

## 4. Data model

There are three tables in one SQLite file at `$DATA_DIR/app.db`. Each domain owns its own schema file and only its repository touches its tables.

![Database schema diagram](diagrams/schema.png)

The solid line is a real foreign key. The dotted line is the soft reference by ticker, which has no foreign key. The source is `docs/diagrams/schema.mmd`.

- **watchlist_items** (watchlist domain): one row per tracked ticker. `ticker` is UNIQUE, so a duplicate is rejected by SQLite and the service turns that into a clear message.
- **alert_rules** (alerts domain): one row per rule. `condition` is limited to 'above' or 'below' and `threshold` must be greater than 0 by CHECK constraints. `is_active` goes from 1 to 0 when the rule fires.
- **alert_events** (alerts domain): one row per firing. It copies the ticker, condition and threshold from the rule and stores the observed price and time. `rule_id` points at alert_rules with `ON DELETE SET NULL`.

The link from alerts to the watchlist is the ticker as plain text, with no foreign key. That is ADR-2. Both services uppercase the ticker before storing or comparing it, so the plain text match works. If a ticker is removed from the watchlist its rules stay in the table and are skipped on every check. I call those dormant.

The snapshot columns in alert_events are ADR-3. Deleting a rule keeps its history readable and the history page needs no join. The cost is some duplicated values between the two alert tables.

The schema is created on every start with `CREATE TABLE IF NOT EXISTS`, so there is no migration step. SQLite stays in its default journal mode.

## 5. Testing

My approach is in ADR-4. I put most tests on the code where a bug would hurt the user: `is_triggered`, `AlertService.evaluate_all`, `fire_rule` and the watchlist validation. AlertService tests use fake PriceSource and WatchlistReader classes, which the ports make easy. The tests run against a real SQLite file in a temporary folder, never a mock database. Finnhub tests mock `requests`, so no test touches the network.

Around that there are four other kinds of test:

- **Architecture** (`tests/test_architecture.py`) fails on any import that breaks the domain rules.
- **Contract** (`tests/test_contract.py`) starts `python app.py` as a real subprocess on a free port with an empty `DATA_DIR` and waits up to 5 seconds for `/health` to return 200. It also checks the repo for banned files and settings.
- **End to end** (`tests/test_end_to_end.py`) goes from adding a ticker to a fired alert in the trigger history through the Flask test client.
- **Config and poller** tests cover the env var defaults, the error messages for bad values and the thread stopping cleanly.

Coverage is measured with `pytest --cov=app --cov-report=term-missing`. `.coveragerc` leaves out the Flask routes and `app/__init__.py`, because section 4 asks for core logic and not framework glue. It fails the run below 70%.

The last run on 1 Oct gave 119 passed tests and 100% coverage on 312 statements. The number is high because the code is small and the tests were written alongside it. I know it doesn't prove everything. The routes are only covered by the end-to-end and contract tests, and the Finnhub fakes would not notice if Finnhub changed its response format.

## 6. Readiness for Assignment 2

| # | Contract item | How it is met | Proof |
|---|---|---|---|
| 1 | One process, one command | `python app.py` builds the app, starts the poller thread and calls waitress `serve`. | `test_python_app_py_starts_and_reports_healthy` |
| 2 | Bind to 0.0.0.0 | `HOST` defaults to 0.0.0.0. No code mentions localhost or 127.0.0.1. | `test_defaults_when_nothing_is_set`, `test_code_has_no_forbidden_settings` |
| 3 | Port from one env var | `PORT`, default 8080, checked to be 1 to 65535. | `test_config.py`, contract test sets `PORT` |
| 4 | No interactive setup | No `input()`. `init_db` creates the folder and tables on start. | Contract test starts from a folder that doesn't exist yet |
| 5 | One documented SQLite path | `$DATA_DIR/app.db`, default `./data`. | Contract test asserts the file exists under `DATA_DIR` |
| 6 | No required external dependency | Without `PRICE_API_KEY` the app uses DemoPriceSource and needs no network. Finnhub is optional. | Contract test runs with an empty key, `test_market.py` |
| 7 | One manifest at the root | `requirements.txt` only. | `test_requirements_txt_is_the_only_manifest` |
| 8 | No Dockerfile or CI needed | None exist and none are needed to run. | `test_no_container_ci_or_iac_files` |
| 9 | Configurable by env vars only | Seven variables, each with a default in `app/config.py`. No `.env` file is needed or tracked. | `test_config.py`, `test_no_env_or_database_file_is_tracked` |
| 10 | Ready within a few seconds | Startup is config, schema and serve. The contract test needs `/health` to return 200 inside 5 seconds. | `test_python_app_py_starts_and_reports_healthy` |

Two things matter for the deployment itself and are in the README. `DATA_DIR` must sit on a persistent volume or the database is lost on restart. The app must run as exactly one replica, because each replica would start its own poller against the same rules. `PRICE_API_KEY` is supplied as a runtime secret and never baked into the image.

## 7. AI disclosure
