"""Errors leave the service as JSON and never show what went wrong inside."""

import logging

import pytest
from flask import Flask

from app.errors import install_error_handlers


@pytest.fixture
def client():
    app = Flask(__name__)
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret detail from inside the service")

    return app.test_client()


def test_a_missing_page_is_a_json_404(client):
    response = client.get("/nope")

    assert response.status_code == 404
    assert "error" in response.get_json()


def test_a_wrong_method_is_a_json_405(client):
    response = client.post("/boom")

    assert response.status_code == 405
    assert "error" in response.get_json()


def test_an_unexpected_error_is_a_json_500_without_details(client, caplog):
    caplog.set_level(logging.ERROR)

    response = client.get("/boom")

    assert response.status_code == 500
    assert response.get_json() == {"error": "Something went wrong on our side. Try again."}
    assert "secret detail" not in response.get_data(as_text=True)
    # The details are in the log, where only I can read them.
    assert "secret detail" in caplog.text
