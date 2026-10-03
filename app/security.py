"""Supporting access control, not a third business domain.

SQLite holds accounts, revocable sessions and fixed-window rate limits.
Neither business domain imports this module or knows about passwords/cookies.
"""

import hashlib
import math
import re
import secrets
import sqlite3
import time
from contextlib import closing

from flask import abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import get_connection

USERNAME = re.compile(r"[a-z0-9_]{3,30}")


class AccessStore:
    def __init__(self, db_path, max_accounts=50, clock=time.time):
        self.db_path = db_path
        self.max_accounts = max_accounts
        self.clock = clock
        # Unknown usernames still perform the same password-hash work.
        self.dummy_hash = generate_password_hash(secrets.token_urlsafe(32))
        with closing(get_connection(db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    session_hash TEXT,
                    expires_at REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS rate_limits (
                    key TEXT PRIMARY KEY,
                    attempts INTEGER NOT NULL,
                    reset_at REAL NOT NULL
                );
            """)

    def register(self, username, password):
        username = username.strip().lower()
        if not USERNAME.fullmatch(username):
            raise ValueError(
                "Use 3–30 lowercase letters, numbers or underscores for your username."
            )
        if not 15 <= len(password) <= 128:
            raise ValueError(
                "Use a password of 15–128 characters. A memorable passphrase works well."
            )
        password_hash = generate_password_hash(password)
        with closing(get_connection(self.db_path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if (
                conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
                >= self.max_accounts
            ):
                raise ValueError(
                    "Registration is unavailable. Please contact the app owner."
                )
            try:
                cursor = conn.execute(
                    "INSERT INTO accounts (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
            except sqlite3.IntegrityError:
                raise ValueError(
                    "Unable to create this account. Choose another username or sign in."
                ) from None
            return cursor.lastrowid

    def sign_in(self, username, password, lifetime):
        with closing(get_connection(self.db_path)) as conn, conn:
            user = conn.execute(
                "SELECT * FROM accounts WHERE username = ?", (username.strip().lower(),)
            ).fetchone()
            stored = user["password_hash"] if user else self.dummy_hash
            valid = check_password_hash(stored, password)
            if not user or not valid:
                return None
            token = secrets.token_urlsafe(32)
            conn.execute(
                "UPDATE accounts SET session_hash = ?, expires_at = ? WHERE id = ?",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    self.clock() + lifetime,
                    user["id"],
                ),
            )
            return {"user_id": user["id"], "token": token}

    def current_user(self, user_id, token):
        if not isinstance(user_id, int) or not isinstance(token, str):
            return None
        with closing(get_connection(self.db_path)) as conn:
            row = conn.execute(
                """SELECT id, username FROM accounts
                WHERE id = ? AND session_hash = ? AND expires_at > ?""",
                (user_id, hashlib.sha256(token.encode()).hexdigest(), self.clock()),
            ).fetchone()
        return dict(row) if row else None

    def sign_out(self, user_id, token):
        with closing(get_connection(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE accounts SET session_hash = NULL, expires_at = 0 "
                "WHERE id = ? AND session_hash = ?",
                (user_id, hashlib.sha256(token.encode()).hexdigest()),
            )

    def account_ids(self):
        with closing(get_connection(self.db_path)) as conn:
            return [
                row["id"] for row in conn.execute("SELECT id FROM accounts ORDER BY id")
            ]

    def consume(self, key, limit, window):
        """Atomically reserve an attempt. Return Retry-After seconds when blocked."""
        key = hashlib.sha256(key.encode()).hexdigest()
        now = self.clock()
        with closing(get_connection(self.db_path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM rate_limits WHERE reset_at <= ?", (now,))
            row = conn.execute(
                "SELECT * FROM rate_limits WHERE key = ?", (key,)
            ).fetchone()
            if row and row["attempts"] >= limit:
                return max(1, math.ceil(row["reset_at"] - now))
            conn.execute(
                """INSERT INTO rate_limits (key, attempts, reset_at) VALUES (?, 1, ?)
                ON CONFLICT(key) DO UPDATE SET attempts = attempts + 1""",
                (key, now + window),
            )
        return 0


def install_access(app, config):
    store = AccessStore(config.db_path, config.max_accounts)
    app.extensions["access_store"] = store
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.cookie_secure,
        PERMANENT_SESSION_LIFETIME=config.session_seconds,
        SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=16384,
        MAX_FORM_MEMORY_SIZE=16384,
        MAX_FORM_PARTS=12,
    )

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    def limit(key, attempts, window):
        retry = store.consume(key, attempts, window)
        if retry:
            response = app.make_response(
                (
                    render_template(
                        "auth.html",
                        mode="error",
                        error="Too many attempts. Please wait and try again.",
                    ),
                    429,
                )
            )
            response.headers["Retry-After"] = str(retry)
            return response
        return None

    @app.before_request
    def protect_request():
        g.csp_nonce = secrets.token_urlsafe(24)
        g.user = (
            None
            if request.endpoint == "health"
            else store.current_user(session.get("user_id"), session.get("token"))
        )
        if request.method == "POST":
            sent = request.form.get("csrf_token", "")
            expected = session.get("csrf", "")
            if (
                not sent
                or not expected
                or not secrets.compare_digest(sent.encode(), expected.encode())
            ):
                abort(
                    400,
                    description="This form has expired. Reload the page and try again.",
                )
        if request.blueprint == "market" and not g.user:
            return {"error": "Sign in to see prices."}, 401
        if (
            request.blueprint in ("watchlist", "alerts")
            or request.endpoint == "sign_out"
        ) and not g.user:
            return redirect(url_for("sign_in"), code=303)
        if g.user and request.method == "POST":
            response = limit(f"write:{g.user['id']}", 60, 60)
            if response is not None:
                return response
            if request.endpoint == "alerts.evaluate":
                return limit(f"evaluate:{g.user['id']}", 4, 60)

    @app.after_request
    def response_headers(response):
        nonce = getattr(g, "csp_nonce", "")
        response.headers["Content-Security-Policy"] = (
            f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
            "connect-src 'self'; img-src 'self' data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if config.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(400)
    @app.errorhandler(413)
    @app.errorhandler(404)
    def request_error(error):
        return render_template(
            "auth.html", mode="error", error=error.description
        ), error.code

    @app.route("/login", methods=["GET", "POST"])
    def sign_in():
        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            # remote_addr only: untrusted forwarding headers cannot bypass throttling.
            for key, count in (
                (f"login-ip:{request.remote_addr}", config.auth_attempts * 5),
                (f"login-user:{username}", config.auth_attempts),
            ):
                response = limit(key, count, config.auth_window_seconds)
                if response is not None:
                    return response
            password = request.form.get("password", "")
            result = (
                store.sign_in(username, password, config.session_seconds)
                if len(password) <= 128
                else None
            )
            if result:
                session.clear()
                session.update(result)
                session.permanent = True
                return redirect(url_for("watchlist.list_items"), code=303)
            error = "Incorrect username or password."
        return render_template(
            "auth.html", mode="login", error=error
        ), 401 if error else 200

    @app.route("/register", methods=["GET", "POST"])
    def register():
        error = None
        if request.method == "POST":
            response = limit(
                f"register:{request.remote_addr}",
                config.auth_attempts,
                config.auth_window_seconds,
            )
            if response is not None:
                return response
            try:
                store.register(
                    request.form.get("username", ""), request.form.get("password", "")
                )
            except ValueError as exc:
                error = str(exc)
            else:
                session.clear()
                flash("Account created. Sign in to your private workspace.", "success")
                return redirect(url_for("sign_in"), code=303)
        return render_template(
            "auth.html", mode="register", error=error
        ), 400 if error else 200

    @app.post("/logout")
    def sign_out():
        store.sign_out(session["user_id"], session["token"])
        session.clear()
        return redirect(url_for("sign_in"), code=303)

    return store
