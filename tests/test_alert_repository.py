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


def test_stale_rule_cannot_fire_a_replacement_with_reused_id(repo):
    old = repo.get_rule(repo.add_rule("AAPL", "above", 100))
    repo.delete_rule(old["id"])
    replacement_id = repo.add_rule("MSFT", "below", 50)
    assert replacement_id == old["id"]  # SQLite can reuse an INTEGER PRIMARY KEY.
    assert repo.fire_rule(old, 150) is False
    assert repo.get_rule(replacement_id)["is_active"] == 1
    assert repo.list_events() == []


def test_two_threads_fire_only_one_event(repo):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    rule = repo.get_rule(repo.add_rule("AAPL", "above", 100))
    barrier = Barrier(2)

    def fire():
        barrier.wait()
        return repo.fire_rule(rule, 150)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: fire(), range(2)))
    assert sorted(results) == [False, True]
    assert len(repo.list_events()) == 1


def test_owner_cannot_read_delete_or_fire_another_owners_rule(db_path):
    alice = AlertRepository(db_path, 1)
    bob = AlertRepository(db_path, 2)
    rule = alice.get_rule(alice.add_rule("AAPL", "above", 100))
    assert bob.get_rule(rule["id"]) is None
    assert bob.delete_rule(rule["id"]) is False
    assert bob.fire_rule(rule, 150) is False
    assert bob.list_rules() == bob.list_active_rules() == bob.list_events() == []
    assert alice.fire_rule(rule, 150)
    assert bob.list_events() == []


def test_history_page_is_bounded_but_full_history_is_retained(repo):
    for _ in range(105):
        rule = repo.get_rule(repo.add_rule("AAPL", "above", 100))
        assert repo.fire_rule(rule, 150)
        repo.delete_rule(rule["id"])
    assert len(repo.list_events()) == 100
    assert repo.count_events() == 105
    assert repo.list_events()[0]["id"] == 105
