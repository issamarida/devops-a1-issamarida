"""Checks the alert rules in the background every few seconds.

Started from app.py only. create_app never starts it, so tests don't get a thread.
"""

import logging
import threading

logger = logging.getLogger(__name__)


def run_once(alert_service) -> int:
    """Check every rule once. Returns how many fired, or 0 if the check failed."""
    try:
        return len(alert_service.evaluate_all())
    except Exception:
        # One bad run must not kill the thread. Log it and try again next time.
        logger.exception("Alert check failed")
        return 0


def start_poller(alert_service, interval_seconds, stop_event=None):
    """Start the background thread and return it. Returns None if polling is off."""
    if interval_seconds <= 0:
        logger.info("Alert poller is off because POLL_INTERVAL_SECONDS is 0 or less")
        return None

    if stop_event is None:
        stop_event = threading.Event()

    def loop():
        while not stop_event.is_set():
            run_once(alert_service)
            # wait returns early when the event is set, so stopping is quick.
            stop_event.wait(interval_seconds)

    # daemon=True means the thread dies with the process and never blocks shutdown.
    thread = threading.Thread(target=loop, name="alert-poller", daemon=True)
    thread.start()
    logger.info("Alert poller started, checking every %s seconds", interval_seconds)
    return thread
