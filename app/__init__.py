"""create_app builds the Flask app.

This is the only file allowed to import more than one domain.
"""

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Flask, g, redirect, url_for

from app.alerts.repository import AlertRepository
from app.alerts.routes import create_alerts_blueprint
from app.alerts.service import AlertService
from app.config import Config
from app.db import get_connection, init_db
from app.market.cache import CachedPriceSource
from app.market.finnhub import FinnhubSource
from app.security import install_access
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

    access = install_access(app, config)

    # Tests inject an offline fake. Finnhub is the only runtime price source.
    app.config["PRICE_SOURCE_CONFIGURED"] = price_source is not None or bool(
        config.price_api_key
    )
    if price_source is None:
        price_source = CachedPriceSource(
            FinnhubSource(
                config.price_api_key,
                requests_per_minute=config.quote_requests_per_minute,
            ),
            config.price_cache_ttl_seconds,
        )
        if config.price_api_key:
            logger.info("Price source: Finnhub")
        else:
            logger.warning(
                "Finnhub is not configured; set PRICE_API_KEY to enable price checks"
            )

    def watchlist_for(owner_id):
        return WatchlistService(
            WatchlistRepository(config.db_path, owner_id, config.max_watchlist_items)
        )

    def alerts_for(owner_id):
        return AlertService(
            AlertRepository(config.db_path, owner_id, config.max_alert_rules),
            price_source,
            watchlist_for(owner_id),
        )

    app.register_blueprint(
        create_watchlist_blueprint(lambda: watchlist_for(g.user["id"]))
    )
    app.register_blueprint(create_alerts_blueprint(lambda: alerts_for(g.user["id"])))

    class AllAccounts:
        def evaluate_all(self):
            fired = []
            for owner_id in access.account_ids():
                try:
                    fired.extend(alerts_for(owner_id).evaluate_all())
                except Exception:
                    logger.exception("Alert check failed for an account")
            return fired

    app.extensions["alert_service"] = AllAccounts()
    app.extensions["alerts_for"] = alerts_for
    app.extensions["watchlist_for"] = watchlist_for

    @app.context_processor
    def workspace_context():
        if not g.user:
            return {}
        items = watchlist_for(g.user["id"]).list_items()
        alerts = alerts_for(g.user["id"])
        rules = alerts.list_rules()
        return {
            "asset_count": len(items),
            "watched_tickers": [item.ticker for item in items],
            "active_count": sum(rule["status"] == "active" for rule in rules),
            "dormant_count": sum(rule["status"] == "dormant" for rule in rules),
            "event_count": alerts.count_events(),
            "prices_configured": app.config["PRICE_SOURCE_CONFIGURED"],
            "poll_interval": config.poll_interval_seconds,
        }

    @app.get("/")
    def index():
        return redirect(url_for("watchlist.list_items"))

    @app.get("/health")
    def health():
        # Reads each table once. Fails if the file or a table is missing.
        try:
            with closing(get_connection(config.db_path)) as conn:
                conn.execute("SELECT 1 FROM watchlist_items LIMIT 1").fetchone()
                conn.execute("SELECT 1 FROM alert_rules LIMIT 1").fetchone()
                conn.execute("SELECT 1 FROM alert_events LIMIT 1").fetchone()
                conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone()
                conn.execute("SELECT 1 FROM rate_limits LIMIT 1").fetchone()
        except sqlite3.Error:
            # The details go to the log only, never into the response.
            logger.exception("Health check failed")
            return {"status": "error"}, 503
        return {"status": "ok"}, 200

    return app
