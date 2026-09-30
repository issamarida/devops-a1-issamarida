from unittest.mock import Mock, patch

import pytest
import requests

from app.market.demo import DemoPriceSource
from app.market.finnhub import QUOTE_URL, FinnhubSource
from app.ports import PriceUnavailable

FAKE_KEY = "fake-key-for-tests"


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


def fake_response(status_code=200, payload=None, json_error=None):
    response = Mock()
    response.status_code = status_code
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = payload
    return response


# Demo prices


def test_demo_same_price_inside_one_window():
    clock = FakeClock(60)
    source = DemoPriceSource(clock=clock)
    first = source.get_price("AAPL")
    clock.now = 89
    assert source.get_price("AAPL") == first


def test_demo_ignores_ticker_case():
    source = DemoPriceSource(clock=FakeClock(60))
    assert source.get_price("aapl") == source.get_price("AAPL")


def test_demo_price_changes_in_a_later_window():
    clock = FakeClock(0)
    source = DemoPriceSource(clock=clock)
    prices = set()
    for window in range(10):
        clock.now = window * 30
        prices.add(source.get_price("AAPL"))
    assert len(prices) > 1


def test_demo_price_is_always_positive_and_in_range():
    clock = FakeClock(0)
    source = DemoPriceSource(clock=clock)
    for ticker in ["AAPL", "MSFT", "BRK.B", "X", "TSLA"]:
        for window in range(50):
            clock.now = window * 30
            price = source.get_price(ticker)
            assert 9.5 <= price <= 525
            assert price == round(price, 2)


# Finnhub


def test_finnhub_success_returns_the_current_price():
    with patch("app.market.finnhub.requests.get") as get:
        get.return_value = fake_response(payload={"c": 187.44, "h": 190.0})
        assert FinnhubSource(FAKE_KEY).get_price("AAPL") == 187.44


def test_finnhub_sends_the_key_in_the_header_not_the_url():
    with patch("app.market.finnhub.requests.get") as get:
        get.return_value = fake_response(payload={"c": 187.44})
        FinnhubSource(FAKE_KEY, timeout=2.0).get_price("AAPL")

    args, kwargs = get.call_args
    assert args == (QUOTE_URL,)
    assert FAKE_KEY not in QUOTE_URL
    assert kwargs["params"] == {"symbol": "AAPL"}
    assert kwargs["headers"] == {"X-Finnhub-Token": FAKE_KEY}
    assert kwargs["timeout"] == 2.0


@pytest.mark.parametrize(
    "get_behaviour",
    [
        {"side_effect": requests.Timeout(f"timed out calling {QUOTE_URL}?token={FAKE_KEY}")},
        {"return_value": fake_response(status_code=429, payload={"error": "limit"})},
        {"return_value": fake_response(json_error=ValueError(f"bad json {FAKE_KEY}"))},
        {"return_value": fake_response(payload={"c": 0})},
        {"return_value": fake_response(payload={"h": 190.0})},
        {"return_value": fake_response(payload={"c": -1})},
        {"return_value": fake_response(payload={"c": None})},
        {"return_value": fake_response(payload=["not", "a", "dict"])},
    ],
    ids=["timeout", "http-429", "invalid-json", "c-zero", "c-missing", "c-negative", "c-null", "not-a-dict"],
)
def test_finnhub_failure_raises_price_unavailable_without_the_key(get_behaviour):
    with patch("app.market.finnhub.requests.get", **get_behaviour):
        with pytest.raises(PriceUnavailable) as raised:
            FinnhubSource(FAKE_KEY).get_price("AAPL")

    error = raised.value
    assert "AAPL" in str(error)
    assert FAKE_KEY not in str(error)
    assert FAKE_KEY not in repr(error)
    assert error.__cause__ is None
    assert error.__suppress_context__
