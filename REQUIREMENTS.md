# REQUIREMENTS — Asre Ertebatat 2 store system (bot + site + bridge)

Source of truth for all decisions. Read together with `SAZEH_DB_REFERENCE.md` (verified DB reference) and `CLAUDE.md`.
Work on the TEST DB (`.\SQLEXPRESS`, `hesab5`) and a separate Bale TEST bot token only. Production = config change only.

## 0. Working rules (context budget)
- Work ONE phase per session. At the end of each phase: run tests, update `PROGRESS.md` (done / pending / decisions / next step), then stop.
- Never load large files fully; read only the needed sections (grep/offset). Do not paste big outputs into the conversation; write them to files.
- Use subagents for broad searches. Keep summaries short.
- Before each phase, show a short plan and wait for approval.

## 1. Architecture
- Shop server (Windows 10, always on, SQL Server 2008 R2 instance `SAZEHHESAB`) runs everything as Windows services:
  `shopapi` (127.0.0.1 only) + Bale bot + Telegram price/proxy worker + (optional, later) Telegram bot.
- Services: NSSM (or equivalent), auto-start at boot without login, auto-restart on crash, dedicated limited Windows account (not admin). Independent of our desktop app and of the accounting software.
- Install / uninstall / update scripts; update script backs up current version and rolls back automatically on failure.
- README: BIOS "Restore on AC power loss" + UPS.
- Shared core logic (catalog, pricing, orders, customers) used by every bot channel, so adding a channel = thin adapter.

## 2. Channels
- **Bale bot = primary and only required channel** (`https://tapi.bale.ai/`, long polling, no webhook).
- **Telegram bot = optional later phase**, built on the same core, connected through the MTProto proxy pool (§6). Do NOT build in early phases. Remove any old Telegram Bot-API code that is not part of this design.
- Accounting software's own bot and `Telegram_*` tables are NOT used.

## 3. Customer verification
- Registration ONLY via Bale "share contact" button (request_contact). Never accept typed numbers. Reject if `contact.user_id != from.id`.
- Normalize number → match `DetailTBL` (recipe R4, types 1 and 3).
  - Match → auto-approved, linked to `name_mo.Code` (covers ~10,000 existing customers and new in-store customers once entered in the accounting software).
  - No match → "pending approval" queue in shopadmin; on approval create person per recipe §5.1.
- A customer's data (orders, statement) is reachable ONLY from the Bale account whose verified contact matched. ChatId↔Code stored in our SQLite.
- Unapproved customers: configurable cap on **item count only** (`PENDING_MAX_ORDER_ITEMS`, counted over their open orders). **No order-amount cap** — prices fluctuate (decision 2026-10-11).

## 4. Pricing
- **Unit: all money is in RIAL** everywhere (DB, API, bot texts, shopadmin, reports) — the same unit as the accounting software (`Kala.Gey*`, `KOL`, `KalaOrder*`). No Toman conversion at display time (decision 2026-10-11).
- **Accessories:** price level 3 (`gey3`) from the accounting DB; only items with stock > 0 are offered.
- **Phones (and AirPods / Apple Watch in the list):** from the distributor's Telegram channel PDF (§5).
  - Customer price = **"روال"** price unchanged. If روال is empty → **"نقد" + 500,000 Toman**. If both are `...` → unavailable (still allow "order/inquiry for unavailable item").
  - Price is per color: the bot shows the price AFTER the customer picks a color; if the customer changes color, announce the new price.
  - **PDF price unit = thousand Toman → Rial ×10,000** (confirmed 2026-10-11). E.g. `52,500` in the PDF = 525,000,000 Rial.
  - "نقد + 500,000 Toman" = نقد (converted) **+ 5,000,000 Rial**.
- Never cache accounting prices long-term (the software can rewrite `Kala.Gey`); read at order time and store the unit price in `KalaOrderDetail.Gey`.

## 5. Distributor price list (Telegram channel)
- Channel: `https://t.me/AbrishamiiPhoneMashhad` (public). Posts 1–3 PDFs per day (Excel-generated, text-based, 1 page, A4).
- PDF layout: 3 blocks iPhone / Xiaomi / Samsung; each row = model | storage/RAM | type (شرکتی/ویتنام/ZAA/CHA) | color | نقد | روال. Date at top (e.g. `1405/07/19`). `...` = unavailable. Persian text extracts garbled (RTL) — rely on column x-positions and Latin fields; use pdfplumber.
- Telethon client logged in with the shop's Telegram account (one-time login code; `api_id/api_hash` from my.telegram.org). Session file = full account access → encrypt / NTFS ACL to service account only; never log.
- Check the channel ~every 30 min; process only PDFs newer than the last processed date; ignore images.
- Mapping table (shopadmin UI): PDF row (model+storage+type+color) ↔ our product/variant. Unmapped rows → listed for me to map.
- Safety: if a price changes > 15% vs previous, or parsing fails, or the layout changes → hold (keep last good prices) and alert me on Bale.
- Polite usage: read-only, minimal requests; never join/spam.

## 6. MTProto proxy pool (the app acts as a Telegram user)
- Collect `tg://proxy` / `t.me/proxy` links from the proxy channels the shop account follows (configurable list) + manual entry in shopadmin.
- Ranking by **historical stability**, not freshness. Proven old proxies are never dropped while working.
- New proxies = probation: tested over several days before entering the main list.
- Fetch new links **weekly**. Health-check the current proxy every few minutes; on failure switch within seconds to the next best.
- Remove a proxy only after several consecutive days of failure.
- Keep several known-good proxies stored (chicken-and-egg). If all fail → Bale alert to me + manual proxy entry in shopadmin.

## 7. Bot features (Bale)
- Browse by group + text search (normalize ی/ي, ک/ك).
- Deep link from site: open the bot directly on a product (`start` parameter; from Phase 6 the site sends `m_<slug>`, see §9/§9a — `kala_<code>` stays supported for old links). **Live test 2026-10-11: Bale passes the start parameter unreliably** (2 of 8 opens; `kala_289` and `289` both arrived once) → keep the deep link, but the fallback is the dependable path: the customer sends the model slug shown on the site (§9a).
- Cart → order per recipe §5.2 (`sp_getapplock`, transaction, `Codf=-100`, `va=0`, `takhfif/avarez=0`, `Status=0` until GUI test G2, `Sharhlp='API-<id>'`, `tavasot=''`, Shamsi date via `dbo.MiladiToShamsi`).
- Payment: show bank account; customer uploads receipt photo → attached to the order in shopadmin for manual review.
- Order tracking messages: registered → payment confirmed → invoiced (detected via `Facto.ordercode`, R5/R6) → shipped (set in shopadmin).
- Account statement (گردش حساب) for verified customers from `KOL` (formula in reference §3); add column-level SELECT on KOL to the low-privilege user; paginated.
- Shop-closed mode toggle in shopadmin: bot says orders will be reviewed when the shop reopens, still accepts orders.
- Per-user rate limiting; input validation; receipt size/type limits.

## 7a. Order flow v2.5.0 (decision 2026-10-14; supersedes the 12-hour reservation and the "closed mode still accepts orders" rule above)
- No 12-hour reservation, no payment gateway. The customer uploads the receipt right after ordering; deadline `RECEIPT_DEADLINE_MINUTES` = 30. Then the order is cancelled **locally** (our SQLite). Nothing is ever deleted from the Sazeh DB; an order that already exists there is only reported to the admin.
- Price channel polled every 10 min (`TG_PRICE_INTERVAL_MIN`), new lists auto-imported (the >15% hold stays).
- Sales windows (Asia/Tehran): a list posted before 13:30 opens sales until 13:30; before 20:30 until 20:30; otherwise closed; Fridays closed. While closed the bot shows the last prices + «لیست به‌روز نشده، فروش بسته است» and refuses orders.
- **Scope (user, 2026-10-14): the closed state (windows, Friday, «تعطیلی امروز», «بستن فروش») blocks ONLY phones** (items priced from the Telegram list). Accessories and other accounting-priced items stay orderable at all times; a cart with a phone is refused as a whole until the phone is removed.
- ShopAdmin buttons (stored on the server, audited, one event each): «تعطیلی امروز» (closed until next morning), «بستن فروش» (now, until the next list or «باز کردن»), «باز کردن فروش» (until the next transition: a new list or the next closing time; can be closed any time).
- `KalaOrder.Status` = `ACCOUNTING_STATUS_CODE`, no default (6808 is invalid; value from GUI test G2). Unset = nothing committed. Production writes stay disabled by default.
- Every order stores the accounting DB name; invoices are only looked up in that DB.
- After the insert (in the transaction and again after COMMIT) the Codlp is checked for duplicates; a duplicate alerts the admin (nothing deleted).
- SQL errors (18456, 4060, 53, IM002, …) are explained in Persian (`shopapi/app/sql_errors.py`).
- Least-privilege role `shop_app` (`shopapi/sql/grant_shop_app.sql`, `grant_shop_app.ps1` in the ShopServer installer).
- DB allowlist: real writes only to databases in `ACCOUNTING_ALLOWED_DATABASES` (+ switch + host); test mode only for `ACCOUNTING_TEST_DATABASES`; a dry run never sends an INSERT.

## 7b. v2.6.0 (decision 2026-10-14, after the Windows test on `hesab5 t`; supersedes "phone = mapped in the price list")
- **Product groups** (ShopAdmin «گروه‌های کالا», `shopapi` table `product_groups`): two checkboxes per Sazeh group, «نمایش در ربات» and «گروه گوشی». The bot shows and sells only items of groups shown in the bot; no group chosen = nothing shown (fail closed).
- **A phone = an item of a phone group.** Phones are shown and orderable only while present and available (a price) in the current valid price list; their price comes only from the list; a phone not in the list is hidden and refused (never the accounting price). The sales gate applies to phone-group items, read from the accounting DB at order time (also for stale carts). A price-list mapping on a non-phone group is ignored.
- Lists show only in-stock items (phones: available in the list). An out-of-stock item opened by code offers «درخواست این کالا».
- ~~**Payment card required**~~ (v2.6.0, replaced in v2.8.2): **payment details per order.** No fixed card / Sheba / owner / bank text in the server settings. After checkout the bot says the payment details will follow; staff open the order and fill «ارسال اطلاعات پرداخت» (card number, account number, Sheba, holder, bank, note — empty fields are left out of the message), confirm, and the bot sends it. The receipt deadline starts then; an order without payment details never times out. After «تأیید موجودی» the same form opens at once.
- **«درخواست کالای ناموجود»** (menu button): the customer types an item, picks a match or submits the text. No order, no payment, nothing written to Sazeh. Event `item_request` → ShopAdmin toast + «درخواست کالا» page + admin chats. Max 10 per customer per day.
- **Statement = one A4 PDF** (RTL, Vazirmatn, Jalali dates): header (logo, shop name, customer name + code, date range, print date), table (date, description, debit, credit, running balance + side), totals and final balance in bold. Rendered by the headless Edge/Chromium the cards use; without a browser the paged text statement is the fallback.
- The customer's **Sazeh name** (`name_mo.fname` + `Name`) is read for linked customers only: ShopAdmin order dialog («نام (کد شخص N)») and the customer's own PDF. Needs the column grant in `grant_shop_app.sql`; without it the registration name is shown.
- `ACCOUNTING_STATUS_CODE` is editable from ShopAdmin's server settings (super admin), same rule (required, whole number, not 6808).
- Rate limits: button taps have their own limit (`RATE_LIMIT_CALLBACKS`, 120/min), messages 20/min, one warning per window, `/start` is never limited.

## 7c. v2.9.0 (decision 2026-10-21; supersedes the login script and the weekly proxy collection of §5–6)
- **Telegram reader bundled**: `ShopSystem.exe --tg-worker` (no separate Python install); started by the service when `TG_READER_ENABLED=true`. The old separate install (`SHOPTG_DIR`) still works.
- **Key (temporary, owner's decision)**: the public api_id / api_hash of the official Telegram Desktop app with matching InitConnection parameters (device "Desktop", "Windows 10", app "5.12.3 x64", lang_pack "tdesktop"), **for a separate secondary account only**; editable in «تنظیمات سرور» › تلگرام («کلید خودم» = my.telegram.org, also used by the Telegram bot). Telegram may restrict accounts that use these keys from other software.
- **Login from «تنظیمات سرور»** (server only, administrator): phone → code → 2FA password through `ShopSystem.exe --tg-login` (JSON lines on stdin/stdout; nothing on a command line, nothing stored but the DPAPI LocalMachine session with the SYSTEM / Administrators (+ service read) ACL).
- **Read-only, low rate**: price channel every 10 min, health ping every 3 min, FloodWait pauses everything for the time asked; never joins, posts or marks read.
- **Price lists**: a new PDF of `@AbrishamiiPhoneMashhad` goes through the same import as a manual upload (same morning / afternoon rules); ShopAdmin announces «لیست قیمت تازه»; a PDF that cannot be downloaded (3 tries, too large, not a PDF) → `telegram_pricelist_error` to the owner (ShopAdmin + Bale admin chats). Images are ignored.
- **Proxy pool**: daily (hourly while fewer than `TG_PROXY_POOL_SIZE`=5 work) links of `@ProxyMTProto` (with the account; without login / proxy from the public web preview `t.me/s/…`); links the server never saw are tested with an anonymous client until pool_size + 2 work (≤ 40 tests); working ones join (probation), failed ones are kept as retired (never retested); at most 30 usable proxies. Rotation on failure is immediate; manual proxies (ShopAdmin «سرور فروشگاه» › «افزودن پراکسی دستی», or `TG_PROXY` in «تنظیمات سرور») are tried when the pool is empty (first start). Status (reader, last list, pool counts, last collection) on «سرور فروشگاه».
- **Look**: ShopAdmin palettes اقیانوس / شفق / زمرد × روشن / تیره / مطابق ویندوز × «جلوه‌ها» خودکار / کامل / ساده, per computer, in «اعلان‌ها و ظاهر» for every user; WCAG AA (`contrast_audit.py --all`) and 0 cut texts (`text_fit_audit.py`) in every look.

## 8. Alerts to the owner
- Bale message to the owner's chat (ChatId in .env) on every new order and pending customer.
- Windows tray app: detects when the Sazeh Hesab program starts (process watch) → "X new orders, Y customers awaiting approval" + link to shopadmin.
- Pending counters in shopadmin.
- Health monitoring alerts (Bale + tray): bot down, Bale unreachable, SQL unreachable, price-list hold, all proxies dead.

## 9. Website
- Hosted on **ArvanCloud** (static site on Arvan Object Storage + CDN; DNS to Arvan); published from the owner's GitHub repo.
- **The live site is `E:\DSH-Workspace\projects\asr-ertebatat-2-redesign`** (GitHub `asr-ertebatat-2`, branch `redesign`; verified 2026-10-12 by matching the live files). It is plain HTML/JS with no build step.
- `projects\asr-ertebatat-shop` (GitHub `asr-ertebatat-shop`) is the older design and is not published. It gets the same changes; slugs are identical in both.
- The Next.js prototype `E:\projects\mobile-shop` is not used.
- Showcase only: product presentation and specs. **No prices, no stock, no live connection to the server, no data push, no order submission from the site.**
- **No accounting codes on the site** (decision 2026-10-12): `Kala.Code` can change after stocktaking and Sazeh Hesab names are entered inconsistently. Each site model has a **permanent slug of our own** (e.g. `iphone-17-pro`; a storage-level slug such as `iphone-17-pro-256` may be added later — slugs are never renamed or reused).
- Each model: button «استعلام قیمت و سفارش در بله» → copies the model name + slug to the clipboard and opens the Bale bot with a deep link (`start=m_<slug>`); the slug is printed next to the button as the dependable fallback («کد مدل: iphone-17-pro — این متن را در ربات بفرستید»). Telegram button later (same mechanism). Shop phone number as fallback.

## 9a. Catalog model mapping (shopapi / ShopAdmin / bot — decision 2026-10-12)
- One **catalog model** table in shopapi: slug ↔ accounting product(s) (`Kala`, per storage/color where needed). The distributor price-list rows (§5) map to the same catalog model, so each model is mapped once.
- ShopAdmin suggests matches with fuzzy, normalized name matching (case, partial names, ی/ي, ک/ك, spacing/ZWNJ, Persian/English digits); the owner confirms once.
- **Nightly validation** of every mapping: if the mapped product disappears or its name drifts → re-search by name, propose candidates, **hide that model from customers until the owner confirms**, and alert the owner on Bale. Never show a wrong product.
  - Refinement (user, 2026-10-12): if the `kala_code` still exists and the new name is still a strong fuzzy match to the confirmed name (`MODEL_DRIFT_MIN_SCORE`, default 0.7; e.g. a color or spacing added), the model **stays visible** and the item is only flagged «drifted» in ShopAdmin (no Bale alert). Hide + Bale alert only when the product is missing/inactive or the similarity falls below the threshold. Another storage size, another model (Pro/Max, 17/17e) or an accessory always falls below it.
- The bot resolves what the site sends: deep link `m_<slug>`, a pasted «name + slug» text, a bare slug, or (if the customer edited the text) a fuzzy name match → asks to confirm when ambiguous. Unknown/unmapped/hidden → polite message + shop phone, never a guess.

## 10. Security
- NO inbound ports to the server from the internet. Long polling only; shopapi on 127.0.0.1.
- SQL login = least-privilege user (`research_tools/recipes/grant_shopbot_2008r2.sql`) + KOL read. DENY on `setting`, `Telegram_Setting`, `api_online_setting`, `TabaghehBandi`, UPDATE/DELETE on orders.
- `sa` password cannot be changed (vendor/hardware lock): our code NEVER uses sa or reads `Options.ini`; Windows Firewall limits port 1433 to the server itself and the accounting client PCs; document it.
- Secrets (Bale token, DB password, Telethon session) only in `.env`/protected files with NTFS ACL to the service account; never logged.
- Parameterized queries only. Audit log of writes and admin actions; alert on suspicious activity (repeated failed matches, rate-limit hits).
- Daily backup of SQLite + receipts + config, one copy off the server; documented restore test.
- `SECURITY.md`: threat model — if bot or site is compromised, what can/cannot be reached.
- (Network egress restriction on MikroTik is done separately, not in code.)

## 11. Bugs to fix first (reference §9/§11)
- `find_person_by_mobile` reads empty `name_mo.mobile` → use R4.
- Status `6808` doesn't exist → `0`.
- `UPDLOCK,HOLDLOCK` → `sp_getapplock`.
- `create_api_user.sql` too broad → replace with the least-privilege script.

## 12. Out of scope
Postal tracking codes, back-in-stock notifications, support chat, broadcast messages, daily reports.

## 13. Later (separate tasks — do not start)
- Bot visual style (several sample designs to choose from).
- Read the accounting software's invoice designer templates.
- Colorful branded invoice (image/PDF) sent by the bot: pre-invoice at order + final invoice when invoiced.
- GUI tests G1–G5 (reference §10) to confirm `Status` and order→invoice behavior.

## 14. Phases
1. Bug fixes (§11) + remove obsolete Telegram code + shared core refactor + tests.
2. Bale bot: verification (§3), catalog/search/deep link, accessories pricing, cart/order, receipt upload, tracking, statement, closed mode.
3. Telegram worker: Telethon login, proxy pool (§6), distributor PDF parser + mapping UI + phone pricing (§4–5).
4. Services, install/update/rollback scripts, tray app, alerts and health monitoring (§1, §8).
5. Security hardening + SECURITY.md + backups (§10).
6. Website: static showcase, permanent slugs + copy/deep link, ArvanCloud deployment guide (§9).
6b. Catalog model mapping, fuzzy suggestions, nightly validation + hide/alert, bot slug/name resolution (§9a).
7. (Optional) Telegram bot channel on the shared core via proxy pool.
