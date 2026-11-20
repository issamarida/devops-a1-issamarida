"""Sign-in tokens: only a token this secret signed, and not yet expired, is accepted."""

import jwt
import pytest

from app.tokens import (
    SNAPSHOT_SCOPE,
    is_service_token,
    issue_token,
    read_token,
)

SECRET = "test-only-token-secret-not-a-real-one"
OTHER_SECRET = "another-test-only-secret-also-not-real"


def service_token(secret=SECRET, lifetime=60):
    """What the alerts service sends: a scope, no account."""
    import time

    now = int(time.time())
    claims = {"sub": "alerts", "scope": SNAPSHOT_SCOPE, "iat": now, "exp": now + lifetime}
    return jwt.encode(claims, secret, algorithm="HS256")


def test_a_token_reads_back_as_its_account():
    token = issue_token(SECRET, 7, "investor", 3600)

    assert read_token(SECRET, token) == {"id": 7, "username": "investor"}


def test_a_token_is_three_parts_and_holds_no_password():
    token = issue_token(SECRET, 7, "investor", 3600)

    assert token.count(".") == 2
    # Anyone can read the claims. Only the signature is secret.
    claims = jwt.decode(token, options={"verify_signature": False})
    assert set(claims) == {"sub", "name", "iat", "exp"}
    assert claims["exp"] - claims["iat"] == 3600


def test_a_token_signed_with_another_secret_is_rejected():
    token = issue_token(OTHER_SECRET, 7, "investor", 3600)

    assert read_token(SECRET, token) is None


def test_an_expired_token_is_rejected():
    token = issue_token(SECRET, 7, "investor", -1)

    assert read_token(SECRET, token) is None


def test_a_changed_token_is_rejected():
    header, claims, signature = issue_token(SECRET, 7, "investor", 3600).split(".")
    other_claims = issue_token(SECRET, 8, "someone", 3600).split(".")[1]

    # Account 8's claims with account 7's signature.
    assert read_token(SECRET, f"{header}.{other_claims}.{signature}") is None


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "Bearer x"])
def test_text_that_is_not_a_token_is_rejected(token):
    assert read_token(SECRET, token) is None
    assert is_service_token(SECRET, token) is False


def test_an_unsigned_token_is_rejected():
    unsigned = jwt.encode({"sub": "7", "exp": 9999999999}, "", algorithm="none")

    assert read_token(SECRET, unsigned) is None


def test_a_token_without_an_expiry_is_rejected():
    forever = jwt.encode({"sub": "7"}, SECRET, algorithm="HS256")

    assert read_token(SECRET, forever) is None


def test_a_token_whose_account_is_not_a_number_is_rejected():
    odd = jwt.encode({"sub": "admin", "exp": 9999999999}, SECRET, algorithm="HS256")

    assert read_token(SECRET, odd) is None


def test_the_service_token_is_accepted_only_as_a_service_token():
    token = service_token()

    assert is_service_token(SECRET, token) is True
    assert read_token(SECRET, token) is None


def test_a_user_token_is_never_a_service_token():
    assert is_service_token(SECRET, issue_token(SECRET, 7, "investor", 3600)) is False


def test_an_expired_or_foreign_service_token_is_rejected():
    assert is_service_token(SECRET, service_token(lifetime=-1)) is False
    assert is_service_token(SECRET, service_token(secret=OTHER_SECRET)) is False
