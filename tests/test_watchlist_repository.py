import sqlite3

import pytest

from app import SCHEMA_FILES
from app.db import init_db
from app.watchlist.repository import WatchlistRepository


@pytest.fixture
def repo(db_path):
    return WatchlistRepository(db_path)


def test_add_returns_item_with_new_id(repo):
    item = repo.add("AAPL", "Apple", "", "2026-10-01T09:00:00+00:00")

    assert item.id is not None
    assert repo.get_by_ticker("AAPL") == item


def test_add_duplicate_raises_integrity_error(repo):
    repo.add("AAPL", "Apple", "", "2026-10-01T09:00:00+00:00")

    with pytest.raises(sqlite3.IntegrityError):
        repo.add("AAPL", "Apple again", "", "2026-10-01T09:01:00+00:00")


def test_get_by_ticker_returns_none_when_missing(repo):
    assert repo.get_by_ticker("NOPE") is None
    assert repo.exists("NOPE") is False


def test_list_all_is_sorted_by_ticker(repo):
    for ticker in ["MSFT", "AAPL", "BRK.B"]:
        repo.add(ticker, ticker, "", "2026-10-01T09:00:00+00:00")

    assert [item.ticker for item in repo.list_all()] == ["AAPL", "BRK.B", "MSFT"]


def test_lookups_are_case_sensitive_so_the_service_must_normalize(repo):
    # The repository stores what it's given. WatchlistService uppercases first.
    repo.add("AAPL", "Apple", "", "2026-10-01T09:00:00+00:00")

    assert repo.exists("aapl") is False
    assert repo.delete("aapl") is False
    assert repo.exists("AAPL") is True


def test_delete_removes_only_that_ticker(repo):
    repo.add("AAPL", "Apple", "", "2026-10-01T09:00:00+00:00")
    repo.add("MSFT", "Microsoft", "", "2026-10-01T09:00:00+00:00")

    assert repo.delete("AAPL") is True
    assert [item.ticker for item in repo.list_all()] == ["MSFT"]


def test_init_db_twice_keeps_existing_rows(repo, db_path):
    repo.add("AAPL", "Apple", "", "2026-10-01T09:00:00+00:00")

    init_db(db_path, SCHEMA_FILES)

    assert repo.exists("AAPL") is True


def test_same_ticker_is_private_to_each_owner(db_path):
    alice = WatchlistRepository(db_path, 1)
    bob = WatchlistRepository(db_path, 2)
    alice.add("AAPL", "Apple", "Private note", "2026-10-03")
    assert bob.list_all() == []
    assert bob.get_by_ticker("AAPL") is None
    assert bob.delete("AAPL") is False
    bob.add("AAPL", "Apple", "Other note", "2026-10-03")
    assert bob.get_by_ticker("AAPL").notes == "Other note"
    assert alice.get_by_ticker("AAPL").notes == "Private note"
