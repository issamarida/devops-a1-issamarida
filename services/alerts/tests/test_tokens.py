"""Tokens on the alerts side: check the user's token, sign the service token."""

import time

import jwt
import pytest

from app.tokens import SNAPSHOT_SCOPE, issue_service_token, read_token

SECRET = "test-only-token-secret-not-a-real-one"
OTHER_SECRET = "another-test-only-secret-also-not-real"


def user_token(secret=SECRET, lifetime=3600, **changes):
    """Signed the way the watchlist service signs one at sign in."""
    now = int(time.time())
    claims = {"sub": "7", "name": "investor", "iat": now, "exp": now + lifetime}
    claims.update(changes)
    return jwt.encode(claims, secret, algorithm="HS256")


def test_a_token_from_the_watchlist_reads_back_as_its_account():
    assert read_token(SECRET, user_token()) == {"id": 7, "username": "investor"}


def test_a_token_signed_with_another_secret_is_rejected():
    assert read_token(SECRET, user_token(secret=OTHER_SECRET)) is None


def test_an_expired_token_is_rejected():
    assert read_token(SECRET, user_token(lifetime=-1)) is None


def test_a_changed_token_is_rejected():
    header, _, signature = user_token().split(".")
    other_claims = user_token(sub="8").split(".")[1]

    # Account 8's claims with account 7's signature.
    assert read_token(SECRET, f"{header}.{other_claims}.{signature}") is None


@pytest.mark.parametrize("token", ["", "abc", "a.b.c"])
def test_text_that_is_not_a_token_is_rejected(token):
    assert read_token(SECRET, token) is None


def test_an_unsigned_token_is_rejected():
    unsigned = jwt.encode({"sub": "7", "exp": 9999999999}, "", algorithm="none")

    assert read_token(SECRET, unsigned) is None


def test_a_token_without_an_expiry_is_rejected():
    assert read_token(SECRET, jwt.encode({"sub": "7"}, SECRET, algorithm="HS256")) is None


def test_a_token_whose_account_is_not_a_number_is_rejected():
    assert read_token(SECRET, user_token(sub="admin")) is None


def test_the_service_token_has_the_snapshot_scope_and_lasts_a_minute():
    claims = jwt.decode(issue_service_token(SECRET), SECRET, algorithms=["HS256"])

    assert claims["scope"] == SNAPSHOT_SCOPE
    assert claims["sub"] == "alerts"
    assert claims["exp"] - claims["iat"] == 60


def test_the_service_token_is_never_read_as_a_user():
    assert read_token(SECRET, issue_service_token(SECRET)) is None
