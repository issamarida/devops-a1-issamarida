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
    quote_requests_per_minute: int = 50
    live_symbol_limit: int = 50

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

    poll_interval_seconds = read_int("POLL_INTERVAL_SECONDS", "5")
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
        ("QUOTE_REQUESTS_PER_MINUTE", "50"),
        ("LIVE_SYMBOL_LIMIT", "50"),
    ):
        limits[name] = read_int(name, default)
        if limits[name] <= 0:
            raise ValueError(f"{name} must be greater than 0")

    return Config(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=port,
        data_dir=Path(os.environ.get("DATA_DIR", "./data")),
        # An empty or whitespace-only key counts as not configured.
        price_api_key=os.environ.get("PRICE_API_KEY", "").strip() or None,
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
        live_symbol_limit=limits["LIVE_SYMBOL_LIMIT"],
    )


def load_env_file(path) -> None:
    """Read KEY=value lines from an optional .env file into the environment.

    A missing file is fine. A variable already set in the shell always wins,
    so the file is only a local convenience and never required.
    """
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        if name:
            os.environ.setdefault(name, value)


class RedactSecret:
    """Logging filter that replaces a secret with *** in every log line."""

    def __init__(self, secret: str | None):
        self.secret = secret

    def filter(self, record) -> bool:
        if self.secret and self.secret in record.getMessage():
            record.msg = record.getMessage().replace(self.secret, "***")
            record.args = None
        return True
