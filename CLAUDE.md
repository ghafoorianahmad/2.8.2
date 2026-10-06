# CLAUDE.md — Software Asr (فروشگاه چت‌بات‌محور «عصر ارتباطات ۲»)

این پوشه هستهٔ نرم‌افزاری ارتباط **ربات‌ها ↔ نرم‌افزار حسابداری «سازه حساب»** و کنسول مدیریت فروشگاه است.
قواعد کلی workspace در `E:\DSH-Workspace\CLAUDE.md` معتبر است (production ممنوع، `.env`/`*.db`/توکن نخوان و چاپ نکن، SQL فقط پارامتری، بدون تغییر اسکیمای حسابداری، `backups/ dist/ build/ *.bak-*` را ویرایش نکن، متن‌ها فارسی UTF-8).

> **قاعدهٔ جلسه:** اول این فایل را بخوان، با وضعیت واقعی پوشه تطبیق بده و بعد از هر کار مهم بخش «وضعیت» و «کارهای پیش رو» را به‌روز کن.

## اجزا (هرکدام venv و `.env` جدا)

| پوشه | چیست | وضعیت |
| --- | --- | --- |
| `shopapi/` | FastAPI؛ تنها جزئی که به SQL Server وصل می‌شود. کالا/گروه/موجودی/قیمت از حسابداری (فقط‌خواندنی)، مشتری/سفارش/رزرو در SQLite خودش، ثبت سفارش تأییدشده در `KalaOrder/KalaOrderDetail` (پیش‌فرض dry-run + ROLLBACK). کلیدها: `BOT_API_KEY`, `SITE_API_KEY`, `ADMIN_API_KEY` (هدر `X-API-Key`). | کامل؛ ۵۵ تست سبز؛ روی `hesab5 t` زنده تست شده |
| `shopbots/` | ربات بله + تلگرام (long-polling، httpx خام، موتور گفتگوی مشترک). فقط HTTP به shopapi. ادمین‌ها از `ADMIN_CHAT_IDS` تأیید مشتری/فیش را داخل چت انجام می‌دهند. تلگرام با `PROXY_URL`. | کامل؛ ۴۸ تست سبز؛ **بله با ربات واقعی راستی‌آزمایی نشده** |
| `shopadmin/` | کنسول دسکتاپ PySide6 (فارسی، RTL، شمسی): داشبورد، مشتریان، سفارش‌ها، محصولات، گزارش CSV/XLSX، تنظیمات، کاربران داخلی. ShopSystem.exe را به‌صورت child process (Job Object) بالا می‌آورد. + نصب‌کنندهٔ Inno Setup. | برنامه کامل (۳۲۳ تست سبز)؛ **نصب‌کننده نیمه‌کاره** |
| `shopsystem/` | `launcher.py` → `ShopSystem.exe` (PyInstaller): API + بات‌ها در یک پروسه. پکیج‌های `app` در بیلد به `shopapi_app`/`shopbots_app` تغییر نام می‌دهند. `.env`، `shopapi.db`، `shopbots.db`، `app.log` کنار exe. | بیلد و تست‌شده با دادهٔ واقعی |

**سایت** خارج از این پوشه است: `E:\DSH-Workspace\projects\asr-ertebatat-shop` (HTML ثابت، CLAUDE.md خودش را دارد). فعلاً به shopapi وصل نیست و فقط لینک ربات (`asrertebatat2_bot`) می‌دهد؛ اتصال آینده فقط سمت سرور و بدون کلید در کد مرورگر.

```
سایت (ثابت) ──لینک──► ربات بله/تلگرام ──HTTP+BOT_API_KEY──┐
ShopAdmin.exe ─────────────HTTP+ADMIN_API_KEY─────────────┼──► shopapi ──pyodbc──► SQL Server «سازه حساب»
(SITE_API_KEY آماده، بدون مصرف‌کننده)                      ┘      └─ shopapi.db (SQLite)
```

استقرار: PC سرور (کنار SQL Server) = `ShopSystem.exe` + ODBC Driver 17؛ PCهای کارمندان = فقط `ShopAdmin.exe` با آدرس راه دور (استقرار چندکاره هنوز عملاً تست نشده).

## مستندات مرجع
- `shopapi/README.md` (مدل ایمنی، endpointها، رفتن به production)، `shopapi/NOTES.md` (واقعیت‌های اسکیما: قیمت‌ها `Gey/Geycf/gey3/gey4/gey5`، موجودی `SUM(Megv)-SUM(Megs)` از `kardex_an`، فقط سطح ۱ در نسخهٔ تست کاتالوگ واقعی دارد ← `PRICE_LEVEL_*=1`)، `shopapi/REVIEW.md` (بازبینی امنیتی).
- `shopbots/README.md`, `shopbots/NOTES.md` (۱۰ سؤال باز دربارهٔ تفاوت‌های بله).
- `shopadmin/CLAUDE.md` (وضعیت نصب‌کننده با جزئیات)، `shopadmin/NOTES.md`, `shopadmin/README.txt` (راهنمای کاربر)، `shopadmin/installer/`.
- `shopsystem/NOTES.md`, `shopsystem/README.txt`.

## اجرا و تست (PowerShell، داخل پوشهٔ هر جزء)
```powershell
.\.venv\Scripts\python.exe -m pytest -q          # shopapi, shopbots
.\.venv\Scripts\python.exe -m pytest tests -q    # shopadmin (برای اجرای بی‌پنجره: $env:QT_QPA_PLATFORM='offscreen')
.\run.ps1 [-Port 8100 -Reload]                   # shopapi / shopbots
.\check.ps1 ; .\.venv\Scripts\python.exe scripts\selfcheck.py   # shopapi، فقط‌خواندنی
build_all.bat        # (ریشه) بیلد کامل به ترتیب درست: ShopSystem → تست shopadmin → ShopAdmin + installer
```
همیشه `python -m <tool>` بزن، نه `pytest.exe`/`uvicorn.exe`: exeهای داخل `.venv\Scripts` هنوز مسیر قدیمی (`E:\DSH-Workspace\<proj>`) را دارند. خود `python.exe` و `python -m pip` سالم‌اند.

## git
ریپوی محلی در همین پوشه (branch `main`، از 2026-10-07). `.gitignore` ریشه `.env`، `*.db`، `*.log`، `.venv`، `build/`، `dist/`، `build_src/`، `*.spec` (PyInstaller در هر بیلد با مسیر مطلق بازمی‌سازد)، `.wheels/`، `.tools/` را بیرون نگه می‌دارد. قبل از هر commit: `git status` و مطمئن شو هیچ `.env`/`.db` stage نشده.

## وضعیت (به‌روز 2026-10-07)

- تست‌ها: shopapi ۵۵ ✓، shopbots ۴۸ ✓، shopadmin ۳۲۳ ✓ (بدون اخطار).
- **ثبت در حسابداری:** خاموش (`ACCOUNTING_WRITE_ENABLED=false`)؛ کد وضعیت `6808` در `TabaghehBandi` تأیید نشده — باید DBA در production تأیید کند.
- **نشت `.env`:** راه بسته شد (`build_installer.bat` بعد از کپی، `.env`/`*.db`/`*.log` را از staging پاک می‌کند و اگر چیزی ماند متوقف می‌شود؛ `.iss` هم `Excludes` دارد). `ShopAdminSetup.exe` در 2026-10-07 از نو ساخته شد (نسخهٔ آلودهٔ 2026-10-05 جایگزین شد؛ اگر کپی‌ای از آن جای دیگری هست، دور بریز).
- `.env` کنار `shopsystem/dist/ShopSystem/ShopSystem.exe` (تنظیمات تست توسعه‌دهنده) عمداً آنجا می‌ماند و rebuild حفظش می‌کند؛ فقط نباید وارد installer شود.

## کارهای پیش رو (backlog)

### ۰. دستورات جدید کاربر
_(بعد از بررسی کامل، کاربر کارهای تکمیلی را می‌دهد؛ اینجا ثبت و تیک بخورند.)_
- [ ] …

### ۱. سروسامان (مرحلهٔ ۱ — انجام شد 2026-10-07)
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

### ۲. مرحلهٔ ۲ — معماری نهایی (تصمیم کاربر 2026-10-07)
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
- [ ] 2.5 بازطراحی UI.
- [ ] 2.6 تست سرتاسری روی نسخهٔ محلی `hesab5 t`.

### ۲-قدیم. نصب‌کننده (از `shopadmin/CLAUDE.md`)
- [x] exclude کردن `.env`, `app.log`, `*.db` از staging (بیلد مجدد = بند آخر مرحلهٔ ۱).
- [ ] پوشهٔ دادهٔ ShopSystem: launcher آرگومان/متغیر پوشهٔ داده بگیرد (مثلاً `%LOCALAPPDATA%\ShopAdmin\service`) تا نصب در Program Files مشکل مجوز نداشته باشد.
- [ ] ساخت `.env` سرویس هنگام نصب/اجرای اول (کلیدهای تصادفی قوی، DB_SERVER/DB_NAME + تست اتصال، توکن بات‌ها، `ADMIN_CHAT_IDS`, `BANK_ACCOUNT_TEXT`).
- [ ] تمیزکاری `.iss`: حذف CustomMessageهای سرویس ویندوز بی‌استفاده؛ بستن ShopAdmin/ShopSystem در حال اجرا هنگام آپدیت؛ چک پیش‌نیاز ODBC Driver 17/SQL.
- [ ] نصب‌کنندهٔ جدا «فقط کلاینت» و «فقط سرور».
- [x] تضمین بیلد تازهٔ ShopSystem پیش از installer ← `build_all.bat`.

### ۳. باز از shopapi / shopbots
- [ ] راستی‌آزمایی بله با ربات واقعی (`tapi.bale.ai`، long-poll، inline keyboard، request_contact، getFile، …).
- [ ] کلید ایدمپوتنسی برای `POST /orders`.
- [ ] (اختیاری) اعتبارسنجی platform↔نقش کلید؛ credential هر مشتری برای خواندن پروفایل/سفارش؛ redact دلیل رد در audit_log؛ بازبینی grant `TabaghehBandi`.
- [ ] تست استقرار چندکاره (ShopAdmin روی PC دیگر با آدرس راه دور).
- [ ] اتصال سایت به shopapi (سمت سرور، با `SITE_API_KEY`) — فیچر آینده.
- [ ] پیش از production: کاربر `shopbot` با `sql/create_api_user.sql`، تأیید `6808`، امضای دیجیتال installer.

### ۴. تصمیم‌های باز (از کاربر پرسیده شده)
- [ ] فقط برای «عصر ارتباطات ۲» یا فروش به فروشگاه‌های دیگر؟
- [ ] یک PC یا سرور + چند کلاینت؟
- [ ] سرویس فقط هم‌زمان با ShopAdmin، یا همیشه روشن (پیشنهاد: Scheduled Task هنگام بوت) تا ربات‌ها ۲۴ ساعته جواب دهند؟
