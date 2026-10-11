# CLAUDE.md — shopadmin (کنسول مدیریت دسکتاپ + نصب‌کننده)

قواعد کلی workspace در `E:\DSH-Workspace\CLAUDE.md` است (دیتابیس production ممنوع، داده شخصی/توکن/`.env` نخوان، فقط SQL پارامتری، `backups/ dist/ build/ *.bak-*` را ویرایش نکن). این فایل فقط خلاصهٔ ارتباط اجزا و وضعیت کار نصب‌کننده است.

> **وضعیت و backlog جاری در `../CLAUDE.md` (Software Asr) است؛ این بخش تاریخچهٔ ۲۰۲۶-۱۰-۰۵ است.** از آن زمان: نشت `.env` در staging با حذف + بررسی در `build_installer.bat` و `Excludes` در `.iss` بسته شد؛ `.installtest/`، `.keyringtest/` و لاگ‌های موقت حذف شدند (سطل بازیافت)؛ بیلد کامل با `../build_all.bat`.

## Current status (هر جلسه اول همین بخش را بخوان؛ بعد از هر تغییر مهم به‌روزش کن)

- **قاعده:** در شروع هر جلسه، قبل از هر کاری این بخش را بخوان و با وضعیت واقعی پوشه‌ها تطبیق بده؛ اگر کهنه بود اصلاحش کن.
- **چه کسی صدا می‌زند:** ربات‌های بله/تلگرام (`BOT_API_KEY`) و ShopAdmin (`ADMIN_API_KEY`) → shopapi → SQL Server «سازه حساب». سایت به API وصل نیست (فقط لینک ربات).
- **سرور فروشگاه (PC کنار SQL Server):** `ShopSystem.exe` (shopapi + بات‌ها، با `.env` و دو SQLite کنار exe) و SQL Server/ODBC Driver 17؛ تنها جایی که به حسابداری وصل می‌شود.
- **PCهای کارمندان:** فقط `ShopAdmin.exe` با آدرس راه دور سرور + کلید ادمین؛ **هرگز** سرور را پیدا/اجرا/متوقف نمی‌کند (از 2026-10-07 `services/connection.py` فقط `/health` را پروب می‌کند؛ `child_process.py`/`jobobject.py` حذف شدند).
- **نصب تک‌سیستمه:** `ShopAdminSetup.exe` هر دو را کنار هم نصب می‌کند و ShopAdmin سرویس را خودش بالا می‌آورد.
- **ناتمام (کار نصب‌کننده ۱۴۰۵/۰۷/۱۳ نیمه‌کاره ماند):**
  1. `.env` توسعه داخل staging/installer رفته → پاک‌سازی و بیلد مجدد (`ShopAdminSetup.exe` فعلی را نده).
  2. مسیر داده ShopSystem کنار exe است → در Program Files مشکل مجوز.
  3. ساخت `.env` سرویس هنگام نصب/اجرای اول (کلیدها، DB، توکن‌ها) پیاده نشده.
  4. بقایای Taskهای سرویس ویندوز در `.iss`، نبود بستن برنامهٔ در حال اجرا هنگام آپدیت، و نبود چک پیش‌نیاز SQL/ODBC.
  5. نصب‌کنندهٔ جداگانهٔ «فقط کلاینت» (بدون ShopSystem) و «فقط سرور» وجود ندارد.
- جزئیات در بخش «وضعیت نصب‌کننده» پایین‌تر.

## معماری و ارتباط اجزا

```
 سایت (HTML ثابت)  ──لینک──►  ربات بله / تلگرام ─┐
 projects/asr-ertebatat-shop                      │ HTTP + X-API-Key (BOT_API_KEY)
                                                  ▼
 ShopAdmin.exe (PySide6) ──HTTP + ADMIN_API_KEY──► shopapi (FastAPI)  ──pyodbc──► SQL Server «سازه حساب»
 shopadmin/                                         │  SQLite خودش: مشتری/سفارش/رزرو   (خواندن کالا و موجودی؛ نوشتن سفارش = dry-run+ROLLBACK مگر فعال شود)
                                                    └─ shopapi.db
```

- **shopapi** (`../shopapi`) تنها نقطه‌ای است که به دیتابیس حسابداری وصل می‌شود. سه کلید جدا در `.env`: `BOT_API_KEY` (نقش bot)، `SITE_API_KEY` (نقش site)، `ADMIN_API_KEY` (نقش admin). هدر: `X-API-Key`. سطح قیمت هر کانال: `PRICE_LEVEL_BOT/SITE`.
- **shopbots** (`../shopbots`): فقط بله (Telegram Bot-API از 2026-10-11 حذف شد) با long-polling و موتور گفتگوی مشترک؛ فقط با shopapi حرف می‌زنند (`SHOPAPI_BASE_URL`, پیش‌فرض `127.0.0.1:8000`). ادمین‌ها با `ADMIN_CHAT_IDS` (`telegram:123`/`bale:456`) اعلان «مشتری جدید» و «فیش جدید» را می‌گیرند و از داخل چت تأیید/رد می‌کنند. تلگرام فقط با `PROXY_URL`؛ بله بدون پروکسی. آدرس Bale API (`https://tapi.bale.ai`) هنوز با ربات واقعی **راستی‌آزمایی نشده** (`shopbots/NOTES.md`).
- **سایت** (`../projects/asr-ertebatat-shop`): ویترین استاتیک بدون بک‌اند؛ قیمت/سبد ندارد، کاتالوگ در `assets/products.js` ثابت است. **به shopapi وصل نیست**؛ فقط لینک `t.me/asrertebatat2_bot` و بله (`PLACEHOLDERS` در `site.js`) دارد و سفارش از ربات انجام می‌شود. کلید `SITE_API_KEY` در shopapi آماده است ولی هنوز مصرف‌کننده ندارد (اتصال زندهٔ سایت = کار آینده، نیازمند فیچر جدید).
- **shopadmin** (این پوشه): فقط HTTP به shopapi؛ هرگز به SQL Server یا shopbots دست نمی‌زند. صفحه‌ها: داشبورد، مشتریان (تأیید با `person_code` حسابداری)، سفارش‌ها (تأیید/رد پرداخت)، محصولات، گزارش‌ها (CSV/XLSX)، تنظیمات، کاربران سیستم (فقط super_admin). نوار زرد «حالت آزمایشی» وقتی `ACCOUNTING_WRITE_ENABLED=false`.
  - تنها تغییر در shopapi برای این برنامه: `GET /admin/system-info` (فقط‌خواندنی).
  - نکته: `approve-payment` در dry-run هم 200 می‌دهد؛ کلاینت وضعیت `written` را چک می‌کند.
- **shopsystem** (`../shopsystem`): `launcher.py` یک exe (PyInstaller) که API (thread + restart خودکار) و بات‌ها (asyncio) را با هم بالا می‌آورد. دو پکیج `app` در build به `shopapi_app`/`shopbots_app` تغییر نام می‌دهند. `.env` باید **کنار ShopSystem.exe** باشد؛ دو SQLite جدا (`shopapi.db`, `shopbots.db`) و `app.log` هم همان‌جا. نام‌های ساده در `.env` (`DB_SERVER`, `SHOPAPI_URL`, …) در launcher به نام‌های اصلی نگاشت می‌شوند.

## ساختار shopadmin

- `app/`: `main.py`, `api_client.py` (ترجمهٔ خطا به فارسی), `auth.py` (bcrypt، قفل ۵ تلاش/۱۵ دقیقه، توکن remember-me در keyring), `store.py` (SQLite محلی: `admin_users`, settings, audit), `permissions.py` (super_admin / مدیر فروش / اپراتور / ناظر), `persian.py` (ارقام فارسی + شمسی بدون وابستگی), `statuses.py`, `reporting.py`, `paths.py`, `services/connection.py` (فقط پروب اتصال؛ بیلد کلاینت بدون `server_setup`)، `ui/` (صفحه‌ها، wizard اولیه، login، theme AA).
- داده محلی: `%LOCALAPPDATA%\ShopAdmin` (`shopadmin.db`, `app.log`, `shopapi.log`)؛ با `SHOPADMIN_DATA_DIR` قابل تغییر.
- `tests/` (~۳۱۱ تست، بدون شبکه/SQL)، `scripts/` (`e2e_check.py`, `e2e_app_live.py` نیاز به shopapi زنده؛ `contrast_audit.py`, `render_screens.py` → `docs/screens/`).
- بیلد: `build_shopadmin.py --clean` (یا `.bat`) → `dist/ShopAdmin/`؛ سپس `build_installer.bat` → `dist/installer/ShopAdminSetup.exe` (۴۸MB). نیازمند Inno Setup (`.tools/innosetup.exe`, یا `winget install JRSoftware.InnoSetup`) و بیلد قبلی `../shopsystem/build_exe.bat`. ویل‌های PySide6 در `.wheels/` (به‌خاطر قطعی TLS با pythonhosted).

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_shopadmin.py
```

## وضعیت نصب‌کننده (آخرین کار: ۱۴۰۵/۰۷/۱۳ ≈ 2026-10-05 ساعت ۲۰:۱۷)

انجام‌شده و تست‌شده: wizard اولیه، login، remember-me، مدیریت child process (Job Object؛ **عمداً Windows Service نیست** چون نیاز به UAC و اجرای دائمی دارد)، تم WCAG AA، `ShopAdmin.iss` (per-user پیش‌فرض، میان‌بر فارسی «مدیریت فروشگاه», uninstaller که `%LOCALAPPDATA%\ShopAdmin` را نگه می‌دارد)، نصب/حذف بی‌صدا در `.installtest/`، و `ShopAdminSetup.exe` ساخته شده. آخرین ویرایش‌ها: `ShopAdmin.spec`، `shopsystem/build_exe.bat` و `ShopSystem.spec` (۲۰:۱۴–۲۰:۰۹) — همان‌جا کار قطع شده.

### موارد باز / ریسک‌ها (قبل از تحویل به فروشگاه‌ها حل شود)

1. **نشت `.env` در نصب‌کننده (مهم‌ترین).** `shopsystem/dist/ShopSystem/.env` (دستی ساخته‌شده، با تنظیمات dev و احتمالاً توکن) توسط `xcopy` به `build/installer_staging/ShopSystem/` و از آنجا داخل `ShopAdminSetup.exe` رفته است (`.iss` همهٔ پوشه را `recursesubdirs` کپی می‌کند). باید: `.env`، `app.log`، `*.db` را از staging حذف/exclude کنید و installer را از نو بسازید؛ `ShopAdminSetup.exe` فعلی را به کسی ندهید.
2. **`.env` و دیتای ShopSystem کنار exe است** (قرارداد launcher). در نصب «برای همهٔ کاربران» (`Program Files`) نوشتن `.env`/`shopapi.db`/`shopbots.db`/`app.log` به UAC می‌خورد. باید یا نصب per-user اجباری شود، یا launcher آرگومان/متغیر برای پوشهٔ داده (مثلاً `%LOCALAPPDATA%\ShopAdmin\service`) بگیرد و ShopAdmin همان را پاس دهد.
3. **ساخت `.env` سرویس هنگام نصب/اولین اجرا وجود ندارد.** wizard فقط URL و ADMIN_API_KEY می‌گیرد؛ DB_SERVER/DB_NAME، کلیدهای سه‌گانه، توکن بات‌ها، `ADMIN_CHAT_IDS`, `BANK_ACCOUNT_TEXT` باید دستی در `.env` نوشته شوند. پیشنهاد: صفحهٔ wizard/Inno برای تولید `.env` (کلیدهای تصادفی قوی، تست اتصال SQL).
4. در `ShopAdmin.iss` CustomMessageهای `ServiceSection / InstallServiceTask / RunAtStartup` تعریف شده ولی هیچ Task/کدی ندارند — بقایای ایدهٔ نصب سرویس ویندوز که رد شد؛ حذف یا تکمیل کنید. `InitializeWizard`/`InitializeSetup` خالی‌اند و بستن ShopAdmin/ShopSystem در حال اجرا هنگام آپدیت پیاده نشده (فایل قفل می‌شود).
5. نصب‌کننده ShopSystem را فقط از `../shopsystem/dist` برمی‌دارد؛ اگر آن بیلد کهنه باشد بی‌صدا نسخهٔ قدیمی را می‌بندد. `build_exe.bat` را همیشه قبل از installer بزنید.
6. هیچ‌جا ODBC Driver 17 و دسترسی SQL (کاربر least-privilege `shopbot` طبق `shopapi/sql/create_api_user.sql`) روی سیستم مقصد چک/نصب نمی‌شود؛ در راهنما بیاید یا installer بررسی کند.
7. سایر: Bale API راستی‌آزمایی نشده؛ سایت به API وصل نیست؛ `POST /orders` ایدمپوتنت نیست؛ ثبت واقعی در حسابداری باید خاموش (`ACCOUNTING_WRITE_ENABLED=false`) بماند تا DBA وضعیت `6808` (TabaghehBandi) را در production تأیید کند؛ نصب‌کننده امضای دیجیتال ندارد (هشدار SmartScreen در راهنما آمده).
8. فایل‌های موقتی برای تمیزکاری: `dbg.log`, `full.log`, `kc_*.txt`, `install.log`, `.keyringtest/`, `.installtest/`، و `shopapi/it_*.txt`.

## مستندات مرجع
`NOTES.md` (لاگ کامل تصمیم‌ها/تست‌ها)، `README.txt` (راهنمای کاربر فارسی)، `installer/installer_readme.txt`، `../shopsystem/NOTES.md`، `../shopapi/{README,NOTES,REVIEW}.md`، `../shopbots/{README,NOTES}.md`، `../projects/asr-ertebatat-shop/CLAUDE.md`.
