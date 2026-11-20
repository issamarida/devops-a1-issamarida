"""Every error leaves the service as JSON: {"error": "..."}.

The static UI reads that one field. A stack trace never reaches the browser.
"""

import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)


def install_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def http_error(error):
        # 404, 405, 413 and the rest that Flask raises itself.
        return {"error": error.description}, error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        # The details go to the log only.
        logger.exception("Unhandled error")
        return {"error": "Something went wrong on our side. Try again."}, 500
