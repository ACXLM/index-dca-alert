# Notifications v2 Tests

Tests are organized by feature points, corresponding to the implementation order in `todo.md`.

---

## 1. Credential Service

### Unit Tests

- `encrypt_credential()` output can be successfully reverted to the original dictionary by `decrypt_credential()`.
- The encrypted output is in base64url format and does not contain the plaintext token.
- Encrypting the same payload twice produces different ciphertexts (due to Fernet's random IV).
- `decrypt_credential()` throws a clear exception for invalid ciphertexts instead of returning an empty value.
- `load_fernet_from_env()` throws a clear error including the expected variable name when the environment variable is missing.
- `load_fernet_from_env()` throws an error when the environment variable value is not a valid Fernet key.

---

## 2. DB Schema and Migration

### Unit Tests

- `m20260528_multi_channel_schema.sql` can be executed entirely on an empty database without errors.
- After execution, `users`, `user_index_subscriptions`, `user_notification_endpoints`, `valuation_signals`, and `notifications` tables exist, and their fields and constraints match the DDL.
- `valuation_signals.user_index_subscription_id` FK constraint is active: inserting a non-existent `user_index_subscription_id` throws a foreign key error.
- `notifications.endpoint_id` FK constraint is active: inserting a non-existent `endpoint_id` throws a foreign key error.
- `UNIQUE(user_id, index_id)` constraint: inserting the same `(user_id, index_id)` pair twice throws a unique constraint error.
- `UNIQUE(user_id, channel_type, target)` constraint: inserting the same triplet twice throws a unique constraint error.
- `enabled BOOLEAN DEFAULT TRUE`: When `enabled` is omitted during insertion, the returned value is `1` (TRUE).

### Integration Tests (Migration Script)

- Executing `m20260528_multi_channel_notifications.py` on a database containing old `user_subscriptions` data results in:
  - The `users` table containing a `default` user record.
  - The row count of `user_index_subscriptions` matching the number of distinct `(user_id, index_id)` pairs from the old `user_subscriptions` table.
  - The `credential_enc` in `user_notification_endpoints` can be decrypted to retrieve the original `bot_token`.
  - The old `user_subscriptions` table no longer existing.
- Executing in `--dry-run` mode does not alter the database.
- Executing the migration script on an already migrated database throws no errors (idempotent).

---

## 3. Repository Layer

### Unit Tests (using in-memory SQLite)

**UserRepository**

- `get_or_create()` inserts and returns a new user row on the first call.
- `get_or_create()` returns the existing row on subsequent calls without inserting a duplicate.
- `get_by_id()` returns `None` for a non-existent ID.

**UserIndexSubscriptionRepository**

- `get_or_create()` returns a new subscription row on the first call, storing the `base_amount` correctly.
- `get_or_create()` returns the existing row on subsequent calls.
- `list_enabled_for_index()` only returns rows where `enabled=TRUE`.
- `list_enabled_for_index()` returns an empty list when there are no subscriptions.

**UserNotificationEndpointRepository**

- `create()` inserts a row that can be retrieved by `get_by_identity()`, and the `credential_enc` matches the inserted value.
- `list_enabled_for_index_and_channel()` returns endpoints satisfying all of the following:
  - `user.enabled = TRUE`
  - `user_index_subscriptions.index_id = :index_id` AND `enabled = TRUE`
  - `endpoint.channel_type = :channel_type` AND `enabled = TRUE`
- `list_enabled_for_index_and_channel()` does not return endpoints if the user, subscription, or endpoint is `enabled=FALSE`.
- `list_enabled_for_index_and_channel()` returns an empty list when no endpoints match.
- Inserting a duplicate `target` for the same user and channel throws a unique constraint error.

**NotificationRepository**

- `create_attempt()` accepts the `endpoint_id` parameter and correctly writes to the `notifications` table.
- `already_sent()` returns `True` for a record with `status='sent'`.
- `already_sent()` returns `False` for a record with `status='failed'`.
- `already_sent()` returns `False` when no record exists.
- `already_sent()` precisely matches the `(signal_id, endpoint_id)` combination and does not misidentify records across endpoints.

---

## 4. Feishu Channel

### Unit Tests (using fake HTTP client)

- `FeishuChannel.send()` issues a payload structured as `{"msg_type": "text", "content": {"text": <rendered>}}`, targeting URL `https://open.feishu.cn/open-apis/bot/v2/hook/{webhook_token}`.
- `FeishuChannel.target` returns `feishu:hook/{last_8_chars_of_webhook_token}` and does not include the full token.
- `FeishuChannel.send()` returns `status='failed'` on HTTP 4xx responses.
- `FeishuChannel.send()` returns `status='failed'` on HTTP 5xx responses.
- `FeishuChannel.send()` catches network exceptions (e.g., `requests.ConnectionError`) and returns `status='failed'`.
- `FeishuChannel.send()` returns `status='sent'` and a non-empty ISO timestamp for `sent_at` on success.
- `sanitize_feishu_error()` removes the full `webhook_token` from error strings.
- `sanitize_feishu_error()` removes the full Webhook URL (including the token part) from error strings.
- `FeishuRenderer` uses `templates/feishu_signal.md` to render and outputs a non-empty string.
- Rendering throws a `TemplateRenderError` if placeholders are missing instead of sending incomplete messages.
- The Feishu channel does not require a `parse_mode` parameter (it is plain text).

---

## 5. Channel Manager Layer

### Unit Tests (using fake endpoint rows + fake channel)

**TelegramManager**

- `dispatch_signal()` calls `already_sent()` for each retrieved endpoint and skips those that have already been successfully sent.
- For unsent endpoints, `dispatch_signal()` decrypts `credential_enc` to obtain `bot_token` and constructs a `TelegramChannel`.
- After sending, `dispatch_signal()` calls `repo.create_attempt()` with the correct `endpoint_id`.
- If an endpoint fails to send (`status='failed'`), it does not block subsequent endpoints from being sent.
- If decryption fails (e.g., `InvalidToken`), the endpoint is recorded as `status='failed'`, and subsequent endpoints are processed normally.
- Returns an empty list if there are no enabled endpoints.

**FeishuManager**

- All scenarios above hold true for `FeishuManager`, using `channel_type='feishu'` and decrypting to retrieve `webhook_token`.

### Integration Tests (using in-memory DB + fake HTTP client)

- Given two Telegram endpoints and one Feishu endpoint, `dispatch_signal()` generates three `notifications` records with distinct `endpoint_id`s.
- If one of the Telegram endpoints already has a `status='sent'` record, it is skipped, resulting in only two new records.
- If an endpoint previously resulted in `status='failed'`, it is retried during a fallback run (`already_sent()` returns `False`).

---

## 6. Dispatcher Upgrade

### Unit Tests

- `NotificationDispatcher(managers=[...])` accepts a list of Managers and iterates through them, calling `dispatch_signal()`.
- `dispatch()` returns the consolidated list of results from all Managers.
- Returns an empty list when the number of Managers is 0.
- The `NotificationChannel` protocol can still be constructed and invoked independently outside of the Manager (ensuring backward compatibility).

---

## 7. Job Layer Integration

### Integration Tests

- `daily_run` fails during startup with a clear error if `APP_CREDENTIAL_KEY` is missing, preventing signal calculation.
- `daily_run` correctly initializes `Fernet` and injects the Managers when `APP_CREDENTIAL_KEY` is present.
- `valuation_signals` are written with the `user_index_subscription_id` FK pointing to the correct `user_index_subscriptions` row.
- After `daily_run` completes, the `notifications` table includes the `endpoint_id` field with non-empty values.

---

## 8. Feishu Smoke Test

### Manual Verification

- `uv run python -m app.jobs.feishu_smoke --dry-run` renders the Feishu message and prints it to stdout without sending. The output does not contain the plaintext `webhook_token`.
- `uv run python -m app.jobs.feishu_smoke --send` sends a test message, and the corresponding Feishu group receives it.
- Using `--send` without `--db-path` does not write new records to the `notifications` table.
- Using `--send` with `--db-path` writes a `status='sent'` record to the `notifications` table.
- Both `--dry-run` and `--send` outputs are completely free of plaintext for `APP_CREDENTIAL_KEY`, `bot_token`, and `webhook_token`.

---

## End-to-End Verification

- Configure two Telegram subscribers and one Feishu subscriber. Run `daily_run`. All three endpoints receive notifications, and the `notifications` table generates three corresponding rows.
- Disconnect one of the Telegram Webhooks (e.g., using a fake invalid token). The system records `status='failed'` for that endpoint, while the other endpoints successfully receive their notifications.
- During a fallback run for the same `(signal_id, endpoint_id)`: Endpoints marked as `sent` are skipped, while `failed` endpoints are retried.
- Verify that `notifications.error_message` does not contain any plaintext tokens.
- Verify that once the database is committed back to the repository, the `credential_enc` field remains securely encrypted, preventing any direct extraction of `bot_token` or `webhook_token`.
