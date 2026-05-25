# Notifications Plan

## Goal

Send MVP DCA reminder messages through Telegram Bot and record each notification
attempt.

Telegram Bot is the only MVP notification channel. Notification templates start
as files under `templates/`; DB-backed templates can be added later.

The renderer should build the final message from a valuation signal and
`templates/telegram_signal.md`. The sender should use `TG_BOT_TOKEN` and
`TG_CHAT_ID` from GitHub Actions secrets or local `.env`.

Notification should stay independent from signal calculation, provider fetching,
market-window checks, and daily job idempotency. Runtime code decides when a
signal should be notified; notification code renders and sends a message, then
records the send attempt.

## Channel Abstraction

Notification channels should be composable. The MVP implements Telegram first,
but the design should allow later configurations such as:

- Telegram only
- Email only
- Telegram plus Email
- Additional channels without changing signal generation

Expected concepts:

- `NotificationContext`
- `NotificationMessage`
- `NotificationChannel`
- `NotificationResult`
- `NotificationDispatcher`

Each channel should implement a common interface such as:

```python
send(context) -> NotificationResult
```

The dispatcher can accept one or more channels and send through each configured
channel. Channel selection and composition should be explicit runtime
configuration, not hard-coded inside signal generation.

## Rendering Context

`SignalResult` does not contain every template field. Runtime code should build
a notification context with signal data plus index, valuation, and subscription
metadata.

The Telegram template currently expects:

- `index_name`
- `trade_date`
- `market`
- `category`
- raw valuation metrics such as `pe` and `pb`
- percentile fields
- `composite_percentile`
- `signal_quality`
- `valuation_zone`
- `base_amount`
- `dca_ratio_percent`
- `suggested_amount`

Missing optional values should render as `暂无`. Ratios and amounts should be
formatted by the renderer. For example, `dca_ratio_percent` is
`dca_ratio * 100`.

Use the existing `{{ key }}` template style with a lightweight standard-library
renderer. Do not add a heavy template dependency for the MVP. Missing
placeholders should raise a clear rendering error instead of sending a partially
rendered message.

Telegram messages are plain text for the MVP. Do not pass Telegram
`parse_mode` unless a future template explicitly requires Markdown or HTML
escaping.

## Environment and Secrets

Use `python-dotenv` so local development can load `.env` without shell-specific
manual sourcing. GitHub Actions should continue to provide secrets through
environment variables.

Required Telegram variables:

- `TG_BOT_TOKEN`
- `TG_CHAT_ID`

Secret safety rules:

- never commit `.env`
- never log `TG_BOT_TOKEN`
- never store `TG_BOT_TOKEN` in `notifications.error_message`
- never include the full Telegram API URL with token in errors
- failed send errors should include only sanitized status and response context

Telegram HTTP requests should set an explicit timeout, for example 10 seconds.
The HTTP client/session should be injectable so normal tests use a fake client
and do not call Telegram.

## Notification State

Each notification attempt should create a `notifications` row with:

- `channel`
- `target`
- `status`
- `error_message`
- `sent_at`
- `created_at`

Use `sent` for successful delivery and `failed` for failed delivery.

The send attempt flow should be explicit:

1. Build `NotificationContext`.
2. Render the channel-specific message.
3. Send through the configured channel.
4. On success, create `notifications.status = sent`.
5. On failure, create `notifications.status = failed` and
   `notifications.error_message = sanitized_error`.

Notification storage records attempts. It should not decide whether a signal was
already sent and should not perform de-duplication. Runtime orchestration can add
skip logic later if needed.

## Extension Boundary

Notification channels should have a clear interface so Email or other channels
can be added later without changing signal generation.

## Manual Smoke Test

Add a manual smoke test path after the Telegram channel exists:

```bash
uv run python -m app.jobs.telegram_smoke --dry-run
uv run python -m app.jobs.telegram_smoke --send
```

`--dry-run` renders a fixture message without sending it. `--send` loads
environment variables, sends one Telegram test message, and records the attempt
only when a database path is explicitly provided.
