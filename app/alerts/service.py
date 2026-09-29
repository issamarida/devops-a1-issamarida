"""Alert rules: check new rules, then fire the ones whose price condition is met.

Only talks to the watchlist and to prices through the interfaces in app.ports.
"""

import logging
import math

from app.alerts.repository import AlertRepository
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
            raise InvalidRuleError(f"{ticker} isn't on the watchlist. Add it there first.")

        rule_id = self.repository.add_rule(ticker, condition, threshold)
        return self.repository.get_rule(rule_id)

    def delete_rule(self, rule_id) -> bool:
        return self.repository.delete_rule(rule_id)

    def list_rules(self) -> list[dict]:
        return self.repository.list_rules()

    def list_events(self) -> list[dict]:
        return self.repository.list_events()

    def evaluate_all(self) -> list[dict]:
        """Check every active rule once and return the rules that fired."""
        fired = []
        prices = {}  # ticker -> price, or None if unavailable. One lookup per ticker per run.

        for rule in self.repository.list_active_rules():
            ticker = rule["ticker"]
            # Dormant: the ticker was removed from the watchlist. Keep the rule, skip it.
            if not self.watchlist_reader.is_watched(ticker):
                continue

            if ticker not in prices:
                try:
                    prices[ticker] = self.price_source.get_price(ticker)
                except PriceUnavailable:
                    logger.warning("Price unavailable for %s, skipping its rules", ticker)
                    prices[ticker] = None

            price = prices[ticker]
            if price is None:
                continue
            if is_triggered(rule["condition"], rule["threshold"], price):
                # fire_rule returns False if another thread already fired it
                if self.repository.fire_rule(rule, price):
                    fired.append(rule)

        return fired
