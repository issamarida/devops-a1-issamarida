"""The one answer the alerts service asks for: who watches what, and what it costs.

    GET /internal/snapshot?tickers=AAPL,MSFT

    {"owners": {"7": ["AAPL", "MSFT"]}, "prices": {"AAPL": 187.44, "MSFT": null}}

"owners" always lists every account's tickers. "prices" only holds the tickers
that were asked for, so listing rules never waits for a price lookup.
security.py only lets the alerts service call this.
"""

from flask import Blueprint, request

from app.ports import PriceSource, PriceUnavailable

MAX_TICKERS = 200


def build_snapshot(owners: dict, tickers, price_source: PriceSource) -> dict:
    watched = {ticker for owned in owners.values() for ticker in owned}
    prices = {}
    for ticker in tickers:
        # A ticker nobody watches can't trigger a rule, so its price is never fetched.
        if ticker not in watched or ticker in prices:
            continue
        try:
            prices[ticker] = price_source.get_price(ticker)
        except PriceUnavailable:
            prices[ticker] = None  # null in JSON: the rule waits for the next check
    return {"owners": owners, "prices": prices}


def create_snapshot_blueprint(get_owners, price_source: PriceSource) -> Blueprint:
    bp = Blueprint("internal", __name__)

    @bp.get("/internal/snapshot")
    def snapshot():
        asked = request.args.get("tickers", "").upper().split(",")
        tickers = [ticker for ticker in asked if ticker][:MAX_TICKERS]
        return build_snapshot(get_owners(), tickers, price_source)

    return bp
