"""Drives the real Flask app over its JSON API: watchlist, prices and the snapshot."""

import time
from unittest.mock import Mock, patch

import jwt

from app import create_app
from app.config import load_config
from conftest import TEST_TOKEN_SECRET


def service_headers():
    now = int(time.time())
    claims = {"sub": "alerts", "scope": "snapshot", "iat": now, "exp": now + 60}
    token = jwt.encode(claims, TEST_TOKEN_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def add(client, headers, ticker, name="A company"):
    return client.post("/watchlist", json={"ticker": ticker, "name": name}, headers=headers)


# The watchlist


def test_an_asset_is_added_listed_and_removed(client, sign_up):
    alice = sign_up("alice")

    created = client.post(
        "/watchlist",
        json={"ticker": " aapl ", "name": "Apple", "notes": "Core holding"},
        headers=alice,
    )

    assert created.status_code == 201
    item = created.get_json()
    assert item["ticker"] == "AAPL" and item["notes"] == "Core holding"
    assert set(item) == {"id", "ticker", "name", "notes", "added_at"}
    assert client.get("/watchlist", headers=alice).get_json() == {"items": [item]}

    assert client.delete("/watchlist/aapl", headers=alice).status_code == 204
    assert client.get("/watchlist", headers=alice).get_json() == {"items": []}


def test_watchlist_errors_have_their_own_status_codes(client, sign_up):
    alice = sign_up("alice")
    add(client, alice, "AAPL")

    invalid = client.post("/watchlist", json={"ticker": "AAPL!", "name": "Apple"}, headers=alice)
    duplicate = add(client, alice, "AAPL")
    missing = client.delete("/watchlist/TSLA", headers=alice)

    assert invalid.status_code == 400 and "Ticker must be" in invalid.get_json()["error"]
    assert duplicate.status_code == 409 and "already on the watchlist" in duplicate.get_json()["error"]
    assert missing.status_code == 404 and missing.get_json() == {"error": "TSLA isn't on the watchlist."}


# Prices for the browser


def test_quotes_api_returns_only_the_accounts_own_tickers(client, sign_up, prices, monkeypatch):
    alice, bob = sign_up("alice"), sign_up("bob")
    add(client, alice, "AAPL")
    add(client, bob, "TSLA")

    response = client.get("/api/quotes", headers=alice)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.get_json()
    assert list(body["quotes"]) == ["AAPL"]
    assert body["market"] is None  # no network in tests
    # The alert summary left with the alerts service: the UI asks it directly.
    assert "alerts" not in body
    assert prices.asked == [["AAPL"]]


def test_quotes_api_never_runs_for_a_signed_out_request(client, prices):
    response = client.get("/api/quotes")

    assert response.status_code == 401
    assert response.is_json
    assert prices.asked == []


def test_search_and_details_only_cover_the_accounts_own_tickers(client, sign_up):
    alice = sign_up("alice")
    add(client, alice, "AAPL")

    assert client.get("/api/search?q=AAPL", headers=alice).get_json() == {"results": []}
    assert client.get("/api/details/aapl", headers=alice).get_json() == {"ticker": "AAPL", "details": None}
    assert client.get("/api/details/TSLA", headers=alice).status_code == 404


def test_stream_follows_the_most_watched_tickers_of_real_accounts(client, sign_up):
    from app.watchlist.repository import most_watched_tickers

    alice, bob = sign_up("alice"), sign_up("bob")
    for headers in (alice, bob):
        add(client, headers, "TSLA")
    add(client, alice, "AAPL")

    assert most_watched_tickers(load_config().db_path) == ["TSLA", "AAPL"]


def test_runtime_wiring_builds_a_stream_that_create_app_never_starts(monkeypatch):
    from app.market.stream import FinnhubStream

    monkeypatch.setenv("PRICE_API_KEY", "fake-key-for-tests")
    with patch("app.market.stream.websocket.WebSocketApp") as connect:
        app = create_app(load_config())

    stream = app.extensions["price_stream"]
    assert isinstance(stream, FinnhubStream) and stream.enabled
    assert not stream.connected
    connect.assert_not_called()


# The snapshot the alerts service reads across the seam


def test_snapshot_lists_every_account_and_prices_only_what_was_asked(client, sign_up, prices):
    alice, bob = sign_up("alice"), sign_up("bob")
    add(client, alice, "AAPL")
    add(client, alice, "MSFT")
    add(client, bob, "TSLA")
    prices.price = 187.44

    owners = {"1": ["AAPL", "MSFT"], "2": ["TSLA"]}

    plain = client.get("/internal/snapshot", headers=service_headers())
    assert plain.get_json() == {"owners": owners, "prices": {}}
    assert prices.looked_up == []  # listing who watches what costs no price lookup

    priced = client.get("/internal/snapshot?tickers=aapl,TSLA,NFLX,", headers=service_headers())
    # NFLX is on nobody's watchlist, so it is left out and never looked up.
    assert priced.get_json() == {"owners": owners, "prices": {"AAPL": 187.44, "TSLA": 187.44}}
    assert prices.looked_up == ["AAPL", "TSLA"]


def test_snapshot_reports_a_missing_price_as_null_with_no_api_key(client, sign_up):
    # The real price code with no Finnhub key: it must not call the network.
    with patch("app.market.finnhub.requests.get") as get:
        real = create_app(load_config()).test_client()
        alice = sign_up("alice")
        add(real, alice, "AAPL")

        body = real.get("/internal/snapshot?tickers=AAPL", headers=service_headers()).get_json()

    assert body == {"owners": {"1": ["AAPL"]}, "prices": {"AAPL": None}}
    get.assert_not_called()


def test_snapshot_carries_the_finnhub_quote_and_never_the_key(monkeypatch, sign_up):
    monkeypatch.setenv("PRICE_API_KEY", "fake-key-for-tests")
    quote = Mock(status_code=200, json=lambda: {"c": 187.44})
    with patch("app.market.finnhub.requests.get", return_value=quote) as get:
        real = create_app(load_config()).test_client()
        alice = sign_up("alice")
        add(real, alice, "AAPL")

        response = real.get("/internal/snapshot?tickers=AAPL", headers=service_headers())

    assert response.get_json()["prices"] == {"AAPL": 187.44}
    assert "fake-key-for-tests" not in response.get_data(as_text=True)
    get.assert_called_once()


def test_rejected_finnhub_key_gives_null_and_not_a_made_up_price(monkeypatch, sign_up):
    monkeypatch.setenv("PRICE_API_KEY", "fake-key-for-tests")
    with patch("app.market.finnhub.requests.get", return_value=Mock(status_code=401)):
        real = create_app(load_config()).test_client()
        alice = sign_up("alice")
        add(real, alice, "AAPL")

        body = real.get("/internal/snapshot?tickers=AAPL", headers=service_headers()).get_json()

    assert body["prices"] == {"AAPL": None}
