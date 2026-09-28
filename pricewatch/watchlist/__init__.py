"""Watchlist domain: which assets the user tracks.

Must not import pricewatch.alerts or pricewatch.market. It satisfies
pricewatch.ports.WatchlistReader structurally via WatchlistService.is_watched.
"""

from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
