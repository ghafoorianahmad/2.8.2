# PROGRESS — Asre Ertebatat 2 store system

Phases are defined in `REQUIREMENTS.md` §14. One phase per session.

## v2.4.0 — forgot password, server edition without login, test-DB mode (2026-10-13, branch `claude/amazing-mccarthy-dob95x`, from `claude/invoice-card-v3`) — DONE in code (Linux); GUI/Windows UNVERIFIED

- **Version 2.4.0** in `shopapi/app/control.py` and `shopadmin/installer/ShopAdmin.iss`; `shopapi/tests/test_v240.py::test_server_and_installer_versions_match` fails if they differ.
- **Remember-me checkmark**: Qt style sheets do not load `data:` URIs, so the glyph never showed. `theme.indicator_images()` now renders the check/radio PNGs to `%TEMP%\ShopAdmin-ui` and the stylesheet points at the files. Test renders a checked box offscreen and looks for the white mark.
- **Forgot password**: public `POST /auth/forgot` (+ `/forgot/status`, `/forgot/complete`) with a per-request secret (stored hashed), new table `password_requests`, event `password_request`; admins (`admin`, `super_admin`; permission `passwords.decide`) approve/reject in the new ShopAdmin page «درخواست‌های گذرواژه»; an admin cannot decide a super admin's request. After approval (30 min window) the requester picks the new password in the login window's dialog; the old password and all sessions die. Unknown usernames get an identical answer. Passwords stay salted scrypt hashes (the server has always used scrypt, not bcrypt).
- **Super admin**: «بازنشانی به ۱۲۳۴۵» (`POST /admin/staff/{id}/reset-default`: hash of 12345 + must-change-password, sessions dropped; until changed the account can do nothing but change its password) and the existing «تغییر گذرواژه» (now with an optional must-change checkbox).
- **Server edition** (the full build / ShopServerSetup; detected by the presence of `app.server_setup`, override `SHOPADMIN_EDITION`): no login screen, no logout/lock/change-password. It signs in with `POST /auth/console-login` — service key from `%ProgramData%\ShopServer\.env` + loopback only → session of the first active super admin. Client edition, bot/API keys unchanged.
- **Test mode**: `Settings.is_test_db()` (`ACCOUNTING_DATABASE` = `hesab5 t`) ⇒ `write_allowed()` is true with no switch/host check; `/admin/system-info` and `/admin/server/status` report `test_mode` and write enabled. Any other database keeps the old `ACCOUNTING_WRITE_ENABLED` + allowed-host rule.
- Also fixed two Linux-only test races (login window prefill / main-window header after the store closed).
- Tests: shopapi 303, shopadmin all green offscreen, shopbots 218, shoptg 45 (+2 skipped), shopsystem 36 (+12 skipped; `test_local_backup_dir` fails only because it asserts a Windows path).
- **Not verified**: anything on Windows (UAC/ACL read of the server `.env` by the server edition, real window rendering, installer build), live `hesab5 t` writes, the checkmark on a real display.

## Idempotency, e2e scripts, ShopAdmin UI leftovers (2026-10-13, branch `claude/magical-ride-7p262r`, from `claude/invoice-card-v3`) — DONE in code (Linux)

- `POST /orders` accepts `Idempotency-Key` (8–128 chars): same key + same customer → the original order (HTTP 200, no new reservation); another customer's key → 409; keys live 24 h in SQLite (`idempotency_keys`). The bot keeps one key per cart in its `kv` (retry/double tap reuses it; a changed cart or a finished checkout gets a new one). Tests: shopapi 293, shopbots 219.
- `shopadmin/scripts/e2e_check.py` and `e2e_app_live.py` rewritten for server-side login (`SHOPADMIN_USER`/`SHOPADMIN_PASSWORD` env, optional `SHOPADMIN_BOOTSTRAP_KEY`/`SHOPADMIN_CERT_FILE`); how to run is in their headers. Both were run on Linux against a fake-backed shopapi (all pass); **not run against `hesab5 t` / on Windows**.
- ShopAdmin: two-column login (`LoginWindow._build_brand_panel`), `widgets.add_shadow` on stat cards and the login card, `_CenteredOverlay` background scoped by object name, deferred login prefill tolerates a closed store. contrast_audit 95/95. Screens re-rendered on Linux into `shopadmin/docs/screens/` (fonts differ from Windows).
- Known on Linux: `test_sidebar_badges_and_close_to_tray` fails (closed SQLite in a Qt callback; also fails without these changes); shopsystem `test_local_backup_dir` fails (Windows path).
- `CLAUDE.md` shortened; its old status/backlog moved to the archive at the end of this file.

## Bot image cards v3.2 — small fixes (2026-10-13, branch `claude/invoice-card-v3`) — DONE in code (Linux)

- Final invoice: the «✓ فاکتور شما صادر شد — شمارهٔ فاکتور: …» row is now forced onto one line (`nowrap`, font 24 → 17 px by text length); it wraps only beyond ~62 characters (about 8 invoice numbers).
- Price card: the lone «فروشگاه» footer line (signature) is gone; the footer is now the date box plus the same contact band as the invoices (address, phone, Bale bot ID from the `shop` block of `messages.fa.json`; no thank-you line). `price_card()` takes `contact=`; the engine passes it.
- Tests: shopbots 186 passed (Telegram-channel tests not collectable here). Samples re-rendered in `docs/card-samples/`.

## Bot image cards v3.1 — invoice numbers, logo in header (2026-10-13, branch `claude/invoice-card-v3`) — DONE in code (Linux)

- **Pre-invoice**: new status row «✓ سفارش شما ثبت شد — شمارهٔ پیگیری: <our order number>» (same style as before on the final invoice).
- **Final invoice**: the number is now the accounting invoice number. New `AccountingReader.invoice_numbers()`: `SELECT DISTINCT f.ordercode, f.Numfact FROM <db>.dbo.facto f WHERE f.ordercode IN (?,…) AND f.Numfact IS NOT NULL ORDER BY …` — parameterized, no 2012+ syntax (no OFFSET/STRING_AGG), only `facto.Numfact/ordercode` (already in `grant_shopbot_2008r2.sql`). `GET /orders/{id}` returns `invoice_numbers` (list of strings) **only for the admin/bot key** and only when the order is written and invoiced; accounting down → empty list. Card text «✓ فاکتور شما صادر شد — شمارهٔ فاکتور: ۲۶۷۲، ۲۶۸۰» (all numbers of a partial order, joined by «،»); with no numbers it says only «فاکتور شما صادر شد».
- **Logo**: `assets/logo.png` is now in the header of all three cards in place of the store/phone illustration (the illustration remains only as a fallback when the logo file is missing), and still at the bottom of the invoices.
- Tests: shopapi 289 passed (pyodbc stubbed), shopbots 184 passed (Telegram-channel tests not collectable here). Samples re-rendered in `docs/card-samples/`.
- **Pending live check on `hesab5 t`**: the `invoice_numbers` query against a real invoiced order (`Numfact` type/format, e.g. varchar vs int) and that the bot's admin key reaches it.

## Bot image cards v3 — invoice/price card changes (2026-10-13, branch `claude/invoice-card-v3`, from `claude/hopeful-hamilton-yd346p`) — DONE in code (Linux); cards still OFF by default

- **Logo**: `clip/img/logo_black.png` from `ghafoorianahmad/cloud` (branch `claude/vibrant-fermat-eu8xlh`, 1450×650 transparent PNG) → `shopbots/app/cards/assets/logo.png`, embedded in the card HTML. Missing file = card still renders without it.
- **Invoice cards** (`render.py`): signature box removed, logo in its place; no colour anywhere on invoices (colour column/sub-line removed; the **price card keeps its colour column**); label «مشتری» → «خریدار»; accounting row → «سفارش شما ثبت شد — شمارهٔ پیگیری: <order id>» (shown when the order has an accounting number, i.e. on the final invoice; the tracking number is the bot order number); grand total in words under the digits (`cards/numwords.py`, tests in `tests/test_numwords.py`); titles «پیش‌فاکتور» (placed) / «فاکتور فروش» (invoiced: the existing `order_invoiced*` events, driven by the `Facto.ordercode` sync); footer = date box + logo, then a band with address, phone, Bale bot ID and one thank-you line; no price-validity line on invoices.
- **Footer values** come from the `shop` block of `messages.fa.json` (editable copy in `%ProgramData%\ShopServer`): existing `shop_address`, `shop_phone`; **new keys** `bot_id` (default `@asrertebatat2_bot`, taken from CLAUDE.md — owner must confirm it is the Bale bot ID) and `invoice_thanks`. Placeholder values still in the JSON (e.g. «شماره تلفن فروشگاه») would be printed as is — fill them in before enabling cards.
- **Payment info**: new shopapi settings `PAYMENT_CARD_NUMBER` (16 digits), `PAYMENT_SHEBA` (IR + 24 digits), `PAYMENT_OWNER` (≤ 80 chars), editable remotely (`control.EDITABLE`, written to `.env`, restart as for other settings) and labelled in ShopAdmin's server-settings page (`shopadmin/app/server_settings.py`, no new UI code). `POST /orders` now returns `payment_card_number/sheba/owner` (None when empty); the pre-invoice shows the payment row only for the filled fields, nothing at all when all are empty (then a note says details follow in the next message). The old `card_number/card_owner/bank_name` of `messages.fa.json` are no longer used by the card (still used by the text message).
- **Price card**: only the word «حسابداری» removed from its note.
- Tests (Linux, fakes): shopapi 286 passed (pyodbc stubbed: libodbc missing here), shopbots 180 passed (+ `test_telegram_channel.py` not collected, Telethon missing). ShopAdmin tests not run (PySide6 missing); only the label/translation module was exercised by hand.
- Samples: `docs/card-samples/{pre-invoice,pre-invoice-no-payment,final-invoice,price-card,price-card-out-of-stock}.png`.
- **Still to verify on Windows**: all items of the v2 list below, plus the ShopAdmin settings page shows/saves the three new fields, and a real order shows them on the pre-invoice.

## Bot image cards v2 — light invoice-sheet style, HTML → headless browser (2026-10-12, branch `claude/hopeful-hamilton-yd346p`) — DONE in code (Linux); OFF by default

Replaces the dark Pillow cards below with the style of `docs/card-samples/invoice-reference.jpg`. Same public API (`price_card`, `pre_invoice_card`, `final_invoice_card`), same text fallback, `BOT_IMAGE_CARDS` still default `false`.

- **Look**: white/light-blue page, soft blue waves top and bottom, header with «عصر ارتباطات ۲» + inline store/phone illustration, rounded info box (order no., Shamsi date, optional customer), table with dark-blue header row and an icon per column/row, dark-blue totals panel with large bold numbers, notes box (bank card goes here on the pre-invoice), footer with date and signature line. Amounts in Rial, Persian digits.
- **Tech** (`shopbots/app/cards/render.py`): HTML/CSS template per card; Vazirmatn embedded as base64; icons = Tabler Icons subset (MIT, `assets/icons.json` + `ICONS-LICENSE-MIT.txt`) inlined as SVG; screenshot by running a Chromium-family binary with `--headless=new --screenshot` (no Playwright, no download). Browser lookup: `BOT_CARD_BROWSER` → on Windows Microsoft Edge (`Program Files (x86)\Microsoft\Edge\Application\msedge.exe`, then Chrome) → PATH → `/opt/pw-browsers`. Persian shaping/RTL are done by the browser, so `arabic-reshaper`/`python-bidi` were dropped from `requirements.txt` and `build_exe.bat`; Pillow stays, only to crop the screenshot (a headless window's viewport is shorter than `--window-size`, so the window is rendered 200 px taller and cropped). Render timeout 40 s; any failure (no browser, timeout, crash, bad image) → `None` → text message.
- **Samples** regenerated with Linux Chromium 141: `docs/card-samples/*.png` (+ README). Regenerate: `python shopbots/scripts/render_card_samples.py`.
- Tests: shopbots 146 passed (`tests/test_telegram_channel.py` not collected here: Telethon not installed in this container). Browser-dependent tests skip when no browser exists.

### Must be verified on Windows (not done here)
1. `msedge.exe --headless=new --screenshot` works from the **ShopServer service account** (`NT SERVICE\ShopServer`): it needs a writable temp dir (we use `%TEMP%` of that account) and Edge must start without a desktop session. If it fails, set `BOT_CARD_BROWSER` or run the service as a normal user; the bot just sends text.
2. Output size/crop: the PNG must come out exactly 1080 px wide with the whole page (footer + bottom wave) visible; the 200 px window padding assumes Edge's headless viewport is shorter by < 200 px.
3. Vazirmatn and icons render the same (fonts are embedded, so they should); compare against the Linux samples.
4. Card latency (~1–2 s per card) acceptable; many parallel cards spawn parallel Edge processes.
5. PyInstaller build still bundles `cards/assets` (now includes `icons.json`); `--collect-submodules PIL` kept.
6. Real Bale/Telegram upload and how the clients display the tall image (unchanged from v1, still untested).

## Bot image cards — price / pre-invoice / invoice (2026-10-12, branch `bot-cards`) — DONE in code (Linux, fakes only); OFF by default

Branched from `bot-design`. Samples with fake data: `docs/card-samples/` (regenerate: `shopbots/scripts/render_card_samples.py`).

### Done
- **Renderer** `shopbots/app/cards/render.py`: Pillow + `arabic-reshaper` + `python-bidi`, Vazirmatn Regular/Bold (OFL, bundled in `cards/assets/` with `OFL.txt`). Letters are reshaped, put in visual order and drawn with Pillow's BASIC layout, so output is identical with or without libraqm and nothing needs installing on Windows. Dark theme (#05070c, deep blue glow, frosted panels); optional `cards/assets/logo.png` replaces the text wordmark. Every function returns PNG bytes or `None` (never raises).
- **Shaping proof** (`tests/test_cards.py`): joined presentation forms, RTL visual order, Latin model names/digits keep their order inside Persian, every emitted glyph exists in the font, Shamsi date (`cards/jdate.py`) and Persian digits.
- **Cards**: price card (name, colour, price in Rial, stock badge, shop name), pre-invoice (order no., Shamsi date, lines, total, bank card from `messages.fa.json`), final invoice (order no., lines, total, "invoice issued" / partial badge).
- **Sending**: `send_photo_bytes()` on the adapters (Bale = multipart `sendPhoto`; Telegram = Telethon `send_file` from memory). Photo + short caption (`CARD_CAPTION_*` in `messages.fa.json`). Any render/upload failure → the existing text message (flow never breaks).
  - Price card: on the **first colour pick per product view only**; later colour switches send just the existing short "new price" text.
  - Pre-invoice: right after checkout; the text payment instructions still follow (copyable card number, receipt prompt).
  - Invoice: on the existing `order_invoiced` / `order_partially_invoiced` events; the photo's caption is the usual invoiced message (text only if the photo fails).
- **Setting** `BOT_IMAGE_CARDS` (default `false`, `.env` only; not in shopapi's editable list). `shopbots/.env.example` updated.
- `requirements.txt`: Pillow 12.3.0, arabic-reshaper 3.0.1, python-bidi 0.6.11.
- `shopsystem/build_exe.bat`: added `--add-data` for `cards/assets` and `--collect-data arabic_reshaper`, `--collect-submodules bidi/PIL` (**untested: no Windows build in this session**).
- Tests (Linux): shopbots **177 passed** (was 160; +17 in `tests/test_cards.py`).

### Final invoice data — what is used and what a true invoice needs
Used today (no grant change): the order's own lines (`order_items`: name, colour, qty, unit price), total, `accounting_order_no`, `invoiced_at` from shopapi's SQLite. The card therefore shows the **order's** prices/quantities, not what was actually invoiced, and no invoice number.
For an invoice-based card, these **read-only** grants would be needed (not added; to be applied by the owner on Windows / a DBA):
- `GRANT SELECT ON dbo.facto (Gey, Mab) TO shopbot;` — actual unit price / line amount invoiced (currently granted on `facto`: `Numfact, Codekala, Meg, ordercode, orderdetailcode`; `Numfact` = the invoice number and `Meg` = invoiced quantity are therefore already readable).
- `GRANT SELECT ON dbo.Fact (Numfact, <invoice-date column>) TO shopbot;` — the invoice date. The exact column name is **not confirmed**: check `Fact` on `hesab5 t` (`SAZEH_DB_REFERENCE.md` lists `Facto`, the line table, but the `Fact` header columns need a look).
Then shopapi's tracking (`tracking.py`) must also read and store them; that is a separate task.

### Pending / for the user
- Review the samples, then set `BOT_IMAGE_CARDS=true` in the server `.env` to enable.
- Not tested: real Bale `sendPhoto` multipart upload, Telethon `send_file` of bytes, the Windows PyInstaller build (assets/fonts bundled), and the card in the real Bale/Telegram clients (cropping of tall images).
- The card number shows exactly what is in `messages.fa.json`; with the placeholder, the pre-invoice says payment details follow.
- Persian digits are used on the cards; the captions keep the existing Latin-digit format.

## Bot look & feel — option C applied (2026-10-12, branch `bot-design`)

Texts only: `shopbots/app/messages.fa.json` (98 values changed: 25 button labels + 73 messages). No code, flows, callback data, keys or placeholders changed (placeholder sets checked per message).
- Style = option C of `DESIGN_SAMPLES.md` (formal Persian, "فرمایید", ◆ ❖ ✦ ☑ ◈ markers, 12-char `────────────` separators) mixed with a few functional emojis: 📱 phones/contact, 🛒 cart, 📦 orders, 💳 payment, 🧾 receipt/invoice, 🚚 shipped, 📍 address, ☎️ phone, 🔒 closed, 🎨 colors, 📒 statement, 📨 inquiry.
- Test-driven wording kept: `«{shop_name}»` in WELCOME, "رنگ را انتخاب کنید", "قیمت ندارد", "شمارهٔ سفارش", "🔄" in COLOR_CHANGED.
- Not changed (still in `engine.py`): color buttons use 🎨/❌, unavailable products `❌ <name>` in lists. Admin-only notices were only lightly restyled.
- Tests (Linux): shopbots 160 ✓.
- Pending: look at it in real Bale/Telegram (◆ ❖ ✦ ◈ glyphs on Bale desktop; if broken swap for 🔹). Operators who copied `%ProgramData%\ShopServer\messages.fa.json` keep their old texts until they replace that file.

## Phase 7 — Telegram bot channel (2026-10-12) — DONE in code (Linux, fakes only); never connected to Telegram

Branch `phase7-telegram` (not merged). No token, `.env`, session or real Telegram traffic was used.

### Decisions (user, 2026-10-12)
- Proxy parsing + fake-TLS + `connection_for` moved into a small shared package **`shared/tgproxy`** (`shop-tgproxy` 1.0.0), used by shoptg and shopbots. No importlib-by-path loading.
- The bot both **reads** the proxy ranking and **reports** health to shopapi (`/worker/proxies`, `/worker/proxies/report`).
- Reuses shoptg's `TG_API_ID` / `TG_API_HASH` (one Telegram app). Only `TELEGRAM_BOT_TOKEN` is new.

### Done
- `shared/` (`pyproject.toml`, `tgproxy/{proxies,faketls,connection}.py`): files moved with `git mv` from `shoptg/app`; shoptg imports and tests updated, behaviour unchanged. `import tgproxy` does not import Telethon; `faketls`/`connection` do (lazily from `connection_for`).
- `shopbots/app/platforms/telegram.py` — `TelethonBotAdapter(PlatformAdapter)`, `platform = "telegram"`:
  - bot login (`sign_in(bot_token=…)`) over an outgoing MTProto connection; no webhook, no inbound port;
  - Telethon events (new message, callback) become Bot-API-shaped update dicts in a queue, so **`polling.py` and `engine.py` are unchanged** and every Bale flow works as is: contact-only registration (contact `user_id` 0/missing → `None` → refused; `!= sender` refused by the existing core check), R4 auto-approval, catalog/search, `m_<slug>`/copied text/names, colors with per-color price, cart/order, receipt (photo or PNG/JPEG file, size checked from the message and while streaming), tracking messages, statement, closed mode;
  - messages > 4096 chars are split (keyboard on the last part); callback data > 64 bytes is refused with an error; Telethon's default Markdown parse mode is switched off; groups and bot senders are ignored; update ids are time based, so they keep growing across restarts (the engine stores the last id).
- `shopbots/app/platforms/tg_pool.py` — `ProxyPool`: shopapi ranking (best first) → local `TG_PROXY` links → direct (`TG_ALLOW_DIRECT`). Reports `{"id","ok","latency_ms"}` after every connection attempt and every health ping.
- **Auto-switch:** each `get_updates` call (re)connects through the first working candidate; a failed ping (every `TG_HEALTH_INTERVAL_SEC`, default 180 s), a dropped socket or a network error drops the connection, reports the proxy as failed and raises a network `BotApiError`; `poll_platform`'s existing backoff retries, which connects through the next proxy within seconds. A wrong bot token / api id is fatal (401 line) and does not cycle through the pool. All proxies dead → the retry loop continues; shopapi raises its `proxies_all_dead` alert from the reports.
- Config (`shopbots/app/config.py`, `.env.example`): `TELEGRAM_BOT_TOKEN`, `TG_API_ID`, `TG_API_HASH`, `WORKER_API_KEY`, `TG_PROXY`, `TG_ALLOW_DIRECT`, `TG_BOT_SESSION` (default `tg_bot.session` next to `SQLITE_PATH`), `TG_HEALTH_INTERVAL_SEC`, `TG_CONNECT_TIMEOUT_SEC`. The channel starts only when token + api id + api hash are all set and Telethon is installed (otherwise one log line, Bale unaffected). Secrets are `repr=False`; the log redactor also masks `api_hash`.
- **Owner alerts stay on Bale / admin isolation:** `ADMIN_CHAT_IDS` now means Bale only (a bare id used to match *any* platform; a Telegram user id equal to the owner's Bale id would have become an admin). `telegram:<id>` entries are ignored. Tested.
- The bot's Telethon session is an SQLite file (keeps update state with `catch_up=True`, so messages sent while the bot was down are delivered, and the entity cache so proactive tracking messages work after a restart). It is git-ignored (`*.session`) but holds the bot's auth key: treat it as a secret.
- Packaging: `shoptg/requirements.txt` + `shopbots/requirements.txt` + `shopsystem/requirements.txt` list `shop-tgproxy==1.0.0` / `../shared`; `shoptg/install.ps1 -Dev` and `shopbots/setup.ps1` install `..\shared` first; `shoptg/build_package.ps1` builds the shared wheel into `wheels\`; `shopsystem/build_exe.bat` adds `--collect-submodules telethon` and `tgproxy`.

### Tests (Linux, fakes; no network)
- shopbots **160** ✓ (+32: `tests/test_telegram_channel.py`, `tests/tg_fakes.py`): connector per secret kind (ee/dd/plain), ranking order, failover on ping failure and dropped socket, all-dead and recovery, fatal token, reports, pool client (local dedupe, direct last, keyless, API down), full engine flows on platform `telegram` (registration refusals, R4, model links, colors, order + receipt, statement, closed mode + tracking), split messages, polling loop unchanged, admin isolation, secrets absent from logs, the real Telethon client accepts our options.
- shoptg **45 ✓ + 2 skipped** (same as before the move), shopapi **281** ✓ (needs `unixodbc`).
- shopadmin: 2 failures in `test_notifications` / `test_ui` that **also occur without my changes** (sqlite "closed database", differs per run; Qt on Linux); the code is untouched by this phase. shopsystem: 36 ✓, 12 skipped, 1 failed (`test_local_backup_dir`, expects the Windows path `E:\ShopBackup`).

### Must be verified on Windows / live (not done)
- A real BotFather bot: login, `/start`, contact button, inline buttons, receipt photo download, **`/start m_<slug>` deep link** (`t.me/<bot>?start=m_<slug>`), message editing, a callback toast.
- Telethon 1.45.0 uses the newer TL layer: reply/inline buttons are `Button`/`KeyboardInlineButton` with `.type`; confirm `request_phone` really shows the share-contact button and that the contact message carries `user_id` for the user's own number.
- Fake-TLS (`ee`) against real proxies **for a bot login** (shoptg only proved the user-session path); latency/failover timings; behaviour when Telegram is blocked without a proxy.
- Two Telethon processes (shoptg user session + the bot) using the same api id from one IP: no interference expected, unproven.
- `catch_up` on first start with an empty session file; update delivery after a restart.
- `WORKER_API_KEY` reaches ShopSystem's environment so the in-process bot can read `/worker/proxies` (the launcher already writes it for shoptg).
- **PyInstaller / ShopSystem.exe:** `Telethon` and `shop-tgproxy` must be installed in `shopsystem`'s venv (`pip install -r requirements.txt` from `shopsystem\`, which now includes `../shared`); `--collect-submodules telethon`/`tgproxy` were added to `build_exe.bat` untested; the packages are renamed `shopbots_app`, so `shopbots_app.platforms.telegram` is imported lazily — check it is in the bundle, that the exe size is acceptable, and that `build_all.bat` still passes.
- `shoptg\install.ps1 -Dev`, `build_package.ps1` (shared wheel + offline install probe) and `shopbots\setup.ps1`: edited on Linux, never run.
- ShopAdmin shows no Telegram bot status yet (the health snapshot has the platform; no UI change was made).

### Next step
Owner: create the bot with BotFather, put `TELEGRAM_BOT_TOKEN` in the server `.env`, run the checks above on a test bot, then add the Telegram button on the site (same `m_<slug>` mechanism, REQUIREMENTS §9).

## Phase 6b — catalog-model mapping, fuzzy suggestions, nightly check, bot resolution (2026-10-12) — DONE in code; not tested on SQL or live Bale

### Decisions (user, 2026-10-12)
- Plan approved with one change to the nightly check (now in REQUIREMENTS §9a):
  - if the `kala_code` still exists and the new name is still a strong fuzzy match (`MODEL_DRIFT_MIN_SCORE`, default 0.7), the model **stays visible** and the item is only flagged «drifted» in ShopAdmin, with no Bale alert;
  - the model is hidden and the owner alerted only when the product is missing/inactive or the similarity is below the threshold.
- Price-list rows reach a model through the same `kala_code` (`price_mappings.kala_code` = `catalog_model_items.kala_code`), so each model is mapped once. One accounting product belongs to one model only.

### Done
**shopapi**
- `app/fuzzy.py` — normalized matching:
  - case, ی/ي, ک/ك, Persian/Arabic digits, ZWNJ/diacritics;
  - letter/digit split (`17pro`);
  - Persian↔English model words (آیفون/iphone, پرو/pro, گیگ/gb, «سی» = c, «ای» next to a number = e).
  - Identity first: numbers, model qualifiers (Pro/Max/Ultra/…, and any single latin letter: 17/17e, 14/14c) and accessory words (قاب/گلس/…) on one side only cost a lot. Colors/units cost little.
  - `coverage()` ranks suggestions (model name → accounting name). `similarity()` is used for drift. `similarity(model_only=True)` ignores storage/color in a customer's text.
- Tables `catalog_models` (slug, name, brand, aliases, hidden) and `catalog_model_items` (kala_code UNIQUE, label, confirmed/current name, state ok/drifted/missing, score, candidates JSON).
- `app/catalog_models.py`: repo, `run_check`, `nightly_loop` (started in the lifespan; once a day after `MODEL_CHECK_HOUR`, default 02:00 server time, -1 = off), `resolve`.
  - **Nightly check:**
    - unchanged name → ok;
    - small change → drifted (visible, no alert);
    - gone/inactive or below the threshold → missing: candidates (searched by the confirmed name, excluding products already mapped) + model hidden + `model_review` event + **one** Bale message (`owner_alerts`) for newly hidden models only.
    - A failed or empty accounting read changes nothing. Never re-maps on its own.
- Reader `product_names()`: `SELECT Code, Name FROM Kala WHERE active = 1`, no user input.
- `app/routers/catalog.py`:
  - `/admin/catalog-models`: list + counts + last check; `import` (upsert by slug, site aliases merged, mappings untouched); `check` (now); `{id}` GET/PATCH; `{id}/suggestions`; `{id}/items` POST; `items/{id}` PATCH (relabel/replace) / DELETE; `items/{id}/accept`; `{id}/confirm`.
  - New permission `catalog.manage` (admin + super admin). Every change is audited.
  - **Confirm is refused while any item is «missing»**: a code that was reused for another product must be replaced, removed or accepted on its own, never by a model-wide confirm. This was found by a test where the code became a charger.
  - `GET /catalog/resolve?text=` (bot key) → found (items + labels) / ambiguous (≤3 options) / unavailable / unknown. Products are returned only for a visible, mapped model.
- `.env.example`: `MODEL_CHECK_HOUR`, `MODEL_DRIFT_MIN_SCORE`, `MODEL_RESOLVE_MIN_SCORE` (0.75).

**shopbots**
- `looks_like_model_ref` (shape only): `m_<slug>`, «کد مدل»/«كد مدل», a bare hyphenated slug. Resolution itself is on the server.
- `/start m_<slug>`, a pasted text, a bare slug, or (free text) a strong name match:
  - one product → open it;
  - several → label buttons (`kp:<code>`);
  - ambiguous → model buttons (`mdl:<i>`, slugs kept in the conversation because 64-byte callbacks are too short for a 62-char slug);
  - hidden/unmapped/unknown → `MODEL_UNAVAILABLE` / `MODEL_UNKNOWN` with the shop phone. Plain chat still goes to the main menu.
- A model reference sent before registration is kept and shown after the contact (`MODEL_AFTER_CONTACT`).
- 5 new texts in `messages.fa.json`. An older operator copy in ProgramData falls back to them key by key.

**shopadmin**
- New page «مدل‌های سایت» (`app/ui/pages/catalog_models.py`; sidebar `catalog`; `catalog.view` for every role, `catalog.manage` for admin/super admin):
  - banner with the last check and the hidden/unmapped counts;
  - filters (hidden / drifted / unmapped / ok / all) and search;
  - «ورود مدل‌ها از سایت…» reads the site's `assets/products.js` as text (never executed): slug, name, brand, aliases;
  - «بررسی اکنون».
  - Detail: items with state, current name, similarity and price-list row count. Actions: add (suggestion dialog), replace (nightly candidates first), accept current name, label, delete, aliases, «تأیید و نمایش به مشتری».
- `model_review` → tray warning, opens the page on the «hidden» filter.

**Other:** `SECURITY.md` website row (an edited/unknown slug gets "not found + phone", never a guess). REQUIREMENTS §9a refinement.

### Tests
- shopapi **281** ✓ (+36: fuzzy, drift classes, routes/permissions, nightly hide/alert-once/confirm, failed read, loop, resolve paths, aliases, storage/color in customer text).
- shopbots **128** ✓ (+8). shopadmin **434** ✓ (+15, exit 0). shopsystem **49** ✓, shoptg **47** ✓ (unchanged).
- The real site catalog (66 models of the redesign `products.js`): every name, alias, `m_<slug>` and copied text resolves to its own model, except 4 aliases the site gives to two models. For those the bot asks, which is the intended behavior:
  - «شیائومی پوکو» → poco-x6-pro / poco-x7-pro;
  - «شیائومی ردمی ۱۵» → redmi-15 / redmi-note-15.
  - The first run found «iPhone 17» vs «17e» ambiguous; fixed (single letters = model identity).

### Pending / for the user
1. On `hesab5 t` (regular PowerShell, not from the Claude app): start shopapi, import `products.js` in ShopAdmin, check that the suggestions on real Sazeh names make sense, map a few models, run «بررسی اکنون». `product_names()` has not run on real SQL yet.
2. Bale: `/start m_<slug>` still depends on Bale passing the start parameter (2 of 8 in the live test). The pasted text and the bare slug are the fallback and are handled.
3. Site data: the two shared aliases above. Make them specific in `products.js` if you prefer that the bot never asks.
4. Then push the redesign repo (branch `redesign`) and purge the Arvan cache (Phase 6 pending item 1).

### Next step
Phase 7 (optional): Telegram bot channel on the shared core via the proxy pool, or the live-test items above.

## Phase 6 — website: static showcase, model slugs, ArvanCloud guide (2026-10-12) — DONE; committed, not pushed

**Live site = `E:\DSH-Workspace\projects\asr-ertebatat-2-redesign`** (GitHub `ghafoorianahmad/asr-ertebatat-2`, branch `redesign`). This was found after the first pass:
- every live file (`index`, brand pages, `products.js`, `site.js`, `site.css`, `theme.css`) is byte-identical to `origin/redesign` `141d9c1`;
- `redesign-2`-only files and `design-samples/` return 404;
- the live site is already served from Arvan Object Storage `ir-thr-at1`.

GitHub itself could not be queried: both repos are private and the local token has no access.

Phase 6 is in **both** site repos, with identical slugs:
- redesign `e98eaef` on branch `redesign` (the asset diff replayed from the main site + the same page edits; every assertion matched);
- `asr-ertebatat-shop` `1524dc1` + `5258adf` on local branch `backup-local-2026-10-10` (not `main`; that site is not published).

Nothing is pushed: the owner pushes after Phase 6b. The Next.js folder `E:\projects\mobile-shop` is an unused Sep-17 prototype.

### Decisions (user, 2026-10-12) — added to REQUIREMENTS §9, new §9a, phase 6b
- **No accounting codes on the site.** `Kala.Code` can change after stocktaking and Sazeh names are inconsistent. Each model has a **permanent slug** (`id` in `products.js`, e.g. `iphone-17-pro`; never renamed or reused). Slugs are model-level because the site shows models, not storage sizes. Storage and color are picked in the bot; storage-level slugs can be added later.
- Mapping slug ↔ accounting product(s) lives in shopapi/ShopAdmin (one catalog-model table shared with price-list rows), with:
  - fuzzy suggestions and one-time confirmation by the owner;
  - a nightly check that hides a model and sends a Bale alert on drift.
  This is **Phase 6b** (§9a); not started.
- No order submission from the site; it stays static with no server connection.

### Done (site)
- Card, detail and order modals show «کد مدل: <slug>».
- The button «استعلام قیمت و سفارش در بله»:
  - copies «name + کد مدل: slug» (Clipboard API on HTTPS, textarea fallback);
  - opens `ble.ir/asrertebatat2_bot?start=m_<slug>`;
  - has a «کپی» button, the hint «این متن را در ربات بفرستید» and a `tel:09155000432` fallback.
- The floating action button opens Bale, not Telegram.
- The Telegram **bot** is hidden everywhere (`data-telegram-bot hidden` + `TELEGRAM_BOT_ENABLED=false` in `site.js`); the channel link is untouched. Telegram claims in the page text and meta descriptions now say Bale.
- `site.js`: `isSlug`/`SLUG_RE` (starts with a letter, ≤62 chars so `m_`+slug fits Bale/Telegram's 64-char `[A-Za-z0-9_-]` start payload). A numeric or unsafe "slug" is never put in a URL.
- `tools/check_site.js` (Node, no dependencies; also runs on the unpacked zip) checks:
  - slug format and uniqueness; no price/stock/code fields;
  - deep links and copied text, by evaluating the real `site.js` helpers;
  - no `fetch`/XHR/WebSocket/forms/keys/`shopapi`/price text in served files;
  - Telegram bot gated; phone fallback present;
  - every local `src`/`href`/`url()` exists.
- `DEPLOY_ARVAN_FA.md`: step-by-step Persian guide, checked against docs.arvancloud.ir on 2026-10-12. It covers:
  - bucket + public-read files, the «وب‌سایت استاتیک» feature (index `index.html`, error `404.html`);
  - adding the domain to the CDN, NS change at IRNIC (copy MX/TXT from Cloudflare first);
  - free HTTPS, the bucket «دامنه اختصاصی» (ANAME root + CNAME www, Host Header = static-website host);
  - cache rules + purge, test checklist, update and rollback (keep Cloudflare for 2 weeks).

### Tests
- `check_site.js`: **1249 ✓** on the repo and on the unpacked release zip. A mutation run (numeric slug, `fetch`, price text, unhidden Telegram) fails as expected.
- shopbots **120 ✓** (+1: site slugs, `m_<slug>` and the copied text are never parsed as a Kala code).
- Headless Chrome (375 px dark/light, 1366 px): no horizontal overflow and no clipped card buttons. Order modal within the viewport. Click flow verified (deep link, copied text, toast, FAB → plain bot link).
- Found and fixed on the way:
  - the long Bale label (`nowrap`) widened the modal past the phone screen;
  - `.order-note` was an existing dashed class, so mine was renamed `.order-intro`;
  - the card CTA clipped the label at desktop widths.

### Output
- **Live:** `E:\Outputs\StoreWebsite-Redesign\StoreWebsite-Redesign_2026-10-12.zip`. 316 files, SHA-256 `1430A348…2AADD2`, `check_site.js` 1249 ✓ unpacked. The redesign was also checked with headless screenshots (375 px dark/light, 1366 px) and a click flow.
- Not published: `E:\Outputs\StoreWebsite\StoreWebsite_2026-10-12.zip`. 179 files, built before `5258adf`.
- Each folder also has `DEPLOY_ARVAN_FA.md` + README; the previous 2026-10-08 zips are kept.
- Missed in the first pass and fixed in both repos: the hero «ثبت سفارش در ربات» button still had a Telegram icon.

### Pending / for the user
1. Push the redesign repo (branch `redesign`, `e98eaef`) after Phase 6b, then purge the Arvan CDN cache and run step 8 of the guide.
   - The live site is already on Arvan Object Storage, so the bucket/DNS steps of `DEPLOY_ARVAN_FA.md` are reference only.
   - Make sure the publish excludes `DEPLOY_ARVAN_FA.md` and `tools/`; the current setup already excludes `design-samples/` and `MISSING_IMAGES.md`.
2. ~~Until Phase 6b, the bot opens at the main menu for `m_<slug>` and pasted text.~~ Done in Phase 6b.
3. `asr-ertebatat-shop`'s Phase 6 commits are on local branch `backup-local-2026-10-10`, not `main`; merge or keep as you prefer (not published).
4. Still open on the site: Telegram channel link, map link, photos for 3 models.

### Next step
Phase 6b — catalog-model mapping (§9a): table + fuzzy suggestions in ShopAdmin, nightly validation with hide + Bale alert, bot resolution of `m_<slug>` / pasted text / fuzzy name.

## Phase 5 — security hardening, SECURITY.md, backups (2026-10-12) — DONE in code; nothing installed or applied on the shop server yet

Rollback point: `1867321` (Phase 4). Version **2.2.0**.

### Decisions (user, 2026-10-12)
- The off-server backup copy is **encrypted with AES-256-GCM**. The passphrase is in the server `.env` for the nightly job and **on paper** with the owner. Losing it makes the off-server copies unrecoverable, and README_FA §10 says so in a boxed warning.
- The local daily zip is complete (plain), protected by the data-folder ACL.
- **The Telegram (Telethon) session is never backed up**: DPAPI LocalMachine binds it to this machine. After a restore on new hardware, log in again.

### Done
**A. Daily backup — `shopsystem/backup.py`, supervisor thread**
- Runs at `BACKUP_HOUR` (3), or at once if the last attempt is more than 24 h old. It backs up:
  - `shopapi.db` / `shopbots.db` through SQLite's online-backup API, consistent while the server writes and including WAL content;
  - `.env`, `messages.fa.json`, `receipts\`, `pricelists\`, `tls\`.
- It never backs up `shoptg\`, logs or `backups\`.
- Output: `backups\daily\ShopServer_<stamp>.zip` with `manifest.json` (SHA-256 per file, row counts). `BACKUP_KEEP_DAYS` (14) are kept.
- **Restore test after every backup:** hashes, `PRAGMA integrity_check`, row counts == manifest.
- **Off-server copy** in `BACKUP_COPY_DIR`:
  - `.ssbk` = scrypt (n=2¹⁵, r=8, p=1) → AES-256-GCM in 1 MiB chunks. The nonce = prefix | index | last flag and the header is AAD, so truncation, reordering and edits are detected.
  - Each copy is read back, decrypted and compared to the local zip.
  - Without a passphrase nothing is copied, and the backup counts as failed.
- Status: `backups\status.json`. It shows in shopapi as the health check `backup` (down if the last run failed or there has been no success for 30 h → Bale + tray), in `/admin/server/status.backup` (no paths or secrets) and in a ShopAdmin server-page row.
- CLI:
  - `--backup-now`, `--verify-backup <zip|ssbk>`, `--decrypt-backup … --out …`, `--restore-backup <file>`;
  - `--set-backup-passphrase`: interactive; shows a generated 8×4 passphrase (160 bits) once, makes the owner type it back from paper, writes it to `.env` and clears the screen.
  - The passphrase comes from `SHOPSERVER_BACKUP_PASSPHRASE`, else `.env`, else a hidden prompt (real console only); never from argv.
- `--install-service` grants the service account Modify on a local `BACKUP_COPY_DIR`. A drive root or a UNC path is not granted; README explains it.
- `deploy/restore.ps1`:
  1. restore test first; a bad file or wrong passphrase changes nothing (exit 1);
  2. stop the service, safety copy to `backups\pre_restore_<t>`;
  3. restore, start, `/health`;
  4. if unhealthy, put the old data back automatically (exit 3/4).
- `common.ps1` now carries the SQLite `-wal/-shm` files with backups and update rollbacks (a WAL can hold committed rows after a crash). `restore_to` deletes a stale WAL.
- `build_exe.bat` copies `deploy\{common,restore,firewall_sql}.ps1` + README next to the exe (`ShopSystem\deploy\`), so a ShopServerSetup install has them too; `build_package.ps1` adds them to the zip.

**B. Hardening**
- **Suspicious-activity alerts — `shopapi/app/security_watch.py`.**
  - Every report is audited (`suspicious_<kind>`, masked source `…1234`). A per-source threshold within 1 h triggers one Bale message + `security_alert` event (ShopAdmin tray). It repeats at most once per source and kind per hour, and at most 6 alerts per hour overall.
  - Kinds:
    - bot: `contact_not_own` (3), `rate_limited` (3), `receipt_flood` (2);
    - shopapi: `order_probe` (5; someone else's order via GET or receipt), `login_failed` (10 per address), `login_throttled`, `account_locked`.
  - Bot side: new `POST /security/report` (bot/admin key, whitelisted kinds). `engine._report_security` sends at most one report per chat and kind per 60 s and never breaks the chat.
- **Log redaction — `shopbots/app/logging_setup.RedactingFilter`**, on every root handler, including the launcher's `app.log` and `supervisor.log`. It masks `bot<token>`, bare Bot API tokens, X-API-Key/Authorization/Bearer and `password|pwd|passphrase|api_key|secret|token=` values, in messages and exception text.
- **`sa` refused:** `Settings.accounting_connection_string()` raises for `sa` (any case). A test asserts that no shopapi code mentions `Options.ini`.
- The launcher warns when `API_HOST` is not loopback and `API_TLS` is off.
- `verify_permissions.sql`:
  - new probes: DELETE KalaOrder, UPDATE KalaOrderDetail, DELETE name_mo, `name_mo.mobile`, INSERT/UPDATE/DELETE KOL, UPDATE setting / Telegram_Setting, db_owner/datareader/datawriter membership, sysadmin;
  - a test checks the grant script DENYs §10's tables and the verify script probes them.
- **`deploy/firewall_sql.ps1`:**
  - limits sqlservr.exe of the instance (+ SQL Browser UDP 1434) to `-AllowedIPs`;
  - lists and disables (never deletes) broader allow rules, saved for `-Undo`;
  - is a dry run without `-Apply`.
  - **Not run anywhere.**
- `BACKUP_*` settings are not remotely editable (test).

**C. Docs**
- `SECURITY.md`: assets, trust boundaries, a compromise table (bot token, customer account, abuse, website, ShopAdmin PC, staff password, shoptg session, `shopbot` login, server admin, LAN, stolen USB), the `sa` problem, secrets, detection, backups, incident steps, known limits.
- `deploy/README_FA.txt` §10 (backup, passphrase warning, Telegram session, restore, quarterly restore drill) and §11 (SQL firewall). `.env.example` has a `BACKUP_*` block.

### Tests
- shopapi **245** ✓ (+15 `test_phase5.py`)
- shopbots **119** ✓ (+5)
- shopadmin **419** ✓ (+3)
- shoptg **47** ✓
- shopsystem **49** ✓ (+26):
  - `test_backup.py`: contents, live WAL, tamper, encryption round trip/wrong passphrase/truncation/reorder, no-passphrase never copies plain, prune, due/health, restore, CLI end to end;
  - `test_deploy.py`: restore.ps1 in real PowerShell against the fake service — OK, bad backup, unhealthy → rollback, encrypted copy with wrong/right passphrase.
- Sandbox note: pytest needs `--basetemp` in the scratchpad from the Claude app (`pytest-of-Lenovo` is not readable here).
- Found by the tests: `isatty()` is True for NUL on Windows, so a non-interactive run would hang in getpass. `interactive_console()` now checks `GetConsoleMode`.

### Pending / for the user (on the server, elevated)
1. Plug in a USB/second disk. Then:
   - set `BACKUP_COPY_DIR=E:\ShopBackup`;
   - run `ShopSystem.exe --install-service`, then `--set-backup-passphrase` (write it on paper, keep it away from the server and the USB);
   - run `--backup-now`. Expect `ok: true`, and the server page shows «موفق و آزموده».
2. Restore drill on another PC: `--verify-backup <latest .ssbk>` with the paper passphrase. Repeat every 3 months.
3. SQL firewall:
   - run `deploy\firewall_sql.ps1 -Instance SAZEHHESAB -AllowedIPs <accounting PCs>`, read the dry run, then add `-Apply`;
   - open «سازه حساب» on every PC; if anything breaks, run `-Undo`.
4. Run `shopapi\sql\create_api_user.sql` (DBA) and `verify_permissions.sql`. Every `(0)` row must show 0, and `is_sysadmin` must be 0.
5. Still from Phase 4: live service install/reboot test. Not verified live: Bale delivery of security/backup alerts, restore on real hardware.

### Next step
Phase 6 — website: static showcase, deep links + printed product code, ArvanCloud deployment guide (§9).

## Phase 4 — service, install/update/rollback, tray, alerts, health (2026-10-12) — DONE in code; service not installed on any PC yet

Rollback point: `4a151d0` (Phase 3). Version 2.1.0.

### Decisions (user, 2026-10-12)
- Real Windows service (pywin32), not NSSM: no unsigned third-party download. Account = virtual service account **`NT SERVICE\ShopServer`** (dedicated, not admin, no password).
- shopapi stays on **LAN HTTPS** for ShopAdmin clients (the network is VLAN-segmented). Firewall = LocalSubnet by default; optional allowed-IP list (`FIREWALL_ALLOWED_IPS`). No port is opened to the internet.
- Tray = part of ShopAdmin (`--tray`), not a separate app: it already has the server session.
- Health alerts go **straight from shopapi to Bale** (`owner_alerts.py`), so "bot down" still arrives; other owner alerts still go through the bot.

### Done
**A. Windows service — `shopsystem/winservice.py`, `launcher.py`**
- Service `ShopServer`: `ShopSystem.exe --winservice --data-dir …`. Auto start at boot, no login needed. SCM restarts it 10 s / 30 s / 60 s; `failureflag 1`; `sidtype unrestricted`.
- `--install-service` / `--uninstall-service` / `--start-service` / `--stop-service` / `--service-status` print JSON.
  - Install grants the account Modify on the data folder and on files that have their own ACL (`.env`, dbs, `tls\*`). With `SHOPTG_DIR` set, it also grants Read on `shoptg\.env` and Modify on the session folder `%ProgramData%\ShopServer\shoptg`.
  - It removes the old `ShopServer` boot task.
  - Uninstall takes the grants back. Data stays.
- The supervisor runs separate children, each with its own restart and back-off: (1) API + Bale bot; (2) **shoptg** when `SHOPTG_DIR` is set.
  - shoptg's environment is filtered: it gets only the local HTTPS URL, the CA file, `WORKER_API_KEY` and `TG_SERVICE_ACCOUNT`, never the Bale token or the SQL password.
  - A child failing 3× in 10 min → one Bale alert per hour.
  - A service stop terminates the children.
- `--health-check [--timeout N]` waits for `/health` using the pinned certificate (used by update.ps1).
- `--init-config` now generates `WORKER_API_KEY`; `SHOPTG_DIR` and `FIREWALL_ALLOWED_IPS` are setup fields.
- Build: pywin32 + pdfplumber hidden imports/collects; `build_exe.bat` also runs the shopsystem tests.

**B. Install / update / rollback — `shopsystem/deploy/`**
- `install.ps1` copies the program, locks the data folder, registers the service, opens the firewall, then starts it and checks health. Without a `.env` it registers but does not start.
- `update.ps1` steps:
  1. Stop the service, then back up the program plus `.env`, dbs, `messages.fa.json`, `receipts\`, `pricelists\`, `tls\` → `backups\update_<time>\`.
  2. Swap in the new program and start it.
  3. `/health` within 120 s → done.
  4. Otherwise it **puts back the old program and data**, restarts and exits 3 (4 if the old version is unhealthy too).
  - Keeps 3 backups. Accepts a zip.
- `uninstall.ps1` removes the service and firewall rule; `-RemoveProgram` also removes the program folder. Data is kept.
- `README_FA.txt` covers the service, install/update/uninstall, a SQL login for `NT SERVICE\ShopServer` if Windows auth is used, the firewall, shoptg, alerts, and **BIOS "Restore on AC Power Loss" + UPS**.
- `build_package.ps1` builds `ShopServer_<ver>_<date>.zip`. The exe, scripts and README go in; `.env`/db/log/key are refused.

**C. Health monitoring — `shopapi/app/monitor.py`, `owner_alerts.py`**
- Every `HEALTH_CHECK_SECONDS` (60) it checks: SQL ping, bot loop running, Bale reachable (≥3 failed polls and no success for 3 min), and shoptg status freshness (`TG_STATUS_STALE_MINUTES` 20; ignored until the worker has ever reported).
- Down after `HEALTH_FAIL_THRESHOLD` (2) bad checks, up on the first good one. Each change produces one event `health_<check>_down/up` plus one direct Bale message.
- `/admin/server/status` now has `health` and `telegram_worker` (connected/proxy/login/error/time only).
- Both settings are remote-editable.

**D. ShopAdmin**
- The server wizard registers the **service** (no Windows password any more). The Windows-auth option explains the SQL login the service account needs. New optional fields: allowed IPs (validated) and the shoptg folder.
- Tray:
  - health and server warnings (price list held/failed, all proxies dead, Telegram login/unreachable) appear as warning balloons. They are not counted as unread; price-list warnings open the price-list page.
  - `--tray` starts hidden with the remembered session. Without one, it shows an icon that offers to sign in. A second `--tray` start sends "ping" instead of "show".
- Settings → اعلان‌ها:
  - "run at Windows sign-in", via HKCU Run `ShopAdmin.exe --tray`;
  - "remind when سازه حساب opens" (`sazeh_watch.py`): `tasklist` every 10 s, prefix `Sazeh Hesab` (the exe name carries the version); on start → "X سفارش جدید، Y مشتری در انتظار تأیید", and a click opens the page.
- Server page: rows «کارگر تلگرام» and «پایش سلامت».
- Inno:
  - uninstall runs `--uninstall-service` (plus legacy task delete);
  - an upgrade does `net stop ShopServer` before copying;
  - an old task-based install is moved to the service and started again in `ssPostInstall`.

### Tests
- shopapi **230** ✓ (+12 `test_phase4.py`), run with `PYTHONPATH=.venv\Lib\site-packages python -m pytest`.
- shopbots **114** ✓ (unchanged).
- shopadmin **416** ✓ (+15 `test_phase4.py`; task tests replaced by service/firewall tests).
- shoptg **47** ✓.
- shopsystem **23** ✓ (new):
  - service commands with a fake runner;
  - supervisor restart, stop and crash-loop alerts;
  - the shoptg environment filter;
  - health check against a local HTTP server;
  - **update.ps1 run in real PowerShell against a fake service**: update OK, rollback of program + data after a "migration", old version unhealthy → 4, zip + keep 3, no service, bad package;
  - firewall list; service path parsing.
- Sandbox note: the shopapi venv (Store Python) cannot create temp files from the Claude app. `build_exe.bat` therefore has an opt-in `SHOP_TESTS_ALREADY_RUN=1` to skip its shopapi/shopbots test step after both suites were run separately; this build used it. On a normal PowerShell, run `build_all.bat` without it.

### Build / outputs (`E:\Outputs\ShopSystem\`)
- `ShopServerSetup_2.1.0_2026-10-12.exe` (64 MB; bigger because of pywin32 + pdfplumber) and `ShopAdminSetup_2.1.0_2026-10-12.exe` (33 MB).
- `ShopServer_2.1.0_2026-10-12.zip` is the server package for `install.ps1` / `update.ps1`: 254 files, no `.env`/db/log/key.
- SHA-256 values are in `E:\Outputs\ShopSystem\README_FA.txt`; the 2.0.0 pair is kept as the previous version.
- Smoke test of the frozen exe: `--service-status` → `state: null` (not installed); `--health-check` returns JSON; pywin32 and pdfminer are bundled.

### Pending / for the user (on the server, elevated)
1. **Live service test** (not done on any PC — it changes the system):
   - install with ShopServerSetup, or move the current task install with `install.ps1`;
   - `Get-Service ShopServer`, reboot without logging in, check the bot answers;
   - kill `ShopSystem.exe --worker` in Task Manager → it comes back;
   - `update.ps1` with the same zip (expect 0).
2. The service account must reach SQL:
   - with SQL auth (`shopbot`) nothing changes;
   - with Windows auth, create `LOGIN [NT SERVICE\ShopServer]` (README §5).
3. The dev xray proxy at 127.0.0.1:10808 needs a logged-in user; Bale needs no proxy. shoptg uses its own `TG_PROXY`.
4. shoptg: set `SHOPTG_DIR` in the server `.env`, run `--install-service` again, restart (`shoptg/SERVER_GUIDE.md` §6). The shoptg zip in `E:\Outputs\ShopTG` still has the old guide; the updated guide is next to it.
5. BIOS "Restore on AC Power Loss" + UPS (README §9).
6. ShopAdmin on the owner PC: Settings → اعلان‌ها → autostart + «سازه حساب» reminder; tick «مرا به خاطر بسپار» once.
- Not verified live: Bale delivery of health alerts, `tasklist` names on the shop PC (prefix setting `sazeh_process_names` if different), Inno upgrade from 2.0.0 (task → service migration path).

### Next step
Phase 5 — security hardening, `SECURITY.md`, daily backups of SQLite + receipts + config with an off-server copy and a restore test (§10).

## Phase 3 — Telegram worker, price list, proxy pool (2026-10-12) — DONE in code; live Telegram login pending (on the server)

Part 1 is WIP commit `db48ce3` (rollback point: `5d7a0cf`). Part 2 is committed on top of it.

### Done — part 1 (shopapi / shopbots / shopadmin)
- **shopapi**
  - PDF parser `app/pricelist/parser.py`. On the sample: 195 rows, 15 sections, date 1405/07/19. Scrambled Persian text is matched by its letter multiset.
  - Pricing `pricing.py`: روال×10,000 Rial; else نقد×10,000 + 5,000,000 Rial; no price = inquiry.
  - Import with safety checks, `importer.py`. Outcomes: duplicate / older / failed / held. A list is held on a >15% change of a mapped price, or when most mapped rows are missing. A copy of each PDF goes to `pricelists/`.
  - Tables: `price_lists`, `price_list_rows`, `price_mappings` (map or ignore, by row key), `inquiries`, `proxies`, `proxy_days`.
  - Routes `/admin/pricelists*`, `/admin/price-mappings*`, `/admin/inquiries*`, `/admin/proxies*` and `/worker/*`. `WORKER_API_KEY` is loopback-only and limited to `/worker/*`.
  - Permissions: `pricelist.manage` for admin and super admin; `proxies.manage` for super admin only.
  - Products and orders have per-color variants, from mapped rows only. Phones are sold on list availability. A list older than `PRICELIST_MAX_AGE_HOURS` allows inquiries only.
  - Proxy pool `app/proxypool.py`: ranked by stability; probation → main; retired after N bad days, but never below 3 main proxies; days when no proxy worked are ignored; all-dead alert.
- **shopbots**
  - Color picker: the price shows only after a color is picked. Changing the color announces the new price, re-read from shopapi on each pick.
  - Cart lines are per color (the cart table was migrated). An inquiry button.
  - Owner alerts: pricelist held/failed, all proxies dead, Telegram login required/unreachable, price inquiry.
- **shopadmin**: page «لیست قیمت».
  - Rows tab: mapping dialog, ignore, section/brand filter, search.
  - Lists tab: PDF upload, approve/reject a held list.
  - Proxies tab (super admin only).

### Done — part 2 (this session)
**A. `shoptg/` — new component: Telegram worker, its own venv, Telethon 1.45**
- `app/gateway.py` is the only module that uses Telethon. It is read-only: connect, read public channel messages, download, ping. It never joins, posts or marks messages as read.
- **Fake-TLS (`ee`) proxy support: `app/faketls.py`.**
  - Telethon 1.x throws away the domain of an `ee` secret and cannot use fake-TLS proxies, which are the most common kind in Iran.
  - The new connector does the full handshake: a signed 517-byte ClientHello with SNI, verification of the proxy's HMAC, then obfuscated2 inside TLS records.
  - It is tested against a local fake proxy that checks what mtprotoproxy/mtg check (HMAC, time, SNI) and decrypts the obfuscated2 header (tag `dddddddd`, DC id).
  - `dd` proxies use RandomizedIntermediate; plain proxies use Intermediate.
- **Session security: `app/secure_store.py`.**
  - The StringSession is encrypted with DPAPI **LocalMachine** scope plus app entropy, so the Phase 4 service account can decrypt it on this server only.
  - The file and folder get an NTFS ACL with inheritance removed: SYSTEM + Administrators full control (by SID, so it works on any Windows language), plus `TG_SERVICE_ACCOUNT` read.
  - The file is written atomically.
  - Honest limit: any local administrator can decrypt it. The ACL is what keeps other accounts out.
- **Worker loop: `app/worker.py`.**
  - Price channel every 30 min. PDFs newer than the cursor `tg_price_last_id` go to `/worker/pricelists`. The cursor also moves past images and text posts. On the first run only the newest PDF is sent. If shopapi is down, the cursor is not advanced.
  - Proxy channels weekly: links found in the text, in link entities and in buttons go to `/worker/proxies/candidates`.
  - Health check every 3 min. On a failure it switches at once to the next proxy: the shopapi ranking first, then `TG_PROXY`, then a direct connection (`TG_ALLOW_DIRECT`).
  - Every hour it probes up to 15 other proxies in rotation with an **anonymous** client. The shop session is never used for probes: the same auth key from two IPs risks `AUTH_KEY_DUPLICATED`.
  - Alerts go to `/worker/alerts`: login required (missing or revoked session), unreachable (after 15 min).
  - A status JSON is kept in `tg_status`. Logs show host:port and kind only, never secrets.
- **Scripts**
  - `login.ps1` → `scripts/login.py`: elevated PowerShell only. Phone, code, 2FA password and proxy are all typed into hidden prompts. 3 tries each. Nothing secret is printed.
  - `check_pricelist.ps1` → `scripts/check_pricelist.py`: read-only and works **without shopapi**. It takes the newest PDF of the price channel, parses it with the vendored parser and prints a summary. `-Save` keeps a copy; `-ProxyChannels` counts proxy links.
  - `run.ps1 [-Check]`: the check prints names and yes/no only, never values.
  - `install.ps1`:
    - creates the venv, installing **offline from the bundled wheels** when the server has Python 3.12 x64, otherwise from PyPI;
    - creates `.env` and limits it to SYSTEM and Administrators;
    - creates the data folder `%ProgramData%\ShopServer\shoptg` with the same ACL;
    - `-Dev` is for this PC.
  - `build_package.ps1` builds the zip:
    - app, scripts, ps1 files, guide;
    - `vendor/pricelist` = shopapi's `parser.py` + `pricing.py`;
    - 20 wheels for Python 3.12 x64;
    - an offline-install probe;
    - a check that no `.env`/db/log/session file is inside.
- **SERVER_GUIDE.md**: step-by-step guide for the server — copy, install, `.env` by hand, login, read-only test, troubleshooting.
- **Tests: 47**, using a fake Telethon client and a fake shopapi (httpx MockTransport), no network. They cover:
  - worker failover, direct fallback, probe rotation, cursor rules, weekly collection, alerts, status;
  - fake-TLS;
  - a real DPAPI round trip and the ACL arguments;
  - the config, and parity of proxy-link parsing with shopapi;
  - that real Telethon accepts our client options;
  - the login script (wrong code, 2FA, nothing secret in the output);
  - the check script on the real sample PDF (195 rows) and on a broken PDF.

**B. shopadmin**
- The sidebar test now expects 9 entries, including `pricelist`.
- `tests/test_pricelist.py` (24 tests):
  - helpers, permissions per role, rows/counts/sections/banner, server-side section filter, local search;
  - map (dialog), ignore, clear, cancel;
  - operator read-only; admin without the proxies tab;
  - lists: approve/reject held, upload (active vs held), non-PDF refused;
  - proxies: add, toggle, delete; mapping dialog search/pick/validation; no callback errors on any tab.
- The fake shopapi in `conftest.py` gained the price-list, mapping and proxy endpoints.

**C. Other**
- The WIP commit had committed pytest temp files (`shopapi/pytest-of-Lenovo/…`). They are now untracked, and `pytest-of-*/`, `shoptg/wheels/` and `shoptg/vendor/` are git-ignored.

### Tests
- shopapi **218** ✓. Run it with the regular Python 3.12: `PYTHONPATH=.venv\Lib\site-packages`. The Store-Python venv cannot write temp files from the Claude app.
- shopbots **114** ✓.
- shopadmin **401** ✓ (exit 0; pytest's summary line is lost at Qt teardown in this sandbox).
- shoptg **47** ✓.

### Server package
- `E:\Outputs\ShopTG\shoptg_server_1.0.0_2026-10-12.zip`; SHA-256 is in `E:\Outputs\ShopTG\README_FA.txt`.
- The guide is `shoptg/SERVER_GUIDE.md`, also inside the zip.

### Pending / for the user (the live Telegram day, on the server)
1. Install Python 3.12 x64 for all users. Copy and extract the zip to `C:\ShopServer\`, then run `install.ps1` from an elevated PowerShell.
2. `notepad .env`: type `TG_API_ID`, `TG_API_HASH` and `TG_PROXY` yourself. **Never paste them in chat.**
3. Run `login.ps1` (hidden prompts), then `check_pricelist.ps1 -Save`. Send me the output; it contains no secrets.
- **Not verified live:**
  - fake-TLS against a real proxy (tested only against a local fake proxy built to the protocol);
  - Telethon reading the channel;
  - the format of the real channel posts (document MIME type and file name).
- shopapi is not on the server yet. The worker itself (`run.ps1`) needs shopapi plus `WORKER_API_KEY`, which comes in Phase 4.
- Phase 4 carry-overs:
  - pdfplumber in the ShopSystem PyInstaller build;
  - `--init-config` must generate `WORKER_API_KEY`;
  - the shoptg service with `TG_SERVICE_ACCOUNT` (read grant on the session; no new login needed);
  - shopapi's `/admin/server/status` could show `tg_status`.

### Next step
Phase 4 — services (NSSM or equivalent), install/update/rollback scripts, tray app, alerts and health monitoring (§1, §8).

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

---

## Archive — CLAUDE.md status and backlog as of 2026-10-12 (moved here 2026-10-13)

Historical text, kept verbatim (Persian). The live status is in `CLAUDE.md`.

#### وضعیت (به‌روز 2026-10-12)

- **فاز ۷ (کانال تلگرام) در کد کامل شد (2026-10-12، شاخهٔ `phase7-telegram`؛ جزئیات در `PROGRESS.md`).** ربات تلگرام با Telethon (توکن BotFather) از طریق استخر پراکسی MTProto؛ آداپتر نازک `shopbots/app/platforms/telegram.py` روی همان هستهٔ مشترک، پکیج مشترک `shared/tgproxy` (لینک پراکسی + fake-TLS) برای shoptg و shopbots، خواندن و گزارش سلامت پراکسی از/به shopapi. فقط `TELEGRAM_BOT_TOKEN` جدید است؛ `TG_API_ID/HASH` همان shoptg. اعلان مالک فقط بله (`ADMIN_CHAT_IDS` فقط بله). **روی تلگرام واقعی و بیلد ویندوز آزموده نشده.** تست‌ها (لینوکس): shopbots ۱۶۰ ✓، shopapi ۲۸۱ ✓، shoptg ۴۵ ✓.

- **فاز ۶b انجام شد (2026-10-12)؛ جزئیات در `PROGRESS.md`.** جدول مدل‌های سایت در shopapi (slug ↔ کالاهای حسابداری؛ ردیف‌های لیست قیمت از همان `kala_code`)، تطبیق فازی (`app/fuzzy.py`)، بررسی شبانه (`MODEL_CHECK_HOUR`): تغییر کوچک نام = «drifted» و مدل نمایش داده می‌شود؛ کالای گم‌شده یا شباهت زیر `MODEL_DRIFT_MIN_SCORE` = پنهان + هشدار بله. ربات `m_<slug>`، متن کپی‌شده، slug خالی و نام را با `GET /catalog/resolve` می‌شناسد و هرگز حدس نمی‌زند. صفحهٔ ShopAdmin «مدل‌های سایت» (ورود از `products.js`). **روی `hesab5 t` و بلهٔ واقعی آزموده نشده.** تست‌ها: shopapi ۲۸۱ ✓، shopbots ۱۲۸ ✓، shopadmin ۴۳۴ ✓، shopsystem ۴۹ ✓، shoptg ۴۷ ✓.

- **فاز ۶ (سایت) انجام شد (2026-10-12)؛ جزئیات در `PROGRESS.md`.** سایت زنده = `projects\asr-ertebatat-2-redesign` (شاخهٔ `redesign`، commit `e98eaef`، **push نشده**؛ نسخهٔ منتشرنشدهٔ `asr-ertebatat-shop` هم `1524dc1`+`5258adf`): «کد مدل» دائمی (slug، بدون کد حسابداری/قیمت/موجودی)، دکمهٔ «استعلام قیمت و سفارش در بله» (کپی نام+کد و `start=m_<slug>`)، تلفن پشتیبان، ربات تلگرام پنهان، `tools/check_site.js`، راهنمای `DEPLOY_ARVAN_FA.md`. zip سایت زنده در `E:\Outputs\StoreWebsite-Redesign\`. تصمیم جدید: نگاشت slug ↔ کالای حسابداری با پیشنهاد فازی + بررسی شبانه = **فاز ۶b** (REQUIREMENTS §9a)، انجام شد. shopbots ۱۲۰ ✓.

- **فاز ۵ در کد کامل شد (2026-10-12)؛ جزئیات در `PROGRESS.md`، مدل تهدید در `SECURITY.md`.** پشتیبان روزانه (`shopsystem/backup.py`، رشتهٔ سرپرست، ساعت ۳): zip کامل محلی + آزمون بازگردانی خودکار + نسخهٔ بیرون از سرور **فقط رمزگذاری‌شده** (AES-256-GCM، عبارت عبور در `.env` و روی کاغذ مالک؛ `--set-backup-passphrase`)؛ نشست تلگرام هرگز پشتیبان نمی‌شود. `deploy/restore.ps1` با برگشت خودکار. هشدار فعالیت مشکوک (`shopapi/app/security_watch.py` + `POST /security/report` از ربات)، فیلتر حذف اسرار از لاگ، رد `sa`، `deploy/firewall_sql.ps1` (اجرا نشده). نسخه ۲٫۲٫۰. **هیچ‌چیز روی سرور فروشگاه نصب/اعمال نشده.** تست‌ها: shopapi ۲۴۵ ✓، shopbots ۱۱۹ ✓، shopadmin ۴۱۹ ✓، shoptg ۴۷ ✓، shopsystem ۴۹ ✓.

- **فاز ۴ در کد کامل شد (2026-10-12)؛ جزئیات در `PROGRESS.md`.** سرور = سرویس ویندوز `ShopServer` با حساب مجازی `NT SERVICE\ShopServer` (pywin32؛ جای Scheduled Task قدیمی را می‌گیرد و آن را حذف می‌کند)؛ سرپرست، سرور+ربات و (با `SHOPTG_DIR`) کارگر تلگرام را جدا اجرا/بازراه‌اندازی می‌کند. اسکریپت‌ها: `shopsystem/deploy/{install,update,uninstall}.ps1` (update با پشتیبان و برگشت خودکار)، بسته با `shopsystem/build_package.ps1`. پایش سلامت `shopapi/app/monitor.py` (SQL/ربات/بله/تلگرام → پیام مستقیم بله + اعلان ShopAdmin). ShopAdmin: `--tray`، اجرای خودکار با ورود ویندوز، یادآوری با باز شدن «سازه حساب». دیوار آتش: LocalSubnet یا `FIREWALL_ALLOWED_IPS`. **سرویس روی هیچ رایانه‌ای نصب/آزمون زنده نشده.** نسخه ۲٫۱٫۰. تست‌ها: shopapi ۲۳۰ ✓، shopbots ۱۱۴ ✓، shopadmin ۴۱۶ ✓، shoptg ۴۷ ✓، shopsystem ۲۳ ✓.

- **فاز ۳ در کد کامل شد (2026-10-12)؛ جزئیات در `PROGRESS.md`.** جزء جدید `shoptg/` (کارگر تلگرام با Telethon، venv جدا): کانال قیمت هر ۳۰ دقیقه → `/worker/pricelists`، جمع‌آوری هفتگی پراکسی، health check و failover، پشتیبانی fake-TLS (`ee`) که Telethon ندارد، نشست با DPAPI LocalMachine + ACL. بستهٔ سرور: `E:\Outputs\ShopTG\` + `shoptg/SERVER_GUIDE.md`. **ورود تلگرام و تست زنده هنوز انجام نشده** (فقط روی سرور فروشگاه، توسط کاربر). تست‌ها: shopapi ۲۱۸ ✓، shopbots ۱۱۴ ✓، shopadmin ۴۰۱ ✓، shoptg ۴۷ ✓.

- **جلسهٔ آزمون زنده بعد از فاز ۲ (2026-10-11)؛ جزئیات در `PROGRESS.md`.** بله: `contact.user_id` هست و با `from.id` برابر است ✓؛ **پارامتر start نامطمئن است** (۲ از ۸ بار رسید: `kala_289` و `289`) ← fallback: مشتری کد کالا را می‌فرستد (پیش از ثبت‌نام هم نگه داشته می‌شود). SQL روی `hesab5 t`: گردش KOL ✓، `create_person` + بررسی تکراری ✓ (دادهٔ آزمون پاک شد)، R5 فقط بخش بدون فاکتور (فاکتور با `ordercode` در DB تست نیست ← G3). همهٔ مبالغ **ریال**؛ سقف مبلغ مشتری تأییدنشده حذف شد (فقط سقف تعداد). اسکریپت SQL را فقط از PowerShell معمولی اجرا کنید (پروسه‌های اپ Claude را shared memory رد می‌کند). تست‌ها: shopapi ۱۷۳ ✓، shopbots ۱۰۴ ✓، shopadmin ۳۷۷ ✓.

- **فاز ۲ از `REQUIREMENTS.md` انجام و commit شد (2026-10-11)؛ جزئیات در `PROGRESS.md`.** ثبت‌نام فقط با دکمهٔ اشتراک شماره + تطبیق خودکار R4، ساخت شخص با نام ویرایش‌شده در ShopAdmin، سفارش محدود مشتری تأییدنشده، لینک عمیق `kala_<code>`، رسید عکس/فایل ≤۵MB با ذخیره روی سرور، پیگیری فاکتور/ارسال، گردش حساب از KOL، حالت تعطیل. تست‌ها: shopapi ۱۷۳ ✓، shopbots ۱۰۱ ✓، shopadmin ۳۷۷ ✓. **پارامتر start بله و ستون‌های KOL زنده بررسی نشده‌اند** (توکن تست نیست؛ SQL از این جلسه در دسترس نبود).

- **فاز ۱ از `REQUIREMENTS.md` انجام شد (2026-10-11)؛ جزئیات و کارهای بعدی در `PROGRESS.md`.** تلگرام Bot-API حذف شد (فقط بله)؛ هستهٔ مشترک `shopbots/app/core/`؛ R4/R2/`sp_getapplock`/`Status=0`/`create_person` بدون شخص تکراری. تست‌ها: shopapi ۱۴۵ ✓، shopbots ۸۰ ✓، shopadmin ۳۶۴ ✓. هنوز commit نشده (نقطهٔ بازگشت `6f7eca5`).

- تست‌ها: shopapi ۱۰۹ ✓، shopbots ۷۷ ✓، shopadmin ۳۶۴ ✓ (2026-10-07، بعد از کار تلگرام).
- **کلاینت هرگز سرور را اجرا نمی‌کند** (باگ Sandbox «ShopSystem.exe not found»): `child_process.py`/`jobobject.py` حذف؛ `services/connection.py` فقط `/health` را پروب می‌کند و در قطعی «سرور در دسترس نیست» + نشانی + «تلاش دوباره» نشان می‌دهد. بیلد کلاینت جدا (`build_shopadmin.py --variant client` → `dist/client`، بدون `server_setup`، بررسی خودکار صفر ارجاع به ShopSystem حتی داخل PYZ). باگ `build_installer.bat` (کپی قدیمی اسکریپت بعد از `:fail`) رفع شد.
- **متن سفید روی زمینهٔ روشن** (دکمهٔ «ادامه» و OK دیالوگ‌ها) در سورس از 7bcabe8 رفع شده بود؛ installerهای قبلی قدیمی بودند. `contrast_audit.py` حالا دکمه‌های واقعی رندرشده (ویزاردها، ورود، MessageDialog/ConfirmDialog/QMessageBox روی هر پنجره) را اندازه می‌گیرد: ۹۵/۹۵ AA؛ قاعدهٔ قدیمی را ۱٫۰۶:۱ تشخیص می‌دهد.
- هر دو installer در 2026-10-07 ۱۰:۵۰ از نو ساخته شدند (`ShopAdminSetup.exe` ۳۳MB، `ShopServerSetup.exe` ۵۱MB)؛ ShopSystem/سرور دست نخورد، `ACCOUNTING_WRITE_ENABLED=false`. نصب آزمایشی دوباره در Sandbox لازم است.
- **ثبت در حسابداری:** خاموش (`ACCOUNTING_WRITE_ENABLED=false`)؛ کد وضعیت `6808` در `TabaghehBandi` تأیید نشده — باید DBA در production تأیید کند.
- **نشت `.env`:** راه بسته شد (`build_installer.bat` بعد از کپی، `.env`/`*.db`/`*.log` را از staging پاک می‌کند و اگر چیزی ماند متوقف می‌شود؛ `.iss` هم `Excludes` دارد). `ShopAdminSetup.exe` در 2026-10-07 از نو ساخته شد (نسخهٔ آلودهٔ 2026-10-05 جایگزین شد؛ اگر کپی‌ای از آن جای دیگری هست، دور بریز).
- `.env` کنار `shopsystem/dist/ShopSystem/ShopSystem.exe` (تنظیمات تست توسعه‌دهنده) عمداً آنجا می‌ماند و rebuild حفظش می‌کند؛ فقط نباید وارد installer شود.

#### کارهای پیش رو (backlog)

##### ۰. دستورات جدید کاربر
- [x] (۱)–(۵) در فاز ۱ انجام شد (2026-10-11)؛ (۶) باز است. **(2026-10-10، از `SAZEH_DB_REFERENCE.md` §9/§11) یافته‌هایی که باید در shopapi اصلاح شوند:** (۱) `find_person_by_mobile` روی `name_mo.mobile` کار می‌کند ولی آن ستون در همهٔ ردیف‌ها خالی است ← باید از `DetailTBL` (نوع ۱ و ۳) بخواند؛ (۲) `ACCOUNTING_STATUS_CODE=6808` در `TabaghehBandi` وجود ندارد ← `0` و پس از آزمایش GUI؛ (۳) تولید `Codlp` با `sp_getapplock`؛ (۴) فرمول رزرو با `va=0` و `orderdetailcode`؛ (۵) `create_api_user.sql` را با نسخهٔ حداقل‌دسترسی `research_tools/recipes/grant_shopbot_2008r2.sql` جایگزین کنید (فعلاً SELECT روی `setting`/`TabaghehBandi` می‌دهد که رمز پیامک/یادداشت شخصی دارند)؛ (۶) آزمایش GUI گام‌های G1‑G4 (§10) برای تعیین `Status` واقعی.
- [x] (2026-10-07) ربات تلگرام آمادهٔ production برای «عصر ارتباطات ۲» (بله دست نخورد؛ موتور مشترک است پس متن‌های جدید در بله هم دیده می‌شوند):
  - خوشامد با نام فروشگاه؛ منو: گروه‌ها، جستجو، سبد، سفارش‌های من، پشتیبانی، آدرس/ساعت کاری؛ لیست کالا = نام + قیمت سطح ۱ + «موجود/ناموجود» (بدون تعداد؛ ناموجود قابل سفارش نیست).
  - `/myid` (همه، در هر وضعیت)، `/help`؛ `/start` وسط ثبت‌نام هم از نو شروع می‌کند. مشتری در انتظار تأیید فقط پشتیبانی/آدرس می‌بیند.
  - پس از ثبت سفارش: دستور پرداخت از `messages.fa.json` (شمارهٔ کارت؛ تا وقتی شمارهٔ کارت placeholder است `BANK_ACCOUNT_TEXT` سرور)؛ دکمهٔ «ارسال رسید» در «سفارش‌های من».
  - اعلان فوری به مدیر: سفارش جدید (دکمهٔ وضعیت)، رسید با عکس (تأیید/رد پرداخت)، مشتری جدید (تأیید/رد). تأیید در حالت dry-run صادقانه «در حسابداری ثبت نشد» می‌گوید.
  - تصمیم‌های ShopAdmin از فید `/admin/events` به مشتری خبر داده می‌شود (یک‌بار؛ اجرای اول فقط مکان فعلی را ثبت می‌کند).
  - `TELEGRAM_PROXY` (fallback: `PROXY_URL`) فقط روی کلاینت httpx تلگرام (polling/send/getFile/دانلود)؛ shopapi با `trust_env=False`. قطعی پروکسی: backoff 1→60s، یک خط خطای انگلیسی+فارسی در هر قطعی، «connection restored» در وصل دوباره؛ socksio در venv/بیلد. روی این PC پورت 10808 (xray) هم socks5 و هم http جواب می‌دهد → socks5 انتخاب شد.
  - `scripts/set_telegram_token.ps1` (prompt مخفی، نوشتن درجا در `.env` با حفظ ACL) و `scripts/test_telegram_proxy.ps1` (تشخیص خودکار socks5→http، getMe بدون نمایش توکن؛ توکن از stdin به curl). در بیلد کنار `ShopSystem.exe\scripts\` کپی می‌شوند.
  - `TELEGRAM_PROXY` به تنظیمات قابل ویرایش shopapi (`control.EDITABLE`) و صفحهٔ سرور ShopAdmin اضافه شد.
  - تسک `ShopServer` با حساب `Lenovo` (Password logon) اجرا می‌شود و به 127.0.0.1:10808 دسترسی دارد؛ **ولی xray فقط با ورود کاربر بالا می‌آید** — اگر PC بدون لاگین ریستارت شود، تلگرام تا اجرای xray در حال retry است.
  - [ ] بعد از «token set» کاربر: ری‌استارت تسک، بررسی `app.log`، تست /start، /myid، سفارش آزمایشی.

##### ۱. سروسامان (مرحلهٔ ۱ — انجام شد 2026-10-07)
- [x] git init + `.gitignore` ریشه + commit اولیه.
- [x] فایل‌های `.spec`: نیازی به ویرایش نیست؛ هر بیلد آن‌ها را با مسیر جدید بازمی‌سازد (در git نیستند).
- [x] مسیرهای قدیمی در `shopapi/README.md`, `shopbots/README.md`, `shopsystem/NOTES.md` و `E:\DSH-Workspace\CLAUDE.md`.
- [x] `build_all.bat` (ریشه)؛ `SHOP_NOPAUSE` در `build_installer.bat` برای اجرای زنجیره‌ای.
- [x] دو باگ `build_exe.bat`: (۱) `%OUT%shopapi.db` بدون `\`؛ (۲) نجات `.env`/db/log **بعد** از PyInstaller انجام می‌شد که پوشه را پاک کرده بود ← حالا قبل از آن در `shopsystem/.rebuild_keep/` و در صورت شکست بیلد هم برگردانده می‌شود (تست‌شده).
- [x] `build_all.bat` اجرا شد (2026-10-07 00:24): همهٔ تست‌ها سبز، `ShopAdminSetup.exe` تازه (۴۸MB) بدون `.env`/db/log در staging.
- [ ] **`.env` تست توسعه کنار `shopsystem/dist/ShopSystem/ShopSystem.exe` در همین بیلد اول (باگ ۲) پاک شد.** یک نسخه در سطل بازیافت هست (`shopadmin\.installtest\ShopSystem\.env`)؛ بازگرداندن با تأیید کاربر. تنظیمات اصلی توسعه در `shopapi/.env` سالم است.
- [x] نصب آزمایشی ثبت‌شده در ویندوز (`.installtest`، منوی Start) با uninstaller خودش حذف شد؛ فایل‌های موقت به سطل بازیافت.
- [x] `qt_api` از `shopadmin/pytest.ini` (pytest-qt نصب نیست و تست‌ها از آن استفاده نمی‌کنند).
- [ ] نصب و اجرای آزمایشی `ShopAdminSetup.exe` تازه.
- [ ] (اختیاری) بازسازی venvها در مسیر جدید تا `pip.exe`/`pytest.exe` هم کار کنند.

##### ۲. مرحلهٔ ۲ — معماری نهایی (تصمیم کاربر 2026-10-07)
- **فقط برای فروشگاه خود مالک** (فروشی نیست) → لایسنس/فعال‌سازی لازم نیست.
- **سرور = همان PC سرور حسابداری** (همیشه روشن): `ShopServer` (shopapi + ربات‌ها) به‌صورت سرویس پس‌زمینه با اجرای خودکار هنگام بوت و ری‌استارت خودکار. ربات‌ها فقط اتصال خروجی دارند (بله/تلگرام آپدیت‌ها را تا ~۲۴ ساعت نگه می‌دارند)؛ سایت در آینده از طریق یک relay سمت سرور.
- **همهٔ PCهای دیگر کلاینت‌اند** (ShopAdmin)؛ PC مدیر هم کلاینت است ولی نقش super_admin دارد و سرور را هم کنترل می‌کند (وضعیت، ری‌استارت، تنظیمات، لاگ).
- **نوتیفیکیشن** در کلاینت‌ها: مشتری جدید، سفارش جدید، فیش جدید (tray + اعلان ویندوز + شمارنده).
- **امنیت اولویت اول:** کاربران و نقش‌ها **سمت سرور** (نه SQLite محلی هر PC)؛ ورود با نام کاربری/رمز → توکن نشست؛ کنترل دسترسی در خود API؛ `ADMIN_API_KEY`/`BOT_API_KEY` فقط از loopback (داخل همان سرور) پذیرفته می‌شوند و به کلاینت‌ها داده نمی‌شوند؛ HTTPS در شبکه با گواهی self-signed و pin اثرانگشت در کلاینت؛ فایروال فقط LocalSubnet؛ داده و `.env` سرور در `%ProgramData%` با ACL محدود.
- **رابط کاربری** بازطراحی با گرافیک بهتر (کاربر اجازه داده).

زیرمرحله‌ها:
- [x] 2.1 shopapi: کاربران کارکنان + نشست + نقش سمت سرور + rate-limit ورود + لاگ ممیزی با نام کاربر + فید رویداد (`/admin/events`) + محدودیت loopback کلیدها. ← انجام شد (۸۹ تست؛ `app/staff.py`, `routers/auth.py`, `routers/staff_admin.py`).  **تغییر قرارداد:** کلاینت‌ها دیگر ADMIN_API_KEY ندارند؛ ShopAdmin باید به ورود سمت سرور مهاجرت کند (2.2).
- [x] 2.2 ShopAdmin: ورود سمت سرور، حذف کاربران محلی، اعلان‌ها (tray/toast/badge)، مدیریت کارکنان روی سرور. ← انجام شد (۳۴۰ تست + ۲۲ بررسی زنده با shopapi واقعی و `hesab5 t`):
  - `api_client.py`: Bearer token؛ `X-API-Key` فقط در `bootstrap`. `on_session_invalid` → بازگشت به ورود.
  - `auth.py`: همهٔ تصمیم‌ها با سرور؛ «مرا به خاطر بسپار» = توکن نشست سرور در Credential Manager (fallback با DPAPI، نه فقط obfuscation).
  - `store.py`: جدول‌های `admin_users`/`remembered_sessions` و `shopapi_api_key` قدیمی هنگام باز شدن حذف + VACUUM.
  - `notifications.py`: `EventWatcher` (پولینگ `/admin/events` با کپی توکن) + `TrayNotifier` (tray، اعلان ویندوز، صدا، شمارندهٔ نوار کناری). بستن پنجره = ماندن در tray.
  - عدم فعالیت = قفل (نه خروج): نشست سرور برای اعلان‌ها می‌ماند؛ باز کردن قفل با ورود دوباره و ابطال توکن قبلی.
  - تغییر اجباری گذرواژهٔ موقت (`ui/password_dialog.py`)؛ ویزارد: آدرس سرور → (فقط سرور تازه) bootstrap با کلید سرویس.
  - **مانده:** `scripts/e2e_check.py`, `e2e_app_live.py`, `render_screens.py` هنوز API قدیمی را دارند (همراه 2.5 بازنویسی شوند).
- [x] 2.3 ShopServer: پوشهٔ داده در ProgramData، HTTPS، endpointهای وضعیت/کنترل سرور، وضعیت ربات‌ها. ← انجام شد:
  - `shopsystem/launcher.py`: پوشهٔ داده `%ProgramData%\ShopServer` (یا `--data-dir`)؛ `--service` = سرپرست که `--worker` را با Job Object اجرا و در خرابی/درخواست (کد خروج ۳) دوباره بالا می‌آورد؛ `supervisor.log` جدا؛ `app.log` چرخشی.
  - `shopsystem/server_tls.py`: `API_TLS=true` → گواهی self-signed ECDSA در `tls/` + `fingerprint.txt`؛ ربات‌ها با `SHOPAPI_CA_FILE` pin می‌کنند. `ShopSystem.exe --fingerprint` اثرانگشت را چاپ می‌کند.
  - shopapi `control.py` + `/admin/server/{status,settings,logs,restart}` (فقط super_admin). تنظیمات قابل تغییر از راه دور فقط فهرست سفید (`EDITABLE`)؛ اتصال حسابداری، `ACCOUNTING_WRITE_ENABLED`، کلیدها و `API_HOST` فقط روی خود سرور.
  - shopbots `health.py`: وضعیت هر پلتفرم بدون توکن.
  - ShopAdmin: pin گواهی (`fetch_server_certificate`، `pinned_context`)؛ ویزارد اثرانگشت را نشان می‌دهد و تا تأیید کاربر ادامه نمی‌دهد؛ تغییر آدرس در تنظیمات = ویزارد دوباره؛ صفحهٔ «سرور فروشگاه» (وضعیت، ربات‌ها، اثرانگشت، تنظیمات، گزارش، راه‌اندازی دوباره).
  - آزمون زنده: HTTPS pin‌شده، رد گواهی دیگر/HTTP ساده، restart از API با تنظیمات جدید، مرگ worker همراه سرپرست (۱۸/۱۸).
- [x] 2.4 نصب‌کننده: گزینهٔ «سرور» / «کلاینت»، Scheduled Task، فایروال، ویزارد راه‌اندازی سرور (ساخت `.env` + تست SQL + اولین مدیر)، بستن برنامه هنگام آپدیت، چک ODBC. ← انجام شد (بیلد واقعی: `ShopAdminSetup.exe` ۳۲MB، `ShopServerSetup.exe` ۵۱MB):
  - یک `.iss` با `#ifdef SERVER` → دو نصب‌کننده با AppId جدا. کلاینت: lowest/per-user، بدون سرور. سرور: admin، `{autopf}\ShopServer`، در پایان `ShopAdmin.exe --server-setup`، حذف = برداشتن task و قانون فایروال (پوشهٔ داده می‌ماند). `AppMutex=ShopAdminRunning`؛ توقف task/`taskkill` پیش از ارتقا؛ چک ODBC 17/18.
  - باگ قدیمی رفع شد: `PrepareToInstall` مسیر staging (پوشهٔ بیلد) را روی رایانهٔ مشتری چک می‌کرد → همیشه شکست می‌خورد. حالا چک هنگام کامپایل (`#error`).
  - `ShopSystem.exe --init-config <json>` (کلیدهای تصادفی، گذرواژهٔ DB از فایل JSON داخل پوشهٔ قفل، نه خط فرمان؛ فایل فوراً پاک می‌شود) و `--check-db`.
  - ShopAdmin `--server-setup` (خودکار UAC): `server_setup.py` + `ui/server_setup_wizard.py` — icacls با SID (SYSTEM + Administrators)، task XML (Boot، SYSTEM یا حساب ویندوز با گذرواژه، RestartOnFailure)، فایروال `localsubnet` + `private,domain`، شروع، انتظار HTTPS، pin گواهی از فایل محلی، bootstrap مدیر کل.
  - ShopAdmin: نمونهٔ واحد (QLocalServer؛ اجرای دوباره پنجرهٔ قبلی را نشان می‌دهد) + mutex برای نصب‌کننده. وقتی سرور به‌صورت task نصب است، ShopAdmin هرگز نسخهٔ دوم سرور را اجرا نمی‌کند (فقط `schtasks /Run`).
  - **آزمون نصب واقعی روی ویندوز انجام نشده** (ساخت task/فایروال/پوشهٔ ProgramData روی این رایانه = تغییر سیستمی؛ با اجازهٔ کاربر در 2.6).
- [ ] 2.5 بازطراحی UI. ← شروع شد:
  - [x] `scripts/render_screens.py` با API جدید بازنویسی شد (۱۵ تصویر، شامل صفحهٔ سرور و ویزارد سرور).
  - [x] باگ مهم: دکمه‌های Primary (ورود، ادامه، آزمایش اتصال) در پنجرهٔ ورود و هر دو ویزارد متن سفید روی زمینهٔ روشن داشتند (setStyleSheet بدون selector روی پنجره) → محدود به `QWidget#WindowRoot`.
  - [x] نوار کناری تیره (`SIDEBAR_*` در theme، `nav_icon`، badge زرد) + نمودار سفارش‌های ۷ روز اخیر در داشبورد (`widgets.BarChart`, `orders_per_day`)؛ ۷۳/۷۳ جفت AA، ۳۷۷ تست سبز (2026-10-07).
  - **اول (2026-10-07، مقدم بر بقیهٔ UI):** (۱) ✓ بررسی امنیتی: `shopsystem/dist`، staging و `ShopAdmin` بدون `.env`/`*.db`/لاگ/توکن؛ فقط `.env.example` با مقادیر خالی. محتوای دو installer بدون اجرا قابل بازرسی نیست (فشردهٔ Inno)؛ از روی staging پاک و `Excludes` در `.iss` نتیجه می‌شود. (۲) ✓ `404 persons/match` خطا نیست: قرارداد سرور/کلاینت یکی است و 404 یعنی «مشتری مطابق ندارد» (`match_person` → None)؛ فقط لاگ پرحرف fake server. (۳) ✓ چک‌لیست نصب آزمایشی: `shopadmin/installer/TEST_INSTALL_CHECKLIST.md` (اجرا نشده، منتظر PC/VM تست).
  - [ ] مانده از بازطراحی: صفحهٔ ورود دو ستونه، سایهٔ کارت‌ها.
  - [ ] `scripts/e2e_check.py` و `e2e_app_live.py` هنوز API قدیمی دارند.
  - نکته: `widgets.py:388` (overlay) هم background بدون selector دارد — بررسی شود.
- [ ] 2.6 تست سرتاسری روی نسخهٔ محلی `hesab5 t`.

##### ۲-قدیم. نصب‌کننده (از `shopadmin/CLAUDE.md`)
- [x] exclude کردن `.env`, `app.log`, `*.db` از staging (بیلد مجدد = بند آخر مرحلهٔ ۱).
- [ ] پوشهٔ دادهٔ ShopSystem: launcher آرگومان/متغیر پوشهٔ داده بگیرد (مثلاً `%LOCALAPPDATA%\ShopAdmin\service`) تا نصب در Program Files مشکل مجوز نداشته باشد.
- [ ] ساخت `.env` سرویس هنگام نصب/اجرای اول (کلیدهای تصادفی قوی، DB_SERVER/DB_NAME + تست اتصال، توکن بات‌ها، `ADMIN_CHAT_IDS`, `BANK_ACCOUNT_TEXT`).
- [ ] تمیزکاری `.iss`: حذف CustomMessageهای سرویس ویندوز بی‌استفاده؛ بستن ShopAdmin/ShopSystem در حال اجرا هنگام آپدیت؛ چک پیش‌نیاز ODBC Driver 17/SQL.
- [ ] نصب‌کنندهٔ جدا «فقط کلاینت» و «فقط سرور».
- [x] تضمین بیلد تازهٔ ShopSystem پیش از installer ← `build_all.bat`.

##### ۳. باز از shopapi / shopbots
- [ ] راستی‌آزمایی بله با ربات واقعی (`tapi.bale.ai`، long-poll، inline keyboard، request_contact، getFile، …).
- [ ] کلید ایدمپوتنسی برای `POST /orders`.
- [ ] (اختیاری) اعتبارسنجی platform↔نقش کلید؛ credential هر مشتری برای خواندن پروفایل/سفارش؛ redact دلیل رد در audit_log؛ بازبینی grant `TabaghehBandi`.
- [ ] تست استقرار چندکاره (ShopAdmin روی PC دیگر با آدرس راه دور).
- [ ] اتصال سایت به shopapi (سمت سرور، با `SITE_API_KEY`) — فیچر آینده.
- [ ] پیش از production: کاربر `shopbot` با `sql/create_api_user.sql`، تأیید `6808`، امضای دیجیتال installer.

##### ۴. تصمیم‌های باز (از کاربر پرسیده شده)
- [ ] فقط برای «عصر ارتباطات ۲» یا فروش به فروشگاه‌های دیگر؟
- [ ] یک PC یا سرور + چند کلاینت؟
- [ ] سرویس فقط هم‌زمان با ShopAdmin، یا همیشه روشن (پیشنهاد: Scheduled Task هنگام بوت) تا ربات‌ها ۲۴ ساعته جواب دهند؟


