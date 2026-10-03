"""Real prices from the Finnhub quote API.

The key goes in a request header, never in the URL, and is never logged.
"""

import math
import threading
import time
from collections import deque

import requests

from app.ports import PriceUnavailable

QUOTE_URL = "https://finnhub.io/api/v1/quote"


class FinnhubSource:
    def __init__(
        self,
        api_key: str,
        timeout: float = 5.0,
        requests_per_minute=30,
        clock=time.monotonic,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.requests_per_minute = requests_per_minute
        self.clock = clock
        self.calls = deque()
        self.lock = threading.Lock()

    def get_price(self, ticker: str) -> float:
        with self.lock:
            now = self.clock()
            while self.calls and now - self.calls[0] >= 60:
                self.calls.popleft()
            if len(self.calls) >= self.requests_per_minute:
                raise PriceUnavailable(f"Quote budget reached for {ticker}")
            self.calls.append(now)
        try:
            response = requests.get(
                QUOTE_URL,
                params={"symbol": ticker},
                headers={"X-Finnhub-Token": self.api_key},
                timeout=self.timeout,
            )
        except requests.RequestException:
            # "from None" drops the original error, which can hold the request details.
            raise PriceUnavailable(f"No price for {ticker}") from None

        if response.status_code != 200:
            raise PriceUnavailable(f"No price for {ticker}") from None

        try:
            payload = response.json()
        except ValueError:
            raise PriceUnavailable(f"No price for {ticker}") from None

        # Finnhub answers 200 with c = 0 for a ticker it doesn't know.
        price = payload.get("c") if isinstance(payload, dict) else None
        if type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
            raise PriceUnavailable(f"No price for {ticker}") from None
        return float(price)
