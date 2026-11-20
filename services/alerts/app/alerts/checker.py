"""What the poller runs: one check for every account, with one call to the watchlist."""

import logging

from app.alerts.repository import active_rule_tickers, owners_with_active_rules
from app.ports import WatchlistUnavailable

logger = logging.getLogger(__name__)


class AllOwners:
    def __init__(self, db_path, new_snapshot, service_for):
        self.db_path = db_path
        self.new_snapshot = new_snapshot  # tickers -> a Snapshot that is not fetched yet
        self.service_for = service_for  # (owner_id, snapshot) -> AlertService

    def evaluate_all(self) -> list[dict]:
        owners = owners_with_active_rules(self.db_path)
        if not owners:
            # Nothing to check, so the watchlist is not called at all.
            return []

        # One request covers every account and every price this run needs.
        snapshot = self.new_snapshot(active_rule_tickers(self.db_path))
        try:
            snapshot.get()
        except WatchlistUnavailable:
            logger.warning("Watchlist unavailable, skipping this check")
            return []

        fired = []
        for owner_id in owners:
            try:
                fired.extend(self.service_for(owner_id, snapshot).evaluate_all())
            except Exception:
                # One account's failure must not stop the others.
                logger.exception("Alert check failed for an account")
        return fired
