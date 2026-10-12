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

## 8. Alerts to the owner
- Bale message to the owner's chat (ChatId in .env) on every new order and pending customer.
- Windows tray app: detects when the Sazeh Hesab program starts (process watch) → "X new orders, Y customers awaiting approval" + link to shopadmin.
- Pending counters in shopadmin.
- Health monitoring alerts (Bale + tray): bot down, Bale unreachable, SQL unreachable, price-list hold, all proxies dead.

## 9. Website
- Moves from Cloudflare to **ArvanCloud** (static export of the site on Arvan Object Storage + CDN; DNS to Arvan). The site is the plain HTML/JS project `E:\DSH-Workspace\projects\asr-ertebatat-shop` (no build step; decision 2026-10-12 — the old Next.js prototype `E:\projects\mobile-shop` is not used).
- Showcase only: product presentation and specs. **No prices, no stock, no live connection to the server, no data push, no order submission from the site.**
- **No accounting codes on the site** (decision 2026-10-12): `Kala.Code` can change after stocktaking and Sazeh Hesab names are entered inconsistently. Each site model has a **permanent slug of our own** (e.g. `iphone-17-pro`; a storage-level slug such as `iphone-17-pro-256` may be added later — slugs are never renamed or reused).
- Each model: button «استعلام قیمت و سفارش در بله» → copies the model name + slug to the clipboard and opens the Bale bot with a deep link (`start=m_<slug>`); the slug is printed next to the button as the dependable fallback («کد مدل: iphone-17-pro — این متن را در ربات بفرستید»). Telegram button later (same mechanism). Shop phone number as fallback.

## 9a. Catalog model mapping (shopapi / ShopAdmin / bot — decision 2026-10-12)
- One **catalog model** table in shopapi: slug ↔ accounting product(s) (`Kala`, per storage/color where needed). The distributor price-list rows (§5) map to the same catalog model, so each model is mapped once.
- ShopAdmin suggests matches with fuzzy, normalized name matching (case, partial names, ی/ي, ک/ك, spacing/ZWNJ, Persian/English digits); the owner confirms once.
- **Nightly validation** of every mapping: if the mapped product disappears or its name drifts → re-search by name, propose candidates, **hide that model from customers until the owner confirms**, and alert the owner on Bale. Never show a wrong product.
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
