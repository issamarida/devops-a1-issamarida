"""Watchlist endpoints. Reads the JSON body, calls the service, answers with JSON."""

from dataclasses import asdict

from flask import Blueprint, request

from app.watchlist.service import (
    DuplicateTickerError,
    InvalidWatchlistItemError,
)


def item_json(item) -> dict:
    body = asdict(item)
    del body["owner_id"]  # the caller already knows whose list this is
    return body


def text(body, name) -> str:
    """A JSON field as text. Anything that is not text counts as empty."""
    value = body.get(name) if isinstance(body, dict) else None
    return value if isinstance(value, str) else ""


def create_watchlist_blueprint(get_service) -> Blueprint:
    bp = Blueprint("watchlist", __name__)

    @bp.get("/watchlist")
    def list_items():
        return {"items": [item_json(item) for item in get_service().list_items()]}

    @bp.post("/watchlist")
    def add_item():
        body = request.get_json(silent=True)
        try:
            item = get_service().add_item(
                text(body, "ticker"), text(body, "name"), text(body, "notes")
            )
        except InvalidWatchlistItemError as error:
            return {"error": str(error)}, 400
        except DuplicateTickerError as error:
            return {"error": str(error)}, 409
        return item_json(item), 201

    @bp.delete("/watchlist/<ticker>")
    def delete_item(ticker):
        if get_service().remove_item(ticker):
            return "", 204
        return {"error": f"{ticker.upper()} isn't on the watchlist."}, 404

    return bp
