"""Alerts endpoints. Reads the JSON body, calls the service, answers with JSON."""

from flask import Blueprint, request

from app.alerts.service import InvalidRuleError
from app.ports import WatchlistUnavailable

WATCHLIST_DOWN = "The watchlist can't be reached right now"


def rule_json(rule) -> dict:
    return {
        "id": rule["id"],
        "ticker": rule["ticker"],
        "condition": rule["condition"],
        "threshold": rule["threshold"],
        "created_at": rule["created_at"],
        # active, dormant, fired, or unknown when the watchlist did not answer
        "status": rule["status"],
    }


def event_json(event) -> dict:
    return {
        "id": event["id"],
        "rule_id": event["rule_id"],  # null once the rule is deleted
        "ticker": event["ticker"],
        "condition": event["condition"],
        "threshold": event["threshold"],
        "observed_price": event["observed_price"],
        "triggered_at": event["triggered_at"],
    }


def create_alerts_blueprint(get_service, get_checking_service) -> Blueprint:
    """get_service is enough to list and create rules. get_checking_service also
    asks the watchlist for prices, which only a check needs."""
    bp = Blueprint("alerts", __name__)

    @bp.get("/alerts")
    def list_rules():
        service = get_service()
        # Rules are our own data, so this answers even when the watchlist is down.
        rules = service.list_rules()
        return {
            "rules": [rule_json(rule) for rule in rules],
            "watchlist_available": service.watchlist_available,
        }

    @bp.post("/alerts")
    def add_rule():
        body = request.get_json(silent=True)
        body = body if isinstance(body, dict) else {}
        ticker, condition = body.get("ticker"), body.get("condition")
        try:
            rule = get_service().create_rule(
                ticker if isinstance(ticker, str) else "",
                condition if isinstance(condition, str) else "",
                body.get("threshold"),
            )
        except InvalidRuleError as error:
            return {"error": str(error)}, 400
        except WatchlistUnavailable:
            # We can't check the ticker, so the service stored nothing.
            error = f"{WATCHLIST_DOWN}, so the rule was not saved. Try again in a moment."
            return {"error": error}, 503
        return rule_json(rule), 201

    @bp.delete("/alerts/<int:rule_id>")
    def delete_rule(rule_id):
        if get_service().delete_rule(rule_id):
            return "", 204
        return {"error": "That rule doesn't exist."}, 404

    @bp.get("/alerts/events")
    def list_events():
        service = get_service()
        return {
            "events": [event_json(event) for event in service.list_events()],
            "count": service.count_events(),
        }

    @bp.post("/alerts/evaluate")
    def evaluate():
        service = get_checking_service()
        fired = service.evaluate_all()
        if not service.watchlist_available:
            error = (
                f"{WATCHLIST_DOWN}, so the check did not finish. "
                "Rules that were not checked stay active."
            )
            return {"error": error}, 503
        return {
            "fired": [rule_json(dict(rule, status="fired")) for rule in fired],
            # Tickers with no fresh price. Their rules stay active.
            "unavailable_tickers": sorted(service.unavailable_tickers),
        }

    return bp
