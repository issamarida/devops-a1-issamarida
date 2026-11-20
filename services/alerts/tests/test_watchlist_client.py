"""The alerts side of the seam: one HTTP request to the watchlist, with a timeout.

The unit tests mock requests.get. The cross-seam tests at the bottom replace the
watchlist service with a stub: a real HTTP server on localhost (tests/conftest.py).
"""

import time
from unittest.mock import Mock, patch

import pytest
import requests

from app.alerts.repository import AlertRepository
from app.alerts.service import AlertService
from app.alerts.watchlist_client import (
    RemoteWatchlist,
    Snapshot,
    fetch_snapshot,
)
from app.ports import PriceUnavailable, WatchlistUnavailable
from app.tokens import issue_service_token
from conftest import ANSWER, TEST_TOKEN_SECRET

BASE_URL = "http://watchlist:8001"
GET = "app.alerts.watchlist_client.requests.get"


def fake_response(status_code=200, payload=None, json_error=None):
    response = Mock()
    response.status_code = status_code
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = payload
    return response


# fetch_snapshot


def test_fetch_snapshot_returns_the_answer():
    with patch(GET) as get:
        get.return_value = fake_response(payload=ANSWER)
        assert fetch_snapshot(BASE_URL, 2.0) == ANSWER


def test_fetch_snapshot_sends_one_get_with_the_timeout_and_the_token():
    with patch(GET) as get:
        get.return_value = fake_response(payload=ANSWER)
        fetch_snapshot(BASE_URL + "/", 1.5, "the-token")

    get.assert_called_once_with(
        BASE_URL + "/internal/snapshot",
        params={},
        headers={"Authorization": "Bearer the-token"},
        timeout=1.5,
    )


def test_fetch_snapshot_asks_for_each_ticker_once_in_a_fixed_order():
    with patch(GET) as get:
        get.return_value = fake_response(payload=ANSWER)
        fetch_snapshot(BASE_URL, 1.5, "the-token", ["MSFT", "AAPL", "MSFT"])

    assert get.call_args.kwargs["params"] == {"tickers": "AAPL,MSFT"}


@pytest.mark.parametrize(
    "error",
    [requests.Timeout("slow"), requests.ConnectionError("refused")],
)
def test_fetch_snapshot_fails_cleanly_when_nothing_answers(error):
    with patch(GET, side_effect=error):
        with pytest.raises(WatchlistUnavailable) as raised:
            fetch_snapshot(BASE_URL, 2.0)

    # The requests error and its text are dropped, not chained.
    assert raised.value.__cause__ is None
    assert "slow" not in str(raised.value) and "refused" not in str(raised.value)


@pytest.mark.parametrize("status_code", [401, 404, 500, 503])
def test_fetch_snapshot_rejects_any_status_but_200(status_code):
    with patch(GET) as get:
        get.return_value = fake_response(status_code=status_code, payload=ANSWER)
        with pytest.raises(WatchlistUnavailable, match=str(status_code)):
            fetch_snapshot(BASE_URL, 2.0)


def test_fetch_snapshot_rejects_a_body_that_is_not_json():
    with patch(GET) as get:
        get.return_value = fake_response(json_error=ValueError("not json"))
        with pytest.raises(WatchlistUnavailable):
            fetch_snapshot(BASE_URL, 2.0)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"owners": {}},
        {"prices": {}},
        {"owners": [], "prices": {}},
        {"owners": {}, "prices": []},
        {"owners": {"7": "AAPL"}, "prices": {}},
    ],
)
def test_fetch_snapshot_rejects_the_wrong_shape(payload):
    with patch(GET) as get:
        get.return_value = fake_response(payload=payload)
        with pytest.raises(WatchlistUnavailable):
            fetch_snapshot(BASE_URL, 2.0)


# Snapshot


def test_snapshot_fetches_on_first_use_and_only_once():
    fetch = Mock(return_value=ANSWER)
    snapshot = Snapshot(fetch)
    assert fetch.call_count == 0

    assert snapshot.get() == ANSWER
    assert snapshot.get() == ANSWER
    assert fetch.call_count == 1


def test_snapshot_remembers_a_failure_and_does_not_wait_again():
    fetch = Mock(side_effect=WatchlistUnavailable("down"))
    snapshot = Snapshot(fetch)

    for _ in range(3):
        with pytest.raises(WatchlistUnavailable):
            snapshot.get()
    assert fetch.call_count == 1


# RemoteWatchlist


def test_is_watched_only_sees_its_own_account():
    snapshot = Snapshot(lambda: ANSWER)

    assert RemoteWatchlist(snapshot, 7).is_watched("AAPL") is True
    assert RemoteWatchlist(snapshot, 7).is_watched("TSLA") is False
    assert RemoteWatchlist(snapshot, 8).is_watched("TSLA") is True
    # An account with no watchlist is simply not in the answer.
    assert RemoteWatchlist(snapshot, 9).is_watched("AAPL") is False


def test_get_price_returns_a_float():
    watchlist = RemoteWatchlist(Snapshot(lambda: ANSWER), 8)

    price = watchlist.get_price("TSLA")

    assert price == 300.0
    assert type(price) is float


@pytest.mark.parametrize("price", [None, True, 0, -5, "200", float("nan")])
def test_get_price_rejects_anything_that_is_not_a_real_price(price):
    answer = {"owners": {"7": ["AAPL"]}, "prices": {"AAPL": price}}
    watchlist = RemoteWatchlist(Snapshot(lambda: answer), 7)

    with pytest.raises(PriceUnavailable):
        watchlist.get_price("AAPL")


def test_get_price_for_a_ticker_that_is_not_in_the_answer():
    watchlist = RemoteWatchlist(Snapshot(lambda: ANSWER), 7)

    with pytest.raises(PriceUnavailable):
        watchlist.get_price("NFLX")


def test_both_calls_fail_when_the_watchlist_is_down():
    def fetch():
        raise WatchlistUnavailable("down")

    watchlist = RemoteWatchlist(Snapshot(fetch), 7)

    with pytest.raises(WatchlistUnavailable):
        watchlist.is_watched("AAPL")
    with pytest.raises(WatchlistUnavailable):
        watchlist.get_price("AAPL")


# Across the seam: the real AlertService and AlertRepository call a stub watchlist
# service over real HTTP. Nothing is mocked from here on.


def alerts_for(db_path, url, owner_id=7, timeout_seconds=2.0, tickers=()):
    """An AlertService wired the way create_app wires it for one request."""
    token = issue_service_token(TEST_TOKEN_SECRET)
    watchlist = RemoteWatchlist(
        Snapshot(lambda: fetch_snapshot(url, timeout_seconds, token, tickers)), owner_id
    )
    return AlertService(AlertRepository(db_path, owner_id), watchlist, watchlist)


def test_a_rule_is_created_and_fires_across_the_seam(db_path, stub):
    rule = alerts_for(db_path, stub.url).create_rule("aapl", "above", 190)
    assert rule["status"] == "active"
    # The watched check and the status of the new rule share one request.
    assert stub.paths == ["/internal/snapshot"]

    service = alerts_for(db_path, stub.url, tickers=["AAPL"])
    fired = service.evaluate_all()

    assert [r["id"] for r in fired] == [rule["id"]]
    assert service.list_events()[0]["observed_price"] == 200.0
    # One more request for the whole check: watched tickers and prices together.
    assert len(stub.paths) == 2
    assert stub.asked == ["", "AAPL"]


def test_the_stub_refuses_a_caller_without_the_service_token(db_path, stub):
    with pytest.raises(WatchlistUnavailable, match="401"):
        fetch_snapshot(stub.url, 2.0, "not-a-token")


def test_a_change_in_the_watchlist_is_seen_on_the_next_request(db_path, stub):
    alerts_for(db_path, stub.url).create_rule("AAPL", "above", 190)

    stub.answer = {"owners": {"7": []}, "prices": {}}

    service = alerts_for(db_path, stub.url)
    assert service.list_rules()[0]["status"] == "dormant"
    assert service.evaluate_all() == []


def test_a_ticker_watched_by_another_account_is_refused(db_path, stub):
    with pytest.raises(ValueError, match="isn't on the watchlist"):
        alerts_for(db_path, stub.url, owner_id=7).create_rule("TSLA", "above", 100)


def test_a_ticker_without_a_price_keeps_its_rule_active(db_path, stub):
    alerts_for(db_path, stub.url).create_rule("MSFT", "above", 1)
    service = alerts_for(db_path, stub.url)

    assert service.evaluate_all() == []

    assert service.unavailable_tickers == {"MSFT"}
    assert service.repository.list_rules()[0]["is_active"] == 1


@pytest.mark.parametrize("failure", ["stopped", "too slow"])
def test_alerts_keeps_serving_its_own_data_without_the_watchlist(
    db_path, stub, failure
):
    alerts_for(db_path, stub.url).create_rule("AAPL", "above", 190)
    alerts_for(db_path, stub.url).create_rule("AAPL", "above", 250)
    alerts_for(db_path, stub.url).evaluate_all()

    if failure == "stopped":
        stub.stop()
    else:
        stub.delay_seconds = 1.0

    def alerts():
        return alerts_for(db_path, stub.url, timeout_seconds=0.2)

    # Listing still works and comes back fast. The fired rule is our own data.
    started = time.monotonic()
    service = alerts()
    rules = service.list_rules()
    assert time.monotonic() - started < 0.8
    assert [rule["status"] for rule in rules] == ["fired", "unknown"]
    assert service.watchlist_available is False

    # History and delete never needed the watchlist.
    assert len(service.list_events()) == 1
    assert service.delete_rule(rules[0]["id"]) is True

    # A new rule is refused with a clear error and nothing is stored.
    with pytest.raises(WatchlistUnavailable, match="did not answer"):
        alerts().create_rule("AAPL", "below", 100)
    assert len(service.repository.list_rules()) == 1

    # The check is skipped. The rule stays active and nothing fires.
    checker = alerts()
    assert checker.evaluate_all() == []
    assert checker.watchlist_available is False
    assert service.repository.list_rules()[0]["is_active"] == 1
    assert len(service.list_events()) == 1
