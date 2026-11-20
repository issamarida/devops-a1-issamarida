"""Settings read from environment variables.

Every setting has a default except the two secrets: TOKEN_SECRET must be set,
and PRICE_API_KEY is optional (without it prices are simply unavailable).
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    host: str
    port: int
    data_dir: Path
    price_api_key: str | None
    price_cache_ttl_seconds: int
    token_secret: str
    cors_origins: list[str]
    git_sha: str = "dev"
    token_seconds: int = 3600
    auth_attempts: int = 5
    auth_window_seconds: int = 900
    max_accounts: int = 50
    max_watchlist_items: int = 30
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
    port = read_int("PORT", "8001")
    if port < 1 or port > 65535:
        raise ValueError(f"PORT must be between 1 and 65535, got {port}")

    price_cache_ttl_seconds = read_int("PRICE_CACHE_TTL_SECONDS", "30")
    if price_cache_ttl_seconds < 0:
        raise ValueError(
            f"PRICE_CACHE_TTL_SECONDS must be 0 or more, got {price_cache_ttl_seconds}"
        )

    # A secret, so it has no default. Both services must be given the same value.
    token_secret = os.environ.get("TOKEN_SECRET", "")
    if len(token_secret) < 32:
        raise ValueError("TOKEN_SECRET must be set to at least 32 characters")
    # The only web pages allowed to call this service from a browser.
    cors_origins = [
        origin.strip().rstrip("/")
        for origin in os.environ.get("CORS_ORIGINS", "http://localhost:8080").split(",")
        if origin.strip()
    ]
    limits = {}
    for name, default in (
        ("TOKEN_SECONDS", "3600"),
        ("AUTH_ATTEMPTS", "5"),
        ("AUTH_WINDOW_SECONDS", "900"),
        ("MAX_ACCOUNTS", "50"),
        ("MAX_WATCHLIST_ITEMS", "30"),
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
        price_cache_ttl_seconds=price_cache_ttl_seconds,
        token_secret=token_secret,
        cors_origins=cors_origins,
        # The image build sets this to the commit it was built from.
        git_sha=os.environ.get("GIT_SHA", "dev").strip() or "dev",
        token_seconds=limits["TOKEN_SECONDS"],
        auth_attempts=limits["AUTH_ATTEMPTS"],
        auth_window_seconds=limits["AUTH_WINDOW_SECONDS"],
        max_accounts=limits["MAX_ACCOUNTS"],
        max_watchlist_items=limits["MAX_WATCHLIST_ITEMS"],
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
