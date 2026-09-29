import pytest

from app.alerts.repository import AlertRepository
from app.alerts.service import AlertService, InvalidRuleError
from app.ports import PriceUnavailable


class FakePriceSource:
    def __init__(self, prices):
        self.prices = prices
        self.calls = []

    def get_price(self, ticker):
        self.calls.append(ticker)
        if ticker not in self.prices:
            raise PriceUnavailable(ticker)
        return self.prices[ticker]


class FakeWatchlistReader:
    def __init__(self, tickers):
        self.tickers = set(tickers)

    def is_watched(self, ticker):
        return ticker in self.tickers


@pytest.fixture
def prices():
    return FakePriceSource({"AAPL": 200.0})


@pytest.fixture
def watchlist():
    return FakeWatchlistReader({"AAPL", "MSFT"})


@pytest.fixture
def service(db_path, prices, watchlist):
    return AlertService(AlertRepository(db_path), prices, watchlist)


def test_create_rule_cleans_ticker_and_returns_rule(service):
    rule = service.create_rule("  aapl ", "above", "210.5")

    assert rule["ticker"] == "AAPL"
    assert rule["condition"] == "above"
    assert rule["threshold"] == 210.5
    assert rule["is_active"] == 1
    assert service.list_rules() == [rule]


def test_rejects_unwatched_ticker(service):
    with pytest.raises(InvalidRuleError):
        service.create_rule("TSLA", "above", 100)


def test_rejects_blank_ticker(service):
    with pytest.raises(InvalidRuleError):
        service.create_rule("   ", "above", 100)


def test_rejects_bad_condition(service):
    with pytest.raises(InvalidRuleError):
        service.create_rule("AAPL", "equals", 100)


@pytest.mark.parametrize("threshold", ["0", -5, "abc", None, "nan", "inf", float("-inf")])
def test_rejects_bad_threshold(service, threshold):
    with pytest.raises(InvalidRuleError):
        service.create_rule("AAPL", "above", threshold)
    assert service.list_rules() == []


def test_above_rule_fires(service):
    rule = service.create_rule("AAPL", "above", 190)

    fired = service.evaluate_all()

    assert [r["id"] for r in fired] == [rule["id"]]
    events = service.list_events()
    assert len(events) == 1
    assert events[0]["observed_price"] == 200.0


def test_below_rule_fires(service):
    rule = service.create_rule("AAPL", "below", 210)

    fired = service.evaluate_all()

    assert [r["id"] for r in fired] == [rule["id"]]


def test_untriggered_rule_stays_active(service):
    service.create_rule("AAPL", "above", 250)

    assert service.evaluate_all() == []
    assert service.list_rules()[0]["is_active"] == 1
    assert service.list_events() == []


def test_unavailable_price_is_skipped(service, prices):
    service.create_rule("MSFT", "above", 1)  # FakePriceSource has no MSFT price
    aapl_rule = service.create_rule("AAPL", "above", 190)

    fired = service.evaluate_all()

    assert [r["id"] for r in fired] == [aapl_rule["id"]]
    assert "MSFT" in prices.calls


def test_dormant_rule_is_skipped(service, watchlist, prices):
    service.create_rule("AAPL", "above", 190)
    watchlist.tickers.remove("AAPL")

    assert service.evaluate_all() == []
    assert prices.calls == []
    # Dormant rules are kept, not deleted
    assert service.list_rules()[0]["is_active"] == 1


def test_fired_rule_does_not_fire_again(service):
    service.create_rule("AAPL", "above", 190)

    assert len(service.evaluate_all()) == 1
    assert service.evaluate_all() == []
    assert len(service.list_events()) == 1


def test_two_rules_on_one_ticker_look_up_price_once(service, prices):
    service.create_rule("AAPL", "above", 190)
    service.create_rule("AAPL", "below", 250)

    fired = service.evaluate_all()

    assert len(fired) == 2
    assert prices.calls == ["AAPL"]


def test_delete_rule(service):
    rule = service.create_rule("AAPL", "above", 190)

    assert service.delete_rule(rule["id"]) is True
    assert service.list_rules() == []
