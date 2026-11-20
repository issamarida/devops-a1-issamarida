"""Remembers each ticker's last price for a short time so we call the API less."""

import threading
import time

from app.ports import PriceSource


class CachedPriceSource:
    def __init__(self, source: PriceSource, ttl_seconds: float, clock=time.monotonic):
        self.source = source
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.prices = {}  # ticker -> (price, time it was fetched)
        self.quotes = {}  # ticker -> (Quote, time it was fetched)
        # The poller thread and the request threads share this cache.
        self.lock = threading.Lock()

    def get_price(self, ticker: str) -> float:
        return self.lookup(self.prices, ticker, self.source.get_price)

    def get_quote(self, ticker: str):
        """The full quote, for sources that have one (FinnhubSource does)."""
        return self.lookup(self.quotes, ticker, self.source.get_quote)

    def lookup(self, store: dict, ticker: str, fetch):
        with self.lock:
            now = self.clock()
            if ticker in store:
                value, fetched_at = store[ticker]
                if now - fetched_at < self.ttl_seconds:
                    return value
            # PriceUnavailable passes straight through, so a failure is never stored.
            value = fetch(ticker)
            for key in [k for k, v in store.items() if self.clock() - v[1] >= self.ttl_seconds]:
                del store[key]
            store[ticker] = (value, self.clock())
            return value
