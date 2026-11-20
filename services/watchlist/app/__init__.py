"""create_app builds the watchlist service: tracked assets, prices and accounts.

This is the only file allowed to import more than one part of the service.
"""

import logging
import sqlite3

from flask import Flask, g
from flask_cors import CORS

from app.config import Config
from app.db import check_database, init_db
from app.errors import install_error_handlers
from app.market.cache import CachedPriceSource
from app.market.finnhub import FinnhubSource
from app.market.info import MarketInfo
from app.market.routes import create_market_blueprint
from app.market.snapshot import create_snapshot_blueprint
from app.market.stream import FinnhubStream, LivePrices
from app.request_log import install_request_log
from app.security import install_access
from app.watchlist import SCHEMA_PATH as WATCHLIST_SCHEMA
from app.watchlist.repository import (
    WatchlistRepository,
    most_watched_tickers,
    tickers_by_owner,
)
from app.watchlist.routes import create_watchlist_blueprint
from app.watchlist.service import WatchlistService

logger = logging.getLogger(__name__)

# Every schema file init_db runs. tests/conftest.py uses this same list.
SCHEMA_FILES = [WATCHLIST_SCHEMA]


def create_app(config: Config, *, price_source=None) -> Flask:
    init_db(config.db_path, SCHEMA_FILES)

    app = Flask(__name__)

    # First, so its line is written last and shows the final status.
    install_request_log(app)
    install_error_handlers(app)
    # Only the UI's own address may call this service from a browser. The two
    # headers are the ones the UI sends: JSON bodies and the sign-in token.
    CORS(
        app,
        origins=config.cors_origins,
        allow_headers=["Content-Type", "Authorization"],
        max_age=600,
    )
    install_access(app, config)

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

    app.extensions["watchlist_for"] = watchlist_for

    app.register_blueprint(
        create_watchlist_blueprint(lambda: watchlist_for(g.user["id"]))
    )
    app.register_blueprint(
        create_market_blueprint(
            lambda: [item.ticker for item in watchlist_for(g.user["id"]).list_items()],
            price_source,
            info,
        )
    )
    # The other side of the seam: the alerts service reads this over HTTP.
    app.register_blueprint(
        create_snapshot_blueprint(
            lambda: tickers_by_owner(config.db_path), price_source
        )
    )

    @app.get("/health")
    def health():
        # About this service's own database only, never about the alerts service.
        try:
            check_database(config.db_path)
        except sqlite3.Error:
            # The details go to the log only, never into the response.
            logger.exception("Health check failed")
            return {"status": "error", "db": "error", "version": config.git_sha}, 503
        return {"status": "ok", "db": "ok", "version": config.git_sha}, 200

    return app
