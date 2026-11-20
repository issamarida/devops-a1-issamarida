"""The JSON endpoints the pages poll. None of them ever returns the API key.

security.py rejects every request here that has no valid sign-in token.
"""

from flask import Blueprint, jsonify, request


def create_market_blueprint(get_tickers, prices, info) -> Blueprint:
    bp = Blueprint("market", __name__)

    @bp.get("/api/quotes")
    def quotes():
        # Only the signed-in account's own tickers.
        body = prices.snapshot(get_tickers())
        body["market"] = info.market_status()
        return jsonify(body)

    @bp.get("/api/search")
    def search():
        return jsonify({"results": info.search(request.args.get("q", ""))})

    @bp.get("/api/details/<ticker>")
    def details(ticker):
        ticker = ticker.upper()
        if ticker not in get_tickers():
            return {"error": "Not on your watchlist."}, 404
        return jsonify({"ticker": ticker, "details": info.details(ticker)})

    return bp
