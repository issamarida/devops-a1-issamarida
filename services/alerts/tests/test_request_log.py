"""One log line per request with method, path, status and duration."""

import logging
import re

import pytest
from flask import Flask

from app import create_app
from app.config import load_config
from app.request_log import install_request_log

LINE = re.compile(r"^(GET|POST) (/\S*) (\d{3}) (\d+\.\d)ms$")


def request_lines(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.request_log"
    ]


@pytest.fixture
def small_app():
    app = Flask(__name__)
    install_request_log(app)

    @app.get("/hello")
    def hello():
        return "hi"

    @app.post("/things")
    def create_thing():
        return "made", 201

    return app


def test_each_request_writes_one_line(small_app, caplog):
    caplog.set_level(logging.INFO)
    client = small_app.test_client()

    client.get("/hello")
    client.post("/things")

    lines = request_lines(caplog)
    assert len(lines) == 2
    assert LINE.match(lines[0]).groups()[:3] == ("GET", "/hello", "200")
    assert LINE.match(lines[1]).groups()[:3] == ("POST", "/things", "201")


def test_a_page_that_does_not_exist_is_logged_too(small_app, caplog):
    caplog.set_level(logging.INFO)

    small_app.test_client().get("/nope")

    assert LINE.match(request_lines(caplog)[0]).groups()[:3] == ("GET", "/nope", "404")


def test_the_query_string_is_left_out(small_app, caplog):
    caplog.set_level(logging.INFO)

    small_app.test_client().get("/hello?token=do-not-log-me")

    assert "do-not-log-me" not in caplog.text
    assert request_lines(caplog)[0].startswith("GET /hello 200 ")


def test_the_duration_covers_the_time_spent_in_the_route(caplog):
    import time

    app = Flask(__name__)
    install_request_log(app)

    @app.get("/slow")
    def slow():
        time.sleep(0.05)
        return "done"

    caplog.set_level(logging.INFO)
    app.test_client().get("/slow")

    duration_ms = float(LINE.match(request_lines(caplog)[0]).group(4))
    assert 50 <= duration_ms < 1000


def test_the_real_app_logs_requests_that_access_control_answers(caplog):
    # A request without a token never reaches a route. It still gets a line,
    # with the status the browser saw.
    client = create_app(load_config()).test_client()
    caplog.set_level(logging.INFO)

    client.get("/health")
    client.get("/alerts")
    client.post("/alerts/evaluate?debug=do-not-log-me")

    statuses = [LINE.match(line).groups()[:3] for line in request_lines(caplog)]
    assert statuses == [
        ("GET", "/health", "200"),
        ("GET", "/alerts", "401"),
        ("POST", "/alerts/evaluate", "401"),
    ]
    assert "do-not-log-me" not in caplog.text
