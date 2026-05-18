# Notifications TODO

- [x] Add `python-dotenv` for local `.env` loading.
- [x] Define notification context, message, channel, result, and dispatcher
  interfaces.
- [x] Implement Telegram renderer using `templates/telegram_signal.md`.
- [x] Render missing optional fields as `暂无`.
- [x] Keep Telegram messages as MVP plain text without `parse_mode`.
- [x] Implement Telegram sender.
- [x] Support injectable HTTP client/session for Telegram tests.
- [x] Set an explicit Telegram request timeout.
- [x] Read `TG_BOT_TOKEN` and `TG_CHAT_ID` from environment variables and local
  `.env`.
- [x] Sanitize Telegram errors so tokens and full API URLs are never persisted.
- [x] Record `sent` and `failed` notification states.
- [x] Record failures as `notifications.status = failed` and
  `notifications.error_message = sanitized_error`.
- [x] Support composing one or more notification channels.
- [x] Keep signal calculation, provider fetching, market-window checks, and
  send de-duplication outside notification code.
- [x] Add a manual Telegram smoke test path.
