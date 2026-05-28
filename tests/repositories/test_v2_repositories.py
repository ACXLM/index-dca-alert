from __future__ import annotations

import sqlite3

import pytest

from app.repositories.sqlite import (
    NotificationRepository,
    UserIndexSubscriptionRepository,
    UserNotificationEndpointRepository,
    UserRepository,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    with open("app/schema.sql") as f:
        c.executescript(f.read())
    c.execute(
        "INSERT INTO indices (id, code, name, market, category, currency, timezone, "
        "primary_provider, source_symbol, created_at, updated_at) "
        "VALUES ('idx1', 'code1', 'name1', 'mkt', 'cat', 'cur', 'tz', 'prov', 'sym', 'now', 'now')"
    )
    c.commit()
    yield c
    c.close()


class TestUserRepository:
    def test_get_or_create_inserts_on_first_call(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)

        user = repo.get_or_create("alice")

        assert user is not None
        assert user["name"] == "alice"

    def test_get_or_create_returns_existing_without_duplicate(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        user1 = repo.get_or_create("alice")
        user2 = repo.get_or_create("alice")

        assert user1["id"] == user2["id"]
        count = conn.execute("SELECT COUNT(*) FROM users WHERE name = 'alice'").fetchone()[0]
        assert count == 1

    def test_get_by_id_returns_none_for_nonexistent(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)

        result = repo.get_by_id("nonexistent-id")

        assert result is None


class TestUserIndexSubscriptionRepository:
    def test_get_or_create_inserts_with_base_amount(self, conn: sqlite3.Connection) -> None:
        user = UserRepository(conn).get_or_create("alice")
        repo = UserIndexSubscriptionRepository(conn)

        sub = repo.get_or_create(user["id"], "idx1", 1500.0)

        assert sub is not None
        assert sub["base_amount"] == 1500.0

    def test_get_or_create_returns_existing_on_second_call(self, conn: sqlite3.Connection) -> None:
        user = UserRepository(conn).get_or_create("alice")
        repo = UserIndexSubscriptionRepository(conn)
        sub1 = repo.get_or_create(user["id"], "idx1", 1000.0)
        sub2 = repo.get_or_create(user["id"], "idx1", 2000.0)

        assert sub1["id"] == sub2["id"]

    def test_list_enabled_for_index_excludes_disabled(self, conn: sqlite3.Connection) -> None:
        user = UserRepository(conn).get_or_create("alice")
        repo = UserIndexSubscriptionRepository(conn)
        sub = repo.get_or_create(user["id"], "idx1", 1000.0)

        subs = repo.list_enabled_for_index("idx1")
        assert len(subs) == 1

        conn.execute("UPDATE user_index_subscriptions SET enabled = 0 WHERE id = ?", (sub["id"],))
        conn.commit()

        assert len(repo.list_enabled_for_index("idx1")) == 0

    def test_list_enabled_for_index_returns_empty_when_none(self, conn: sqlite3.Connection) -> None:
        repo = UserIndexSubscriptionRepository(conn)

        assert repo.list_enabled_for_index("idx1") == []


class TestUserNotificationEndpointRepository:
    def test_create_and_get_by_identity(self, conn: sqlite3.Connection) -> None:
        user = UserRepository(conn).get_or_create("alice")
        repo = UserNotificationEndpointRepository(conn)

        endpoint_id = repo.create(user["id"], "telegram", "chat-1", "enc_cred_value")
        endpoint = repo.get_by_identity(user["id"], "telegram", "chat-1")

        assert endpoint is not None
        assert endpoint["id"] == endpoint_id
        assert endpoint["credential_enc"] == "enc_cred_value"

    def test_list_enabled_for_index_and_channel_respects_all_filters(self, conn: sqlite3.Connection) -> None:
        user = UserRepository(conn).get_or_create("alice")
        UserIndexSubscriptionRepository(conn).get_or_create(user["id"], "idx1", 1000.0)
        repo = UserNotificationEndpointRepository(conn)
        repo.create(user["id"], "telegram", "chat-1", "enc_cred")

        results = repo.list_enabled_for_index_and_channel("idx1", "telegram")
        assert len(results) == 1
        assert results[0]["target"] == "chat-1"

    def test_list_enabled_excludes_disabled_user(self, conn: sqlite3.Connection) -> None:
        user = UserRepository(conn).get_or_create("alice")
        UserIndexSubscriptionRepository(conn).get_or_create(user["id"], "idx1", 1000.0)
        repo = UserNotificationEndpointRepository(conn)
        repo.create(user["id"], "telegram", "chat-1", "enc_cred")

        conn.execute("UPDATE users SET enabled = 0 WHERE id = ?", (user["id"],))
        conn.commit()

        assert repo.list_enabled_for_index_and_channel("idx1", "telegram") == []

    def test_list_enabled_excludes_disabled_subscription(self, conn: sqlite3.Connection) -> None:
        user = UserRepository(conn).get_or_create("alice")
        sub = UserIndexSubscriptionRepository(conn).get_or_create(user["id"], "idx1", 1000.0)
        repo = UserNotificationEndpointRepository(conn)
        repo.create(user["id"], "telegram", "chat-1", "enc_cred")

        conn.execute("UPDATE user_index_subscriptions SET enabled = 0 WHERE id = ?", (sub["id"],))
        conn.commit()

        assert repo.list_enabled_for_index_and_channel("idx1", "telegram") == []

    def test_list_enabled_excludes_disabled_endpoint(self, conn: sqlite3.Connection) -> None:
        user = UserRepository(conn).get_or_create("alice")
        UserIndexSubscriptionRepository(conn).get_or_create(user["id"], "idx1", 1000.0)
        repo = UserNotificationEndpointRepository(conn)
        endpoint_id = repo.create(user["id"], "telegram", "chat-1", "enc_cred")

        conn.execute("UPDATE user_notification_endpoints SET enabled = 0 WHERE id = ?", (endpoint_id,))
        conn.commit()

        assert repo.list_enabled_for_index_and_channel("idx1", "telegram") == []

    def test_list_enabled_returns_empty_when_no_match(self, conn: sqlite3.Connection) -> None:
        repo = UserNotificationEndpointRepository(conn)

        assert repo.list_enabled_for_index_and_channel("idx1", "telegram") == []

    def test_duplicate_target_raises_unique_constraint(self, conn: sqlite3.Connection) -> None:
        user = UserRepository(conn).get_or_create("alice")
        repo = UserNotificationEndpointRepository(conn)
        repo.create(user["id"], "telegram", "chat-1", "enc1")

        with pytest.raises(sqlite3.IntegrityError):
            repo.create(user["id"], "telegram", "chat-1", "enc2")


class TestNotificationRepository:
    def _setup_signal(self, conn: sqlite3.Connection) -> tuple[str, str]:
        user = UserRepository(conn).get_or_create("alice")
        sub = UserIndexSubscriptionRepository(conn).get_or_create(user["id"], "idx1", 1000.0)
        endpoint_id = UserNotificationEndpointRepository(conn).create(
            user["id"], "telegram", "chat-1", "enc_cred"
        )
        conn.execute(
            "INSERT INTO valuation_signals "
            "(id, user_index_subscription_id, index_id, trade_date, "
            "signal_quality, valuation_zone, dca_ratio, suggested_amount, message, created_at) "
            "VALUES ('sig1', ?, 'idx1', '2023-01-01', 'q', 'z', 1.0, 1000, 'msg', 'now')",
            (sub["id"],),
        )
        conn.commit()
        return "sig1", endpoint_id

    def test_create_attempt_with_endpoint_id(self, conn: sqlite3.Connection) -> None:
        signal_id, endpoint_id = self._setup_signal(conn)
        repo = NotificationRepository(conn)

        notification_id = repo.create_attempt(
            signal_id, "telegram", "chat-1", "sent", endpoint_id=endpoint_id, sent_at="2023-01-01T00:00:00Z"
        )

        row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
        assert row is not None
        assert row["endpoint_id"] == endpoint_id
        assert row["status"] == "sent"

    def test_already_sent_returns_true_for_sent_status(self, conn: sqlite3.Connection) -> None:
        signal_id, endpoint_id = self._setup_signal(conn)
        repo = NotificationRepository(conn)
        repo.create_attempt(signal_id, "telegram", "chat-1", "sent", endpoint_id=endpoint_id)

        assert repo.already_sent(signal_id, endpoint_id) is True

    def test_already_sent_returns_false_for_failed_status(self, conn: sqlite3.Connection) -> None:
        signal_id, endpoint_id = self._setup_signal(conn)
        repo = NotificationRepository(conn)
        repo.create_attempt(signal_id, "telegram", "chat-1", "failed", endpoint_id=endpoint_id)

        assert repo.already_sent(signal_id, endpoint_id) is False

    def test_already_sent_returns_false_when_no_record(self, conn: sqlite3.Connection) -> None:
        repo = NotificationRepository(conn)

        assert repo.already_sent("nonexistent-sig", "nonexistent-endpoint") is False

    def test_already_sent_does_not_match_across_endpoints(self, conn: sqlite3.Connection) -> None:
        signal_id, endpoint_id = self._setup_signal(conn)
        user_id = conn.execute("SELECT user_id FROM user_notification_endpoints").fetchone()["user_id"]
        other_endpoint_id = UserNotificationEndpointRepository(conn).create(
            user_id, "feishu", "feishu:hook/abcdefgh", "enc2"
        )
        repo = NotificationRepository(conn)
        repo.create_attempt(signal_id, "telegram", "chat-1", "sent", endpoint_id=endpoint_id)

        assert repo.already_sent(signal_id, other_endpoint_id) is False
