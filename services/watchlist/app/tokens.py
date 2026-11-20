"""Signed tokens (JSON Web Tokens signed with HMAC-SHA256).

A token is three parts joined by dots: a header, the claims and a signature.
The signature is made with TOKEN_SECRET, which only the two services know,
so nobody else can make or change a token.

This service signs a user token at sign in and checks it on every later
request. The alerts service checks the same tokens with the same secret, so
it never has to call this service to know who is asking.
"""

import time

import jwt

ALGORITHM = "HS256"
SNAPSHOT_SCOPE = "snapshot"


def issue_token(secret: str, account_id: int, username: str, lifetime_seconds: int) -> str:
    """A user token. "sub" is the account ID and "exp" is when it stops working."""
    now = int(time.time())
    claims = {
        "sub": str(account_id),
        "name": username,
        "iat": now,
        "exp": now + lifetime_seconds,
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def read_claims(secret: str, token: str) -> dict | None:
    """The claims of a token we signed, or None if it is forged, changed or expired."""
    try:
        # Naming the algorithm stops a token that asks for a weaker one.
        return jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
        )
    except jwt.InvalidTokenError:
        return None


def read_token(secret: str, token: str) -> dict | None:
    """The account a user token belongs to, or None if it is not a valid user token."""
    claims = read_claims(secret, token)
    # A service token has a scope and no account, so it is never a user.
    if claims is None or "scope" in claims or not claims["sub"].isdigit():
        return None
    return {"id": int(claims["sub"]), "username": str(claims.get("name", ""))}


def is_service_token(secret: str, token: str) -> bool:
    """True for the short-lived token the alerts service signs for the snapshot."""
    claims = read_claims(secret, token)
    return claims is not None and claims.get("scope") == SNAPSHOT_SCOPE
