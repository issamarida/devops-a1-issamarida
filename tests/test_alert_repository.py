import sqlite3

import pytest

from app.alerts.repository import AlertRepository


@pytest.fixture
def repo(db_path):
    return AlertRepository(db_path)


def count_events(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM alert_events").fetchone()[0]
    finally:
        conn.close()


def test_add_then_list(repo):
    rule_id = repo.add_rule("AAPL", "above", 200.0)

    rules = repo.list_rules()
    assert len(rules) == 1
    assert rules[0]["id"] == rule_id
    assert rules[0]["ticker"] == "AAPL"
    assert rules[0]["condition"] == "above"
    assert rules[0]["threshold"] == 200.0
    assert rules[0]["is_active"] == 1
    assert repo.list_active_rules() == rules


def test_fire_rule_deactivates_and_logs_one_event(repo):
    rule_id = repo.add_rule("AAPL", "above", 200.0)
    rule = repo.get_rule(rule_id)

    assert repo.fire_rule(rule, 201.5) is True

    assert repo.get_rule(rule_id)["is_active"] == 0
    assert repo.list_active_rules() == []
    events = repo.list_events()
    assert len(events) == 1
    assert events[0]["rule_id"] == rule_id
    assert events[0]["ticker"] == "AAPL"
    assert events[0]["condition"] == "above"
    assert events[0]["threshold"] == 200.0
    assert events[0]["observed_price"] == 201.5


def test_second_fire_returns_false_and_adds_no_event(repo):
    rule = repo.get_rule(repo.add_rule("AAPL", "above", 200.0))
    repo.fire_rule(rule, 201.5)

    assert repo.fire_rule(rule, 202.0) is False
    assert len(repo.list_events()) == 1


def test_fire_rule_rolls_back_when_insert_fails(repo, db_path):
    rule_id = repo.add_rule("AAPL", "above", 200.0)
    rule = repo.get_rule(rule_id)
    rule["ticker"] = None  # alert_events.ticker is NOT NULL, so the INSERT fails

    with pytest.raises(sqlite3.IntegrityError):
        repo.fire_rule(rule, 201.5)

    assert repo.get_rule(rule_id)["is_active"] == 1
    assert count_events(db_path) == 0


def test_delete_rule_keeps_event_with_null_rule_id(repo):
    rule_id = repo.add_rule("AAPL", "below", 150.0)
    repo.fire_rule(repo.get_rule(rule_id), 149.0)

    assert repo.delete_rule(rule_id) is True

    assert repo.get_rule(rule_id) is None
    events = repo.list_events()
    assert len(events) == 1
    assert events[0]["rule_id"] is None
    assert events[0]["ticker"] == "AAPL"


def test_delete_missing_rule_returns_false(repo):
    assert repo.delete_rule(999) is False
