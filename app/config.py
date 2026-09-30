"""Settings read from environment variables. Every one has a default."""

import os
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
        raise ValueError(f"POLL_INTERVAL_SECONDS must be 0 or more, got {poll_interval_seconds}")

    price_cache_ttl_seconds = read_int("PRICE_CACHE_TTL_SECONDS", "30")
    if price_cache_ttl_seconds < 0:
        raise ValueError(
            f"PRICE_CACHE_TTL_SECONDS must be 0 or more, got {price_cache_ttl_seconds}"
        )

    return Config(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=port,
        data_dir=Path(os.environ.get("DATA_DIR", "./data")),
        # An empty PRICE_API_KEY counts as not set.
        price_api_key=os.environ.get("PRICE_API_KEY") or None,
        poll_interval_seconds=poll_interval_seconds,
        price_cache_ttl_seconds=price_cache_ttl_seconds,
        secret_key=os.environ.get("SECRET_KEY", "dev-only-not-for-production"),
    )
