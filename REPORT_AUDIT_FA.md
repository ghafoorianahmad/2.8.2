# گزارش ممیزی فنی (فقط‌خواندنی) — اتصال فروشگاه به «سازه حساب»

> تاریخ: 2026-10-13 · شاخه: `main` (commit `2cfa59f`) · روش: خواندن کد + چند `SELECT` فقط روی `[hesab5 t]` در `.\SQLEXPRESS`.
> هیچ فایل، تنظیم، سرویس یا دیتابیسی تغییر نکرد. به `hesab5` و `master` دست زده نشد. `.env` خوانده نشد.
> علامت‌ها: ✅ = با کد یا SELECT ثابت شد · ⚠ فرض = راستی‌آزمایی نشده · 🔴 باید قبل از production رفع شود · 🟠 مهم · 🟡 بهتر است.

---

## خلاصهٔ مدیریتی (۱۰ خط)

1. **آیا امروز نوشتن در دیتابیس اصلی امن است؟ خیر — «مشروط».** هنوز نباید روشن شود.
2. فقط **دو** نوع نوشتن وجود دارد: ساخت سفارش (`KalaOrder` + `KalaOrderDetail`) و ساخت مشتری (`name_mo` + `taf` + `DetailTBL`). **فاکتور، موجودی، مانده و دفتر کل نوشته نمی‌شوند** ✅.
3. هر نوشتن یک تراکنش کامل دارد، با قفل `sp_getapplock` و `ROLLBACK` در خطا. ردیف نیمه‌کاره نمی‌ماند ✅.
4. 🔴 الگوی ستون‌های سفارش هرگز با سفارشی که **خود نرم‌افزار سازه** ساخته مقایسه نشده است. در `hesab5 t` فقط ۳ سفارش هست و هر ۳ را ربات ما ساخته (با `Status=6808` قدیمی). مقدار درست `Status` هنوز با آزمون GUI (G2) تأیید نشده.
5. 🔴 نرم‌افزار سازه خودش برای شمارهٔ سفارش قفل نمی‌گیرد. اگر کارمند و ربات در یک لحظه سفارش ثبت کنند، احتمال کمی برای **شمارهٔ تکراری** هست.
6. 🔴 هنگام رفتن به سال مالی جدید (hesab6)، شمارهٔ سفارش‌های قدیمی ممکن است به سفارش‌های **دیگران** در DB جدید وصل شود و پیام اشتباه «فاکتور شد» برود.
7. 🔴 حساب سرویس `NT SERVICE\ShopServer` الان **`db_owner`** است. یعنی محدودیتی جز خود کد وجود ندارد. برای production باید نقش حداقلی ساخته شود.
8. 🟠 «حالت آزمایشی» فقط با **نام** دیتابیس (`hesab5 t`) تشخیص داده می‌شود و سرور را بررسی نمی‌کند. «dry-run» هم واقعاً INSERT می‌زند و بعد ROLLBACK می‌کند، پس دیتابیس اصلی را لمس می‌کند.
9. 🟠 شناسهٔ تکرارناپذیری (`Sharhlp='API-<شمارهٔ سفارش در SQLite>'`) اگر فایل SQLite از نو ساخته شود، با سفارش‌های قدیمی تداخل پیدا می‌کند.
10. **مسیر امن:** اول ۷ مورد «باید رفع شود» (بخش ۸). بعد آزمون GUI روی یک **کپی جداگانه** روی سرور اصلی (بخش ۴-ج). در آخر روشن کردن نوشتن با دو کلید و فهرست مجاز DB.

---

## ۱. انتخاب دیتابیس و تعویض سال مالی

### الف) الان دیتابیس چطور انتخاب می‌شود ✅
- **تشخیص خودکار «سال فعال» وجود ندارد.** نام DB فقط از تنظیمات می‌آید:
  - `shopsystem/.env` ← `DB_NAME` که لانچر آن را به `ACCOUNTING_DATABASE` تبدیل می‌کند (`shopsystem/launcher.py:57`).
  - `shopapi/app/config.py:169` ← `ACCOUNTING_DATABASE`. **پیش‌فرض اگر خالی باشد: `"hesab5 t"`** (`config.py:70`).
- در هر کوئری نام DB به‌شکل `[نام].dbo.جدول` می‌آید (`util.py` تابع `quote_identifier`)، پس نام با فاصله مشکلی ندارد.
- ShopAdmin از راه دور **نمی‌تواند** DB را عوض کند. اتصال DB و `ACCOUNTING_WRITE_ENABLED` در فهرست کلیدهای قابل‌ویرایش نیستند (`shopapi/app/control.py:132-160`). عوض کردن DB فقط با ویزارد سرور روی خود PC سرور (`shopadmin/app/server_setup.py:209` `write_config`) یا ویرایش دستی `.env` ممکن است. **این کار درستی است.**

### ب) نام‌ها و کدهای ثابت در کد ✅
| محل | مقدار ثابت |
|---|---|
| `shopapi/app/config.py:70` | پیش‌فرض `accounting_database = "hesab5 t"` |
| `shopapi/app/config.py:265` | `TEST_DATABASE = "hesab5 t"` (حالت آزمایشی) |
| `shopapi/app/accounting_writer.py:50-52` | `PERSON_GROUP=4`، `PERSON_TAF_COMO=13`، `PERSON_TAF_GROUP=59` (گروه مشتریان و حساب معین/تفصیلی) |
| `shopapi/app/accounting_writer.py:341` | `Codf=-100` (سفارش اینترنتی) و `va=0` |
| `shopapi/sql/create_api_user.sql:15,17` | `USE [hesab5 t]` و `DEFAULT_DATABASE=[hesab5 t]` |
| `shopapi/scripts/live_db_check.py:26`، `scripts/e2e_order_dryrun.py:30` | فهرست DBهای مجاز برای اسکریپت آزمون |
| `shopsystem/.env.example:51` | `DB_NAME=hesab5 t` |

**سال (۱۴۰۵) در کد سفارش ثابت نشده است.** تاریخ از تابع خود DB می‌آید: `dbo.MiladiToShamsi(...)` (`accounting_writer.py:334`).

### ج) با ساخته شدن hesab6 چه باید عوض شود
| مورد | چرا | وضعیت |
|---|---|---|
| `DB_NAME` | نام DB سال جدید | قطعی |
| کاربر SQL / دسترسی سرویس در DB جدید | دسترسی در سطح هر DB است؛ DB جدید کاربر ما را ندارد | قطعی |
| `ACCOUNTING_STATUS_CODE` | کدهای `TabaghehBandi` ممکن است در DB جدید فرق کند | ⚠ فرض: احتمالاً کپی می‌شود |
| `ACCOUNTING_USERCODE`، `ACCOUNTING_ANBARCODE`، `STOCK_WAREHOUSES` | کد کاربر و انبار | ⚠ باید در hesab6 با SELECT بررسی شود |
| `PERSON_GROUP/COMO/TAF_GROUP` (کد ثابت) | اگر جدول `gsh` در سال جدید عوض شود، مشتری جدید به حساب اشتباه می‌رود | ⚠ باید `SELECT Code,moe,CodeGTaf FROM gsh WHERE Code=4` در hesab6 بررسی شود |
| شمارهٔ سفارش (`Codlp`) | `MAX+1` روی DB جدید است. **اگر سال جدید از ۱ شروع شود، شماره‌ها با سال قبل تکرار می‌شوند** | 🔴 مشکل پایین را ببینید |
| کد اشخاص (`name_mo.Code`) و کالا (`Kala.Code`) | اتصال مشتری‌های ربات (`users.person_code` در SQLite) و نگاشت مدل‌های سایت و لیست قیمت به این کدها وابسته است | ⚠ فرض: سازه این کدها را به سال جدید منتقل می‌کند. باید تأیید شود |

🔴 **مشکل تعویض سال:** در SQLite فقط `accounting_order_no` (همان `Codlp`) ذخیره می‌شود، **بدون نام DB**. همگام‌سازی فاکتور (`shopapi/app/tracking.py:29-49`) و شمارهٔ فاکتورها (`accounting_reader.py:294`) این شماره‌ها را در **DB فعلی** جستجو می‌کنند. بعد از رفتن به hesab6:
- اگر شماره در DB جدید نباشد، سفارش «حذف‌شده» به نظر می‌رسد (`tracking.py:39-41`).
- اگر شماره **وجود داشته باشد ولی مال کس دیگری باشد**، پیام «فاکتور شد» و شمارهٔ فاکتور به **مشتری اشتباه** می‌رود.

### د) طراحی پیشنهادی (حداقلی و امن)
1. در SQLite برای هر سفارش ثبت‌شده، نام DB هم ذخیره شود (`accounting_db`). همگام‌سازی فاکتور فقط سفارش‌هایی را بررسی کند که `accounting_db` آن‌ها با DB فعلی برابر است. سفارش‌های سال قبل یا «بسته» شوند یا از DB قبلی (فقط‌خواندنی) خوانده شوند.
2. یک تنظیم جدید: `ACCOUNTING_ALLOWED_DATABASES=hesab6` (فهرست مجاز). نوشتن فقط وقتی مجاز باشد که نام DB در این فهرست باشد.
3. بررسی سلامت قبل از نوشتن (یک بار در شروع و هر ساعت): وجود جدول‌ها و ستون‌های لازم، `gsh` گروه ۴ برابر ۱۳/۵۹، `ANBAR` شامل کد انبار، و برابر بودن سال `MAX(Fact.Date1)` با سال انتظاری. اگر یکی رد شود، نوشتن قفل شود و پیام فارسی دقیق نمایش داده شود.
4. تعویض DB فقط با ویزارد سرور (محلی و با UAC). بعد از تعویض، نوشتن **خودکار خاموش** بماند تا مدیر یک «تأیید بعد از تعویض سال» بزند.
5. اسکریپت ساخت کاربر SQL پارامتر `-Database` داشته باشد، نه `USE [hesab5 t]` ثابت.

---

## ۲. ممیزی مسیر نوشتن (مهم‌ترین بخش)

### الف) چه کسی و چه زمانی می‌نویسد ✅
- تنها فایلی که در DB حسابداری می‌نویسد `shopapi/app/accounting_writer.py` است. در `shopapi/app` هیچ `INSERT/UPDATE/DELETE` دیگری روی DB حسابداری نیست (جستجوی کامل).
- **ربات‌ها هیچ‌وقت مستقیم نمی‌نویسند.** نوشتن فقط با دو کار کارمند در ShopAdmin انجام می‌شود:
  1. «تأیید پرداخت» ← `POST /admin/orders/{id}/approve-payment` ← `writer.write_order` (`routers/admin.py:252`)
  2. «تأیید مشتری بدون کد شخص» ← `POST /admin/users/{id}/approve` ← `writer.create_person` (`routers/admin.py:119`)

### ب) سفارش / پیش‌فاکتور
| جدول | ستون‌هایی که نوشته می‌شود (`accounting_writer.py:29-37`، `:338-353`) | مقدار | منبع حقیقت |
|---|---|---|---|
| `KalaOrder` (۱ ردیف) | `Codlp` | `MAX(Codlp)+1` زیر قفل | ✅C از کد برنامه و ربات رسمی (مرجع §4.1، §4.2) |
| | `Codnlp` | کد شخص مشتری | ✅C |
| | `Datelp` | `MiladiToShamsi(امروز)` | ✅C/T |
| | `Mablp` | Σ(تعداد×قیمت)، بدون گرد کردن | ✅C (§4.4) |
| | `Sharhlp` | `'API-<شمارهٔ سفارش ما>'` | طراحی ما (برای جلوگیری از ثبت تکراری) |
| | `Codf=-100`، `va=0` | سفارش اینترنتی/فروش | ✅C |
| | `takhfif=0`، `avarez=0`، `keraye=0`، `Naghd=0`، `Ischeck=0`، `tavasot=''` | | ✅C (ماژول Woo خود برنامه؛ §4.2) |
| | `Status` | `ACCOUNTING_STATUS_CODE` (پیش‌فرض `0`) | ⚠ **فرض** (§4.5؛ آزمون G2 انجام نشده) |
| | `PrintCount=0`، `usercode=ACCOUNTING_USERCODE` | | `usercode` ✅C؛ مقدار `1` ⚠ فرض |
| | **نوشته نمی‌شود (NULL):** `Taf2, Ras, UseUser, NetOrder, num_hav, bank_hav, Field1-5, order_code_ste_seconed` | | ✅C برای `UseUser`؛ بقیه ⚠ |
| `KalaOrderDetail` (n ردیف) | `Num` (۱..n)، `Codlp_`، `Codekala`، `Meg`، `Gey`، `sharh=''`، `AnbarCode`، `PrintCount=0`، `takhfif=0`، `field1..8=''` | | ✅C (§5.2)؛ `AnbarCode` = کمترین کد `ANBAR` (اینجا ۱ ✅ SELECT) |

### ج) مشتری جدید (`create_person`، `accounting_writer.py:222-281`)
`name_mo` (۳۳ ستون + ۲۶ ستون متنی خالی) ← `taf` (identity) ← `UPDATE name_mo.codetaf` ← `DetailTBL` (موبایل، نوع ۳).
منبع: ✅T در مرجع §5.1، مقایسه با شخصی که خود نرم‌افزار ساخته بود. تنها تفاوت `Ch_Etebar_chek` بود. قبل از ساخت، داخل همان تراکنش موبایل جستجو می‌شود (R4) تا شخص تکراری ساخته نشود ✅ (`:229-232`).

### د) فاکتور فروش
**هیچ نوشتنی وجود ندارد** ✅. فقط خواندن انجام می‌شود: `facto.ordercode/Meg` برای وضعیت (`accounting_reader.py:260-292`) و `facto.Numfact` (`:294-319`). فاکتور را اپراتور در سازه می‌سازد.

### هـ) تراکنش، قفل، شماره‌گذاری، ثبت تکراری
| موضوع | وضعیت | شاهد |
|---|---|---|
| تراکنش | `autocommit=False` و یک تراکنش برای سربرگ و همهٔ اقلام | `accounting_writer.py:159` |
| بازگشت در خطا | هر خطا ← `rollback()`. اگر برنامه وسط کار crash کند، SQL Server تراکنش باز را خودش برمی‌گرداند ✅ | `:166-178` |
| قفل | `sp_getapplock 'shop:KalaOrder'` (و `'shop:name_mo'`) با مالکیت تراکنش و ۱۵ ثانیه مهلت | `:41-44`، `:305`، `:227` |
| شماره | `MAX(Codlp)+1` **بعد از** قفل؛ بعد از درج `COUNT(*)=1` بررسی می‌شود | `:329-365` |
| ثبت تکراری (سمت حسابداری) | قبل از درج: `SELECT MAX(Codlp) WHERE Sharhlp='API-<id>'`. اگر بود، همان برگردانده می‌شود | `:309-327` |
| ثبت تکراری (سمت ربات) | `Idempotency-Key` به مدت ۲۴ ساعت در SQLite. همان کلید و همان مشتری ← همان سفارش | `routers/public.py:253-279`، `db_own.py:427-445` |
| دو تأیید همزمان پرداخت | `db.reservation_guard()` + وضعیت `receipt_uploaded` | `routers/admin.py:217-226` |
| `Status=0` | از تنظیمات خوانده می‌شود. 🔴 **۳ سفارش موجود در `hesab5 t` مقدار `6808` دارند** (کدی که وجود ندارد) ✅ SELECT | |
| تلاش دوباره | در خطای ۱۲۲۲ (مهلت قفل) یک بار دوباره امتحان می‌شود | `:169-174` |

### و) ریسک‌های پیدا شده
| # | ریسک | شدت |
|---|---|---|
| W1 | **مقایسه با سفارش واقعی سازه انجام نشده.** در `hesab5 t` همهٔ ۳ سفارش مال ماست ✅ SELECT. پس `Status`، `usercode`، `NetOrder` و `Ras` که خود برنامه می‌نویسد هنوز فرض است | 🔴 |
| W2 | **همزمانی با خود سازه:** برنامه `MAX+1` را بدون قفل می‌زند. قفل ما فقط ربات‌ها را با هم هماهنگ می‌کند. بررسی `COUNT=1` فقط تکراری‌هایی را می‌گیرد که *قبل از* commit ما درج شده باشند. ⚠ فرض: پنجرهٔ خطر چند میلی‌ثانیه است | 🔴 (احتمال کم، اثر زیاد) |
| W3 | **شناسهٔ `API-<id>`:** شمارهٔ سفارش SQLite است. اگر `shopapi.db` از نو ساخته شود (نصب دوباره یا بازیابی پشتیبان قدیمی)، سفارش ۱ِ جدید با `API-1` قدیمی یکی حساب می‌شود و **ثبت نمی‌شود**، ولی در فروشگاه «ثبت‌شده» نشان داده می‌شود (`admin.py:258`). در بررسی ثبت تکراری کد مشتری (`Codnlp`) چک نمی‌شود | 🔴 |
| W4 | تعویض سال (بخش ۱) | 🔴 |
| W5 | **dry-run واقعاً INSERT می‌زند** و بعد ROLLBACK می‌کند (`:366`). روی production یعنی قفل گرفتن روی جدول‌های واقعی، نیاز به دسترسی INSERT، و دیده شدن ردیف commit‌نشده توسط خواننده‌های `NOLOCK` در سازه (⚠ فرض: سازه از NOLOCK استفاده می‌کند یا نه، معلوم نیست) | 🟠 |
| W6 | **رنگ گوشی به حسابداری نمی‌رود:** قلم‌های رنگ‌دار با `sharh=''` نوشته می‌شوند (`admin.py:251`، `:350`) و موجودی سازه هم برایشان بررسی نمی‌شود (`admin.py:235-236`). اپراتور در سازه رنگ را نمی‌بیند | 🟠 |
| W7 | اگر `AccountingLockTimeout` رخ دهد، در `approve_payment` گرفته نمی‌شود و خطای ۵۰۰ برمی‌گردد (در `create_person` گرفته می‌شود: `admin.py:120`) | 🟡 |
| W8 | ستون‌هایی که سازه پس از ثبت به‌روز می‌کند و ما نه: `Kala.Mogod` (فقط بعد از فاکتور تغییر می‌کند، پس برای سفارش لازم نیست ✅)، کش ماندهٔ `name_mo` (برای سفارش لازم نیست). **جدول شمارنده یا لاگ جداگانه برای سفارش در DB پیدا نشد** (مرجع §1: شماره‌ها `MAX+1` هستند) ✅C. ⚠ فرض: لاگ داخلی برنامه (مثل جدول‌های audit) در ثبت دستی سفارش نوشته نمی‌شود. این را فقط G2 روشن می‌کند | 🟠 |
| W9 | ردیف یتیم: SELECT روی `hesab5 t` ← ۰ قلم بدون سربرگ، ۰ سربرگ بدون قلم، ۰ عدم‌تطابق `Mablp`، ۰ شمارهٔ تکراری، ۰ سفارش بدون شخص ✅ | ✓ |
| W10 | اسکریپت `scripts/live_db_check.py` با `dry_run=False` شخص می‌سازد و بعد **DELETE** می‌کند (`:109-148`). فقط روی سرور `.\sqlexpress` با DB `hesab5` یا `hesab5 t` اجرا می‌شود. 🟠 اگر روزی production روی `.\SQLEXPRESS` و با نام `hesab5` باشد، این اسکریپت در دفاتر واقعی می‌نویسد و پاک می‌کند. ۵ شخص آزمایشی با موبایل `0999…` در `hesab5 t` باقی مانده ✅ SELECT | 🟠 |

---

## ۳. دروازه‌های ایمنی

### الف) منطق دقیق ✅ (`shopapi/app/config.py:263-274`)
```python
TEST_DATABASE = "hesab5 t"
def is_test_db(self):  return self.accounting_database.strip().lower() == "hesab5 t"
def write_allowed(self):
    if self.is_test_db(): return True                       # حالت آزمایشی: بدون هیچ کلیدی
    allowed = {h.lower() for h in self.accounting_allowed_hosts}   # پیش‌فرض: localhost و .\SQLEXPRESS
    return self.accounting_write_enabled and self.accounting_server.lower() in allowed
```
- نویسنده وقتی `dry_run` داده نشود از `write_allowed()` استفاده می‌کند (`accounting_writer.py:148-149`، `:204-205`). هر دو endpoint `dry_run` نمی‌دهند (`admin.py:119`، `:252`).
- **اثبات:** حالت آزمایشی فقط یک شرط دارد: نام DB برابر `hesab5 t` (بدون توجه به حروف بزرگ و کوچک). برای هر نام دیگر، اجرا به خط دوم می‌رسد که **هم** `ACCOUNTING_WRITE_ENABLED=true` (پیش‌فرض `false`، `config.py:80,179`) **و هم** بودن سرور در فهرست میزبان‌های مجاز را می‌خواهد. پس اگر حالت آزمایشی تنها دلیل اجازه باشد، نوشتن روی DB دیگر ممکن نیست ✅.
- **ولی** حالت آزمایشی سرور را بررسی نمی‌کند. اگر `DB_SERVER` به سرور اصلی اشاره کند و آنجا DBای به نام `hesab5 t` باشد (مثلاً کپی آزمایشی‌ای که برای آزمون GUI بازیابی شده)، نوشتن بدون هیچ کلیدی آزاد است. این تا وقتی بی‌خطر است که آن DB واقعاً کپی باشد.

### ب) اگر `DB_NAME` اشتباه تایپ شود یا به DB واقعی اشاره کند
| حالت | نتیجه |
|---|---|
| نام وجود ندارد (مثلاً `hesab5t`) | اتصال با خطای 4060 رد می‌شود. نه خواندن و نه نوشتن. پایش فقط «SQL در دسترس نیست» نشان می‌دهد (علت گفته نمی‌شود، بخش ۶) |
| خالی | پیش‌فرض `hesab5 t` ← **حالت آزمایشی فعال می‌شود** (`config.py:70`). روی سرور اصلی که این DB را ندارد، اتصال رد می‌شود |
| `hesab5` (DB واقعی) و `ACCOUNTING_WRITE_ENABLED=false` | فقط dry-run، یعنی INSERT و بعد ROLLBACK (W5) |
| `hesab5` و `true` و سرور `.\SQLEXPRESS` | 🔴 **نوشتن واقعی.** فهرست میزبان پیش‌فرض شامل `.\SQLEXPRESS` است. اگر SQL اصلی روی همان PC سرور باشد، فهرست میزبان هیچ محافظتی نمی‌دهد. ⚠ فرض: production طبق مرجع `192.168.20.150\SAZEHHESAB` است، پس آنجا `.\SAZEHHESAB` باید دستی به فهرست اضافه شود که یک قدم آگاهانه است |

### ج) محافظ‌های پیشنهادی
1. 🔴 **فهرست مجاز DB:** `ACCOUNTING_ALLOWED_DATABASES`. حالت آزمایشی فقط وقتی معتبر باشد که **هم** نام `hesab5 t` باشد **و هم** سرور محلی (`.\SQLEXPRESS`/`localhost`).
2. 🔴 **بررسی پیش از نوشتن** (در همان تراکنش): `DB_NAME()` برابر تنظیمات، وجود ستون‌های لازم (`sys.columns`)، `gsh` گروه ۴ = ۱۳/۵۹، `ANBAR` شامل کد انبار. اگر رد شد ← ROLLBACK و قفل نوشتن.
3. 🟠 **dry-run بدون لمس:** حالت `ACCOUNTING_WRITE_MODE=off|dryrun|live`. حالت `off` (پیش‌فرض برای production) فقط SELECT کند و INSERT نزند.
4. 🟠 **کلید قطع اضطراری:** دکمه‌ای در ShopAdmin (کاربر مدیر کل) که فقط بتواند نوشتن را *خاموش* کند (نه روشن). روشن کردن فقط روی سرور.
5. 🟠 **سقف مبلغ و تعداد در هر سفارش** (مثلاً `MAX_ORDER_AMOUNT_RIAL`) برای جلوگیری از اشتباه بزرگ.
6. 🟡 هشدار قرمز در ShopAdmin وقتی «نوشتن واقعی روی DB غیرآزمایشی» فعال است، همراه با نام DB و سرور.
7. 🟡 در اسکریپت‌های آزمون، `hesab5` از فهرست مجاز حذف شود (W10).

---

## ۴. برنامهٔ راستی‌آزمایی بدون دانگل

### الف) آماده‌سازی (روی همین PC، فقط `hesab5 t`)
1. یک پشتیبان `COPY_ONLY` از `hesab5 t` بگیرید تا هر وقت خواستید به حالت اول برگردید.
2. اسنپ‌شات قبل/بعد با ابزار موجود: `research_tools/sazeh_snapshot.py save|diff` (مرجع §10). داده‌های شخصی را ماسک می‌کند.
3. دادهٔ آزمایشی: ۲ مشتری با موبایل‌های `09990000001` و `09990000002` (یکی را با ربات و یکی با ShopAdmin بسازید)، ۳ کالا (یکی با موجودی زیاد، یکی با موجودی ۱، یکی با موجودی ۰)، و یک مشتری بدهکار موجود (فقط کد آن را بردارید).

### ب) کوئری‌های فقط‌خواندنی پس از هر کار
```sql
USE [hesab5 t];
-- 1) سربرگ و اقلام سفارش ما (X = شمارهٔ سفارش در ShopAdmin)
SELECT Codlp,Codnlp,Datelp,Mablp,Codf,va,Status,usercode,takhfif,avarez,keraye,Naghd,Ischeck,
       PrintCount,UseUser,NetOrder,Ras,Taf2,LEN(tavasot) tav_len
FROM dbo.KalaOrder WHERE Sharhlp = 'API-' + CAST(@X AS varchar(12));
SELECT d.* FROM dbo.KalaOrderDetail d JOIN dbo.KalaOrder h ON h.Codlp=d.Codlp_
WHERE h.Sharhlp = 'API-' + CAST(@X AS varchar(12)) ORDER BY d.Num;
-- 2) سلامت کلی (همه باید 0 باشند)
SELECT (SELECT COUNT(*) FROM (SELECT Codlp FROM dbo.KalaOrder GROUP BY Codlp HAVING COUNT(*)>1) a) dup_codlp,
       (SELECT COUNT(*) FROM (SELECT Sharhlp FROM dbo.KalaOrder WHERE Sharhlp LIKE 'API-%' GROUP BY Sharhlp HAVING COUNT(*)>1) b) dup_api,
       (SELECT COUNT(*) FROM dbo.KalaOrderDetail d WHERE NOT EXISTS (SELECT 1 FROM dbo.KalaOrder h WHERE h.Codlp=d.Codlp_)) orphan_lines,
       (SELECT COUNT(*) FROM dbo.KalaOrder h WHERE NOT EXISTS (SELECT 1 FROM dbo.KalaOrderDetail d WHERE d.Codlp_=h.Codlp)) empty_headers,
       (SELECT COUNT(*) FROM dbo.KalaOrder h WHERE ABS(ISNULL(h.Mablp,0)-ISNULL((SELECT SUM(Meg*Gey) FROM dbo.KalaOrderDetail d WHERE d.Codlp_=h.Codlp),0))>0.5) bad_total,
       (SELECT COUNT(*) FROM dbo.KalaOrder h WHERE NOT EXISTS (SELECT 1 FROM dbo.name_mo p WHERE p.Code=h.Codnlp)) no_person;
-- 3) موجودی و رزرو یک کالا (K): موجودی نباید با «سفارش» تغییر کند؛ فقط «مانده سفارش» بالا می‌رود
SELECT (SELECT SUM(ISNULL(Megv,0))-SUM(ISNULL(Megs,0)) FROM dbo.kardex_an WHERE Codekala=@K) stock,
       (SELECT Mogod FROM dbo.Kala WHERE Code=@K) mogod_cache,
       (SELECT SUM(d.Meg) FROM dbo.KalaOrderDetail d JOIN dbo.KalaOrder h ON h.Codlp=d.Codlp_ AND ISNULL(h.va,0)=0 WHERE d.Codekala=@K) ordered;
-- 4) مشتری جدید (P = کد): پیوند name_mo↔taf↔DetailTBL (بدون نام و تلفن)
SELECT n.Code,n.Gcod,n.l_gey,n.codetaf,t.Cota,t.como,t.codgtaf,t.va,
       (SELECT COUNT(*) FROM dbo.DetailTBL WHERE IDMaster=n.Code AND Va=0 AND TabaghehBandiID IN (1,3)) phones
FROM dbo.name_mo n LEFT JOIN dbo.taf t ON t.Code=n.codetaf WHERE n.Code=@P;
-- 5) جدول‌هایی که «نباید» تغییر کنند (قبل و بعد مقایسه شود)
SELECT 'Fact' t,COUNT(*) n,CHECKSUM_AGG(BINARY_CHECKSUM(*)) cs FROM dbo.Fact UNION ALL
SELECT 'facto',COUNT(*),CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.facto UNION ALL
SELECT 'kardex_an',COUNT(*),CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.kardex_an UNION ALL
SELECT 'KOL',COUNT(*),CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.KOL UNION ALL
SELECT 'Kala',COUNT(*),CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.Kala UNION ALL
SELECT 'havale',COUNT(*),CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.havale UNION ALL
SELECT 'KalaOrder',COUNT(*),CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.KalaOrder UNION ALL
SELECT 'KalaOrderDetail',COUNT(*),CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.KalaOrderDetail UNION ALL
SELECT 'name_mo',COUNT(*),CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.name_mo UNION ALL
SELECT 'taf',COUNT(*),CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.taf UNION ALL
SELECT 'DetailTBL',COUNT(*),CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM dbo.DetailTBL;
```
**روش قبل/بعد:** کوئری ۵ را قبل و بعد اجرا کنید. پس از یک سفارش n‌قلمی فقط باید `KalaOrder` ۱+ و `KalaOrderDetail` n+ شود. پس از ساخت مشتری فقط `name_mo`، `taf` و `DetailTBL` هر کدام ۱+ شوند. چک‌سام بقیه باید **دقیقاً یکسان** بماند. (`BINARY_CHECKSUM` کامل نیست ولی برای «تغییر نکرد» کافی است. برای مقایسهٔ کامل از `sazeh_snapshot.py` استفاده کنید.)

### ج) موارد مرزی
| آزمون | انتظار |
|---|---|
| چند قلم (۳ کالا) | ۳ ردیف `Num=1,2,3`؛ `Mablp` = جمع |
| موجودی صفر | ربات خطای «موجودی کافی نیست» می‌دهد؛ هیچ ردیفی ساخته نمی‌شود |
| مشتری بدهکار | سفارش ثبت می‌شود (سقف اعتبار بررسی نمی‌شود ⚠ تصمیم کسب‌وکار)؛ گردش حساب منفی نشان داده می‌شود |
| تعداد زیاد (> `MAX_ORDER_QTY`) | ۴۲۲ و بدون ردیف |
| ارسال دوباره (دو بار زدن دکمه) | همان سفارش ربات (`Idempotency-Key`)؛ تأیید پرداخت دوباره ← ۴۰۹ |
| دو سفارش همزمان | دو `Codlp` متوالی و بدون تکرار (دو ShopAdmin همزمان «تأیید پرداخت» بزنند) |
| crash وسط نوشتن | سرویس را وسط کار متوقف نکنید (محدودیت این ممیزی). به‌جای آن: `pytest` موجود برای ROLLBACK + یک آزمون دستی که اتصال SQL را با `KILL` قطع می‌کند (فقط روی `hesab5 t`، توسط مالک). انتظار: ۰ ردیف و سفارش هنوز `receipt_uploaded` |
| بازسازی SQLite (W3) | `shopapi.db` آزمایشی جدید ← سفارش ۱ ← باید ثبت شود، نه «idempotent» (الان شکست می‌خورد) |

### د) اسکریپت «مورد انتظار در برابر واقعی» (طرح)
`research_tools/compare_order_pattern.py --ours API-123 --golden <Codlp>`:
1. هر دو سفارش را (سربرگ و اقلام) با `SELECT *` بخواند.
2. برای هر ستون یک «الگو» بسازد: `NULL` / `''` / `0` / مقدار ثابت / عدد مثبت / تاریخ `^\d{4}/\d{2}/\d{2}$` / متن.
3. ستون‌های متغیر نادیده گرفته شوند: `Codlp, Codlp_, Codnlp, Datelp (فقط الگو), Mablp, Sharhlp (متن), Meg, Gey, Codekala`.
4. خروجی: جدول ستون به ستون با ✓/✗. هر ✗ یعنی ما چیزی متفاوت با خود برنامه می‌نویسیم.

⚠ **مشکل:** در `hesab5 t` هیچ سفارشی که سازه ساخته باشد وجود ندارد (SELECT: ۳ سفارش، همه `API-`). نمونهٔ طلایی باید از یکی از این‌ها بیاید: (۱) آزمون GUI G2 (پایین)، یا (۲) اگر خودتان صلاح دانستید، `SELECT COUNT(*) FROM [hesab5].dbo.KalaOrder WHERE Sharhlp NOT LIKE 'API-%'` روی نسخهٔ پشتیبان. این را من اجرا نکردم.

### هـ) کارهایی که **فقط** داخل خود سازه ممکن است
- باز کردن سفارش ما در فرم «سفارش‌ها» (نمایش درست، وضعیت، جمع، قفل `UseUser`).
- تبدیل سفارش به فاکتور (کامل و جزئی) و بررسی `facto.ordercode/orderdetailcode`.
- گزارش «رزرو / مانده سفارش» (`spTotalObject`) با `Status=0`.
- حذف سفارش و اثر آن.
- تعیین مقدار درست `Status/usercode/NetOrder` (G2).

**روش امن روی سرور اصلی (بدون دور زدن قفل سخت‌افزاری):**
1. از راه دور (Remote Desktop) و با هماهنگی DBA: یک پشتیبان `COPY_ONLY` از `hesab5 t` (یا از production) را با **نام جدا** (مثلاً `hesab5_shoptest`) روی همان SQL بازیابی کنید. DB اصلی دست نخورد.
2. یک **کپی** از پوشهٔ برنامهٔ سازه بسازید و فقط در `Data1\Options.ini` *همان کپی* DB را `hesab5_shoptest` بگذارید. `Options.ini` اصلی را هرگز عوض نکنید. دانگل همان دانگل قانونی سرور است و دور زده نمی‌شود. ⚠ فرض: سازه اجازهٔ انتخاب DB با نام دلخواه را می‌دهد (سؤال ۴).
3. یک shopapi آزمایشی (پورت و SQLite جدا) به `hesab5_shoptest` وصل کنید. بعد از اضافه شدن محافظ ۳-ج-۱، این DB را صریحاً در فهرست مجاز بگذارید. با ربات آزمایشی سفارش بسازید، بعد در سازه مراحل G1 تا G4 (مرجع §10) را اجرا کنید و قبل و بعد هر قدم `sazeh_snapshot.py` بگیرید.
4. در پایان DB آزمایشی را حذف کنید (توسط DBA) و کپی برنامه را پاک کنید.

---

## ۵. مشتریان و ربات

### الف) تأیید مشتری ✅
1. ثبت‌نام فقط با «اشتراک شمارهٔ خود» در بله پذیرفته می‌شود. اگر شماره مال کس دیگری باشد، رد می‌شود (`shopbots/app/core/customers.py:3-5,71`).
2. `POST /users/register` ← موبایل نرمال‌سازی می‌شود (`mobile_key`، ۱۰ رقم آخر) ← **تطبیق خودکار** (`routers/public.py:48-67,208`):
   - R4: `DetailTBL` با `Va=0`، نوع ۱ یا ۳، ۱۰ رقم آخر (`accounting_reader.py:24-36`). `TOP 2` برمی‌گرداند.
   - دقیقاً **۱** نتیجه و آن کد به مشتری دیگری وصل نباشد ← خودکار «تأییدشده».
   - **۲ نتیجه (شمارهٔ مشترک)** ← معلق؛ کارمند انتخاب می‌کند (`accounting_reader.py:246-248`).
   - کد قبلاً به کاربر دیگری وصل باشد و `ALLOW_SHARED_PERSON_CODE=false` ← معلق.
   - SQL در دسترس نباشد ← معلق می‌ماند (خطا نمی‌دهد).
3. تأیید دستی در ShopAdmin (`admin.py:139-180`): یا `person_code` داده می‌شود (وجودش در `name_mo` بررسی می‌شود) یا شخص جدید ساخته می‌شود (§2-ج). اگر موبایل در این فاصله پیدا شود، به همان شخص وصل می‌شود. اگر بین چند نفر مشترک باشد ← ۴۰۹ «کد شخص را انتخاب کنید».
4. رد: `status=rejected` ← نمی‌تواند سفارش بدهد (`public.py:249`). مشتری معلق تا `PENDING_MAX_ORDER_ITEMS` قلم سفارش می‌دهد ولی **تا تأیید نشود در حسابداری ثبت نمی‌شود** (`admin.py:227-229`).

### ب) گردش حساب ✅
- کوئری: `accounting_reader.py:321-364` روی جدول `KOL` با `Noa='m' AND Codkol=<کد شخص> AND NOT (Va=N'غ' AND Cod_n IN (-1003,-1005))`. حداکثر ۲۰۰۰ ردیف آخر خوانده می‌شود، ولی جمع از **همهٔ** ردیف‌ها حساب می‌شود.
- محاسبه (`shopapi/app/statement.py:1-47`): مانده = Σبستانکار (`Bes`) − Σبدهکار (`Bed`). **منفی = مشتری بدهکار است.** مقدار نمایشی قدر مطلق است با برچسب بدهکار/بستانکار. کمتر از ۰٫۵ = «تسویه».
- واحد پول: همان عددی که در `KOL` (نوع `money`) هست، بدون تبدیل. ربات «ریال» نشان می‌دهد (`shopbots/app/messages.fa.json:22`). ⚠ فرض: سازه مبالغ را به ریال ذخیره می‌کند. با یک فاکتور شناخته‌شده مقایسه کنید.
- این فرمول در مرجع §3 با کش ماندهٔ خود نرم‌افزار در ۱۰۸۳ از ۱۰۸۴ شخص برابر بود ✅T.
- **کوئری مستقل برای مقایسه (فقط‌خواندنی، یک مشتری):**
```sql
USE [hesab5 t];
DECLARE @code int = 0;  -- کد شخص را بگذارید
SELECT SUM(ISNULL(Bed,0)) AS jam_bedehkar, SUM(ISNULL(Bes,0)) AS jam_bestankar,
       SUM(ISNULL(Bes,0)) - SUM(ISNULL(Bed,0)) AS mande,   -- منفی = بدهکار
       CASE WHEN ABS(SUM(ISNULL(Bes,0)) - SUM(ISNULL(Bed,0))) < 0.5 THEN N'تسویه'
            WHEN SUM(ISNULL(Bes,0)) - SUM(ISNULL(Bed,0)) < 0 THEN N'بدهکار' ELSE N'بستانکار' END AS vaziat,
       COUNT(*) AS tedad_radif
FROM dbo.KOL
WHERE Noa = 'm' AND Codkol = @code AND NOT (Va = N'غ' AND Cod_n IN (-1003, -1005));
```
عدد `mande` باید با «مانده» در ربات (و با گزارش مانده در خود سازه) یکی باشد.
- 🟡 در ربات فقط `Va='f'` برچسب «فاکتور فروش» دارد و بقیه «سند» نمایش داده می‌شوند (`statement.py:7`)، در حالی که در DB انواع دیگری هم هست: `8, w, r, t, س, n, u, o, a, ^, Z, ش` ✅ SELECT. بهتر است برچسب‌ها کامل شوند.

### ج) ربات آزمایشی جداگانهٔ بله
- تنظیمات لازم (فقط نام‌ها): `BALE_TOKEN` (توکن ربات **آزمایشی** جدید از BotFather بله)، `BOT_API_KEY` (یکسان در shopapi و shopbots)، `SHOPAPI_BASE_URL`، `ADMIN_CHAT_IDS`، و برای shopapi آزمایشی: `SQLITE_PATH` جدا، پورت جدا، `DB_NAME=hesab5 t`.
- ⚠ اگر shopapi آزمایشی با همان `shopapi.db` واقعی اجرا شود، مشتری‌ها و سفارش‌ها قاطی می‌شوند. حتماً SQLite جدا بگذارید.

| رفتار ربات | نوع |
|---|---|
| فهرست کالا، جستجو، قیمت، موجودی، گروه‌ها | فقط‌خواندنی (SQL) |
| گردش حساب، پیگیری سفارش، شمارهٔ فاکتور | فقط‌خواندنی (SQL) |
| ثبت‌نام، تطبیق خودکار | نوشتن فقط در SQLite؛ SQL فقط خوانده می‌شود |
| سبد، ساخت سفارش، رزرو ۱۲ ساعته، رسید | نوشتن فقط در SQLite و فایل |
| **ثبت در حسابداری** | **فقط با دکمهٔ کارمند در ShopAdmin**، نه ربات |

---

## ۶. دسترسی حساب سرویس در SQL

### وضعیت فعلی ✅ (SELECT روی `hesab5 t`)
- `NT SERVICE\ShopServer` ← `WINDOWS_USER` و عضو **`db_owner`**. یعنی می‌تواند هر جدولی را بخواند، تغییر دهد یا حذف کند، از جمله `setting` (رمز پنل پیامک) و `Geyk` (قیمت خرید). 🔴 برای production قابل قبول نیست.
- پایش سلامت علت خطا را **دور می‌ریزد**: `monitor.py:85-90` هر استثنایی را فقط `False` می‌کند. برای همین پیام فقط «SQL در دسترس نیست» بود.

### طراحی نقش حداقلی (سازگار با 2008 R2)
```sql
-- اجرا توسط sysadmin، روی DB سال جاری (پارامتر، نه ثابت)
CREATE LOGIN [NT SERVICE\ShopServer] FROM WINDOWS;          -- اگر نیست
USE [<DB>];
CREATE USER [NT SERVICE\ShopServer] FOR LOGIN [NT SERVICE\ShopServer];
CREATE ROLE shop_app;
EXEC sp_addrolemember 'shop_app', 'NT SERVICE\ShopServer';
-- سپس همهٔ GRANT/DENYهای shopapi/sql/create_api_user.sql را به‌جای shopbot به shop_app بدهید
```
| نوع | جدول/شیء |
|---|---|
| **فقط SELECT (ستونی)** | `Kala(Code,Name,Gcod,Gey,Geycf,gey3,gey4,gey5,pic,v1,active,Mogod,hadeaghalmogodi)`، `Gkala(Code,Name,g_kala)`، `vahed`، `ANBAR`، `kardex_an(Codekala,Megv,Megs,Codanbar)`، `facto(Numfact,Codekala,Meg,ordercode,orderdetailcode)`، `name_mo(Code,Gcod,l_gey,codetaf)`، `DetailTBL(IDMaster,TabaghehBandiID,Va,Comment)`، `taf(Code,Cota,codgtaf)`، `KOL(Noa,Codkol,Bed,Bes,Va,Cod_n,Num_kol,Date1,N_sanad,Sharh)` |
| **SELECT + INSERT** | `KalaOrder`، `KalaOrderDetail` (SELECT لازم است برای MAX و بررسی تکراری) |
| **INSERT + UPDATE(`codetaf`,`telephons`)** | `name_mo`؛ INSERT روی `taf` و `DetailTBL` (اگر ساخت مشتری خاموش شود، حذف شوند) |
| **EXECUTE** | `dbo.MiladiToShamsi` (تابع). `sp_getapplock` دسترسی خاصی نمی‌خواهد |
| **DENY** | UPDATE/DELETE روی `KalaOrder*`، DELETE روی `name_mo`، هر تغییری روی `KOL`، و هر دسترسی به `setting`، `Telegram_Setting`، `api_online_setting`، `TabaghehBandi` |
| ⚠ کمبود احتمالی | اگر `Fact` (تاریخ فاکتور) لازم شود: `Fact(Numfact, <ستون تاریخ>)` (PROGRESS.md:88) |

### اسکریپت کمکی پیشنهادی
`shopsystem/deploy/grant_sql_service.ps1 -Server .\SQLEXPRESS -Database "hesab6" [-WhatIf]`:
1. با `sqlcmd -E` (حساب ادمین ویندوز که sysadmin SQL است) فایل SQL بالا را اجرا کند. اگر sysadmin نیست، پیام بدهد «این مرحله را DBA انجام دهد» و فایل SQL را کنار بگذارد.
2. `sql/verify_permissions.sql` را با `EXECUTE AS USER='NT SERVICE\ShopServer'` اجرا کند و نتیجه را سبز یا قرمز نشان دهد.
3. در installer: یک قدم اختیاری «اعطای دسترسی SQL» که این اسکریپت را صدا بزند. **هرگز `db_owner` ندهد.**

### پیام خطای دقیق (پیشنهاد)
در `ping()` و `monitor.probe_sql` شمارهٔ خطای SQL گرفته شود (بدون رمز) و در لاگ و ShopAdmin نمایش داده شود:
| کد | پیام فارسی |
|---|---|
| 18456 | «ورود حساب سرویس به SQL رد شد. اسکریپت grant_sql_service.ps1 را اجرا کنید.» |
| 4060 | «پایگاه‌دادهٔ «X» پیدا نشد یا حساب سرویس به آن دسترسی ندارد. نام DB را در ویزارد سرور بررسی کنید.» |
| 229 / 230 | «دسترسی ناکافی به جدول/ستون Y. نقش shop_app را بررسی کنید.» |
| 53 / 2 / 08001 | «سرور SQL «S» در دسترس نیست (سرویس SQL یا SQL Browser یا دیوار آتش).» |
| HYT00 | «مهلت اتصال تمام شد.» |

---

## ۷. پنل پیامک (فقط تحلیل)
- در DB جدول‌های پیامک هست ✅ (فقط شمارش): `tblSentMessages` (۷۱)، `SmsText` (۱۵)، `tblSmsZSetting` (۷)، و `SmsReport`، `tblInboxMessages`، `tblSentMessagesZ` (۰). اعتبارنامهٔ پنل در `setting` ۴۹۷ تا ۵۰۰ است (**خوانده نشد و نباید خوانده شود**). تنظیم «پیامک هنگام سفارش» (`setting` ۵۶۱/۵۶۲) طبق مرجع §12 برابر ۰ است.
- **تداخل‌های احتمالی (⚠ همه فرض):**
  1. اگر پنل یا سازه هنگام ثبت `KalaOrder` پیامک بفرستد (۵۶۱/۵۶۲ روشن)، سفارش‌های ربات هم پیامک می‌گیرند. ممکن است با پیام ربات تکراری شود.
  2. پنل اگر موبایل‌ها را از `DetailTBL` بخواند، مشتری‌هایی که ما می‌سازیم در فهرست ارسال گروهی قرار می‌گیرند (نیاز به رضایت).
  3. اگر پنل در DB می‌نویسد (مثلاً `tblSentMessages`)، با ما تداخل جدولی ندارد. ما این جدول‌ها را نه می‌خوانیم و نه می‌نویسیم.
  4. مکمل: پیامک «سفارش ثبت شد» یا «فاکتور شد» برای مشتری‌ای که ربات ندارد.
- **اطلاعات لازم قبل از هر اتصال:** نام و سازندهٔ پنل؛ اینکه داخل سازه است یا برنامهٔ جداگانه‌ای که به DB وصل می‌شود؛ چه جدول‌هایی را می‌خواند یا می‌نویسد؛ آیا API یا وب‌سرویس دارد (مستندات)؛ آیا روی سفارش یا فاکتور خودکار پیامک می‌فرستد؛ وضعیت ۵۶۱/۵۶۲ در production.

---

## ۸. چک‌لیست اولویت‌دار

### باید قبل از production رفع شود 🔴
1. [ ] آزمون GUI G1 تا G4 روی کپی جداگانه در سرور اصلی (۴-هـ) + اسکریپت مقایسهٔ الگو (۴-د). تعیین قطعی `Status`، `usercode` و `NetOrder`.
2. [ ] نقش حداقلی `shop_app` به‌جای `db_owner` + اسکریپت grant + `verify_permissions.sql` سبز.
3. [ ] فهرست مجاز DB (`ACCOUNTING_ALLOWED_DATABASES`) + محدود کردن حالت آزمایشی به سرور محلی.
4. [ ] ذخیرهٔ نام DB برای هر سفارش ثبت‌شده و محدود کردن همگام‌سازی فاکتور به همان DB (تعویض سال).
5. [ ] شناسهٔ تکرارناپذیری محکم: `Sharhlp='API-<شناسهٔ نصب>-<id>'` یا بررسی `Codnlp` و `Mablp` هنگام پیدا شدن `Sharhlp` تکراری (W3).
6. [ ] بررسی ساختار و سال پیش از نوشتن (۳-ج-۲).
7. [ ] پیام خطای دقیق SQL در پایش و ShopAdmin (بخش ۶).
8. [ ] تصمیم دربارهٔ همزمانی با ثبت دستی (W2): یا ثبت سفارش فقط در ساعت‌هایی که کارمند سفارش دستی نمی‌زند، یا پس از commit یک بررسی دوبارهٔ `COUNT(Codlp)` و هشدار به مدیر.

### بهتر است 🟠/🟡
- [ ] حالت `off` بدون لمس DB به‌جای dry-run با INSERT (W5).
- [ ] نوشتن رنگ گوشی در `KalaOrderDetail.sharh` (بعد از تأیید G2 که برنامه آن را نمایش می‌دهد) (W6).
- [ ] گرفتن `AccountingLockTimeout` در `approve_payment` و پاسخ ۴۰۹ (W7).
- [ ] حذف `hesab5` از فهرست مجاز `live_db_check.py` و پاکسازی ۵ شخص آزمایشی `0999…` در `hesab5 t` (W10).
- [ ] اصلاح `Status=6808` در ۳ سفارش آزمایشی قدیمی، یا حذف آن‌ها از داخل سازه.
- [ ] کلید قطع اضطراری (فقط خاموش کردن) در ShopAdmin، و سقف مبلغ هر سفارش.
- [ ] برچسب کامل انواع سند در گردش حساب.

---

## ۹. سؤال‌هایی که باید جواب بدهید
1. در سال مالی جدید، سازه کد اشخاص، کالاها و انبارها را **همان** نگه می‌دارد؟ سفارش‌های باز سال قبل به DB جدید منتقل می‌شوند؟ شمارهٔ سفارش از ۱ شروع می‌شود؟
2. production دقیقاً کجاست؟ (نام سرور/instance، و آیا ShopSystem روی همان PC نصب می‌شود؟) نام DB سال جاری آنجا چیست؟
3. آیا کارمندان در سازه هم «سفارش کالا» دستی ثبت می‌کنند؟ چند بار در روز؟ (برای ریسک W2)
4. آیا سازه اجازه می‌دهد در یک کپی از برنامه، DB با نام دلخواه (مثلاً `hesab5_shoptest`) انتخاب شود؟ آیا دانگل محدودیتی روی تعداد یا نام DB دارد؟
5. چه کسی روی سرور اصلی sysadmin SQL است (برای اجرای اسکریپت دسترسی)؟
6. مبالغ در سازه ریال است یا تومان؟ (برای گردش حساب)
7. سقف اعتبار مشتری بدهکار باید جلوی سفارش را بگیرد؟
8. رنگ گوشی باید در سفارش حسابداری دیده شود؟ کجا (شرح ردیف)؟
9. پنل پیامک: نام، نوع اتصال (داخل سازه یا جدا)، API، و اینکه پیامک خودکار سفارش روشن است یا نه.
10. آیا ربات رسمی سازه (`Telegram_Bot.exe`) هنوز روی production کار می‌کند؟ (برای همزمانی شماره‌گذاری سفارش)
