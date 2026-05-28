# Notifications Documentation

Notification documentation is organized by feature version so completed behavior
stays separate from later iteration plans.

## Versions

- `mvp/`: implemented Telegram notification baseline for the MVP release.
- `v2/`: adds Feishu Bot webhook channel and multi-recipient list dispatch.

## Current Baseline

The MVP notification baseline covers Telegram message rendering, sending,
environment-based secrets, sanitized failure recording, and notification status
tracking.

## v2 Scope

v2 extends the baseline with:

- **飞书渠道**：via group Webhook Bot, text message format, mirroring the MVP Telegram pattern.
- **多收件人 List**：recipients defined in `config/recipients.yml`; one signal dispatches to all configured channel instances across all recipients.
- **幂等重试**：job layer skips `(signal_id, channel, target)` triples already recorded as `sent`; failed attempts are retried on fallback runs.

