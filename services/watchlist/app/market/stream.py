"""Live trade prices from the Finnhub WebSocket.

The process keeps one connection to Finnhub. Browsers never connect to
Finnhub: they read prices from /api/quotes, so the key stays on the server.
The key is part of the connection URL (Finnhub's only option for WebSockets)
and that URL is never logged.

app.py starts the threads. create_app only builds the objects, so tests never
open a connection.
"""

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

import websocket

from app.market.finnhub import is_price
from app.ports import PriceUnavailable

STREAM_URL = "wss://ws.finnhub.io"
# The sparkline keeps one point per 5 seconds, so 240 points cover 20 minutes.
POINT_SECONDS = 5
MAX_POINTS = 240

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Trade:
    price: float
    at: float  # Unix seconds of the trade, from Finnhub
    received: float  # Unix seconds when this process got it


class FinnhubStream:
    def __init__(
        self,
        api_key: str | None,
        symbols,
        max_symbols: int = 50,
        refresh_seconds: float = 5,
        clock=time.time,
        connect=websocket.WebSocketApp,
    ):
        self.api_key = (api_key or "").strip() or None
        # symbols() returns the tickers to follow, most watched first.
        self.symbols = symbols
        self.max_symbols = max_symbols
        self.refresh_seconds = refresh_seconds
        self.clock = clock
        self.connect = connect
        self.trades = {}  # ticker -> newest Trade
        self.points = {}  # ticker -> deque of (time, price) for the sparkline
        self.subscribed = set()
        self.ws = None
        self.connected = False
        # The stream thread writes trades while request threads read them.
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.wake = threading.Event()

    @property
    def enabled(self) -> bool:
        return self.api_key is not None

    def latest(self, ticker: str) -> Trade | None:
        with self.lock:
            return self.trades.get(ticker)

    def recent(self, ticker: str) -> list[float]:
        """Recent trade prices, oldest first, for the sparkline."""
        with self.lock:
            return [price for _, price in self.points.get(ticker, ())]

    def add_point(self, ticker, at, price) -> None:
        """Start a new point every POINT_SECONDS, otherwise move the last one."""
        points = self.points.setdefault(ticker, deque(maxlen=MAX_POINTS))
        if points and at - points[-1][0] < POINT_SECONDS:
            points[-1] = (points[-1][0], price)
        else:
            points.append((at, price))

    def follow(self, tickers) -> None:
        """Ask for a quick resync when a page needs a ticker we don't stream yet."""
        with self.lock:
            missing = self.connected and not set(tickers) <= self.subscribed
        if missing:
            self.wake.set()

    def handle_message(self, raw) -> None:
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not isinstance(message, dict):
            return
        if message.get("type") == "error":
            logger.warning("Finnhub stream refused a request: %s", str(message.get("msg"))[:120])
            return
        # Finnhub also sends {"type": "ping"}, which needs no reply.
        if message.get("type") != "trade" or not isinstance(message.get("data"), list):
            return
        received = self.clock()
        with self.lock:
            for item in message["data"]:
                if not isinstance(item, dict):
                    continue
                ticker, price, at_ms = item.get("s"), item.get("p"), item.get("t")
                if ticker not in self.subscribed or not is_price(price) or not is_price(at_ms):
                    continue
                current = self.trades.get(ticker)
                # One message can hold many trades, not always in time order.
                if current is None or at_ms / 1000 >= current.at:
                    self.trades[ticker] = Trade(float(price), at_ms / 1000, received)
                    self.add_point(ticker, at_ms / 1000, float(price))

    def sync(self) -> None:
        """Subscribe to newly watched tickers and drop the ones nobody watches."""
        try:
            wanted = set(list(self.symbols())[: self.max_symbols])
        except Exception:
            logger.exception("Could not read the tickers to stream")
            return
        with self.lock:
            if not self.connected or self.ws is None:
                return
            ws = self.ws
            added = sorted(wanted - self.subscribed)
            removed = sorted(self.subscribed - wanted)
            self.subscribed = (self.subscribed | set(added)) - set(removed)
            for ticker in removed:
                self.trades.pop(ticker, None)
                self.points.pop(ticker, None)
        try:
            for ticker in added:
                ws.send(json.dumps({"type": "subscribe", "symbol": ticker}))
            for ticker in removed:
                ws.send(json.dumps({"type": "unsubscribe", "symbol": ticker}))
        except Exception as error:
            # The connection dropped mid-send. on_open subscribes again after reconnect.
            logger.warning("Finnhub stream send failed: %s", type(error).__name__)

    def on_open(self, ws) -> None:
        with self.lock:
            self.connected = True
            self.subscribed = set()
        logger.info("Finnhub stream connected")
        self.sync()

    def on_message(self, ws, raw) -> None:
        self.handle_message(raw)

    def on_error(self, ws, error) -> None:
        # Only the type and HTTP status: a connection error's message can include the URL.
        status = getattr(error, "status_code", None)
        hint = " (HTTP 401: check PRICE_API_KEY)" if status == 401 else f" (HTTP {status})" if status else ""
        logger.warning("Finnhub stream error: %s%s", type(error).__name__, hint)

    def on_close(self, ws, *args) -> None:
        with self.lock:
            self.connected = False

    def run(self) -> None:
        """Keep one connection open, reconnecting with a growing delay."""
        delay = 1
        while not self.stop_event.is_set():
            opened_at = self.clock()
            ws = self.connect(
                f"{STREAM_URL}?token={self.api_key}",
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
            )
            with self.lock:
                self.ws = ws
            try:
                ws.run_forever(ping_interval=30, ping_timeout=10, reconnect=0)
            except Exception as error:
                logger.warning("Finnhub stream stopped: %s", type(error).__name__)
            with self.lock:
                self.connected = False
                self.ws = None
            if self.stop_event.is_set():
                break
            # A connection that lasted a minute was healthy, so start the delay again.
            if self.clock() - opened_at > 60:
                delay = 1
            logger.info("Finnhub stream reconnecting in %s seconds", delay)
            self.stop_event.wait(delay)
            delay = min(delay * 2, 60)

    def keep_symbols_in_sync(self) -> None:
        while not self.stop_event.is_set():
            self.wake.wait(self.refresh_seconds)
            self.wake.clear()
            self.sync()

    def start(self) -> list[threading.Thread]:
        """Start the connection and subscription threads. No key means no threads."""
        if not self.enabled:
            logger.warning("Live prices are off because PRICE_API_KEY is not set")
            return []
        threads = [
            threading.Thread(target=self.run, name="finnhub-stream", daemon=True),
            threading.Thread(
                target=self.keep_symbols_in_sync, name="finnhub-symbols", daemon=True
            ),
        ]
        for thread in threads:
            thread.start()
        return threads

    def stop(self) -> None:
        self.stop_event.set()
        self.wake.set()
        with self.lock:
            ws = self.ws
        if ws is not None:
            ws.close()


class LivePrices:
    """The PriceSource for alerts, plus the price snapshot the browser polls.

    A fresh streamed trade wins. Otherwise the cached REST quote is used.
    """

    def __init__(self, stream, quotes, max_trade_age=60, baseline_age=900, clock=time.time):
        self.stream = stream
        self.quotes = quotes  # CachedPriceSource around FinnhubSource
        self.max_trade_age = max_trade_age
        self.baseline_age = baseline_age
        self.clock = clock
        self.last_quotes = {}  # ticker -> (Quote, time fetched), for display only
        self.lock = threading.Lock()

    def fresh_trade(self, ticker) -> Trade | None:
        trade = self.stream.latest(ticker)
        if trade is not None and self.clock() - trade.received <= self.max_trade_age:
            return trade
        return None

    def get_price(self, ticker: str) -> float:
        trade = self.fresh_trade(ticker)
        if trade is not None:
            return trade.price
        # Raises PriceUnavailable. Alerts never fire on an old or made-up price.
        return self.quotes.get_quote(ticker).price

    def baseline(self, ticker, have_trade):
        """The latest REST quote. With a live trade, an older one is fine for the change."""
        with self.lock:
            saved = self.last_quotes.get(ticker)
        if have_trade and saved and self.clock() - saved[1] < self.baseline_age:
            return saved[0]
        try:
            quote = self.quotes.get_quote(ticker)
        except PriceUnavailable:
            # Keep showing the last real quote rather than nothing.
            return saved[0] if saved else None
        with self.lock:
            if saved is None or saved[0] is not quote:
                self.last_quotes[ticker] = (quote, self.clock())
        return quote

    def snapshot(self, tickers) -> dict:
        tickers = list(tickers)
        self.stream.follow(tickers)
        quotes = {}
        for ticker in tickers:
            trade = self.fresh_trade(ticker)
            quote = self.baseline(ticker, trade is not None)
            if trade is not None and (quote is None or trade.at >= quote.at):
                price, at, source = trade.price, trade.at, "live"
            elif quote is not None:
                price, at, source = quote.price, quote.at, "quote"
            else:
                quotes[ticker] = None
                continue
            close = quote.previous_close if quote else None
            change = price - close if close else None
            # A live trade can set a new day high or low before the REST quote knows.
            high = max(quote.high, price) if quote and quote.high else None
            low = min(quote.low, price) if quote and quote.low else None
            quotes[ticker] = {
                "price": round(price, 4),
                "change": round(change, 4) if change is not None else None,
                "percent": round(change / close * 100, 2) if change is not None else None,
                "source": source,
                "at": at,
                "previous_close": close,
                "open": quote.open if quote else None,
                "high": high,
                "low": low,
                "spark": self.stream.recent(ticker),
            }
        if not self.stream.enabled:
            status = "offline"
        elif self.stream.connected:
            status = "live"
        else:
            status = "connecting"
        return {"status": status, "quotes": quotes, "server_time": self.clock()}
