"""create_app builds the Flask app.

This is the only file allowed to import more than one domain.
"""

import logging
from pathlib import Path

from flask import Flask, redirect, url_for

from app.alerts.repository import AlertRepository
from app.alerts.routes import create_alerts_blueprint
from app.alerts.service import AlertService
from app.config import Config
from app.db import get_connection, init_db
from app.market.cache import CachedPriceSource
from app.market.demo import DemoPriceSource
from app.market.finnhub import FinnhubSource
from app.watchlist import SCHEMA_PATH as WATCHLIST_SCHEMA
from app.watchlist.repository import WatchlistRepository
from app.watchlist.routes import create_watchlist_blueprint
from app.watchlist.service import WatchlistService

logger = logging.getLogger(__name__)

# Every schema file init_db runs. tests/conftest.py uses this same list.
SCHEMA_FILES = [
    WATCHLIST_SCHEMA,
    Path(__file__).parent / "alerts" / "schema.sql",
]


def create_app(config: Config, *, price_source=None) -> Flask:
    init_db(config.db_path, SCHEMA_FILES)

    app = Flask(__name__)
    app.secret_key = config.secret_key

    watchlist_service = WatchlistService(WatchlistRepository(config.db_path))
    app.register_blueprint(create_watchlist_blueprint(watchlist_service))

    # Tests pass a fake price_source. The real app picks one from the config.
    app.config["USING_DEMO_PRICES"] = False
    if price_source is None:
        if config.price_api_key:
            price_source = CachedPriceSource(
                FinnhubSource(config.price_api_key), config.price_cache_ttl_seconds
            )
            logger.info("Price source: Finnhub")
        else:
            price_source = DemoPriceSource()
            app.config["USING_DEMO_PRICES"] = True
            logger.info("Price source: demo prices, PRICE_API_KEY is not set")

    # The watchlist service is passed in as the WatchlistReader.
    alert_service = AlertService(
        AlertRepository(config.db_path), price_source, watchlist_service
    )
    app.extensions["alert_service"] = alert_service
    app.register_blueprint(create_alerts_blueprint(alert_service))

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
