"""create_app builds the alerts service: price rules, their history and the checks.

It talks to the watchlist service over HTTP only, through app/alerts/watchlist_client.py.
"""

import logging
import sqlite3
from pathlib import Path

from flask import Flask, g
from flask_cors import CORS

from app.alerts.checker import AllOwners
from app.alerts.repository import AlertRepository
from app.alerts.routes import create_alerts_blueprint
from app.alerts.service import AlertService
from app.alerts.watchlist_client import RemoteWatchlist, Snapshot, fetch_snapshot
from app.config import Config
from app.db import check_database, init_db
from app.errors import install_error_handlers
from app.request_log import install_request_log
from app.security import install_access
from app.tokens import issue_service_token

logger = logging.getLogger(__name__)

# Every schema file init_db runs. tests/conftest.py uses this same list.
SCHEMA_FILES = [Path(__file__).parent / "alerts" / "schema.sql"]


def create_app(config: Config) -> Flask:
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

    def new_snapshot(tickers=()):
        """One answer from the watchlist, asked for on first use and at most once.

        A new one is made for each request and each poller run. tickers are the
        ones whose prices are needed.
        """
        return Snapshot(
            lambda: fetch_snapshot(
                config.watchlist_url,
                config.watchlist_timeout_seconds,
                issue_service_token(config.token_secret),
                tickers,
            )
        )

    def alerts_for(owner_id, snapshot):
        # The same object answers "is it watched?" and "what does it cost?".
        watchlist = RemoteWatchlist(snapshot, owner_id)
        repository = AlertRepository(config.db_path, owner_id, config.max_alert_rules)
        return AlertService(repository, watchlist, watchlist)

    def service_for_request():
        return alerts_for(g.user["id"], new_snapshot())

    def checking_service_for_request():
        repository = AlertRepository(config.db_path, g.user["id"])
        tickers = {rule["ticker"] for rule in repository.list_active_rules()}
        return alerts_for(g.user["id"], new_snapshot(tickers))

    app.register_blueprint(
        create_alerts_blueprint(service_for_request, checking_service_for_request)
    )

    # app.py hands this to the poller. create_app never starts a thread.
    app.extensions["alert_service"] = AllOwners(config.db_path, new_snapshot, alerts_for)
    app.extensions["alerts_for"] = alerts_for

    @app.get("/health")
    def health():
        # About this service's own database only, never about the watchlist service.
        try:
            check_database(config.db_path)
        except sqlite3.Error:
            # The details go to the log only, never into the response.
            logger.exception("Health check failed")
            return {"status": "error", "db": "error", "version": config.git_sha}, 503
        return {"status": "ok", "db": "ok", "version": config.git_sha}, 200

    return app
