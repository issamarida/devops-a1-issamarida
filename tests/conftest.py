import pytest

from pricewatch.db import init_db
from pricewatch.watchlist import SCHEMA_PATH as WATCHLIST_SCHEMA
from pricewatch.watchlist.repository import WatchlistRepository
from pricewatch.watchlist.service import WatchlistService


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "data" / "pricewatch.db"
    init_db(path, [WATCHLIST_SCHEMA])
    return path


@pytest.fixture
def watchlist_service(db_path):
    return WatchlistService(WatchlistRepository(db_path))
