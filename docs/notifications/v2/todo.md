# Notifications v2 TODO

Implement each feature independently and commit them sequentially in dependency order.

---

## 1. Infrastructure: Cryptography Dependency & Credential Service

**commit:** `feat: add cryptography dependency and credential encryption service`

- [ ] Add `cryptography` to `pyproject.toml` and synchronize `uv.lock`.
- [ ] Create `app/services/credential.py`:
  - [ ] `load_fernet_from_env(env_var: str = "APP_CREDENTIAL_KEY") -> Fernet`: Load the master key from the environment. Raise a clear error if missing.
  - [ ] `encrypt_credential(fernet: Fernet, payload: dict) -> str`: Serialize payload to JSON, encrypt it, and return a base64url string.
  - [ ] `decrypt_credential(fernet: Fernet, credential_enc: str) -> dict`: Decrypt the base64url string, parse JSON, and return the dictionary.

---

## 2. DB Schema Migration

**commit:** `feat: migrate schema to v2 user, subscription, and endpoint tables`

- [ ] Create `app/migrations/` directory.
- [ ] Create `app/migrations/v2_schema.sql` containing the full v2 DDL:
  - [ ] `users` table (`id`, `name`, `enabled BOOLEAN`, `created_at`, `updated_at`).
  - [ ] `user_index_subscriptions` table (`user_id`, `index_id`, `base_amount`, `enabled BOOLEAN`, `UNIQUE(user_id, index_id)`).
  - [ ] `user_notification_endpoints` table (`user_id`, `channel_type`, `target`, `credential_enc`, `enabled BOOLEAN`, `UNIQUE(user_id, channel_type, target)`).
  - [ ] Update `valuation_signals`: FK points to `user_index_subscription_id`, update `UNIQUE` constraint.
  - [ ] Update `notifications`: Add `endpoint_id` column and FK.
  - [ ] `DROP TABLE user_subscriptions`.
- [ ] Create `app/migrations/v2_migrate.py`:
  - [ ] Read data from the old `user_subscriptions` table.
  - [ ] Create a `default` user record in the `users` table (idempotent; skip if exists).
  - [ ] Write `(user_id, index_id, base_amount)` to `user_index_subscriptions`.
  - [ ] Write `(notify_channel, notify_target)` to `user_notification_endpoints` with `credential_enc` generated using the injected Fernet instance.
  - [ ] Execute `v2_schema.sql` DDL.
  - [ ] Support `--db-path` and `--dry-run` arguments.
- [ ] Update `app/schema.sql` to the full v2 version (to act as the entry point for initializing a new database).

---

## 3. Repository Layer: CRUD for New Tables

**commit:** `feat: add v2 repositories for users, subscriptions, and endpoints`

- [ ] Add `UserRepository` in `app/repositories/sqlite.py`:
  - [ ] `get_or_create(name: str) -> sqlite3.Row`.
  - [ ] `get_by_id(user_id: str) -> sqlite3.Row | None`.
- [ ] Add `UserIndexSubscriptionRepository`:
  - [ ] `get_or_create(user_id, index_id, base_amount) -> sqlite3.Row`.
  - [ ] `list_enabled_for_index(index_id: str) -> list[sqlite3.Row]`.
  - [ ] `get_by_identity(user_id, index_id) -> sqlite3.Row | None`.
- [ ] Add `UserNotificationEndpointRepository`:
  - [ ] `create(user_id, channel_type, target, credential_enc) -> str`.
  - [ ] `list_enabled_for_index_and_channel(index_id, channel_type) -> list[sqlite3.Row]` (includes a 3-table JOIN).
  - [ ] `get_by_identity(user_id, channel_type, target) -> sqlite3.Row | None`.
- [ ] Update `NotificationRepository`:
  - [ ] Add the required `endpoint_id` parameter to `create_attempt()`.
  - [ ] Add `already_sent(signal_id: str, endpoint_id: str) -> bool`.

---

## 4. Feishu Notification Channel

**commit:** `feat: add Feishu webhook notification channel`

- [ ] Create `app/services/feishu_channel.py`:
  - [ ] `FeishuConfig(webhook_token, timeout_seconds=10)`.
  - [ ] `FeishuRenderer`: Reuse `SimpleTemplateRenderer` and load `templates/feishu_signal.md`.
  - [ ] `FeishuChannel`: Implement `NotificationChannel` protocol.
    - [ ] `name = "feishu"`.
    - [ ] `target` property returns `feishu:hook/{last_8_chars_of_webhook_token}` (plaintext snippet).
    - [ ] `send()` constructs the `{"msg_type": "text", "content": {"text": ...}}` payload and POSTs to `https://open.feishu.cn/open-apis/bot/v2/hook/{webhook_token}`.
    - [ ] Return `status=failed` for HTTP 4xx/5xx responses.
    - [ ] Catch network exceptions and return `status=failed`.
    - [ ] Implement `sanitize_feishu_error()`: Remove the full webhook token from the error message.
    - [ ] Support an injectable `http_client` (similar to the Telegram design, for testing).
- [ ] Create `templates/feishu_signal.md` (initial content identical to `telegram_signal.md`).

---

## 5. Channel Manager Layer

**commit:** `feat: add NotificationChannelManager protocol and Telegram/Feishu managers`

- [ ] Create `app/services/channel_managers.py`:
  - [ ] Define the `NotificationChannelManager` Protocol (`channel_type: str`, `dispatch_signal(context, repository) -> list[NotificationResult]`).
  - [ ] Implement `TelegramManager(db, fernet)`:
    - [ ] `dispatch_signal()` queries enabled Telegram endpoints for the index.
    - [ ] Check idempotency using `already_sent()` for each endpoint.
    - [ ] Decrypt `credential_enc` to retrieve `bot_token` and instantiate `TelegramChannel`.
    - [ ] Execute `channel.send(context)` and record the result via `repo.create_attempt()`.
  - [ ] Implement `FeishuManager(db, fernet)`:
    - [ ] Similar to Telegram, but for `channel_type='feishu'`, decrypt to get `webhook_token`, and construct `FeishuChannel`.

---

## 6. Dispatcher Upgrade: Accept Manager List

**commit:** `refactor: upgrade NotificationDispatcher to accept channel managers`

- [ ] Update `app/services/notifications.py`:
  - [ ] Modify `NotificationDispatcher.__init__` to accept `managers: list[NotificationChannelManager]` (while retaining `repository` injection).
  - [ ] Modify `dispatch()` to iterate over `managers`, invoke `dispatch_signal()`, and return the consolidated results.
  - [ ] Keep the `NotificationChannel` protocol intact (used internally by managers).

---

## 7. Job Layer Integration

**commit:** `feat: wire daily_run to v2 channel managers and encrypted credentials`

- [ ] Update `app/jobs/daily_run.py`:
  - [ ] Load `APP_CREDENTIAL_KEY` from environment variables and initialize `Fernet`.
  - [ ] Instantiate `TelegramManager` and `FeishuManager` (injecting db conn and fernet).
  - [ ] Replace the old channel list setup with `NotificationDispatcher(managers=[...])`.
  - [ ] Update `valuation_signals` writing logic to set `user_index_subscription_id` instead of `user_subscription_id`.
- [ ] Add documentation about `APP_CREDENTIAL_KEY` in `.env.example` or equivalent.

---

## 8. Feishu Smoke Test

**commit:** `feat: add Feishu smoke test job`

- [ ] Create `app/jobs/feishu_smoke.py`, supporting:
  - [ ] `--dry-run`: Decrypt credential, render the Feishu message, and print it to stdout without sending.
  - [ ] `--send`: Send a test message to the configured Feishu Webhook. Only record the attempt if `--db-path` is explicitly provided.
  - [ ] `--db-path`: Optional argument specifying the path to the testing database.
