import pytest

from app import SCHEMA_FILES, create_app
from app.config import load_config
from app.db import init_db
from app.watchlist.repository import WatchlistRepository
from app.watchlist.service import WatchlistService

# Not a real secret. It only signs tokens inside a test run.
TEST_TOKEN_SECRET = "test-only-token-secret-not-a-real-one"
PASSWORD = "a long test passphrase"


@pytest.fixture(autouse=True)
def service_environment(tmp_path, monkeypatch):
    """Every test gets its own data folder, a token secret and no Finnhub key."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TOKEN_SECRET", TEST_TOKEN_SECRET)
    monkeypatch.setenv("PRICE_API_KEY", "")  # never use a real key from my shell


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "data" / "app.db"
    init_db(path, SCHEMA_FILES)
    return path


@pytest.fixture
def watchlist_service(db_path):
    return WatchlistService(WatchlistRepository(db_path))


class FakePrices:
    """Offline prices. Returns whatever price the test sets and records what was asked."""

    def __init__(self):
        self.price = 100.0
        self.asked = []  # one list of tickers per /api/quotes call
        self.looked_up = []  # every ticker get_price was called for

    def get_price(self, ticker):
        self.looked_up.append(ticker)
        return self.price

    def snapshot(self, tickers):
        self.asked.append(list(tickers))
        quote = {"price": self.price, "change": None, "percent": None, "source": "live", "at": 1.0}
        return {
            "status": "live",
            "server_time": 1.0,
            "quotes": {ticker: dict(quote) for ticker in tickers},
        }


@pytest.fixture
def prices():
    return FakePrices()


@pytest.fixture
def app(prices):
    return create_app(load_config(), price_source=prices)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sign_up(client):
    """sign_up("alice") registers and signs in. Returns the headers that carry the token."""

    def sign_up(username, password=PASSWORD):
        body = {"username": username, "password": password}
        assert client.post("/auth/register", json=body).status_code == 201
        token = client.post("/auth/login", json=body).get_json()["token"]
        return {"Authorization": f"Bearer {token}"}

    return sign_up
