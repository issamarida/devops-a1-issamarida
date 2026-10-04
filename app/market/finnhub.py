"""Real market data from the Finnhub REST API.

The key goes in a request header, never in the URL, and is never logged.
Every REST call shares one rolling budget per minute (the free plan allows 60).
"""

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

import requests

from app.ports import PriceUnavailable

API_URL = "https://finnhub.io/api/v1"
QUOTE_URL = f"{API_URL}/quote"


@dataclass(frozen=True)
class Quote:
    price: float
    previous_close: float | None  # None when Finnhub sends no usable close
    at: float  # Unix seconds of the quote, as reported by Finnhub
    open: float | None = None
    high: float | None = None
    low: float | None = None


def is_price(value) -> bool:
    """A real positive number. bool is excluded because True would count as 1."""
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def price_or_none(value) -> float | None:
    return float(value) if is_price(value) else None


class FinnhubSource:
    def __init__(
        self,
        api_key: str | None,
        timeout: float = 5.0,
        requests_per_minute=30,
        clock=time.monotonic,
    ):
        self.api_key = (api_key or "").strip() or None
        self.timeout = timeout
        self.requests_per_minute = requests_per_minute
        self.clock = clock
        self.calls = deque()
        self.lock = threading.Lock()

    def take_budget(self, keep_free: int) -> bool:
        """Count one call if the budget allows it, leaving keep_free calls for quotes."""
        with self.lock:
            now = self.clock()
            while self.calls and now - self.calls[0] >= 60:
                self.calls.popleft()
            if len(self.calls) + keep_free >= self.requests_per_minute:
                return False
            self.calls.append(now)
            return True

    def fetch(self, url: str, params: dict):
        """One GET to Finnhub. Returns the parsed JSON, or None on any failure."""
        try:
            response = requests.get(
                url,
                params=params,
                headers={"X-Finnhub-Token": self.api_key},
                timeout=self.timeout,
            )
            if response.status_code != 200:
                return None
            return response.json()
        except (requests.RequestException, ValueError):
            # The error text can hold request details, so it is dropped.
            return None

    def get_json(self, path: str, params: dict, keep_free: int = 10):
        """Extra data like market status or search. Never uses the last calls quotes need."""
        if not self.api_key or not self.take_budget(keep_free):
            return None
        return self.fetch(f"{API_URL}/{path}", params)

    def get_price(self, ticker: str) -> float:
        return self.get_quote(ticker).price

    def get_quote(self, ticker: str) -> Quote:
        if not self.api_key:
            raise PriceUnavailable("Finnhub is not configured")
        if not self.take_budget(0):
            raise PriceUnavailable(f"Quote budget reached for {ticker}")
        payload = self.fetch(QUOTE_URL, {"symbol": ticker})
        # Finnhub answers 200 with c = 0 for a ticker it doesn't know.
        if not isinstance(payload, dict) or not is_price(payload.get("c")):
            raise PriceUnavailable(f"No price for {ticker}") from None
        at = payload.get("t")
        return Quote(
            price=float(payload["c"]),
            previous_close=price_or_none(payload.get("pc")),
            at=float(at) if is_price(at) else time.time(),
            open=price_or_none(payload.get("o")),
            high=price_or_none(payload.get("h")),
            low=price_or_none(payload.get("l")),
        )
