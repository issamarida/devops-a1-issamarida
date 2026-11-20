"""Signed tokens (JSON Web Tokens signed with HMAC-SHA256).

A token is three parts joined by dots: a header, the claims and a signature.
The signature is made with TOKEN_SECRET, which only the two services know,
so nobody else can make or change a token.

The watchlist service signs a user token at sign in. This service checks the
signature with the same secret, so it knows who is asking without calling the
watchlist. That keeps alerts working when the watchlist is stopped.
"""

import time

import jwt

ALGORITHM = "HS256"
SNAPSHOT_SCOPE = "snapshot"


def read_token(secret: str, token: str) -> dict | None:
    """The account a user token belongs to, or None if it is not a valid user token."""
    try:
        # Naming the algorithm stops a token that asks for a weaker one.
        claims = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
        )
    except jwt.InvalidTokenError:
        # Forged, changed or expired.
        return None
    if "scope" in claims or not claims["sub"].isdigit():
        return None
    return {"id": int(claims["sub"]), "username": str(claims.get("name", ""))}


def issue_service_token(secret: str, lifetime_seconds: int = 60) -> str:
    """What this service shows the watchlist when it asks for the snapshot.

    It names no account and stops working after a minute, so a copy of it is
    of little use to anyone who sees one.
    """
    now = int(time.time())
    claims = {
        "sub": "alerts",
        "scope": SNAPSHOT_SCOPE,
        "iat": now,
        "exp": now + lifetime_seconds,
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)
