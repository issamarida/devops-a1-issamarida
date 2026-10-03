"""Real prices from the Finnhub quote API.

The key goes in a request header, never in the URL, and is never logged.
"""

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

import requests

from app.ports import PriceUnavailable

QUOTE_URL = "https://finnhub.io/api/v1/quote"


@dataclass(frozen=True)
class Quote:
    price: float
    previous_close: float | None  # None when Finnhub sends no usable close
    at: float  # Unix seconds of the quote, as reported by Finnhub


def is_price(value) -> bool:
    """A real positive number. bool is excluded because True would count as 1."""
    return type(value) in (int, float) and math.isfinite(value) and value > 0


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

    def get_price(self, ticker: str) -> float:
        return self.get_quote(ticker).price

    def get_quote(self, ticker: str) -> Quote:
        if not self.api_key:
            raise PriceUnavailable("Finnhub is not configured")
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
        if not isinstance(payload, dict) or not is_price(payload.get("c")):
            raise PriceUnavailable(f"No price for {ticker}") from None
        previous_close = payload.get("pc")
        at = payload.get("t")
        return Quote(
            price=float(payload["c"]),
            previous_close=float(previous_close) if is_price(previous_close) else None,
            at=float(at) if is_price(at) else time.time(),
        )
