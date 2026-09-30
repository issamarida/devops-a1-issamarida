"""Made-up prices for when no API key is set. No network."""

import hashlib
import time

WINDOW_SECONDS = 30


def hash_fraction(text: str) -> float:
    """Turn any text into a number from 0 to 1. The same text always gives the same number."""
    digest = hashlib.sha256(text.encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


class DemoPriceSource:
    def __init__(self, clock=time.time):
        self.clock = clock

    def get_price(self, ticker: str) -> float:
        ticker = ticker.upper()
        # The base price only depends on the ticker: between 10 and 500.
        base = 10 + hash_fraction(ticker) * 490
        # The offset changes every 30 seconds: between -5% and +5%.
        window = int(self.clock()) // WINDOW_SECONDS
        offset = -0.05 + hash_fraction(f"{ticker}:{window}") * 0.10
        return round(base * (1 + offset), 2)
