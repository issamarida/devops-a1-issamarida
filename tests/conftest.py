import pytest

from app import SCHEMA_FILES
from app.db import init_db
from app.watchlist.repository import WatchlistRepository
from app.watchlist.service import WatchlistService


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "data" / "app.db"
    init_db(path, SCHEMA_FILES)
    return path


@pytest.fixture
def watchlist_service(db_path):
    return WatchlistService(WatchlistRepository(db_path))
