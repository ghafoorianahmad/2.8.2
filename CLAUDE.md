# CLAUDE.md — Software Asr (فروشگاه چت‌بات‌محور «عصر ارتباطات ۲»)

این پوشه هستهٔ نرم‌افزاری ارتباط **ربات‌ها ↔ نرم‌افزار حسابداری «سازه حساب»** و کنسول مدیریت فروشگاه است.
قواعد کلی workspace در `E:\DSH-Workspace\CLAUDE.md` معتبر است (production ممنوع، `.env`/`*.db`/توکن نخوان و چاپ نکن، SQL فقط پارامتری، بدون تغییر اسکیمای حسابداری، `backups/ dist/ build/ *.bak-*` را ویرایش نکن، متن‌ها فارسی UTF-8).

> **قاعدهٔ جلسه:** اول این فایل را بخوان، با وضعیت واقعی پوشه تطبیق بده و بعد از هر کار مهم بخش «وضعیت» و «کارهای پیش رو» را به‌روز کن.

## اجزا (هرکدام venv و `.env` جدا)

| پوشه | چیست | وضعیت |
| --- | --- | --- |
| `shopapi/` | FastAPI؛ تنها جزئی که به SQL Server وصل می‌شود. کالا/گروه/موجودی/قیمت از حسابداری (فقط‌خواندنی)، مشتری/سفارش/رزرو در SQLite خودش، ثبت سفارش تأییدشده در `KalaOrder/KalaOrderDetail` (پیش‌فرض dry-run + ROLLBACK). کلیدها: `BOT_API_KEY`, `SITE_API_KEY`, `ADMIN_API_KEY` (هدر `X-API-Key`). | کامل؛ ۵۵ تست سبز؛ روی `hesab5 t` زنده تست شده |
| `shopbots/` | ربات بله + تلگرام (long-polling، httpx خام، موتور گفتگوی مشترک). فقط HTTP به shopapi. ادمین‌ها از `ADMIN_CHAT_IDS` تأیید مشتری/فیش را داخل چت انجام می‌دهند. تلگرام با `TELEGRAM_PROXY` (socks5/http). همهٔ متن‌ها/دکمه‌ها/اطلاعات فروشگاه در `app/messages.fa.json` (نسخهٔ قابل ویرایش: `%ProgramData%\ShopServer\messages.fa.json`). | کامل؛ ۷۷ تست سبز؛ **بله با ربات واقعی راستی‌آزمایی نشده** |
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
- **`SAZEH_DB_REFERENCE.md`** (2026-10-10) — مرجع کامل DB «سازه حساب»: نقشهٔ جدول‌ها، READ/WRITE recipe تست‌شده، پاسخ سؤال‌های باز، حداقل دسترسی، پروتکل آزمایش GUI. ابزارها: `research_tools/` (`sazeh_snapshot.py` برای diff قبل/بعد، `recipes/`).
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

## وضعیت (به‌روز 2026-10-11)

- **فاز ۲ از `REQUIREMENTS.md` انجام و commit شد (2026-10-11)؛ جزئیات در `PROGRESS.md`.** ثبت‌نام فقط با دکمهٔ اشتراک شماره + تطبیق خودکار R4، ساخت شخص با نام ویرایش‌شده در ShopAdmin، سفارش محدود مشتری تأییدنشده، لینک عمیق `kala_<code>`، رسید عکس/فایل ≤۵MB با ذخیره روی سرور، پیگیری فاکتور/ارسال، گردش حساب از KOL، حالت تعطیل. تست‌ها: shopapi ۱۷۳ ✓، shopbots ۱۰۱ ✓، shopadmin ۳۷۷ ✓. **پارامتر start بله و ستون‌های KOL زنده بررسی نشده‌اند** (توکن تست نیست؛ SQL از این جلسه در دسترس نبود).

- **فاز ۱ از `REQUIREMENTS.md` انجام شد (2026-10-11)؛ جزئیات و کارهای بعدی در `PROGRESS.md`.** تلگرام Bot-API حذف شد (فقط بله)؛ هستهٔ مشترک `shopbots/app/core/`؛ R4/R2/`sp_getapplock`/`Status=0`/`create_person` بدون شخص تکراری. تست‌ها: shopapi ۱۴۵ ✓، shopbots ۸۰ ✓، shopadmin ۳۶۴ ✓. هنوز commit نشده (نقطهٔ بازگشت `6f7eca5`).

- تست‌ها: shopapi ۱۰۹ ✓، shopbots ۷۷ ✓، shopadmin ۳۶۴ ✓ (2026-10-07، بعد از کار تلگرام).
- **کلاینت هرگز سرور را اجرا نمی‌کند** (باگ Sandbox «ShopSystem.exe not found»): `child_process.py`/`jobobject.py` حذف؛ `services/connection.py` فقط `/health` را پروب می‌کند و در قطعی «سرور در دسترس نیست» + نشانی + «تلاش دوباره» نشان می‌دهد. بیلد کلاینت جدا (`build_shopadmin.py --variant client` → `dist/client`، بدون `server_setup`، بررسی خودکار صفر ارجاع به ShopSystem حتی داخل PYZ). باگ `build_installer.bat` (کپی قدیمی اسکریپت بعد از `:fail`) رفع شد.
- **متن سفید روی زمینهٔ روشن** (دکمهٔ «ادامه» و OK دیالوگ‌ها) در سورس از 7bcabe8 رفع شده بود؛ installerهای قبلی قدیمی بودند. `contrast_audit.py` حالا دکمه‌های واقعی رندرشده (ویزاردها، ورود، MessageDialog/ConfirmDialog/QMessageBox روی هر پنجره) را اندازه می‌گیرد: ۹۵/۹۵ AA؛ قاعدهٔ قدیمی را ۱٫۰۶:۱ تشخیص می‌دهد.
- هر دو installer در 2026-10-07 ۱۰:۵۰ از نو ساخته شدند (`ShopAdminSetup.exe` ۳۳MB، `ShopServerSetup.exe` ۵۱MB)؛ ShopSystem/سرور دست نخورد، `ACCOUNTING_WRITE_ENABLED=false`. نصب آزمایشی دوباره در Sandbox لازم است.
- **ثبت در حسابداری:** خاموش (`ACCOUNTING_WRITE_ENABLED=false`)؛ کد وضعیت `6808` در `TabaghehBandi` تأیید نشده — باید DBA در production تأیید کند.
- **نشت `.env`:** راه بسته شد (`build_installer.bat` بعد از کپی، `.env`/`*.db`/`*.log` را از staging پاک می‌کند و اگر چیزی ماند متوقف می‌شود؛ `.iss` هم `Excludes` دارد). `ShopAdminSetup.exe` در 2026-10-07 از نو ساخته شد (نسخهٔ آلودهٔ 2026-10-05 جایگزین شد؛ اگر کپی‌ای از آن جای دیگری هست، دور بریز).
- `.env` کنار `shopsystem/dist/ShopSystem/ShopSystem.exe` (تنظیمات تست توسعه‌دهنده) عمداً آنجا می‌ماند و rebuild حفظش می‌کند؛ فقط نباید وارد installer شود.

## کارهای پیش رو (backlog)

### ۰. دستورات جدید کاربر
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
- [ ] 2.5 بازطراحی UI. ← شروع شد:
  - [x] `scripts/render_screens.py` با API جدید بازنویسی شد (۱۵ تصویر، شامل صفحهٔ سرور و ویزارد سرور).
  - [x] باگ مهم: دکمه‌های Primary (ورود، ادامه، آزمایش اتصال) در پنجرهٔ ورود و هر دو ویزارد متن سفید روی زمینهٔ روشن داشتند (setStyleSheet بدون selector روی پنجره) → محدود به `QWidget#WindowRoot`.
  - [x] نوار کناری تیره (`SIDEBAR_*` در theme، `nav_icon`، badge زرد) + نمودار سفارش‌های ۷ روز اخیر در داشبورد (`widgets.BarChart`, `orders_per_day`)؛ ۷۳/۷۳ جفت AA، ۳۷۷ تست سبز (2026-10-07).
  - **اول (2026-10-07، مقدم بر بقیهٔ UI):** (۱) ✓ بررسی امنیتی: `shopsystem/dist`، staging و `ShopAdmin` بدون `.env`/`*.db`/لاگ/توکن؛ فقط `.env.example` با مقادیر خالی. محتوای دو installer بدون اجرا قابل بازرسی نیست (فشردهٔ Inno)؛ از روی staging پاک و `Excludes` در `.iss` نتیجه می‌شود. (۲) ✓ `404 persons/match` خطا نیست: قرارداد سرور/کلاینت یکی است و 404 یعنی «مشتری مطابق ندارد» (`match_person` → None)؛ فقط لاگ پرحرف fake server. (۳) ✓ چک‌لیست نصب آزمایشی: `shopadmin/installer/TEST_INSTALL_CHECKLIST.md` (اجرا نشده، منتظر PC/VM تست).
  - [ ] مانده از بازطراحی: صفحهٔ ورود دو ستونه، سایهٔ کارت‌ها.
  - [ ] `scripts/e2e_check.py` و `e2e_app_live.py` هنوز API قدیمی دارند.
  - نکته: `widgets.py:388` (overlay) هم background بدون selector دارد — بررسی شود.
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

## پوشهٔ خروجی (`E:\Outputs\ShopSystem\`)
بعد از هر بیلد تازه (`build_all.bat` ← `shopadmin\dist\installer\ShopServerSetup.exe` و `ShopAdminSetup.exe`):
1. هر دو installer را به `E:\Outputs\ShopSystem\` **کپی** کن (هرگز move نکن؛ داخل این پوشهٔ پروژه چیزی را پاک یا جابه‌جا نکن). هنگام کپی نسخه و تاریخ را به نام اضافه کن: `ShopServerSetup_<MyAppVersion>_<YYYY-MM-DD>.exe` و `ShopAdminSetup_<MyAppVersion>_<YYYY-MM-DD>.exe` (نسخه از `shopadmin/installer/ShopAdmin.iss`).
2. در `E:\Outputs\ShopSystem\` فقط جفت جدیدترین + **یک** جفت قبلی بماند؛ قدیمی‌ترها فقط از همان پوشهٔ Outputs پاک شوند.
3. `E:\Outputs\ShopSystem\README_FA.txt` را به‌روز کن: نام فایل‌ها، نسخه، تاریخ (میلادی + شمسی)، commit، SHA-256، روش نصب، و نسخهٔ قبلی نگه‌داشته‌شده.
4. ردیف ShopSystem در `E:\Outputs\README_FA.txt` را به‌روز کن.
5. هرگز `.env`، `*.db` یا `*.log` را در Outputs کپی نکن.
