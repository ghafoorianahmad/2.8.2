# PROGRESS — Asre Ertebatat 2 store system

Phases are defined in `REQUIREMENTS.md` §14. One phase per session.

## Phase 3 (part 1, no Telegram login) — 2026-10-12 — IN PROGRESS (stopped at the usage limit)

### Done
- **shopapi** (218 tests ✓): PDF parser `app/pricelist/parser.py` (sample: 195 rows, 15 sections, date 1405/07/19; scrambled Persian matched by letter multiset); pricing `pricing.py` (روال×10,000; else نقد×10,000+5,000,000 Rial; none = inquiry); import with safety `importer.py` (duplicate / older / failed / held on >15% mapped change or most mapped rows missing; PDF copy in `pricelists/`); tables price_lists, price_list_rows, price_mappings (map|ignore by row key), inquiries, proxies, proxy_days; `routers/pricelist.py` (`/admin/pricelists*`, `/admin/price-mappings*`, `/admin/inquiries*`, `/admin/proxies*`, `/worker/*`); `WORKER_API_KEY` (loopback, /worker only); permissions `pricelist.manage` (admin, super) and `proxies.manage` (super); products/orders with per-color variants (mapped rows only; phones sold on list availability; stale list > `PRICELIST_MAX_AGE_HOURS` = inquiry only); proxy pool `app/proxypool.py` (stability ranking, probation→main, retire after N bad days, never below 3, outage days ignored, all-dead alert).
- **shopbots** (114 tests ✓): color picker (price only after a color is picked; changing color announces the new price; the price is re-read from shopapi on each pick), cart lines per color (cart table migrated), inquiry button, owner alerts for pricelist_held/failed, proxies_all_dead, telegram_login_required/unreachable, price_inquiry.
- **shopadmin**: API client methods, permissions, new page `ui/pages/pricelist.py` (rows + mapping dialog + ignore + section/brand filter + search; lists + PDF upload + approve/reject held; proxies), registered in the sidebar.

### Not done / next session
- shopadmin: `tests/test_ui.py::test_sidebar_shows_users_for_the_super_admin` fails after adding the sidebar entry (probably an exact nav list). The full shopadmin suite was not completed; no tests for the new page yet.
- **shoptg worker not started**: Telethon login script (DPAPI-encrypted session + NTFS ACL), worker loop (channel every 30 min, PDFs → `/worker/pricelists`, weekly proxy collection, health checks/failover), tests with a fake gateway, its own venv.
- pdfplumber was installed into `shopapi\.venv` with the regular Python 3.12 (`pip --target`). The Store-Python venvs cannot write files from the Claude app, and pip needs `--use-deprecated=legacy-certs`. Add pdfplumber to the ShopSystem PyInstaller build (Phase 4). The launcher's `--init-config` must generate `WORKER_API_KEY`.

### For the live Telegram day (do not paste secrets in chat)
1. From my.telegram.org (logged in as the shop account): `api_id`, `api_hash` → type them yourself into `%ProgramData%\ShopServer\.env` (`TG_API_ID=`, `TG_API_HASH=`), or into `shoptg\.env` for the dev test.
2. The shop phone, to receive the login code. Have the 2FA password ready if set. Both are typed only into the login script's hidden prompt in your own PowerShell.
3. At least one working MTProto proxy link (enter it in ShopAdmin › لیست قیمت › پراکسی‌ها, "مستقیم در فهرست اصلی"), plus the usernames of the proxy channels the account follows.

## Live test session after Phase 2 (2026-10-11) — DONE

No new features, except the deep-link fallback the user approved after the start parameter proved unreliable.

### Live results
**Bale** (`@asr_test_bot`, `shopbots/scripts/check_start_param.py [--formats]`; the token is read from `shopbots/.env`, with `BALE_TOKEN` as a fallback for `BALE_TEST_TOKEN`)
- ✅ A shared contact carries `contact.user_id` (int) and it **equals `from.id`**. The fields are `first_name`, `phone_number`, `user_id`. Contact-only registration works as built.
- ⚠ **The `/start` parameter is unreliable.** First run: a bare `/start`. Then, with the chat deleted and 5 variants opened (`kala_289`, `kala289`, `KALA289`, `289`, `kala%5F289`), 8 `/start` messages arrived. Only 2 carried a parameter: `/start 289` and `/start kala_289`; the other 6 were bare. So Bale *can* pass it, but often doesn't. It is unclear when (first open vs. reopen, app vs. web). Both forms that did arrive are handled.
- → **Fallback (approved), now the main path:** the site shows the product code; the customer sends it to the bot.
  - Accepted forms: `289`, `kala_289`, `kala289`, `kala-289`, `کد 289`, `کد کالا: ۲۸۹`, `#289`. Persian digits work.
  - A code sent before registering is kept and the product is shown right after the contact is shared (`PRODUCT_AFTER_CONTACT`).
  - The welcome and help texts tell customers to send the code.
  - `/start <code>` still works, in case Bale ever passes the parameter.
  - Phone-length numbers are never taken as codes.
  - The site (Phase 6) must print the code next to the "order in Bale" button.

**SQL on `.\SQLEXPRESS` / `hesab5 t`** (`shopapi/scripts/live_db_check_all.ps1` → `live_db_check.py kol|r5|person`)
- Must be run from a normal PowerShell window. Processes started by the Claude app are refused by SQL shared memory ("access denied", error 5). Only shared memory is enabled on the instance; TCP, named pipes and SQL Browser are off.
- **KOL statement ✅**
  - Columns: `Num_kol int`, `Date1 varchar(10)` (`1405/07/19` format), `Va char(1)`, `N_sanad int`, `Bed/Bes money`, `Sharh nvarchar(500)`, `Noa char(1)`, `Codkol int`, `Cod_n int`.
  - Checked on the 3 persons with the most rows (2139/540/366 rows):
    - totals = the reference §3 formula;
    - rows come out oldest first;
    - the newest running balance = the balance, including when truncated to `STATEMENT_MAX_ROWS` (the carried-over opening balance works);
    - no fractional amounts.
  - `Va` codes seen: `8 Z f n t w ^ a r` and a Persian letter. Only `f` has a label; the rest show as «سند».
- **R5 tracking ⚠ partly verified.** The query runs. Ordered quantities are correct and a missing `Codlp` → `None`. But the test DB has only 3 orders and **no invoice with `ordercode`**, so the partial/full invoiced path still needs GUI test G3.
- **create_person ✅**
  - Duplicate check: an existing mobile (also given as `+98…` or with Persian digits) returns `existing=True` with the same code and writes nothing, even with `dry_run=False`.
  - Dry-run leaves no rows.
  - Real create: `Code = MAX+1`, `Gcod=4`, `l_gey=1`, `taf(como=13, codgtaf=59, va=1, Cota=Code)` linked through `codetaf`, `DetailTBL(type 3, Va 0, darfn 1)`. R4 then finds it.
  - No triggers on `name_mo/taf/DetailTBL`.
  - The test person (09990007731) was deleted afterwards and the row counts were restored. Only the IDENTITY counters of `taf`/`DetailTBL` moved on.

### Decisions applied (REQUIREMENTS §3/§4 updated)
- **All money is in Rial**, the same unit as the accounting software. The bot's `currency` is now «ریال», as are ShopAdmin `format_money`, the report column and the filter hint. The editable copy `%ProgramData%\ShopServer\messages.fa.json` must be changed by hand if it still says «تومان».
- **No amount cap for pending customers.** `PENDING_MAX_ORDER_TOTAL` was removed from the API check, config, the remote-editable settings, launcher defaults, ShopAdmin labels and both `.env.example`; old lines in a `.env` are ignored. Only `PENDING_MAX_ORDER_ITEMS` remains.
- Phase 3: distributor PDF price (thousand Toman) ×10,000 = Rial; "نقد + 500,000 Toman" = +5,000,000 Rial.

### Other
- `shopbots/.env.example` was restored (it was deleted in the working tree).
- Tests: shopapi **173** ✓, shopbots **104** ✓ (+3 fallback), shopadmin **377** ✓.

### Pending
- GUI tests G1–G4, especially G3 (invoice an order) to verify R5 end to end.
- Installers were not rebuilt; `E:\Outputs` is unchanged.

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
- ~~Live checks on `hesab5 t`~~ → done in the live test session above.
- ~~Bale start-parameter / contact `user_id`~~ → see the live test session above. Still open: `getFile` `file_size`; document MIME types.
- ~~Price unit of `PENDING_MAX_ORDER_TOTAL`~~ → the setting was removed; all money is in Rial.
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
