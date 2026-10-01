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
    return app.test_client()


def page(response) -> str:
    """The page text with &#39; and friends turned back into plain characters."""
    assert response.status_code == 200
    return html.unescape(response.get_data(as_text=True))


def add_aapl_with_rule(client):
    page(client.post("/watchlist", data={"ticker": "AAPL", "name": "Apple"}, follow_redirects=True))
    text = page(
        client.post(
            "/alerts",
            data={"ticker": "AAPL", "condition": "above", "threshold": "150"},
            follow_redirects=True,
        )
    )
    assert "Added a rule for AAPL." in text


def test_rule_fires_and_lands_in_trigger_history(client, prices):
    add_aapl_with_rule(client)

    prices.price = 160.0
    text = page(client.post("/alerts/evaluate", follow_redirects=True))

    assert "Checked the rules. 1 fired." in text
    assert "No rule has fired yet." not in text
    assert "<td>160.0</td>" in text
    assert "<td>fired</td>" in text
    assert "<td>active</td>" not in text


def test_rule_for_unwatched_ticker_shows_error(client):
    text = page(
        client.post(
            "/alerts",
            data={"ticker": "MSFT", "condition": "above", "threshold": "150"},
            follow_redirects=True,
        )
    )

    assert "MSFT isn't on the watchlist. Add it there first." in text
    assert "No alert rules yet." in text


def test_removed_ticker_leaves_rule_dormant(client, prices):
    add_aapl_with_rule(client)
    text = page(client.post("/watchlist/AAPL/delete", follow_redirects=True))
    assert "Removed AAPL." in text

    prices.price = 160.0
    text = page(client.post("/alerts/evaluate", follow_redirects=True))

    assert "Checked the rules. 0 fired." in text
    assert "<td>active</td>" in text
    assert "No rule has fired yet." in text
