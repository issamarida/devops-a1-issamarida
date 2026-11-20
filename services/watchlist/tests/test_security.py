"""Exercise real cookies, CSRF, password hashes, access boundaries and throttling."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app import SCHEMA_FILES, create_app
from app.config import load_config
from app.db import get_connection, init_db
from app.security import AccessStore

PASSWORD = "a private test passphrase"


def post(client, path, data=None, **kwargs):
    client.get("/login")
    with client.session_transaction() as cookie:
        token = cookie["csrf"]
    return client.post(path, data=dict(data or {}, csrf_token=token), **kwargs)


def join(client, username):
    assert (
        post(
            client, "/register", {"username": username, "password": PASSWORD}
        ).status_code
        == 303
    )
    assert (
        post(client, "/login", {"username": username, "password": PASSWORD}).status_code
        == 303
    )


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PRICE_API_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    return create_app(
        load_config(), price_source=Mock(get_price=Mock(return_value=100.0))
    )


def test_all_private_pages_require_login_but_health_is_public(app):
    client = app.test_client()
    assert client.get("/health").status_code == 200
    for path in ("/watchlist", "/alerts"):
        assert client.get(path).location == "/login"
    assert (
        post(client, "/watchlist", {"ticker": "AAPL", "name": "Apple"}).location
        == "/login"
    )


def test_csrf_blocks_signup_login_and_authenticated_mutations(app):
    client = app.test_client()
    for path in ("/register", "/login"):
        assert (
            client.post(
                path, data={"username": "alice", "password": PASSWORD}
            ).status_code
            == 400
        )
    join(client, "alice")
    for path in ("/watchlist", "/alerts", "/alerts/evaluate", "/logout"):
        assert client.post(path, data={"csrf_token": "wrong"}).status_code == 400


def test_password_is_hashed_and_session_is_revoked_on_logout(app):
    client = app.test_client()
    join(client, "alice")
    store = app.extensions["access_store"]
    with closing(get_connection(store.db_path)) as conn:
        row = conn.execute("SELECT * FROM accounts").fetchone()
        assert row["password_hash"].startswith("scrypt:")
        assert PASSWORD not in row["password_hash"]
    stolen = client.get_cookie("session").value
    assert post(client, "/logout").status_code == 303
    client.set_cookie("session", stolen)
    assert client.get("/watchlist").location == "/login"


def test_new_login_invalidates_previous_session_and_old_csrf(app):
    first, second = app.test_client(), app.test_client()
    join(first, "alice")
    first.get("/watchlist")
    with first.session_transaction() as cookie:
        old_csrf = cookie["csrf"]
    assert (
        post(second, "/login", {"username": "alice", "password": PASSWORD}).status_code
        == 303
    )
    assert first.get("/watchlist").location == "/login"
    assert second.post("/watchlist", data={"csrf_token": old_csrf}).status_code == 400


def test_session_expires_on_server(app):
    client = app.test_client()
    join(client, "alice")
    store = app.extensions["access_store"]
    now = store.clock()
    store.clock = lambda: now + 3601
    assert client.get("/alerts").location == "/login"


def test_users_cannot_read_or_delete_each_others_data(app):
    alice, bob = app.test_client(), app.test_client()
    join(alice, "alice")
    post(
        alice,
        "/watchlist",
        {"ticker": "AAPL", "name": "Private Apple", "notes": "Only Alice sees this"},
    )
    post(alice, "/alerts", {"ticker": "AAPL", "condition": "above", "threshold": "1"})
    post(alice, "/alerts/evaluate")
    join(bob, "bob")
    assert "Only Alice sees this" not in bob.get("/watchlist").text
    assert '<span class="ticker">AAPL</span>' not in bob.get("/alerts").text
    post(bob, "/watchlist/AAPL/delete")
    post(bob, "/alerts/1/delete")
    assert "Only Alice sees this" in alice.get("/watchlist").text
    assert '<span class="ticker">AAPL</span>' in alice.get("/alerts").text
    # A forged owner parameter never changes the signed-in account scope.
    post(bob, "/watchlist", {"ticker": "MSFT", "name": "Bob only", "owner_id": "1"})
    assert "Bob only" not in alice.get("/watchlist").text


def test_one_accounts_watchlist_does_not_activate_anothers_rule(app):
    alice, bob = app.test_client(), app.test_client()
    join(alice, "alice")
    join(bob, "bob")
    for client in (alice, bob):
        post(client, "/watchlist", {"ticker": "AAPL", "name": "Apple"})
        post(
            client,
            "/alerts",
            {"ticker": "AAPL", "condition": "above", "threshold": "1"},
        )
    post(alice, "/watchlist/AAPL/delete")
    app.extensions["alert_service"].evaluate_all()
    assert app.extensions["alerts_for"](1).list_events() == []
    assert len(app.extensions["alerts_for"](2).list_events()) == 1


def test_login_rate_limit_survives_restart_and_ignores_forwarded_address(app):
    client = app.test_client()
    join(client, "alice")  # first login consumed one attempt
    for _ in range(4):
        assert (
            post(
                client, "/login", {"username": "alice", "password": "wrong"}
            ).status_code
            == 401
        )
    response = post(
        client,
        "/login",
        {"username": "alice", "password": PASSWORD},
        headers={"X-Forwarded-For": "203.0.113.3"},
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    original = app.extensions["access_store"]
    reopened = AccessStore(original.db_path)
    assert reopened.consume("login-user:alice", 5, 900) > 0
    reopened.clock = lambda: original.clock() + 901
    assert reopened.consume("login-user:alice", 5, 900) == 0


def test_unknown_and_wrong_password_have_identical_messages(app):
    client = app.test_client()
    join(client, "alice")
    for username in ("alice", "missing"):
        response = post(client, "/login", {"username": username, "password": "wrong"})
        assert response.status_code == 401
        assert "Incorrect username or password." in response.text


def test_registration_validation_duplicate_and_capacity(app):
    store = app.extensions["access_store"]
    for username, password in [
        ("a", PASSWORD),
        ("bad name", PASSWORD),
        ("alice", "short"),
        ("alice", "x" * 129),
    ]:
        with pytest.raises(ValueError):
            store.register(username, password)
    assert store.register(" Alice ", PASSWORD) == 1
    with pytest.raises(ValueError, match="Unable to create"):
        store.register("ALICE", PASSWORD)
    store.max_accounts = 1
    with pytest.raises(ValueError, match="Registration is unavailable"):
        store.register("bob", PASSWORD)


def test_registration_throttle_and_validation_render_errors(app):
    client = app.test_client()
    for _ in range(5):
        assert (
            post(
                client, "/register", {"username": "a", "password": "short"}
            ).status_code
            == 400
        )
    assert (
        post(
            client, "/register", {"username": "alice", "password": PASSWORD}
        ).status_code
        == 429
    )


def test_rate_limit_reservation_is_atomic(app):
    store = app.extensions["access_store"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.consume("concurrent", 3, 60), range(8)))
    assert results.count(0) == 3


def test_evaluate_is_rate_limited(app):
    client = app.test_client()
    join(client, "alice")
    for _ in range(4):
        assert post(client, "/alerts/evaluate").status_code == 302
    assert post(client, "/alerts/evaluate").status_code == 429


def test_escaped_notes_headers_cookie_flags_and_request_size(app):
    client = app.test_client()
    join(client, "alice")
    post(
        client,
        "/watchlist",
        {"ticker": "AAPL", "name": "Apple", "notes": "<script>alert(1)</script>"},
    )
    response = client.get("/watchlist")
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    cookie = client.get_cookie("session")
    assert cookie.http_only and cookie.same_site == "Lax"
    assert client.post("/watchlist", data={"notes": "x" * 20000}).status_code == 413
    assert client.get("/missing").status_code == 404


def test_secure_cookie_setting_and_hsts(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    config = replace(load_config(), cookie_secure=True)
    response = (
        create_app(config).test_client().get("/login", base_url="https://example.test")
    )
    assert "Secure;" in response.headers["Set-Cookie"]
    assert "max-age=" in response.headers["Strict-Transport-Security"]


def test_automatic_upgrade_preserves_legacy_rows_without_exposing_them(tmp_path):
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript("""
            CREATE TABLE watchlist_items (id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE, name TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', added_at TEXT NOT NULL);
            INSERT INTO watchlist_items VALUES (1, 'AAPL', 'Apple', 'legacy private note', '2026-09-28');
            CREATE TABLE alert_rules (id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, condition TEXT NOT NULL,
                threshold REAL NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
            INSERT INTO alert_rules VALUES (1, 'AAPL', 'above', 100, 1, '2026-09-28');
            CREATE TABLE alert_events (id INTEGER PRIMARY KEY, rule_id INTEGER REFERENCES alert_rules(id) ON DELETE SET NULL,
                ticker TEXT NOT NULL, condition TEXT NOT NULL, threshold REAL NOT NULL, observed_price REAL NOT NULL, triggered_at TEXT NOT NULL);
            INSERT INTO alert_events VALUES (1, 1, 'AAPL', 'above', 100, 120, '2026-09-28');
        """)
    init_db(path, SCHEMA_FILES)
    init_db(path, SCHEMA_FILES)
    with closing(get_connection(path)) as conn:
        for table in ("watchlist_items", "alert_rules", "alert_events"):
            assert (
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE owner_id = 0"
                ).fetchone()[0]
                == 1
            )
        assert conn.execute("SELECT rule_token FROM alert_rules").fetchone()[0]
        conn.execute(
            "INSERT INTO watchlist_items(owner_id,ticker,name,added_at) VALUES(1,'AAPL','New owner','2026-10-03')"
        )
        conn.commit()
        conn.execute("DELETE FROM alert_rules WHERE id = 1")
        assert conn.execute("SELECT rule_id FROM alert_events").fetchone()[0] is None


def test_unicode_csrf_is_rejected_without_server_error(app):
    client = app.test_client()
    client.get("/login")
    assert client.post("/login", data={"csrf_token": "é" * 20}).status_code == 400


def test_authenticated_write_rate_limit(app):
    client = app.test_client()
    join(client, "alice")
    store = app.extensions["access_store"]
    for _ in range(60):
        assert store.consume("write:1", 60, 60) == 0
    assert (
        post(client, "/watchlist", {"ticker": "AAPL", "name": "Apple"}).status_code
        == 429
    )
