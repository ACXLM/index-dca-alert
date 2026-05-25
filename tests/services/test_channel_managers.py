import sqlite3
import pytest
from cryptography.fernet import Fernet
from app.services.credential import encrypt_credential
from app.services.notifications import NotificationContext, NotificationResult
from app.services.channel_managers import TelegramManager, FeishuManager
from app.repositories.sqlite import (
    UserNotificationEndpointRepository,
    UserRepository,
    UserIndexSubscriptionRepository,
    NotificationRepository
)

class FakeChannel:
    def __init__(self, name):
        self.name = name
        self.target = "fake_target"
        self.sent_count = 0

    def send(self, context):
        self.sent_count += 1
        return NotificationResult(channel=self.name, target=self.target, status="sent", message="msg", sent_at="now")

@pytest.fixture
def db_conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("app/schema.sql") as f:
        c.executescript(f.read())
    c.execute("INSERT INTO indices (id, code, name, market, category, currency, timezone, primary_provider, source_symbol, created_at, updated_at) VALUES ('idx1', 'code1', 'n', 'm', 'c', 'cu', 'tz', 'p', 's', 'now', 'now')")
    
    # Create user, sub, endpoint
    u_repo = UserRepository(c)
    s_repo = UserIndexSubscriptionRepository(c)
    e_repo = UserNotificationEndpointRepository(c)
    
    user = u_repo.get_or_create("alice")
    sub = s_repo.get_or_create(user["id"], "idx1", 1000)
    
    # insert a signal
    c.execute("INSERT INTO valuation_signals (id, user_index_subscription_id, index_id, trade_date, signal_quality, valuation_zone, dca_ratio, suggested_amount, message, created_at) VALUES ('sig1', ?, 'idx1', '2023-01-01', 'q', 'z', 1.0, 1000, 'msg', 'now')", (sub["id"],))
    c.commit()
    
    return c, user["id"]

@pytest.fixture
def fernet():
    return Fernet(Fernet.generate_key())

@pytest.fixture
def dummy_context():
    return NotificationContext(
        signal_id="sig1",
        index_name="CSI300",
        trade_date="2023-01-01",
        market="CN",
        category="broad",
        base_amount=1000,
        dca_ratio=1.0,
        suggested_amount=1000,
        signal_quality="high",
        valuation_zone="low",
    )

def test_telegram_manager(db_conn, fernet, dummy_context, monkeypatch):
    conn, user_id = db_conn
    e_repo = UserNotificationEndpointRepository(conn)
    cred = encrypt_credential(fernet, {"bot_token": "token1", "chat_id": "chat1"})
    e_repo.create(user_id, "telegram", "chat1", cred)
    
    mgr = TelegramManager(conn, fernet)
    
    # mock construct_channel to avoid network
    def fake_construct(*args, **kwargs):
        return FakeChannel("telegram")
    monkeypatch.setattr(mgr, "_construct_channel", fake_construct)
    
    n_repo = NotificationRepository(conn)
    
    # dispatch
    results = mgr.dispatch_signal(dummy_context, n_repo)
    assert len(results) == 1
    assert results[0].status == "sent"
    
    # Check that already_sent works
    results2 = mgr.dispatch_signal(dummy_context, n_repo)
    assert len(results2) == 0 # skipped because already sent

def test_manager_decryption_fail(db_conn, fernet, dummy_context, monkeypatch):
    conn, user_id = db_conn
    e_repo = UserNotificationEndpointRepository(conn)
    # create endpoint with invalid credential string
    endpoint_id = e_repo.create(user_id, "telegram", "chat2", "invalid_cred")
    
    mgr = TelegramManager(conn, fernet)
    n_repo = NotificationRepository(conn)
    
    results = mgr.dispatch_signal(dummy_context, n_repo)
    assert len(results) == 1
    assert results[0].status == "failed"
    
    # DB should have a failed notification
    row = conn.execute("SELECT * FROM notifications WHERE endpoint_id = ?", (endpoint_id,)).fetchone()
    assert row["status"] == "failed"
