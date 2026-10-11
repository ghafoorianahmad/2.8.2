# NOTES.md — shopbots build log

> **2026-10-11 (Phase 1):** Bale is the only channel. The Telegram Bot-API adapter,
> `TELEGRAM_TOKEN`/`TELEGRAM_PROXY`/`PROXY_URL` and `socksio` were removed; the
> shop logic moved to `app/core/` so a future channel is a thin adapter.
> Telegram mentions below are history.

## Work order and status

| Step | Status |
| --- | --- |
| 1. Skeleton, venv, `requirements.txt`, `.env.example` | done |
| 2. `config.py`, `texts.py`, `utils.py` | done |
| 3. `store.py` (SQLite bot state) | done |
| 4. `platforms/` (adapter interface + Bale; Telegram removed 2026-10-11) | done |
| 5. `shopapi.py` client | done |
| 6. `engine.py` (customer + admin flows) + `ratelimit.py` | done |
| 7. `polling.py` + `main.py` (two tasks, backoff, admin sweep) | done |
| 8. tests (fake Bot API + fake shopapi via `httpx.MockTransport`) | done |
| 9. README + NOTES + acceptance checks | done |

`pytest -q` → **48 passed** (no network access). `python -m app.main --dry-run`
starts both adapters with fake tokens and exits 0.

## Design decisions

- **One HTTP implementation.** Bale and Telegram share method names and JSON
  shapes, so `platforms/base.py` holds the whole Bot API implementation and
  `BaleAdapter`/`TelegramAdapter` only set `platform`, the base URL and the
  feature flags (`supports_inline_keyboard`, `supports_reply_keyboard`,
  `supports_contact_button`).
- **Feature fallback.** `engine._markup()` uses an inline keyboard when the
  platform supports it, otherwise a reply keyboard, otherwise plain text with the
  options listed as bullets. Every keyboard is also recorded as
  `label -> callback_data` in the conversation, so a **typed** label triggers the
  same action on text-only platforms.
- **Idempotency.** `platform_state.last_update_id` is updated for every update
  (handled or not, including failures), so an update is never processed twice.
- **Isolation.** `poll_platform()` runs one task per platform; a failure only
  backs that platform off (1s → 2s → … → 60s). An immediate empty `getUpdates`
  answer triggers a small idle sleep so the loop can never spin and starve the
  other task.
- **Send failures never break the flow.** `send_text`/`edit_text`/`answer_callback`
  swallow `BotApiError` and log only the platform and method name.
- **Admin notices** are remembered in `admin_notices(kind, ref_id, platform,
  chat_id)`; `GET /admin/users?status=pending` and
  `GET /admin/orders?status=receipt_uploaded` are polled every
  `ADMIN_SWEEP_SECONDS` (default 30) and each item is announced once. The row also
  records the customer's chat so the customer can be notified after a decision —
  only the chat identity is stored, never the name or phone.
- **Receipt photo.** The file reference received from the customer is stored in
  `receipts(order_id, platform, chat_id, file_ref)` so the admin notice can send
  the photo, and so it can be re-sent as the `receipt_ref` to shopapi. A file id
  is only sent to admins on the **same** platform (a Telegram file id is useless
  to Bale).
- **Admin identity.** `ADMIN_CHAT_IDS` accepts `bale:456` and a bare `123`
  (entries for other platforms are ignored). The chat id is re-checked on **every** admin action, including
  callbacks; buttons alone are never trusted.
- **shopapi contract.** `POST /orders/{id}/receipt` is called with
  `?platform=&chat_id=` because shopapi requires ownership proof for non-admin
  callers.
- **Privacy.** `utils.log_event` is the only log shape (`platform`, `update id`,
  `event type`). `app/logging_setup.py` caps `httpx`/`httpcore` at WARNING because
  httpx logs request URLs at INFO and those URLs contain the bot token — without
  this the token lands in every log sink (the test suite caught exactly this).
- **Numbers.** Prices/quantities are displayed with thousands separators and
  ASCII digits. Persian/Arabic digits in user input are normalized
  (`utils.normalize_digits`), so `۰۹۱۲...` and `0912...` both work.

## Open questions — Bale differences to verify with a real test bot

1. **Base URL.** `BALE_API_BASE=https://tapi.bale.ai` and the
   `bot<token>/<method>` path are assumed identical to Telegram. Verify against
   Bale's official docs.
2. **`getUpdates` long polling.** Does Bale support the `timeout` parameter (and
   an `offset` based on `update_id`)? If not, `POLL_TIMEOUT` must be lowered and
   an explicit idle sleep used (already in place for an immediate empty answer).
3. **`allowed_updates`.** Telegram accepts `["message","callback_query"]`; Bale
   may ignore or reject it.
4. **Inline keyboards** (`reply_markup.inline_keyboard` + `callback_data`) and
   **`answerCallbackQuery`** — supported? The fallback path (reply keyboard, then
   plain text) covers a missing feature.
5. **`request_contact` keyboard button** — supported? Validating a typed number
   is the fallback.
6. **`editMessageText`** on a callback message — if unsupported, the code already
   falls back to sending a new message.
7. **`getFile` / file download.** `download_file_ref()` assumes Telegram's
   `result.file_path` and `GET /file/bot<token>/<file_path>`. The main flow only
   stores and re-sends the file reference, so downloading is not on the critical
   path.
8. **Message length** and the photo `file_id` re-use across chats.
9. **Rate limits / API errors** returned by Bale (`ok:false` descriptions).
10. **No proxy.** Bale must work without any proxy — confirm on the real network.

## Known limitations

- The bot can only notify the customer about an order decision if its own state
  database still knows that order's chat (`receipts` / `admin_notices`). If the
  database is deleted while shopapi still has `receipt_uploaded` orders, the admin
  still gets the notice but no customer notification (shopapi does not expose the
  order's chat to admins).
- Rate limiting is in-process and resets on restart.
- `POST /orders` has no idempotency key, so a retried checkout can create two
  orders (shopapi releases the reservation at expiry).
- The conversation engine is deliberately linear; no multi-cart or saved-address
  features.
- Only private chats are handled; group/channel updates are ignored.

## Bale-unverified risk

Everything Bale-specific is isolated in `app/platforms/bale.py` (base URL plus
feature flags) and in `Settings.bale_api_base`, so a wrong assumption is a
one-file change once the real behaviour is confirmed.
