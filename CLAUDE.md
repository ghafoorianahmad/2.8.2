# CLAUDE.md — Software Asr (فروشگاه چت‌بات‌محور «عصر ارتباطات ۲»)

این پوشه هستهٔ نرم‌افزاری ارتباط **ربات‌ها ↔ نرم‌افزار حسابداری «سازه حساب»** و کنسول مدیریت فروشگاه است.
قواعد کلی workspace در `E:\DSH-Workspace\CLAUDE.md` معتبر است (production ممنوع، `.env`/`*.db`/توکن نخوان و چاپ نکن، SQL فقط پارامتری، بدون تغییر اسکیمای حسابداری، `backups/ dist/ build/ *.bak-*` را ویرایش نکن، متن‌ها فارسی UTF-8).

> **جلسهٔ ابری (Claude Code cloud، لینوکس):** اول `CLOUD.md` را بخوان — بدون SQL، بدون بیلد ویندوز، فقط روی شاخهٔ خودش (هرگز `main`).
> **قاعدهٔ جلسه:** اول این فایل را بخوان، با وضعیت واقعی تطبیق بده، بعد از هر کار مهم «وضعیت» و «کارهای باز» را به‌روز کن. **تاریخچهٔ فازها و بایگانی وضعیت‌های قدیمی در `PROGRESS.md`** است؛ تصمیم‌ها در `REQUIREMENTS.md`.

## اجزا (هرکدام venv و `.env` جدا)

| پوشه | چیست | تست‌ها (لینوکس، 2026-10-13) |
| --- | --- | --- |
| `shopapi/` | FastAPI؛ تنها جزئی که به SQL Server وصل می‌شود. کالا/موجودی/قیمت از حسابداری (فقط‌خواندنی)، مشتری/سفارش/رزرو/مدل‌های سایت/لیست قیمت/پراکسی در SQLite خودش، ثبت سفارش در `KalaOrder` (پیش‌فرض dry-run + ROLLBACK). ورود کارکنان سمت سرور (توکن نشست)؛ کلیدهای `BOT_/SITE_/ADMIN_API_KEY` فقط loopback. `POST /orders` ایدمپوتنت است (`Idempotency-Key`، ۲۴ ساعت). | ۳۵۳ ✓ (2026-10-14) |
| `shopbots/` | ربات بله (long-polling) + آداپتر تلگرام (فاز ۷، فقط با fake)، موتور مشترک `app/core/`، کارت‌های تصویری (قیمت/پیش‌فاکتور/فاکتور؛ پیش‌فرض خاموش)، متن‌ها در `messages.fa.json`. فقط HTTP به shopapi. | ۲۲۸ ✓ |
| `shopadmin/` | کنسول PySide6 (فارسی، RTL، شمسی): داشبورد، مشتریان، سفارش‌ها، محصولات، مدل‌های سایت، لیست قیمت، گزارش، سرور، کاربران؛ ورود دو‌ستونه. بیلد کلاینت/سرور + نصب‌کننده Inno. اسکریپت‌های `e2e_check.py`/`e2e_app_live.py` (ورود سمت سرور؛ راهنما در سرفایل). | ۴۴۸ ✓، ۳ skip |
| `shoptg/` | کارگر تلگرام (Telethon، فقط‌خواندنی): لیست قیمت PDF و استخر پراکسی MTProto؛ فقط `/worker/*`. | ۴۷ ✓، ۲ skip |
| `shopsystem/` | `launcher.py` → `ShopSystem.exe` (PyInstaller)، سرویس ویندوز `ShopServer`، پشتیبان، `deploy/*.ps1`. | ۳۶ ✓، ۱ ✗ (مسیر `E:\` ویندوز)، ۱۲ skip |
| `shared/` | پکیج مشترک `shop-tgproxy` (پراکسی MTProto). | — |

تست‌های ویندوزی/SQL (`hesab5 t`) را فقط مالک روی PC خودش اجرا می‌کند؛ لینوکس = fakeها (`CLOUD.md`). نیاز لینوکس: `apt install unixodbc` برای import `pyodbc`، و `pip install ./shared` برای shopbots/shoptg.

**سایت** خارج از این پوشه است (`E:\DSH-Workspace\projects\asr-ertebatat-2-redesign`، شاخهٔ `redesign`)؛ HTML ثابت با «کد مدل» و لینک ربات بله، بدون اتصال به shopapi.

```
سایت ──لینک──► ربات بله/تلگرام ──HTTP+BOT_API_KEY──┐
ShopAdmin.exe ───────────HTTP + نشست کارمند────────┼──► shopapi ──pyodbc──► SQL Server «سازه حساب»
shoptg ──────────────────/worker/* + WORKER_API_KEY─┘      └─ shopapi.db (SQLite)
```

استقرار: PC سرور (کنار SQL Server) = `ShopSystem.exe` (سرویس `ShopServer`) + ODBC Driver 17؛ PCهای کارمندان = فقط `ShopAdmin.exe` با آدرس راه دور (HTTPS با pin اثرانگشت).

## مستندات مرجع
- `REQUIREMENTS.md` (تصمیم‌ها و فازها)، `PROGRESS.md` (لاگ فازها + بایگانی)، `SECURITY.md`، `DEPLOY_CHECKLIST.md`.
- `SAZEH_DB_REFERENCE.md` — مرجع DB «سازه حساب» (READ/WRITE recipeها؛ ابزار: `research_tools/`).
- `shopapi/{README,NOTES,REVIEW}.md`، `shopbots/{README,NOTES}.md`، `shopadmin/{CLAUDE,NOTES}.md` + `README.txt`، `shopsystem/{NOTES.md,README.txt}`، `shoptg/{README,SERVER_GUIDE}.md`.

## اجرا و تست (PowerShell، داخل پوشهٔ هر جزء)
```powershell
.\.venv\Scripts\python.exe -m pytest -q          # shopapi, shopbots, shoptg
.\.venv\Scripts\python.exe -m pytest tests -q    # shopadmin, shopsystem ($env:QT_QPA_PLATFORM='offscreen')
.\run.ps1 [-Port 8100 -Reload]                   # shopapi / shopbots
build_all.bat        # (ریشه) ShopSystem → تست shopadmin → ShopAdmin + installer
```
همیشه `python -m <tool>` بزن، نه `pytest.exe`/`uvicorn.exe` (مسیر قدیمی در exeهای `.venv`).

## git
ریپوی محلی، شاخهٔ `main`. `.gitignore` ریشه `.env`، `*.db`، `*.log`، `.venv`، `build/`، `dist/`، `*.spec` و … را بیرون نگه می‌دارد. قبل از commit: `git status` و مطمئن شو هیچ `.env`/`.db` stage نشده.

## وضعیت (2026-10-14)
- **نسخه ۲٫۶٫۰ (2026-10-14، همان شاخهٔ `feature/order-flow-v250`؛ جزئیات در `PROGRESS.md`، تصمیم‌ها در `REQUIREMENTS.md` §7b):** یافته‌های آزمون ویندوز روی `hesab5 t`. **باگ بحرانی رفع شد:** گوشی دیگر «کالای نگاشت‌شده در لیست قیمت» نیست بلکه «کالای گروه گوشی» است؛ بدون لیست معتبر گوشی پنهان است و با فروش بسته هرگز سفارش گوشی پذیرفته نمی‌شود. صفحهٔ جدید «گروه‌های کالا» (نمایش در ربات / گروه گوشی؛ تا انتخاب نشود ربات کالایی نشان نمی‌دهد)، فقط کالای موجود در فهرست‌ها، «درخواست کالای ناموجود» (+ صفحهٔ «درخواست کالا» و اعلان)، گردش حساب به‌صورت یک PDF (A4، راست‌به‌چپ، شمسی)، کارت پرداخت الزامی (بدون کارت سفارش نهایی نیست، هشدار در داشبورد، هرگز placeholder)، `ACCOUNTING_STATUS_CODE` در تنظیمات سرور ShopAdmin، نام و کد شخص «سازه حساب» در جزئیات سفارش (نیاز به اجرای دوبارهٔ `grant_shop_app.ps1`)، نسخهٔ واقعی در نوار کناری، بدون دکمهٔ تأیید/رد برای مشتری تصمیم‌گرفته، محدودیت ربات برای دکمه‌ها جدا و یک هشدار در هر بازه و `/start` همیشه آزاد، `build_all.bat` با `SHOP_NOPAUSE=1` مکث نمی‌کند. تست‌ها (لینوکس): shopapi ۳۷۱ ✓، shopbots ۲۳۹ ✓، shopadmin ۴۶۳ ✓، shoptg ۴۷ ✓، shopsystem ۳۶ ✓ (+۱ ✗ قدیمی مسیر ویندوز). **روی ویندوز/SQL/بله آزموده نشده.**
- **نسخه ۲٫۵٫۰ (2026-10-14، شاخهٔ `feature/order-flow-v250`؛ جزئیات در `PROGRESS.md`، تصمیم‌ها در `REQUIREMENTS.md` §7a):** حذف رزرو ۱۲ ساعته؛ رسید تا ۳۰ دقیقه وگرنه لغو محلی (در «سازه حساب» هرگز چیزی حذف نمی‌شود)؛ لیست قیمت هر ۱۰ دقیقه؛ پنجرهٔ فروش **فقط برای گوشی** (لیست صبح تا ۱۳:۳۰، عصر تا ۲۰:۳۰، جمعه بسته؛ لوازم جانبی همیشه قابل سفارش) + دکمه‌های «تعطیلی امروز / بستن فروش / باز کردن فروش»؛ تست‌ها هرگز `.env` واقعی را نمی‌خوانند (fixture `_no_real_dotenv`، خروج با `SHOP_TESTS_USE_DOTENV=1`)؛ `ACCOUNTING_STATUS_CODE` بدون پیش‌فرض؛ نام DB با هر سفارش؛ بررسی Codlp تکراری؛ خطاهای SQL فارسی؛ نقش `shop_app`؛ allowlist پایگاه‌داده و dry-run بدون INSERT. **روی ویندوز/SQL/بله آزموده نشده.**
- **نسخه ۲٫۴٫۰ (2026-10-13، شاخهٔ `claude/amazing-mccarthy-dob95x`؛ جزئیات در `PROGRESS.md`):** فراموشی گذرواژه با تأیید مدیر، بازنشانی به ۱۲۳۴۵ توسط مدیر کل، نسخهٔ سرور ShopAdmin بدون صفحهٔ ورود (ورود کنسول فقط loopback)، حالت آزمایشی `hesab5 t` با خواندن/نوشتن کامل، رفع تیک «مرا به خاطر بسپار». **روی ویندوز/GUI واقعی راستی‌آزمایی نشده.**
- **فازهای ۱–۷ و کارت‌های تصویری ربات در کد کامل‌اند** (جزئیات هر فاز در `PROGRESS.md`). ثبت واقعی در حسابداری خاموش است (`ACCOUNTING_WRITE_ENABLED=false`).
- **تازه (شاخهٔ `claude/magical-ride-7p262r`):** `Idempotency-Key` برای `POST /orders` (ربات برای هر checkout یک کلید می‌فرستد؛ تلاش دوباره = همان سفارش)؛ اسکریپت‌های e2e با ورود سمت سرور؛ صفحهٔ ورود دو‌ستونه + سایهٔ کارت‌ها + overlay جدول با selector (contrast_audit ۹۵/۹۵ AA؛ تصاویر در `shopadmin/docs/screens/` روی لینوکس رندر شده → فونت‌ها با ویندوز فرق دارند).
- **هیچ‌چیز روی سرور فروشگاه نصب/آزمون زنده نشده:** سرویس `ShopServer`، پشتیبان، دیوار آتش، ورود تلگرام (`shoptg`)، بلهٔ واقعی (پارامتر `start` نامطمئن؛ fallback = ارسال کد کالا)، کارت‌های تصویری و نصب‌کننده‌ها.

## کارهای باز
- [ ] آزمون زنده روی `hesab5 t` + بلهٔ واقعی: R4/`create_person`، applock سفارش، فاز ۶b (مدل‌های سایت)، کارت‌ها (Edge headless)، e2e scripts.
- [ ] GUI تست G1–G4 (`SAZEH_DB_REFERENCE.md` §10) برای `Status` واقعی و تنظیم `ACCOUNTING_STATUS_CODE` (بدون آن ثبت واقعی انجام نمی‌شود)؛ تأیید DBA قبل از production؛ اجرای `grant_shop_app.ps1` (نقش `shop_app`) روی `hesab5 t` و بعد production.
- [ ] نصب آزمایشی سرویس/installer روی PC یا VM تست (`shopadmin/installer/TEST_INSTALL_CHECKLIST.md`)، `firewall_sql.ps1`، ورود تلگرام روی سرور (`shoptg/SERVER_GUIDE.md`).
- [ ] راستی‌آزمایی بله (`shopbots/NOTES.md`: ۱۰ سؤال باز)، تست استقرار چندکاره (ShopAdmin روی PC دیگر).
- [ ] رفع تست `test_sidebar_badges_and_close_to_tray` (لینوکس) و وابستگی تست‌های shoptg به `pdfplumber`.
- [ ] ماندهٔ UI (اختیاری): سایه روی Panelهای بدون جدول؛ دکمه‌های حاشیه‌ای ویزارد.
- [ ] امضای دیجیتال installer؛ اتصال سایت به shopapi (آینده، فقط سمت سرور).

## پوشهٔ خروجی (`E:\Outputs\ShopSystem\`)
بعد از هر بیلد تازه (`build_all.bat` ← `shopadmin\dist\installer\ShopServerSetup.exe` و `ShopAdminSetup.exe`):
1. هر دو installer را به `E:\Outputs\ShopSystem\` **کپی** کن (هرگز move نکن؛ داخل این پوشهٔ پروژه چیزی را پاک یا جابه‌جا نکن). هنگام کپی نسخه و تاریخ را به نام اضافه کن: `ShopServerSetup_<MyAppVersion>_<YYYY-MM-DD>.exe` و `ShopAdminSetup_<MyAppVersion>_<YYYY-MM-DD>.exe` (نسخه از `shopadmin/installer/ShopAdmin.iss`).
2. در `E:\Outputs\ShopSystem\` فقط جفت جدیدترین + **یک** جفت قبلی بماند؛ قدیمی‌ترها فقط از همان پوشهٔ Outputs پاک شوند.
3. `E:\Outputs\ShopSystem\README_FA.txt` را به‌روز کن: نام فایل‌ها، نسخه، تاریخ (میلادی + شمسی)، commit، SHA-256، روش نصب، و نسخهٔ قبلی نگه‌داشته‌شده.
4. ردیف ShopSystem در `E:\Outputs\README_FA.txt` را به‌روز کن.
5. هرگز `.env`، `*.db` یا `*.log` را در Outputs کپی نکن.
