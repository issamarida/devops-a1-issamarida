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
        # The poller thread and the request threads share this cache.
        self.lock = threading.Lock()

    def get_price(self, ticker: str) -> float:
        with self.lock:
            now = self.clock()
            if ticker in self.prices:
                price, fetched_at = self.prices[ticker]
                if now - fetched_at < self.ttl_seconds:
                    return price
            # PriceUnavailable passes straight through, so a failure is never stored.
            price = self.source.get_price(ticker)
            self.prices[ticker] = (price, now)
            return price
