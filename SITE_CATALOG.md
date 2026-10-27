# بخش «سایت» (نسخهٔ ۲٫۱۲٫۰)

منبع سایت: مخزن GitHub `ghafoorianahmad/asr-ertebatat-2` (شاخهٔ `main`)، کلون در `E:\DSH-Workspace\asr-site-live`.
از ۲٫۱۱٫۰ دادهٔ سایت **فقط روی رایانهٔ مدیر** است (داخل پوشهٔ دادهٔ «مدیریت فروشگاه»)؛ سرور فروشگاه در ساختن یا انتشار سایت هیچ نقشی ندارد. (خروجی سمت سرورِ ۲٫۱۰٫۰ حذف شد.)

## کجا ذخیره می‌شود

`%LOCALAPPDATA%\ShopAdmin\site\` (همان پوشهٔ دادهٔ «مدیریت فروشگاه»):
- `site_data.json` — برندها، گوشی‌ها، لوازم جانبی (رنگ، مشخصات، عکس، پنهان/نمایش)
- `photos\` — عکس‌ها در اندازهٔ استاندارد سایت (۱۲۸۰×۱۰۲۴ JPEG روی زمینهٔ #FBFCFF)
- `published.json` — آنچه اکنون در سایت است (پایهٔ «پیش‌نمایش»)
- `history\` — سابقهٔ هر انتشار برای «برگرداندن انتشار قبلی»؛ پس از ۴۸ ساعت خودکار پاک می‌شود
- توکن GitHub در تنظیمات محلی، رمزگذاری‌شده با Windows DPAPI (فقط همین کاربر ویندوز روی همین رایانه)
- `look\` — (۲٫۱۲٫۰) لوگو و عکس‌های بنر «ظاهر و چیدمان»؛ خود تنظیمات ظاهر در `site_data.json` (کلید `look`) است.
- `preview\` و `site_base\` — (۲٫۱۲٫۰) پوشهٔ «پیش‌نمایش در مرورگر» و رونوشت کد سایت از GitHub برای آن (هر بار از نو ساخته می‌شود)

«پشتیبان‌گیری…» یک zip از داده، عکس‌ها، عکس‌های ظاهر و وضعیت انتشار می‌سازد؛ «بازگردانی از پشتیبان…» اول یک رونوشت از دادهٔ فعلی نگه می‌دارد.

## قالب فایل سایت (`asr-catalog`، نسخهٔ ۱)

در سایت: `assets/catalog/catalog.json` و عکس‌ها در `assets/catalog/images/`. سایت اگر فایل نبود یا خراب بود همان فهرست داخلی `products.js` را نشان می‌دهد.

```json
{"format": "asr-catalog", "version": 1, "generated_at": "…", "generator": "ShopAdmin 2.12.0",
 "brands": [{"key": "samsung", "name": "Samsung", "tagline": "…"}],
 "items": [
  {"code": "galaxy-a57", "brand": "samsung", "category": "phone", "name": "Galaxy A57",
   "tier": "میان‌رده", "release_year": 2026, "price_state": "استعلام قیمت", "aliases": [],
   "specs": [["باتری", "5000 میلی‌آمپر ساعت"]],
   "colors": [{"name": "سرمه‌ای", "image": "images/galaxy-a57-c1a2b3.jpg"}],
   "image": "images/galaxy-a57.jpg"},
  {"code": "anker-737", "category": "accessory", "group": "powerbank", "name": "پاوربانک Anker 737",
   "brand_name": "Anker", "description": "…", "specs": [], "colors": [], "image": "images/anker-737.jpg"}],
 "images": {"images/galaxy-a57.jpg": {"sha256": "…"}}}
```
هرگز در فایل نیست: قیمت (رقم در برچسب قیمت پذیرفته نمی‌شود)، کد کالای حسابداری، موجودی، مشتری، کلید یا نشانی سرور.

## ظاهر و چیدمان (`asr-site-look`، نسخهٔ ۱ — از ۲٫۱۲٫۰)

در سایت: `assets/catalog/site.json` و عکس‌ها در `assets/catalog/look/` (نام عکس با hash محتوا، تا CDN نسخهٔ کهنه نشان ندهد). فقط رنگ‌بندی‌های آماده و متن ساده — هرگز HTML، CSS یا کد. `site.js` هر مقدار را دوباره بررسی می‌کند (`checkLook`)، متن را فقط با `textContent` می‌گذارد و برای هر مقدار خالی/نادرست همان متن خود صفحه را نگه می‌دارد. اگر فایل نبود، سایت همان ظاهر همیشگی است.

```json
{"format": "asr-site-look", "version": 1, "generated_at": "…", "generator": "ShopAdmin 2.12.0",
 "palette": "violet | ocean | emerald | sunset | ruby | graphite",
 "logo": "look/logo-<hash>.png",
 "hero": {"eyebrow": "…", "title": "…", "highlight": "…", "lede": "…",
          "badges": [{"title": "…", "text": "…"}, {…}, {…}], "images": ["look/banner-<hash>.jpg"]},
 "sections": [{"key": "brands", "show": true}, {"key": "featured", "show": true}, {"key": "accessories", "show": true},
              {"key": "order", "show": true}, {"key": "store", "show": true}, {"key": "faq", "show": false}],
 "brand_order": ["samsung", "apple", "xiaomi"], "phone_order": "auto | manual", "featured": ["galaxy-a57"],
 "store": {"address": "…", "address_short": "…", "phone": "09155000432", "hours": [["جمعه", "تعطیل"]],
           "about": "…", "bale": "https://ble.ir/…", "telegram": "https://t.me/…", "telegram_channel": "", "map": ""},
 "images": {"look/logo-<hash>.png": {"sha256": "…"}}}
```
- رنگ‌بندی: `data-palette` روی `<html>`؛ از بازدید قبلی پیش از اولین نقاشی (localStorage) اعمال می‌شود.
- بنر: عکس اول جای عکس وسط (Samsung)، دوم و سوم جای Apple و Xiaomi؛ عکس‌ها ۱۲۰۰×۶۰۰. لوگو ۲۵۶×۲۵۶ PNG به‌جای نشان «۲».
- بخش‌ها: بنر همیشه اول؛ بخش پنهان و پیوندهای `#…` آن در منو دیده نمی‌شوند.
- ترتیب: کارت‌های برند به ترتیب `brand_order` (آخری پهن)؛ `manual` = گوشی‌های هر برند به ترتیب catalog.json؛ `auto` = جدیدترین اول (مثل همیشه)؛ لوازم جانبی همیشه به ترتیب catalog.json. `featured` خالی = ۴ گوشی جدیدتر.
- اطلاعات فروشگاه: عنصرهای `data-store="address|address_short|phone|about"`، همهٔ پیوندهای `tel:`، ساعت کاری در `data-store-hours` صفحهٔ «تماس»، پیوندهای `data-link-key` (ربات بله/تلگرام خالی = پیوند داخلی سایت). JSON-LD (سئو) در HTML ثابت می‌ماند.
- اگر site.json پس از بازدید قبلی حذف شود (مثلاً «برگرداندن»)، صفحه یک بار با ظاهر پیش‌فرض دوباره بارگذاری می‌شود.

### روش کار در «مدیریت فروشگاه» › «سایت» › «ظاهر و چیدمان»
1. «چیدمان کالاها»: ترتیب برندها؛ برند را انتخاب و گوشی‌ها را بکشید یا «بالاتر/پایین‌تر» (ترتیب دستی می‌شود؛ «ترتیب خودکار (جدیدترین اول)» برمی‌گرداند)؛ ترتیب لوازم جانبی.
2. «تازه‌ترین گوشی‌ها»: «افزودن گوشی…» (تا ۸)، مرتب کردن، «برداشتن از فهرست»؛ «خودکار» = ۴ گوشی جدیدتر.
3. «رنگ و لوگو»: روی یکی از شش رنگ‌بندی کلیک کنید؛ «انتخاب لوگو…».
4. «بنر صفحهٔ اصلی»: متن‌ها و سه نشان › «ذخیرهٔ متن‌های بنر»؛ «افزودن عکس…» تا ۳ عکس.
5. «بخش‌های صفحهٔ اصلی»: کشیدن برای ترتیب، تیک برای نمایش.
6. «اطلاعات فروشگاه»: آدرس، تلفن، ساعت کاری، درباره ما، ربات‌ها، کانال، نقشه › «ذخیرهٔ اطلاعات فروشگاه».
7. «پیش‌نمایش در مرورگر» (همان سایت با دادهٔ این رایانه روی `127.0.0.1`؛ کد سایت از پوشهٔ «خواندن از پوشهٔ سایت…» یا از GitHub) › «انتشار در سایت». «برگرداندن انتشار قبلی» تا ۴۸ ساعت ظاهر و کالاها را با هم برمی‌گرداند.

## انتشار

«انتشار در سایت» = یک commit روی `main` مخزن سایت با GitHub API (catalog.json، site.json و عکس‌هایشان؛ فقط فایل‌هایی که عوض شده‌اند، بدون force)، سپس اجرای گردش‌کار دستی «Deploy static site to ArvanCloud Object Storage». «برگرداندن انتشار قبلی» = commit تازه با نسخهٔ قبلی همان فایل‌ها (تا ۴۸ ساعت).

## ساختن توکن GitHub (یک بار)

1. در github.com با حساب `ghafoorianahmad` وارد شوید.
2. بالا سمت راست، عکس حساب › **Settings** › پایین منوی چپ **Developer settings** › **Personal access tokens** › **Fine-grained tokens** › **Generate new token**.
3. **Token name**: مثلاً `ShopAdmin site`. **Expiration**: مثلاً ۹۰ روز (پس از آن توکن تازه بسازید).
4. **Repository access** › **Only select repositories** › فقط `asr-ertebatat-2`.
5. **Permissions** › **Repository permissions**:
   - **Contents** → **Read and write** (لازم)
   - **Actions** → **Read and write** (برای شروع خودکار «Deploy»؛ اگر ندهید، پس از انتشار باید در GitHub › Actions آن را دستی اجرا کنید)
   - بقیه همان «No access».
6. **Generate token** و متن `github_pat_…` را کپی کنید (فقط همین یک بار دیده می‌شود).
7. در «مدیریت فروشگاه» › «سایت» › «انتشار و پشتیبان»: توکن را بچسبانید › «ذخیرهٔ توکن» › «آزمایش اتصال».

توکن را جای دیگری ننویسید و برای کسی نفرستید؛ اگر لو رفت، همان‌جا در GitHub «Delete» کنید و توکن تازه بسازید.

## فروش فقط در ربات

سایت فقط ویترین است: **سبد خرید ندارد** (سبد ۲٫۱۱٫۰ پیش از انتشار در ۲٫۱۲٫۰ حذف شد). هر مدل دکمهٔ «خرید از ربات» دارد که ربات را با `?start=m_<کد-مدل>` باز می‌کند؛ سفارش و سبد فقط در خود ربات است (همان روال ۲٫۱۰٫۰).
