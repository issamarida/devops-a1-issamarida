"""The JSON endpoint the pages poll for prices. It never returns the API key."""

from flask import Blueprint, jsonify


def create_market_blueprint(get_tickers, prices) -> Blueprint:
    bp = Blueprint("market", __name__)

    @bp.get("/api/quotes")
    def quotes():
        # Only the signed-in account's own tickers. security.py rejects anyone else.
        return jsonify(prices.snapshot(get_tickers()))

    return bp
