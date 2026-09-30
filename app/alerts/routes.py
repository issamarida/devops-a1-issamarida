"""Alerts pages. Reads the form, calls the service, shows the result."""

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.alerts.service import CONDITIONS, AlertService, InvalidRuleError


def create_alerts_blueprint(service: AlertService) -> Blueprint:
    bp = Blueprint("alerts", __name__)

    @bp.get("/alerts")
    def list_rules():
        return render_template(
            "alerts.html",
            rules=service.list_rules(),
            events=service.list_events(),
            conditions=CONDITIONS,
            using_demo_prices=current_app.config["USING_DEMO_PRICES"],
        )

    @bp.post("/alerts")
    def add_rule():
        try:
            rule = service.create_rule(
                request.form.get("ticker", ""),
                request.form.get("condition", ""),
                request.form.get("threshold", ""),
            )
            flash(f"Added a rule for {rule['ticker']}.", "success")
        except InvalidRuleError as error:
            flash(str(error), "error")
        return redirect(url_for("alerts.list_rules"))

    @bp.post("/alerts/<int:rule_id>/delete")
    def delete_rule(rule_id):
        if service.delete_rule(rule_id):
            flash("Deleted the rule.", "success")
        else:
            flash("That rule doesn't exist.", "error")
        return redirect(url_for("alerts.list_rules"))

    @bp.post("/alerts/evaluate")
    def evaluate():
        fired = service.evaluate_all()
        flash(f"Checked the rules. {len(fired)} fired.", "success")
        return redirect(url_for("alerts.list_rules"))

    return bp
