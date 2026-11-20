"""AllOwners: what the poller runs for every account."""

import logging

from app.alerts.checker import AllOwners
from app.alerts.repository import (
    AlertRepository,
    active_rule_tickers,
    owners_with_active_rules,
)
from app.alerts.service import AlertService
from app.alerts.watchlist_client import RemoteWatchlist, Snapshot
from app.ports import WatchlistUnavailable
from conftest import ANSWER


def make_checker(db_path, fetch):
    made = []  # the tickers each new snapshot was asked for

    def new_snapshot(tickers=()):
        made.append(list(tickers))
        return Snapshot(fetch)

    def service_for(owner_id, snapshot):
        watchlist = RemoteWatchlist(snapshot, owner_id)
        return AlertService(AlertRepository(db_path, owner_id), watchlist, watchlist)

    return AllOwners(db_path, new_snapshot, service_for), made


def test_owners_and_tickers_come_from_active_rules_only(db_path):
    AlertRepository(db_path, 8).add_rule("TSLA", "above", 250)
    AlertRepository(db_path, 7).add_rule("MSFT", "above", 1)
    AlertRepository(db_path, 7).add_rule("AAPL", "above", 190)
    AlertRepository(db_path, 7).add_rule("AAPL", "below", 100)
    # A fired rule and old data without an owner are not checked.
    fired = AlertRepository(db_path, 9)
    fired.fire_rule(fired.get_rule(fired.add_rule("NFLX", "above", 1)), 2.0)
    AlertRepository(db_path, 0).add_rule("IBM", "above", 1)

    assert owners_with_active_rules(db_path) == [7, 8]
    assert active_rule_tickers(db_path) == ["AAPL", "MSFT", "TSLA"]


def test_one_snapshot_serves_every_account(db_path):
    AlertRepository(db_path, 7).add_rule("AAPL", "above", 190)
    AlertRepository(db_path, 8).add_rule("TSLA", "above", 250)
    fetches = []
    checker, made = make_checker(db_path, lambda: fetches.append(1) or ANSWER)

    fired = checker.evaluate_all()

    assert sorted(rule["ticker"] for rule in fired) == ["AAPL", "TSLA"]
    assert made == [["AAPL", "TSLA"]]
    assert len(fetches) == 1


def test_nothing_is_fetched_when_no_rule_is_active(db_path):
    checker, made = make_checker(db_path, lambda: ANSWER)

    assert checker.evaluate_all() == []
    assert made == []


def test_an_unreachable_watchlist_skips_the_run_and_keeps_every_rule(db_path, caplog):
    AlertRepository(db_path, 7).add_rule("AAPL", "above", 190)
    AlertRepository(db_path, 8).add_rule("TSLA", "above", 250)

    def fetch():
        raise WatchlistUnavailable("down")

    checker, _ = make_checker(db_path, fetch)
    caplog.set_level(logging.WARNING)

    assert checker.evaluate_all() == []

    assert [r.getMessage() for r in caplog.records] == ["Watchlist unavailable, skipping this check"]
    assert owners_with_active_rules(db_path) == [7, 8]


def test_one_accounts_failure_does_not_stop_the_others(db_path, caplog):
    AlertRepository(db_path, 7).add_rule("AAPL", "above", 190)
    AlertRepository(db_path, 8).add_rule("TSLA", "above", 250)
    checker, _ = make_checker(db_path, lambda: ANSWER)
    working = checker.service_for

    def service_for(owner_id, snapshot):
        if owner_id == 7:
            raise RuntimeError("broken for account 7")
        return working(owner_id, snapshot)

    checker.service_for = service_for
    caplog.set_level(logging.ERROR)

    fired = checker.evaluate_all()

    assert [rule["ticker"] for rule in fired] == ["TSLA"]
    assert "Alert check failed for an account" in caplog.text
