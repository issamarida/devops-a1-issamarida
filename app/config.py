"""Settings read from environment variables. Every one has a default."""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    host: str
    port: int
    data_dir: Path
    price_api_key: str | None
    poll_interval_seconds: int
    price_cache_ttl_seconds: int
    secret_key: str
    cookie_secure: bool = False
    session_seconds: int = 3600
    auth_attempts: int = 5
    auth_window_seconds: int = 900
    max_accounts: int = 50
    max_watchlist_items: int = 30
    max_alert_rules: int = 100
    quote_requests_per_minute: int = 30

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"


def read_int(name: str, default: str) -> int:
    """Read a whole number from the environment. The error names the variable."""
    value = os.environ.get(name, default)
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {value!r}") from None


def load_config() -> Config:
    port = read_int("PORT", "8080")
    if port < 1 or port > 65535:
        raise ValueError(f"PORT must be between 1 and 65535, got {port}")

    poll_interval_seconds = read_int("POLL_INTERVAL_SECONDS", "60")
    if poll_interval_seconds < 0:
        raise ValueError(
            f"POLL_INTERVAL_SECONDS must be 0 or more, got {poll_interval_seconds}"
        )

    price_cache_ttl_seconds = read_int("PRICE_CACHE_TTL_SECONDS", "30")
    if price_cache_ttl_seconds < 0:
        raise ValueError(
            f"PRICE_CACHE_TTL_SECONDS must be 0 or more, got {price_cache_ttl_seconds}"
        )

    secret_key = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32)
    if len(secret_key) < 32:
        raise ValueError("SECRET_KEY must contain at least 32 characters")
    secure = os.environ.get("SESSION_COOKIE_SECURE", "false").lower()
    if secure not in ("true", "false"):
        raise ValueError("SESSION_COOKIE_SECURE must be true or false")
    limits = {}
    for name, default in (
        ("SESSION_SECONDS", "3600"),
        ("AUTH_ATTEMPTS", "5"),
        ("AUTH_WINDOW_SECONDS", "900"),
        ("MAX_ACCOUNTS", "50"),
        ("MAX_WATCHLIST_ITEMS", "30"),
        ("MAX_ALERT_RULES", "100"),
        ("QUOTE_REQUESTS_PER_MINUTE", "30"),
    ):
        limits[name] = read_int(name, default)
        if limits[name] <= 0:
            raise ValueError(f"{name} must be greater than 0")

    return Config(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=port,
        data_dir=Path(os.environ.get("DATA_DIR", "./data")),
        # An empty PRICE_API_KEY counts as not set.
        price_api_key=os.environ.get("PRICE_API_KEY") or None,
        poll_interval_seconds=poll_interval_seconds,
        price_cache_ttl_seconds=price_cache_ttl_seconds,
        secret_key=secret_key,
        cookie_secure=secure == "true",
        session_seconds=limits["SESSION_SECONDS"],
        auth_attempts=limits["AUTH_ATTEMPTS"],
        auth_window_seconds=limits["AUTH_WINDOW_SECONDS"],
        max_accounts=limits["MAX_ACCOUNTS"],
        max_watchlist_items=limits["MAX_WATCHLIST_ITEMS"],
        max_alert_rules=limits["MAX_ALERT_RULES"],
        quote_requests_per_minute=limits["QUOTE_REQUESTS_PER_MINUTE"],
    )
