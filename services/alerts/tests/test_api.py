"""Drives the real alerts service over its JSON API.

The watchlist service is replaced by the stub in tests/conftest.py, a real HTTP
server on localhost, so every test here crosses the seam the way production does.
"""

import logging
import time

import pytest

from app import create_app
from app.config import load_config
from conftest import user_headers

UI_ORIGIN = "http://localhost:8080"
ALICE = user_headers(7, "alice")
BOB = user_headers(8, "bob")
RULE = {"ticker": "AAPL", "condition": "above", "threshold": 190}


@pytest.fixture
def app(stub, monkeypatch):
    monkeypatch.setenv("WATCHLIST_URL", stub.url)
    monkeypatch.setenv("WATCHLIST_TIMEOUT_SECONDS", "0.3")
    return create_app(load_config())


@pytest.fixture
def client(app):
    return app.test_client()


def statuses(client, headers=ALICE):
    return [rule["status"] for rule in client.get("/alerts", headers=headers).get_json()["rules"]]


# Access


def test_every_alerts_endpoint_needs_a_token_but_health_is_public(client, stub):
    assert client.get("/health").status_code == 200
    for method, path in [
        ("get", "/alerts"),
        ("post", "/alerts"),
        ("delete", "/alerts/1"),
        ("get", "/alerts/events"),
        ("post", "/alerts/evaluate"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 401
        assert response.get_json() == {"error": "Sign in to continue."}
    assert stub.paths == []


@pytest.mark.parametrize(
    "headers",
    [
        user_headers(7, secret="another-test-only-secret-also-not-real"),
        user_headers(7, lifetime=-1),
        {"Authorization": "Bearer not-a-token"},
    ],
    ids=["signed with another secret", "expired", "not a token"],
)
def test_a_token_the_watchlist_did_not_sign_or_that_expired_is_refused(client, headers):
    assert client.get("/alerts", headers=headers).status_code == 401


def test_the_service_token_is_not_a_user(client):
    from app.tokens import issue_service_token
    from conftest import TEST_TOKEN_SECRET

    headers = {"Authorization": "Bearer " + issue_service_token(TEST_TOKEN_SECRET)}

    assert client.get("/alerts", headers=headers).status_code == 401


# The cross-seam flow, with the watchlist up


def test_a_rule_is_created_checked_and_lands_in_the_history(client, stub):
    created = client.post("/alerts", json=RULE, headers=ALICE)

    assert created.status_code == 201
    rule = created.get_json()
    assert rule["status"] == "active" and rule["ticker"] == "AAPL"
    assert set(rule) == {"id", "ticker", "condition", "threshold", "created_at", "status"}

    checked = client.post("/alerts/evaluate", headers=ALICE)

    assert checked.status_code == 200
    body = checked.get_json()
    assert [fired["id"] for fired in body["fired"]] == [rule["id"]]
    assert body["fired"][0]["status"] == "fired"
    assert body["unavailable_tickers"] == []
    history = client.get("/alerts/events", headers=ALICE).get_json()
    assert history["count"] == 1
    assert history["events"][0]["observed_price"] == 200.0
    assert history["events"][0]["rule_id"] == rule["id"]
    assert statuses(client) == ["fired"]


def test_each_operation_is_one_request_and_only_a_check_asks_for_prices(client, stub):
    client.post("/alerts", json=RULE, headers=ALICE)
    client.post("/alerts", json=dict(RULE, ticker="MSFT", threshold=1), headers=ALICE)
    client.get("/alerts", headers=ALICE)
    assert stub.asked == ["", "", ""]

    client.post("/alerts/evaluate", headers=ALICE)

    # One request for the whole check, asking only for the tickers with an active rule.
    assert stub.asked == ["", "", "", "AAPL,MSFT"]
    assert stub.paths == ["/internal/snapshot"] * 4


def test_history_delete_and_an_empty_list_never_call_the_watchlist(client, stub):
    client.post("/alerts", json=RULE, headers=ALICE)
    client.post("/alerts/evaluate", headers=ALICE)
    before = len(stub.paths)

    client.get("/alerts/events", headers=ALICE)
    client.get("/alerts", headers=ALICE)  # the only rule has fired: nothing to ask
    client.get("/alerts", headers=BOB)  # no rules at all
    client.delete("/alerts/1", headers=ALICE)

    assert len(stub.paths) == before


def test_a_rule_for_a_ticker_that_is_not_watched_is_refused(client):
    response = client.post("/alerts", json=dict(RULE, ticker="TSLA"), headers=ALICE)

    assert response.status_code == 400
    assert response.get_json() == {"error": "TSLA isn't on the watchlist. Add it there first."}
    # TSLA is on Bob's watchlist, not Alice's.
    assert client.post("/alerts", json=dict(RULE, ticker="TSLA"), headers=BOB).status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        None,
        [1, 2],
        {},
        {"ticker": 5, "condition": "above", "threshold": 1},
        {"ticker": "AAPL", "condition": ["above"], "threshold": 1},
        {"ticker": "AAPL", "condition": "sideways", "threshold": 1},
        {"ticker": "AAPL", "condition": "above", "threshold": "abc"},
        {"ticker": "AAPL", "condition": "above", "threshold": None},
        {"ticker": "AAPL", "condition": "above", "threshold": -5},
    ],
)
def test_a_bad_body_is_a_clean_400_and_stores_nothing(client, body):
    response = client.post("/alerts", json=body, headers=ALICE)

    assert response.status_code == 400
    assert "error" in response.get_json()
    assert statuses(client) == []


def test_accounts_only_see_and_delete_their_own_rules(client):
    rule_id = client.post("/alerts", json=RULE, headers=ALICE).get_json()["id"]
    client.post("/alerts/evaluate", headers=ALICE)

    assert client.get("/alerts", headers=BOB).get_json()["rules"] == []
    assert client.get("/alerts/events", headers=BOB).get_json() == {"events": [], "count": 0}
    assert client.delete(f"/alerts/{rule_id}", headers=BOB).status_code == 404

    assert client.delete(f"/alerts/{rule_id}", headers=ALICE).status_code == 204
    assert client.delete(f"/alerts/{rule_id}", headers=ALICE).get_json() == {
        "error": "That rule doesn't exist."
    }
    # The history outlives the rule, with no rule to point at any more.
    assert client.get("/alerts/events", headers=ALICE).get_json()["events"][0]["rule_id"] is None


def test_a_rule_goes_dormant_when_its_ticker_leaves_the_watchlist(client, stub):
    client.post("/alerts", json=RULE, headers=ALICE)

    stub.answer = {"owners": {"7": []}, "prices": {}}

    assert statuses(client) == ["dormant"]
    assert client.post("/alerts/evaluate", headers=ALICE).get_json()["fired"] == []
    assert statuses(client) == ["dormant"]


def test_a_ticker_without_a_price_is_reported_and_its_rule_stays_active(client):
    client.post("/alerts", json=dict(RULE, ticker="MSFT", threshold=1), headers=ALICE)

    body = client.post("/alerts/evaluate", headers=ALICE).get_json()

    assert body == {"fired": [], "unavailable_tickers": ["MSFT"]}
    assert statuses(client) == ["active"]


# Partial failure: the watchlist service is stopped, slow or broken (brief section 3)


def break_watchlist(stub, failure):
    if failure == "stopped":
        stub.stop()
    elif failure == "too slow":
        stub.delay_seconds = 1.0
    elif failure == "answers 500":
        stub.status = 500
    else:
        stub.answer = b"<html>not json</html>"


FAILURES = ["stopped", "too slow", "answers 500", "answers nonsense"]


@pytest.mark.parametrize("failure", FAILURES)
def test_alerts_keeps_serving_its_own_data_when_the_watchlist_fails(client, stub, failure):
    client.post("/alerts", json=RULE, headers=ALICE)
    client.post("/alerts", json=dict(RULE, threshold=250), headers=ALICE)
    client.post("/alerts/evaluate", headers=ALICE)
    break_watchlist(stub, failure)

    # The list still answers, quickly. What we cannot know is marked unknown.
    started = time.monotonic()
    listed = client.get("/alerts", headers=ALICE)
    assert time.monotonic() - started < 1.0
    assert listed.status_code == 200
    body = listed.get_json()
    assert [rule["status"] for rule in body["rules"]] == ["fired", "unknown"]
    assert body["watchlist_available"] is False

    # History and delete are our own data and never needed the watchlist.
    assert client.get("/alerts/events", headers=ALICE).get_json()["count"] == 1
    assert client.delete(f"/alerts/{body['rules'][0]['id']}", headers=ALICE).status_code == 204
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("failure", FAILURES)
def test_a_new_rule_is_refused_with_a_clear_error_when_the_watchlist_fails(client, stub, failure):
    break_watchlist(stub, failure)

    started = time.monotonic()
    response = client.post("/alerts", json=RULE, headers=ALICE)

    assert time.monotonic() - started < 1.0
    assert response.status_code == 503
    assert response.get_json() == {
        "error": "The watchlist can't be reached right now, so the rule was not saved. "
        "Try again in a moment."
    }
    assert "Traceback" not in response.get_data(as_text=True)
    assert statuses(client) == []


@pytest.mark.parametrize("failure", FAILURES)
def test_a_check_is_skipped_and_nothing_fires_when_the_watchlist_fails(client, stub, failure):
    client.post("/alerts", json=RULE, headers=ALICE)
    break_watchlist(stub, failure)

    response = client.post("/alerts/evaluate", headers=ALICE)

    assert response.status_code == 503
    assert "so the check did not finish" in response.get_json()["error"]
    # No rule fired on a price nobody could confirm.
    assert client.get("/alerts/events", headers=ALICE).get_json() == {"events": [], "count": 0}


def test_alerts_recovers_by_itself_when_the_watchlist_is_back(client, stub):
    client.post("/alerts", json=RULE, headers=ALICE)
    stub.status = 500
    assert statuses(client) == ["unknown"]

    stub.status = 200

    assert statuses(client) == ["active"]
    assert len(client.post("/alerts/evaluate", headers=ALICE).get_json()["fired"]) == 1


# The poller's check for every account


def test_the_poller_checks_every_account_with_one_request(app, client, stub):
    client.post("/alerts", json=RULE, headers=ALICE)
    client.post("/alerts", json=dict(RULE, ticker="TSLA", threshold=250), headers=BOB)
    before = len(stub.paths)

    fired = app.extensions["alert_service"].evaluate_all()

    assert sorted(rule["ticker"] for rule in fired) == ["AAPL", "TSLA"]
    assert len(stub.paths) == before + 1
    assert stub.asked[-1] == "AAPL,TSLA"
    assert statuses(client, ALICE) == ["fired"] and statuses(client, BOB) == ["fired"]


def test_the_poller_does_not_call_the_watchlist_when_no_rule_is_active(app, client, stub):
    assert app.extensions["alert_service"].evaluate_all() == []
    client.post("/alerts", json=RULE, headers=ALICE)
    app.extensions["alert_service"].evaluate_all()  # the rule fires
    before = len(stub.paths)

    assert app.extensions["alert_service"].evaluate_all() == []

    assert len(stub.paths) == before


def test_the_poller_skips_the_check_with_one_warning_when_the_watchlist_is_down(
    app, client, stub, caplog
):
    client.post("/alerts", json=RULE, headers=ALICE)
    client.post("/alerts", json=dict(RULE, ticker="TSLA"), headers=BOB)
    stub.stop()
    caplog.set_level(logging.WARNING)

    assert app.extensions["alert_service"].evaluate_all() == []

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == ["Watchlist unavailable, skipping this check"]
    assert statuses(client, ALICE) == ["unknown"]


# CORS and headers


def test_cors_allows_the_ui_origin_and_nobody_else(client):
    def preflight(origin):
        return client.options(
            "/alerts",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    allowed = preflight(UI_ORIGIN)
    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == UI_ORIGIN
    assert "authorization" in allowed.headers["Access-Control-Allow-Headers"].lower()
    assert "Access-Control-Allow-Origin" not in preflight("https://evil.example").headers
    # An error answer still carries the header, or the browser hides it from the UI.
    refused = client.get("/alerts", headers={"Origin": UI_ORIGIN})
    assert refused.status_code == 401
    assert refused.headers["Access-Control-Allow-Origin"] == UI_ORIGIN


def test_headers_and_request_size(client):
    response = client.get("/alerts", headers=ALICE)

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    too_big = client.post("/alerts", json={"ticker": "x" * 20000}, headers=ALICE)
    assert too_big.status_code == 413 and "error" in too_big.get_json()
