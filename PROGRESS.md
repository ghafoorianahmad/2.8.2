# PROGRESS — Asre Ertebatat 2 store system

Phases are defined in `REQUIREMENTS.md` §14. One phase per session.

## Phase 2 — Bale bot (2026-10-11) — DONE

Rollback point: commit `428016f` (Phase 1). Phase 2 is committed on top of it.

### Done
**A. Verification (§3)**
- Bot: registration is **contact-only**. `/start` asks for Bale's share-contact button. A typed number is refused, as is a contact whose `user_id` ≠ `from.id` (or has no `user_id`), and a non-Iranian number. The name comes from the contact, then the Bale profile; there is no name step any more. Conversations left in the old `await_name`/`await_phone` states continue as contact-only.
- shopapi `POST /users/register`: needs a real mobile (422 otherwise; stored as `09…`). R4 then gives exactly one person not linked to another customer → **approved at once** (`customer_auto_approved` event, no staff alert). Otherwise the customer is pending (`customer_registered` → Bale alert to the owner as before). Accounting down = pending, never an error. A pending customer who shares again is re-matched (covers in-store customers entered later).
- `POST /admin/users/{id}/approve`: `person_code` is optional. Without it, `create_person` (§5.1) runs with `first_name`/`last_name` from the request. If the mobile already exists, the customer is linked to that person; a mobile shared by 2+ persons → 409. **Dry-run → 409 "Accounting writes are disabled; the person was not created"** (nothing is faked).
- ShopAdmin approve dialog: "link to existing person" (with the mobile suggestion) / "**create new person**". The name fields are pre-filled from the Bale name with emoji/symbols stripped and are editable; letters/space/ZWNJ/hyphen only, ≤ 50 chars, last name required. Create mode is chosen automatically when nobody matches.
- Pending customers may order within `PENDING_MAX_ORDER_TOTAL` (default 50,000,000, accounting price unit) and `PENDING_MAX_ORDER_ITEMS` (default 3). Both count their other open orders; 0 items = may not order. Approve-payment of a pending customer's order → 409 until the customer is approved. Rejected customers cannot order. The statement needs an approved, linked customer.

**B. Catalog / deep link**
- Price level 3 (`gey3`) for the bot: config default was already 3. Now also in `shopsystem/.env.example` and the launcher's first-run defaults (they said 1). `shopapi/.env.example` stays 1 for the dev copy (only level 1 has a catalogue there).
- `GET /products/{code}` (also out of stock; 404 if price ≤ 0). Bot: `/start kala_289` opens the product. An unregistered user gets it right after registering. Fallbacks: sending `kala_289` or a bare code (Persian digits OK).

**C. Receipts**
- Photo **or** image document (JPEG/PNG by MIME or file name), ≤ `RECEIPT_MAX_BYTES` (5 MB). The size is checked from the message, then from `getFile`, then while streaming, so an oversized file is never held in memory. The bytes must start with a JPEG/PNG signature, checked in both the bot and shopapi.
- The bot uploads the image base64 in `POST /orders/{id}/receipt` (`data_b64`). shopapi stores it as `receipts/order<id>_<time>_<rand>.<ext>` next to the SQLite file (`RECEIPTS_DIR`); there are no customer data in file names. The `receipts/` folder is git-ignored.
- `GET /admin/orders/{id}/receipt` (view permission; path-traversal safe). ShopAdmin order dialog: "نمایش تصویر رسید".
- Per-customer receipt limit: `RECEIPT_RATE_COUNT=5` per `RECEIPT_RATE_WINDOW=600` s (on top of the general message limiter).

**D. Tracking**
- New `orders` columns (added by an `ALTER TABLE` migration at startup): `invoice_state` (partial/full), `invoiced_qty`, `invoiced_at`, `shipped_at`. `payments` gets `file_name`, `content_type`, `created_at`.
- `tracking.sync_invoices`: R5 over written orders → `order_partially_invoiced` / `order_invoiced` events (once each). It runs in the API lifespan every `INVOICE_SYNC_SECONDS` (300; 0 = off) and on demand via `POST /admin/orders/sync-invoices`. An order deleted in accounting is skipped (not yet shown anywhere).
- `POST /admin/orders/{id}/ship` (new permission `orders.ship`: operator/admin/super) → `order_shipped`. ShopAdmin: "ثبت ارسال" button + "پیگیری" row.
- The bot tells the customer once per event: payment approved/rejected → invoiced (partial/full) → shipped. If the bot has no record of the chat, it is found via the new `GET /admin/users/{id}` and `user_id` in `OrderOut`. "My orders" shows the furthest step.

**E. Statement**
- `GET /users/{platform}/{chat_id}/statement?page=&page_size=`: bot/service key only (site key → 403); approved and linked customers only. KOL rows use the same filter as the verified balance formula, newest first, with a running balance (debtor/creditor/settled). At most `STATEMENT_MAX_ROWS` (2000) rows are read; older rows are carried as the opening balance. `Va='f'` → "فاکتور فروش", other codes → "سند". The description is cut to 60 chars.
- Bot: "📒 گردش حساب" in the menu (approved customers only), paginated (`STATEMENT_PAGE_SIZE=8`).
- Grant: `KOL (…, Num_kol, Date1, N_sanad, Sharh)` added to `sql/create_api_user.sql`; 2 probes added to `verify_permissions.sql`. KOL column names come from the reference/snapshot tool; **not checked live** (see Pending).

**F. Closed mode**
- `shop_state` table; `GET /shop/state` (any channel key), `GET/PUT /admin/shop/state` (new permission `shop.state`: admin/super) + audit + `shop_closed`/`shop_opened` events.
- Bot (state cached 60 s): orders are still accepted; the checkout message adds "🔒 … reviewed when the shop reopens". ShopAdmin dashboard: "وضعیت فروشگاه" panel with an open/close button (with confirmation).

**G. Texts / settings**
- New Persian texts in `messages.fa.json`; the layout is kept. Removed: `ASK_NAME`, `ASK_PHONE*`, `PHONE_INVALID`, `NAME_INVALID`. Operator copies in `%ProgramData%` fall back to the new defaults automatically.
- Remote-editable settings (+ ShopAdmin labels): `PENDING_MAX_ORDER_TOTAL`, `PENDING_MAX_ORDER_ITEMS`, `INVOICE_SYNC_SECONDS`.
- Small fix: the bot's admin `/order <id>` command used the bot key without an owner, so it always got 404. It now uses the service key.

**H. Tests** (fake DB / Bot API, no network)
- shopapi **173 passed** (was 145): `tests/test_phase2.py` (28).
- shopbots **101 passed** (was 80): contact-only flow rewritten in `test_customer_flow.py`, plus `test_phase2.py` (12) and core tests.
- shopadmin **377 passed** (was 364): `tests/test_phase2.py` (13).
- Run with `--basetemp .pytest_tmp` (git-ignored) in this sandbox.

### Bale start parameter — NOT tested live
No Bale **test** token is configured: no `shopbots/.env`, no `BALE_TEST_TOKEN`. The only token is in the running ShopServer's `%ProgramData%` config. It is not a designated test bot, and a second poller would steal its updates, so it was not used. Ready to run: `shopbots/scripts/check_start_param.py`. Set `BALE_TEST_TOKEN` for a separate test bot; the script prints `https://ble.ir/<bot>?start=kala_289` and reports what `/start` text arrives (the token is never printed). The link format itself is part of what it checks. Until then, the typed-code fallback covers a lost parameter.

### Decisions
- Name from the contact (no name step). Pending customers may order within limits (user-approved defaults).
- Orders of pending customers wait in our SQLite; they are written to accounting only after customer approval + payment approval (unchanged write moment: approve-payment).
- "Registered" = the checkout confirmation. Tracking statuses live in extra columns, not in the `orders.status` CHECK (SQLite cannot alter it).
- Receipt image travels as base64 JSON (`python-multipart` is not installed; 5 MB → ~6.7 MB request, local only).

### Pending / for the user
- **Live checks on `hesab5 t` were not possible:** SQL Server refused the connection from this session (`.\SQLEXPRESS` "instance not found"; shared memory "access denied"). Still to do: KOL column names/types (`Date1`, `N_sanad`, `Sharh`, `Num_kol`) and a real statement, R5 invoice progress, and `create_person` dry-run.
- Bale: start-parameter test (above); whether Bale's contact includes `user_id` (**required**: without it every contact is refused as "not own"); `getFile` `file_size`; document MIME types.
- Confirm the price unit of `PENDING_MAX_ORDER_TOTAL` (Rial vs Toman in `Kala.gey3`).
- Orders deleted in accounting (cancelled there) are not surfaced yet.
- Installers/ShopSystem were not rebuilt; `E:\Outputs` unchanged.

### Next step
Phase 3 — Telegram worker: Telethon login, MTProto proxy pool (§6), distributor PDF parser + mapping UI + phone pricing (§4–5).

## Phase 1 — bug fixes, Telegram removal, shared core (2026-10-11) — DONE

Rollback point: commit `6f7eca5` ("Checkpoint before Phase 1"). Phase 1 was committed as `428016f`.

### Done
**A. Bug fixes (REQUIREMENTS §11, reference §9/§11) — shopapi**
- Mobile lookup → recipe R4: `DetailTBL` types 1 and 3, last 10 ASCII digits (`text.mobile_key`; accepts 09…, +98…, 0098…, Persian digits). `name_mo.mobile` is no longer read. Returns the code only (`masked_name` is now always `null`: the least-privilege user cannot read names). A number shared by 2+ persons = no match → manual approval.
- `ACCOUNTING_STATUS_CODE` default `6808` → `0` (`config.py`, `shopapi/.env.example`, `shopsystem/.env.example`, launcher first-run defaults).
- Writer: `UPDLOCK,HOLDLOCK` → `sp_getapplock 'shop:KalaOrder'` (transaction owner, 15s). It is taken before the idempotency check. A lock failure raises `AccountingLockTimeout` and rolls back. Header columns now follow §5.2 (`Taf2` no longer written, `keraye=0` added). `Mablp` = Σ(qty×price), not rounded.
- **New `AccountingWriter.create_person`** (§5.1, dry-run by default, not called by any endpoint yet). Under `sp_getapplock 'shop:name_mo'` it first runs R4 inside the same transaction. If the mobile already exists, it **links to that person instead of creating a duplicate** (`existing=True`, `ambiguous` if shared). The accounting UI forbids duplicate phones, but the DB has no unique constraint.
- Reservation → recipe R2: only `va=0` orders, invoices matched per line (`ordercode`+`orderdetailcode`+`Codekala`), clamped per line. Groups: `Code > 0`.
- `sql/create_api_user.sql` replaced with the least-privilege script (from `research_tools/recipes/grant_shopbot_2008r2.sql`), plus column SELECT on `KOL(Noa,Codkol,Bed,Bes,Va,Cod_n)` and DENY on KOL writes. `sql/verify_permissions.sql` now lists all column grants plus 14 `HAS_PERMS_BY_NAME` probes. **Not run on any DB.**

**B. Old Telegram Bot-API code removed (REQUIREMENTS §2)**
- shopbots: `platforms/telegram.py`, `TELEGRAM_TOKEN/TELEGRAM_API_BASE/TELEGRAM_PROXY/PROXY_URL`, `describe_proxy`/`proxy_for`, `socksio`. `ADMIN_CHAT_IDS` accepts `bale:<id>` or a bare id; leftover `telegram:` entries are ignored.
- shopapi `control.EDITABLE`: Telegram token/proxy keys removed (now refused as unknown). Chat-id validator is Bale-only.
- shopsystem launcher (status, setup fields, logs), `build_exe.bat` (`socksio`, script copies), README/NOTES.
- shopadmin: server-settings labels, setup-wizard Telegram token and proxy fields.
- Root `scripts/set_telegram_token.ps1` and `scripts/test_telegram_proxy.ps1` deleted.

**C. Shared core — `shopbots/app/core/`**
- `catalog.py` (groups, product pages, search normalization ی/ي ک/ك + digits), `cart.py` (limits, totals, order payload), `orders.py` (checkout, receipt outcomes, order list), `customers.py` (status, name/phone validation, registration).
- `engine.py` now only routes, holds conversation state and renders texts and keyboards. Adding a channel = one adapter in `app/platforms/`. No behaviour change.

**D. Tests** (unit tests, fake DB/Bot API; no real SQL or network)
- shopapi **145 passed** (was 120): new `tests/test_person_and_reservation.py`, applock/person tests in `test_writer.py`.
- shopbots **80 passed**: `test_telegram_shop.py` → `test_shop_features.py` (Bale; the proxy tests were dropped), new `test_core.py`.
- shopadmin **364 passed** (offscreen).
- Run note: in this sandbox, shopbots/shopadmin need `--basetemp <writable dir>` (the default pytest temp folder is not writable here).

### Decisions
- `'telegram'` stays a valid platform value in shopapi (SQLite CHECK + schema) and in the shopadmin labels: old rows keep displaying, and phase 7 reuses it. No migration.
- `create_person` is built and tested now, but is wired to an endpoint only in Phase 2 (§3 pending-approval flow).
- KOL grant covers only the balance formula's columns. Phase 2 must add the date/description columns for the paginated statement once they are confirmed on the test DB.

### Pending / for the user
- **Local `.env` files are not touched by design.** `shopapi/.env` sets `ACCOUNTING_STATUS_CODE` explicitly: change it to `0`. Old `TELEGRAM_*`/`PROXY_URL` lines in any `.env` (including `%ProgramData%\ShopServer\.env`) are now ignored and can be deleted.
- Live check on `hesab5 t` (read-only R4 lookup, dry-run order with applock), then the scripts in `shopapi/sql/` with a DBA.
- `installer`/ShopSystem were not rebuilt, so `E:\Outputs` was not updated.
- Still open from §13/backlog: GUI tests G1–G4 (real `Status`), Bale verification with a real test bot.

### Next step
Phase 2 — Bale bot: contact-only verification (§3, R4 + `create_person` on approval), catalog/search/deep link, price level 3, cart/order, receipts, tracking (R5/R6), statement (KOL), closed mode.
