# SAZEH_DB_REFERENCE — پایگاه‌دادهٔ «سازه حساب» برای سیستم فروشگاه

> مرجع دائمی حاصل مهندسی معکوس (2026-10-10). هدف: دیگر نیازی به تکرار این پژوهش نباشد.
> **هیچ داده شخصی (نام/تلفن/آدرس) و هیچ توکن/رمزی در این سند نیست.** نمونه‌ها فقط کد عددی یا ساختار هستند.

## 0. روش و درجهٔ اطمینان

| نشان | معنی |
|---|---|
| ✅ T | با آزمایش روی نسخهٔ تست (`hesab5` محلی، SQL 2019 با compat level 100) اثبات شد |
| ✅ C | از کد خود نرم‌افزار (رشته‌های SQL داخل `Sazeh Hesab Integrated 1405.06.05.exe` پس از باز کردن بستهٔ UPX، و `Telegram_Bot.exe` پس از دیس‌اسمبل IL) یا از کد پروسیجرهای DB خوانده شد |
| ⚠ | نامطمئن / فرض / نیازمند تأیید با GUI |

**منابع پژوهش**
1. اسکیمای زنده: ۴۷۰ جدول، ۲۱ view، ۲۶۳ پروسیجر، ۷۱ تابع، ۱۴ تریگر (همه تعریف‌ها خوانده/جستجو شد).
2. `D:\sazeh_hesab\SazehHesab_Bot\Telegram_Bot.exe` (ربات رسمی؛ .NET 6 + EF Core): IL دیس‌اسمبل شد → منطق دقیق ثبت‌نام/سفارش.
3. فایل اصلی برنامه (Delphi، بستهٔ UPX 3.08/NRV2E): روی **کپی در حافظه** باز شد (`research_tools/upx_unpack_readonly.py`، فقط‌خواندنی؛ فایل اصلی دست نخورد و برنامه **اجرا نشد** چون `Data1\Options.ini` به سرور production اشاره می‌کند). رشته‌های SQL آن استخراج شد.
4. آزمایش‌های نوشتن روی `hesab5` (پیش از شروع از آن `BACKUP … COPY_ONLY` گرفته شد؛ در پایان **بازیابی شد** و با اسنپ‌شات چک‌سام همهٔ ۴۷۰ جدول با حالت اولیه یکسان تأیید شد). `hesab5 t` (نسخهٔ توسعهٔ shopapi) **اصلاً لمس نشد**. سرور production لمس نشد.
5. همهٔ SQLها سازگار با SQL Server 2008 R2 نوشته شدند: بدون `OFFSET/FETCH`، `STRING_AGG`، `CONCAT`، `IIF`، `TRY_CONVERT`، `THROW`، `FORMAT`. (تست‌ها روی compat 100 اجرا شدند؛ تابع‌های نسخه‌بندی‌شده را به‌صورت دستی پرهیز کردیم.)

**ابزارها و دستورهای آماده** (ساخته‌شده در `research_tools/`، هیچ کد پروژه تغییر نکرد):
`sazeh_snapshot.py` (اسنپ‌شات قبل/بعد + diff با ماسک داده شخصی)، `recipes/reads.py`، `recipes/writes.py`، `recipes/grant_shopbot_2008r2.sql`.

---

## 1. واقعیت‌های محیطی (✅ T)

- هر سال مالی یک دیتابیس: `hesab1…hesab5` (hesab5 = سال 1405؛ تاریخ‌ها `1405/..`). نام دیتابیس جاری باید تنظیم شود.
- Collation: **`Arabic_CI_AS`** (code page 1256). ستون‌های متنی اصلی `varchar` (نه nvarchar) هستند ← متن فارسی ANSI/cp1256. با pyodbc روی این PC درست خوانده می‌شود چون locale ویندوز cp1256 است؛ **برای اطمینان روی سرور دیگر**: `conn.setdecoding(pyodbc.SQL_CHAR, encoding='cp1256')`.
- ⚠ نرم‌افزار حروف عربی `ي ك` و فارسی `ی ک` را **مخلوط** ذخیره می‌کند (مثلاً «گلس انتي استاتيک»). جستجو باید نرمال‌سازی کند (shopapi `normalize_fa` دارد). مقدار ثابت «بی‌حساب» در DB با **ي عربی** است: `N'بي حساب'`.
- **روی هیچ‌کدام از جدول‌های مرتبط ایندکس/PK/Unique/FK نیست** (فقط `name_mo.Code` PK دارد؛ `Kala`, `Gkala`, `Fact`, `Facto`, `KalaOrder`, `KalaOrderDetail`, `kardex_an`, `KOL`, `DetailTBL` هیچ ایندکسی ندارند). یعنی: تکراری‌شدن کد ممکن است (§6)، و هر پرس‌وجو scan است (در مقیاس فعلی ۶ هزار ردیف، میلی‌ثانیه).
- تریگر روی جدول‌های مرتبط: فقط `kardex_an` دو تریگر دارد (`updateKardexShenaseTigger*`) که اگر `ShenaseKala_Define` خالی باشد (اینجا خالی) بلافاصله `RETURN` می‌کنند ← بی‌اثر. هیچ تریگری روی `Kala`, `name_mo`, `KalaOrder*`, `Fact*`, `KOL`, `taf`, `DetailTBL` نیست.
- Identity: `taf.Code`, `DetailTBL.ID`, `Facto.Num`, `kardex_an.Num`, `KOL.Num_kol`, `havale.code`, `Dar.Code`, `TabaghehBandi.code`, `ANBAR.Code`, `vahed.Code`, `Telegram_*.Id`, `Chats.ID`, `gsh.Code`.
  **Identity نیست (کد دستی MAX+1):** `Kala.Code`, `Gkala.Code`, `name_mo.Code`, `KalaOrder.Codlp`, `KalaOrderDetail.Num` (شماره ردیف داخل سفارش، 1..n), `Fact.Numfact`.
- پروسیجرهای `Telegram*` در DB **نیست**؛ ربات رسمی مستقیماً با EF/SQL خام کار می‌کند و با کاربر `sa` وصل می‌شود (طبق `Options.ini`).

---

## 2. نقشهٔ جدول‌ها

### 2.1 کالا
| جدول | ستون‌های کلیدی | توضیح |
|---|---|---|
| **`Kala`** (۶۳۰ ردیف، ۹۹ ستون) | `Code` (NN، دستی)، `Name varchar(100)`، `Gcod`→`Gkala.Code`، `v1`→`vahed.Code`، `active bit NN`، `pic varchar(100)`، `Mogod`, `Mogod_f`, `hadeaghalmogodi`، **قیمت فروش: `Gey`=سطح۱، `Geycf`=سطح۲، `gey3`، `gey4`، `gey5`**، `darsad1..5` (درصد تخفیف هر سطح)، `IsKalaSite`, `IdProductInSite(_Second)`, `IdVariantInSite(_Second)` (لینک سایت) | **`Geyk`=قیمت خرید، `Geya`=قیمت اول دوره، `Geym`=داخلی ← هرگز نمایش/فروش نشوند.** `Mogod` = **cache** موجودی (برابر `SUM(Megv)-SUM(Megs)` برای هر ۶۳۰ کالا ✅T؛ نرم‌افزار بعد از هر ثبت سند دوباره حساب می‌کند). `Mogod_f` = موجودی اول دوره (در `kardex_an` هم ردیف `va='v'` دارد ✅T برای ۱۸۳ کالا). ۵۵۷ کالا فقط قیمت سطح ۱ دارند؛ سطح ۲ و ۴ هر کدام ۱ کالا؛ سطح ۳ و ۵ هیچ. **همه `pic` خالی‌اند.** |
| **`Gkala`** (۱۰ ردیف) | `Code`, `Name`, `g_kala` (والد)، `Moe`, `codtaf`, `Code_in_site` | درخت گروه: ریشهٔ `Code=0` («کلیه کالاها»)؛ `g_kala=0` گروه اصلی (۱ گوشی، ۲ لوازم جانبی، ۹ ماشین/موتور)؛ ۳‑۸ زیرگروه `g_kala=1`. `Kala.Gcod` به یک برگ/گره اشاره می‌کند. |
| `vahed` | `Code,Name,type` | واحد؛ فقط «عدد» (۱) |
| `LevelsName` | `id,base_name,selected_name` | نام سطوح قیمت 1..5 («قیمت سطح n») |
| `ANBAR` | `Code,Name` | انبارها؛ اینجا فقط `1` («انبار ۱») |
| **`kardex_an`** (۶۶۹۲) | `Num`(identity)، `va`, `Numfk` (شمارهٔ سند)، `Codename`, `Codekala`, `Date1`, `Megv` (ورودی)، `Megs` (خروجی)، `Codanbar`, `radifKardex` | **منبع حقیقت موجودی.** `va='s'` فروش (`Numfk`=`Fact.Numfact`)، `'v'` خرید/اول دوره، `'b'` برگشت از فروش (Megv)، `'k'` برگشت از خرید (Megs). |
| `Pictuers` (۰ ردیف) `ID,Type,CodeP,Image(image)` و `OrderPic` (۰) | | تصویر در DB تقریباً استفاده نمی‌شود. تصویر کالا = **فایل** در `PicturesInDatabase\` (کنار exe، یا مسیر شبکه) و نام/مسیر آن در `Kala.pic`؛ در این دیتابیس همه خالی. ربات رسمی مسیر عکس را جداگانه در `Telegram_Product.ImageAddress` نگه می‌دارد (۰ ردیف پر). |

### 2.2 اشخاص
| جدول | ستون‌های کلیدی | توضیح |
|---|---|---|
| **`name_mo`** (۹۶۴۹، ۸۹ ستون) | `Code` (PK، دستی)، `Gcod`، `Name` (نام خانوادگی/عنوان)، `fname` (نام)، `Addres2`, `datestart`, `l_gey`, `codetaf`, `telephons`, … | **`mobile`, `Tel1..3` در تمام ۹۶۴۹ ردیف خالی است** ✅T. شمارهٔ تماس در `DetailTBL` است و `telephons` یک متن تجمیعی ("a, b") که با `dbo.fn_tell(code)` ساخته می‌شود. `Gcod`: ۱ مدیریت، ۲ کاربران، ۳ تأمین‌کنندگان، **۴ مشتریان** (۹۵۶۶ نفر). `l_gey` = سطح قیمت مشتری (۰=پیش‌فرض/۱..۵ ✅C؛ ۶۰۰۱ نفر ۱، ۳۶۳۹ نفر ۰). ستون‌های مانده/اعتبار (`Man_n`, `Mah_n`, `sumbed`, `sumbes`, `datebedehe`, `mabbedehe`) **cache** اند و فقط با `SPName_mo_update_one_person` به‌روز می‌شوند (§5.3). |
| **`DetailTBL`** (۹۸۴۹) | `ID`(identity)، `IDMaster`=`name_mo.Code` (یا `Kala.Code` برای `Va=5`)، `TabaghehBandiID`، `Comment`، `Va`، `darfn`, `darfm` | `Va=0` + `TabaghehBandiID=1` تلفن، `=3` موبایل (نگاه کنید `TabaghehBandi va='!'`: ۱ تلفن، ۲ فکس، ۳ موبایل). `darfn=1` = شمارهٔ اصلی. ۹۴۵۷ شخص حداقل یک شمارهٔ `09xxxxxxxxx` دارند؛ **۵۱۶۸ موبایل در نوع ۱ و ۴۴۹۵ در نوع ۳ ثبت شده‌اند** (باید هر دو را جستجو کرد). `Va=5` = قیمت پلکانی کالا (`TabaghehBandiID`=سطح، `darfn`=حداقل تعداد)؛ `Va=6,7` = هزینه‌/متفرقه. |
| **`taf`** (۹۶۶۸) | `Code`(identity)، `Cota`=`name_mo.Code`، `Como`، `va`، `codgtaf`، `Sharh` | حساب تفصیلی هر شخص: `Como=13` (معین مشتریان)، `va=1`، `codgtaf=59` (گروه «مشتریان»). `name_mo.codetaf = taf.Code`. |
| `gsh` | `Code,Name,moe,CodeGTaf` | گروه‌های شخص ↔ معین/گروه تفصیلی: ۴ مشتریان (`moe=13`, `CodeGTaf=59`)، ۳ تأمین‌کنندگان (۱۴/۵۸)، ۲ کاربران (۱۳/۵۷)، ۱ مدیریت (۱۳/۱). |
| `G_Taf` | `ID_Gtaf,Nam_Gtaf,va` | گروه‌های تفصیلی. |
| `TabaghehBandi` (۶۷۹۲) | `code`(identity)، `va char(1)`, `sharh`, `parent` | جدول طبقه‌بندی عمومی («لیست‌های کشویی»). `va` نوع لیست را مشخص می‌کند (`!` انواع تلفن، `b` بانک‌ها، `o`/`s`/`9` شهر/محله/استان، `\` یادداشت‌های آزاد (۶۲۹۸ ردیف **با داده شخصی/مالی**) و …). **لیست وضعیت سفارش در این دیتابیس تعریف نشده است**؛ کد `6808` که در تنظیمات shopapi هست **وجود ندارد** (max code = 6799). |

### 2.3 سفارش و فاکتور
| جدول | توضیح |
|---|---|
| **`KalaOrder`** (سربرگ سفارش، ۲۸ ستون) | `Codlp` (NN، دستی MAX+1)، `Codnlp`=`name_mo.Code`، `Datelp varchar(10)` (شمسی `1405/07/18`)، `Mablp money` (جمع قبل از تخفیف)، `takhfif`, `avarez`, `keraye`, `Sharhlp varchar(1000)`, `tavasot varchar(50)`, `Codf int` (**-100 = سفارش اینترنتی/خارجی** ✅C)، `va int` (**0 = سفارش فروش، 1 = سفارش خرید/امانی**)، `Status int`→`TabaghehBandi.code`، `Taf2`, `Ras`, `UseUser` (قفل ویرایش: کدکاربری که فرم را باز کرده)، `usercode`, `NetOrder bit`, `Naghd`, `Ischeck`, `PrintCount` (default 0)، `order_code_ste_seconed` (کد سفارش سایت دوم)، `Field1..5`, `num_hav`, `bank_hav` |
| **`KalaOrderDetail`** (۲۳ ستون) | `Num` (شمارهٔ ردیف 1..n)، `Codlp_`→`KalaOrder.Codlp`، `Codekala`، `Meg float` (تعداد)، `Gey money` (قیمت واحد)، `sharh`, `AnbarCode`, `takhfif`, `PrintCount`(default 0)، `field1..8` (مشخصات جزئی؛ تعریف در `setting` 429–433)، `meg2,cnt2`, `Dolar,codearz,ArzTorial` (ارزی) |
| **`Fact`** (سربرگ فاکتور فروش، ۷۴ ستون) | `Numfact` (دستی)، `Codename`, `Date1`, `Mabkol`, `Takh`, `Par` (دریافتی همان لحظه)، `Sharh`, `UserCode`, `timesabt`, … |
| **`Facto`** (اقلام فاکتور، ۵۴ ستون) | `Num`(identity)، `Numfact`, `Radif`, `Codekala`, `Meg`, `Gey`, `Mab`, `Codanbar`, **`ordercode`=`KalaOrder.Codlp`**, **`orderdetailcode`=`KalaOrderDetail.Num`**, `Time_insert` (default saat) |
| `KOL` (دفتر کل/اسناد، ۱۵۷۸۲) | `Num_kol`(identity)، `Codkol` (کد شخص یا حساب)، `Noa` (`'m'` شخص)، `Va` (`'f'` فاکتور فروش)، `N_sanad` (=`Numfact`)، `Cod_n`, `Date1`, `Bed`, `Bes`, `Mah`, `TafCode` |
| `havale`, `Dar` | حواله‌های حسابداری / اسناد دریافت |
| `setting` (۷۰۳ ردیف) | `code, name (مقدار), share (عنوان), status` — **حاوی رمز پنل پیامک (۴۹۷‑۴۹۹) و اتصال سایت (۶۴۸‑۶۵۰)؛ هرگز SELECT نشود** |

### 2.4 جدول‌های ربات رسمی (`Telegram_*`, `Chats`) — فقط اگر ربات رسمی استفاده شود
| جدول | ستون‌ها | ✅ منطق |
|---|---|---|
| `Telegram_user` | `Id, ChatId, Name_mo_Id, FullName, PhoneNumber, IsConfirm, LastCommand, Status_Register, Name_mo_FullName` | `/start` یک ردیف می‌سازد (`Status_Register=0`). پیام بعد: نام (≥۵ نویسه) → `FullName`, `Status_Register=1`. شماره با regex `^(?:0|98|\+98|\+980|0098|098|00980)?(9\d{9})$` → `PhoneNumber`, `Status_Register=2` → «منتظر تأیید مدیر». **تأیید فقط توسط مدیر در پنجرهٔ دسکتاپ خود ربات** (انتخاب یک شخص *موجود* از `name_mo`): `Name_mo_Id=Code`, `Name_mo_FullName=fname+' '+Name`, **`Status_Register=3`**؛ `IsConfirm` هرگز تغییر نمی‌کند (همیشه 0). ردیف تکراری برای یک `ChatId` ممکن است (قید یکتایی نیست؛ ۳ ردیف تکراری برای یک chat در داده). |
| `Telegram_OrderList` | `Id, ChatId, Date, Confirmed, SumPrice` | `Date = DateTime.Now` هنگام ساخت سبد، `Confirmed=0`. هنگام «تأیید نهایی» اگر Σ(amount×Price)>0 → `Confirmed=1`. **`SumPrice` هرگز نوشته نمی‌شود (NULL)** — در IL هیچ فراخوانی `set_SumPrice` نیست. |
| `Telegram_OrderDetails` | `OrderListId`(FK، cascade)، `Kala_Id`(=`Kala.Code`)، `Kala_Name`, `amount`, `Price` (قیمت واحد) | قیمت هنگام افزودن کالا از جدول کالا (سطح ۱) گرفته می‌شود؛ ⚠ نمی‌توان از IL تشخیص داد از `Kala.Gey` است یا `Telegram_Product.Price` (که با دکمهٔ «به‌روزرسانی کالا» از `Kala.Gey` همگام می‌شود). موجودی بررسی **نمی‌شود**. |
| `Telegram_Product` | `Code_kala, Gcod, Name, Price, Send, MessageId, ImageAddress` | کپی کالا برای ارسال به کانال؛ `ImageAddress` مسیر فایل عکس روی PC ربات |
| `Telegram_Setting` | توکن، کانال، `IsTelegram` (0 = **بله** با `https://tapi.bale.ai/`)، آدرس/تلفن فروشگاه، `Price_List` | **حاوی توکن؛ هرگز SELECT/لاگ نشود** |
| `Chats` | `ChatId, Message, Date_Time, telegram_userId, FullName` | لاگ گفتگو (۵۲ ردیف) |

---

## 3. پرس‌وجوهای خواندنی (production-ready، ✅T با کاربر کم‌دسترسی)

همه در `research_tools/recipes/reads.py`. زمان اجرا روی ۶۳۰ کالا: ≤ ۱۶ms.

```sql
-- R1) گروه‌ها (درخت با g_kala)
SELECT g.Code, g.Name, g.g_kala AS ParentCode,
       (SELECT COUNT(*) FROM dbo.Kala k WHERE k.Gcod = g.Code AND k.active = 1) AS ActiveProducts
FROM dbo.Gkala g WHERE g.Code > 0 ORDER BY g.g_kala, g.Code;

-- R2) کالاها + قیمت همهٔ سطوح + موجودی + مقدار سفارش باز  (قیمت سطح n = ستون جدول §2.1؛ سطح 1 برای ربات/سایت)
SELECT k.Code, k.Name, k.Gcod AS GroupCode, k.v1 AS UnitCode, k.pic AS Pic,
       k.Gey AS Price1, k.Geycf AS Price2, k.gey3 AS Price3, k.gey4 AS Price4, k.gey5 AS Price5,
       ISNULL(s.Stock, 0) AS Stock,
       ISNULL(o.OpenOrderQty, 0) AS OpenOrderQty
FROM dbo.Kala k
LEFT JOIN (SELECT Codekala, SUM(ISNULL(Megv,0)) - SUM(ISNULL(Megs,0)) AS Stock
           FROM dbo.kardex_an GROUP BY Codekala) s ON s.Codekala = k.Code      -- افزودن: WHERE Codanbar IN (...) برای انبار خاص
LEFT JOIN (SELECT d.Codekala,
                  SUM(CASE WHEN d.Meg - ISNULL(f.Meg,0) > 0 THEN d.Meg - ISNULL(f.Meg,0) ELSE 0 END) AS OpenOrderQty
           FROM dbo.KalaOrderDetail d
           JOIN dbo.KalaOrder h ON h.Codlp = d.Codlp_ AND ISNULL(h.va,0) = 0
           LEFT JOIN (SELECT ordercode, orderdetailcode, Codekala, SUM(Meg) AS Meg
                      FROM dbo.facto WHERE ISNULL(ordercode,0) > 0
                      GROUP BY ordercode, orderdetailcode, Codekala) f
                  ON f.ordercode = d.Codlp_ AND f.orderdetailcode = d.Num AND f.Codekala = d.Codekala
           GROUP BY d.Codekala) o ON o.Codekala = k.Code
WHERE k.active = 1 AND k.Code > 0 ORDER BY k.Code;
--   قابل‌فروش = Stock − OpenOrderQty (حداقل 0). همان فرمول «مانده سفارش» خود نرم‌افزار (tbl_MandeCNT: به تفکیک ordercode+orderdetailcode+Codekala).
--   فیلتر عرضه: Price(level) > 0. «موجود/ناموجود» ربات: Stock − OpenOrderQty > 0.

-- R3) موجودی یک کالا به تفکیک انبار
SELECT Codekala, Codanbar, SUM(ISNULL(Megv,0)) - SUM(ISNULL(Megs,0)) AS Stock
FROM dbo.kardex_an WHERE Codekala = ? GROUP BY Codekala, Codanbar;

-- R4) پیدا کردن مشتری با موبایل  (ورودی: ۱۰ رقم آخر بدون صفر، مثل 9123456789، ASCII)
SELECT TOP 1 n.Code
FROM dbo.DetailTBL d JOIN dbo.name_mo n ON n.Code = d.IDMaster
WHERE d.Va = 0 AND d.TabaghehBandiID IN (1, 3)
  AND LEN(RTRIM(d.Comment)) BETWEEN 10 AND 14
  AND RIGHT(RTRIM(d.Comment), 10) = ?
ORDER BY n.Code;
--   فقط Code برمی‌گرداند (بدون نام). یک شماره در ≤ ۱ شخص تکراری است (۱ مورد مشترک در کل DB) → اگر چند نتیجه بود، تأیید دستی.
--   ⚠ name_mo.mobile/Tel1 را نخوانید: خالی است.

-- R5) سفارش‌های یک مشتری (+ تعداد سفارش‌شده/فاکتورشده)
SELECT h.Codlp, h.Codnlp, h.Datelp, h.Mablp, h.takhfif, h.avarez, h.Status, h.Codf, h.va, h.Sharhlp, h.tavasot,
       (SELECT SUM(d.Meg) FROM dbo.KalaOrderDetail d WHERE d.Codlp_ = h.Codlp) AS OrderedQty,
       (SELECT SUM(f.Meg) FROM dbo.facto f WHERE f.ordercode = h.Codlp)         AS InvoicedQty
FROM dbo.KalaOrder h WHERE h.Codnlp = ? ORDER BY h.Codlp DESC;

-- R6) اقلام یک سفارش با مقدار فاکتورشدهٔ هر ردیف
SELECT d.Num, d.Codekala, k.Name, d.Meg, d.Gey, d.Meg * d.Gey AS LineAmount,
       (SELECT SUM(f.Meg) FROM dbo.facto f
         WHERE f.ordercode = d.Codlp_ AND f.orderdetailcode = d.Num AND f.Codekala = d.Codekala) AS InvoicedQty
FROM dbo.KalaOrderDetail d LEFT JOIN dbo.Kala k ON k.Code = d.Codekala WHERE d.Codlp_ = ? ORDER BY d.Num;
```

**وضعیت سفارش (برای نمایش به مشتری):**
- «ثبت‌شده در حسابداری» = وجود ردیف `KalaOrder`.
- «فاکتور شده» = `InvoicedQty` ≥ `OrderedQty` (کامل) یا بین (جزئی). فاکتور با `Facto.ordercode` به سفارش وصل می‌شود.
- «لغو» = **ردیف حذف می‌شود** (نرم‌افزار برای لغو، سفارش را پاک می‌کند: `delete from KalaOrderDetail where Codlp_=…` ✅C). پس سفارش غایب‌شده = لغو/حذف. وضعیت متنی (`Status`) فعلاً تعریف نشده.
- متن وضعیت: `TabaghehBandi.sharh WHERE code=Status` (در این DB چیزی تعریف نشده → «بدون وضعیت»). چون خواندن TabaghehBandi توصیه نمی‌شود (§9)، وضعیت‌های لازم را فروشگاه خودش نگه دارد.

**مانده حساب مشتری** (اختیاری، ✅T برابر cache در ۱۰۸۳ از ۱۰۸۴ شخص؛ مورد دیگر را آزمایش من ساخته بود):
`SELECT SUM(Bed), SUM(Bes) FROM dbo.KOL WHERE Noa='m' AND Codkol=? AND NOT (Va=N'غ' AND Cod_n IN (-1003,-1005))` ← مانده = |Σبس − Σبد|؛ بدهکار اگر Σبس−Σبد<0، بستانکار اگر >0. (نیازمند GRANT روی KOL که در لیست حداقل دسترسی **نیست**؛ فقط در صورت نیاز.)

---

## 4. جریان سفارش — واقعاً چه اتفاقی می‌افتد

### 4.1 ربات رسمی (✅C از IL)
1. `/start` → ردیف `Telegram_user`; مشتری نام + موبایل می‌دهد؛ مدیر در دسکتاپ ربات او را به یک `name_mo` **موجود** وصل می‌کند (`Status_Register=3`). ربات هرگز `name_mo` نمی‌سازد.
2. «سفارش کالا» → «افزودن کالا» (کد کالا) → «مقدار» → `Telegram_OrderList(Date=now, Confirmed=0)` + `Telegram_OrderDetails(Kala_Id, Kala_Name, amount, Price)`.
3. «تایید نهایی سفارش» (فقط اگر Σ>0؛ وگرنه «مبلغ سفارش صفر نمی‌تواند باشد»):
   - `codlp = SELECT isnull(max(codlp),0) FROM KalaOrder` (+۱)، `anbar = SELECT isnull((SELECT top 1 code FROM ANBAR ORDER BY Code),1)`.
   - برای هر قلم (شماره 1..n): `INSERT INTO KalaOrderDetail (num, Codlp_, Codekala, Meg, gey, sharh, AnbarCode) VALUES (n, codlp, Kala_Id, amount, Price, '', anbar)`.
   - `UPDATE Telegram_OrderList SET Confirmed=1`.
   - `INSERT INTO KalaOrder (codlp, codnlp, Datelp, Mablp, Codf, va) VALUES (codlp, Name_mo_Id, 'yyyy/mm/dd شمسی', Σ, -100, 0)` — **فقط همین ۶ ستون**؛ بقیه NULL می‌مانند (`takhfif`, `avarez`, `Status`, `usercode`, … NULL). ⚠ در IL تراکنش صریحی دیده نشد (اگر بین درج اقلام و سربرگ قطع شود، اقلام یتیم می‌مانند؛ ما در تراکنش می‌نویسیم).
   - پیام «سفارش با شماره … در سیستم ثبت نهایی شد».
4. روی ردیف‌های نتیجه (✅T با شبیه‌سازی دقیق این INSERTها): `view_Sefaresh` ردیف را نشان می‌دهد؛ ستون‌های محاسباتی `khales`/`takhfif` در view **NULL** می‌شوند چون `Mablp−takhfif+avarez` با NULL محاسبه می‌شود ← **برای سفارش‌های ما `takhfif=0, avarez=0` بنویسید** (نرم‌افزار خودش هنگام ثبت سفارش از سایت همین را می‌نویسد).

### 4.2 ورود سفارش از سایت/Woo داخل خود نرم‌افزار (✅C)
نرم‌افزار ماژولی دارد که سفارش API/WooCommerce را وارد می‌کند و **دقیقاً** همین جدول‌ها را می‌نویسد:
```
INSERT INTO Kalaorder(Usercode,Codlp,codnlp,Datelp,tavasot,Sharhlp,takhfif,mablp,Codf,va,Status,naghd,ischeck,keraye) VALUES (...,-100,0,...)
UPDATE Kalaorder SET Status=…, Codf=… WHERE Codlp=…          -- پس از درج (وضعیت/نوع از تنظیمات)
INSERT INTO kalaorderDetail(Num,Codlp_,Codekala,Meg,Gey,Anbarcode,sharh,meg2,cnt2) VALUES (...)
```
- `Sharhlp` = متن + «و شماره سفارش <id>»، **`tavasot` ⚠(استنباط) = شمارهٔ سفارش در سایت** (عدد). برنامه با `SELECT MAX(CAST(tavasot AS int)) … WHERE ISNUMERIC(tavasot)=1` آخرین سفارش وارد‌شده را می‌یابد و با `WHERE tavasot=…` تکراری‌ها را رد می‌کند ⚠ ⇒ **اگر ماژول Woo روزی فعال شود، ما نباید در `tavasot` عدد بنویسیم** (خالی یا متن `API-…` بماند).
- مشتری جدید سایت: `SELECT ISNULL(MAX(Code),0)+1 FROM name_mo` → `INSERT INTO name_mo (code, fname, gcod, [name], addres, Addres2, datestart, l_gey, codeposti, tartavalod, Man_f, Mah_f, Man_n, Mah_n, etebar, datebedehe, mabbedehe, memo1, pic, sumbed, sumbes, codetaf, CodeEghtesadi)` (tartavalod=`'1300/01/01'`، Mah_f=`'بي حساب'`) + `INSERT INTO DetailTBL (IDMaster, TabaghehBandiID, VA, Comment)` (دو بار: نوع 3 و نوع 1). ۴۰ شخص آخر DB دقیقاً با همین الگو ساخته شده‌اند.

### 4.3 تبدیل سفارش به فاکتور (نرم‌افزار؛ ✅C + ✅T جزئی)
- فرم «لیست سفارش‌ها» اقلام باز را در تور فاکتور (`#FactorDTL`، ستون‌های `OrderID`, `orderDetailCode`) می‌ریزد؛ **مقدار باقی‌ماندهٔ هر ردیف** = `KalaOrderDetail.Meg − Σ facto.Meg (ordercode=Codlp, Codekala)` (− ردیف‌هایی که همان لحظه در همان فاکتور آمده).
- `SaveSellFactor_SP` فاکتور را می‌نویسد؛ ارتباط: **`Facto.ordercode = KalaOrder.Codlp`، `Facto.orderdetailcode = KalaOrderDetail.Num`**.
- فاکتور → جدول‌های تغییرکرده (✅T؛ شبیه‌سازی با پروسیجر رسمی `SP_TempFact_To_Fact`، جز ordercode): `Fact` (سربرگ؛ `Numfact = MAX+1`)، `Facto` (اقلام)، `kardex_an` (`va='s'`, `Megs=Meg`, `Codanbar`)، `KOL` (بدهی مشتری: `Codkol=شخص, Noa='m', Va='f', N_sanad=Numfact, Bed=مبلغ`)، **`Kala.Mogod` دوباره از kardex حساب می‌شود** (۱۶۳۲→۱۶۳۰ برای ۲ عدد ✅T)، و در صورت `Dar` (سند دریافت). فاکتور واقعی ثبت‌شدهٔ این DB (`Numfact=2672`) نیز فقط همین‌ها را دارد: ۱ ردیف `Fact`، ۱ `Facto`، ۱ `kardex_an`، ۱ `KOL` — **ردیف KOL «کالا» (`Noa='k'`) برای فروش در این فروشگاه دیده نشد.**
- بعد از ثبت فاکتور/دریافت، نرم‌افزار `SPName_mo_update_one_person(@CodePerson)` را برای به‌روزکردن cache مانده صدا می‌زند (✅T: بعد از اجرا `Man_n=16500000, Mah_n='بدهكار'`).
- پس از فاکتور کامل: `UPDATE KalaOrder SET Status=<setting 422> WHERE va=0 AND Codlp=…` ✅C (فقط وقتی تنظیم 422 مقدار دارد؛ اینجا خالی) و `Sp_AddHavByOrder` (حوالهٔ بدهکاری برای مانده سفارش، **فقط با تنظیم 444=1**؛ اینجا 0). `Sp_AddHavByOrder` را هیچ‌وقت صدا نزنید (✅T: `havale` و `KOL` می‌نویسد).
- **ما فاکتور نمی‌نویسیم.** فاکتور را اپراتور در نرم‌افزار از روی سفارش می‌سازد.
- ⚠ **خطر پروسیجرهای رسمی:** `SP_TempFact_To_Fact` پس از ثبت `Kala.Gey` را با قیمت «یک ردیف دلخواه از تاریخچهٔ facto همان کالا» بازنویسی می‌کند (✅T: قیمت سطح ۱ کالای ۱ از ۳٬۵۰۰٬۰۰۰ به ۱٬۰۰۰٬۰۰۰ تغییر کرد). یعنی قیمت کالا در DB می‌تواند توسط خود نرم‌افزار تغییر کند → قیمت را **هر بار از DB بخوانید و ذخیره نکنید**.

### 4.4 ویرایش/حذف/وضعیت سفارش در نرم‌افزار (✅C)
- هنگام باز بودن فرم: `UPDATE KalaOrder SET useuser=<کاربر>` و در خروج `useuser=NULL` ⇒ **ما نباید `UseUser` را بنویسیم**؛ اگر `UseUser` غیر NULL باشد آن سفارش در حال ویرایش است (دستی/خواندنی).
- «تغییر دسته‌ای وضعیت»: `UPDATE KalaOrder SET Status=@new WHERE Status=@old`.
- هر بار ذخیرهٔ اقلام: `UPDATE KalaOrder SET mablp=(SELECT SUM(gey*meg) FROM KalaOrderDetail WHERE codlp=codlp_)` (جمع **بدون رُند**).
- قیمت پلکانی: اگر `DetailTBL(Va=5, IDMaster=کالا)` ردیف داشته باشد، `Gey` سطر بر اساس `TabaghehBandiID`=سطح و `darfn`≤تعداد تنظیم می‌شود (در این DB هیچ ردیف `Va=5` نیست).
- قیمت مشتری: بر اساس `name_mo.l_gey` (۱..۵ ← `Gey, Geycf, gey3, gey4, gey5`؛ اگر قیمت آن سطح صفر باشد fallback به سطح دیگر؛ 0/NULL = سطح ۱).
- ذخیرهٔ ردیف فیلدهای `field1..8` فقط وقتی تعریف شده باشند (`setting` 429‑433).

### 4.5 رزرو موجودی توسط سفارش
- DB هیچ «رزرو» ذخیره نمی‌کند. گزارش موجودی نرم‌افزار (`spTotalObject`) دو ستون دارد: **`rezerv`** = Σ `Meg` سفارش‌های `va=0` با `Status = setting(421)` (اگر 421 خالی = **`Status=0`**؛ ردیف‌های `Status IS NULL` **شمرده نمی‌شوند**)، و **`mandeh`** (مانده سفارش باز) = Σ(سفارش `va=0`) − Σ(`facto` با `ordercode>0`) به تفکیک کالا.
- ⚠ در این DB 421/422/81 خالی‌اند؛ پس برای دیده شدن سفارش ما در ستون «رزرو» گزارش نرم‌افزار باید `Status=0` (نه NULL) نوشته شود. ربات رسمی NULL می‌نویسد. توصیهٔ ما: **`Status=0`** (برابر «بدون وضعیت» در view و رزرو در گزارش) — ⚠ تأیید نهایی با آزمایش GUI (§10، G2) انجام شود که نرم‌افزار خودش چه مقداری می‌نویسد.

---

## 5. دستور نوشتن در production (Recipes)

> کد اجرایی و تست‌شده: `research_tools/recipes/writes.py`. همه با **کاربر کم‌دسترسی** (§8) اجرا و تأیید شدند و دقیقاً فقط جدول‌های زیر تغییر کردند.

### 5.0 قوانین عمومی
1. هر نوشتن = **یک تراکنش صریح** (`autocommit=False`)؛ خطا → `ROLLBACK` و هیچ ردیف نیمه‌کاره نماند.
2. **تولید کد**: کدها `MAX+1` دستی‌اند و جدول‌ها ایندکس یکتا **ندارند** ⇒ بدون قفل، همزمانی کد تکراری می‌سازد. **آزمایش (۴ نخ × ۱۵ درج): بدون قفل ۶۰ ردیف فقط ۱۵ کد یکتا؛ با `UPDLOCK,HOLDLOCK` کدها یکتا اما ۴۴ خطای deadlock؛ با `sp_getapplock` ۶۰/۶۰ یکتا و ۰ خطا** (✅T). → قبل از `MAX+1` همیشه:
   ```sql
   DECLARE @r int; EXEC @r = sp_getapplock @Resource='shop:KalaOrder', @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=15000; -- @r<0 → ROLLBACK
   ```
   (قفل با پایان تراکنش آزاد می‌شود؛ در SQL 2008 R2 موجود است؛ دسترسی خاصی نمی‌خواهد.) نرم‌افزار خودش قفل نمی‌گیرد، پس در لحظهٔ همزمان با ثبت دستی سفارش در نرم‌افزار هنوز ریسک بسیار کم باقی است (§9).
3. تاریخ شمسی: `dbo.MiladiToShamsi(GETDATE())` (خروجی `1405/07/18`؛ معادل `Change_Date_To_Shamsi('yyyy/mm/dd')` که خود برنامه استفاده می‌کند؛ ✅T روی ۳ تاریخ مرز سال).
4. **متن‌های اختیاری را `''` بنویسید نه NULL** (برنامه رشته‌ها را concatenate می‌کند؛ ربات رسمی/برنامه هم `''` می‌نویسند).
5. هیچ DDL (جدول/ایندکس/تریگر/view) در DB حسابداری نسازید.

### 5.1 ساخت شخص (مشتری) جدید — ترتیب
جدول‌ها: `name_mo` → `taf` → `UPDATE name_mo.codetaf` → `DetailTBL`. (✅T؛ ستون‌ها با شخص ساخته‌شده توسط خود نرم‌افزار مقایسه شد؛ تنها تفاوت: `Ch_Etebar_chek` که به‌جای NULL مقدار default (0) می‌گیرد.)
```sql
-- applock 'shop:name_mo' سپس:
SELECT @Code = ISNULL(MAX(Code),0)+1 FROM dbo.name_mo;               -- name_mo PK دارد (قید یکتایی واقعی)
INSERT INTO dbo.name_mo
 (Code, Gcod, fname, Name, Addres2, datestart, l_gey, tartavalod, Man_f, Mah_f, Man_n, Mah_n, etebar, etebar2, etebar3,
  datebedehe, mabbedehe, sumbed, sumbes, CodeEghtesadi, VisitorPercent, Mary_date, ClubMember, clubIntroducer, ClubScore,
  Is_salary, ServiceType_salary, TypeBime_salary, IsMarried_salary, Code_personley_salary, isEnd_salary_work, number_children,
  telephons,
  Addres, Cherk, Zamin, memo1, pic, codeposti, Codemelli, Numbershenasname, Moaref, ShomareEghtesadi, Namepedar, AccountingNumber,
  Degree_salary, BankeName_salary, Field_salary, ShobeName_salary, ServiceTitle_salary, ServiceDate_salary, UnderWrite_salary,
  ThumbPrint_salary, ShoamreBime_salary, Jensiat_salary, shenaseMeli, shomareSabt, start_salary_work, end_salary_work)
VALUES (@Code, 4, @fname, @name, @addr, @today, 1, '1300/01/01', 0, N'بي حساب', 0, N'بي حساب', 0,0,0,
        @today, 0, 0, 0, 0, 0, '    /  /   ', 0,0,0,  0,0,0,0,0,0,0,  @mobile,  '', '', … (۲۶ رشتهٔ خالی));
INSERT INTO dbo.taf (cota, como, va, codgtaf, Sharh) VALUES (@Code, 13, 1, 59, @fname + ' ' + @name);
SELECT @Taf = MAX(Code) FROM dbo.taf WHERE Cota = @Code AND codgtaf = 59;
UPDATE dbo.name_mo SET codetaf = @Taf WHERE Code = @Code;
INSERT INTO dbo.DetailTBL (IDMaster, TabaghehBandiID, Comment, Va, darfn) VALUES (@Code, 3, @mobile, 0, 1);   -- 3=موبایل (نرم‌افزار گاهی 1 می‌گذارد؛ هر دو را R4 می‌یابد)
```
- `@today` = تاریخ شمسی امروز؛ `Gcod=4` (مشتریان؛ ⚠ تنظیم 654 «گروه شخص پیش‌فرض اینترنتی» در این DB خالی است)؛ `taf.como=13, codgtaf=59` از `gsh` گروه ۴ (اگر گروه دیگری بسازید از `gsh.moe/CodeGTaf` بخوانید).
- `telephons` باید همان شماره (یا `dbo.fn_tell(code)`) باشد؛ فهرست نمایشی نرم‌افزار از آن می‌آید.
- **قبل از ساخت: جستجو** (R4)؛ نرم‌افزار خودش فقط روی نام تکراری هشدار می‌دهد (`SELECT Code FROM name_mo WHERE name=…`) و پروسیجر رسمی import اکسل روی `(name, fname, Codemelli)` مشابه رد می‌کند.
- **ننویسید:** `Man_n/Mah_n/sumbed/sumbes/mabbedehe` به‌جز مقدار اولیهٔ بالا؛ مانده‌ها را فقط `SPName_mo_update_one_person` (نرم‌افزار) به‌روز کند.
- ارتباط با ربات رسمی (فقط اگر هنوز استفاده می‌شود): ردیف `Telegram_user` را **ما نمی‌سازیم**؛ مدیر در ربات رسمی «ویرایش/تأیید» می‌کند. اگر ربات ما جایگزین شد، `Telegram_*` اصلاً لازم نیست و `ChatId↔Code` در SQLite خود فروشگاه می‌ماند.

### 5.2 ثبت سفارش — ترتیب
جدول‌ها: `KalaOrderDetail` (n ردیف) → `KalaOrder` (۱ ردیف) — دقیقاً مثل ربات و ماژول Woo خود نرم‌افزار (اقلام اول، سربرگ آخر؛ در تراکنش ما ترتیب مهم نیست).
```sql
-- applock 'shop:KalaOrder' سپس:
SELECT @Codlp = ISNULL(MAX(Codlp),0)+1 FROM dbo.KalaOrder;
-- برای هر قلم (Num = 1..n)، Meg = تعداد، Gey = قیمت واحد سطح مشتری (از R2 در همان لحظه)، AnbarCode = ANBAR با کمترین Code (اینجا 1)
INSERT INTO dbo.KalaOrderDetail (Num, Codlp_, Codekala, Meg, Gey, sharh, AnbarCode) VALUES (@n, @Codlp, @kala, @qty, @price, '', @anbar);
INSERT INTO dbo.KalaOrder (Usercode, Codlp, Codnlp, Datelp, tavasot, Sharhlp, takhfif, Mablp, Codf, va, Status, Naghd, Ischeck, keraye, avarez)
VALUES (@usercode, @Codlp, @person, dbo.MiladiToShamsi(GETDATE()), '', @memo, 0, @sum, -100, 0, 0, 0, 0, 0, 0);
-- @sum = Σ(Gey*Meg) بدون رُند؛  @memo = 'API-<id سفارش ما>' (برای idempotency: قبل از درج SELECT MAX(Codlp) WHERE Sharhlp=@memo)
```
- `Codf=-100`، `va=0` (سفارش فروش)، `Status`: بحث §4.5، `UseUser/Ras/Taf2/NetOrder/num_hav/bank_hav/Field1-5`: نوشته نشوند (NULL).
- `Codnlp` **باید** در `name_mo` موجود باشد: سفارش با شخص ناموجود در `view_Sefaresh` (INNER JOIN) **نمایش داده نمی‌شود** ولی ردیفش در `KalaOrder` می‌ماند (✅T) ← پیش از درج وجود را بررسی کنید (`SELECT COUNT(*) FROM name_mo WHERE Code=?`).
- ❌ `Telegram_user/Telegram_OrderList` برای ثبت سفارش در نرم‌افزار **لازم نیستند** (§6، Q1).
- پس از `COMMIT` سفارش فوراً در بخش «سفارش‌ها»ی نرم‌افزار دیده می‌شود (view زنده است؛ ✅T با کاربر کم‌دسترسی).

### 5.3 چه چیزی را هرگز ننویسید
- `Fact`, `Facto`, `kardex_an`, `KOL`, `havale`, `Dar`, `Kala` (قیمت/موجودی/Mogod)، `setting`, `TabaghehBandi`, `Telegram_*` — و هیچ پروسیجر ذخیره‌ای (`SaveSellFactor_SP`, `SP_TempFact_To_Fact`, `Sp_AddHavByOrder`, `UpdateKardex`, …).
- `KalaOrder.UseUser/Ras/NetOrder/Status` مگر بعد از تأیید GUI؛ `UPDATE/DELETE` روی سفارش‌های موجود (سفارش را کارمند در نرم‌افزار ویرایش/حذف می‌کند).
- `tavasot` عددی؛ `name_mo.mobile/Tel*`.
- هرگز با حساب `sa` یا صاحب DB وصل نشوید.

---

## 6. پاسخ تأییدشدهٔ سؤال‌های باز

| سؤال | پاسخ | روش تأیید |
|---|---|---|
| **۱. آیا سفارشی که `ChatId`اش در `Telegram_user` نیست پذیرفته می‌شود؟** | **بله در سطح DB و نرم‌افزار — اصلاً به `Telegram_user` ربطی ندارد.** `KalaOrder/KalaOrderDetail` ستون `ChatId` ندارند؛ تنها پیوند به مشتری `Codnlp = name_mo.Code` است. فقط **ربات رسمی** برای ساخت سفارش `Telegram_user.Name_mo_Id` را لازم دارد (ثبت‌نام و تأیید مدیر ← `Status_Register=3`). | ✅T: درج سفارش با کاربر کم‌دسترسی بدون هیچ دسترسی/ردیفی در `Telegram_*` موفق و در `view_Sefaresh` دیده شد. ✅C: IL ربات. هیچ پروسیجر/تریگر/view در DB به `Telegram_*` ارجاع ندارد. |
| **۲. آیا `Date`/`SumPrice` باید نوشته شود؟** | در `Telegram_OrderList`: `Date=now` را ربات می‌گذارد (اجباری نیست)، **`SumPrice` هیچ‌وقت نوشته نمی‌شود (NULL، همیشه)**. در `KalaOrder` ما: `Datelp` (شمسی) و `Mablp` را **باید** بنویسیم (نرم‌افزار آنها را نمایش و جمع می‌زند؛ `Mablp` در گزارش/`khales` استفاده می‌شود). | ✅C: IL (بدون `set_SumPrice`، `set_Date(DateTime.Now)`)؛ ✅T: view. |
| **۳. مشتری جدید چگونه به `name_mo` وصل می‌شود؟** | **دستی توسط مدیر:** در پنجرهٔ دسکتاپ ربات رسمی یک شخص **موجود** انتخاب می‌شود (`Name_mo_Id`, `Name_mo_FullName`, `Status_Register=3`). ربات هرگز شخص نمی‌سازد؛ تطبیق خودکار با موبایل ندارد (`PhoneNumber` فقط نمایش داده می‌شود). برای سیستم ما: تطبیق موبایل با `DetailTBL` (R4) و در نبود، ساخت شخص طبق §5.1. | ✅C IL (`btn_Select_Click`)؛ ✅T داده: ۳ کاربر تأییدشده همگی `Status_Register=3, IsConfirm=0`. |
| ۴. `Confirmed` | `0` هنگام ساخت سبد، `1` هنگام «تأیید نهایی» (و در همان لحظه درج در `KalaOrder`) | ✅C |
| ۵. `Kala_Id` / `Price` | `Kala_Id=Kala.Code`؛ `Price` قیمت واحد (سطح ۱)؛ `KalaOrderDetail.gey = Price` | ✅C/✅T |
| ۶. نقشه‌ها | `Gey=L1,Geycf=L2,gey3,gey4,gey5` درست؛ `Geya/Geyk/Geym` فروش نیستند (Geyk = قیمت خرید) | ✅C (`spTotalObject`, برنامه) |
| ۷. موجودی | `Kala.Mogod` cache است؛ منبع `SUM(Megv)−SUM(Megs)` از `kardex_an` — برابر برای ۶۳۰/۶۳۰ | ✅T |

---

## 7. سایت / WooCommerce / سامانه‌های خارجی

- نرم‌افزار **اتصال Woo/وب‌سرویس داخلی دارد** (کد داخل exe؛ آدرس‌های `wp-json/wc/v…`, JSON فیلدهای `billing`, `line_items`, `Customer_id_sazeh`, `product_id_sazeh`, `id_in_woo_wordpress`, `version_woo_wordpress`)، ولی در این DB **غیرفعال/تنظیم‌نشده** است: `setting` 648‑650 (رمز/یوزر/آدرس سایت) خالی، `api_online_setting` خالی، هیچ کالایی `IsKalaSite=1` یا `IdProductInSite` ندارد.
- ستون‌های پیوند: `Kala.IsKalaSite` (>0 = ارسال به سایت)، `Kala.IdProductInSite/IdVariantInSite` (+ `_Second` برای سایت دوم)، `Gkala.Code_in_site(_second)` (نگاشت گروه)، جدول `AnbarSiteSelected(Code,Name,SiteNumber)` (انبارهایی که موجودی‌شان به سایت می‌رود؛ `SiteNumber` 0/1)، تنظیمات: 611/634 سطح قیمت سایت (عادی/عمده)، 654 گروه شخص پیش‌فرض اینترنتی، 598 کد (شخص) پیش‌فرض اینترنتی، 661 کالای پیش‌فرض سایت، 659/660 ضریب تبدیل قیمت، 665/666/682/688/689/690 رفتار ارسال (نام/موجودی/قیمت/سطوح).
- ورود سفارش سایت = §4.2؛ **ما نیازی به آن نداریم** و بهتر است اتصال Woo خود نرم‌افزار را فعال نکنیم تا با `tavasot` ما تداخل نکند.
- پیام‌رسان: پیامک (`setting` 497‑500 ← **اعتبارنامهٔ پنل؛ ممنوع‌ُالخواندن**)، `tblSmsZSetting/SmsText/tblSentMessages`؛ ارسال پیام هنگام سفارش `setting 561/562`.
- دو سطح بانک/POS و سامانهٔ مودیان (`Tax_*`) وجود دارد؛ به مسیر ما ربطی ندارد.

---

## 8. حداقل دسترسی کاربر production (SQL 2008 R2) — ✅T

فایل کامل: `research_tools/recipes/grant_shopbot_2008r2.sql`. خلاصه:

| دسترسی | روی | دلیل |
|---|---|---|
| SELECT (ستونی) | `Kala(Code,Name,Gcod,Gey,Geycf,gey3,gey4,gey5,pic,v1,active,Mogod,hadeaghalmogodi)`، `Gkala(Code,Name,g_kala)`، `vahed(Code,Name)`، `ANBAR(Code,Name)` | کاتالوگ — **بدون `Geyk/Geya/Geym` (قیمت خرید/داخلی)** |
| SELECT (ستونی) | `kardex_an(Codekala,Megv,Megs,Codanbar)`، `facto(Numfact,Codekala,Meg,ordercode,orderdetailcode)` | موجودی و مانده سفارش |
| SELECT | `KalaOrder`, `KalaOrderDetail` | وضعیت سفارش‌ها |
| SELECT (ستونی) | `name_mo(Code,Gcod,l_gey,codetaf)`، `DetailTBL(IDMaster,TabaghehBandiID,Va,Comment)`، `taf(Code,Cota,codgtaf)` | تطبیق موبایل، سطح قیمت؛ **بدون نام/آدرس/مانده** |
| INSERT | `KalaOrder`, `KalaOrderDetail` | ثبت سفارش |
| INSERT + UPDATE(`codetaf`,`telephons`) | `name_mo`؛ INSERT: `taf`, `DetailTBL` | ساخت مشتری (حذف کنید اگر فروشگاه شخص نمی‌سازد) |
| EXECUTE | `dbo.MiladiToShamsi` | تاریخ شمسی |
| **DENY** | UPDATE/DELETE روی `KalaOrder*`؛ هر دسترسی به `setting`, `Telegram_Setting`, `api_online_setting`, `TabaghehBandi` | رمز پیامک/سایت/توکن؛ یادداشت‌های شخصی |

آزمون: ۱۳ پروب منفی (خواندن `Geyk`, `setting`, `Telegram_Setting.Token`, `name_mo.Name/mobile`, `TabaghehBandi`, `KOL`؛ UPDATE/DELETE سفارش؛ INSERT در `Fact`/`kardex_an`/`Telegram_user`؛ UPDATE `Kala`) همه **denied**؛ همهٔ R1‑R6 و دو recipe نوشتن **موفق**.
تفاوت با `shopapi/sql/create_api_user.sql` فعلی: آن فایل `SELECT` روی کل `Kala`, `setting`, `TabaghehBandi`, `facto` می‌دهد (شامل قیمت خرید و رمزها) و `name_mo(mobile)` که بی‌فایده است.

---

## 9. ریسک‌ها و موارد نامطمئن

**ریسک‌های واقعی (باید در پروژه رفع شوند):**
1. 🔴 **`find_person_by_mobile` در shopapi هرگز نتیجه نمی‌دهد** (`name_mo.mobile` در همهٔ ردیف‌ها خالی است). باید از R4 (DetailTBL، نوع 1 و 3، ۱۰ رقم آخر) استفاده کند.
2. ✅ (v2.17.0) کد وضعیت برای هر پایگاه‌داده جداست. در `hesab5 t` کد ۶۸۰۸ در `TabaghehBandi` نیست؛ در سرور اصلی «تایید» = ۶۸۰۸ و «تحویل به فروش» = ۶۹۱۴. مدیر در ShopAdmin › «قواعد فروشگاه» وارد می‌کند؛ بدون کد بزرگ‌تر از صفر هیچ سفارشی نوشته نمی‌شود.
3. 🟠 کد MAX+1 بدون قفل ← تکراری (آزمایش شد). با `sp_getapplock` اصلاح شود؛ حتی بعد از آن، ثبت همزمان کارمند در نرم‌افزار قفل ندارد (نرم‌افزار خودش `MAX+1` بدون قفل می‌زند) — احتمال ناچیز، اما در شلوغی تکرار ممکن است؛ پس از درج، با `SELECT COUNT(*) FROM KalaOrder WHERE Codlp=@c` (باید 1 باشد) بررسی کنید و در غیر این صورت rollback/تکرار.
4. 🟠 فرمول رزرو shopapi: کل `KalaOrderDetail` منهای `facto` بدون فیلتر `va=0` و بدون `orderdetailcode` است؛ سفارش *حذف‌نشدهٔ فاکتورنشده* همیشه رزرو می‌ماند. R2 بالا دقیق‌تر است. سفارشی که کارمند فاکتور نمی‌کند ولی حذف هم نمی‌کند ← رزرو دائمی (محدودیت ذاتی).
5. 🟠 `TabaghehBandi` دارای متن آزاد شخصی/مالی (۶۲۹۸ ردیف) و `setting` دارای رمز پیامک/سایت است؛ shopapi نباید SELECT روی آنها داشته باشد. مقادیر لازم (انبار پیش‌فرض، سطح قیمت) را در `.env` بگذارید.
6. 🟠 قیمت `Kala.Gey` می‌تواند توسط خود نرم‌افزار تغییر کند (§4.3)؛ قیمت‌ها را کش بلندمدت نکنید؛ در سفارش، قیمتِ لحظهٔ ثبت را در `KalaOrderDetail.Gey` می‌نویسیم.
7. 🟡 کدگذاری: Persian در `varchar/cp1256`؛ `setdecoding(SQL_CHAR,'cp1256')` برای اطمینان. نوشتن با پارامتر یونیکد (pyodbc) درست به cp1256 تبدیل می‌شود (✅T). حروف مخلوط ی/ي، ک/ك: جستجو را نرمال کنید.
8. 🟡 ایندکس نیست؛ اگر production خیلی بزرگ‌تر باشد (میلیون ردیف `kardex_an`) پرس‌وجوی R2 کند می‌شود — ایندکس ساختن مجاز نیست؛ کش سمت shopapi با TTL کوتاه.
9. 🟡 `NetOrder` (برچسب «اینترنتی» در لیست) توسط ماژول Woo نرم‌افزار هم نوشته نمی‌شود؛ مقدار پیش‌فرض NULL = «حضوری». ما هم نمی‌نویسیم (⚠ می‌توانست 1 باشد؛ GUI G2 نشان می‌دهد).
10. 🟡 `Mablp` شامل مالیات/عوارض نیست و `takhfif` سفارش را نرم‌افزار دستی می‌دهد.

**نامطمئن (⚠، در GUI تأیید شود):** (الف) مقدار `Status` و سایر ستون‌هایی که خود نرم‌افزار هنگام ثبت سفارش دستی می‌نویسد؛ (ب) رفتار دقیق «تبدیل به فاکتور» (آیا `Status` سفارش عوض می‌شود؟ آیا `UseUser` قفل می‌ماند؟)؛ (ج) قیمت مبنای ربات رسمی (`Kala.Gey` یا `Telegram_Product.Price`)؛ (د) معنی دقیق `l_gey=0`؛ (ه) ستون‌های ریز `KalaOrder` (`Ras`, `Taf2`, `bank_hav`, `num_hav`)؛ (و) شبیه‌سازی فاکتور با پروسیجر ساده انجام شد، نه با `SaveSellFactor_SP` (به temp tableهای برنامه وابسته است).

---

## 10. پروتکل آزمایش GUI (کاری که شما باید در نرم‌افزار انجام دهید)

نرم‌افزار را **فقط علیه دیتابیس تست** اجرا کنید (کپی exe با `Data1\Options.ini` محلی؛ **هرگز `Options.ini` فعلی که به `192.168.20.150\SAZEHHESAB` اشاره می‌کند**). قبل و بعد از هر گام:
```powershell
cd "E:\DSH-Workspace\Software Asr"
.\shopapi\.venv\Scripts\python.exe research_tools\sazeh_snapshot.py save before_G1
# ← فقط ۱ عمل در نرم‌افزار
.\shopapi\.venv\Scripts\python.exe research_tools\sazeh_snapshot.py save after_G1
.\shopapi\.venv\Scripts\python.exe research_tools\sazeh_snapshot.py diff before_G1 after_G1
```
(خروجی diff داده شخصی را ماسک می‌کند و می‌توان برای تحلیل مستقیم به من داد.)

| گام | عمل در نرم‌افزار | چه چیزی را روشن می‌کند |
|---|---|---|
| **G1** | ثبت یک شخص جدید (گروه مشتریان) با نام، موبایل | تأیید §5.1 (جدول‌ها/ستون‌ها، `DetailTBL` نوع ۱ یا ۳، `l_gey`) |
| **G2** | ثبت یک «سفارش کالا» دستی برای آن شخص با ۲ قلم | `Status/Usercode/NetOrder/takhfif/avarez/UseUser/Ras` که خود برنامه می‌نویسد؛ تعیین مقدار پیشنهادی `Status` |
| **G3** | تبدیل همان سفارش به فاکتور فروش (اول **جزئی** — یک قلم/نصف تعداد؛ بعد باقی) | تغییرات `Fact/Facto(ordercode, orderdetailcode)/kardex_an/KOL/Kala.Mogod/KalaOrder.Status` |
| **G4** | حذف یک سفارش فاکتورنشده؛ و تلاش برای حذف سفارش فاکتورشده | آیا فقط ردیف پاک می‌شود، `havale/KOL` چه می‌شوند |
| **G5** | (اختیاری) در ربات رسمی روی DB تست: تأیید یک کاربر + ثبت سفارش | تطبیق نهایی §4.1 |

---

## 11. نقشهٔ اتصال پروژهٔ ما به DB (بدون تغییر کد)

| بخش پروژه | اکنون | باید به این جدول/ستون‌ها وصل شود |
|---|---|---|
| `shopapi/app/accounting_reader.py` `list_groups` | `SELECT Code,Name FROM Gkala` (شامل ریشهٔ ۰) | R1: `Code>0`, ستون `g_kala` برای درخت |
| `list_products/get_products_for_order` | `Kala`(Code,Name,Gcod,قیمت,pic) + `kardex_an` + `KalaOrderDetail−facto` | R2: افزودن `ISNULL(h.va,0)=0`، join روی `orderdetailcode`؛ `pic` همیشه خالی است → تصویر باید جای دیگر (فایل در `PicturesInDatabase\` یا CDN خودمان) |
| `find_person_by_mobile` | `name_mo.mobile` ❌ | R4 (`DetailTBL`) |
| `person_code_exists` | `name_mo` COUNT | ✔ درست |
| (نیست) ساخت شخص | — | §5.1 |
| `accounting_writer.py` | هدر ۱۶ ستون + اقلام ۱۷ ستون؛ `Codf=-100` ✔، `Status=6808` ❌، `takhfif=0` ✔، `tavasot=''` ✔، `Sharhlp='API-<id>'` ✔ (idempotency)، قفل `UPDLOCK,HOLDLOCK` (deadlock-prone) | §5.2: `sp_getapplock`؛ `Status=0` (پس از G2)؛ `Mablp` بدون رُند؛ `PrintCount` اختیاری |
| `shopapi/sql/create_api_user.sql` | دسترسی‌های گسترده | §8 |
| `shopbots/*` | فقط HTTP به shopapi | بدون دسترسی DB ✔ (ربات رسمی و ربات ما جدا؛ از `Telegram_*` استفاده نمی‌کنیم) |
| `shopadmin/*` | فقط HTTP | ✔ |
| وضعیت سفارش به مشتری | `GET /orders/{id}` از SQLite | افزودن خواندن R5/R6 برای «فاکتور شد/تحویل» |

---

## 12. پیوست — دستورهای مفید

- شمارنده‌های کد: `Kala`: `MAX(Code)+1` (برنامه: `select max(code)+1 from kala`)؛ `Gkala`: `max(code)+1`؛ `name_mo`: `ISNULL(MAX(Code),0)+1`؛ `KalaOrder`: `ISNULL(MAX(Codlp),0)+1`؛ `Fact`: `MAX(Numfact)+1 WHERE len(Numfact)<9` (+ سری‌بندی با تنظیم 473)؛ `taf/DetailTBL/KOL/kardex_an/Facto`: identity.
- تنظیمات مرتبط (`setting.code`، فقط مقدار عددی؛ در این DB): 33 انبار پیش‌فرض فروش=1، 341=1، 495 انبار پیش‌فرض=1، 399 «انتخاب انبار سفارش»=0 (425‑427 کد انبار ۱..۳ سفارش، خالی)، 421/422/81 کد وضعیت (خالی)، 428 جزئیات سفارش=0، 429‑433 تعریف فیلدهای جزئی، 444 ثبت بدهکاری سفارش=0، 561/562 پیامک سفارش=0، 598/654/655/661 پیش‌فرض‌های اینترنتی (خالی)، 611/634 سطح قیمت سایت=0، 622‑626 سطوح قیمت انتقال.
- پروسیجرهای رسمی مفید برای *خواندن/مرجع* (نه فراخوانی): `AddPersonFromExcelToName_mo` (الگوی رسمی ساخت شخص+taf+DetailTBL+مانده اول دوره)، `spSavePerson` (@Mode=0 درج؛ کد را تا اولین آزاد بالا می‌برد؛ taf نمی‌سازد)، `SP_TempFact_To_Fact` (الگوی ساده فاکتور)، `SPName_mo_update_one_person` (به‌روزرسانی cache مانده)، `spTotalObject` (فرمول رزرو/مانده سفارش)، `SaveSellFactor_SP`/`SP_SellFactorSave` (ثبت کامل فاکتور؛ وابسته به temp table).
- نکتهٔ اجرای ابزار: پایتون سیستم `pyodbc` ندارد؛ از `shopapi\.venv\Scripts\python.exe` استفاده کنید.
