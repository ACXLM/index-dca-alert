import sqlite3
import pytest
from app.repositories.sqlite import (
    UserRepository,
    UserIndexSubscriptionRepository,
    UserNotificationEndpointRepository,
    NotificationRepository,
)

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("app/schema.sql") as f:
        c.executescript(f.read())
    # Add dummy index for FK constraints
    c.execute("INSERT INTO indices (id, code, name, market, category, currency, timezone, primary_provider, source_symbol, created_at, updated_at) VALUES ('idx1', 'code1', 'name1', 'mkt', 'cat', 'cur', 'tz', 'prov', 'sym', 'now', 'now')")
    c.commit()
    yield c
    c.close()

def test_user_repository(conn):
    repo = UserRepository(conn)
    user1 = repo.get_or_create("alice")
    assert user1["name"] == "alice"
    
    user2 = repo.get_or_create("alice")
    assert user1["id"] == user2["id"]
    
    assert repo.get_by_id(user1["id"])["name"] == "alice"
    assert repo.get_by_id("invalid") is None

def test_user_index_subscription_repository(conn):
    user_repo = UserRepository(conn)
    user = user_repo.get_or_create("alice")
    repo = UserIndexSubscriptionRepository(conn)
    
    sub1 = repo.get_or_create(user["id"], "idx1", 1000.0)
    assert sub1["base_amount"] == 1000.0
    
    sub2 = repo.get_or_create(user["id"], "idx1", 2000.0)
    assert sub1["id"] == sub2["id"]
    
    subs = repo.list_enabled_for_index("idx1")
    assert len(subs) == 1
    
    # disable sub
    conn.execute("UPDATE user_index_subscriptions SET enabled=0 WHERE id=?", (sub1["id"],))
    assert len(repo.list_enabled_for_index("idx1")) == 0
    assert len(repo.list_enabled_for_index("idx2")) == 0

def test_user_notification_endpoint_repository(conn):
    user_repo = UserRepository(conn)
    user = user_repo.get_or_create("alice")
    sub_repo = UserIndexSubscriptionRepository(conn)
    sub_repo.get_or_create(user["id"], "idx1", 1000.0)
    
    repo = UserNotificationEndpointRepository(conn)
    endpoint_id = repo.create(user["id"], "telegram", "chat1", "enc_token")
    
    endpoint = repo.get_by_identity(user["id"], "telegram", "chat1")
    assert endpoint["id"] == endpoint_id
    assert endpoint["credential_enc"] == "enc_token"
    
    endpoints = repo.list_enabled_for_index_and_channel("idx1", "telegram")
    assert len(endpoints) == 1
    assert endpoints[0]["target"] == "chat1"
    
    # Disable endpoint
    conn.execute("UPDATE user_notification_endpoints SET enabled=0")
    assert len(repo.list_enabled_for_index_and_channel("idx1", "telegram")) == 0
    
    # Unique constraint test
    with pytest.raises(sqlite3.IntegrityError):
        repo.create(user["id"], "telegram", "chat1", "enc2")

def test_notification_repository(conn):
    user_repo = UserRepository(conn)
    user = user_repo.get_or_create("alice")
    sub_repo = UserIndexSubscriptionRepository(conn)
    sub = sub_repo.get_or_create(user["id"], "idx1", 1000.0)
    end_repo = UserNotificationEndpointRepository(conn)
    endpoint_id = end_repo.create(user["id"], "telegram", "chat1", "enc_token")
    
    # Need a signal
    conn.execute("INSERT INTO valuation_signals (id, user_index_subscription_id, index_id, trade_date, signal_quality, valuation_zone, dca_ratio, suggested_amount, message, created_at) VALUES ('sig1', ?, 'idx1', '2023-01-01', 'q', 'z', 1.0, 1000, 'msg', 'now')", (sub["id"],))
    
    repo = NotificationRepository(conn)
    repo.create_attempt("sig1", "telegram", "chat1", "sent", endpoint_id=endpoint_id)
    
    assert repo.already_sent("sig1", endpoint_id) is True
    assert repo.already_sent("sig1", "other_end") is False
    assert repo.already_sent("sig2", endpoint_id) is False
    
    repo.create_attempt("sig1", "telegram", "chat2", "failed", endpoint_id=endpoint_id) # dummy status overwrite
    conn.execute("UPDATE notifications SET status='failed' WHERE status='sent'")
    assert repo.already_sent("sig1", endpoint_id) is False
