"""Composition root.

create_app is the only place allowed to import more than one domain and
wire concrete classes together.
"""

from flask import Flask

from pricewatch.config import Config
from pricewatch.db import get_connection, init_db

SCHEMA_PATHS = []
REQUIRED_TABLES = []


def create_app(config: Config) -> Flask:
    init_db(config.db_path, SCHEMA_PATHS)

    app = Flask(__name__)
    app.secret_key = config.secret_key

    @app.get("/health")
    def health():
        conn = get_connection(config.db_path)
        try:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        finally:
            conn.close()
        existing = {row["name"] for row in rows}
        missing = [table for table in REQUIRED_TABLES if table not in existing]
        if missing:
            return {"status": "unavailable", "missing_tables": missing}, 503
        return {"status": "ok"}, 200

    return app
