# Architecture Decision Records

## 1. Backend language and framework

Date: 2026-09-28

Status: Decided

Context: I have one week to build this and then explain it at a closed-book check with no notes. It has to run as one process with no outside database.

Decision: Python 3 with Flask. I use the built-in sqlite3 module with no ORM. Pages are Jinja2 templates and waitress serves the app.

Alternatives considered: FastAPI was rejected because nothing here needs async. Django was rejected because it's far too big for two small domains. SQLAlchemy was rejected so every query stays plain SQL that I can read out and explain.

Consequences: There's less framework to explain at the check. I write the SQL and form handling by hand so the tests have to catch more mistakes.
