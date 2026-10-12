# PROGRESS — Asre Ertebatat 2 store system

Phases are defined in `REQUIREMENTS.md` §14. One phase per session.

## Phase 6 — website: static showcase, model slugs, ArvanCloud guide (2026-10-12) — DONE; not deployed

Site = `E:\DSH-Workspace\projects\asr-ertebatat-shop` (plain HTML/JS, its own git repo; commit `1524dc1`). The Next.js folder `E:\projects\mobile-shop` is an unused Sep-17 prototype (cart, API routes, admin), and `projects\asr-ertebatat-2-redesign` is an alternative plain-HTML design that did **not** get these changes.

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
- `E:\Outputs\StoreWebsite\StoreWebsite_2026-10-12.zip`: 179 files, SHA-256 `0EA37F04…7F85C0`. Next to it: `DEPLOY_ARVAN_FA.md` and the README. The previous 2026-10-08 zip is kept.

### Pending / for the user
1. Deploy to ArvanCloud per `DEPLOY_ARVAN_FA.md` (account + 2FA, IRNIC access; copy the email DNS records from Cloudflare first).
2. Until Phase 6b, the bot opens at the main menu for `m_<slug>` and pasted text (never a wrong product). Deploying before 6b is safe.
3. Decide which site goes live: main vs `asr-ertebatat-2-redesign`. If the redesign, port the Phase 6 changes there.
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
