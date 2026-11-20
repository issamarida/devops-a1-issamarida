from pathlib import Path

import pytest

from app.config import RedactSecret, load_config, load_env_file

VARIABLES = [
    "HOST",
    "PORT",
    "DATA_DIR",
    "WATCHLIST_URL",
    "WATCHLIST_TIMEOUT_SECONDS",
    "POLL_INTERVAL_SECONDS",
    "CORS_ORIGINS",
    "GIT_SHA",
    "MAX_ALERT_RULES",
]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Start every test with none of the service's variables set, except the one secret it needs."""
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_only_the_secret_is_set():
    config = load_config()

    assert config.host == "0.0.0.0"
    assert config.port == 8002
    assert config.data_dir == Path("./data")
    assert config.db_path == Path("./data") / "alerts.db"
    # The watchlist service's name and port in docker-compose.yml.
    assert config.watchlist_url == "http://watchlist:8001"
    assert config.watchlist_timeout_seconds == 3.0
    assert config.poll_interval_seconds == 15
    assert config.cors_origins == ["http://localhost:8080"]
    assert config.git_sha == "dev"
    assert config.max_alert_rules == 100


def test_environment_variables_override_the_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WATCHLIST_URL", "https://watchlist.example ")
    monkeypatch.setenv("WATCHLIST_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("TOKEN_SECRET", "a-test-secret-that-is-at-least-32-characters")
    monkeypatch.setenv("CORS_ORIGINS", "https://ui.example/, https://other.example")
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("MAX_ALERT_RULES", "5")

    config = load_config()

    assert config.host == "127.0.0.1"
    assert config.port == 9000
    assert config.db_path == tmp_path / "alerts.db"
    assert config.watchlist_url == "https://watchlist.example"
    assert config.watchlist_timeout_seconds == 1.5
    assert config.poll_interval_seconds == 0
    assert config.token_secret == "a-test-secret-that-is-at-least-32-characters"
    # A trailing slash is dropped: a browser never sends one in the Origin header.
    assert config.cors_origins == ["https://ui.example", "https://other.example"]
    assert config.git_sha == "abc1234"
    assert config.max_alert_rules == 5


@pytest.mark.parametrize("value", [None, "", "short"])
def test_token_secret_is_required_and_has_no_default(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("TOKEN_SECRET")
    else:
        monkeypatch.setenv("TOKEN_SECRET", value)

    with pytest.raises(ValueError, match="TOKEN_SECRET must be set"):
        load_config()


@pytest.mark.parametrize("name", ["PORT", "POLL_INTERVAL_SECONDS", "MAX_ALERT_RULES"])
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


def test_negative_poll_interval_is_rejected(monkeypatch):
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "-1")

    with pytest.raises(ValueError, match="POLL_INTERVAL_SECONDS must be 0 or more"):
        load_config()


def test_rule_limit_must_be_positive(monkeypatch):
    monkeypatch.setenv("MAX_ALERT_RULES", "0")

    with pytest.raises(ValueError, match="MAX_ALERT_RULES"):
        load_config()


@pytest.mark.parametrize("url", ["watchlist:8001", "ftp://watchlist", ""])
def test_watchlist_url_must_be_an_http_address(monkeypatch, url):
    monkeypatch.setenv("WATCHLIST_URL", url)

    with pytest.raises(ValueError, match="WATCHLIST_URL"):
        load_config()


@pytest.mark.parametrize("value", ["0", "-1", "31", "abc", "nan"])
def test_every_call_needs_a_real_timeout(monkeypatch, value):
    # No timeout, or a huge one, would let a silent watchlist hang a request.
    monkeypatch.setenv("WATCHLIST_TIMEOUT_SECONDS", value)

    with pytest.raises(ValueError, match="WATCHLIST_TIMEOUT_SECONDS"):
        load_config()


def test_blank_git_sha_falls_back_to_dev(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "  ")
    assert load_config().git_sha == "dev"


def test_env_file_fills_in_missing_variables_only(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a comment\n\nnot a setting\nPORT=9100\nexport WATCHLIST_URL='http://other:1'\n=x\n"
    )
    monkeypatch.setenv("PORT", "9000")

    load_env_file(env_file)
    load_env_file(tmp_path / "missing.env")  # a missing file is fine

    config = load_config()
    assert config.port == 9000  # the shell wins over the file
    assert config.watchlist_url == "http://other:1"


def test_redact_secret_hides_the_secret_in_a_log_line():
    import logging

    record = logging.LogRecord("x", logging.INFO, "f", 1, "token is %s", ("the-secret",), None)

    assert RedactSecret("the-secret").filter(record) is True
    assert record.getMessage() == "token is ***"
    untouched = logging.LogRecord("x", logging.INFO, "f", 1, "nothing here", None, None)
    assert RedactSecret(None).filter(untouched) is True
    assert untouched.getMessage() == "nothing here"
