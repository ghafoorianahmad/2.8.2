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
- **نشت `.env`:** راه بسته شد (`build_installer.bat` بعد از کپی، `.env`/`*.db`/`*.log` را از staging پاک می‌کند و اگر چیزی ماند متوقف می‌شود؛ `.iss` هم `Excludes` دارد). ولی `shopadmin/dist/installer/ShopAdminSetup.exe` موجود (2026-10-05) هنوز نسخهٔ آلوده است — **به کسی نده** تا با `build_all.bat` از نو ساخته شود.
- `shopsystem/dist/ShopSystem/.env` تنظیمات تست توسعه‌دهنده است و عمداً کنار exe می‌ماند (build_exe آن را حفظ می‌کند)؛ فقط نباید وارد installer شود.

## کارهای پیش رو (backlog)

### ۰. دستورات جدید کاربر
_(بعد از بررسی کامل، کاربر کارهای تکمیلی را می‌دهد؛ اینجا ثبت و تیک بخورند.)_
- [ ] …

### ۱. سروسامان (مرحلهٔ ۱ — انجام شد 2026-10-07)
- [x] git init + `.gitignore` ریشه + commit اولیه.
- [x] فایل‌های `.spec`: نیازی به ویرایش نیست؛ هر بیلد آن‌ها را با مسیر جدید بازمی‌سازد (در git نیستند).
- [x] مسیرهای قدیمی در `shopapi/README.md`, `shopbots/README.md`, `shopsystem/NOTES.md` و `E:\DSH-Workspace\CLAUDE.md`.
- [x] `build_all.bat` (ریشه)؛ `SHOP_NOPAUSE` در `build_installer.bat` برای اجرای زنجیره‌ای.
- [x] باگ `build_exe.bat`: `%OUT%shopapi.db` بدون `\` ← دیتابیس/لاگ در rebuild حفظ نمی‌شد.
- [x] نصب آزمایشی ثبت‌شده در ویندوز (`.installtest`، منوی Start) با uninstaller خودش حذف شد؛ فایل‌های موقت به سطل بازیافت.
- [x] `qt_api` از `shopadmin/pytest.ini` (pytest-qt نصب نیست و تست‌ها از آن استفاده نمی‌کنند).
- [ ] اجرای واقعی `build_all.bat` و نصب `ShopAdminSetup.exe` تازه (چند دقیقه طول می‌کشد؛ Inno Setup لازم است).
- [ ] (اختیاری) بازسازی venvها در مسیر جدید تا `pip.exe`/`pytest.exe` هم کار کنند.

### ۲. نصب‌کننده (از `shopadmin/CLAUDE.md`)
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
