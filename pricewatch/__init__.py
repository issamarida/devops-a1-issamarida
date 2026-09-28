"""Composition root.

create_app is the only place allowed to import more than one domain and
wire concrete classes together.
"""

from flask import Flask, redirect, url_for

from pricewatch import watchlist
from pricewatch.config import Config
from pricewatch.db import get_connection, init_db
from pricewatch.watchlist.repository import WatchlistRepository
from pricewatch.watchlist.routes import create_watchlist_blueprint
from pricewatch.watchlist.service import WatchlistService

SCHEMA_PATHS = [watchlist.SCHEMA_PATH]
REQUIRED_TABLES = ["watchlist_items"]


def create_app(config: Config) -> Flask:
    init_db(config.db_path, SCHEMA_PATHS)

    app = Flask(__name__)
    app.secret_key = config.secret_key

    watchlist_service = WatchlistService(WatchlistRepository(config.db_path))
    app.register_blueprint(create_watchlist_blueprint(watchlist_service))

    @app.get("/")
    def index():
        return redirect(url_for("watchlist.list_items"))

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
