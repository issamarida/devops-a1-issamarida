import threading

import pytest

from app.poller import run_once, start_poller


class FakeAlertService:
    """Stands in for AlertService. Counts calls and returns a fixed list of fired rules."""

    def __init__(self, fired=None, error=None):
        self.fired = fired or []
        self.error = error
        self.calls = 0
        self.called = threading.Event()

    def evaluate_all(self):
        self.calls += 1
        self.called.set()
        if self.error is not None:
            raise self.error
        return self.fired


@pytest.mark.parametrize("interval", [0, -5])
def test_start_poller_is_disabled_for_zero_or_negative_interval(interval):
    service = FakeAlertService()

    assert start_poller(service, interval) is None
    assert service.calls == 0


def test_run_once_returns_the_number_of_fired_rules():
    service = FakeAlertService(fired=[{"id": 1}, {"id": 2}])

    assert run_once(service) == 2
    assert service.calls == 1


def test_run_once_returns_zero_when_nothing_fired():
    assert run_once(FakeAlertService()) == 0


def test_run_once_swallows_an_exception_and_returns_zero():
    service = FakeAlertService(error=RuntimeError("database is locked"))

    assert run_once(service) == 0
    assert service.calls == 1


def test_started_thread_evaluates_and_stops_when_the_event_is_set():
    service = FakeAlertService()
    stop_event = threading.Event()

    thread = start_poller(service, 0.01, stop_event)

    assert thread.name == "alert-poller"
    assert thread.daemon is True
    assert service.called.wait(timeout=1)

    stop_event.set()
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_thread_keeps_running_after_a_failed_check():
    service = FakeAlertService(error=RuntimeError("boom"))
    stop_event = threading.Event()

    thread = start_poller(service, 0.01, stop_event)
    assert service.called.wait(timeout=1)
    service.called.clear()
    # A second call proves the first failure didn't kill the loop.
    assert service.called.wait(timeout=1)

    stop_event.set()
    thread.join(timeout=1)
    assert not thread.is_alive()
