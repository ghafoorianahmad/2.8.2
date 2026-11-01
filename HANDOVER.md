# HANDOVER — «عصر ارتباطات ۲» shop system (for the next AI agent)

Written 2026-11-01 at version **2.16.0** (unattended session, no admin rights, nothing pushed,
nothing published, nothing installed). Persian, simple version for the owner: `HANDOVER_FA.md`.

Read in this order before touching anything:
1. this file;
2. `CLAUDE.md` (this folder) — the living status + backlog ("وضعیت", "کارهای باز"); update it after
   every important step;
3. `E:\DSH-Workspace\CLAUDE.md` — workspace rules (they override defaults);
4. `PROGRESS.md` / `PROGRESS_SITE.md` — step logs per version (newest on top), `REQUIREMENTS.md` —
   decisions (§7a…§7j), `SECURITY.md`, `DEPLOY_CHECKLIST.md`, `SAZEH_DB_REFERENCE.md` (accounting DB).
5. In a Linux cloud session: `CLOUD.md` first (no SQL, no Windows builds, own branch only).

---

## 1. What this is

A chatbot-driven phone shop on top of the accounting program «سازه حساب» (SQL Server). Customers
browse a static website, order through a Bale / Telegram bot, staff work in a Windows desktop console,
and confirmed orders are written into the accounting database.

```
website (static, GitHub → ArvanCloud) ──link ?start=m_<model>──► Bale / Telegram bot ─┐
ShopAdmin.exe (staff PCs) ─────── HTTPS + staff session ──────────────────────────────┼──► shopapi ──pyodbc──► SQL Server «سازه حساب»
Telegram reader (inside ShopSystem.exe) ── /worker/* + WORKER_API_KEY ───────────────┘       └─ shopapi.db (SQLite)
ShopAdmin «سایت» ── GitHub API commit (owner's token) ──► website repo (catalog.json + site.json)
```

## 2. Components and where they live

All under `E:\DSH-Workspace\Software Asr\` (one git repo, branch **`feature/order-flow-v250`** =
the real line of work; `main` is old). Each package has its own `.venv` and `.env`.

| Folder | What | Notes |
| --- | --- | --- |
| `shopapi/` | FastAPI. The ONLY part that talks to SQL Server. Reads items / stock / prices (read-only), keeps customers, orders, requests, price lists, proxies in its own SQLite, writes confirmed orders into `KalaOrder` (dry-run + ROLLBACK unless the owner enables real writes per database). | `app/accounting_reader.py`, `accounting_writer.py`, `routers/{public,admin}.py`, `app/pricelist/`, `selfheal.py`, `control.py` (VERSION) |
| `shopbots/` | Bale bot (long polling) + Telegram adapter; shared engine `app/core/`; texts `messages.fa.json`. HTTP to shopapi only. | |
| `shopadmin/` | PySide6 console (Persian, RTL, Jalali). Pages: dashboard, customers, orders, products, item requests, price list, site models, **«سایت»** (site editor), reports, server, users, health. Installers (Inno Setup). | `app/ui/`, `app/site/` (site editor logic, no Qt), `app/paths.py` (APP_VERSION), `installer/ShopAdmin.iss` (MyAppVersion), `scripts/` (audits, screenshots) |
| `shoptg/` | Telegram reader (Telethon, read-only): price-list PDFs from @AbrishamiiPhoneMashhad, other price channels, MTProto proxy pool. Runs inside `ShopSystem.exe --tg-worker`. | |
| `shopsystem/` | `launcher.py` → `ShopSystem.exe` (PyInstaller): API + bots + reader as Windows service `ShopServer`; backups; `deploy/*.ps1`. | `build_src/` is generated — never edit |
| `shared/` | `shop-tgproxy` package (MTProto proxy helpers). | |

**Website** (separate repo): `E:\DSH-Workspace\asr-site-live`, branch `main`, remote GitHub
`asr-ertebatat-2` = the live site asrertebatat2.ir (`origin/main`). Push is disabled there on purpose.
Plain HTML/CSS/JS: `index.html`, `apple/samsung/xiaomi.html`, `about/contact/404.html`,
`assets/site.js` (all logic), `assets/site.css` + `assets/theme.css`, `assets/products.js`
(built-in catalogue, the fallback), `assets/catalog/` (written only by ShopAdmin «انتشار»:
`catalog.json` = phones + accessories, `site.json` = look/texts/links). Local commits on top of
`origin/main` are **not pushed** (see §5).

**Data on this PC**: ShopAdmin `%LOCALAPPDATA%\ShopAdmin\` (`shopadmin.db`, `site\site_data.json`
+ `site\photos\` = the site editor's working data). Server data (installed service) `D:\ShopServerData`
or `C:\ProgramData\ShopServer`. **Outputs**: `E:\Outputs\ShopSystem\` (only the newest installer pair
+ `README_FA.txt` + `PRODUCTION_GUIDE_FA.txt`).

## 3. Key rules (non-negotiable)

1. **Database safety.** Never work on the production accounting DB. While YOU test, write test data
   only to the local copy **`hesab5 t`** on `.\SQLEXPRESS` (name has a space → `[hesab5 t]`). The
   program itself must keep supporting real writes to any DB the admin enables (per-DB list
   `ACCOUNTING_WRITE_DATABASES` + allow-list, set by the owner in «تنظیمات سرور»). No schema changes
   in the accounting DB; parameterised SQL only. Do not read/print personal data (`name_mo`, `kol`,
   `chek*`, `checkque*`, `Telegram_*` rows).
2. **Secrets.** Never read or print `.env`, `*.db`, `dsh/.credentials.yaml`, tokens or keys; never
   commit them. Values come from env only.
3. **No prices on the website.** Ever. `catalog.price_problems` blocks a publish that contains
   «تومان/ریال/قیمت» or any number from a price column of an imported PDF. Prices only come from the bot.
4. **Site look rule (2.16).** The look, layout and structure of the LIVE site (`origin/main`) stay
   exactly as they are. Only allowed: what makes the site editable from ShopAdmin (catalog/look data
   loading; adding/editing/hiding/deleting phones and accessories *inside the existing design*) and the
   2.10 functional fixes (broken buttons/links, `?start=m_<code>` bot links). Any new content must use
   existing markup/classes. Prove it with `shopadmin/scripts/site_compare.py compare` (real Edge,
   pixel-by-pixel vs `origin/main`, every page, desktop + phone, dark + light) — it must say SAME.
5. **Never `git push`** (either repo) and never publish the site unless the owner asks in that very
   message. Releases = local commits only. Never use the owner's GitHub token to write to the real repo.
6. Do not edit `backups/`, `dist/`, `build/`, `build_src/`, `*.bak-*`. Keep UTF-8; user texts are Persian.
7. No admin rights in unattended sessions: do not try to install, start/stop the service, or change
   system settings.

## 4. Build, test, release

PowerShell, inside each package (see `CLAUDE.md` "اجرا و تست"):

```powershell
.\.venv\Scripts\python.exe -m pytest -q                 # shopapi, shopbots, shoptg
$env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest tests -q   # shopadmin, shopsystem
```
Quirks on this PC: pass `-p no:cacheprovider --basetemp <writable dir>`; shopapi/shopadmin need a
basetemp inside the package (`.pytest_tmp\x`); shopsystem's deploy test needs `TEMP`/`TMP` pointing to
a deletable folder (build_all does that: `%TEMP%\ShopBuild\tmp_*`). Always `python -m <tool>`.

Quality gate for ShopAdmin UI (must be **0** in all 9 looks): `scripts/text_fit_audit.py`,
`scripts/rtl_audit.py`, `scripts/button_audit.py` (every screen/dialog is listed in
`scripts/audit_screens.py` — add new dialogs there). Contrast: `scripts/contrast_audit.py --all`.

Release steps (see `CLAUDE.md` "پوشهٔ خروجی"):
1. all suites green + three audits 0;
2. bump version in `shopadmin/app/paths.py` (APP_VERSION), `shopadmin/installer/ShopAdmin.iss`
   (MyAppVersion), `shopapi/app/control.py` (VERSION) and the version asserts in
   `shopadmin/tests/test_v260.py`, `shopapi/tests/test_v240.py`, `test_v260.py`;
3. local commit (no push);
4. `$env:SHOP_NOPAUSE="1"; cmd /c '"E:\DSH-Workspace\Software Asr\build_all.bat"'` (full path!) →
   `shopadmin\dist\installer\ShopServerSetup.exe` + `ShopAdminSetup.exe`;
5. check ProductVersion of both; COPY (never move) to `E:\Outputs\ShopSystem\` as
   `ShopServerSetup_<ver>_<date>.exe` / `ShopAdminSetup_<ver>_<date>.exe`, verify SHA-256, then delete
   older pairs there; update `E:\Outputs\ShopSystem\README_FA.txt` and the ShopSystem row of
   `E:\Outputs\README_FA.txt`. Never copy `.env` / `*.db` / `*.log`.

Website checks: `shopadmin/scripts/site_compare.py compare E:\DSH-Workspace\asr-site-live <out>`
(add `--local <ShopAdmin preview folder>` to compare the site built with real ShopAdmin data);
`site_compare.py shot <folder> <png> index.html --js "<click script>"` for interactive states.
ShopAdmin real-app screenshots: `scripts/live_shot.py`, `scripts/live_farsi.py`.

## 5. Status at 2.16.0 — done

* Phases 1–7, order flow, price lists from Telegram, proxy pool, multi-channel prices, health page,
  staff roles, backups, installers: in code and tested with fakes (see `PROGRESS.md`).
* Site editor in ShopAdmin («سایت»): tree of phones/accessories, PDF import (table PDFs, one row = one
  item + its photo), duplicate detection, bulk tick/hide/show/delete (48 h undo), look & layout tab,
  browser preview, publish via GitHub API + 48 h rollback (tested only against a fake GitHub).
* **2.16.0 (this session):**
  1. Site = live site: 28/28 screenshots identical to `origin/main` (phone menu and the A57 photo
     reverted to live; site.json no longer overwrites each page's own wording with ShopAdmin defaults).
  2. Accessories: the live site's four category cards unchanged; a card with items opens its items
     (brand filter) only after a click; empty categories keep «به‌زودی تکمیل می‌شود»; the manager's new
     categories become new cards in the same markup.
  3. «فارسی‌سازی توضیحات» (`shopadmin/app/site/farsi.py`): codes/barcodes/«|» noise removed, offline
     Persian dictionary (305 built-in words + the manager's own in `site_data.json › fa_words`) on every
     PDF import; buttons «فارسی‌سازی توضیحات», «واژه‌نامه…», «برگرداندن فارسی‌سازی» (48 h). Applied once
     to this PC's 35 power banks (34 changed; backup `%LOCALAPPDATA%\ShopAdmin\site_before_farsi_2.16.0.zip`).
  Screenshots: `shopadmin/docs/screens_2.16.0/` (`site/`, `farsi/`).

## 6. Pending (owner or next agent)

See `CLAUDE.md` "کارهای باز" for the full list. Most important:
* Install 2.13 → 2.16 builds on this PC (owner, admin rights) and test the listed items; nothing
  since 2.9.x has been verified on an installed build.
* Website: the owner must push the local commits of `asr-site-live` (2.10–2.16 site code: catalog.json /
  site.json reader, accessory cards, bot links), give a fine-grained GitHub token, and do one test
  publish. Verify the Bale `start` parameter (`m_<code>`) on the real bot.
* Live tests on `hesab5 t` + real Bale (order write, `create_person`, applock); GUI tests G1–G4 for the
  real `Status` code (`ACCOUNTING_STATUS_CODE`); DBA approval before production; `grant_shop_app.ps1`.
* Production server per `E:\Outputs\ShopSystem\PRODUCTION_GUIDE_FA.txt`.
* Accessory photos/PDFs: real accessory PDFs of other categories; missing phone photos
  (`xiaomi-17-pro`, `redmi-15`, `redmi-14c`), the owner's decision on manufacturer photos.
* Installer code signing; site ↔ shopapi live connection (future, server side only).

## 7. Known issues

* `shopsystem/tests/test_deploy.py::test_update_from_zip_and_keeps_three_backups` fails when `TEMP`
  is a folder the sandbox cannot delete in (passes with build_all's TEMP).
* Linux: `test_sidebar_badges_and_close_to_tray`, shoptg tests need `pdfplumber`.
* PDF text from suppliers is sometimes garbled (glyph order, words cut by line breaks); the cleaner
  fixes the common cases only — check items after an import, edit by hand when needed, add words to
  «واژه‌نامه…».
* Long Latin names like «Type-C» may wrap at the hyphen in the site's spec table (the site's own CSS;
  not changed because of the look rule).
* `galaxy-a57.jpg` on the live site has a black box; fix it as data (a new photo in ShopAdmin), not in
  the site code.

## 8. Where to start

1. `git -C "E:\DSH-Workspace\Software Asr" status` and `git -C E:\DSH-Workspace\asr-site-live status`
   (both should be clean apart from untracked samples/screens); read `CLAUDE.md`.
2. Ask the owner which pending item comes next (§6); when unattended, pick from "کارهای باز".
3. For any site change: change → `site_compare.py compare` → must stay SAME (except intended data).
4. For any ShopAdmin UI change: tests + three audits in 9 looks + a real screenshot.
5. After every step: update `PROGRESS*.md` / `CLAUDE.md`, local commit, never push.
