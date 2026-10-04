"""The Finnhub WebSocket stream and the live price layer. No network: the socket is faked."""

import json
import logging
from unittest.mock import Mock, patch

import pytest

from app.config import RedactSecret
from app.market.cache import CachedPriceSource
from app.market.finnhub import FinnhubSource, Quote
from app.market.stream import MAX_POINTS, STREAM_URL, FinnhubStream, LivePrices, Trade
from app.ports import PriceUnavailable

FAKE_KEY = "fake-key-for-tests"


class FakeClock:
    def __init__(self, now=1_000.0):
        self.now = now

    def __call__(self):
        return self.now


class FakeSocket:
    """Records what the stream sends, and can fail on demand."""

    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
        self.closed = False

    def send(self, text):
        if self.fail:
            raise ConnectionError("socket is gone")
        self.sent.append(json.loads(text))

    def close(self):
        self.closed = True


def trade_message(*trades):
    return json.dumps(
        {"type": "trade", "data": [{"s": s, "p": p, "t": t, "v": 1} for s, p, t in trades]}
    )


def connected_stream(symbols=("AAPL", "MSFT"), clock=None):
    stream = FinnhubStream(FAKE_KEY, lambda: list(symbols), clock=clock or FakeClock())
    socket = FakeSocket()
    stream.ws = socket
    stream.on_open(socket)
    return stream, socket


# Subscriptions


def test_open_subscribes_to_every_watched_ticker():
    stream, socket = connected_stream()
    assert socket.sent == [
        {"type": "subscribe", "symbol": "AAPL"},
        {"type": "subscribe", "symbol": "MSFT"},
    ]
    assert stream.connected
    assert stream.subscribed == {"AAPL", "MSFT"}


def test_sync_adds_new_and_drops_removed_tickers():
    symbols = ["AAPL", "MSFT"]
    stream = FinnhubStream(FAKE_KEY, lambda: symbols, clock=FakeClock())
    socket = FakeSocket()
    stream.ws = socket
    stream.on_open(socket)
    stream.handle_message(trade_message(("MSFT", 400.0, 1_000_000)))
    socket.sent.clear()

    symbols[:] = ["AAPL", "TSLA"]
    stream.sync()

    assert socket.sent == [
        {"type": "subscribe", "symbol": "TSLA"},
        {"type": "unsubscribe", "symbol": "MSFT"},
    ]
    assert stream.latest("MSFT") is None  # a dropped ticker forgets its price


def test_sync_respects_the_symbol_limit_most_watched_first():
    stream = FinnhubStream(FAKE_KEY, lambda: ["AAPL", "MSFT", "TSLA"], max_symbols=2)
    socket = FakeSocket()
    stream.ws = socket
    stream.on_open(socket)
    assert stream.subscribed == {"AAPL", "MSFT"}


def test_sync_does_nothing_while_disconnected():
    stream = FinnhubStream(FAKE_KEY, lambda: ["AAPL"])
    stream.sync()
    assert stream.subscribed == set()


def test_sync_survives_a_broken_ticker_source(caplog):
    def broken():
        raise RuntimeError("database is locked")

    stream = FinnhubStream(FAKE_KEY, broken)
    stream.connected, stream.ws = True, FakeSocket()
    stream.sync()
    assert stream.subscribed == set()
    assert "Could not read the tickers to stream" in caplog.text


def test_sync_survives_a_dropped_socket(caplog):
    stream = FinnhubStream(FAKE_KEY, lambda: ["AAPL"])
    socket = FakeSocket(fail=True)
    stream.ws = socket
    stream.on_open(socket)
    assert "send failed: ConnectionError" in caplog.text


def test_follow_wakes_the_sync_thread_only_for_unknown_tickers():
    stream, _ = connected_stream(symbols=("AAPL",))
    stream.follow(["AAPL"])
    assert not stream.wake.is_set()
    stream.follow(["AAPL", "NVDA"])
    assert stream.wake.is_set()


# Messages


def test_trade_message_updates_the_latest_price():
    clock = FakeClock(2_000)
    stream, _ = connected_stream(clock=clock)
    stream.handle_message(trade_message(("AAPL", 187.5, 1_999_000)))
    assert stream.latest("AAPL") == Trade(187.5, 1_999.0, 2_000)


def test_out_of_order_trades_keep_the_newest():
    stream, _ = connected_stream()
    stream.handle_message(
        trade_message(("AAPL", 101.0, 5_000), ("AAPL", 100.0, 4_000))
    )
    assert stream.latest("AAPL").price == 101.0


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        None,
        "[1, 2]",
        json.dumps({"type": "ping"}),
        json.dumps({"type": "trade", "data": "nope"}),
        json.dumps({"type": "trade", "data": ["nope"]}),
        trade_message(("AAPL", 0, 5_000)),
        trade_message(("AAPL", True, 5_000)),
        trade_message(("AAPL", float("nan"), 5_000)),
        trade_message(("AAPL", 100.0, None)),
        trade_message(("NVDA", 100.0, 5_000)),  # not subscribed
    ],
)
def test_bad_or_irrelevant_messages_are_ignored(raw):
    stream, _ = connected_stream()
    stream.on_message(None, raw)
    assert stream.trades == {}


def test_error_message_is_logged_without_crashing(caplog):
    stream, _ = connected_stream()
    stream.handle_message(json.dumps({"type": "error", "msg": "Subscribing to too many symbols"}))
    assert "too many symbols" in caplog.text


def test_close_marks_the_stream_disconnected():
    stream, socket = connected_stream()
    stream.on_close(socket, 1000, "bye")
    assert not stream.connected


def test_error_logs_only_the_error_type(caplog):
    stream, socket = connected_stream()
    stream.on_error(socket, OSError(f"failed to reach {STREAM_URL}?token={FAKE_KEY}"))
    assert "OSError" in caplog.text
    assert FAKE_KEY not in caplog.text


def test_rejected_key_names_the_setting_to_check(caplog):
    stream, socket = connected_stream()
    error = Exception("Handshake status 401")
    error.status_code = 401
    stream.on_error(socket, error)
    assert "HTTP 401: check PRICE_API_KEY" in caplog.text


# Connection loop


def test_run_connects_with_the_key_and_reconnects_after_a_drop():
    stream = FinnhubStream(FAKE_KEY, lambda: ["AAPL"])
    urls = []

    def connect(url, **callbacks):
        urls.append(url)
        socket = Mock()

        def run_forever(**kwargs):
            assert kwargs["reconnect"] == 0  # the loop below owns reconnecting
            callbacks["on_open"](socket)
            if len(urls) == 2:
                stream.stop_event.set()
            raise ConnectionResetError("dropped")

        socket.run_forever.side_effect = run_forever
        return socket

    stream.connect = connect
    with patch.object(stream.stop_event, "wait") as wait:
        stream.run()

    assert urls == [f"{STREAM_URL}?token={FAKE_KEY}"] * 2
    wait.assert_called_once_with(1)
    assert not stream.connected and stream.ws is None


def test_reconnect_delay_doubles_while_connections_keep_failing():
    clock = FakeClock()
    stream = FinnhubStream(FAKE_KEY, lambda: [], clock=clock)
    attempts = []

    def connect(url, **callbacks):
        attempts.append(url)
        if len(attempts) == 4:
            stream.stop_event.set()
        return Mock()

    stream.connect = connect
    with patch.object(stream.stop_event, "wait") as wait:
        stream.run()
    assert [call.args[0] for call in wait.call_args_list] == [1, 2, 4]


def test_start_without_a_key_opens_nothing(caplog):
    stream = FinnhubStream("  ", lambda: ["AAPL"])
    connect = Mock()
    stream.connect = connect
    assert not stream.enabled
    assert stream.start() == []
    connect.assert_not_called()
    assert "PRICE_API_KEY is not set" in caplog.text


def test_start_runs_two_daemon_threads_and_stop_ends_them():
    stream = FinnhubStream(FAKE_KEY, lambda: [], refresh_seconds=0.01)
    blocker = Mock()
    blocker.run_forever.side_effect = lambda **kwargs: stream.stop_event.wait(5)
    stream.connect = lambda url, **callbacks: blocker
    threads = stream.start()
    assert all(thread.daemon for thread in threads)
    stream.stop()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    blocker.close.assert_called_once()


# LivePrices


class FakeStream:
    def __init__(self, enabled=True, connected=True):
        self.enabled = enabled
        self.connected = connected
        self.trades = {}
        self.followed = []

    def latest(self, ticker):
        return self.trades.get(ticker)

    def recent(self, ticker):
        return [1.0, 2.0] if ticker in self.trades else []

    def follow(self, tickers):
        self.followed.append(list(tickers))


class FakeQuotes:
    def __init__(self, quotes=None):
        self.quotes = quotes or {}
        self.calls = []

    def get_quote(self, ticker):
        self.calls.append(ticker)
        if ticker not in self.quotes:
            raise PriceUnavailable(ticker)
        return self.quotes[ticker]


def live(stream=None, quotes=None, clock=None):
    return LivePrices(stream or FakeStream(), quotes or FakeQuotes(), clock=clock or FakeClock())


def test_fresh_trade_is_the_alert_price():
    clock = FakeClock(1_000)
    stream = FakeStream()
    stream.trades["AAPL"] = Trade(190.0, 999, received=990)
    quotes = FakeQuotes({"AAPL": Quote(180.0, 175.0, 900)})
    assert live(stream, quotes, clock).get_price("AAPL") == 190.0
    assert quotes.calls == []


def test_old_trade_falls_back_to_the_rest_quote():
    clock = FakeClock(1_000)
    stream = FakeStream()
    stream.trades["AAPL"] = Trade(190.0, 900, received=900)
    quotes = FakeQuotes({"AAPL": Quote(180.0, 175.0, 950)})
    assert live(stream, quotes, clock).get_price("AAPL") == 180.0


def test_no_trade_and_no_quote_is_unavailable_never_invented():
    with pytest.raises(PriceUnavailable):
        live().get_price("AAPL")


def test_snapshot_prefers_live_trade_and_computes_the_day_change():
    clock = FakeClock(1_000)
    stream = FakeStream()
    stream.trades["AAPL"] = Trade(110.0, 999, received=999)
    quotes = FakeQuotes({"AAPL": Quote(105.0, 100.0, 900, open=101.0, high=108.0, low=99.0)})

    body = live(stream, quotes, clock).snapshot(["AAPL"])

    assert body == {
        "status": "live",
        "server_time": 1_000,
        "quotes": {
            "AAPL": {
                "price": 110.0, "change": 10.0, "percent": 10.0, "source": "live", "at": 999,
                # The live trade is above the quote's day high, so it becomes the high.
                "previous_close": 100.0, "open": 101.0, "high": 110.0, "low": 99.0,
                "spark": [1.0, 2.0],
            }
        },
    }
    assert stream.followed == [["AAPL"]]


def test_snapshot_uses_the_quote_when_no_trade_has_arrived():
    quotes = FakeQuotes({"MSFT": Quote(400.0, None, 900)})
    body = live(FakeStream(connected=False), quotes).snapshot(["MSFT"])
    assert body["status"] == "connecting"
    assert body["quotes"]["MSFT"] == {
        "price": 400.0, "change": None, "percent": None, "source": "quote", "at": 900,
        "previous_close": None, "open": None, "high": None, "low": None, "spark": [],
    }


def test_snapshot_reuses_the_baseline_while_trades_stream():
    clock = FakeClock(1_000)
    stream = FakeStream()
    stream.trades["AAPL"] = Trade(110.0, 999, received=999)
    quotes = FakeQuotes({"AAPL": Quote(105.0, 100.0, 900)})
    prices = live(stream, quotes, clock)
    prices.snapshot(["AAPL"])
    clock.now = 1_010
    stream.trades["AAPL"] = Trade(111.0, 1_009, received=1_009)
    assert prices.snapshot(["AAPL"])["quotes"]["AAPL"]["price"] == 111.0
    assert quotes.calls == ["AAPL"]  # one REST call, then the stream carries it
    clock.now = 2_000
    stream.trades["AAPL"] = Trade(112.0, 1_999, received=1_999)
    prices.snapshot(["AAPL"])
    assert quotes.calls == ["AAPL", "AAPL"]  # baseline refreshed after 15 minutes


def test_snapshot_keeps_the_last_real_quote_when_rest_fails():
    quotes = FakeQuotes({"AAPL": Quote(105.0, 100.0, 900)})
    prices = live(FakeStream(connected=False), quotes)
    prices.snapshot(["AAPL"])
    quotes.quotes.clear()
    assert prices.snapshot(["AAPL"])["quotes"]["AAPL"]["price"] == 105.0


def test_snapshot_reports_offline_and_empty_without_a_key():
    body = live(FakeStream(enabled=False, connected=False)).snapshot(["AAPL"])
    assert body["status"] == "offline"
    assert body["quotes"] == {"AAPL": None}


# REST quote details used by the snapshot


def test_get_quote_reads_price_previous_close_and_time():
    payload = {"c": 187.44, "pc": 185.0, "t": 1_700_000_000}
    with patch(
        "app.market.finnhub.requests.get",
        return_value=Mock(status_code=200, json=lambda: payload),
    ):
        quote = FinnhubSource(FAKE_KEY).get_quote("AAPL")
    assert quote == Quote(187.44, 185.0, 1_700_000_000.0)


def test_get_quote_tolerates_a_missing_close_and_time():
    with patch(
        "app.market.finnhub.requests.get",
        return_value=Mock(status_code=200, json=lambda: {"c": 10, "pc": 0}),
    ):
        quote = FinnhubSource(FAKE_KEY).get_quote("AAPL")
    assert quote.previous_close is None and quote.at > 0


def test_cache_stores_quotes_separately_from_prices():
    source = Mock()
    source.get_quote.return_value = Quote(1.0, None, 1)
    cache = CachedPriceSource(source, ttl_seconds=30, clock=FakeClock())
    assert cache.get_quote("AAPL") is cache.get_quote("AAPL")
    source.get_quote.assert_called_once_with("AAPL")


# Log redaction


def test_redact_secret_hides_the_key_in_any_log_line():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "url %s", (f"?token={FAKE_KEY}",), None)
    assert RedactSecret(FAKE_KEY).filter(record)
    assert record.getMessage() == "url ?token=***"


def test_redact_secret_without_a_key_changes_nothing():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("there",), None)
    assert RedactSecret(None).filter(record)
    assert record.getMessage() == "hello there"


def test_a_long_healthy_connection_resets_the_reconnect_delay():
    clock = FakeClock()
    stream = FinnhubStream(FAKE_KEY, lambda: [], clock=clock)
    runs = []

    def connect(url, **callbacks):
        socket = Mock()

        def run_forever(**kwargs):
            runs.append(1)
            # Runs 1 and 2 fail at once; run 3 stays up for two minutes.
            if len(runs) == 3:
                clock.now += 120
            if len(runs) == 4:
                stream.stop_event.set()

        socket.run_forever.side_effect = run_forever
        return socket

    stream.connect = connect
    with patch.object(stream.stop_event, "wait") as wait:
        stream.run()
    assert [call.args[0] for call in wait.call_args_list] == [1, 2, 1]


# Sparkline points from streamed trades


def spark_trade(ticker, price, at_ms):
    return json.dumps({"type": "trade", "data": [{"s": ticker, "p": price, "t": at_ms}]})


def test_trades_build_one_sparkline_point_per_five_seconds():
    stream = FinnhubStream(FAKE_KEY, lambda: [])
    stream.subscribed = {"AAPL"}
    stream.handle_message(spark_trade("AAPL", 100.0, 1_000_000))
    stream.handle_message(spark_trade("AAPL", 101.0, 1_002_000))  # same point, moved
    stream.handle_message(spark_trade("AAPL", 102.0, 1_006_000))  # new point
    assert stream.recent("AAPL") == [101.0, 102.0]
    assert stream.recent("MSFT") == []


def test_sparkline_keeps_only_the_latest_points():
    stream = FinnhubStream(FAKE_KEY, lambda: [])
    stream.subscribed = {"AAPL"}
    for i in range(MAX_POINTS + 10):
        stream.handle_message(spark_trade("AAPL", 100.0 + i, 1_000_000 + i * 5_000))
    points = stream.recent("AAPL")
    assert len(points) == MAX_POINTS
    assert points[-1] == 100.0 + MAX_POINTS + 9
