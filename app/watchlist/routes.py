"""Watchlist pages. Reads the form, calls the service, shows the result."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.watchlist.service import (
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
            flash(f"Added {item.ticker}.", "success")
        except (InvalidWatchlistItemError, DuplicateTickerError) as error:
            flash(str(error), "error")
        return redirect(url_for("watchlist.list_items"))

    @bp.post("/watchlist/<ticker>/delete")
    def delete_item(ticker):
        if service.remove_item(ticker):
            flash(f"Removed {ticker.upper()}.", "success")
        else:
            flash(f"{ticker.upper()} isn't on the watchlist.", "error")
        return redirect(url_for("watchlist.list_items"))

    return bp
