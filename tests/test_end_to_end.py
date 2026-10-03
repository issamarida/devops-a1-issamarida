"""Drives the real Flask app from the watchlist through to a fired alert."""

import html

import pytest

from app import create_app
from app.config import load_config


class FakePriceSource:
    """Returns whatever price the test sets."""

    def __init__(self):
        self.price = 100.0

    def get_price(self, ticker):
        return self.price


@pytest.fixture
def prices():
    return FakePriceSource()


@pytest.fixture
def client(tmp_path, monkeypatch, prices):
    # Same as app.py: load_config reads the environment.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app(load_config(), price_source=prices)
    client = app.test_client()
    post_form(
        client,
        "/register",
        data={"username": "investor", "password": "a long test passphrase"},
    )
    post_form(
        client,
        "/login",
        data={"username": "investor", "password": "a long test passphrase"},
    )
    return client


def post_form(client, path, **kwargs):
    client.get("/login")
    with client.session_transaction() as session:
        token = session["csrf"]
    data = dict(kwargs.pop("data", {}), csrf_token=token)
    return client.post(path, data=data, **kwargs)


def page(response) -> str:
    """The page text with &#39; and friends turned back into plain characters."""
    assert response.status_code == 200
    return html.unescape(response.get_data(as_text=True))


def add_aapl_with_rule(client):
    page(
        post_form(
            client,
            "/watchlist",
            data={"ticker": "AAPL", "name": "Apple"},
            follow_redirects=True,
        )
    )
    text = page(
        post_form(
            client,
            "/alerts",
            data={"ticker": "AAPL", "condition": "above", "threshold": "150"},
            follow_redirects=True,
        )
    )
    assert "Added a rule for AAPL." in text


def test_rule_fires_and_lands_in_trigger_history(client, prices):
    add_aapl_with_rule(client)

    prices.price = 160.0
    text = page(post_form(client, "/alerts/evaluate", follow_redirects=True))

    assert "Checked the rules. 1 fired." in text
    assert "No rule has fired yet." not in text
    assert "<td>160.00</td>" in text
    assert 'class="badge fired">fired</span>' in text


def test_rule_for_unwatched_ticker_shows_error(client):
    text = page(
        post_form(
            client,
            "/alerts",
            data={"ticker": "MSFT", "condition": "above", "threshold": "150"},
            follow_redirects=True,
        )
    )

    assert "MSFT isn't on the watchlist. Add it there first." in text
    assert "No alert rules yet." in text


def test_removed_ticker_leaves_rule_dormant(client, prices):
    add_aapl_with_rule(client)
    text = page(post_form(client, "/watchlist/AAPL/delete", follow_redirects=True))
    assert "Removed AAPL." in text

    prices.price = 160.0
    text = page(post_form(client, "/alerts/evaluate", follow_redirects=True))

    assert "Checked the rules. 0 fired." in text
    assert 'class="badge dormant">dormant</span>' in text
    assert "No rule has fired yet." in text


def test_manual_check_reports_unavailable_prices(client, prices):
    add_aapl_with_rule(client)
    prices.price = float("nan")
    text = page(post_form(client, "/alerts/evaluate", follow_redirects=True))
    assert "1 ticker had no fresh quote yet; those rules stay active." in text
    assert "No rule has fired yet." in text


def finnhub_client(tmp_path, monkeypatch, key):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRICE_API_KEY", key)
    app = create_app(load_config())
    client = app.test_client()
    post_form(
        client,
        "/register",
        data={"username": "investor", "password": "a long test passphrase"},
    )
    post_form(
        client,
        "/login",
        data={"username": "investor", "password": "a long test passphrase"},
    )
    return app, client


def test_missing_key_keeps_app_ready_but_cannot_fire_rules(tmp_path, monkeypatch):
    from unittest.mock import patch

    with patch("app.market.finnhub.requests.get") as get:
        app, client = finnhub_client(tmp_path, monkeypatch, "")
        assert client.get("/health").status_code == 200
        add_aapl_with_rule(client)
        text = page(post_form(client, "/alerts/evaluate", follow_redirects=True))
        assert "Checked the rules. 0 fired." in text
        assert "unavailable" not in text
        assert "Demo" not in text
        assert app.extensions["alert_service"].evaluate_all() == []
        assert app.extensions["alerts_for"](1).list_events() == []
        assert app.extensions["alerts_for"](1).list_rules()[0]["is_active"] == 1
        get.assert_not_called()


def test_configured_finnhub_quote_is_the_recorded_price(tmp_path, monkeypatch):
    from unittest.mock import Mock, patch

    with patch(
        "app.market.finnhub.requests.get",
        return_value=Mock(status_code=200, json=lambda: {"c": 187.44}),
    ) as get:
        app, client = finnhub_client(tmp_path, monkeypatch, "fake-key-for-tests")
        add_aapl_with_rule(client)
        text = page(post_form(client, "/alerts/evaluate", follow_redirects=True))
        assert "Live market data" in text
        assert "Demo" not in text
        assert (
            app.extensions["alerts_for"](1).list_events()[0]["observed_price"] == 187.44
        )
        get.assert_called_once()


def test_rejected_finnhub_key_does_not_fall_back_to_fake_prices(tmp_path, monkeypatch):
    from unittest.mock import Mock, patch

    with patch("app.market.finnhub.requests.get", return_value=Mock(status_code=401)):
        app, client = finnhub_client(tmp_path, monkeypatch, "fake-key-for-tests")
        add_aapl_with_rule(client)
        text = page(post_form(client, "/alerts/evaluate", follow_redirects=True))
        assert "had no fresh quote yet" in text
        assert app.extensions["alerts_for"](1).list_events() == []
        assert app.extensions["alerts_for"](1).list_rules()[0]["is_active"] == 1


# The /api/quotes endpoint the pages poll


class SnapshotPrices(FakePriceSource):
    def __init__(self):
        super().__init__()
        self.asked = []

    def snapshot(self, tickers):
        self.asked.append(list(tickers))
        return {
            "status": "live",
            "server_time": 1.0,
            "quotes": {t: {"price": self.price, "change": None, "percent": None, "source": "live", "at": 1.0} for t in tickers},
        }


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRICE_API_KEY", "fake-key-for-tests")
    prices = SnapshotPrices()
    app = create_app(load_config(), price_source=prices)
    return app, prices


def sign_up(client, username):
    password = "a long test passphrase"
    post_form(client, "/register", data={"username": username, "password": password})
    post_form(client, "/login", data={"username": username, "password": password})


def test_quotes_api_rejects_signed_out_requests_with_json(api_client):
    app, prices = api_client
    response = app.test_client().get("/api/quotes")
    assert response.status_code == 401
    assert response.is_json
    assert prices.asked == []


def test_quotes_api_returns_only_the_accounts_own_tickers(api_client):
    app, prices = api_client
    alice, bob = app.test_client(), app.test_client()
    sign_up(alice, "alice")
    sign_up(bob, "bob")
    post_form(alice, "/watchlist", data={"ticker": "AAPL", "name": "Apple"})
    post_form(bob, "/watchlist", data={"ticker": "TSLA", "name": "Tesla"})

    response = alice.get("/api/quotes")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert list(response.get_json()["quotes"]) == ["AAPL"]
    assert prices.asked == [["AAPL"]]
    assert "fake-key-for-tests" not in response.get_data(as_text=True)


def test_pages_allow_only_their_own_script_and_same_origin_fetch(api_client):
    app, _ = api_client
    client = app.test_client()
    sign_up(client, "alice")
    post_form(client, "/watchlist", data={"ticker": "AAPL", "name": "Apple"})
    response = client.get("/watchlist")
    policy = response.headers["Content-Security-Policy"]
    text = page(response)
    nonce = policy.split("script-src 'nonce-")[1].split("'")[0]
    assert f'<script nonce="{nonce}">' in text
    assert "connect-src 'self'" in policy
    assert 'data-quote="AAPL" data-field="price"' in text
    assert "/api/quotes" in text
    assert "finnhub.io" not in text and "fake-key-for-tests" not in text


def test_stream_follows_the_most_watched_tickers_of_real_accounts(api_client):
    from app.watchlist.repository import most_watched_tickers

    app, _ = api_client
    alice, bob = app.test_client(), app.test_client()
    sign_up(alice, "alice")
    sign_up(bob, "bob")
    for client in (alice, bob):
        post_form(client, "/watchlist", data={"ticker": "TSLA", "name": "Tesla"})
    post_form(alice, "/watchlist", data={"ticker": "AAPL", "name": "Apple"})
    db_path = load_config().db_path
    assert most_watched_tickers(db_path) == ["TSLA", "AAPL"]


def test_runtime_wiring_builds_a_stream_that_create_app_never_starts(tmp_path, monkeypatch):
    from app.market.stream import FinnhubStream

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRICE_API_KEY", "fake-key-for-tests")
    with patch_connect() as connect:
        app = create_app(load_config())
    stream = app.extensions["price_stream"]
    assert isinstance(stream, FinnhubStream) and stream.enabled
    assert not stream.connected
    connect.assert_not_called()


def patch_connect():
    from unittest.mock import patch

    return patch("app.market.stream.websocket.WebSocketApp")
