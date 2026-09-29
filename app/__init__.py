"""create_app builds the Flask app.

This is the only file allowed to import more than one domain.
"""

from pathlib import Path

from flask import Flask, redirect, url_for

from app.config import Config
from app.db import get_connection, init_db
from app.watchlist import SCHEMA_PATH as WATCHLIST_SCHEMA
from app.watchlist.repository import WatchlistRepository
from app.watchlist.routes import create_watchlist_blueprint
from app.watchlist.service import WatchlistService

# Every schema file init_db runs. tests/conftest.py uses this same list.
SCHEMA_FILES = [
    WATCHLIST_SCHEMA,
    Path(__file__).parent / "alerts" / "schema.sql",
]


def create_app(config: Config) -> Flask:
    init_db(config.db_path, SCHEMA_FILES)

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
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'watchlist_items'"
        ).fetchone()
        conn.close()
        if row is None:
            return {"status": "database not ready"}, 503
        return {"status": "ok"}, 200

    return app
