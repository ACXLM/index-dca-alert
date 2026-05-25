import os
import sqlite3
import pytest
from cryptography.fernet import Fernet
from app.migrations.v2_migrate import run_migration

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    # create old schema
    conn.execute("""
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
    """)
    conn.execute("""
        CREATE TABLE indices (
            id TEXT PRIMARY KEY,
            code TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE valuation_signals (
            id TEXT PRIMARY KEY
        )
    """)
    conn.execute("""
        CREATE TABLE notifications (
            id TEXT PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()
    return db_path

def test_migration_script(temp_db, monkeypatch):
    fernet_key = Fernet.generate_key()
    monkeypatch.setenv("APP_CREDENTIAL_KEY", fernet_key.decode("utf-8"))
    monkeypatch.setenv("TG_BOT_TOKEN", "fake_bot_token")
    
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT INTO indices (id, code) VALUES ('idx1', '000300')")
    conn.execute("""
        INSERT INTO user_subscriptions (id, user_id, index_id, base_amount, notify_channel, notify_target, enabled, created_at, updated_at)
        VALUES ('sub1', 'user1', 'idx1', 1000, 'telegram', 'chat1', 1, '2023-01-01', '2023-01-01')
    """)
    conn.commit()
    conn.close()
    
    run_migration(str(temp_db))
    
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    
    users = conn.execute("SELECT * FROM users").fetchall()
    assert len(users) == 1
    assert users[0]["name"] == "default"
    
    subs = conn.execute("SELECT * FROM user_index_subscriptions").fetchall()
    assert len(subs) == 1
    assert subs[0]["index_id"] == "idx1"
    
    endpoints = conn.execute("SELECT * FROM user_notification_endpoints").fetchall()
    assert len(endpoints) == 1
    
    from app.services.credential import load_fernet_from_env, decrypt_credential
    fernet = load_fernet_from_env()
    cred = decrypt_credential(fernet, endpoints[0]["credential_enc"])
    assert cred["bot_token"] == "fake_bot_token"
    
    # Old table dropped
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT * FROM user_subscriptions")
        
    conn.close()

def test_schema_execution(tmp_path):
    db_path = tmp_path / "schema.sqlite"
    conn = sqlite3.connect(db_path)
    with open("app/schema.sql", "r") as f:
        conn.executescript(f.read())
        
    # Check tables
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "users" in tables
    assert "user_index_subscriptions" in tables
    assert "user_notification_endpoints" in tables
    assert "valuation_signals" in tables
    assert "notifications" in tables
    conn.close()
