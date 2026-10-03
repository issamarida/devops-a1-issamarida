"""Alert rules: check new rules, then fire the ones whose price condition is met.

Only talks to the watchlist and to prices through the interfaces in app.ports.
"""

import logging
import math

from app.alerts.repository import AlertRepository, RuleLimitReached
from app.alerts.rules import is_triggered
from app.ports import PriceSource, PriceUnavailable, WatchlistReader

logger = logging.getLogger(__name__)

CONDITIONS = ("above", "below")


class InvalidRuleError(ValueError):
    pass


class AlertService:
    def __init__(
        self,
        repository: AlertRepository,
        price_source: PriceSource,
        watchlist_reader: WatchlistReader,
    ):
        self.repository = repository
        self.price_source = price_source
        self.watchlist_reader = watchlist_reader
        self.unavailable_tickers = set()

    def create_rule(self, ticker: str, condition: str, threshold) -> dict:
        ticker = ticker.strip().upper()
        if ticker == "":
            raise InvalidRuleError("Ticker can't be blank.")
        if condition not in CONDITIONS:
            raise InvalidRuleError("Condition must be above or below.")
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            raise InvalidRuleError("Threshold must be a number.")
        if not math.isfinite(threshold) or threshold <= 0:
            raise InvalidRuleError("Threshold must be a number greater than 0.")
        if not self.watchlist_reader.is_watched(ticker):
            raise InvalidRuleError(
                f"{ticker} isn't on the watchlist. Add it there first."
            )

        try:
            rule_id = self.repository.add_rule(ticker, condition, threshold)
        except RuleLimitReached as error:
            raise InvalidRuleError(str(error)) from None
        return next(rule for rule in self.list_rules() if rule["id"] == rule_id)

    def delete_rule(self, rule_id) -> bool:
        return self.repository.delete_rule(rule_id)

    def list_rules(self) -> list[dict]:
        rules = self.repository.list_rules()
        for rule in rules:
            rule["status"] = (
                "fired"
                if not rule["is_active"]
                else "active"
                if self.watchlist_reader.is_watched(rule["ticker"])
                else "dormant"
            )
        return rules

    def list_events(self) -> list[dict]:
        return self.repository.list_events()

    def count_events(self):
        return self.repository.count_events()

    def evaluate_all(self) -> list[dict]:
        """Check every active rule once and return the rules that fired."""
        self.unavailable_tickers = set()
        fired = []
        prices = {}  # ticker -> price, or None if unavailable. One lookup per ticker per run.

        for rule in self.repository.list_active_rules():
            ticker = rule["ticker"]
            # Dormant: the ticker was removed from the watchlist. Keep the rule, skip it.
            if not self.watchlist_reader.is_watched(ticker):
                continue

            if ticker not in prices:
                try:
                    price = self.price_source.get_price(ticker)
                    if (
                        type(price) not in (float, int)
                        or not math.isfinite(price)
                        or price <= 0
                    ):
                        raise PriceUnavailable(ticker)
                    prices[ticker] = price
                except PriceUnavailable:
                    logger.warning(
                        "Price unavailable for %s, skipping its rules", ticker
                    )
                    prices[ticker] = None
                    self.unavailable_tickers.add(ticker)

            price = prices[ticker]
            if price is None:
                continue
            if is_triggered(rule["condition"], rule["threshold"], price):
                # fire_rule returns False if another thread already fired it
                if self.repository.fire_rule(rule, price):
                    fired.append(rule)

        return fired
