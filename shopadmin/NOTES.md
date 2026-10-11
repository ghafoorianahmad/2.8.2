# ShopAdmin — Progress Log

Persian desktop admin console for the **shopapi** REST API.
Never touches SQL Server directly. Never touches `shopbots`.

**Status: complete and verified.** 311 tests green, `.exe` and
`ShopAdminSetup.exe` built, full end-to-end run against a live shopapi passed.

---

## 0. Round 2 — the owner's four usability issues (all fixed)

| Issue | Fix | Verified by |
| --- | --- | --- |
| 1. «مرا به خاطر بسپار» did not remember | startup auto-login, tokens that never expire, keyring + obfuscated file fallback | 20 tests + live frozen run |
| 2. ShopSystem.exe had to be started by hand | child-process manager with Job Object, status indicator | 28 tests + **real installed-app run** |
| 3. only a portable folder | Inno Setup installer `ShopAdminSetup.exe` | 33 tests + silent install/uninstall |
| 4. white text on light backgrounds | full palette rework to WCAG AA | 65/65 pairs + Qt regression tests |

### Issue 2 — decision: child process with a Job Object (NOT a Windows Service)

The service route was evaluated first, because a Windows Service keeps running
after ShopAdmin closes, which is genuinely nice when the bots and the website
also need the API.

**It was rejected for this owner**, for three concrete reasons:

1. **It needs admin rights to install.** That means a UAC prompt the owner may
   not be able to answer (staff machines on the LAN, possibly no admin account).
   The child-process route works with zero elevation.
2. **It would keep the accounting API running 24/7 on a single shop PC** with no
   obvious off switch. The owner's mental model is "I close the program, it
   stops." A background service that is still running after everything is closed
   is exactly the kind of invisible state a non-technical user cannot debug.
3. **Debugging is much harder**: service logs live in the Windows Event Log,
   `sc.exe` failure codes are cryptic, and a stuck service blocks reinstalls.
   The child process writes plain `shopapi.log` next to the app.

The one real advantage of a service — surviving a ShopAdmin crash — is solved
differently and more simply: the child is placed in a **Windows Job Object**
created with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
(`app/services/jobobject.py`). When ShopAdmin dies, for any reason including a
hard crash or being killed from Task Manager, Windows itself terminates the
child. No cleanup code has to run, so orphaning is impossible.

Normal shutdown is the graceful path: `terminate()`, wait up to 5 s, then
`kill()`. Only ever the process **we** started — a ShopSystem the owner launched
by hand is never touched (covered by a test).

Behaviour summary:
* remote address (anything not 127.0.0.1 / localhost / ::1) → never launches
  anything, just connects over HTTP;
* local address + already answering → nothing is started;
* local address + nothing answering → start `ShopSystem.exe` with
  `CREATE_NO_WINDOW`, stdout/stderr appended to `shopapi.log` in the data folder,
  then poll `/health` until ready (12 s budget);
* missing executable → the required Persian message is shown and the app keeps
  working read-only;
* top bar always shows «سرویس فروشگاه: متصل / در حال راه‌اندازی / قطع / راه دور»
  with a colour dot, plus a «راه‌اندازی» retry button when it is off.

The service is started by the **controller**, before the login window, so the
first data request already succeeds — and it is stopped from
`QApplication.aboutToQuit`, so it is cleaned up however the app exits.

### Issue 4 — contrast audit (WCAG AA)

`scripts/contrast_audit.py` reads the LIVE theme constants (not a copy) and
checks every foreground/background pair the UI renders, plus every literal
colour inside the stylesheet and the non-text indicators.

Before: **11 of 48 pairs failed**. After: **65 of 65 pass.**

| What | Before | After | Fix |
| --- | --- | --- | --- |
| wizard confirm button (white on green) | **3.77:1 ✗** | **5.48:1 ✓** | `SUCCESS` #059669 → #047857 |
| primary button, disabled | **1.42:1 ✗** | **4.97:1 ✓** | white-on-light-blue → dark grey on light grey |
| success button, disabled | **1.28:1 ✗** | **4.97:1 ✓** | same |
| danger button, disabled | **1.45:1 ✗** | **4.97:1 ✓** | same |
| default button, disabled | **2.45:1 ✗** | **4.97:1 ✓** | `TEXT_FAINT` #94A3B8 → #5B6B7F |
| placeholder text | **2.56:1 ✗** | **5.30:1 ✓** | `TEXT_FAINT` darkened |
| secondary text on white | 4.76:1 (barely) | **7.48:1 ✓** | `TEXT_MUTED` #64748B → #475569 |
| dialog detail text | **4.47:1 ✗** | **7.25:1 ✓** | follows `TEXT_MUTED` |
| operator role badge | **3.29:1 ✗** | **6.49:1 ✓** | new `INFO_DARK` #155E75 |
| viewer role badge | **4.47:1 ✗** | **7.48:1 ✓** | follows `TEXT_MUTED` |
| "expired" order pill | **4.39:1 ✗** | **6.68:1 ✓** | #6B7280 → #4B5563 |
| checkbox/radio glyphs | invisible (no glyph at all) | **6.70:1 ✓** | inline SVG data-URI check and dot |

Also fixed: checked `QCheckBox`/`QRadioButton` previously rendered a plain blue
square with **no visible mark**, so the user could not tell whether «مرا به خاطر
بسپار» was ticked. Both now draw a real glyph.

Only one theme remains (light). `theme.apply_theme` is the single entry point;
there is no dark variant to test, which is stated here rather than implied.

Regression tests in `tests/test_ui.py` resolve the actual stylesheet rule that
governs the wizard's step-2 primary button and assert both that the text and
background differ and that the ratio is ≥ 4.5, plus a test that the whole
palette audit stays green.

### Issue 3 — installer

`installer/ShopAdmin.iss` + `build_installer.bat` → `dist/installer/ShopAdminSetup.exe`.

* installs to `{autopf}\ShopAdmin` (i.e. `%ProgramFiles%\ShopAdmin` for an
  all-users install, or `%LOCALAPPDATA%\Programs\ShopAdmin` for per-user);
* `PrivilegesRequired=lowest` + `PrivilegesRequiredOverridesAllowed=dialog`
  → **per-user by default**, per-machine offered on the wizard page;
* copies the ShopSystem service build into `{app}\ShopSystem`, which is exactly
  where the child-process manager looks for it;
* Desktop shortcut and Start Menu entry both named «مدیریت فروشگاه»;
* Start Menu also gets «راهنمای نصب» and «حذف مدیریت فروشگاه»;
* uninstall entry in Add/Remove Programs;
* optional «مطالعهٔ راهنمای نصب پس از نصب» task that opens the readme;
* optional task to launch the app;
* the uninstaller deliberately does **not** delete `%LOCALAPPDATA%\ShopAdmin`,
  so a reinstall keeps settings and users (asserted by a test);
* `build_installer.bat` runs PyInstaller, stages both applications, then calls
  `iscc.exe`; if Inno Setup is missing it prints
  https://jrsoftware.org/isdl.php and `winget install JRSoftware.InnoSetup`,
  then fails loudly instead of continuing.

---

## 1. Environment (verified)

- Python **3.12.10**; project venv at `shopadmin/.venv`.
- PySide6 **6.10.3** (`PySide6-Essentials` + `shiboken6`; the Addons package is
  not imported and is deliberately not installed).
- shopapi inspected **read-only**: `app/routers/public.py`,
  `app/routers/admin.py`, `app/schemas.py`, `app/config.py`, `app/security.py`,
  `app/db_own.py`, `tests/conftest.py`.
- `shopapi/.env` → `ACCOUNTING_WRITE_ENABLED=false`, so the yellow dry-run
  banner must be visible against this server. Confirmed live.

### Network note (build environment only)
`files.pythonhosted.org` resets TLS connections from this machine, and pip's
downloads stalled. `scripts/fetch_wheels.py` downloads the PySide6 wheels from a
PyPI mirror with resumable `curl` calls and installs them locally with
`--no-index`. This affects only how the *build* environment was prepared; the
shipped application has no such dependency.

---

## 2. shopapi API facts the client depends on

| Purpose | Call |
| --- | --- |
| health | `GET /health` (no key) |
| customers | `GET /admin/users?status=pending\|approved\|rejected` |
| customer match | `GET /admin/persons/match?mobile=...` |
| approve customer | `POST /admin/users/{id}/approve` `{person_code}` |
| reject customer | `POST /admin/users/{id}/reject` `{reason?}` |
| orders | `GET /admin/orders?status=<status>` |
| approve payment | `POST /admin/orders/{id}/approve-payment` |
| reject payment | `POST /admin/orders/{id}/reject-payment` |
| products | `GET /products?q=&group=&in_stock=&page=&page_size=` |
| groups | `GET /groups` |
| system info | `GET /admin/system-info` **(added by this project)** |

Auth: header `X-API-Key: <ADMIN_API_KEY>`.
Errors arrive as `{"detail": ...}`; `detail` may be a **string**
(`HTTPException`) *or* a **list** of pydantic errors (422). Both are handled and
turned into Persian sentences — no English from the server is shown to the user.

Two shopapi behaviours worth remembering:
1. `GET /admin/orders` defaults `status` to `receipt_uploaded`, so the client
   always sends an explicit status.
2. `POST /admin/orders/{id}/approve-payment` answers **200 even in dry-run mode**
   without committing. The client therefore checks the returned status is
   `written` before claiming success, and says so clearly when it is not.

---

## 3. Change made to shopapi (no business logic touched)

`GET /admin/system-info` — a new **read-only** endpoint in
`app/routers/admin.py`. It returns operational flags the desktop app needs and
nothing secret:

```
accounting_write_enabled, write_allowed_on_host, price_level_bot,
price_level_site, reserve_hours, max_order_qty, allow_shared_person_code,
bank_account_text
```

Why it was needed: the required yellow banner depends on
`ACCOUNTING_WRITE_ENABLED`, which is a server-side setting that no existing
endpoint exposed. It reads `Settings` only — no writes, no schema changes, no
alteration to any existing route. Covered by two new tests in
`tests/test_review_fixes.py`; the full shopapi suite is **55 passed**.

---

## 4. Design decisions

- **Internal users vs customers are kept strictly apart.**
  *Internal admin users* live in the app's own SQLite (`admin_users`) and are
  managed on the «کاربران سیستم» page, Super Admin only.
  *Customers* live in shopapi and are only ever read over HTTP; the «مشتریان»
  page manages them. The two never share a table, a model or a screen.
- **Local data** at `%LOCALAPPDATA%\ShopAdmin` (`shopadmin.db`, `app.log`), so a
  read-only install directory still works. Override with `SHOPADMIN_DATA_DIR`.
- **Passwords** → bcrypt (12 rounds). Never stored or logged in clear text.
- **«مرا به خاطر بسپار»** stores a random **session token**, never the password.
  The token goes to the OS keyring when available (SHA-256 hash kept locally,
  7-day expiry), with a masked local fallback otherwise.
- **Login lockout** after 5 failed attempts for 15 minutes.
- **Persian digits + Shamsi dates** everywhere, via `app/persian.py`
  (dependency-free Jalali conversion, verified against 11 known date anchors and
  a 20 000-day round-trip).
- **Money** in ریال (same unit as the accounting software) with the Persian thousands separator `٬`.
- **Async**: every HTTP call runs on a `QThreadPool` worker so the window never
  freezes; a spinner/busy overlay is shown while waiting.
- **Five shopapi statuses are never invented**: statuses and their Persian
  labels live in `app/statuses.py` and match the schema CHECK constraint exactly.

---

## 5. Two non-obvious bugs found and fixed (worth knowing)

1. **PySide6 does not keep a `QRunnable` alive** handed to
   `QThreadPool.start()`. Without a strong reference the worker — and with it its
   signal object and every callback — was garbage-collected before the background
   call finished, so pages silently stayed on the loading spinner forever.
   Fixed with the `_ACTIVE_WORKERS` registry in `app/ui/async_utils.py`.
   Related: PySide6 also holds only a **weak** reference to a plain-function
   slot, so the guarded callback wrappers are kept alive on the worker itself.

2. **An exception inside a queued Qt slot does not raise in Python.** Qt prints
   it and *disconnects the slot*, so one bug would silently break every later UI
   update. Every callback is now routed through `_guard(...)`, which logs and
   continues. This immediately surfaced a wrong relative import
   (`from ..persian` inside `app/ui/pages/`, which is `app.ui.persian`) that had
   been silently breaking the dashboard.

A third, caught earlier: `theme.STYLESHEET` called `QFontDatabase` at **import
time**, which aborts the process before a `QApplication` exists. Font resolution
is now lazy (inside `apply_theme`).

Regression tests for all three live in `tests/test_ui.py`.

---

## 6. Verification performed

### Unit / integration tests — 226 passed
```
226 passed in ~60s
```
Covers: Persian digits and Jalali dates, local store, auth (correct/incorrect
password, lockout, disabled user, first-super-admin bootstrap, last-super-admin
protection), role permissions, the HTTP client against a mocked shopapi
(including error translation and auth failures), reporting/CSV/XLSX export, and
the UI (RTL, Persian-only strings, role gating, the wizard, the login window,
the dry-run banner, and a "every page loads without a callback error" guard).

No test touches the network. No test needs a database server.

### Live shopapi integration
```
9 passed, 0 failed, 2 skipped
```
against a running `uvicorn` instance: `/health`, `/admin/system-info`
(dry-run correctly reported), customers + status filters, all 7 order statuses,
**557 products**, 10 groups, and a wrong API key correctly rejected with 401.

### Full application against the live server
```
[ok] fresh install requires the setup wizard
[ok] wizard test-connection: ارتباط با موفقیت برقرار شد. کلید مدیریت معتبر است.
[ok] wizard warns about dry-run mode
[ok] wizard created the super admin and saved the settings
[ok] login as owner (super_admin)
[ok] connection status dot: connected
[ok] yellow dry-run banner is visible
[ok] dashboard cards — products='۵۵۷'
[ok] products page loaded 50 row(s); first='گلس انتي استاتيک'
[ok] settings reports: ... ثبت در حسابداری: غیرفعال (حالت آزمایشی — بدون ثبت واقعی)
E2E against the live shopapi: ALL CHECKS PASSED
```

### Packaged executable
`build_shopadmin.py --clean` → `dist/ShopAdmin/ShopAdmin.exe` (**98 MB folder**,
176 files, Vazirmatn fonts bundled). Launched with a clean data directory in a
*frozen* build; the log confirms:

```
Python 3.12.10, frozen=True
first run detected; showing the setup wizard
```
and it created `shopadmin.db` with all 6 tables and the default settings — i.e.
it runs on a machine with no Python installed.

### Visual review
`scripts/render_screens.py` renders all 13 screens to `docs/screens/` with the
real widgets against fake data; each was inspected for layout, RTL correctness,
Persian text and the absence of English.

---

## 7. How to run

```powershell
# tests
.venv\Scripts\python.exe -m pytest tests -q

# run from source
.venv\Scripts\python.exe run_shopadmin.py

# build the executable  (or just double-click build_shopadmin.bat)
.venv\Scripts\python.exe build_shopadmin.py --clean

# regenerate screenshots / icons
.venv\Scripts\python.exe scripts\render_screens.py
.venv\Scripts\python.exe scripts\make_icon.py

# verification helpers (need a running shopapi)
.venv\Scripts\python.exe scripts\e2e_check.py
.venv\Scripts\python.exe scripts\e2e_app_live.py
```

---

## 8. Work order (plan)

1. ✅ Recon shopapi API surface + environment
2. ✅ Add read-only `/admin/system-info` to shopapi + tests (55 passed)
3. ✅ Core: paths, logging with masking, Persian digits + Shamsi dates, statuses, permissions
4. ✅ Local SQLite store + bcrypt auth + lockout + remember-me tokens
5. ✅ shopapi HTTP client with Persian error mapping
6. ✅ Theme, RTL, Vazirmatn font, icons, table/toast/dialog widgets
7. ✅ First-run wizard, login window, session timeout, logout
8. ✅ Main window: right sidebar, top bar, status dot, dry-run banner
9. ✅ All 7 pages
10. ✅ Pytest suite green (226)
11. ✅ `build_shopadmin.bat` + PyInstaller → `dist/ShopAdmin/ShopAdmin.exe`, smoke-tested
12. ✅ `README.txt` (Persian), `.env.example`, `.gitignore`
13. ✅ Live end-to-end acceptance + screenshots + this log

## 9. Deliberate scope choices

- **CSV + XLSX export only** (no PDF): no extra dependency, and both open
  correctly in Excel with Persian text (UTF-8 BOM for CSV, RTL sheets for XLSX).
- **No `QtWebEngine`/Addons**: nothing in the app needs them, and leaving them out
  keeps the bundle at 98 MB instead of several hundred.
- **Receipt image is not fetched**: shopapi exposes only `receipt_ref` (a text
  reference) on `OrderOut`, so the dialog shows that reference. No shopapi change
  was invented for it.
- **Product images** are loaded over HTTP from the shopapi URL when present.
