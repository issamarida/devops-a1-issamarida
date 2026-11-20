"""Access control for the alerts service. Not a business domain.

This service holds no accounts and no passwords. A request carries the token
the watchlist service signed at sign in, and app/tokens.py checks it here.
"""

from flask import g, request

from app.tokens import read_token


def bearer_token() -> str:
    """The token from "Authorization: Bearer <token>", or "" if there is none."""
    header = request.headers.get("Authorization", "")
    return header[7:] if header.startswith("Bearer ") else ""


def install_access(app, config) -> None:
    # No request body here needs more than a few hundred bytes.
    app.config["MAX_CONTENT_LENGTH"] = 16384

    @app.before_request
    def protect_request():
        g.user = None
        if request.method == "OPTIONS":
            # The browser's CORS preflight carries no token. Flask-CORS answers it.
            return None
        if request.blueprint == "alerts":
            g.user = read_token(config.token_secret, bearer_token())
            if not g.user:
                return {"error": "Sign in to continue."}, 401
        return None

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response
