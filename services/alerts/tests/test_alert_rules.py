import pytest

from app.alerts.rules import is_triggered


def test_above_triggers_when_price_is_higher():
    assert is_triggered("above", 100.0, 100.5) is True


def test_above_does_not_trigger_when_price_is_lower():
    assert is_triggered("above", 100.0, 99.5) is False


def test_below_triggers_when_price_is_lower():
    assert is_triggered("below", 100.0, 99.5) is True


def test_below_does_not_trigger_when_price_is_higher():
    assert is_triggered("below", 100.0, 100.5) is False


def test_above_does_not_trigger_at_equal_price():
    assert is_triggered("above", 100.0, 100.0) is False


def test_below_does_not_trigger_at_equal_price():
    assert is_triggered("below", 100.0, 100.0) is False


def test_unknown_condition_raises():
    with pytest.raises(ValueError):
        is_triggered("equals", 100.0, 100.0)
