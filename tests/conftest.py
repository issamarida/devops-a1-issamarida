import pytest

from app.db import init_db
from app.watchlist import SCHEMA_PATH as WATCHLIST_SCHEMA
from app.watchlist.repository import WatchlistRepository
from app.watchlist.service import WatchlistService


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "data" / "app.db"
    init_db(path, [WATCHLIST_SCHEMA])
    return path


@pytest.fixture
def watchlist_service(db_path):
    return WatchlistService(WatchlistRepository(db_path))
