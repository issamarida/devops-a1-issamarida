"""Market context for the dashboard: is the market open, symbol search, company details.

Each answer is kept for a while so the shared Finnhub budget stays free for quotes.
A failed call is never stored, so it is retried on the next request.
"""

import threading
import time

from app.market.finnhub import FinnhubSource, is_price

STATUS_SECONDS = 60
SEARCH_SECONDS = 3600
DETAILS_SECONDS = 6 * 3600


class MarketInfo:
    def __init__(self, source: FinnhubSource, clock=time.monotonic):
        self.source = source
        self.clock = clock
        self.saved = {}  # key -> (value, time saved)
        self.lock = threading.Lock()

    def remembered(self, key, max_age, fetch):
        with self.lock:
            if key in self.saved and self.clock() - self.saved[key][1] < max_age:
                return self.saved[key][0]
        value = fetch()
        if value is not None:
            with self.lock:
                self.saved[key] = (value, self.clock())
        return value

    def market_status(self) -> dict | None:
        """US market state: open or closed, the session name and any holiday."""

        def fetch():
            payload = self.source.get_json("stock/market-status", {"exchange": "US"})
            if not isinstance(payload, dict) or not isinstance(payload.get("isOpen"), bool):
                return None
            return {
                "open": payload["isOpen"],
                "session": payload.get("session") if isinstance(payload.get("session"), str) else None,
                "holiday": payload.get("holiday") if isinstance(payload.get("holiday"), str) else None,
            }

        return self.remembered("status", STATUS_SECONDS, fetch)

    def search(self, query: str) -> list[dict]:
        """Up to eight US stocks whose symbol or name matches the query."""
        query = query.strip().upper()
        if not query or len(query) > 20:
            return []

        def fetch():
            payload = self.source.get_json("search", {"q": query, "exchange": "US"})
            if not isinstance(payload, dict) or not isinstance(payload.get("result"), list):
                return None
            matches = []
            for item in payload["result"]:
                if not isinstance(item, dict):
                    continue
                symbol, name = item.get("symbol"), item.get("description")
                if isinstance(symbol, str) and isinstance(name, str) and symbol and name:
                    matches.append({"symbol": symbol, "name": name.title()})
            return matches[:8]

        return self.remembered(("search", query), SEARCH_SECONDS, fetch) or []

    def details(self, ticker: str) -> dict | None:
        """Company name, industry, market cap and the 52 week range."""

        def fetch():
            profile = self.source.get_json("stock/profile2", {"symbol": ticker})
            if not isinstance(profile, dict) or not profile.get("name"):
                return None
            metrics = self.source.get_json("stock/metric", {"symbol": ticker, "metric": "all"})
            metric = metrics.get("metric") if isinstance(metrics, dict) else None
            metric = metric if isinstance(metric, dict) else {}
            cap = profile.get("marketCapitalization")
            return {
                "name": str(profile["name"]),
                "industry": str(profile.get("finnhubIndustry") or ""),
                "exchange": str(profile.get("exchange") or ""),
                # Finnhub reports market cap in millions of USD.
                "market_cap": cap * 1_000_000 if is_price(cap) else None,
                "year_high": metric.get("52WeekHigh") if is_price(metric.get("52WeekHigh")) else None,
                "year_low": metric.get("52WeekLow") if is_price(metric.get("52WeekLow")) else None,
            }

        return self.remembered(("details", ticker), DETAILS_SECONDS, fetch)
