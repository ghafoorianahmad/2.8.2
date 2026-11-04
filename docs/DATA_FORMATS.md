# قالب فایل‌ها و داده‌ها (نسخهٔ ۲٫۱۸٫۱)

همهٔ فایل‌های متنی UTF-8 هستند. پولْ عدد صحیح به **ریال** است؛ تاریخ در متن‌ها شمسی `YYYY/MM/DD`.
اگر چیزی این‌جا عوض شد، آزمونی که نامش جلوی هر بخش آمده باید هم‌زمان عوض شود.

## ۱. فایل‌های همراه برنامه: `shopapi/app/data/`

این پوشه در بیلد با `--add-data` همراه `ShopSystem.exe` می‌رود (`shopsystem/build_exe.bat`).

### `faq_fa.json`: بانک پاسخ‌گوی خودکار
```json
{"version": 1, "items": [
  {"id": "hours", "category": "ساعت کاری", "questions": ["ساعت کاری چنده", "..."],
   "answer": "ساعت کاری ما: {hours}", "needs_staff": false}
]}
```
| فیلد | معنی |
| --- | --- |
| `id` | شناسهٔ یکتا |
| `category` | دسته (امتیاز تا ۸۵ هم از نام دسته می‌آید) |
| `questions` | شکل‌های پرسش |
| `answer` | پاسخ. جای‌خالی‌ها فقط: `{hours} {address} {phone} {instagram} {telegram} {website}` |
| `needs_staff` | `true`: در پایان پاسخ «یکی از همکاران پاسخ می‌دهد.» می‌آید و پرسش در «درخواست کالا» ثبت می‌شود |

مقدار جای‌خالی‌ها از «قواعد فروشگاه» است (`shop_state.faq_values`؛ ساعت از «ساعت کار»). پاسخی که جای‌خالی پرنشده دارد فرستاده نمی‌شود، مگر `needs_staff` که فقط همان جملهٔ مؤدبانه را می‌فرستد.
این فایل هرگز با ویرایش مدیر عوض نمی‌شود: ویرایش‌ها در جدول `faq_custom` است (بخش ۳). آزمون: `shopapi/tests/test_v2180_chat_faq.py`، `test_v2181_faq.py`.

### `product_aliases.json`: نام‌های مستعار کالا
بانک ۱۴ برند و ۱۲۲ مدل برای جستجوی ربات. ساختار و قواعد در سرفایل `shopapi/app/product_aliases.py`. واژه‌های یادگرفته در جدول `product_alias_learned`. آزمون: `test_v2180_aliases.py`.

### `reply_templates.json`: پاسخ‌های آمادهٔ همکاران
```json
{"version": 1, "templates": [
  {"id": "greet", "category": "خوشامد", "title": "سلام و خوشامد",
   "text": "سلام {customer_name} عزیز، ...", "placeholders": ["customer_name"]}
]}
```
۵۶ قالب در ۱۷ دسته. `placeholders` باید دقیقاً همان‌هایی باشد که در `text` آمده:

| جای‌خالی | از کجا پر می‌شود |
| --- | --- |
| `customer_name` | نام و نام خانوادگی مشتری |
| `product`, `color` | کالای درخواست، یا اولین قلم آخرین سفارش |
| `price` | قیمت پیشنهادی درخواست، یا جمع آخرین سفارش (با «ریال») |
| `order_no` | شمارهٔ آخرین سفارش مشتری |
| `hours` | «ساعت کار» |
| `address` | نشانی **فروشگاه**؛ در پنج قالب ارسال (`reply_templates.CUSTOMER_ADDRESS`) عبارت ثابت «نشانی ثبت‌شدهٔ شما»، هرگز نشانی مشتری |
| `phone` | تلفن فروشگاه؛ در `reply_templates.CUSTOMER_PHONE` شمارهٔ خود مشتری |

چیزی که سرور نمی‌داند به همان شکل `{product}` می‌ماند و تا پر نشود پیام فرستاده نمی‌شود. قالبی که چیزی را می‌پرسد که در پرونده هست اصلاً نشان داده نمی‌شود. قالب تازه‌ای که نشانی یا تلفن مشتری را می‌گوید باید به آن دو فهرست اضافه شود. آزمون: `test_v2181_templates.py`.

### `card/`: کارت اقساط
`Vazirmatn-Regular.ttf`، `Vazirmatn-Bold.ttf` (`OFL.txt`)، `logo.png`.

## ۲. آنچه به مشتری و ربات می‌رسد

### جزئیات مشتری: `GET /users/{platform}/{chat}/details`
```json
{"missing": ["address"], "has_address": false, "asked": false, "known": true,
 "prefill": {"first_name": "علی", "last_name": "رضایی"}}
```
**کد ملی و نشانی هرگز در این پاسخ، در `UserOut` و `OrderOut` ربات، در پیوند یا در پیام ربات نیست.** `known: false` یعنی «سازه حساب» خوانده نشد؛ چیزی پرسیده نمی‌شود و نوشتن در حسابداری متوقف است.

### پیوند فرم: `/app/form/`
| پارامتر | معنی |
| --- | --- |
| `fn`, `ln` | فقط نام و نام خانوادگی |
| `need` | فیلدهای لازم بدون مقدار: `nc`، `addr`، یا `nc,addr`. نبودنش یعنی هر دو خالی نشان داده شود |

`nc` و `addr` قدیمی نادیده گرفته می‌شوند. آزمون: `shopbots/tests/test_v2181_private.py`.

### پیام‌های مینی‌اپ به ربات (`web_app_data`)
همگی JSON با `"v": 1`، حداکثر طول `WEB_APP_DATA_MAX`، و همهٔ مقدارها روی سرور دوباره بررسی می‌شوند.
```json
{"v": 1, "type": "customer", "first_name": "علی", "last_name": "رضایی", "national_code": "...", "address": "..."}
{"v": 1, "type": "cart", "items": [{"id": "galaxy-a57", "color": "مشکی", "qty": 1}]}
{"v": 1, "type": "price", "id": "galaxy-a57", "color": "مشکی"}
{"v": 1, "type": "installment", "name": "Galaxy S25", "price": 200000000, "down": 100000000, "months": 5}
```
در `customer` فقط فیلدهای دیده‌شده فرستاده می‌شود؛ سرور آنچه در پرونده هست را نادیده می‌گیرد.

### محاسبهٔ اقساط برای مشتری (پیش‌فرض خاموش)
کلید: «قواعد فروشگاه» › «محاسبهٔ اقساط». تا روشن نشود `POST /installments/quote` پاسخ ۴۰۳ می‌دهد و ربات دکمه ندارد.

`GET /installments/settings` → `{"enabled": false}` (نرخ هرگز)

`POST /installments/quote` با `{"phone_name": "", "price": 0, "down": 0, "months": 5}` →
```json
{"view": {"phone_name": "Galaxy S25", "down": 100000000, "check_count": 5,
          "checks": [28000000, 28000000, 28000000, 28000000, 28000000],
          "groups": [{"count": 5, "amount": 28000000}],
          "dates": ["1405/09/13", "..."], "grand_total": 240000000, "date": "1405/08/13"},
 "text": "متن کارت برای کپی", "png_b64": "..."}
```
در این خروجی و روی کارت **نرخ، سود و قیمت نقدی نیست** (قیمت نقدی کنار جمع کل، سود را لو می‌داد). `png_b64` خالی یعنی مرورگری برای ساخت تصویر نبود و `text` فرستاده می‌شود. آزمون: `shopapi/tests/test_v2181_installments.py`.

## ۳. دادهٔ سرور: `shopapi.db` (SQLite) و `shop_state`

| جدول | چیست |
| --- | --- |
| `faq_custom` | ویرایش مدیر روی پرسش‌های آماده (همان `id`) و پرسش‌های افزوده (`custom_N`): `category`، `questions` (JSON)، `answer`، `needs_staff`، `enabled` |
| `faq_suggestions` | پیشنهاد از پاسخ همکار: `question`، `answer`، `request_id`، `status` = `pending`/`approved`/`rejected`. پاسخ با عدد بلند یا قیمت پیشنهاد نمی‌شود و تا تأیید به کار نمی‌رود |
| `faq_log` | پاسخ‌های داده‌شده؛ عددهای بلند متن مشتری به «…» تبدیل شده |
| `installment_quotes` | پیش‌فاکتور اقساط ذخیره یا فرستاده‌شده؛ `sheet` (JSON پایین)، `status` = `saved`/`pending`/`sent`/`failed`. **سود و نرخ دارد؛ فقط برای همکاران** |

`installment_quotes.sheet`:
```json
{"phone_name": "Galaxy S25", "price": 200000000, "down": 100000000, "rate": "8",
 "checks": [28000000, 28000000, 28000000, 28000000, 28000000],
 "dates": ["1405/09/15", "1405/10/15", "1405/11/15", "1405/12/15", "1406/01/15"],
 "date": "1405/08/13"}
```
`checks` مبلغ نهایی پس از ویرایش دستی است؛ سود = `down + sum(checks) - price`.

| کلید `shop_state` | معنی |
| --- | --- |
| `installment_rate` | نرخ ماهانهٔ پیش‌فرض (متن، مثل `8` یا `8.5`؛ نبودش = ۸) |
| `installment_customer_enabled` | `1` = ماشین‌حساب مشتری روشن؛ پیش‌فرض خاموش |
| `faq_enabled`, `faq_values` | پاسخ‌گوی خودکار |
| `permissions_2181` | مهاجرت یک‌بارهٔ تیک «پیام‌های کانال» انجام شده |

## ۴. فرمول اقساط: `shopapi/app/installments.py`

این فایل عیناً در `shopadmin/app/installments.py` کپی است (آزمون `test_the_copy_in_shopadmin_is_identical`).
```
مانده = قیمت − پیش‌پرداخت
سود = مانده × نرخ٪ × ماه (گرد به نزدیک‌ترین ریال)
جمع اقساط = مانده + سود
هر چک = جمع اقساط ÷ ماه (ریال‌های باقی‌مانده روی چک آخر)
جمع کل = پیش‌پرداخت + جمع اقساط
```
نمونهٔ مالک: ۲۰۰٬۰۰۰٬۰۰۰، پیش‌پرداخت ۱۰۰٬۰۰۰٬۰۰۰، ۵ ماه، ۸٪ ← سود ۴۰٬۰۰۰٬۰۰۰؛ ۵ چک × ۲۸٬۰۰۰٬۰۰۰؛ جمع ۲۴۰٬۰۰۰٬۰۰۰.

| گرد کردن (فقط پیشنهاد) | نتیجه |
| --- | --- |
| `none` | همان محاسبه |
| `equal` + گام | هر چک رو به بالا، همه برابر؛ اضافه به سود می‌رود |
| `last` + گام | چک‌ها رو به بالا و اختلاف روی چک آخر؛ جمع کل ثابت می‌ماند. اگر چک آخر صفر یا منفی شود، رو به پایین |

تاریخ چک‌ها یک ماه از هم فاصله دارند؛ ۳۱ام ماه کوتاه‌تر می‌شود آخرین روز آن ماه.

## ۵. فایل‌های انتشار سایت

`assets/catalog/catalog.json` (`asr-catalog` v1) و `assets/catalog/site.json` (`asr-site-look` v1): `SITE_CATALOG.md`. مینی‌اپ و فرم و صفحهٔ اقساط زیر `/app/`: `shopadmin/app/assets/miniapp/app/` با `scripts/build_miniapp.py` (صفحهٔ اقساط از `scripts/miniapp_installment.html`).

## ۶. دادهٔ این رایانه (ShopAdmin)

`%LOCALAPPDATA%\ShopAdmin\`: `shopadmin.db`، `site\site_data.json`، `site\photos\`. قالب سایت در `SITE_CATALOG.md`.
