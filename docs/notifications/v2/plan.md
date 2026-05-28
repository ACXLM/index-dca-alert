# Notifications v2 Plan

## Goal

Extend the MVP Telegram baseline with two new capabilities:

1. **Feishu Bot Notification Channel** (plain text).
2. **Multi-Subscriber Management**: Persist subscription relations in the database to support future Web UI operations (create/read/update/delete) and track which user is subscribed to which index.

---

## 1. Architecture: Channel Manager Pattern

The v2 notification architecture uses a **Channel Manager** pattern. The dispatcher traverses a list of channel managers (e.g., Telegram, Feishu), and each manager is responsible for querying the database for enabled endpoints of its type, decrypting the credentials, constructing the channel instances, and sending the notifications.

```text
Signal
  └─> NotificationDispatcher(managers=[TelegramManager, FeishuManager])
        ├─> TelegramManager
        │     └─> Query enabled Telegram endpoints for the index from DB
        │     └─> Decrypt credential → Build TelegramChannel → send
        │     └─> Record attempt in notifications table
        └─> FeishuManager
              └─> Query enabled Feishu endpoints for the index from DB
              └─> Decrypt credential → Build FeishuChannel → send
              └─> Record attempt in notifications table
```

```python
class NotificationChannelManager(Protocol):
    channel_type: str

    def dispatch_signal(
        self,
        context: NotificationContext,
        repository: NotificationRepository,
    ) -> list[NotificationResult]: ...
```

---

## 2. DB Schema Design

### Credential Design: Encrypted Storage with a Single Master Key

Instead of relying entirely on plaintext environment variables for every endpoint (which scales poorly for multiple users), the system stores credentials in an encrypted format.

- The database stores the **encrypted credential blob** using symmetric encryption (Fernet) and base64url encoding.
- The system maintains a single master key `APP_CREDENTIAL_KEY` (32 bytes, base64url encoded), which is injected via GitHub Secrets / `.env`.
- When the Web UI (future work) or a migration script adds an endpoint, the backend encrypts the credential using the master key before writing to the database.
- Credentials never appear in plaintext within the database, logs, or commit history.

**Target and Credential Storage**:
- `user_notification_endpoints.credential_enc`: Stores the Fernet-encrypted JSON blob.
  - Telegram: `{"bot_token": "7xxxxxxx:AAxxxxxx"}`
  - Feishu: `{"webhook_token": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}`
- `user_notification_endpoints.target`: Stores a plaintext, non-sensitive identifier used for logging and deduplication.
  - Telegram: `chat_id`
  - Feishu: `feishu:hook/{last_8_chars_of_token}`

> Note on Feishu Webhook URL: The base URL `https://open.feishu.cn/open-apis/bot/v2/hook/` is hardcoded in the application. Only the unique token is stored in the database.

### Schema

```sql
PRAGMA foreign_keys = ON;

-- User Entity (Identity Layer)
CREATE TABLE IF NOT EXISTS users (
  id         TEXT    PRIMARY KEY,
  name       TEXT    NOT NULL,
  enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TEXT    NOT NULL,
  updated_at TEXT    NOT NULL
);

-- User x Index Subscriptions (Business Layer)
CREATE TABLE IF NOT EXISTS user_index_subscriptions (
  id          TEXT    PRIMARY KEY,
  user_id     TEXT    NOT NULL,
  index_id    TEXT    NOT NULL,
  base_amount REAL    NOT NULL DEFAULT 1000.0,
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TEXT    NOT NULL,
  updated_at  TEXT    NOT NULL,
  UNIQUE(user_id, index_id),
  FOREIGN KEY(user_id)  REFERENCES users(id),
  FOREIGN KEY(index_id) REFERENCES indices(id)
);

-- User Notification Endpoints (Notification Layer)
CREATE TABLE IF NOT EXISTS user_notification_endpoints (
  id             TEXT    PRIMARY KEY,
  user_id        TEXT    NOT NULL,
  channel_type   TEXT    NOT NULL,   -- 'telegram' | 'feishu'
  target         TEXT    NOT NULL,   -- Non-sensitive identifier
  credential_enc TEXT    NOT NULL,   -- Fernet encrypted JSON blob
  enabled        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TEXT    NOT NULL,
  updated_at     TEXT    NOT NULL,
  UNIQUE(user_id, channel_type, target),
  FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Valuation Signals
CREATE TABLE IF NOT EXISTS valuation_signals (
  id                         TEXT    PRIMARY KEY,
  user_index_subscription_id TEXT    NOT NULL,
  index_id                   TEXT    NOT NULL,
  trade_date                 TEXT    NOT NULL,
  pe_percentile              REAL,
  pb_percentile              REAL,
  cape_percentile            REAL,
  dividend_yield_percentile  REAL,
  dividend_yield_inverse_percentile REAL,
  price_percentile           REAL,
  composite_percentile       REAL,
  signal_quality             TEXT    NOT NULL,
  valuation_zone             TEXT    NOT NULL,
  dca_ratio                  REAL    NOT NULL,
  suggested_amount           REAL    NOT NULL,
  message                    TEXT    NOT NULL,
  created_at                 TEXT    NOT NULL,
  UNIQUE(user_index_subscription_id, trade_date),
  FOREIGN KEY(user_index_subscription_id) REFERENCES user_index_subscriptions(id),
  FOREIGN KEY(index_id) REFERENCES indices(id)
);

-- Notification Send Attempts
CREATE TABLE IF NOT EXISTS notifications (
  id            TEXT    PRIMARY KEY,
  signal_id     TEXT    NOT NULL,
  endpoint_id   TEXT    NOT NULL,
  channel       TEXT    NOT NULL,   -- Redundant: 'telegram' | 'feishu'
  target        TEXT    NOT NULL,   -- Redundant identifier
  status        TEXT    NOT NULL,   -- 'sent' | 'failed'
  error_message TEXT,
  sent_at       TEXT,
  created_at    TEXT    NOT NULL,
  FOREIGN KEY(signal_id)   REFERENCES valuation_signals(id),
  FOREIGN KEY(endpoint_id) REFERENCES user_notification_endpoints(id)
);
```

### Entity Relationships

```text
users
  ├─── user_index_subscriptions ─── valuation_signals ─── notifications
  │         (user_id, index_id)        (subscription_id)      (signal_id)
  │                                                               ↑ endpoint_id
  └─── user_notification_endpoints
            (user_id, channel_type, target, credential_enc)
```

**Manager Query Logic**:
When a manager dispatches a signal for `index_id`, it executes a query equivalent to:
```sql
SELECT e.*
FROM user_notification_endpoints e
JOIN users u ON u.id = e.user_id
JOIN user_index_subscriptions s ON s.user_id = e.user_id
WHERE s.index_id = :index_id
  AND s.enabled = TRUE
  AND e.channel_type = :channel_type
  AND e.enabled = TRUE
  AND u.enabled = TRUE
```

---

### Migration Strategy

The old `user_subscriptions` table will be migrated to the new schema and dropped.

1. A migration script reads the existing `user_subscriptions` data.
2. It creates a `default` user record in the `users` table.
3. It writes `(user_id, index_id, base_amount)` to `user_index_subscriptions`.
4. It encrypts the credentials and writes `(notify_channel, notify_target, credential_enc)` to `user_notification_endpoints`.
5. It drops the old `user_subscriptions` table.
6. It recreates `valuation_signals` to point to `user_index_subscriptions`.

---

## 3. Idempotency

Before sending a notification, the Channel Manager invokes `repo.already_sent(signal_id, endpoint_id)`:

```sql
SELECT 1 FROM notifications
WHERE signal_id = ? AND endpoint_id = ? AND status = 'sent'
LIMIT 1
```

- If `sent`: Skip sending to prevent duplicate notifications.
- If `failed` or no record: Allow sending (retries on fallback runs).

---

## 4. Dependencies

| Library | Purpose |
|---|---|
| `cryptography` | For Fernet symmetric encryption and decryption of `credential_enc`. |

---

## 5. File Changes

### Added
- `app/migrations/m20260528_multi_channel_schema.sql`: v2 schema definitions and DROP old tables.
- `app/migrations/m20260528_multi_channel_notifications.py`: Migration script to move data to the new schema.
- `app/services/feishu_channel.py`: Contains `FeishuConfig`, `FeishuRenderer`, and `FeishuChannel`.
- `app/services/channel_managers.py`: Defines `NotificationChannelManager` protocol, `TelegramManager`, and `FeishuManager`.
- `app/services/credential.py`: Fernet wrapper containing `encrypt_credential()`, `decrypt_credential()`, and `load_fernet_from_env()`.
- `templates/feishu_signal.md`: Plaintext template for Feishu (initially mirrors the Telegram template).

### Modified
- `app/schema.sql`: Replaced with the complete v2 schema.
- `app/services/notifications.py`: `NotificationDispatcher` accepts a list of `managers`.
- `app/repositories/sqlite.py`: Add `UserRepository`, `UserIndexSubscriptionRepository`, `UserNotificationEndpointRepository`. Update `NotificationRepository.create_attempt` and add `already_sent()`.
- `app/jobs/daily_run.py`: Replace static channel initialization with Manager instances; inject `Fernet` instance.
- `pyproject.toml`: Add `cryptography` dependency.
