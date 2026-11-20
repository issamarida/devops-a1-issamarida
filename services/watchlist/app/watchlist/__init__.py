"""Watchlist domain: the assets the user tracks.

Never imports app.alerts or app.market. WatchlistService.is_watched
matches app.ports.WatchlistReader without importing it.
"""

from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
