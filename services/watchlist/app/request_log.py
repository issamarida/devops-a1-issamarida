"""Writes one log line per request: method, path, status and duration.

The line goes through the logging module, which app.py points at stdout.
"""

import logging
import time

from flask import Flask, g, request

logger = logging.getLogger(__name__)


def install_request_log(app: Flask) -> None:
    """Call this before anything else adds request hooks to the app.

    Flask runs before_request hooks in the order they were added and
    after_request hooks in reverse. Added first, the timer starts before any
    other hook and the line is written after every other hook, so it shows
    the final status even when another hook answered the request itself.
    """

    @app.before_request
    def start_timer():
        g.request_started = time.perf_counter()

    @app.after_request
    def log_request(response):
        duration_ms = (time.perf_counter() - g.request_started) * 1000
        # request.path leaves out the query string, so nothing typed after
        # the "?" ends up in the logs.
        logger.info(
            "%s %s %s %.1fms",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response
