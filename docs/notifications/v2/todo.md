# Notifications v2 TODO

Implement each feature independently and commit them sequentially in dependency order.

---

## 1. Infrastructure: Cryptography Dependency & Credential Service

**commit:** `feat: add cryptography dependency and credential encryption service`

- [x] Add `cryptography` to `pyproject.toml` and synchronize `uv.lock`.
- [x] Create `app/services/credential.py`:
  - [x] `load_fernet_from_env(env_var: str = "APP_CREDENTIAL_KEY") -> Fernet`: Load the master key from the environment. Raise a clear error if missing.
  - [x] `encrypt_credential(fernet: Fernet, payload: dict) -> str`: Serialize payload to JSON, encrypt it, and return a base64url string.
  - [x] `decrypt_credential(fernet: Fernet, credential_enc: str) -> dict`: Decrypt the base64url string, parse JSON, and return the dictionary.

---

## 2. DB Schema Migration

**commit:** `feat: migrate schema to v2 user, subscription, and endpoint tables`

- [x] Create `app/migrations/` directory.
- [x] Create `app/migrations/m20260528_multi_channel_schema.sql` containing the full v2 DDL:
  - [x] `users` table (`id`, `name`, `enabled BOOLEAN`, `created_at`, `updated_at`).
  - [x] `user_index_subscriptions` table (`user_id`, `index_id`, `base_amount`, `enabled BOOLEAN`, `UNIQUE(user_id, index_id)`).
  - [x] `user_notification_endpoints` table (`user_id`, `channel_type`, `target`, `credential_enc`, `enabled BOOLEAN`, `UNIQUE(user_id, channel_type, target)`).
  - [x] Update `valuation_signals`: FK points to `user_index_subscription_id`, update `UNIQUE` constraint.
  - [x] Update `notifications`: Add `endpoint_id` column and FK.
  - [x] `DROP TABLE user_subscriptions`.
- [x] Create `app/migrations/m20260528_multi_channel_notifications.py`:
  - [x] Read data from the old `user_subscriptions` table.
  - [x] Create a `default` user record in the `users` table (idempotent; skip if exists).
  - [x] Write `(user_id, index_id, base_amount)` to `user_index_subscriptions`.
  - [x] Write `(notify_channel, notify_target)` to `user_notification_endpoints` with `credential_enc` generated using the injected Fernet instance.
  - [x] Execute `m20260528_multi_channel_schema.sql` DDL.
  - [x] Support `--db-path` and `--dry-run` arguments.
- [x] Update `app/schema.sql` to the full v2 version (to act as the entry point for initializing a new database).

---

## 3. Repository Layer: CRUD for New Tables

**commit:** `feat: add v2 repositories for users, subscriptions, and endpoints`

- [x] Add `UserRepository` in `app/repositories/sqlite.py`:
  - [x] `get_or_create(name: str) -> sqlite3.Row`.
  - [x] `get_by_id(user_id: str) -> sqlite3.Row | None`.
- [x] Add `UserIndexSubscriptionRepository`:
  - [x] `get_or_create(user_id, index_id, base_amount) -> sqlite3.Row`.
  - [x] `list_enabled_for_index(index_id: str) -> list[sqlite3.Row]`.
  - [x] `get_by_identity(user_id, index_id) -> sqlite3.Row | None`.
- [x] Add `UserNotificationEndpointRepository`:
  - [x] `create(user_id, channel_type, target, credential_enc) -> str`.
  - [x] `list_enabled_for_index_and_channel(index_id, channel_type) -> list[sqlite3.Row]` (includes a 3-table JOIN).
  - [x] `get_by_identity(user_id, channel_type, target) -> sqlite3.Row | None`.
- [x] Update `NotificationRepository`:
  - [x] Add the required `endpoint_id` parameter to `create_attempt()`.
  - [x] Add `already_sent(signal_id: str, endpoint_id: str) -> bool`.

---

## 4. Feishu Notification Channel

**commit:** `feat: add Feishu webhook notification channel`

- [x] Create `app/services/feishu_channel.py`:
  - [x] `FeishuConfig(webhook_token, timeout_seconds=10)`.
  - [x] `FeishuRenderer`: Reuse `SimpleTemplateRenderer` and load `templates/feishu_signal.md`.
  - [x] `FeishuChannel`: Implement `NotificationChannel` protocol.
    - [x] `name = "feishu"`.
    - [x] `target` property returns `feishu:hook/{last_8_chars_of_webhook_token}` (plaintext snippet).
    - [x] `send()` constructs the `{"msg_type": "text", "content": {"text": ...}}` payload and POSTs to `https://open.feishu.cn/open-apis/bot/v2/hook/{webhook_token}`.
    - [x] Return `status=failed` for HTTP 4xx/5xx responses.
    - [x] Catch network exceptions and return `status=failed`.
    - [x] Implement `sanitize_feishu_error()`: Remove the full webhook token from the error message.
    - [x] Support an injectable `http_client` (similar to the Telegram design, for testing).
- [x] Create `templates/feishu_signal.md` (initial content identical to `telegram_signal.md`).

---

## 5. Channel Manager Layer

**commit:** `feat: add NotificationChannelManager protocol and Telegram/Feishu managers`

- [x] Create `app/services/channel_managers.py`:
  - [x] Define the `NotificationChannelManager` Protocol (`channel_type: str`, `dispatch_signal(context, repository) -> list[NotificationResult]`).
  - [x] Implement `TelegramManager(db, fernet)`:
    - [x] `dispatch_signal()` queries enabled Telegram endpoints for the index.
    - [x] Check idempotency using `already_sent()` for each endpoint.
    - [x] Decrypt `credential_enc` to retrieve `bot_token` and instantiate `TelegramChannel`.
    - [x] Execute `channel.send(context)` and record the result via `repo.create_attempt()`.
  - [x] Implement `FeishuManager(db, fernet)`:
    - [x] Similar to Telegram, but for `channel_type='feishu'`, decrypt to get `webhook_token`, and construct `FeishuChannel`.

---

## 6. Dispatcher Upgrade: Accept Manager List

**commit:** `refactor: upgrade NotificationDispatcher to accept channel managers`

- [x] Update `app/services/notifications.py`:
  - [x] Modify `NotificationDispatcher.__init__` to accept `managers: list[NotificationChannelManager]` (while retaining `repository` injection).
  - [x] Modify `dispatch()` to iterate over `managers`, invoke `dispatch_signal()`, and return the consolidated results.
  - [x] Keep the `NotificationChannel` protocol intact (used internally by managers).

---

## 7. Job Layer Integration

**commit:** `feat: wire daily_run to v2 channel managers and encrypted credentials`

- [x] Update `app/jobs/daily_run.py`:
  - [x] Load `APP_CREDENTIAL_KEY` from environment variables and initialize `Fernet`.
  - [x] Instantiate `TelegramManager` and `FeishuManager` (injecting db conn and fernet).
  - [x] Replace the old channel list setup with `NotificationDispatcher(managers=[...])`.
  - [x] Update `valuation_signals` writing logic to set `user_index_subscription_id` instead of `user_subscription_id`.
- [x] Add documentation about `APP_CREDENTIAL_KEY` in `.env.example` or equivalent.

---

## 8. Feishu Smoke Test

**commit:** `feat: add Feishu smoke test job`

- [x] Create `app/jobs/feishu_smoke.py`, supporting:
  - [x] `--dry-run`: Decrypt credential, render the Feishu message, and print it to stdout without sending.
  - [x] `--send`: Send a test message to the configured Feishu Webhook. Only record the attempt if `--db-path` is explicitly provided.
  - [x] `--db-path`: Optional argument specifying the path to the testing database.
