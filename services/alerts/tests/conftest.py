import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest

from app import SCHEMA_FILES
from app.db import init_db

# Not a real secret. It only signs tokens inside a test run.
TEST_TOKEN_SECRET = "test-only-token-secret-not-a-real-one"

ANSWER = {
    "owners": {"7": ["AAPL", "MSFT"], "8": ["TSLA"]},
    "prices": {"AAPL": 200.0, "MSFT": None, "TSLA": 300},
}


@pytest.fixture(autouse=True)
def service_environment(tmp_path, monkeypatch):
    """Every test gets its own data folder and a token secret."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TOKEN_SECRET", TEST_TOKEN_SECRET)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "data" / "alerts.db"
    init_db(path, SCHEMA_FILES)
    return path


def user_headers(account_id, username="investor", secret=TEST_TOKEN_SECRET, lifetime=3600):
    """A token signed the way the watchlist service signs one at sign in."""
    now = int(time.time())
    claims = {"sub": str(account_id), "name": username, "iat": now, "exp": now + lifetime}
    return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm="HS256")}


class StubWatchlist:
    """Stands in for the watchlist service. A real HTTP server on a free localhost port.

    Like the real one it only answers the alerts service: the request must carry
    a token with the snapshot scope, signed with the shared secret.
    """

    def __init__(self):
        self.answer = ANSWER
        self.status = 200
        self.delay_seconds = 0.0
        self.paths = []  # the path of every request it received
        self.asked = []  # the tickers each request asked prices for
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlsplit(self.path)
                stub.paths.append(url.path)
                stub.asked.append(parse_qs(url.query).get("tickers", [""])[0])
                time.sleep(stub.delay_seconds)
                if url.path != "/internal/snapshot":
                    status, body = 404, {}
                elif not stub.is_alerts_service(self.headers.get("Authorization", "")):
                    status, body = 401, {"error": "This endpoint is for the alerts service."}
                else:
                    status, body = stub.status, stub.answer
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # the caller timed out and hung up, which is the point

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        # A short poll interval makes stop() return quickly.
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        ).start()

    @staticmethod
    def is_alerts_service(header) -> bool:
        try:
            claims = jwt.decode(
                header.removeprefix("Bearer "), TEST_TOKEN_SECRET, algorithms=["HS256"]
            )
        except jwt.InvalidTokenError:
            return False
        return claims.get("scope") == "snapshot"

    def stop(self):
        """Like docker compose stop watchlist: the port stops answering."""
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    stub = StubWatchlist()
    yield stub
    stub.stop()
