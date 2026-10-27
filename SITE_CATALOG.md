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

«پشتیبان‌گیری…» یک zip از سه بخش اول می‌سازد؛ «بازگردانی از پشتیبان…» اول یک رونوشت از دادهٔ فعلی نگه می‌دارد.

## قالب فایل سایت (`asr-catalog`، نسخهٔ ۱)

در سایت: `assets/catalog/catalog.json` و عکس‌ها در `assets/catalog/images/`. سایت اگر فایل نبود یا خراب بود همان فهرست داخلی `products.js` را نشان می‌دهد.

```json
{"format": "asr-catalog", "version": 1, "generated_at": "…", "generator": "ShopAdmin 2.11.0",
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

## انتشار

«انتشار در سایت» = یک commit روی `main` مخزن سایت با GitHub API (فقط فایل‌هایی که عوض شده‌اند، بدون force)، سپس اجرای گردش‌کار دستی «Deploy static site to ArvanCloud Object Storage». «برگرداندن انتشار قبلی» = commit تازه با نسخهٔ قبلی همان فایل‌ها (تا ۴۸ ساعت).

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
