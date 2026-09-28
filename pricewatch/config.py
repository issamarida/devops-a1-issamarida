"""Runtime configuration, read entirely from environment variables.

No .env file is required: every setting has a default that lets
`python app.py` start cleanly right after clone + install.
"""

import os
from dataclasses import dataclass
from pathlib import Path

DB_FILENAME = "pricewatch.db"


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 8080
    data_dir: Path = Path("./data")
    price_api_key: str | None = None
    poll_interval_seconds: int = 60
    price_cache_ttl_seconds: int = 30
    secret_key: str = "dev-only-not-for-production"

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    @classmethod
    def from_env(cls, environ=None) -> "Config":
        env = os.environ if environ is None else environ
        return cls(
            host=env.get("HOST", cls.host),
            port=int(env.get("PORT", cls.port)),
            data_dir=Path(env.get("DATA_DIR", cls.data_dir)),
            price_api_key=env.get("PRICE_API_KEY") or None,
            poll_interval_seconds=int(env.get("POLL_INTERVAL_SECONDS", cls.poll_interval_seconds)),
            price_cache_ttl_seconds=int(
                env.get("PRICE_CACHE_TTL_SECONDS", cls.price_cache_ttl_seconds)
            ),
            secret_key=env.get("SECRET_KEY", cls.secret_key),
        )
