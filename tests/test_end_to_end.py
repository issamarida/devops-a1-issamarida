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
    assert "Some prices were unavailable." in text
    assert "No rule has fired yet." in text
