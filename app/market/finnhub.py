"""Real prices from the Finnhub quote API.

The key goes in a request header, never in the URL, and is never logged.
"""

import requests

from app.ports import PriceUnavailable

QUOTE_URL = "https://finnhub.io/api/v1/quote"


class FinnhubSource:
    def __init__(self, api_key: str, timeout: float = 5.0):
        self.api_key = api_key
        self.timeout = timeout

    def get_price(self, ticker: str) -> float:
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
        if not isinstance(price, (int, float)) or price <= 0:
            raise PriceUnavailable(f"No price for {ticker}") from None
        return float(price)
