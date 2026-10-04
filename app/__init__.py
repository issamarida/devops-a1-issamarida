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
from app.market.info import MarketInfo
from app.market.routes import create_market_blueprint
from app.market.stream import FinnhubStream, LivePrices
from app.security import install_access
from app.watchlist import SCHEMA_PATH as WATCHLIST_SCHEMA
from app.watchlist.repository import WatchlistRepository, most_watched_tickers
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

    # Tests inject an offline fake. At runtime every price comes from Finnhub:
    # streamed trades first, the REST quote when no recent trade exists.
    # Tests get a MarketInfo with no key, so it never calls the network.
    info = MarketInfo(FinnhubSource(None))
    if price_source is None:
        finnhub = FinnhubSource(
            config.price_api_key,
            requests_per_minute=config.quote_requests_per_minute,
        )
        info = MarketInfo(finnhub)
        stream = FinnhubStream(
            config.price_api_key,
            lambda: most_watched_tickers(config.db_path),
            max_symbols=config.live_symbol_limit,
        )
        price_source = LivePrices(
            stream,
            CachedPriceSource(finnhub, config.price_cache_ttl_seconds),
        )
    # app.py starts this. create_app never opens a connection.
    app.extensions["price_stream"] = getattr(price_source, "stream", None)

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
    def alert_summary():
        alerts = alerts_for(g.user["id"])
        events = alerts.list_events()
        return {
            "event_count": alerts.count_events(),
            "latest": events[0] if events else None,
        }

    app.register_blueprint(
        create_market_blueprint(
            lambda: [item.ticker for item in watchlist_for(g.user["id"]).list_items()],
            price_source,
            info,
            alert_summary,
        )
    )

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
