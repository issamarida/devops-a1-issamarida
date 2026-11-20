"""Settings read from environment variables.

Every setting has a default except the one secret: TOKEN_SECRET must be set.
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    host: str
    port: int
    data_dir: Path
    watchlist_url: str
    watchlist_timeout_seconds: float
    poll_interval_seconds: int
    token_secret: str
    cors_origins: list[str]
    git_sha: str = "dev"
    max_alert_rules: int = 100

    @property
    def db_path(self) -> Path:
        return self.data_dir / "alerts.db"


def read_int(name: str, default: str) -> int:
    """Read a whole number from the environment. The error names the variable."""
    value = os.environ.get(name, default)
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {value!r}") from None


def read_float(name: str, default: str) -> float:
    """Read a number from the environment. The error names the variable."""
    value = os.environ.get(name, default)
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {value!r}") from None


def load_config() -> Config:
    port = read_int("PORT", "8002")
    if port < 1 or port > 65535:
        raise ValueError(f"PORT must be between 1 and 65535, got {port}")

    poll_interval_seconds = read_int("POLL_INTERVAL_SECONDS", "15")
    if poll_interval_seconds < 0:
        raise ValueError(
            f"POLL_INTERVAL_SECONDS must be 0 or more, got {poll_interval_seconds}"
        )

    # Where the watchlist service is. The default is its name in docker-compose.yml.
    watchlist_url = os.environ.get("WATCHLIST_URL", "http://watchlist:8001").strip()
    if not watchlist_url.startswith(("http://", "https://")):
        raise ValueError("WATCHLIST_URL must start with http:// or https://")

    # How long one call to the watchlist may take before we give up on it.
    watchlist_timeout_seconds = read_float("WATCHLIST_TIMEOUT_SECONDS", "3")
    if not 0 < watchlist_timeout_seconds <= 30:
        raise ValueError("WATCHLIST_TIMEOUT_SECONDS must be more than 0 and at most 30")

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

    max_alert_rules = read_int("MAX_ALERT_RULES", "100")
    if max_alert_rules <= 0:
        raise ValueError("MAX_ALERT_RULES must be greater than 0")

    return Config(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=port,
        data_dir=Path(os.environ.get("DATA_DIR", "./data")),
        watchlist_url=watchlist_url,
        watchlist_timeout_seconds=watchlist_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        token_secret=token_secret,
        cors_origins=cors_origins,
        # The image build sets this to the commit it was built from.
        git_sha=os.environ.get("GIT_SHA", "dev").strip() or "dev",
        max_alert_rules=max_alert_rules,
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
