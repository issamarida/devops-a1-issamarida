"""Watchlist domain: the assets the user tracks.

Never imports app.market. Prices and the snapshot for the alerts service
are put together in create_app.
"""

from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
