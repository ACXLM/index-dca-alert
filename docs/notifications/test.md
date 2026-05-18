# Notifications Tests

## Unit Tests

- Telegram rendering from a fixture signal.
- Missing optional signal fields render clearly.
- `insufficient_history` signals render without a DCA amount.
- Template missing placeholders raise clear rendering errors.
- `dca_ratio_percent` is formatted from `dca_ratio * 100`.
- Notification channels implement a common interface and can be composed.
- Telegram request payload is built from environment configuration loaded from
  environment variables or local `.env` via `python-dotenv`.
- Telegram payload does not require `parse_mode` for the MVP plain-text
  template.

## Integration Tests

- Successful Telegram send records `notifications.status = sent`.
- Failed Telegram send records `notifications.status = failed` and
  `notifications.error_message = sanitized_error`.
- Failed Telegram send records do not include `TG_BOT_TOKEN` or full Telegram
  API URLs in `error_message`.
- Telegram sender uses an explicit timeout.
- Telegram sender supports an injectable HTTP client so tests do not call live
  Telegram.
- Dispatching through multiple channels records one attempt per channel.
- Telegram is disabled or mocked for normal local tests.

## Manual Verification

- Render one Telegram smoke-test message with `--dry-run`.
- Send one Telegram test notification using local `.env` secrets.
- Confirm no secret values are logged or committed.
