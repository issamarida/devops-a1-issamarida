"""Market status, symbol search, company details and the optional .env file."""

import os
from unittest.mock import Mock, patch

import pytest

from app.config import load_env_file
from app.market.finnhub import API_URL, FinnhubSource, Quote
from app.market.info import MarketInfo

FAKE_KEY = "fake-key-for-tests"


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


def answers(*payloads):
    """Patch requests.get to return each payload in turn with HTTP 200."""
    return patch(
        "app.market.finnhub.requests.get",
        side_effect=[Mock(status_code=200, json=Mock(return_value=p)) for p in payloads],
    )


def test_quote_reads_open_high_and_low():
    payload = {"c": 10.0, "o": 9.5, "h": 10.5, "l": 9.0, "pc": 9.8, "t": 100}
    with answers(payload):
        quote = FinnhubSource(FAKE_KEY).get_quote("AAPL")
    assert quote == Quote(10.0, 9.8, 100.0, open=9.5, high=10.5, low=9.0)


def test_extra_calls_leave_room_in_the_budget_for_quotes():
    clock = FakeClock()
    source = FinnhubSource(FAKE_KEY, requests_per_minute=12, clock=clock)
    with patch("app.market.finnhub.requests.get", return_value=Mock(status_code=200, json=lambda: {})) as get:
        assert source.get_json("search", {"q": "A"}) == {}
        assert source.get_json("search", {"q": "B"}) == {}
        assert source.get_json("search", {"q": "C"}) is None  # 2 used + 10 kept free
        assert source.take_budget(0)  # a quote still gets through
    assert get.call_count == 2
    args, kwargs = get.call_args
    assert args == (f"{API_URL}/search",)
    assert kwargs["headers"] == {"X-Finnhub-Token": FAKE_KEY}
    assert FAKE_KEY not in str(kwargs["params"])


def test_extra_calls_return_none_on_http_errors_and_bad_json():
    source = FinnhubSource(FAKE_KEY)
    with patch("app.market.finnhub.requests.get", return_value=Mock(status_code=403)):
        assert source.get_json("stock/metric", {}) is None
    bad = Mock(status_code=200, json=Mock(side_effect=ValueError("bad")))
    with patch("app.market.finnhub.requests.get", return_value=bad):
        assert source.get_json("stock/metric", {}) is None


def test_no_key_means_no_calls_and_no_answers():
    info = MarketInfo(FinnhubSource(None))
    with patch("app.market.finnhub.requests.get") as get:
        assert info.market_status() is None
        assert info.search("apple") == []
        assert info.details("AAPL") is None
    get.assert_not_called()


def test_market_status_is_cached_for_a_minute():
    clock = FakeClock()
    info = MarketInfo(FinnhubSource(FAKE_KEY), clock=clock)
    status = {"isOpen": True, "session": "regular", "holiday": None}
    with answers(status, {**status, "isOpen": False}) as get:
        assert info.market_status() == {"open": True, "session": "regular", "holiday": None}
        clock.now = 59
        assert info.market_status()["open"] is True
        clock.now = 61
        assert info.market_status()["open"] is False
    assert get.call_count == 2


def test_a_failed_answer_is_not_cached():
    info = MarketInfo(FinnhubSource(FAKE_KEY))
    with answers({"weird": 1}, {"isOpen": False, "session": None, "holiday": "Christmas"}):
        assert info.market_status() is None
        assert info.market_status() == {"open": False, "session": None, "holiday": "Christmas"}


def test_search_cleans_up_the_results():
    info = MarketInfo(FinnhubSource(FAKE_KEY))
    payload = {"result": [
        {"symbol": "AAPL", "description": "APPLE INC"},
        {"symbol": "", "description": "no symbol"},
        "not a dict",
    ] + [{"symbol": f"X{i}", "description": "Other"} for i in range(10)]}
    with answers(payload) as get:
        results = info.search(" aapl ")
        assert info.search("AAPL") == results  # cached, same normalised query
    assert results[0] == {"symbol": "AAPL", "name": "Apple Inc"}
    assert len(results) == 8
    assert get.call_args.kwargs["params"] == {"q": "AAPL", "exchange": "US"}


@pytest.mark.parametrize("query", ["", "   ", "X" * 21])
def test_search_ignores_empty_or_long_queries(query):
    with patch("app.market.finnhub.requests.get") as get:
        assert MarketInfo(FinnhubSource(FAKE_KEY)).search(query) == []
    get.assert_not_called()


def test_details_combine_profile_and_52_week_range():
    profile = {"name": "Apple Inc", "finnhubIndustry": "Technology", "exchange": "NASDAQ", "marketCapitalization": 3_000_000}
    metrics = {"metric": {"52WeekHigh": 345.3, "52WeekLow": 243.4}}
    with answers(profile, metrics):
        details = MarketInfo(FinnhubSource(FAKE_KEY)).details("AAPL")
    assert details == {
        "name": "Apple Inc", "industry": "Technology", "exchange": "NASDAQ",
        "market_cap": 3_000_000_000_000, "year_high": 345.3, "year_low": 243.4,
    }


def test_details_survive_missing_metrics():
    with answers({"name": "Tiny Co"}, {"error": "nope"}):
        details = MarketInfo(FinnhubSource(FAKE_KEY)).details("TINY")
    assert details["year_high"] is None and details["market_cap"] is None


def test_unknown_ticker_has_no_details():
    with answers({}):
        assert MarketInfo(FinnhubSource(FAKE_KEY)).details("ZZZZ") is None


# The optional .env file


def test_env_file_fills_only_unset_variables(tmp_path, monkeypatch):
    monkeypatch.delenv("FROM_FILE", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.setenv("FROM_SHELL", "shell")
    env = tmp_path / ".env"
    env.write_text("# comment\n\nFROM_FILE=file\nFROM_SHELL=file\nexport QUOTED=\"a b\"\nnot a setting\n")
    load_env_file(env)
    assert os.environ["FROM_FILE"] == "file"
    assert os.environ["FROM_SHELL"] == "shell"
    assert os.environ["QUOTED"] == "a b"


def test_missing_env_file_is_fine(tmp_path):
    load_env_file(tmp_path / "nothing-here")
