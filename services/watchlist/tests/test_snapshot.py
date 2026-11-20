"""The answer the alerts service asks for: who watches what, and what it costs."""

from app.market.snapshot import build_snapshot
from app.ports import PriceUnavailable
from app.watchlist.repository import WatchlistRepository, tickers_by_owner

OWNERS = {"7": ["AAPL", "MSFT"], "8": ["AAPL", "TSLA"]}


class Prices:
    def __init__(self, prices):
        self.prices = prices
        self.calls = []

    def get_price(self, ticker):
        self.calls.append(ticker)
        if ticker not in self.prices:
            raise PriceUnavailable(ticker)
        return self.prices[ticker]


def test_owners_are_always_there_and_prices_only_when_asked():
    source = Prices({"AAPL": 187.44})

    assert build_snapshot(OWNERS, [], source) == {"owners": OWNERS, "prices": {}}
    assert source.calls == []


def test_prices_for_the_tickers_that_were_asked_for():
    source = Prices({"AAPL": 187.44, "TSLA": 300.0})

    body = build_snapshot(OWNERS, ["AAPL", "TSLA"], source)

    assert body["prices"] == {"AAPL": 187.44, "TSLA": 300.0}


def test_a_ticker_without_a_price_is_null_not_an_error():
    body = build_snapshot(OWNERS, ["AAPL", "MSFT"], Prices({"AAPL": 187.44}))

    assert body["prices"] == {"AAPL": 187.44, "MSFT": None}


def test_a_ticker_nobody_watches_is_never_looked_up():
    source = Prices({"NFLX": 500.0})

    body = build_snapshot(OWNERS, ["NFLX"], source)

    assert body["prices"] == {}
    assert source.calls == []


def test_a_ticker_two_accounts_watch_is_looked_up_once():
    source = Prices({"AAPL": 187.44})

    build_snapshot(OWNERS, ["AAPL", "AAPL"], source)

    assert source.calls == ["AAPL"]


def test_tickers_by_owner_groups_each_accounts_tickers(db_path):
    WatchlistRepository(db_path, 7).add("MSFT", "Microsoft", "", "2026-11-20")
    WatchlistRepository(db_path, 7).add("AAPL", "Apple", "", "2026-11-20")
    WatchlistRepository(db_path, 8).add("TSLA", "Tesla", "", "2026-11-20")
    # Owner 0 is old data from before accounts existed. Nobody owns it.
    WatchlistRepository(db_path, 0).add("NFLX", "Netflix", "", "2026-11-20")

    assert tickers_by_owner(db_path) == {"7": ["AAPL", "MSFT"], "8": ["TSLA"]}


def test_tickers_by_owner_is_empty_when_nothing_is_watched(db_path):
    assert tickers_by_owner(db_path) == {}
