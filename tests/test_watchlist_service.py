import pytest

from pricewatch.watchlist.service import DuplicateTickerError, InvalidWatchlistItemError


def test_add_item_normalizes_ticker_to_uppercase(watchlist_service):
    item = watchlist_service.add_item("  aapl ", "Apple Inc.")

    assert item.ticker == "AAPL"
    assert [i.ticker for i in watchlist_service.list_items()] == ["AAPL"]


def test_add_item_stores_name_notes_and_timestamp(watchlist_service):
    item = watchlist_service.add_item("brk.b", " Berkshire Hathaway ", " long term ")

    assert item.ticker == "BRK.B"
    assert item.name == "Berkshire Hathaway"
    assert item.notes == "long term"
    assert item.added_at


def test_add_item_rejects_duplicate_ticker_case_insensitively(watchlist_service):
    watchlist_service.add_item("MSFT", "Microsoft")

    with pytest.raises(DuplicateTickerError):
        watchlist_service.add_item("msft", "Microsoft again")
    assert len(watchlist_service.list_items()) == 1


@pytest.mark.parametrize("name", ["", "   ", None])
def test_add_item_rejects_blank_name(watchlist_service, name):
    with pytest.raises(InvalidWatchlistItemError):
        watchlist_service.add_item("AAPL", name)
    assert watchlist_service.list_items() == []


@pytest.mark.parametrize("ticker", ["", "   ", "AA PL", "AAPL$", "BRK-B", "ABCDEFGHIJK"])
def test_add_item_rejects_invalid_ticker(watchlist_service, ticker):
    with pytest.raises(InvalidWatchlistItemError):
        watchlist_service.add_item(ticker, "Some Company")
    assert watchlist_service.list_items() == []


def test_is_watched_before_and_after_add(watchlist_service):
    assert watchlist_service.is_watched("TSLA") is False

    watchlist_service.add_item("TSLA", "Tesla")

    assert watchlist_service.is_watched("TSLA") is True
    assert watchlist_service.is_watched("tsla") is True


def test_remove_item(watchlist_service):
    watchlist_service.add_item("NVDA", "Nvidia")

    assert watchlist_service.remove_item("nvda") is True
    assert watchlist_service.is_watched("NVDA") is False
    assert watchlist_service.list_items() == []


def test_remove_item_that_is_not_watched_returns_false(watchlist_service):
    assert watchlist_service.remove_item("NOPE") is False
