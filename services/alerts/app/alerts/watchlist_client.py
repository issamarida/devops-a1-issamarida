"""Reaches the watchlist service over HTTP. This is the seam between the two services.

One GET returns every account's watched tickers and the prices that were asked for:

    GET /internal/snapshot?tickers=AAPL,MSFT

    {"owners": {"7": ["AAPL", "MSFT"]}, "prices": {"AAPL": 187.44, "MSFT": null}}

RemoteWatchlist answers is_watched and get_price from that one answer, so it
fits both interfaces in app.ports without a request per rule.
"""

import math

import requests

from app.ports import PriceUnavailable, WatchlistUnavailable

SNAPSHOT_PATH = "/internal/snapshot"


def is_snapshot(body) -> bool:
    """True if the answer has the shape shown at the top of this file."""
    if not isinstance(body, dict):
        return False
    owners, prices = body.get("owners"), body.get("prices")
    if not isinstance(owners, dict) or not isinstance(prices, dict):
        return False
    return all(isinstance(tickers, list) for tickers in owners.values())


def fetch_snapshot(base_url: str, timeout_seconds: float, token: str = "", tickers=()) -> dict:
    """One GET to the watchlist service. Raises WatchlistUnavailable on any failure.

    token proves to the watchlist that the alerts service is asking. tickers are
    the ones whose prices are needed: leave it empty to only learn who watches what.
    """
    params = {"tickers": ",".join(sorted(set(tickers)))} if tickers else {}
    try:
        # The timeout covers connecting and each wait for data, so a stopped
        # or silent watchlist cannot hang the caller.
        response = requests.get(
            base_url.rstrip("/") + SNAPSHOT_PATH,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
        )
    except requests.RequestException:
        # Timeout, refused connection or unknown host. The error text is dropped.
        raise WatchlistUnavailable("The watchlist service did not answer") from None
    if response.status_code != 200:
        raise WatchlistUnavailable(
            f"The watchlist service answered {response.status_code}"
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    if not is_snapshot(body):
        raise WatchlistUnavailable("The watchlist service sent an unexpected answer")
    return body


class Snapshot:
    """One answer from the watchlist, fetched on first use and at most once.

    A failure is remembered too, so one request or one poller run never waits
    for the timeout twice. Make a new Snapshot for each request and each run.
    """

    def __init__(self, fetch):
        self.fetch = fetch  # a function with no arguments that returns the answer
        self.body = None
        self.error = None

    def get(self) -> dict:
        if self.error is not None:
            raise self.error
        if self.body is None:
            try:
                self.body = self.fetch()
            except WatchlistUnavailable as error:
                self.error = error
                raise
        return self.body


class RemoteWatchlist:
    """One account's view of a snapshot. Fits WatchlistReader and PriceSource."""

    def __init__(self, snapshot: Snapshot, owner_id: int):
        self.snapshot = snapshot
        self.owner_id = owner_id

    def is_watched(self, ticker: str) -> bool:
        # JSON object keys are always text, so the account ID is looked up as text.
        owners = self.snapshot.get()["owners"]
        return ticker in owners.get(str(self.owner_id), [])

    def get_price(self, ticker: str) -> float:
        price = self.snapshot.get()["prices"].get(ticker)
        if type(price) not in (float, int) or not math.isfinite(price) or price <= 0:
            raise PriceUnavailable(f"No price for {ticker}")
        return float(price)
