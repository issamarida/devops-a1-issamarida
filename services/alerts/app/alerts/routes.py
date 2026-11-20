"""Alerts pages. Reads the form, calls the service, shows the result."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.alerts.service import CONDITIONS, InvalidRuleError
from app.ports import WatchlistUnavailable

WATCHLIST_DOWN = "The watchlist can't be reached right now"


def create_alerts_blueprint(get_service) -> Blueprint:
    bp = Blueprint("alerts", __name__)

    @bp.get("/alerts")
    def list_rules():
        service = get_service()
        return render_template(
            "alerts.html",
            # Rules and history are our own data, so the page loads either way.
            rules=service.list_rules(),
            events=service.list_events(),
            conditions=CONDITIONS,
            watchlist_down=not service.watchlist_available,
        )

    @bp.post("/alerts")
    def add_rule():
        try:
            rule = get_service().create_rule(
                request.form.get("ticker", ""),
                request.form.get("condition", ""),
                request.form.get("threshold", ""),
            )
            flash(f"Added a rule for {rule['ticker']}.", "success")
        except InvalidRuleError as error:
            flash(str(error), "error")
        except WatchlistUnavailable:
            # We can't check the ticker, so the service stored nothing.
            flash(
                f"{WATCHLIST_DOWN}, so the rule was not saved. Try again in a moment.",
                "error",
            )
        return redirect(url_for("alerts.list_rules"))

    @bp.post("/alerts/<int:rule_id>/delete")
    def delete_rule(rule_id):
        if get_service().delete_rule(rule_id):
            flash("Deleted the rule.", "success")
        else:
            flash("That rule doesn't exist.", "error")
        return redirect(url_for("alerts.list_rules"))

    @bp.post("/alerts/evaluate")
    def evaluate():
        service = get_service()
        fired = service.evaluate_all()
        if not service.watchlist_available:
            flash(
                f"{WATCHLIST_DOWN}, so the check did not finish. "
                "Rules that were not checked stay active.",
                "error",
            )
            return redirect(url_for("alerts.list_rules"))
        message = f"Checked the rules. {len(fired)} fired."
        waiting = len(service.unavailable_tickers)
        if waiting:
            message += f" {waiting} ticker{'s' if waiting > 1 else ''} had no fresh quote yet; those rules stay active."
        flash(message, "success")
        return redirect(url_for("alerts.list_rules"))

    return bp
