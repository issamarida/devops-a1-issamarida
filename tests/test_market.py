from unittest.mock import Mock, patch

import pytest
import requests

from app.market.cache import CachedPriceSource
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
        {
            "side_effect": requests.Timeout(
                f"timed out calling {QUOTE_URL}?token={FAKE_KEY}"
            )
        },
        {"return_value": fake_response(status_code=429, payload={"error": "limit"})},
        {"return_value": fake_response(json_error=ValueError(f"bad json {FAKE_KEY}"))},
        {"return_value": fake_response(payload={"c": 0})},
        {"return_value": fake_response(payload={"h": 190.0})},
        {"return_value": fake_response(payload={"c": -1})},
        {"return_value": fake_response(payload={"c": None})},
        {"return_value": fake_response(payload=["not", "a", "dict"])},
    ],
    ids=[
        "timeout",
        "http-429",
        "invalid-json",
        "c-zero",
        "c-missing",
        "c-negative",
        "c-null",
        "not-a-dict",
    ],
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


# Cache


class CountingSource:
    """Returns a new price on every call so a refetch is easy to spot."""

    def __init__(self):
        self.calls = []
        self.fail = False

    def get_price(self, ticker):
        self.calls.append(ticker)
        if self.fail:
            raise PriceUnavailable(ticker)
        return 100.0 + len(self.calls)


def test_cache_hit_inside_ttl_makes_one_underlying_call():
    clock = FakeClock(0)
    source = CountingSource()
    cached = CachedPriceSource(source, ttl_seconds=30, clock=clock)

    first = cached.get_price("AAPL")
    clock.now = 29
    assert cached.get_price("AAPL") == first
    assert source.calls == ["AAPL"]


def test_cache_refetches_after_the_ttl():
    clock = FakeClock(0)
    source = CountingSource()
    cached = CachedPriceSource(source, ttl_seconds=30, clock=clock)

    first = cached.get_price("AAPL")
    clock.now = 31
    second = cached.get_price("AAPL")
    assert second != first
    assert source.calls == ["AAPL", "AAPL"]


def test_cache_is_per_ticker():
    source = CountingSource()
    cached = CachedPriceSource(source, ttl_seconds=30, clock=FakeClock(0))

    assert cached.get_price("AAPL") != cached.get_price("MSFT")
    assert source.calls == ["AAPL", "MSFT"]


def test_cache_does_not_store_a_failure():
    source = CountingSource()
    source.fail = True
    cached = CachedPriceSource(source, ttl_seconds=30, clock=FakeClock(0))

    with pytest.raises(PriceUnavailable):
        cached.get_price("AAPL")

    source.fail = False
    assert cached.get_price("AAPL") == 102.0
    assert source.calls == ["AAPL", "AAPL"]


def test_cache_with_ttl_zero_always_refetches():
    source = CountingSource()
    cached = CachedPriceSource(source, ttl_seconds=0, clock=FakeClock(0))

    cached.get_price("AAPL")
    cached.get_price("AAPL")
    assert source.calls == ["AAPL", "AAPL"]


@pytest.mark.parametrize(
    "price", [True, False, float("inf"), float("-inf"), float("nan"), "100"]
)
def test_finnhub_rejects_invalid_numeric_prices(price):
    with patch(
        "app.market.finnhub.requests.get",
        return_value=fake_response(payload={"c": price}),
    ):
        with pytest.raises(PriceUnavailable):
            FinnhubSource(FAKE_KEY).get_price("AAPL")


def test_cache_ttl_starts_after_fetch_finishes():
    clock = FakeClock(0)

    class SlowSource:
        def get_price(self, ticker):
            clock.now += 5
            return 100

    cache = CachedPriceSource(SlowSource(), 10, clock)
    cache.get_price("AAPL")
    clock.now = 12
    assert cache.get_price("AAPL") == 100
    assert clock.now == 12


def test_live_quotes_obey_global_budget_and_recover_after_window():
    clock = FakeClock()
    source = FinnhubSource(FAKE_KEY, requests_per_minute=2, clock=clock)
    with patch(
        "app.market.finnhub.requests.get",
        return_value=fake_response(payload={"c": 100}),
    ) as get:
        source.get_price("AAPL")
        source.get_price("MSFT")
        with pytest.raises(PriceUnavailable, match="budget"):
            source.get_price("TSLA")
        assert get.call_count == 2
        clock.now = 60
        assert source.get_price("TSLA") == 100
        assert get.call_count == 3
