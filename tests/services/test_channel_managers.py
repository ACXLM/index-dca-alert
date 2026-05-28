from __future__ import annotations

import sqlite3

import pytest
import requests
from cryptography.fernet import Fernet

from app.repositories.sqlite import (
    NotificationRepository,
    UserIndexSubscriptionRepository,
    UserNotificationEndpointRepository,
    UserRepository,
)
from app.services.channel_managers import FeishuManager, TelegramManager
from app.services.credential import encrypt_credential
from app.services.notifications import NotificationContext, NotificationResult


class _FakeChannel:
    def __init__(self, name: str, *, status: str = "sent") -> None:
        self.name = name
        self.target = "fake-target"
        self.send_count = 0
        self._status = status

    def send(self, context: NotificationContext) -> NotificationResult:
        self.send_count += 1
        return NotificationResult(
            channel=self.name,
            target=self.target,
            status=self._status,
            message="msg",
            sent_at="2023-01-01T00:00:00Z" if self._status == "sent" else None,
            error_message="err" if self._status == "failed" else None,
        )


@pytest.fixture
def fernet() -> Fernet:
    return Fernet(Fernet.generate_key())


@pytest.fixture
def db_with_signal(fernet: Fernet) -> tuple[sqlite3.Connection, str, str]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open("app/schema.sql") as f:
        conn.executescript(f.read())

    conn.execute(
        "INSERT INTO indices (id, code, name, market, category, currency, timezone, "
        "primary_provider, source_symbol, created_at, updated_at) "
        "VALUES ('idx1', 'code1', 'n', 'm', 'c', 'cu', 'tz', 'p', 's', 'now', 'now')"
    )
    user = UserRepository(conn).get_or_create("alice")
    sub = UserIndexSubscriptionRepository(conn).get_or_create(user["id"], "idx1", 1000.0)
    conn.execute(
        "INSERT INTO valuation_signals "
        "(id, user_index_subscription_id, index_id, trade_date, "
        "signal_quality, valuation_zone, dca_ratio, suggested_amount, message, created_at) "
        "VALUES ('sig1', ?, 'idx1', '2023-01-01', 'q', 'z', 1.0, 1000, 'msg', 'now')",
        (sub["id"],),
    )
    conn.commit()
    return conn, user["id"], "idx1"


@pytest.fixture
def ctx() -> NotificationContext:
    return NotificationContext(
        signal_id="sig1",
        index_name="沪深300",
        trade_date="2023-01-01",
        market="CN",
        category="cn_broad",
        base_amount=1000,
        dca_ratio=1.0,
        suggested_amount=1000,
        signal_quality="complete",
        valuation_zone="合理",
    )


class TestTelegramManager:
    def test_dispatch_skips_already_sent_endpoint(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, user_id, index_id = db_with_signal
        cred = encrypt_credential(fernet, {"bot_token": "tok1"})
        endpoint_id = UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat1", cred)
        n_repo = NotificationRepository(conn)
        n_repo.create_attempt("sig1", "telegram", "chat1", "sent", endpoint_id=endpoint_id)

        mgr = TelegramManager(conn, fernet)
        monkeypatch.setattr(mgr, "_construct_channel", lambda cred, target: _FakeChannel("telegram"))

        results = mgr.dispatch_signal(ctx, n_repo)

        assert results == []

    def test_dispatch_decrypts_and_constructs_channel(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, user_id, index_id = db_with_signal
        cred = encrypt_credential(fernet, {"bot_token": "tok1"})
        UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat1", cred)
        n_repo = NotificationRepository(conn)

        captured_cred: list[dict] = []

        def fake_construct(c: dict, target: str) -> _FakeChannel:
            captured_cred.append(c)
            return _FakeChannel("telegram")

        mgr = TelegramManager(conn, fernet)
        monkeypatch.setattr(mgr, "_construct_channel", fake_construct)

        mgr.dispatch_signal(ctx, n_repo)

        assert captured_cred[0]["bot_token"] == "tok1"

    def test_dispatch_records_attempt_with_endpoint_id(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, user_id, index_id = db_with_signal
        cred = encrypt_credential(fernet, {"bot_token": "tok1"})
        endpoint_id = UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat1", cred)
        n_repo = NotificationRepository(conn)

        mgr = TelegramManager(conn, fernet)
        monkeypatch.setattr(mgr, "_construct_channel", lambda c, t: _FakeChannel("telegram"))

        mgr.dispatch_signal(ctx, n_repo)

        row = conn.execute("SELECT * FROM notifications").fetchone()
        assert row is not None
        assert row["endpoint_id"] == endpoint_id
        assert row["status"] == "sent"

    def test_dispatch_failed_endpoint_does_not_block_others(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, user_id, index_id = db_with_signal
        cred1 = encrypt_credential(fernet, {"bot_token": "tok1"})
        cred2 = encrypt_credential(fernet, {"bot_token": "tok2"})
        UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat1", cred1)
        UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat2", cred2)
        n_repo = NotificationRepository(conn)

        call_count = [0]

        def fake_construct(c: dict, target: str) -> _FakeChannel:
            call_count[0] += 1
            return _FakeChannel("telegram", status="failed" if call_count[0] == 1 else "sent")

        mgr = TelegramManager(conn, fernet)
        monkeypatch.setattr(mgr, "_construct_channel", fake_construct)

        results = mgr.dispatch_signal(ctx, n_repo)

        assert len(results) == 2
        statuses = {r.status for r in results}
        assert "failed" in statuses
        assert "sent" in statuses

    def test_dispatch_decryption_failure_records_failed_and_continues(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext
    ) -> None:
        conn, user_id, index_id = db_with_signal
        good_cred = encrypt_credential(fernet, {"bot_token": "tok"})
        UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat1", "invalid_cred_string")
        endpoint2_id = UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat2", good_cred)
        n_repo = NotificationRepository(conn)

        mgr = TelegramManager(conn, fernet)

        results = mgr.dispatch_signal(ctx, n_repo)

        failed = [r for r in results if r.status == "failed"]
        assert len(failed) >= 1
        bad_row = conn.execute(
            "SELECT * FROM notifications WHERE endpoint_id != ?", (endpoint2_id,)
        ).fetchone()
        assert bad_row is not None
        assert bad_row["status"] == "failed"

    def test_dispatch_returns_empty_when_no_endpoints(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext
    ) -> None:
        conn, user_id, index_id = db_with_signal
        n_repo = NotificationRepository(conn)

        mgr = TelegramManager(conn, fernet)
        results = mgr.dispatch_signal(ctx, n_repo)

        assert results == []


class TestFeishuManager:
    def test_dispatch_uses_feishu_channel_type(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, user_id, index_id = db_with_signal
        cred = encrypt_credential(fernet, {"webhook_token": "webhook-tok-12345678"})
        endpoint_id = UserNotificationEndpointRepository(conn).create(
            user_id, "feishu", "feishu:hook/12345678", cred
        )
        n_repo = NotificationRepository(conn)

        mgr = FeishuManager(conn, fernet)
        monkeypatch.setattr(mgr, "_construct_channel", lambda c, t: _FakeChannel("feishu"))

        results = mgr.dispatch_signal(ctx, n_repo)

        assert len(results) == 1
        assert results[0].status == "sent"
        row = conn.execute("SELECT * FROM notifications WHERE endpoint_id = ?", (endpoint_id,)).fetchone()
        assert row["status"] == "sent"

    def test_dispatch_skips_already_sent(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, user_id, index_id = db_with_signal
        cred = encrypt_credential(fernet, {"webhook_token": "tok"})
        endpoint_id = UserNotificationEndpointRepository(conn).create(
            user_id, "feishu", "feishu:hook/12345678", cred
        )
        n_repo = NotificationRepository(conn)
        n_repo.create_attempt("sig1", "feishu", "feishu:hook/12345678", "sent", endpoint_id=endpoint_id)

        mgr = FeishuManager(conn, fernet)
        monkeypatch.setattr(mgr, "_construct_channel", lambda c, t: _FakeChannel("feishu"))

        results = mgr.dispatch_signal(ctx, n_repo)

        assert results == []

    def test_dispatch_returns_empty_when_no_feishu_endpoints(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext
    ) -> None:
        conn, user_id, index_id = db_with_signal
        cred = encrypt_credential(fernet, {"bot_token": "tok"})
        UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat1", cred)
        n_repo = NotificationRepository(conn)

        mgr = FeishuManager(conn, fernet)
        results = mgr.dispatch_signal(ctx, n_repo)

        assert results == []


class TestManagerIntegration:
    def test_two_telegram_one_feishu_generates_three_records(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, user_id, index_id = db_with_signal
        tg_cred = encrypt_credential(fernet, {"bot_token": "tok"})
        fs_cred = encrypt_credential(fernet, {"webhook_token": "wh"})
        ep1 = UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat1", tg_cred)
        ep2 = UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat2", tg_cred)
        ep3 = UserNotificationEndpointRepository(conn).create(user_id, "feishu", "feishu:hook/12345678", fs_cred)
        n_repo = NotificationRepository(conn)

        tg_mgr = TelegramManager(conn, fernet)
        fs_mgr = FeishuManager(conn, fernet)
        monkeypatch.setattr(tg_mgr, "_construct_channel", lambda c, t: _FakeChannel("telegram"))
        monkeypatch.setattr(fs_mgr, "_construct_channel", lambda c, t: _FakeChannel("feishu"))

        tg_results = tg_mgr.dispatch_signal(ctx, n_repo)
        fs_results = fs_mgr.dispatch_signal(ctx, n_repo)
        all_results = tg_results + fs_results

        assert len(all_results) == 3
        rows = conn.execute("SELECT DISTINCT endpoint_id FROM notifications").fetchall()
        assert {r[0] for r in rows} == {ep1, ep2, ep3}

    def test_already_sent_endpoint_is_skipped_in_fallback(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, user_id, index_id = db_with_signal
        cred = encrypt_credential(fernet, {"bot_token": "tok"})
        ep1 = UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat1", cred)
        ep2 = UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat2", cred)
        n_repo = NotificationRepository(conn)
        n_repo.create_attempt("sig1", "telegram", "chat1", "sent", endpoint_id=ep1)

        mgr = TelegramManager(conn, fernet)
        monkeypatch.setattr(mgr, "_construct_channel", lambda c, t: _FakeChannel("telegram"))

        results = mgr.dispatch_signal(ctx, n_repo)

        assert len(results) == 1
        row = conn.execute("SELECT * FROM notifications WHERE endpoint_id = ?", (ep2,)).fetchone()
        assert row["status"] == "sent"

    def test_failed_endpoint_is_retried_in_fallback(
        self, db_with_signal: tuple, fernet: Fernet, ctx: NotificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, user_id, index_id = db_with_signal
        cred = encrypt_credential(fernet, {"bot_token": "tok"})
        ep = UserNotificationEndpointRepository(conn).create(user_id, "telegram", "chat1", cred)
        n_repo = NotificationRepository(conn)
        n_repo.create_attempt("sig1", "telegram", "chat1", "failed", endpoint_id=ep)

        mgr = TelegramManager(conn, fernet)
        monkeypatch.setattr(mgr, "_construct_channel", lambda c, t: _FakeChannel("telegram"))

        results = mgr.dispatch_signal(ctx, n_repo)

        assert len(results) == 1
        assert results[0].status == "sent"
