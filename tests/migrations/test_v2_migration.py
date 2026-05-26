from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.migrations.v2_migrate import run_migration
from app.services.credential import decrypt_credential, load_fernet_from_env


@pytest.fixture
def temp_db_with_old_schema(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE indices (
            id TEXT PRIMARY KEY,
            code TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE user_subscriptions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            index_id TEXT NOT NULL,
            base_amount REAL NOT NULL DEFAULT 1000,
            notify_channel TEXT NOT NULL DEFAULT 'telegram',
            notify_target TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE TABLE valuation_signals (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE notifications (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    return db_path


def test_v2_schema_executes_on_empty_database(tmp_path: Path) -> None:
    db_path = tmp_path / "new.sqlite"
    conn = sqlite3.connect(db_path)
    with open("app/schema.sql") as f:
        conn.executescript(f.read())

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "user_index_subscriptions", "user_notification_endpoints", "valuation_signals", "notifications"}.issubset(tables)
    conn.close()


def test_v2_schema_valuation_signals_fk_constraint(tmp_path: Path) -> None:
    db_path = tmp_path / "new.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    with open("app/schema.sql") as f:
        conn.executescript(f.read())

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO valuation_signals "
            "(id, user_index_subscription_id, index_id, trade_date, signal_quality, "
            "valuation_zone, dca_ratio, suggested_amount, message, created_at) "
            "VALUES ('s1', 'nonexistent-sub', 'idx1', '2023-01-01', 'q', 'z', 1.0, 1000, 'msg', 'now')"
        )
        conn.commit()
    conn.close()


def test_v2_schema_notifications_endpoint_fk_constraint(tmp_path: Path) -> None:
    db_path = tmp_path / "schema_fk_test.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    with open("app/schema.sql") as f:
        conn.executescript(f.read())

    conn.execute(
        "INSERT INTO indices (id, code, name, market, category, currency, timezone, "
        "primary_provider, source_symbol, created_at, updated_at) "
        "VALUES ('idx1', 'c', 'n', 'm', 'c', 'cu', 'tz', 'p', 's', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO users (id, name, enabled, created_at, updated_at) VALUES ('u1', 'alice', 1, 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO user_index_subscriptions "
        "(id, user_id, index_id, base_amount, enabled, created_at, updated_at) "
        "VALUES ('sub1', 'u1', 'idx1', 1000, 1, 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO valuation_signals "
        "(id, user_index_subscription_id, index_id, trade_date, signal_quality, "
        "valuation_zone, dca_ratio, suggested_amount, message, created_at) "
        "VALUES ('sig1', 'sub1', 'idx1', '2023-01-01', 'q', 'z', 1.0, 1000, 'msg', 'now')"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO notifications "
            "(id, signal_id, endpoint_id, channel, target, status, created_at) "
            "VALUES ('n1', 'sig1', 'nonexistent-endpoint', 'telegram', 'chat-1', 'sent', 'now')"
        )
        conn.commit()
    conn.close()


def test_v2_schema_user_index_subscription_unique_constraint(tmp_path: Path) -> None:
    db_path = tmp_path / "unique_test.sqlite"
    conn = sqlite3.connect(db_path)
    with open("app/schema.sql") as f:
        conn.executescript(f.read())
    conn.execute(
        "INSERT INTO indices (id, code, name, market, category, currency, timezone, "
        "primary_provider, source_symbol, created_at, updated_at) "
        "VALUES ('idx1', 'c', 'n', 'm', 'c', 'cu', 'tz', 'p', 's', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO users (id, name, enabled, created_at, updated_at) VALUES ('u1', 'alice', 1, 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO user_index_subscriptions "
        "(id, user_id, index_id, base_amount, enabled, created_at, updated_at) "
        "VALUES ('sub1', 'u1', 'idx1', 1000, 1, 'now', 'now')"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO user_index_subscriptions "
            "(id, user_id, index_id, base_amount, enabled, created_at, updated_at) "
            "VALUES ('sub2', 'u1', 'idx1', 2000, 1, 'now', 'now')"
        )
        conn.commit()
    conn.close()


def test_v2_schema_user_notification_endpoint_unique_constraint(tmp_path: Path) -> None:
    db_path = tmp_path / "uniq2.sqlite"
    conn = sqlite3.connect(db_path)
    with open("app/schema.sql") as f:
        conn.executescript(f.read())
    conn.execute(
        "INSERT INTO users (id, name, enabled, created_at, updated_at) VALUES ('u1', 'alice', 1, 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO user_notification_endpoints "
        "(id, user_id, channel_type, target, credential_enc, enabled, created_at, updated_at) "
        "VALUES ('e1', 'u1', 'telegram', 'chat-1', 'enc', 1, 'now', 'now')"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO user_notification_endpoints "
            "(id, user_id, channel_type, target, credential_enc, enabled, created_at, updated_at) "
            "VALUES ('e2', 'u1', 'telegram', 'chat-1', 'enc2', 1, 'now', 'now')"
        )
        conn.commit()
    conn.close()


def test_v2_schema_enabled_defaults_to_true(tmp_path: Path) -> None:
    db_path = tmp_path / "default_test.sqlite"
    conn = sqlite3.connect(db_path)
    with open("app/schema.sql") as f:
        conn.executescript(f.read())
    conn.execute(
        "INSERT INTO users (id, name, created_at, updated_at) VALUES ('u1', 'alice', 'now', 'now')"
    )
    conn.commit()

    row = conn.execute("SELECT enabled FROM users WHERE id = 'u1'").fetchone()
    assert row[0] == 1
    conn.close()


def test_migration_creates_default_user_and_subscriptions(
    temp_db_with_old_schema: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fernet_key = Fernet.generate_key()
    monkeypatch.setenv("APP_CREDENTIAL_KEY", fernet_key.decode("utf-8"))
    monkeypatch.setenv("TG_BOT_TOKEN", "fake_bot_token")

    db_path = temp_db_with_old_schema
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO indices (id, code) VALUES ('idx1', '000300')")
    conn.execute(
        "INSERT INTO user_subscriptions "
        "(id, user_id, index_id, base_amount, notify_channel, notify_target, enabled, created_at, updated_at) "
        "VALUES ('sub1', 'user1', 'idx1', 1000, 'telegram', 'chat1', 1, '2023-01-01', '2023-01-01')"
    )
    conn.execute(
        "INSERT INTO user_subscriptions "
        "(id, user_id, index_id, base_amount, notify_channel, notify_target, enabled, created_at, updated_at) "
        "VALUES ('sub2', 'user1', 'idx1', 1000, 'telegram', 'chat2', 1, '2023-01-01', '2023-01-01')"
    )
    conn.commit()
    conn.close()

    run_migration(str(db_path))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    users = conn.execute("SELECT * FROM users").fetchall()
    assert len(users) == 1
    assert users[0]["name"] == "default"

    subs = conn.execute("SELECT * FROM user_index_subscriptions").fetchall()
    assert len(subs) == 1

    conn.close()


def test_migration_credential_enc_is_decryptable(
    temp_db_with_old_schema: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fernet_key = Fernet.generate_key()
    monkeypatch.setenv("APP_CREDENTIAL_KEY", fernet_key.decode("utf-8"))
    monkeypatch.setenv("TG_BOT_TOKEN", "real_bot_token_abc")

    db_path = temp_db_with_old_schema
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO indices (id, code) VALUES ('idx1', '000300')")
    conn.execute(
        "INSERT INTO user_subscriptions "
        "(id, user_id, index_id, base_amount, notify_channel, notify_target, enabled, created_at, updated_at) "
        "VALUES ('sub1', 'user1', 'idx1', 1000, 'telegram', 'chat1', 1, '2023-01-01', '2023-01-01')"
    )
    conn.commit()
    conn.close()

    run_migration(str(db_path))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    endpoint = conn.execute("SELECT * FROM user_notification_endpoints").fetchone()
    fernet = load_fernet_from_env()
    cred = decrypt_credential(fernet, endpoint["credential_enc"])
    assert cred["bot_token"] == "real_bot_token_abc"
    conn.close()


def test_migration_drops_old_user_subscriptions_table(
    temp_db_with_old_schema: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fernet_key = Fernet.generate_key()
    monkeypatch.setenv("APP_CREDENTIAL_KEY", fernet_key.decode("utf-8"))
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")

    run_migration(str(temp_db_with_old_schema))

    conn = sqlite3.connect(temp_db_with_old_schema)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT * FROM user_subscriptions")
    conn.close()


def test_migration_dry_run_does_not_alter_database(
    temp_db_with_old_schema: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fernet_key = Fernet.generate_key()
    monkeypatch.setenv("APP_CREDENTIAL_KEY", fernet_key.decode("utf-8"))
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")

    db_path = temp_db_with_old_schema
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO indices (id, code) VALUES ('idx1', '000300')")
    conn.execute(
        "INSERT INTO user_subscriptions "
        "(id, user_id, index_id, base_amount, notify_channel, notify_target, enabled, created_at, updated_at) "
        "VALUES ('sub1', 'user1', 'idx1', 1000, 'telegram', 'chat1', 1, '2023-01-01', '2023-01-01')"
    )
    conn.commit()
    conn.close()

    run_migration(str(db_path), dry_run=True)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT * FROM user_subscriptions").fetchone()
    assert row is not None
    conn.close()


def test_migration_is_idempotent_on_already_migrated_db(
    temp_db_with_old_schema: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fernet_key = Fernet.generate_key()
    monkeypatch.setenv("APP_CREDENTIAL_KEY", fernet_key.decode("utf-8"))
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")

    db_path = temp_db_with_old_schema

    run_migration(str(db_path))
    run_migration(str(db_path))
