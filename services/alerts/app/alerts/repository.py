"""All SQL for alert_rules and alert_events. Each method opens a connection and closes it when done."""

from datetime import datetime, timezone
from uuid import uuid4

from app.db import get_connection


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RuleLimitReached(ValueError):
    pass


class AlertRepository:
    def __init__(self, db_path, owner_id=0, max_rules=100):
        self.db_path = db_path
        self.owner_id = owner_id
        self.max_rules = max_rules

    def add_rule(self, ticker, condition, threshold) -> int:
        conn = get_connection(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute(
                "SELECT COUNT(*) FROM alert_rules WHERE owner_id = ?", (self.owner_id,)
            ).fetchone()[0]
            if count >= self.max_rules:
                raise RuleLimitReached(
                    f"You can keep up to {self.max_rules} rules. Delete an old rule first; its history stays."
                )
            cursor = conn.execute(
                "INSERT INTO alert_rules (ticker, condition, threshold, created_at, owner_id, rule_token) VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, condition, threshold, utc_now(), self.owner_id, uuid4().hex),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_rule(self, rule_id) -> dict | None:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM alert_rules WHERE id = ? AND owner_id = ?",
                (rule_id, self.owner_id),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return dict(row)

    def list_rules(self) -> list[dict]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM alert_rules WHERE owner_id = ? ORDER BY id",
                (self.owner_id,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def list_active_rules(self) -> list[dict]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM alert_rules WHERE is_active = 1 AND owner_id = ? ORDER BY id",
                (self.owner_id,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def delete_rule(self, rule_id) -> bool:
        """Returns True if a row was deleted. Its events stay, with rule_id set to NULL."""
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                "DELETE FROM alert_rules WHERE id = ? AND owner_id = ?",
                (rule_id, self.owner_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def list_events(self) -> list[dict]:
        """Latest 100 events, newest first. Older history remains in SQLite."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM alert_events WHERE owner_id = ? ORDER BY triggered_at DESC, id DESC LIMIT 100",
                (self.owner_id,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def count_events(self):
        conn = get_connection(self.db_path)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM alert_events WHERE owner_id = ?", (self.owner_id,)
            ).fetchone()[0]
        finally:
            conn.close()

    def fire_rule(self, rule, observed_price) -> bool:
        """Deactivate the rule and log an event in one transaction.

        Returns False if the rule was already inactive, so a rule only fires once.
        """
        conn = get_connection(self.db_path)
        try:
            # IMMEDIATE takes the write lock now, so two threads can't both
            # see is_active = 1 and fire the same rule.
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE alert_rules SET is_active = 0 WHERE id = ? AND is_active = 1 "
                "AND owner_id = ? AND rule_token = ?",
                (rule["id"], self.owner_id, rule["rule_token"]),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False
            conn.execute(
                "INSERT INTO alert_events"
                " (rule_id, ticker, condition, threshold, observed_price, triggered_at, owner_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    rule["id"],
                    rule["ticker"],
                    rule["condition"],
                    rule["threshold"],
                    observed_price,
                    utc_now(),
                    self.owner_id,
                ),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
