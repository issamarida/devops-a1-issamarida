"""The trigger check for an alert rule. No database, no network."""


def is_triggered(condition: str, threshold: float, price: float) -> bool:
    """A price equal to the threshold never triggers."""
    if condition == "above":
        return price > threshold
    if condition == "below":
        return price < threshold
    raise ValueError(f"Unknown condition: {condition!r}")
