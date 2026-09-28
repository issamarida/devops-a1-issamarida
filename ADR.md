# Architecture Decision Records

## 1. Backend language and framework

Date: 2026-09-28

Status: Decided

Context: The app must be built within a week and then defended cold at a closed-book comprehension check, so every layer has to be something I can explain without notes. It also has to run as a single process, started with `python app.py`, with no external database.

Decision: Python 3 with Flask, the standard-library `sqlite3` module (no ORM), Jinja2 templates for the frontend, and waitress as the WSGI server.

Alternatives considered: FastAPI was rejected because nothing in the app has an I/O concurrency need that would justify async request handling. Django was rejected as over-engineered for two small domains, since its admin, ORM and project layout would add concepts I would have to defend without using them. SQLAlchemy was rejected in favor of raw `sqlite3` so that every query is visible in the repository code and can be explained line by line.

Consequences: There are fewer abstractions to explain at the check, but I have to write the SQL and form parsing by hand. That moves more of the correctness burden onto the unit tests.
