from pathlib import Path

import pytest

from app.config import load_config

VARIABLES = [
    "HOST",
    "PORT",
    "DATA_DIR",
    "PRICE_API_KEY",
    "POLL_INTERVAL_SECONDS",
    "PRICE_CACHE_TTL_SECONDS",
    "SECRET_KEY",
    "SESSION_COOKIE_SECURE",
    "SESSION_SECONDS",
    "AUTH_ATTEMPTS",
    "AUTH_WINDOW_SECONDS",
    "MAX_ACCOUNTS",
    "MAX_WATCHLIST_ITEMS",
    "MAX_ALERT_RULES",
    "QUOTE_REQUESTS_PER_MINUTE",
]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Start every test with none of the app's variables set."""
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_nothing_is_set():
    config = load_config()

    assert config.host == "0.0.0.0"
    assert config.port == 8080
    assert config.data_dir == Path("./data")
    assert config.db_path == Path("./data") / "app.db"
    assert config.price_api_key is None
    assert config.poll_interval_seconds == 60
    assert config.price_cache_ttl_seconds == 30
    assert len(config.secret_key) >= 32
    assert config.secret_key != load_config().secret_key


def test_environment_variables_override_the_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRICE_API_KEY", "fake-key-for-tests")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "5")
    monkeypatch.setenv("PRICE_CACHE_TTL_SECONDS", "10")
    monkeypatch.setenv("SECRET_KEY", "a-test-secret-that-is-at-least-32-characters")

    config = load_config()

    assert config.host == "127.0.0.1"
    assert config.port == 9000
    assert config.data_dir == tmp_path
    assert config.db_path == tmp_path / "app.db"
    assert config.price_api_key == "fake-key-for-tests"
    assert config.poll_interval_seconds == 5
    assert config.price_cache_ttl_seconds == 10
    assert config.secret_key == "a-test-secret-that-is-at-least-32-characters"


def test_empty_api_key_becomes_none(monkeypatch):
    monkeypatch.setenv("PRICE_API_KEY", "")

    assert load_config().price_api_key is None


@pytest.mark.parametrize("name", ["POLL_INTERVAL_SECONDS", "PRICE_CACHE_TTL_SECONDS"])
def test_zero_is_allowed_for_the_interval_and_the_ttl(monkeypatch, name):
    monkeypatch.setenv(name, "0")

    load_config()


@pytest.mark.parametrize("port", ["1", "65535"])
def test_port_accepts_both_ends_of_the_range(monkeypatch, port):
    monkeypatch.setenv("PORT", port)

    assert load_config().port == int(port)


@pytest.mark.parametrize(
    "name", ["PORT", "POLL_INTERVAL_SECONDS", "PRICE_CACHE_TTL_SECONDS"]
)
@pytest.mark.parametrize("value", ["abc", "", "1.5"])
def test_non_integer_value_names_the_variable_and_the_value(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError) as error:
        load_config()

    assert name in str(error.value)
    assert repr(value) in str(error.value)


@pytest.mark.parametrize("port", ["0", "-1", "65536"])
def test_port_out_of_range_is_rejected(monkeypatch, port):
    monkeypatch.setenv("PORT", port)

    with pytest.raises(ValueError, match="PORT must be between 1 and 65535"):
        load_config()


@pytest.mark.parametrize("name", ["POLL_INTERVAL_SECONDS", "PRICE_CACHE_TTL_SECONDS"])
def test_negative_interval_or_ttl_is_rejected(monkeypatch, name):
    monkeypatch.setenv(name, "-1")

    with pytest.raises(ValueError, match=f"{name} must be 0 or more"):
        load_config()


@pytest.mark.parametrize(
    "name", ["SESSION_SECONDS", "AUTH_ATTEMPTS", "AUTH_WINDOW_SECONDS", "MAX_ACCOUNTS"]
)
def test_security_limits_must_be_positive(monkeypatch, name):
    monkeypatch.setenv(name, "0")
    with pytest.raises(ValueError, match=name):
        load_config()


def test_secure_cookies_require_boolean(monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "yes")
    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        load_config()


def test_secure_cookies_can_be_enabled(monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    assert load_config().cookie_secure is True


def test_rejects_short_session_secret(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "short")
    with pytest.raises(ValueError, match="SECRET_KEY"):
        load_config()


def test_whitespace_api_key_is_unconfigured(monkeypatch):
    monkeypatch.setenv("PRICE_API_KEY", "   ")
    assert load_config().price_api_key is None
