"""HTTP layer for the watchlist: parses forms, calls the service, renders."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from pricewatch.watchlist.service import (
    DuplicateTickerError,
    InvalidWatchlistItemError,
    WatchlistService,
)


def create_watchlist_blueprint(service: WatchlistService) -> Blueprint:
    bp = Blueprint("watchlist", __name__)

    @bp.get("/watchlist")
    def list_items():
        return render_template("watchlist.html", items=service.list_items())

    @bp.post("/watchlist")
    def add_item():
        try:
            item = service.add_item(
                request.form.get("ticker", ""),
                request.form.get("name", ""),
                request.form.get("notes", ""),
            )
        except (InvalidWatchlistItemError, DuplicateTickerError) as exc:
            flash(str(exc), "error")
        else:
            flash(f"Added {item.ticker} to the watchlist.", "success")
        return redirect(url_for("watchlist.list_items"))

    @bp.post("/watchlist/<ticker>/delete")
    def delete_item(ticker):
        if service.remove_item(ticker):
            flash(f"Removed {ticker.upper()} from the watchlist.", "success")
        else:
            flash(f"{ticker.upper()} is not on the watchlist.", "error")
        return redirect(url_for("watchlist.list_items"))

    return bp
