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


def load_config() -> Config:
    return Config(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        data_dir=Path(os.environ.get("DATA_DIR", "./data")),
        # An empty PRICE_API_KEY counts as not set.
        price_api_key=os.environ.get("PRICE_API_KEY") or None,
        poll_interval_seconds=int(os.environ.get("POLL_INTERVAL_SECONDS", "60")),
        price_cache_ttl_seconds=int(os.environ.get("PRICE_CACHE_TTL_SECONDS", "30")),
        secret_key=os.environ.get("SECRET_KEY", "dev-only-not-for-production"),
    )
