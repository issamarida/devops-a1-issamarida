"""Watchlist pages. Reads the form, calls the service, shows the result."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.watchlist.service import (
    DuplicateTickerError,
    InvalidWatchlistItemError,
)


def create_watchlist_blueprint(get_service) -> Blueprint:
    bp = Blueprint("watchlist", __name__)

    @bp.get("/watchlist")
    def list_items():
        return render_template("watchlist.html", items=get_service().list_items())

    @bp.post("/watchlist")
    def add_item():
        try:
            item = get_service().add_item(
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
        if get_service().remove_item(ticker):
            flash(f"Removed {ticker.upper()}.", "success")
        else:
            flash(f"{ticker.upper()} isn't on the watchlist.", "error")
        return redirect(url_for("watchlist.list_items"))

    return bp
