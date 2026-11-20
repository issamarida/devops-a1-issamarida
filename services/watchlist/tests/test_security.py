"""Exercise real tokens, password hashes, access boundaries, CORS and throttling."""

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import jwt
import pytest

from app.db import get_connection
from app.security import AccessStore
from app.tokens import issue_token
from conftest import PASSWORD, TEST_TOKEN_SECRET

UI_ORIGIN = "http://localhost:8080"


def service_headers(secret=TEST_TOKEN_SECRET):
    """The short-lived token the alerts service signs for the snapshot."""
    now = int(time.time())
    claims = {"sub": "alerts", "scope": "snapshot", "iat": now, "exp": now + 60}
    return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm="HS256")}


def test_private_endpoints_need_a_token_but_health_is_public(client):
    assert client.get("/health").status_code == 200
    for path in ("/watchlist", "/api/quotes", "/api/search?q=A", "/api/details/AAPL"):
        response = client.get(path)
        assert response.status_code == 401
        assert response.get_json() == {"error": "Sign in to continue."}
    assert client.post("/watchlist", json={"ticker": "AAPL", "name": "Apple"}).status_code == 401
    assert client.delete("/watchlist/AAPL").status_code == 401


def test_sign_in_answers_with_a_token_and_sets_no_cookie(client, sign_up):
    sign_up("alice")

    response = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})

    assert response.status_code == 200
    body = response.get_json()
    assert body["username"] == "alice" and body["expires_in"] == 3600
    assert "Set-Cookie" not in response.headers
    assert client.get("/watchlist", headers={"Authorization": "Bearer " + body["token"]}).status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        issue_token("another-test-only-secret-also-not-real", 1, "alice", 3600),
        issue_token(TEST_TOKEN_SECRET, 1, "alice", -1),
        "not-a-token",
    ],
    ids=["signed with another secret", "expired", "not a token"],
)
def test_a_token_we_did_not_sign_or_that_expired_is_refused(client, sign_up, token):
    sign_up("alice")

    response = client.get("/watchlist", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_the_token_must_use_the_bearer_scheme(client, sign_up):
    token = sign_up("alice")["Authorization"].removeprefix("Bearer ")

    assert client.get("/watchlist", headers={"Authorization": token}).status_code == 401
    assert client.get("/watchlist", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_password_is_stored_as_a_hash(app, sign_up):
    sign_up("alice")

    with closing(get_connection(app.extensions["access_store"].db_path)) as conn:
        row = conn.execute("SELECT * FROM accounts").fetchone()

    assert PASSWORD not in row["password_hash"]
    assert row["password_hash"].startswith("scrypt:")


def test_users_cannot_read_or_delete_each_others_data(client, sign_up):
    alice, bob = sign_up("alice"), sign_up("bob")
    item = {"ticker": "AAPL", "name": "Private Apple", "notes": "Only Alice sees this"}
    client.post("/watchlist", json=item, headers=alice)

    assert client.get("/watchlist", headers=bob).get_json() == {"items": []}
    assert client.delete("/watchlist/AAPL", headers=bob).status_code == 404
    assert client.get("/api/details/AAPL", headers=bob).status_code == 404
    assert len(client.get("/watchlist", headers=alice).get_json()["items"]) == 1

    # A forged owner field never changes whose list is written to.
    forged = {"ticker": "MSFT", "name": "Bob only", "owner_id": 1}
    assert client.post("/watchlist", json=forged, headers=bob).status_code == 201
    tickers = [i["ticker"] for i in client.get("/watchlist", headers=alice).get_json()["items"]]
    assert tickers == ["AAPL"]


def test_login_rate_limit_survives_restart_and_ignores_forwarded_address(app, client, sign_up):
    sign_up("alice")  # the first sign in used one attempt
    wrong = {"username": "alice", "password": "wrong"}
    for _ in range(4):
        assert client.post("/auth/login", json=wrong).status_code == 401

    response = client.post(
        "/auth/login",
        json={"username": "alice", "password": PASSWORD},
        headers={"X-Forwarded-For": "203.0.113.3"},
    )

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert response.get_json() == {"error": "Too many attempts. Please wait and try again."}
    # The count is in the database, so a restart does not reset it.
    original = app.extensions["access_store"]
    reopened = AccessStore(original.db_path)
    assert reopened.consume("login-user:alice", 5, 900) > 0
    reopened.clock = lambda: original.clock() + 901
    assert reopened.consume("login-user:alice", 5, 900) == 0


def test_unknown_and_wrong_password_have_identical_answers(client, sign_up):
    sign_up("alice")

    answers = [
        client.post("/auth/login", json={"username": username, "password": "wrong"})
        for username in ("alice", "missing")
    ]

    assert [a.status_code for a in answers] == [401, 401]
    assert answers[0].get_json() == answers[1].get_json()


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


def test_registration_errors_are_json_and_then_throttled(client):
    bad = {"username": "a", "password": "short"}
    for _ in range(5):
        response = client.post("/auth/register", json=bad)
        assert response.status_code == 400
        assert "username" in response.get_json()["error"]

    good = {"username": "alice", "password": PASSWORD}
    assert client.post("/auth/register", json=good).status_code == 429


def test_rate_limit_reservation_is_atomic(app):
    store = app.extensions["access_store"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.consume("concurrent", 3, 60), range(8)))
    assert results.count(0) == 3


def test_authenticated_write_rate_limit(app, client, sign_up):
    alice = sign_up("alice")
    store = app.extensions["access_store"]
    for _ in range(60):
        assert store.consume("write:1", 60, 60) == 0

    response = client.post("/watchlist", json={"ticker": "AAPL", "name": "Apple"}, headers=alice)

    assert response.status_code == 429
    # Reading is never throttled.
    assert client.get("/watchlist", headers=alice).status_code == 200


def test_headers_and_request_size(client, sign_up):
    alice = sign_up("alice")

    response = client.get("/watchlist", headers=alice)

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    too_big = client.post("/watchlist", json={"notes": "x" * 20000}, headers=alice)
    assert too_big.status_code == 413
    assert "error" in too_big.get_json()


@pytest.mark.parametrize("body", [None, "plain text", "[1, 2]", '{"ticker": 5, "name": ["x"]}'])
def test_a_body_that_is_not_the_expected_json_is_a_clean_400(client, sign_up, body):
    alice = sign_up("alice")

    response = client.post(
        "/watchlist", data=body, content_type="application/json", headers=alice
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Ticker must be 1-10 letters, digits or dots."}
    assert client.post("/auth/login", data=body, content_type="application/json").status_code == 401


# The snapshot endpoint is for the alerts service only.


def test_snapshot_refuses_everyone_but_the_alerts_service(client, sign_up):
    alice = sign_up("alice")

    assert client.get("/internal/snapshot").status_code == 401
    # A signed-in user is not the alerts service.
    assert client.get("/internal/snapshot", headers=alice).status_code == 401
    wrong_secret = service_headers("another-test-only-secret-also-not-real")
    assert client.get("/internal/snapshot", headers=wrong_secret).status_code == 401

    assert client.get("/internal/snapshot", headers=service_headers()).status_code == 200


def test_the_service_token_does_not_open_a_users_data(client):
    assert client.get("/watchlist", headers=service_headers()).status_code == 401


# CORS: only the UI's own address may call this service from a browser.


def preflight(client, origin, method="POST"):
    return client.options(
        "/watchlist",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_cors_preflight_from_the_ui_is_allowed_without_a_token(client):
    response = preflight(client, UI_ORIGIN)

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == UI_ORIGIN
    allowed = response.headers["Access-Control-Allow-Headers"].lower()
    assert "authorization" in allowed and "content-type" in allowed
    assert "DELETE" in response.headers["Access-Control-Allow-Methods"]


def test_cors_headers_are_not_sent_to_any_other_origin(client, sign_up):
    alice = sign_up("alice")

    assert "Access-Control-Allow-Origin" not in preflight(client, "https://evil.example").headers
    response = client.get("/watchlist", headers=dict(alice, Origin="https://evil.example"))
    assert "Access-Control-Allow-Origin" not in response.headers


def test_an_error_answer_still_carries_the_cors_header(client):
    # Without it the browser hides the 401 from the UI and reports a network error.
    response = client.get("/watchlist", headers={"Origin": UI_ORIGIN})

    assert response.status_code == 401
    assert response.headers["Access-Control-Allow-Origin"] == UI_ORIGIN


def test_cors_origin_comes_from_the_environment(monkeypatch, prices):
    from app import create_app
    from app.config import load_config

    monkeypatch.setenv("CORS_ORIGINS", "https://ui.example/, https://second.example")
    client = create_app(load_config(), price_source=prices).test_client()

    assert preflight(client, "https://ui.example").headers["Access-Control-Allow-Origin"] == "https://ui.example"
    assert preflight(client, "https://second.example").headers["Access-Control-Allow-Origin"] == "https://second.example"
    assert "Access-Control-Allow-Origin" not in preflight(client, UI_ORIGIN).headers
