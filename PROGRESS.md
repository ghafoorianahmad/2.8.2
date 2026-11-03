# PROGRESS — Asre Ertebatat 2 store system

Phases are defined in `REQUIREMENTS.md` §14. One phase per session.

## v2.17.0 — کدهای وضعیت واقعی، جزئیات مشتری، اعلان کارکنان، دسترسی تک‌تک (2026-11-02، بی‌حضور مالک)

قاعدهٔ این دور: بی‌push؛ دادهٔ آزمایشی فقط در «hesab5 t»؛ پس از هر مورد همین فایل و commit محلی.

### گام‌ها
- [x] ۱. `INVALID_STATUS_CODES {6808}` همه‌جا حذف شد (ذخیرهٔ ShopAdmin، ذخیرهٔ سرور، نویسندهٔ حسابداری، متن راهنما، `.env.example`، تست‌ها). در سرور اصلی «تایید» = ۶۸۰۸ و معتبر است. به‌جایش: عدد باید بزرگ‌تر از صفر باشد (۰ در «سازه حساب» همان «بدون وضعیت» است). تست‌ها: shopapi ۵۷۰ ✓.
- [x] ۲. بدون کد وضعیت معتبر هرگز چیزی در «سازه حساب» نوشته نمی‌شود. علت «بدون وضعیت» امروز: کد ۰ معتبر حساب می‌شد؛ اکنون فقط عدد بزرگ‌تر از صفر. «تأیید رسید» در این حالت: پیش از تأیید هشدار، رسید پذیرفته می‌شود، سفارش `approved` + `accounting_pending` می‌ماند، پس از تأیید هشدار روشن؛ دکمهٔ «ثبت در حسابداری» (`POST /admin/orders/{id}/write-accounting`، تیک جدا) بعداً می‌نویسد، حتی اگر ارسال شده باشد؛ سفارش منتظر بایگانی نمی‌شود. حالت خشک‌اجرا مثل قبل.
- [x] ۳. «رسیدگی شد» بی‌پیام: پنجرهٔ «پیامی برای مشتری بفرستم؟» با موجود شد / فعلاً تأمین نمی‌شود / مدل مشابه داریم / متن دلخواه؛ گزینهٔ «بی‌پیام» نیست؛ سرور هم بی‌پیام رد می‌کند (409). پیام ناموفق حساب نمی‌شود.
- [x] ۷. صفحهٔ تازهٔ «قواعد فروشگاه»: کد وضعیت سفارش (۶۸۰۸) و اختیاری «تحویل به فروش» (۶۹۱۴)؛ فوراً اعمال می‌شود، بی‌راه‌اندازی دوباره. ستون و سطر «مرحله در «سازه حساب»» از `KalaOrder.Status` و `facto`: تأیید / تحویل به فروش / بخشی فاکتور شد / فاکتور شد / وضعیت دیگر / نیست؛ فاکتور بر وضعیت می‌چربد؛ حسابداری قطع = مرحله خالی.
- [x] ۸. «صدور خودکار فاکتور»: فقط جا، خاموش و غیرفعال، با نوشتهٔ «در نسخه‌های بعد».
- [x] ۹. جزئیات مشتری (`shopapi/app/customer_details.py`): پس از شمارهٔ موبایل ربات فقط کمبودها را می‌پرسد (نام، نام خانوادگی، کد ملی با رقم کنترل، آدرس) با «فعلاً نه». شخص تازه: همه هنگام ساخت (`Addres2`، `Codemelli`). شخص موجود: `fill_person_empty` فقط فیلد خالی، شرط در خود UPDATE؛ `Addres` یا `Addres2` پر = آدرس دارد. نرسیدن به حسابداری: در SQLite می‌ماند و هر ۵ دقیقه دوباره. اولین «تأیید رسید»: نام ثبت‌شده کنار «نام واریزکننده»؛ «یکی نیست» چیزی را نمی‌بندد و می‌پرسد «نام واریزکننده ثبت شود یا همان نام بماند؟»؛ ثبت فقط در دادهٔ خود فروشگاه.
- [x] ۱۰. آدرس هنگام سفارش (فقط متن): نبود = می‌پرسد و اولین آدرس ذخیره می‌شود (سازه فقط اگر خالی)؛ بود = «ارسال به: …؟ / آدرس جدید»، آدرس جدید فقط روی همان سفارش. سفارش از پیشنهاد قیمت هم آدرس می‌گیرد. در جزئیات سفارش برای همکار و پیک.
- [x] ۱۱. پیش‌فرض با ویندوز (HKCU، بار اول، قابل خاموش کردن در تنظیمات برنامه)؛ ✕ همیشه به کنار ساعت؛ خروج کامل فقط از منوی همان آیکون با پرسش؛ حذف برنامه کلید اجرای خودکار را برمی‌دارد؛ خاموش شدن ویندوز گیر نمی‌کند.
- [x] ۱۲ و ۱۲ب. موبایل در «کاربران سیستم»؛ همکار یک بار شماره‌اش را در ربات می‌فرستد (`/start`، یا `/staff` اگر قبلاً مشتری است). ساعت کار ۰۹:۰۰ تا ۲۱:۰۰ قابل ویرایش. در ساعت کار: سفارش/رسید/درخواست بی‌صاحب به همهٔ وصل‌شده‌ها در بله و تلگرام، تکرار هر ۵ دقیقه تا «برداشت» (در ربات یا ShopAdmin) یا اولین اقدام؛ بیرون از ساعت: بی‌پیام، یک خلاصه هنگام شروع. داشبورد: «روشن کردن اعلان‌ها»، «خاموش کردن اعلان‌ها»، «تعطیلی امروز»؛ انتخاب دستی تا شروع دورهٔ کاری بعدی (روشن در ساعت کار = برگشت به برنامه تا شب تکرار نشود).
- [x] ۱۵. هر صفحه و هر کار تیک جدا دارد (۳۲ ردیف). استثنا: ورود، خروج، گذرواژهٔ خود، و مدیر که همیشه همه را دارد. کاربر تازه: فقط کار روزانه. کاربر موجود یک بار آنچه داشت را نگه می‌دارد (`permissions_2170`). `test_a_user_without_ticks_is_refused_everywhere` همهٔ مسیرهای `/admin` را می‌گردد. «سایت» داده‌اش روی همان رایانه است، پس تیکش را خود ShopAdmin اجرا می‌کند.
- [x] تست، ممیزی، بیلد، خروجی: shopapi ۶۹۹، shopbots ۳۱۳، shoptg ۸۹، shopsystem ۸۴، shopadmin ۹۰۰ ✓؛ سه ممیزی در هر ۹ ظاهر = ۰؛ تضاد رنگ ۴۲۷/۴۲۷ AA؛ ربات واقعی روی shopapi واقعی از راه HTTP ۱۶ از ۱۶ (حسابداری و بله جعلی). بیلد commit `778b140`، ProductVersion هر دو ۲٫۱۷٫۰، کپی در `E:\Outputs\ShopSystem` با SHA-256 برابر، جفت ۲٫۱۶٫۰ پاک شد. عکس‌ها `shopadmin/docs/screens_2.17.0/`. `PRODUCTION_GUIDE_FA.txt` عوض نشد و هنوز کد وضعیت را در «سرور فروشگاه» می‌نویسد.
- **تصمیم‌ها:** کد ۰ نامعتبر؛ روزهای کاری پیش‌فرض شنبه تا پنجشنبه (مثل فروش گوشی)؛ نام واریزکننده فقط در فروشگاه؛ چت همکار حساب مشتری نمی‌سازد؛ آدرس در `Addres2` طبق دستور §5.1.
- **نکتهٔ اجرا:** این جلسه به `hesab5 t` راه نداشت (`Access denied` روی لولهٔ SQL Server، حتی بی‌sandbox) و سرور فروشگاه هم نصب نیست؛ پس SQLهای تازه و `upgrade_2_17_0.sql` فقط با fake آزموده شده‌اند، نه روی SQL واقعی. مدیر باید پس از نصب بیازماید.

## v2.15.0 — نوار «حالت آزمایشی»، ارتقا بی‌تغییر تنظیمات، دکمه‌های مثل سایت، چندانتخابی (2026-11-01، شاخهٔ `feature/order-flow-v250`) — DONE in code, built (not installed: no admin rights)

قاعدهٔ این دور (مالک، بی‌حضور): بی‌دسترسی مدیر (بی‌نصب، بی‌راه‌اندازی دوبارهٔ سرویس)، بی‌push، بی‌انتشار سایت، نوشتن فقط در «hesab5 t»؛ هر مورد با **عکس واقعی ShopAdmin در حال اجرا** (`shopadmin/scripts/live_shot.py`: همین کد، نسخهٔ کلاینت، نشست ذخیره‌شدهٔ همین کاربر ویندوز، سرور واقعی روی 127.0.0.1:8443؛ فقط خواندن). عکس‌ها: `shopadmin/docs/screens_2.15.0/`.

### گام‌ها
- [x] ۲. ارتقا هرگز تنظیمات را عوض نمی‌کند.
  - **علت (در کد تأیید شد):** (الف) نصب‌کنندهٔ سرور پس از **هر** نصب، حتی ارتقا، «راه‌اندازی سرور» (`--server-setup`) را با تیک پیش‌فرض باز می‌کرد و آن حالت تنظیمات فعلی را نمی‌خواند: همهٔ کادرها خالی، فهرست پایگاه‌داده‌ها از نو (اولین = «hesab5»)، فهرست مجاز و «ثبت واقعی» خالی، و «ذخیره» همه را روی `.env` می‌نوشت (به‌علاوهٔ ADMIN_CHAT_IDS، پوشهٔ پشتیبان، راه‌انداز ODBC که همیشه به Driver 17 برمی‌گشت). (ب) سرور `ACCOUNTING_DATABASE` را پیش از `DB_NAME` می‌خواند ولی «تنظیمات سرور» برعکس می‌خواند و فقط `DB_NAME` را می‌نوشت: اگر `.env` هر دو را داشت، پنجره پایگاه‌دادهٔ تازه را نشان می‌داد و سرور همان قبلی را به کار می‌برد. (`.env` واقعی خوانده نشد: هم ممنوع است هم فقط برای مدیر.)
  - **رفع:** `ShopAdmin.iss`: «راه‌اندازی سرور» پس از نصب فقط برای سرور تازه (`Check: IsNewServer`)؛ ارتقا = همان پوشهٔ داده و ثبت دوبارهٔ سرویس، بی‌هیچ نوشتن در `.env`. پنجرهٔ راه‌اندازی روی سروری که تنظیمات دارد همیشه با همان مقدارها باز می‌شود (حالت «تنظیمات»)؛ اگر `.env` خوانده نشد، ذخیره انجام نمی‌شود (هرگز خالی روی تنظیمات واقعی). ترتیب خواندن = ترتیب سرور؛ `init_config` نام دوقلو (`ACCOUNTING_DATABASE`، `ACCOUNTING_SERVER`، …) را هم با همان مقدار عوض می‌کند. راه‌انداز ODBC ذخیره‌شده حفظ می‌شود.
  - **تست:** `shopsystem/tests/test_v2150.py` (شبیه‌سازی ارتقا روی ۱۸ تنظیم: انتقال پوشه + ثبت سرویس + ذخیرهٔ بی‌تغییر = همه دست‌نخورده؛ دوقلوی قدیمی؛ پیش‌فرض‌ها فقط بار اول؛ `[Run]` نصب‌کننده)، `shopadmin/tests/test_v2150_upgrade.py` (۴).
- [x] ۱. نوار «حالت آزمایشی»
  - **علت دقیق (در کد و با ShopAdmin واقعی تأیید شد):** نوار فقط از پاسخ `/admin/system-info` هنگام شروع برنامه (یا آخرین بار داشبورد) پیروی می‌کرد؛ صفحهٔ «تنظیمات سرور فروشگاه» هر بار وضعیت تازه می‌خواند. ۲۸ مهر: ShopAdmin ساعت ۱۶:۱۹ (پس از نصب ۲٫۱۴٫۰، با تنظیمات به‌هم‌ریختهٔ مورد ۲) وصل شد، ۱۶:۲۰ «تنظیمات سرور» ذخیره و سرویس دوباره راه‌اندازی شد؛ صفحهٔ سرور «فعال — ثبت واقعی» می‌گفت ولی نوار همان وضعیت کهنه را نگه داشت (پس از وصل شدن دوباره هم دوباره خوانده نمی‌شد). شرط ایمنیِ واقعاً ناقص در سرور فعلی نیست: امروز سرور «فعال — ثبت واقعی در «hesab5»» و کد وضعیت تنظیم‌شده گزارش می‌دهد و با کد تازه نوار پنهان است (`docs/screens_2.15.0/item1_live/`).
  - **رفع:** `AppContext.write_problems()` = فهرست دقیق کمبودها: «hesab5 t» در فهرست مجاز نیست / «ثبت واقعی» برای … روشن نیست / پایگاه‌داده انتخاب نشده / «کد وضعیت سفارش» تنظیم نشده (این آخری قبلاً اصلاً نوار نمی‌داد، با اینکه بی آن هیچ سفارشی ثبت نمی‌شود). نوار همین‌ها را می‌گوید و برای هر کدام دکمه دارد: «باز کردن «تنظیمات سرور»» (روی رایانهٔ سرور خود پنجره را باز می‌کند، جای دیگر ردیف «ثبت در حسابداری» + توضیح) و «تنظیم «کد وضعیت سفارش»» (صفحهٔ سرور، مکان‌نما در همان کادر). کاربر فروش فقط متن را می‌بیند. همه شرط‌ها برقرار = نوار نیست. تازه ماندن: هر پاسخ صفحهٔ سرور، هر ۶۰ ثانیه، و پس از هر وصل شدن دوباره.
  - **تست:** `shopadmin/tests/test_v2150_banner.py` (۸). عکس حالت‌ها با پنجرهٔ واقعی و سرور آزمایشی: `docs/screens_2.15.0/item1_states/`.
- [x] ۳. دکمه‌ها مثل سایت زنده
  - **مرجع:** CSS سایت از `origin/main` در `E:\DSH-Workspace\asr-site-live` (`assets/theme.css`: `.btn--solid` = `linear-gradient(115deg, #7c6cff, …, #38d6ff)` + `inset 0 1px 0 rgba(255,255,255,.35)` + سایهٔ بنفش `0 16px 34px -14px`؛ `.btn--ghost` = پرشدهٔ ملایم ۵٪ رنگ متن با لبهٔ خنثی `rgba(20,30,60,.14)` / تیره `rgba(255,255,255,.17)` و سایهٔ کوچک `0 1px 2px`؛ hover = لبه و رنگ فیروزه‌ای + بالا آمدن). عکس واقعی سایت زنده (asrertebatat2.ir، صفحهٔ Samsung، روشن و تیره) در `docs/screens_2.15.0/site_ref/`.
  - **علت عدم تطابق ۲٫۱۴٫۰:** دکمهٔ عادی لبهٔ رنگی (رنگ اصلی، ۳:۱ برای ممیزی ۲٫۹٫۴) داشت و سفید→رنگ ملایم بود؛ دکمهٔ اصلی گرادیان آبی→بنفشِ هر رنگ‌بندی (زمرد سبز) و تیره‌تر از سایت بود؛ «ساده» بی‌گرادیان و بی‌درخشش.
  - **رفع (`app/ui/theme.py`):** اصلی در هر ۹ ظاهر = گرادیان ۱۱۵° سایت (همان رنگ‌های سایت ولی عمیق‌تر: `#6E5CF7` → `#346FE3` → `#1677B8`، تا متن سفید روی هر ایستگاه ≥ ۴٫۵:۱ (WCAG AA) بماند — سایت خودش ۳٫۹ / ۲٫۵ / ۱٫۷:۱ است؛ نسخهٔ روشن‌ترِ نزدیک‌تر به سایت در تست‌های AA موجود رد شد)، لبهٔ روشن بالا، درخشش بنفش زیر آن؛ عادی = پرشدهٔ روشن نرم (`#FAFBFD→#ECEFF5`، تیره: سفید ۱۱٪→۵٪)، لبهٔ خنثی کم‌رنگ و لبهٔ پایین مثل سایهٔ کوچک سایت، بی‌لبهٔ رنگی/تیره؛ hover = رنگ و لبهٔ فیروزه‌ای + درخشش فیروزه‌ای (اصلی: درخشش بنفش بزرگ‌تر)؛ pressed = تیره‌تر و فرورفته؛ زبانهٔ انتخاب‌شده = گرادیان سایت. «ساده» هم گرادیان و درخشش hover دارد (فقط سایهٔ دائمی ندارد).
  - **ممیزی دکمه:** قاعدهٔ «کم‌رنگ» از ۳:۱ به ۱٫۴:۱ (سبک «مشخصات» سایت؛ دکمهٔ بی‌پرشدگی و بی‌لبه هنوز ۱:۱ = خطا)؛ contrast_audit ایستگاه‌های گرادیان را هم می‌سنجد (۴۲۷/۴۲۷ AA). `button_audit.py` = ۰ در ۹ ظاهر.
  - **عکس‌ها:** کنار هم (سایت | عادی | hover | فشرده) در هر ۹ ظاهر: `docs/screens_2.15.0/buttons/gallery_all.png` (+ هر ظاهر جدا)؛ ShopAdmin واقعی روی سرور زنده: `docs/screens_2.15.0/item3_live/`.
- [x] ۴. چندانتخابی در فهرست‌های «سایت»
  - `widgets.DataTable.enable_checks()`: ستون اول = تیک هر ردیف (`set_check`، `checked_keys`، `set_all_checked`، سیگنال `checks_changed`؛ ظاهر تیک جدول = همان تیک‌های برنامه). «سایت» › گوشی‌ها و لوازم جانبی: «انتخاب همه»، شمار «۳ انتخاب‌شده»، «حذف» / «پنهان» / «نمایش» روی همهٔ تیک‌خورده‌ها (بی‌تیک = همان ردیف انتخاب‌شده، مثل قبل). تیک‌ها پس از هر بارگذاری دوباره می‌مانند.
  - حذف گروهی = `store.delete_many`: هر کالا مثل حذف تکی ۴۸ ساعت در «حذف‌شده‌ها» با یک شناسهٔ گروه؛ «برگرداندن حذف‌شده‌ها…» اول «همهٔ N مورد حذف‌شده با هم» را پیشنهاد می‌کند (`undelete_many`)؛ «برگرداندن انتشار قبلی» هم مثل قبل برمی‌گرداند. پیش از حذف تأیید با نام ۵ مورد اول و شمار بقیه.
  - **فهرست‌های دیگر:** تیک گذاشته نشد. سفارش‌ها، مشتریان و هر دادهٔ حسابداری ممنوع است؛ «درخواست کالا» پیام به مشتری می‌فرستد؛ نگاشت ردیف‌های لیست قیمت تصمیم جدا برای هر ردیف است (نگاشت اشتباه گروهی = قیمت/کالای اشتباه برای مشتری)؛ کاربران/پراکسی/بایگانی کار گروهی امنی ندارند.
  - **تست:** `tests/test_v2150_bulk.py` (۶). عکس واقعی ShopAdmin روی دادهٔ واقعی این رایانه (فقط تیک روی صفحه، چیزی ذخیره نشد): `docs/screens_2.15.0/item4_live/site.png`، `site_ticked.png`.
- [x] تست همه + سه ممیزی + نسخه ۲٫۱۵٫۰
  - تست‌ها: shopapi ۵۶۹، shopbots ۲۸۷، shoptg ۸۹، shopsystem ۸۴ (با `TEMP` در پوشهٔ قابل نوشتن: `test_update_from_zip…` در `%TEMP%` این PC «Access is denied» می‌گیرد — مشکل قدیمی پوشهٔ موقت، فایل‌هایش از فاز ۴ دست نخورده)، shopadmin ۷۹۴ ✓.
  - سه ممیزی در ۹ ظاهر: متن بریده ۰، RTL ۰، دکمه ۰؛ contrast_audit ۴۲۷/۴۲۷ AA.
- [x] commit، بیلد، ProductVersion، Outputs — بیلد از commit `86eee7d` (تست‌های داخل بیلد سبز: shopapi ۵۶۹، shopbots ۲۸۷، shoptg ۸۹، shopsystem ۸۴، shopadmin). ProductVersion هر دو 2.15.0. کپی با SHA-256 برابر در `E:\Outputs\ShopSystem\` (Server `DAEA1C3F…`، Admin `C8009DFB…`)؛ جفت‌های ۲٫۱۳٫۰ و ۲٫۱۴٫۰ پاک شدند (فقط جدیدترین جفت)؛ هر دو README_FA.txt به‌روز. چیزی نصب نشد؛ push نشد.

### تصمیم‌ها
- ارتقا هیچ پنجرهٔ تنظیمی باز نمی‌کند؛ برای تغییر، میان‌بر «تنظیمات سرور» روی میزکار.
- دکمهٔ اصلی در هر سه رنگ‌بندی همان گرادیان سایت است (نه رنگ هر رنگ‌بندی)؛ رنگ‌ها عمیق‌تر از سایت تا قاعدهٔ AA خود برنامه (۴٫۵:۱ متن سفید) بماند — شکل، جهت، لبهٔ روشن بالا و درخشش بنفش همان سایت است.
- قاعدهٔ «کم‌رنگ» ممیزی دکمه به درخواست صریح مالک (بی‌لبهٔ رنگی/تیره) از ۳:۱ به ۱٫۴:۱ آمد.
- «ساده» درخشش hover دارد (فقط برای دکمهٔ زیر نشانگر ساخته و با رفتن نشانگر برداشته می‌شود)؛ سایهٔ دائمی پنل/دکمه همچنان فقط در «کامل».
- نوار «حالت آزمایشی» برای کاربر فروش فقط متن دارد (دکمهٔ تنظیم فقط برای کسی که «تنظیمات سرور فروشگاه» را می‌بیند).

## v2.14.0 — site tree, table PDFs, de-duplication, price per item, new buttons, other price channels, «سلامت سیستم» (2026-10-28, branch `claude/site-shopadmin-tree-bb74e8` from `feature/order-flow-v250`) — DONE in code; not installed (no admin rights)

Step by step, decisions and the OCR measurement: `PROGRESS_SITE.md` (v2.14.0). Site repo: local commit `3ca2aba` (not pushed, not published).

## v2.13.0 — owner's 11-point list after testing the installed 2.12.0 (2026-10-27, same branch) — DONE in code, built (not installed: no admin rights)

Owner's rules for this run: no admin rights (no service restart, no install, no helper task), test the running ShopAdmin as it is, DB writes only in «hesab5 t», no «پاک‌سازی», no site publish, no push, never message customers. Build goes to `E:\Outputs\ShopSystem\`; the owner installs and re-tests.

**Step 1 — real test of the running 2.12.0 (ShopAdmin driven through UI Automation, `pywinauto`; computer-use tools were not available) — DONE**
- «تنظیمات سرور فروشگاه»: server up 36 min (restarted by «تنظیمات سرور» at 17:56), Telegram reader connected via 135.181.74.178:443 and reporting today; «لیست قیمت کانال — آخرین فایل: ۱۴۰۵/۰۸/۰۵ — خوانده نشد (قالب ناشناخته)»; «پشتیبان‌گیری روزانه: ناموفق در ۱۴۰۵/۰۸/۰۵ (PermissionError: Access is denied) — آخرین پشتیبان موفق: ۱۴۰۵/۰۸/۰۳». `D:\ShopServerData` (logs, status.json) is admin-only: not read.
- **#6 cause (confirmed):** the 1405/08/05 PDF has a second نقد/روال header row lower in the middle block (sub-section «TABLET XIAOMI», y=430); the parser refused any header below the top line ("price headers are not on one line").
- **#5 cause (confirmed by running the installed `ShopSystem.exe --list-dbs` against a non-existing server):** the frozen exe prints its JSON answer with Persian text through a cp1252 stdout (PyInstaller ignores `PYTHONIOENCODING`) → `UnicodeEncodeError` (also in ShopAdmin's `app.log` at 17:50) → ShopAdmin gets no kind (`db_access`) → never offers/does the grant; every DB whose check answers in Persian (no access, missing, …) fails. «hesab5 t» worked only because its success answer has no Persian.
- **#3 cause (confirmed):** the off-server folder `\\192.168.20.150\E` is NOT this PC (this PC = 192.168.40.100, its shares are only `work` and `users`); it is another computer the owner reaches with saved credentials (`Z:`). The service runs as `NT SERVICE\ShopServer`, which reaches another computer's share without any user name → "Access is denied". 2.9.4 assumed it was this PC's own E: drive. `\\192.168.20.150\E\ShopServerBackup` was created today 17:55 by the owner's own test and is empty. The last good backup (1405/08/03) was before the off-server copy was configured.
- **#2 (likely cause, logs not readable without admin):** the worker loop pauses EVERY job during a Telegram FloodWait and does not publish its status while paused, and the supervisor only restarts a process that exits — a worker that stays alive but stops working (long FloodWait on a channel lookup, or a hang) shows as «stopped» until someone restarts the service (which is what «تنظیمات سرور» did today). Fix = watchdog + status while paused + cached channel lookup (step 3).

**Step 2 — #6 PDF reader — DONE** `shopapi/app/pricelist/parser.py`: the column headers are the top line; a lower نقد/روال pair is accepted only as a sub-section header (a نقد then روال pair on one line, inside one block, within 20 pt of that block's price columns) and skipped, anything else is still a layout change. Today's list: 208 rows, no warnings. Sample `samples/price_list_1405-08-05.pdf`; tests `shopapi/tests/test_v2130.py`.

**Step 3 — #2 / #4 worker watchdog, auto-restart, one alert — DONE (code + tests, not on the real service)**
- shoptg: a heartbeat file (`<data>\shoptg.heartbeat`, `TG_HEARTBEAT_FILE`) touched every 30 s by its own task; one round of jobs over 30 min = `WorkerStuck` → exit code 4; during a FloodWait the status is still published every minute with `paused_until` (ShopAdmin: «تلگرام خواسته تا … صبر کند»), a wait of an hour or more raises `telegram_flood_wait` once; the price channel is looked up (ResolveUsername) once and kept across reconnects (`gateway._peer`) — frequent lookups are what earns long FloodWaits.
- supervisor (`launcher.supervise_child`): kills a child whose heartbeat is older than 10 min and starts it again; `on_incident` once per incident (a new incident only after 30 min of healthy running); the supervising loop can no longer die on its own error; the server process exits (code 5) when its bots/API thread gave up, so it is restarted too. Alert = `POST /worker/alerts {"kind": "worker_restarted"}` → ShopAdmin notification + one Bale message (6 h dedupe); when the API itself is down: the direct Bale message.
**Step 4 — #3 backup to another computer — DONE (code + tests; the real share not tried, needs admin/the owner's account)**
- `shopsystem/netshare.py`: `WNetAddConnection2W` with `BACKUP_SHARE_USER` / `BACKUP_SHARE_PASSWORD` for the copy, disconnected afterwards (no drive letter, password never logged); Persian reasons for 5/53/67/86/1219/1326/1327/1331.
- `backup.run_backup`: `local_ok` / `last_local_success_at` (the copy on the server is reported apart); a PermissionError on a network folder without a user name says so.
- «تنظیمات سرور» › «پشتیبان بیرون از سرور»: «نام کاربری / گذرواژهٔ رایانهٔ مقصد» shown only for `\\PC\Share`; «آزمایش» with the service account signs in with them (`/admin/server/backup-test` takes user/password; empty password = saved one).
- ShopAdmin status row: the reason in Persian (`offsite_reason_fa`), «پشتیبان روی خود سرور: سالم», «آخرین پشتیبان کامل موفق».
**Step 5 — #5 DB auto-grant — DONE (code + tests; the real grant needs admin)**: `ShopSystem.exe` writes its JSON answers ASCII-only and reconfigures stdout/stderr to UTF-8 (`utf8_console`); the wizard saves + tests as soon as a database is picked from the list and, when the answer is «دسترسی نیست», grants (`--grant-db`) without asking and tests again; the manual button keeps its confirmation.
**Step 6 — #1 / #6 / #7 / #8 price list — DONE**
- archive `<data>\pricelists\1405-08-05-1.pdf` (`pricelist/pdf_archive.py`) for every received file (also «older» ones, which were not kept before); never deleted; reminder event + Bale on 1 Farvardin / 1 Tir / 1 Mehr / 1 Dey, once each, the first check after the upgrade only notes the quarter; the service grants BUILTIN\Users read on that folder (install / «تنظیمات سرور»); «تنظیمات سرور فروشگاه»: path, count, size, «باز کردن پوشه» (only when ShopAdmin runs on the server).
- «خواندن دوباره» per received list (`POST /admin/pricelists/{id}/reread`, answer within 60 s: `timeout`): a failed list that reads now is imported in place (same id/file); failing again only updates the reason (no second alert); a good list is only checked (`read`). The same rejected file arriving again is read again; once per version, rejected lists of the last 3 days are read again at start (fixes today's 1405/08/05 list after the upgrade).
- «دریافت لیست اکنون» (`POST /admin/pricelists/fetch`, state `tg_price_request/done`): the reader sends the newest list even when unchanged; waits for a connection; ShopAdmin looks for the result for a minute.
- rejected file: one `pricelist_failed` event (ShopAdmin + the bot's Bale notice), as before; reasons shown in Persian in the lists table.
- also fixed from 2.12.0's log: «Internal C++ object (Toast) already deleted» (`widgets._alive`).
Tests: shopapi 565, shoptg 87, shopsystem 80 ✓ (shopadmin running).

**Step 7 — #9 / #10 / #11 UI — DONE in code (audits in all 9 looks: see step 8)**
- #9 `theme.glass_fills`: every normal / Tab button has a see-through fill (white glass in light, smoked glass in dark; «ساده» = flat but still see-through) with a light top edge; hover = lighter fill + accent frame + (جلوه‌ها: کامل) a soft accent halo made on enter and removed on leave (`theme._Effects._glow`, never on idle buttons or table cells); pressed = the thick edge moves to the top, the text 1 px down, darker fill (height unchanged, `button_audit`). Primary / Success / Danger stay coloured with a light sheen; their shadow turns into the accent glow on hover. The 3:1 frame (`BUTTON_BORDER`) stays.
- #10 `widgets.KeyValueList` (captions in one column, values in the other, one spacing) for «جزئیات سفارش», «درخواست»، «کالا»; `widgets.keep_together` in every wrapped label: «(کد شخص ۴)», «hesab5 t», «۳۶ دقیقه» never split; every form's captions centred on their field (`setLabelAlignment(RIGHT | AlignVCenter)`, 7 files); «پایش سلامت» one check per line; the server page's archive row with its button under the path.
- #11 `widgets.dialog_area` / `fit_window_to_screen`: a dialog of the main window is at most 94 % of that window (title bar included), opens centred on it and inside it, long content scrolls inside (`make_responsive`); dialogs from dialogs are bounded by the main window too; without a main window: the screen as before.
- price-list lists table: rows as tall as their «خواندن دوباره» button.

**Step 8 — tests, audits, build, Outputs — DONE**
- Tests (build): shopapi 560, shopbots 287, shoptg 87, shopsystem 80, shopadmin 754 ✓. Audits in all 9 looks: buttons 0, cut text 0, RTL 0; contrast_audit 420/420 AA.
- Build from commit `d6010c7`: both installers ProductVersion 2.13.0; the built `ShopSystem.exe --list-dbs` now answers in (escaped) Persian through a pipe (2.12.0: UnicodeEncodeError); `netshare` is in the build.
- `E:\Outputs\ShopSystem\`: `ShopServerSetup_2.13.0_2026-10-27.exe` (SHA-256 6EA20656…4DE6), `ShopAdminSetup_2.13.0_2026-10-27.exe` (AB395C59…9774), copies verified, the 2.12.0 pair removed, README_FA.txt + `E:\Outputs\README_FA.txt` row updated. Screenshots of every screen in 4 looks: `shopadmin/docs/screens_2.13.0/` (not committed, 20 MB).
- Fixed along the way: a parametrised look test that re-applied the theme to the test app took ~10 min per look (now builds the style sheet only); `existing_config_port` no longer crashes without admin rights; label `text()` = the text itself (no-break spaces are display-only).

**Waiting on the owner (admin rights):** install 2.13.0 on this PC; `shoptg.log` / `supervisor.log` for the exact cause of the 1405/08/04 stop; the backup share's user name / password + «آزمایش»; pick «hesab5» once (auto-grant needs a sysadmin Windows account); «دریافت لیست اکنون» once.

**Decisions so far:** archive names use the receive date (Tehran, Jalali) — a list posted late on 08/04 for 08/05 would be `1405-08-04-n`; an identical file received again is not stored twice; «خواندن دوباره» on a list that was read before changes nothing (its rows and decisions stay); the automatic grant only for «دسترسی نیست» answers (never for a wrong password / missing server); the crash-loop Bale message of 2.9 was replaced by the one-per-incident alert.

## v2.12.0 — the site is a showcase only (no cart) + «ظاهر و چیدمان» in ShopAdmin (2026-10-27, same branch) — DONE in code; site committed locally only; nothing published or installed

Owner's decision change after 2.11.0; step-by-step log in `PROGRESS_SITE.md`, decisions in `REQUIREMENTS.md` §7j, format and how-to in `SITE_CATALOG.md`.

1. **Site cart removed before it was ever published** — site commit `1d7d23c` reverts `22056b7` + `c457494` (the accessory description stays); server and bots: the code of `df7f19a` reversed (`site_cart.py`, `POST /cart-requests`, `/start c_…`, `SITE_CART_*`, tests); `shopbots/` is byte-identical to v2.10.0; ShopAdmin's cart hash and its error text removed. Selling = only the bots' own cart / order flow; per-model «buy via bot» links (`?start=m_`) stay.
2. **«ظاهر و چیدمان»** (`app/site/look.py`, `app/ui/site_look.py`): brand / phone / accessory order (drag or «بالاتر/پایین‌تر», «ترتیب خودکار»), «تازه‌ترین گوشی‌ها» (≤ 8, empty = 4 newest), six colour presets, logo (256×256 PNG), banner texts + 3 badges + ≤ 3 pictures (1200×600), home section order / show-hide, store address / phone / hours / about / bot, channel and map links (checked). Published as `assets/catalog/site.json` (`asr-site-look` v1) + `look/` pictures in the same commit as catalog.json, so the 48-hour rollback undoes both; backup / restore and «خواندن از سایت» carry it.
3. **Browser preview** (`app/site/preview.py`): the site's own code (the folder of «خواندن از پوشهٔ سایت…» or a cached copy from GitHub) + this computer's catalog.json / site.json, served on 127.0.0.1 and opened in the computer's browser.
4. **Site** (commit `25ad4f2`): `site.js` reads site.json (checked again, textContent only, safe fallback, palette before first paint, a removed file reloads once to the built-in look); `data-look` / `data-store` marks; palette CSS in `theme.css`.
5. **End to end** — `shopadmin/scripts/e2e_site_mock.py` against a fake GitHub holding the real site's 318 files: 30/30 checks; the published, rolled-back and a tampered site.json checked in a browser.

## v2.11.0 — «سایت» only in ShopAdmin (no server) + site cart -> bot (2026-10-27, same branch) — DONE in code; site committed locally only; nothing published or installed

Owner's request after 2.10.0; step-by-step log in `PROGRESS_SITE.md`, decisions in `REQUIREMENTS.md` §7i, format / token guide in `SITE_CATALOG.md`.

1. **Security check** (report only) — bots inside ShopServer, outbound only; shopapi for the LAN only (firewall local subnet, service keys loopback); the site never talks to the server.
2. **Server parts of 2.10.0 removed** — `site_export.py`, `routers/site_catalog_export.py`, `site_data`, `SITE_IMAGES_DIR`, the schedule; the accessory-PDF reader moved to ShopAdmin (`app/site/accessory_pdf.py`; ShopAdmin bundles pdfplumber + Pillow).
3. **ShopAdmin «سایت»** (`app/site/` logic, `app/ui/pages/site.py`, `app/ui/site_dialogs.py`): data in `<data>\site\`, phones / accessories / show-hide / new phone with a photo per colour / photos to 1280×1024 on #FBFCFF (Qt) / preview / backup-restore / «خواندن از سایت» (GitHub) or «خواندن از پوشهٔ سایت…».
4. **«انتشار در سایت»** — GitHub Git Data API commit (`app/site/github.py`, `publish.py`), token with DPAPI (`app/site/token.py`), «آزمایش اتصال», deploy workflow dispatch, 48-hour rollback; tested only against `tests/fake_github.py`.
5. **Site cart** (site commits `22056b7`, `c457494`) — «افزودن به سبد», `cart.html`, top-bar cart, `?start=c_<code>`, the code shown on the cart page as a fallback.
6. **Bots** — `/start c_…`, a pasted code, kept through registration -> `POST /cart-requests` (`shopapi/app/site_cart.py`) -> one purchase request per line.

Tests: shopapi 550, shopbots 292, shoptg 81, shopsystem 67, shopadmin 699 ✓; text-fit / RTL / button audits 0 in all 9 looks (the «سایت» page with its three tabs and the four new dialogs included).

## v2.10.0 — site audit + the site's catalogue from ShopSystem (2026-10-27, same branch) — DONE in code; site committed locally only; nothing published or installed

Owner's two-part request. Decisions in `REQUIREMENTS.md` §7h; format and delivery options in `SITE_CATALOG.md`.

**Part A — site audit** (GitHub `asr-ertebatat-2` `main` = live files, cloned in `E:\DSH-Workspace\asr-site-live`, push disabled; local commit `5e18fd4`):
1. **Photos** — 66 models (Apple 15, Samsung 27, Xiaomi 24), 296 JPEGs: every referenced file exists, decodes (PIL) and loads in the browser; colour lists and photo slugs line up for all 63 mapped models. Checked by eye on contact sheets. Problems: `xiaomi-17-pro`, `redmi-15`, `redmi-14c` have only a 160×212 card and no colour photos; the `redmi-15` card is green, a colour the model does not list; `poco-f7-pro` photos are dark lifestyle shots; the `poco-c75` black photo shows a different camera module from green / gold; `galaxy-a57` card had a black box (now its own navy photo). No accessories on the site.
2. **Fixed** — home featured cards' «مشخصات» / «ثبت سفارش» did nothing (no modals on `index.html`); dead `#store` / `#order` / `#about` links on brand / about / contact pages; the phone menu cut «تماس»; Bale missing in the floating menu; the map's pending message spoke of the bot; deep link now `?start=m_<code>`; detail photo eager; `MODEL_CAMS` keys of Fold 7 / Flip 7; duplicated theme / device code. No console errors; light / dark, RTL, 375 px without horizontal scroll checked in the browser.
3. **Not changed (owner's call)** — `USE_UNLICENSED_PHOTOS = true` on the live site against its own licence comment.

**Part B — catalogue from ShopSystem**:
1. `shopapi/app/site_export.py` — format `asr-catalog` v1; `catalog_models.site_data` (JSON) + `site_images/`; a JS-literal reader seeds it from the site's `products.js` + `site.js` (data only, never executed); build / validate (no digits in the price label, image paths `images/…` only) / preview diff against the last export / zip / folder (photos first, `catalog.json` last) / daily schedule (`export_loop`, only on changes).
2. `shopapi/app/accessory_pdf.py` — pdfplumber: «عنوان: مقدار» lines = specs, other lines = item titles, pictures (≥ 60 pt) to the nearest title above; group from words; code from Latin words. Placeholder PDFs generated in the tests.
3. Endpoints `/admin/site-catalog/*` (`routers/site_catalog_export.py`): preview, export (zip), export-folder + schedule (`server.edit`), models/{id} site data, images, seed, accessory-pdf.
4. ShopAdmin — «مدل‌های سایت» › «خروجی کاتالوگ برای سایت…» (preview, «ذخیرهٔ فایل خروجی…», schedule, «خواندن از پوشهٔ سایت…», «خواندن PDF لوازم جانبی…») and «اطلاعات سایت…» per model (`app/ui/site_export_dialog.py`); the three dialogs are in `audit_screens.py`.
5. Site — `loadCatalog` / `applyCatalog` in `site.js` (2.5 s, then the built-in list); accessories in the home page's «لوازم جانبی». Checked in the browser with a catalogue built from the real 66 models + 296 photos and with an unknown version (fallback).

Tests: shopapi 559, shopbots 287, shoptg 81, shopsystem 67, shopadmin 684 ✓; text-fit / RTL / button audits 0 in all 9 looks. Client code never names the server program (`test_client_code_never_mentions_the_server_program` caught «ShopSystem» in the new dialog).

## v2.9.4 — last release before the real server: database drop-down + precise errors tested as the service account, install folders on D:, owner on reinstall, eye on every password, live look, money input, Persian-only errors, real «بستن», backup root cause, cleanup tool, status-code helper (2026-10-26, same branch) — DONE in code; the new build NOT installed

Owner's list after installing and testing 2.9.3 on this PC. Decisions in `REQUIREMENTS.md` §7g. Production steps: `E:\Outputs\ShopSystem\PRODUCTION_GUIDE_FA.txt`.

1. **Database drop-down** — `shopapi/app/db_setup.list_databases` (this Windows account on `master`, then the SQL login; `sys.databases`, user databases only), `ShopSystem.exe --list-dbs` (server / login / password as JSON on stdin), wizard `DatabasePicker` (not editable; a saved name missing on the server is marked), loaded when the database page opens and when the server name changes; the allowed-databases list uses the same picker.
2. **Precise errors** — `db_setup.diagnose`: `server_not_found` (53, 2, 10060, 10061, 08001 …), `db_missing` (`DB_ID` is NULL, with the real list), `no_access` (4060 / 916 / 229 / 230 / login missing) → «دادن دسترسی به این دیتابیس», `bad_password` (18456 with an existing login), `remote_windows`; each with a Persian title and its fix (`server_setup.DatabaseCheckError.kind`).
3. **Tested as the service** — 2.9.3 tested Windows sign-in with the administrator's own account. Now `check_as_service` impersonates the service's login (`EXECUTE AS LOGIN` = `NT SERVICE\ShopServer`, or `DOMAIN\PC$` for a SQL Server on another computer; name as a parameter, `REVERT`) for the same reads, and in «تنظیمات سرور» the running service also tests itself (`POST /admin/server/db-check`, service key, like the backup test). «دادن دسترسی» grants exactly that login (`grant_access.shop_login` → `db_setup.shop_login`), registers the service first when its account does not exist yet (CREATE LOGIN … FROM WINDOWS needs it), then tests again as that login. **Not run on a real SQL Server yet.**
4. **Install folders** — both installers: `DisableDirPage=no`, `UsePreviousAppDir`, default `D:\ShopServer` / `D:\ShopAdmin` when D: is a fixed disk (`GetDriveTypeW`), else Program Files. Server: a data-folder page (default `D:\ShopServerData`, else `%ProgramData%\ShopServer`; remembered in `HKLM\SOFTWARE\ShopServer\DataDir`, read by ShopSystem `resolve_data_dir` and ShopAdmin `server_setup.data_dir`); data in another folder (2.9.3: ProgramData) → «انتقال امن» = `ShopSystem.exe --move-data`: copy + SHA-256 of every file, lock the folder, registry, service re-registered there, start, `/health`; only then the old folder is deleted; any failure = registry and service back to the old folder, nothing deleted. The program folder is locked (SYSTEM / Administrators full, users read) because a D: root lets Authenticated Users modify. After every upgrade the service is re-registered (grants again).
5. **«مدیر کل» on reinstall / settings** — the owner step is in both modes: «مدیر کل فعلی: <username> — اگر خالی بگذارید همان می‌ماند»; blank = keep, same username + password = reset (unlocked, sessions ended), new username = one more owner (`GET/POST /auth/owner`, service key only; a staff member's username is refused). The installer stores no password.
6. **Eye on every password field** — `app/ui/password_eye.py`: an application event filter gives every password-mode QLineEdit an eye when shown; it reveals only typed text (a text the program set = «گذرواژهٔ ذخیره‌شده نمایش داده نمی‌شود» until the field is emptied). The sign-in window keeps its own.
7. **Backup root cause** — the destination `\\192.168.20.150\E` is a share of this PC's whole E: drive; 2.9.2 turned it into `E:\`, and `winservice.local_backup_dir` deliberately refused to grant a drive root, so `NT SERVICE\ShopServer` had no right on `E:\` and `copy_offsite` failed with "PermissionError: Access is denied". Now `localshare.backup_target` always uses the dedicated `ShopServerBackup` sub-folder (also for shares of other computers), the service install creates and grants it, the wizard shows it, grants it before «آزمایش» and tests with the service account. Every failed backup run is reported once to the owners' Bale chat with a Persian reason (`monitor.backup_failure_text`, remembered across restarts).
8. **Look applied live** — 2.9.3 rebuilt the main window (looked like a restart). Now `theme.restyle_live`: the global sheet and palette are set again, every widget's own style sheet is moved from the old palette's colours to the new (`colour_map` / `remap`, white text never touched), icons follow (`theme.set_icon` / `set_nav_icon` keep `icon_spec`), shadows follow «جلوه‌ها» and the mode, and pages reload their data. No window is closed or rebuilt.
9. **Money input + Persian errors** — `widgets.MoneyInput` (grouped Persian digits while typing, «ریال», the amount in words with تومان, the 100-billion limit in Persian) in «تأیید موجودی / ارسال قیمت»; `persian.number_to_words` / `money_in_words`. `app/user_messages.py`: pydantic 422 errors as «<field> …» in Persian, unknown English from the server never shown (`MSG_SERVER_REFUSED`, logged), exception names / English sentences replaced in message boxes, toasts and background-task failures; every `HTTPException` text of shopapi has a Persian translation (test reads the source).
10. **«بستن»** — the default button frame was 1.3–1.9:1 against the dialog; new token `BUTTON_BORDER` (≥ 3.4:1 light, 3.5:1 dark, every palette), weight 600; `button_audit.py` now measures frame / fill against the surrounding pixels (≥ 3:1, WCAG 1.4.11) and reports «looks faint».
11. **Cleanup tool** — «تنظیمات سرور» › «ابزارها» › «پاک‌سازی داده‌های آزمایشی…»: counts, «گرفتن پشتیبان» (`--backup-now`, verified), typed «پاک‌سازی», summary. `shopapi/app/cleanup.py` + `GET/POST /admin/server/cleanup-test-data` (service key; refuses without a verified backup ≤ 30 min old): orders, items, payments, requests and messages, inquiries, customers, events, activity log, idempotency keys, non-owner staff; bot conversations / carts / notices / watches / receipts; receipt files. Kept: owners, settings, groups, price lists and mappings, site models, proxies, Telegram session, audit log. Never opens the accounting database.
12. **Status-code helper** — `AccountingReader.order_status_overview` (two SELECTs on `KalaOrder` / `KalaOrderDetail`: Status × count × made by «سازه حساب» / internet, and the latest orders «سازه حساب» made; no person or description), `GET /admin/server/order-status-codes` (service key or a manager), `StatusCodesDialog` in «ابزارها» and in «سرور فروشگاه». Writes nothing.
13. **Production guide** — `E:\Outputs\ShopSystem\PRODUCTION_GUIDE_FA.txt`.

Tests: shopapi 544, shopbots 287, shoptg 81, shopsystem 67, shopadmin 673 ✓; text-fit / RTL / button audits 0 in all 9 looks, contrast_audit 448/448 AA. The full ShopAdmin suite "hung" (minutes per look change): the old «جلوه‌ها» filter stayed on while every widget was re-polished, and closed main windows kept their application-wide activity filter — both fixed (also faster look changes in the program); an orphaned pytest from the 2.9.3 build had been spinning a CPU core since 2026-10-25 and was stopped. **Not verified on the installed build, a real SQL Server sign-in as the service, the real move from ProgramData, or a real backup to `E:\ShopServerBackup`.**

## v2.9.3 — quality gates (text fit / RTL / buttons), DB access from the setup, cancel reaches the customer, price message with staff's words, proxy pool of 10, look on a click, site models from the live site (2026-10-25, same branch) — DONE in code; the new build NOT installed

Owner's list after installing and testing 2.9.2 on this PC. Decisions in `REQUIREMENTS.md` §7f.

1. **Quality gates** — `shopadmin/scripts/audit_screens.py` lists every screen once (every page for «مدیر» and «کاربر فروش» at 1360 and 1000 px, 33 dialogs filled with long / mixed Persian-Latin data, sign-in, the first-run wizard, every step of the server setup); `text_fit_audit.py` now walks it too and also fails a dialog that is wider than its window; new `rtl_audit.py` and `button_audit.py`; `render_dialogs.py` writes a screenshot of each. Probes on this PC showed that QLabel / QLineEdit / QPlainTextEdit choose their direction from the first strong letter (so «ahmad سفارش را لغو کرد» came out left-to-right) and that an empty QPlainTextEdit starts left-to-right («پیام به مشتری»); table and list cells are always right-to-left. Fixes: `rtl.install_rtl_defaults` (every multi-line box gets a right-to-left document on first show unless `mark_ltr`), `widgets.BidiLabel` (`fix_mixed`: an RLM before a Latin-first Persian line), `mark_ltr` on every deliberate code field (the audit fails an unmarked left-to-right field and a code field that is right-to-left).
2. **Buttons** — one height for every variant (same padding, 1 px frame + 2 px bottom edge, `BUTTON_CONTENT_HEIGHT`), «big» = wider and bolder, never taller; disabled = flat, dashed edge, grey text, no shadow (the shadow effect follows `EnabledChange`); «Ghost» only for an icon; the filter chips («Tab») have a frame; `widgets.footer()` (prominent, others, gap, «بستن» last) used by the order, request, cancel, stock, price-row, proxy, model and text dialogs.
3. **«دادن دسترسی به این دیتابیس»** — `shopapi/app/grant_access.py` (the SQL of `sql/grant_shop_app.sql` embedded; a test keeps them equal), `ShopSystem.exe --grant-db` (current Windows account, `master`, login + user + role; a db_owner login is reported, not an error), `server_setup.grant_database_access`, the button in the wizard after a `DatabaseAccessError`. **Not run on a real SQL Server yet.**
4. **Price message** — `StockConfirmIn.note` / `item_request_messages.note`; the bot: «قیمت امروز این کالا: X ریال», `PURCHASE_OFFER_QTY` only for qty > 1, `PURCHASE_OFFER_NOTE`; the request dialog shows the note in the confirm step, clears the box after sending, and asks before closing with unsent / unsaved text.
5. **Order dialog** — «کارهای انجام‌شده» = `widgets.TimelineView` (one line per action with its time, wrapped, scrolls down only); the item table wraps the full name (`widgets.wrap_rows`); values wrap; the footer is the last row (it was above the error labels, so it never wrapped and widened the dialog to a side scroll bar).
6. **Cancel** — `CancelOrderDialog` (optional reason, 200 chars) → `POST /admin/orders/{id}/cancel {"reason"}` → `orders.cancel_note`; the bot handles `order_cancelled_by_staff` (message + reason), edits its remembered messages of the order (`ordermsgs:<id>`) without a keyboard, answers an old `ocx` / `rcpt` with «لغو شده است» and clears the receipt step (also for `order_auto_cancelled`). Status text «لغوشده» in ShopAdmin and the bot.
7. **Message history** wraps (`wrap_rows`, status column 140 px).
8. **Proxy pool** — shoptg `TG_PROXY_POOL_SIZE` default 10, a slow proxy (> 5000 ms) does not count as healthy; shopapi ranks working → fast → tier → stability → latency, retires dead collected proxies at once (not during our own outage), never a manual one; ShopAdmin shows the full address (wrapped), «سالم ولی کند», «دستی (هرگز خودکار حذف نمی‌شود)», up to 30 rows.
9. **Look** — `AppearancePicker(context=…)`: a click saves and applies (`apply_look_now`); «اعلان‌ها و ظاهر» has no parent (survives the main-window rebuild) and saves the sound / Windows switches at once.
10. **Site models** — `shopapi/app/site_catalog.py` (read, parse, import with `source` / `kind`, `auto_map`, suggestions, monthly loop + re-map after a new price list), `POST /admin/catalog-models/read-site`, `…/{id}/suggestion/accept|dismiss`, event `site_models_new`; ShopAdmin «خواندن از سایت اکنون», filter «پیشنهاد خودکار», «پذیرش پیشنهاد خودکار» / «رد پیشنهاد», last-read line. Checked offline against the live site (66 models, all phones) and `samples/price_list.pdf`: 16 site models have rows in that list, every one matched correctly (no Air → MacBook, A16 → iPad, S25 → S25 FE, Redmi 15 → Note 15); the other 50 are not in that list. How many reach a «سازه حساب» product depends on the price-list mappings on the server (not readable here).

Tests: shopapi 525, shopbots 287, shoptg 81, shopsystem 59, shopadmin 648 ✓ (in `build_all.bat`); text-fit, RTL and button audits 0 in all 9 looks. Build: commit `df9da09`, ShopServerSetup / ShopAdminSetup 2.9.3. **Not verified on the installed build** (not installed by request).

## v2.9.2 — proxy collection that really runs, price guard never sells the old price, «درخواست خرید - استعلام قیمت» with the customer's confirmation, backup share → local folder (2026-10-25, same branch) — DONE in code; the new build NOT installed

Owner's list after installing 2.9.1 on this PC (login and automatic list import OK). Decisions in `REQUIREMENTS.md` §7e.

1. **Proxy collection «never runs»** — real cause from `C:\ProgramData\ShopServer\shoptg.log`: until 2026-10-25 12:58 the service still ran the **2.9.0** reader (the installed exe keeps its build date, 10-23); every hourly collection read @ProxyMTProto with the account and logged `0 links (account)` — the 2.9.0 parser did not know the channel's formats (fixed in 2.9.1 `proxylinks.py`). After 2.9.1 started at 12:58 the next collection waited for the hour after the previous (2.9.0) run (12:07 → due 13:07, checked every 30 min → 13:28), and «سرور فروشگاه» showed «هنوز انجام نشده» because the last collection lived only in the reader's memory (lost at every restart). Live result of 2.9.1 at 13:28: **54 links, 9 tested, 4 working added**; 13:59 «probed 6 proxies: 6 ok». Fixes: the last collection is stored (`tg_collect_info`) and shown after a restart; after a start a short pool is collected at once (if the previous run is ≥ 10 min old); «جمع‌آوری اکنون» (`POST /admin/proxies/collect` → `tg_collect_request`, the reader looks every 20 s; «در صف» shown).
2. **«۳ پراکسی سالم» but «هنوز پراکسی‌ای در استخر نیست»**: `set_busy(False)` showed the table's empty overlay before the rows were inserted and nothing hid it (`server.py` was the only page without `_refresh_states()`).
3. **Price guard**: a held row (`pending_price_rial`) has no price for customers anywhere (`repo.variants`, `purchase.active_rows`, phone search, `/orders` → 422 `price waits for approval; purchase request`); the bot shows «قیمت … در حال بررسی است» + «درخواست خرید - استعلام قیمت». Approve = sold at the new price at once.
4. **Offer flow**: `POST /admin/item-requests/{id}/offer` (also `confirm-stock`) = list price or typed price → request `outcome=offered`, a message with `purpose=offer` (history) delivered by the bot with «✅ تأیید و خرید» / «✖ نمی‌خواهم» (`pok:` / `pno:` + staff message id; another chat or a replaced offer is refused). `POST …/customer-answer` (service key only): accept → order at the offered price (`order_created`, `purchase_order_created`, sales windows), decline → closed (`purchase_offer_declined` notice). Timeline: «قیمت را برای تأیید مشتری فرستاد» → «مشتری «تأیید و خرید» زد». Works for purchase, inquiry and unavailable requests. One bot button «🛍 درخواست خرید - استعلام قیمت» (new keys, so an old operator copy of `messages.fa.json` cannot keep the old labels).
5. **Backup share on this computer**: `localshare.py` (shopsystem + shopadmin): `\\THIS-PC\Share\sub` → the share's folder from `LanmanServer\Shares` (or `D$` → `D:\`); the wizard replaces it (with a note) on edit / «آزمایش» / save; the service converts again (backup + ACL grant). Checked on this PC: `\\<PC>\work\sub` → `G:\Work\sub`.

Tests: shopapi 498, shopbots 284, shoptg 78, shopsystem 57, shopadmin 625 ✓. **Not verified on the installed build** (not installed by request): the offer buttons in real Bale, «جمع‌آوری اکنون», the backup share conversion in the real wizard.

## v2.9.1 — price-channel corrections / «فروش بسته», price guard, every proxy format, channel roles, saved password, live look, off-server backup (2026-10-23, same branch) — DONE in code; installed build UNVERIFIED

Owner's list after testing 2.9.0 on this PC (reader connected, Abrishami PDF imported). Decisions in `REQUIREMENTS.md` §7d.

1. **Proxy collection found «0 links»**: @ProxyMTProto (checked 2026-10-23) posts «Server / Port / Secret» text with «Connect» buttons `t.me/proxy?…` and `t.me/webproxy?server=…&secret=…` (no port = 443), hosts sometimes ending with a dot, base64url secrets. New `shoptg/app/proxylinks.py` reads text, entities and buttons in every format and sends canonical `tg://proxy` links (live page: 42 links, the old parser 27). The account path always reads the newest 100 posts (was: only after a cursor); when it finds nothing the web preview is tried; a filter page answering 200 is reported (`not the channel's preview page`); the reason is shown on «سرور فروشگاه» (`collect.error`). shopapi's own parser (manual entry) accepts the same forms. The worker's log file was empty inside ShopSystem.exe (`basicConfig` without `force`) – fixed.
2. **Proxy table** («سرور فروشگاه»): columns fit their content (`fit_width`, «منبع» stretches); `QAbstractScrollArea::corner` is transparent (the white box).
3. **Auto refresh**: price / sales events mark «لیست قیمت» and the dashboard stale (reload when shown, also after the tray); a refresh postponed while typing is retried every 4 s (was: waited for «به‌روزرسانی»). Sales already open by themselves inside the window (server side).
4. **Price channel**: read at least every 20 min during 07:00–21:00 Tehran (default 10). Placed orders keep their price; at checkout the bot asks shopapi (`?check=true`) and, when a cart price changed, updates the cart and asks the customer to confirm again (no order placed).
5. **Corrections «اصلاحیه»** (`shopapi/app/pricelist/notes.py`): text posts after the newest list go to `POST /worker/pricelist-notes`; lines «model storage-RAM [note] cash-price» apply to every color / type of the model in the active list (A07 vs «A07 (Full)» chosen by the note; «Note 15 Pro» matches «Redmi Note 15 Pro» when unique); the row keeps the PDF values in `orig_*` and is flagged `correction` until the next list; unmatched lines → `price_correction_unmatched` (ShopAdmin + Bale).
6. **«فروش بسته»** (many wordings): phone sales close at once (`close` override by `channel`, reason `channel_close`) until the next list; `sales_closed_channel` alert.
7. **Edited / deleted posts**: every poll looks at the newest 30 posts; the newest list post is sent again when its version (id, edit time, size) changes; posted time = edit time; a deleted newest post brings back the previous list (`latest=true` re-activates a known telegram list, never over a manual upload).
8. **روال for corrections**: `price_raval_diffs` learns each model's «روال − نقد» (median over colors) from every list; without history the median of the same brand at ±25 % price («روال تخمینی»), then the brand, then the whole list.
9. **ShopAdmin login**: with «مرا به خاطر بسپار» the last user's password is kept with Windows DPAPI (`remembered.pw`, this Windows user only; nothing without DPAPI); «خروج» forgets only the session token, so «ورود» is enough; the eye shows a typed password only (disabled for the saved one); a wrong saved password is forgotten; unticking forgets everything.
10. **Look applied at once**: «ذخیره» re-applies the theme and rebuilds the main window on the same page (no restart).
11. **Channel roles**: the reader reports joined channels every 6 h (`iter_dialogs`, read only) → `tgchannels.py` (state `tg_channels`); roles pricelist / proxy / accessories / used / ignore in «تنظیمات سرور › تلگرام» (service key on the server); configured channels get their role when first seen; a channel joined later → `telegram_channel_new` (ShopAdmin). Only pricelist and proxy act today.
12. **Price guard** (`PRICE_GUARD_PCT` 10): a mapped row whose price (new list or correction) moves more than 10 % keeps its previous price; the new one is `pending_*` («قیمت منتظر تأیید» filter, «تأیید / رد قیمت تازه»), `price_held` alert. The whole list is held only when most mapped rows are missing (layout change).
13. **Bale admin chat = problems only**: new orders / receipts / customers / price inquiries only with `ADMIN_CHAT_ORDER_NOTICES=true` (default off); new: suspicious price, unmatched correction, sales closed by the channel.
14. **Off-server backup**: «تنظیمات سرور › شبکه و پشتیبان»: folder (`BACKUP_COPY_DIR`, share allowed), passphrase (`BACKUP_PASSPHRASE`, ≥ 20, «ساخت عبارت تازه»), copies kept (`BACKUP_KEEP_DAYS`, 14), «آزمایش» = write / read / delete with the admin's account AND with the service account (`POST /admin/server/backup-test`).

Tests (Windows, fakes): shopapi **492**, shopbots **279**, shoptg **75**, shopsystem **55**, shopadmin **619** — all passing. Not tried on the installed server, real channels or a real share.

## v2.9.0 — new look (3 palettes × light/dark/system × effects), payment-form cursor, automatic Telegram reader + proxy pool (2026-10-21, same branch) — DONE in code; installed build UNVERIFIED

Owner's request after approving 2.8.3 on this PC. Decisions in `REQUIREMENTS.md` §7c.

1. **ShopAdmin look** (`app/ui/theme.py`, `app/ui/appearance.py`): the best of Phone Bridge (`E:\Soft\phonebridge\app\theme.py`: ocean / emerald, raised buttons, soft animated shadows, «جلوه‌ها» full / simple with the weak-PC / Remote Desktop rule) and the equipment control panel (`E:\AsrNetworkProject\mikrotik_panel_v36`: the indigo → cyan «aurora» accent, the colour glow behind the window, option cards to choose the look, gradient stat icons). Tokens = neutral base per mode + accent family per palette (`palette_tokens`); `PRIMARY_TEXT` = the accent used as text (dark mode had blue-on-dark hover / tab text); `SUCCESS_FILL` / `DANGER_FILL` = white-text button fills apart from the same colours used as text (dark: green / red text was unreadable). Full effects: radial glow window background, gradients, `QGraphicsDropShadowEffect` under panels WITHOUT tables / lists / text boxes (event filter on Polish; the old backlog item «سایه روی Panelهای بدون جدول») and under Primary / Success / Danger buttons outside item views, growing on hover, shrinking on press. Simple: flat fills, no shadows (also removed from existing widgets). Radii 14 / 20 (size unchanged → text fit unchanged). «اعلان‌ها و ظاهر» (every user) and «تنظیمات برنامه»: three rows of option cards (palette swatch = side-bar gradient + accent dot); stored per computer (`theme_palette`, `theme_mode`, `theme_effects`), applied at start; after a change «باز کردن دوباره» restarts the program (the single-instance listener is closed first). `StatCard` defaults read at run time (were captured at import → always ocean). `contrast_audit.py --all`: 462/462 pairs AA in every palette × mode (+ rendered windows); `text_fit_audit.py`: 9 looks (palette × light / dark / system, effects alternating) + the new dialogs, 0 cut texts.
2. **Payment form cursor**: `widgets.MaskedLineEdit` for card / account / Sheba: a click among the mask's blanks or Tab puts the cursor on the first empty place (card after the typed digits and the dash, Sheba right after «IR»); a click inside what is typed keeps its place (to correct a digit); no mask (account) = end of the text.
3. **Telegram reader, automatic** (`shoptg` bundled in ShopSystem as `shoptg_app`; `ShopSystem.exe --tg-worker` started by the service when `TG_READER_ENABLED=true`; `SHOPTG_DIR` still works): `TG_API_PRESET=tdesktop` (default when no own api_id) = the public Telegram Desktop api_id/api_hash with its InitConnection parameters (device_model / system_version / app_version / lang_code / system_lang_code and `lang_pack="tdesktop"` set on Telethon's `_init_request`; overrides `TG_DEVICE_MODEL` …); «کلید خودم» = `TG_API_ID/HASH`. «تنظیمات سرور» has a new step «تلگرام»: on/off, channel, key (with the risk warning), manual first proxy (`TG_PROXY`, hidden), and «ورود به حساب تلگرام…» (`ui/telegram_login.py`, server-only module): phone → code → 2FA via `ShopSystem.exe --tg-login` (`shoptg/app/login_flow.py`, JSON lines; the key chosen in the form is used before it is saved; tries the typed proxy, `TG_PROXY`, the pool, direct). Session: DPAPI LocalMachine + ACL (service read when the service exists; `--install-service` grants it otherwise). Worker log in `<data>\shoptg.log` (the session folder is read-only for the service). New PDF → `/worker/pricelists` (same import as manual: morning / afternoon rules) → `pricelist_imported` (actor `worker`) → ShopAdmin «لیست قیمت تازه»; download failing 3 times / too large / not a PDF → `telegram_pricelist_error` (ShopAdmin + Bale admin chats, manager / «سرور» only). FloodWait pauses every job. The supervisor re-reads `.env` at every child start (`ChildSpec.env_factory`).
4. **Proxy pool**: default proxy channel `@ProxyMTProto`, collected daily (`TG_PROXY_COLLECT_HOURS`=24) and hourly while fewer than `TG_PROXY_POOL_SIZE` (5) work; with the account when connected, else from the web preview `https://t.me/s/<channel>` (first start without login / proxy). `POST /worker/proxies/unknown` → only never-seen links are tested (anonymous client, ≤ `TG_PROXY_TEST_MAX` 40, until pool_size + 2 work); `POST /worker/proxies/candidates` gets `tested` (added on probation with the latency recorded) and `failed` (stored retired, never retested); `ACTIVE_CAP` 30. Existing ranking / promotion / immediate failover unchanged. «سرور فروشگاه»: new panel «خوانندهٔ تلگرام و استخر پراکسی» (reader state + key kind, last check / last file of the channel, pool «N سالم از 5», last collection, table of the usable proxies with masked secrets, «افزودن پراکسی دستی…»). `/admin/server/status` gains `proxy_pool` (counts only) and the reader's `price` / `collect` summary (whitelisted keys, no secrets).

Tests (Windows, fakes): shopapi **464**, shopbots **276**, shoptg **72**, shopsystem **55**, shopadmin **608** — all passing; `text_fit_audit.py` 0 in 9 looks; `contrast_audit.py --all` 462/462. Not tried on a real Telegram account, real proxies or an installed server.

## v2.8.3 — own work only, payment-info reminders, «مرحلهٔ قبل», simpler permissions (2026-10-21, same branch) — DONE in code; installed build UNVERIFIED

Findings from the 2.8.2 test install on the owner's PC.

1. **«گزارش فعالیت»**: a user who is not a manager gets only their OWN actions (`list_activity(own_only=True)`: `staff_id = me`, not what a colleague handed to them) whatever `staff_id` asks; ShopAdmin hides the «کاربر» filter and never loads the staff list for them.
2. **Ownerless finished work**: a sales user sees an ownerless order only while it is OPEN (`awaiting_payment` / `receipt_uploaded`, not sent, not archived); accepted / written / cancelled ones without an owner (e.g. old «ثبت‌شده در حسابداری», or approved in the Bale admin chat) are the manager's only (he can refer them). Same rule in `ownership.visible`, `query_orders` and `customer_ids_for_staff`. The dashboard's 7-day chart of a non-manager counts only `owned_by_me`.
3. **No colleague names**: `/admin/shop/state` (and the «فروش گوشی» buttons) return `override_by` = «شما» for the user's own change and "" for a colleague's (manager: unchanged). Other names were already manager-only (owner, timeline, handled_by, note_by, message created_by).
4. **Dashboard table**: `DataTable(fit_width=True)`: content-sized columns (never narrower than the header or a pill: `sizeHintForColumn`), «مشتری» stretches; no horizontal scroll bar at normal widths (only if the window is narrower than the content itself). The products card is shown only with «محصولات — دیدن» (the dashboard no longer opens `/products` / product groups).
5. **Payment-info reminder**: `GET /admin/orders/payment-info-due` = orders `awaiting_payment` without payment details that THIS user must handle (own, or nobody's yet; the manager too; never a colleague's). ShopAdmin `PaymentInfoReminder` polls it every 30 s and `TrayNotifier.remind_payment_info` shows a small closable balloon (6 s, no window, no focus) + the short Windows sound — independent of the user's notification switches; it stops when the details are sent or the order is cancelled. Orders page: the row is highlighted (`needs_payment_info`) and counted above the list. No auto-cancel (the receipt deadline still starts only with the details). Bot: «لغو سفارش» was already offered in this state (checkout message + «سفارش‌های من»); test added.
6. **Bot «مرحلهٔ قبل»**: every customer screen records itself (`screen=(id, redraw)` in `_send_options`) on a per-chat stack in the bot's kv store (`nav:<platform>:<chat>`, max 15, with the conversation data of that screen); «↩ مرحلهٔ قبل» goes next to «منوی اصلی» on every screen that has it (the main menu resets the stack, `/start` clears it). Going back restores that screen's data and redraws it (callback or internal `@q` / `@stmt` / `@model` / `@ireqtext`), so the quantity, color, part, search results and typed request text are kept. Paths: groups → list → product/colors → part → price → cart, phone search (models → colors → parts → row → purchase request), item request, orders, statement, site models, support/info. One-off answers («ثبت شد») are skipped when going back.
7. **Nightly archive**: `archive.run_nightly_due` at 23:59 Tehran (missed runs catch up): ownerless orders cancelled by the customer (`cancel_reason='customer'`), lapsed (`receipt_timeout`) or `expired`, and ownerless requests of such orders → `archived_at` (nothing deleted; manager sees them in «بایگانی»). The weekly Thursday archive is unchanged.
8. **Payment form**: card with the fixed mask `9999-9999-9999-9999` (digits only, groups fill by themselves, exactly 16), Sheba with a fixed «IR» and 24 digits (`IR999…;_`); «مثل دفعهٔ قبل» fills both. Bot: card / account / Sheba are wrapped in LEFT-TO-RIGHT MARKs around every separator (`engine.ltr`) so the client can never flip the groups (they arrived reversed).
9. **Permission table**: always on for every staff member and removed from the table: dashboard, orders & receipts, item requests, customers (approve / reject), referral, archive, reports (`staff.ALWAYS_SECTIONS` / `ALWAYS_PERMISSIONS`, added after revokes in `effective_permissions`). The table keeps products, groups, price list (+ mapping / proxy), site models, phone sales, activity, password requests, staff, server settings. Start-up migration strips the old ticks of those sections (`strip_always`); `_ticks` never stores them. Visibility of own work is unchanged.
10. **Referral**: the manager can already hand any unfinished order / request over; new `POST /admin/staff/{id}/transfer-open` (manager) moves every open order / request of user X to Y (each logged as `assign` with `from=<id> bulk` on its history and in «گزارش فعالیت»; the manager's timeline shows «کار X را به Y ارجاع داد» via `from_name`). ShopAdmin «کاربران سیستم» › «بیشتر» › «انتقال همهٔ کارهای باز به همکار دیگر».
11. **«وقتی فروش باز شد خبرم کن»** (report only, unchanged): the button exists only while phone sales are CLOSED: (a) on a phone's color list (`_show_colors`, under the colors), (b) in the cart when it holds a phone (instead of «ثبت نهایی»), (c) when «ثبت نهایی» is pressed with a phone in the cart. Not for an out-of-stock phone (that gets «درخواست خرید»), not in the phone-search results (they show «فروش بسته است» + «درخواست خرید»), never while sales are open.

Tests (Windows, fakes): shopapi **458**, shopbots **274**, shoptg **49**, shopsystem **50**, shopadmin **583** — all passing.

## v2.8.2 — per-section permissions, payment details per order, no reload under the user's hands (2026-10-20, same branch) — DONE in code; installed build UNVERIFIED

Findings from the 2.8.1 test install.

1. **Auto refresh**: `BasePage.configure_auto_refresh` ran the timer on EVERY page (also «سرور فروشگاه» / settings), and every server event called `page.refresh()`. Now only list pages poll; `soft_refresh()` waits while a dialog is open, the cursor is in a field of the page, or `has_unsaved_changes()` (server settings form); form pages (`auto_refreshable = refresh_on_server_events = False`) never reload by themselves.
2. **Payment details per order**: `BANK_ACCOUNT_TEXT / PAYMENT_CARD_NUMBER / PAYMENT_SHEBA / PAYMENT_OWNER` are gone from the editable settings and the wizard (ignored if still in `.env`). New `POST /admin/orders/{id}/payment-info` (card / account / Sheba / holder / bank / note; normalised, only filled ones kept; `orders.payment_info`, `payment_info_at`; activity `payment_info`; event `order_payment_info`). The receipt deadline (`reserve_until`) starts then — an order without payment details never times out. ShopAdmin: «ارسال اطلاعات پرداخت» in the order dialog (form like the courier form, «مثل دفعهٔ قبل», preview + confirmation); opens by itself after «تأیید موجودی». Bot: checkout says the details follow (`WAIT_PAYMENT_INFO`); the event sends them (empty fields left out) and starts waiting for the receipt. `payment_ready` is always true.
3. **Two settings pages**: «تنظیمات برنامه» (this computer, every user: intervals, notifications, look, log; the server address needs «تنظیمات سرور فروشگاه — تغییر») and «تنظیمات سرور فروشگاه» (the old «سرور فروشگاه»; «دیدن» = read only, «تغییر» = save / restart / «تنظیمات سرور»).
4. **✕ of the dialogs**: 2.8.1 added the maximise hint to the dialog's default flags and Windows greyed out SC_CLOSE (checked with `GetMenuState`). `widgets.DIALOG_FLAGS` = Dialog | CustomizeWindowHint | title | system menu | maximise | close.
5. **Bot ↔ ShopAdmin delay** — cause: the bot read ShopAdmin's events (payment details, approvals, replies) only inside the 30-second admin sweep, and ShopAdmin polled the event feed every 15 s (+ the 30 s list refresh). Fix: the bot has its own events loop (`EVENTS_POLL_SECONDS`, default 2; one reader at a time via a lock), ShopAdmin polls events every 3 s (an unchanged old default 15 is moved once). Customer → ShopAdmin was already immediate on the server; the 15 s poll was the wait.
6. **Cut text**: `StatusPill` measures bold text + padding with the font it really draws with (Qt's hint left the style-sheet padding out: «کاربر فروش», «گذرواژهٔ موقت», «ثبت‌شده در حسابداری»); «کاربران سیستم» rows: «ویرایش» + «بیشتر» menu (`widgets.actions_menu_button`). `scripts/text_fit_audit.py` renders every page (manager and sales user, 1360 and 1000 px) and the main dialogs and lists every label / button / check box / badge / header narrower than its text: 0 left.
7. **Bot stock**: `POST /orders?check=true` runs every checkout rule without creating an order. The bot asks it when a phone color / part is picked (cart quantity included) and again before adding — no stock → «🛍 درخواست خرید» instead of «افزودن»; a phone that runs out before checkout gets a one-tap «🛍 ثبت درخواست خرید» (the item leaves the cart). Search path unchanged.
8. **Ownership**: «برمی‌دارم» and the `/claim` endpoints are gone; the first action (payment details, receipt decision, ship, cancel, request note / message / status / stock) takes a free row, also for the manager. The losing user gets «همکار دیگری زودتر … برداشت».
9. **Visibility (server)**: a sales user sees their own orders / requests and free rows that still need work (orders awaiting payment / with a receipt / paid and not sent; open requests), customers of those rows plus new (pending) customers, and only events about what they may see. The manager sees everything.
10. **Permissions per section** (`staff.SECTIONS`, `/admin/permission-sections`): `<section>.view` / `.edit` for dashboard, orders, requests, customers, assign (edit only), archive, products, groups, pricelist (+ proxies), models, sales, reports, activity, passwords, staff, server; «تغییر» implies «دیدن»; every endpoint checks them. Old per-user ticks are migrated on start (the user's old effective rights → sections; e.g. any of «تأیید رسید / ارسال / لغو» → «سفارش‌ها — تغییر»). ShopAdmin «کاربران سیستم»: a table (بخش | دیدن | تغییر) + «برگرداندن به دسترسی‌های نقش».
11. CLAUDE.md: never `git push` unless asked; release = local commit.

Tests (Windows, fakes): shopapi **449**, shopbots **268**, shoptg **49**, shopsystem **50**, shopadmin **572** — all passing.

## v2.8.1 — «تنظیمات سرور», real writing per database, fit-to-screen dialogs (2026-10-20, same branch) — DONE in code; installed build UNVERIFIED

Findings from the 2.8.0 test install on the owner's PC.

1. **«تنظیمات سرور»**: `ShopAdmin.exe --server-settings` (UAC) opens the server setup wizard in settings mode (`ServerSetupWizard(mode="settings")`): filled from `%ProgramData%\ShopServer\.env` (`server_setup.read_current_config()`: values, but for secrets only *whether* they are set), no «مدیر کل» step; an empty secret / SQL password keeps the saved one (`write_config`: `None` = keep, `""` = clear). Save = harden folder → `--init-config` → `--install-service` (update) → firewall → `restart_service()` (stop + start) → wait for HTTPS. The ShopServer package's desktop shortcut is now «تنظیمات سرور» (old «مدیریت فروشگاه» on the all-users desktop is removed by `[InstallDelete]`; the console stays in the Start menu, which also gets «تنظیمات سرور»). ShopAdmin «سرور فروشگاه» shows the button «تنظیمات سرور» for the manager only in the server edition on the server itself (`server_installed_here()`). Setup windows don't take the single-instance lock, so they open beside a running console.
2. **Clear reasons** instead of «قطع — دسترسی ندارد»: `/admin/server/status` and `/admin/system-info` add `write_block_reason` (`not_allowed` / `write_off` / `no_database`), `allowed_databases`, `write_databases`; ShopAdmin shows the SQL reason (`message_fa`, e.g. 4060 + «grant_shop_app.ps1 را برای همین پایگاه‌داده اجرا کنید») and why real writing is off. The wizard's DB test shows the same Persian reason.
3. **Real writing per database, no built-in name**: `ACCOUNTING_TEST_DATABASES` no longer defaults to `hesab5 t` (empty). New `ACCOUNTING_WRITE_DATABASES`: `write_allowed()` = database on `ACCOUNTING_ALLOWED_DATABASES` **and** on the write list (or a listed test copy, or the older switch + host + allowlist rule). Both lists are edited only in the wizard on the server («پایگاه‌داده‌های مجاز و ثبت واقعی»: add / remove, a «ثبت واقعی در حسابداری» tick per database with a danger confirmation, a second confirmation on save) — never remotely (`control.EDITABLE` unchanged for them). New installs: nothing allowed, nothing written. **Upgrade note:** an install that relied on the old built-in `hesab5 t` test mode stops writing until the owner ticks it in «تنظیمات سرور».
4. **Addresses**: `server_setup.usable_lan_address()` drops APIPA 169.254.x.x, loopback, 0.0.0.0, multicast and reserved addresses (network page and the final «اجرا» page).
5. **Side bar**: Qt mirrors stylesheet `text-align` in a right-to-left button exactly like `AlignRight`; `NavButton` (and `LinkButton`) now use `text-align: left`, which is the right edge in RTL (verified by rendering: icon on the right half).
6. **Table headers**: `DataTable` measures every bold header (`header_width`) and never sets a column narrower — from the start (also empty tables) and when restoring widths saved by older versions. Plain tables in dialogs use `widgets.show_full_headers()`.
7. **Filters**: «درخواست کالا» has labelled groups «نمایش: کارهای من / همهٔ درخواست‌ها», «وضعیت: باز / رسیدگی‌شده / همهٔ وضعیت‌ها», «نوع: همهٔ انواع…» in a wrapping row, with the selected button highlighted (`Tab` style). «همه» elsewhere became «همهٔ سفارش‌ها / مشتریان / مدل‌ها / ردیف‌ها».
8. **Dialogs**: every dialog derives from `widgets.ResponsiveDialog` (test enforces it): before it opens, `make_responsive()` moves the content into a scroll area, keeps a last row of buttons visible under it (wrapping on narrow windows), adds maximise + size grip, and `fit_window_to_screen()` caps size / minimum size at 92% of the screen's work area (device-independent pixels, so Windows scaling is included) and centres it. The server wizard scrolls too and shrinks to the current page.
9. **Telegram keys**: `TELEGRAM_BOT_TOKEN`, `TG_API_ID`, `TG_API_HASH` are masked secrets in «سرور فروشگاه» settings (validated) and in the wizard's «ربات‌ها» step; the launcher passes `TG_API_ID/HASH` to shoptg and reports the Telegram bot as configured when all three are set.
10. **Theme**: light / dark (Phone Bridge «ocean» palette only) also in the top-bar «اعلان‌ها و ظاهر» dialog for every user (the «تنظیمات» page is manager-only); applies at the next start.

Tests (Windows, fakes): shopapi **440**, shopbots **263**, shoptg **49**, shopsystem **50**, shopadmin **551** — all passing.

## v2.8.0 — phone search, purchase requests, ownership, activity log, archive (2026-10-19, same branch) — DONE in code; SQL / Bale UNVERIFIED

1. **RTL (ShopAdmin)**: in a right-to-left widget Qt mirrors plain `AlignRight` to the LEFT edge, so table cells, labels and form captions sat on the left. Everything now uses `ui/rtl.py: RIGHT` (`AlignRight | AlignAbsolute`); `DataTable` uses `BidiDelegate`, so Latin-only text (codes, part numbers, paths, URLs) is laid out LTR inside the right-aligned cell (the cell text itself is unchanged).
2. **Smart phone search** (`shopapi/app/phone_search.py`, `GET /phones/search?q=`): what the customer types, in any spelling («آیفون ۱۷ پرو», «17pro», «iphone 17 pro 256», «گلکسی اس ۲۶ الترا») and any word order, is reduced to tokens (`fuzzy.tokens` + `Promax`=`Pro Max`, brand implied by the section, Persian/English digits, `GB`). Every number typed must be in the row; an extra model word (Max for «17 Pro») ranks lower. Rows are grouped by model; each says `order` (mapped + stock in Sazeh) or `purchase`. Bot: typed text (or «🔍 جستجو») → models → colors → parts → «افزودن به سبد» (the usual color screen, price read again) or «🛍 درخواست خرید». Nothing found → the unchanged free-text «درخواست کالای ناموجود».
3. **Mapping by name similarity** (`pricelist/matching.py: name_candidates / confident / name_match`): after the v2.6.2 same-row / same-model steps, still-unmapped rows are mapped to the phone-group product with a clearly matching Sazeh name (score ≥ 0.86 and ≥ 0.08 ahead of the next; every model number and storage size must match; RAM and «Galaxy» ignored), flagged «خودکار» (`auto_reason=name`; confirm / undo as before). Ambiguous rows are never mapped. `GET /admin/price-mappings/suggestions?row_key=` = the 3 closest products (shown in the mapping dialog, the confident one preselected). Runs on manual upload, worker import and «تطبیق خودکار»; accounting DB down = skipped.
4. **«درخواست خرید»**: a phone in the list but not orderable (not mapped, or no stock in Sazeh — new `PHONE_STOCK_REQUIRED=true`; false = the list alone decides) → the bot shows the list price and «🛍 درخواست خرید» (`POST /purchase-requests`, by row or by product + color). It lands in «درخواست کالا» as kind `purchase` with color / part / price. Staff: «تأیید موجودی» (maps the row if needed, optional new price) → a normal order (`awaiting_payment`, receipt deadline, sales windows; refused while phone sales are closed) + event `purchase_order_created` → the bot sends the payment details and waits for the receipt. «ناموجود» → a polite message to the customer. A phone ordered without stock is refused (`Product N has no stock; purchase request`).
5. **Activity log** (`activity_log`, `app/ownership.py`): claim, handover / assign, customer approve / reject, receipt approve / reject, ship, cancel, reply, note, request status, stock confirm / unavailable, weekly archive. `GET /admin/activity` (manager only; staff / customer / date filters) → ShopAdmin «گزارش فعالیت». Order / request dialogs show a Persian timeline («احمد رسید را تأیید کرد ← به علی ارجاع داد ← علی ارسال کرد»); a sales user sees «شما» / «همکار», never a name.
6. **Ownership**: a new order / request is visible to every sales user; the first action takes it (`owner_id`) and it disappears for the others (lists filtered, detail 404, actions 403 — enforced in shopapi). Explicit «برمی‌دارم» (`/claim`). Handover by the manager, a user with the new tick «ارجاع سفارش» (`orders.assign`), or the owner (`/assign`; `GET /admin/assignees` = id + display name only). Every handover is logged and announced (`order_assigned` / `request_assigned`).
7. **Archive** (`app/archive.py`): every Thursday 23:30 Asia/Tehran (checked every 5 minutes; a missed run happens at the next check; once per week via `shop_state.archive_last_run`) finished orders (sent, cancelled, rejected, expired) and finished requests get `archived_at`. ShopAdmin «بایگانی»: a sales user sees only their own rows of the current `DB_NAME`, read-only; the manager everything, every year, with search. Finished / archived rows are read-only for everyone (409); nothing is deleted.
8. **Ease**: lists refresh by themselves (orders, requests, activity); «کارهای من» is the default view of sales users; receipts / new requests waiting more than 10 minutes are highlighted and counted; one-click copy of the customer's mobile (no address is stored in the shop DB); per-user sound / Windows notification («اعلان‌ها» in the top bar); bot «🔔 وقتی فروش باز شد خبرم کن» (one message per opening, then the customer leaves the list).
9. Version 2.8.0.

Tests (Windows, fakes): shopapi **436**, shopbots **263**, shoptg **49**, shopsystem **49**, shopadmin **521** — all passing.

## v2.7.0 — ShopAdmin for non-technical staff (2026-10-18, same branch) — DONE in code; SQL / Bale UNVERIFIED

1. **Shipping**: there was no postal tracking code anywhere in this branch (only the bank receipt's «شمارهٔ پیگیری», which is payment). «ارسال شد» now opens a small dialog with an OPTIONAL courier name + phone (`POST /admin/orders/{id}/ship` body `ShipIn`, `orders.courier_name/courier_phone`, phone digits 7–15, Persian digits accepted). The bot appends «🛵 پیک: … — تلفن: …» to ORDER_SHIPPED only when something was entered.
2. **Look**: the Phone Bridge «ocean» theme (`E:\Soft\phonebridge\app\theme.py`, also PySide6) recreated in `shopadmin/app/ui/theme.py`: gradient window, deep-blue gradient side bar, 18px cards, raised buttons, accent focus rings, light **and dark** palettes (`theme_mode` per computer: روشن / تیره / مطابق ویندوز, from the next start). Bug fixed: `fonts_dir()` looked in `assets/fonts` while the fonts live in `app/assets/fonts`, so Vazirmatn never loaded (Tahoma fallback) — in the exe too.
3. **Cut text**: menu and tab labels were clipped when selected because the bold «checked» state is not measured by Qt; every state now has one weight. Table headers are measured bold; the orders search placeholder is shorter; dialogs use flow layouts.
4. **Roles**: «مدیر» (`super_admin`, everything) and «کاربر فروش» (`operator`, default for new users: orders view / confirm or reject receipt / ship / cancel, item requests, customers view). Old roles migrate on start (admin → مدیر, viewer → کاربر فروش). Server permissions split (`orders.view`, `orders.cancel`, `requests.handle`, `customers.view`, `events.view`; `view` = the rest, admin-only); per-user ticks `staff_users.perm_grant/perm_revoke` (`extra_permissions` / `removed_permissions`, `GET /admin/permissions`), sessions end when ticks change. ShopAdmin gets the effective list at sign-in and hides menu items/buttons without permission; the API enforces the same (incl. `/products`, `/groups` for staff). New `POST /admin/orders/{id}/cancel` (awaiting payment / receipt sent; local only; warning event if already in Sazeh).
5. **Simplicity**: sales users land on «سفارش‌ها»; big action buttons (تأیید رسید / رد رسید / ارسال شد / لغو سفارش) with confirmations; a one-line help at the top of every page; friendly empty states («سفارش جدیدی نیست»); plain errors with the next step; «گذرواژهٔ من» in the top bar; no server address / «سرور» / «API» / price level / database name for sales users; «فیش» → «رسید»; menu badges also count customer cancels.
6. Screenshots (before/after, manager and sales user, light and dark): `E:\Outputs\ShopSystem\screenshots_2.7.0\` (`shopadmin/scripts/review_screens.py <dir> <prefix> [dark]`).

Tests (Windows, fakes): shopapi **403**, shopbots **256**, shoptg **49**, shopsystem **49**, shopadmin **501** — all passing.

## v2.6.2 — price-list mapping, phone parts, customer cancel (2026-10-15, same branch) — DONE in code; SQL / Bale UNVERIFIED

1. **PDF drag & drop** on «لیست قیمت» (`dragEnterEvent/dropEvent`, same `upload_pdf_file` path as the button; managers only). The row actions use a flow layout.
2. **Permanent + smart mapping** (`shopapi/app/pricelist/matching.py`): a decided row key is never asked again; on every import (and after each staff decision) undecided rows are matched by *smart key* (brand + model words + type + color; case/spacing/word order, `256GB`=`256`, `R8`=`Ram8`) or, for a new color / part (`ZAA`, `CHA` …) / type of a model whose decided rows all point to one product, mapped to that product. Flagged `price_mappings.auto` (+ `auto_reason`), filter «خودکار (بازبینی)», confirm (`POST /admin/price-mappings/{id}/confirm`), undo (= delete → `price_auto_rejects`, never auto-matched again), run now (`POST /admin/price-mappings/auto`). `safety_reasons` also finds respelled rows by smart key. A model split over several products is never guessed.
3. **Color, then part**: variants carry `part` (Apple part code from the description, else the type when a product has several types). The bot shows one button per color, then the parts with a price in the current list (each with its own price). `order_items.color/part`; the line name/variant = «color — part»; the Sazeh line description `KalaOrderDetail.sharh` gets it (cut to the column size read from `INFORMATION_SCHEMA`; unknown size → left empty).
4. **Customer cancel**: «❌ لغو سفارش» in the order message and «سفارش‌های من» → confirmation → `POST /orders/{id}/cancel` (bot key, owner only, only `awaiting_payment` without a receipt; local only, `cancel_reason=customer`). Already written to Sazeh → cancelled here too, Sazeh untouched, ShopAdmin warning `order_cancel_written`. ShopAdmin notice `order_cancelled_by_customer`; orders show who cancelled.
5. **build_all.bat**: pytest runs with `TEMP/TMP` set to a fresh `%TEMP%\ShopBuild\tmp_<stamp>_<rand>` (fallback `.buildtmp\`), `-p no:cacheprovider`.
6. `CLAUDE.md`: Outputs keeps only the newest installer pair; README_FA.txt updated every release.

Tests (Windows, fakes): shopapi **393**, shopbots **251**, shoptg **49**, shopsystem **49**, shopadmin **484** — all passing.

## v2.6.1 — owner follow-ups (2026-10-15, same branch `feature/order-flow-v250`) — DONE in code; Windows build only, SQL / Bale UNVERIFIED

1. **Shop phone**: `shop_phone` empty (or the old placeholder «شماره تلفن فروشگاه») → every line holding `{shop_phone}` is dropped from the bot texts (`texts.drop_phone_lines`); the shipped default is now empty; invoice cards skip it.
2. **Item requests only in ShopAdmin**: the `item_request` admin-chat notice of the bot is removed (`OWNER_EVENT_TEXTS`, `ITEM_REQUEST_NOTICE`).
3. **Stale carts**: `POST /orders` checks every item before anything else: hidden group → `Product N is not available for sale`, «price on inquiry» → `Product N is price on inquiry`, phone not in the current valid list (sales open) → `Product N is not in the current price list` (422). The bot names the item and offers the cart (`CART_ITEM_*`).
4. **Group tree**: `Gkala.g_kala` = parent (`list_groups` returns `parent`); every flag (show in bot / phone / inquiry) is inherited by subgroups in all backend checks (`groups.GroupConfig.chain`); a group lists its subgroups' items; reader errors → 503 (never "no inheritance"). ShopAdmin «گروه‌های کالا» is a `QTreeWidget`: a ticked parent shows its ticks on the children (greyed); only own ticks are saved. `GET /admin/product-groups` adds `parent` + `effective_*`.
5. **Dashboard**: prominent warning (`phone_groups_ready` in `/shop/state`) when no group is a phone group.
6. **«قیمت با استعلام»** (`product_groups.price_on_inquiry`, inherited): customers get the item with `priced_by="inquiry"`, `unit_price=0`, no stock filter; the bot shows no price and no add-to-cart, only «📨 استعلام قیمت» → `POST /item-requests` with `kind="inquiry"` (no payment, nothing to Sazeh).
7. **«درخواست کالا» page**: type column + filter, new width key and `DataTable(keep_columns=…)` for the date; a stretching last column no longer counts as a user drag (that froze default widths — the truncation bug). Row click → dialog: full text, time to the second, customer name/code/mobile/messenger, status, staff note (`PUT …/note`), «دیده شد» / «رسیدگی شد» / «باز کردن دوباره», and «ارسال پیام به مشتری»: `POST /admin/item-requests/{id}/messages` (staff only) stores a `pending` row in `item_request_messages` + event `item_request_message`; the bot of that messenger delivers it and reports `POST /admin/item-request-messages/{id}/result` (service key only; `sent`/`failed` + reason). The dialog polls and shows history and errors.

Tests (Windows, fakes): shopapi **382** ✓, shopbots **247** ✓, shoptg **49** ✓, shopsystem **49** ✓, shopadmin **475** ✓.

## v2.6.0 — findings from the Windows test on `hesab5 t` (2026-10-14, same branch `feature/order-flow-v250`) — DONE in code (Linux, fakes only); Windows / SQL / Bale UNVERIFIED

Decisions: `REQUIREMENTS.md` §7b. Version **2.6.0** in `shopapi/app/control.py`, `shopadmin/installer/ShopAdmin.iss` and now also `shopadmin/app/paths.py` (`test_v260.py` fails if the three differ).

### Bugs
1. **Sidebar version** showed `APP_VERSION = "1.0.0"` (never bumped) → 2.6.0, kept equal to the installer by a test.
2. **Order dialog «فیشی ثبت نشده است»** although an image existed: the bot sends only an image (no tracking number) → «شمارهٔ پیگیری وارد نشده» when `has_receipt`, «فیشی ثبت نشده است» only without one (`orders.receipt_ref_text`).
3. **«مشتری #4»**: `GET /admin/orders` (and admin `GET /orders/{id}`) now carry `user_name`, `user_person_code` and `person_name` (Sazeh `name_mo.fname + Name`, one batched query, `reader.person_names`; never raises — without the column grant ShopAdmin shows the registration name). Dialog: «نام (کد شخص N)» + a «کد شخص در حسابداری» row. `grant_shop_app.sql` grants `fname, Name` (re-run `grant_shop_app.ps1`).
4. **Approve/Reject on approved customers**: decided customers get no buttons at all («تصمیم گرفته شده»); `_approve/_reject` ignore non-pending rows.
5. **`build_all.bat` paused with `SHOP_NOPAUSE=1`**: it set the variable itself and then paused unconditionally. Now it remembers the caller's value (`CALLER_NOPAUSE`) and pauses only when the caller did not set it; `build_shopadmin.bat` honours `SHOP_NOPAUSE` too. Untested on Windows.
6. **Bot rate limit**: callbacks have their own limiter (`RATE_LIMIT_CALLBACKS`, 120 per `RATE_LIMIT_WINDOW`), messages keep 20; a refused tap only answers the callback (no alert); the warning goes out once per window (`ratelimit.WarnOnce`); `/start` is never counted or refused.
7. **CRITICAL — phone sold while sales were closed**: a phone was "an item mapped in the price list"; with no list nothing was mapped, so the Samsung A26 was sold as an accessory at the Sazeh price. Now a phone = an item of a **phone group** (bug 10), read from the accounting DB inside the order lock: closed sales → 409 for any phone-group item (also from a stale cart without a color); a phone without a sellable entry in the current valid list → hidden (`/products`, `/products/{code}` 404) and 422 on order. The bot re-reads the sales state (no 30 s cache) at the final checkout.
8. **Placeholder card `XXXX-XXXX`**: `PAYMENT_CARD_NUMBER` (16 digits, not all equal) is required: `POST /orders` → 409 «Payment details are not configured» (after the idempotency lookup), `/shop/state.payment_ready=false`, the bot's cart shows `PAYMENT_NOT_READY` instead of «ثبت نهایی», checkout refuses, ShopAdmin dashboard shows a warning. Card/owner/sheba come only from shopapi; `card_number/card_owner/bank_name` and `PAYMENT_INSTRUCTIONS` were removed from `messages.fa.json` (new keys `PAYMENT_DETAILS`, `PAYMENT_OWNER_LINE`, `PAYMENT_SHEBA_LINE`, `PAYMENT_SEND_RECEIPT`, `PAYMENT_NOT_READY`; an old operator copy with a placeholder card is ignored).
9. **`ACCOUNTING_STATUS_CODE` in ShopAdmin**: in `control.EDITABLE` with the same rule as `status_code_problem` (required, whole number, not 6808); ShopAdmin checks it before sending and translates the server's message.

### New features
10. **«گروه‌های کالا»** (ShopAdmin page, `catalog.view` to see, `catalog.manage` to save): `GET/PUT /admin/product-groups`, SQLite `product_groups` (`app/groups.py`). Customers see only «نمایش در ربات» groups (`/groups`, `/products`, `/products/{code}`, orders); none chosen = nothing shown + dashboard warning (`catalog_ready`). Staff (ShopAdmin products page) still see every group.
11. **Lists only in stock**: the bot always asks `in_stock=true` (`SHOW_OUT_OF_STOCK` removed); phones only when sellable in the current valid list and priced only from it; a price-list mapping outside a phone group is ignored.
12. **«درخواست کالای ناموجود»**: menu button → the customer types a name → up to 8 matching product names (`GET /item-requests/search`, no prices) + «ثبت همین متن» → `POST /item-requests` (SQLite `item_requests`; 10 per customer per day; nothing written to Sazeh; no payment). Out-of-stock product → «درخواست این کالا». Event `item_request` → ShopAdmin toast + badge + page «درخواست کالا» (open / handled / all; «دیده شد», «رسیدگی شد») and a notice in the admin chats.
13. **Statement PDF**: `GET /users/{p}/{c}/statement/full` (oldest first, running balance, opening balance, sums, final balance, Sazeh name + person code) → `shopbots/app/cards/statement_pdf.py` (HTML + Vazirmatn → headless Edge/Chromium `--print-to-pdf`, A4, RTL, Jalali print date, header row repeated on every page) → `sendDocument` (Bale multipart / Telethon `force_document`). No browser / failure → the old paged text. Checked on Linux Chromium (3-page sample).

### Tests (Linux, 2026-10-14)
shopapi **371** ✓ (+18 `test_v260.py`), shopbots **239** ✓ (+11), shoptg 47 ✓ + 2 skipped, shopadmin **463** ✓ + 3 skipped (+15), shopsystem 36 ✓ + 12 skipped + 1 ✗ pre-existing (`test_local_backup_dir`, Windows path).

### Not verified / for the owner
- Windows: `build_all.bat` with `SHOP_NOPAUSE=1`, the two new ShopAdmin pages on a real display, the statement PDF with **Edge** on the server (Bale must accept `sendDocument` multipart — not tried live).
- `hesab5 t`: `person_names` with and without the new grant (re-run `grant_shop_app.ps1 -Apply`), group codes from `Gkala`.
- **Before customers use v2.6.0**: choose the groups in «گروه‌های کالا» (until then the bot shows nothing), enter the card number and `ACCOUNTING_STATUS_CODE` in server settings.

## v2.5.0 follow-up — sales gate for phones only, tests isolated from .env (2026-10-14, same branch `feature/order-flow-v250`) — DONE (Linux)

- **Closed sales block only phones.** `POST /orders` returns 409 `Sales are closed: …` only when the order contains a product priced from the price list (`phones.has(code)`); accessories / other items are always accepted (no list, Friday, holiday, manual close). A mixed cart with a phone is refused as a whole. Bot: the closed banner appears only on product pages that show a phone and on the color view; the cart hides «ثبت سفارش» only when it contains a phone; `SALES_CLOSED*` texts say «فروش گوشی بسته است… گوشی را از سبد حذف کنید تا بقیهٔ کالاها سفارش داده شوند». shopapi state messages, ShopAdmin dashboard panel («وضعیت فروش گوشی»), confirm dialogs, notifications and server-setting labels say «گوشی» and that accessories stay orderable. Supersedes item 2's "Scope" note above.
- **Tests never read a real `.env`.** Autouse fixture `_no_real_dotenv` in every suite's `tests/conftest.py`: shopapi/shopbots patch `app.config._load_dotenv`, shoptg `app.config.load_env_file`, shopadmin/shopsystem `dotenv.load_dotenv` (their code imports it inside functions). Opt-out for live runs only: `SHOP_TESTS_USE_DOTENV=1`. Regression tests write a temporary `.env` with `ACCOUNTING_STATUS_CODE=0` and check it is ignored (this is what failed on the Windows dev PC in `test_status_code_has_no_default`).
- Version stays 2.5.0. Tests (Linux): shopapi 353 ✓, shopbots 228 ✓, shoptg 47 ✓ + 2 skipped, shopadmin 448 ✓ + 3 skipped, shopsystem 36 ✓ + 12 skipped + 1 ✗ pre-existing (`test_local_backup_dir`, Windows path).

## v2.5.0 — order flow: 30-min receipt, sales windows, Status config, DB guards (2026-10-14, branch `feature/order-flow-v250`, from `merge/v240-into-magical-ride`) — DONE in code (Linux, fakes only); Windows / SQL / Bale UNVERIFIED

Decisions: `REQUIREMENTS.md` §7a. Nothing was run against SQL Server, Bale, Telegram or Windows.

### Done
1. **No 12-hour reservation; receipt within 30 min.** `RESERVE_HOURS` is gone (`RECEIPT_DEADLINE_MINUTES`, default 30; `orders.reserve_until` now holds the receipt deadline). `shopapi/app/order_timeout.py` runs every `ORDER_TIMEOUT_CHECK_SECONDS` (30 s) and also lazily on `POST /orders` / receipt upload: an `awaiting_payment` order past its deadline becomes `cancelled` with `cancel_reason='receipt_timeout'` **in our SQLite only** (event `order_auto_cancelled` → bot tells the customer, ShopAdmin toast + «لغوشده» tab). A late receipt gets 409 «Receipt deadline passed» (bot: `RECEIPT_TOO_LATE`). An order that already has an `accounting_order_no` is never cancelled: audit + one `order_timeout_written` event (bot → owner chats, ShopAdmin warning). Nothing is ever deleted (neither here nor in Sazeh).
2. **Price list every 10 min** (`shoptg` `TG_PRICE_INTERVAL_MIN` default 30 → 10; auto-import unchanged, the >15 % hold stays). **Sales windows** `shopapi/app/sales.py` (Asia/Tehran; fixed UTC+03:30 fallback when Windows has no tzdata): list posted < 13:30 → open until 13:30; < 20:30 → until 20:30; otherwise / yesterday's list / Friday (`SALES_CLOSED_WEEKDAYS=4`) → closed. Post time = Telegram `posted_at`, else activation time. `POST /orders` → 409 `Sales are closed: <reason>` (after the idempotency lookup, so a retry still gets its order). Bot: product lists start with «لیست قیمت به‌روز نشده… فروش بسته است» (last prices stay visible), the cart hides «ثبت سفارش», checkout answers `SALES_CLOSED` / `_HOLIDAY` / `_FRIDAY`. Transitions raise `sales_opened` / `sales_closed` once. **Scope: the gate closes all orders (accessories too)**, as the spec reads; say if accessories should stay open.
3. **ShopAdmin buttons** (dashboard «وضعیت فروش»): «باز کردن فروش» (only while closed), «بستن فروش», «تعطیلی امروز» → `POST /admin/sales/action` (permission `shop.state`). Stored server-side (`shop_state.sales_override` JSON: mode, until, by, at, list id), audited (`sales_holiday|close|open`), one event each. holiday = closed until 00:00 next day (a new list does not end it); close = until the next list or «باز کردن»; open = until the next list or the next 13:30/20:30. Latest button wins. Old `PUT /admin/shop/state {closed}` maps to close/open. **The old "closed mode still takes orders" behaviour is replaced.**
4. **Notifications**: the existing `shopadmin/app/notifications.py` (EventWatcher + TrayNotifier) already runs on every install (client and server edition; `_open_main_window` → `_start_notifications`) and the main window already toasted every notice. Reused: order/receipt toasts now stay 9 s, warnings are warning-styled, new kinds have Persian notices (`order_auto_cancelled`, `accounting_duplicate_order`, `order_timeout_written`, `sales_*`).
5. **Status**: `ACCOUNTING_STATUS_CODE` has **no default** (`None`); 6808 is refused; a real write without a valid value raises `AccountingConfigError` → approve-payment 409 «Order status code is not configured» (Persian in ShopAdmin/bot). `launcher.FIRST_RUN_DEFAULTS` no longer writes `0`. Writes stay disabled by default.
6. **DB name per order**: `orders.accounting_db` (set at creation, replaced by the DB actually written to). `tracking.sync_invoices(db, reader, accounting_db)` and `GET /orders/{id}` invoice numbers only for orders of the connected DB (case-insensitive); an order without a recorded DB (all orders before v2.5.0) is never matched — **old written orders are no longer tracked** (nothing was deployed, so none should exist).
7. **Duplicate order number**: the in-transaction `COUNT(*) WHERE Codlp=?` ≠ 1 → `DuplicateOrderNumber` (rolled back) → 409 + event `accounting_duplicate_order`; after COMMIT the count is read again (`WriteResult.codlp_rows_after_commit`) and > 1 → audit + the same event. Nothing is deleted.
8. **Persian SQL errors** `shopapi/app/sql_errors.py` (18456, 18452, 18470, 18486, 18488, 4060, 4064, 229, 230, 208, 207, 2812, 1222, 1205, 53, 2, 17, 10060, 10061, 9002, 1105 + SQLSTATE 28000, 08001, 08S01, HYT00, HYT01, IM002, 42000, 42S02, 42S22). The 503 handler returns `error_code` + `message_fa` (never the driver text/server/login); `/admin/server/status` and `ShopSystem.exe --check-db` too; ShopAdmin shows `message_fa`.
9. **Role `shop_app`**: `shopapi/sql/grant_shop_app.sql` (2008 R2: `CREATE ROLE` + `sp_addrolemember`; same column-level grants as `create_api_user.sql` + DENYs, user must not be db_owner) and `shopsystem/deploy/grant_shop_app.ps1` (dry run without `-Apply`; Windows auth; `-CreateLogin` asks the password hidden and sends it as a SqlClient parameter). Both + `verify_permissions.sql` ship in ShopServerSetup (`ShopAdmin.iss` `#ifdef SERVER`). The "audit report section 6" named in the task is **not in this repo**; the role follows `SAZEH_DB_REFERENCE.md` §8 / REQUIREMENTS §10.
10. **DB allowlist**: real writes need switch + allowed host + `ACCOUNTING_ALLOWED_DATABASES` (empty = none). Test mode only for `ACCOUNTING_TEST_DATABASES` (default `hesab5 t`). A dry run now **never sends INSERT/UPDATE** (only lock, idempotency SELECT, MAX+1, Shamsi date); `dry_run=False` on a non-allowed DB raises `AccountingWriteRefused`.
11. **Version 2.5.0** in `shopapi/app/control.py` and `shopadmin/installer/ShopAdmin.iss` (FastAPI title version too).

### Tests (Linux, 2026-10-14)
shopapi **351** ✓ (+44, `tests/test_v250.py`), shopbots **226** ✓ (+7), shoptg **46** ✓ + 2 skipped, shopadmin **448** ✓ + 3 skipped (offscreen), shopsystem 36 ✓ + 12 skipped + **1 ✗ pre-existing** (`test_local_backup_dir` asserts a Windows `E:\` path; unchanged).

### Not verified / for the owner
- Everything on Windows: ShopAdmin dashboard buttons on a real display, `grant_shop_app.ps1` + the SQL script on `hesab5 t` (then `verify_permissions.sql`), the installer build with the new `[Files]` lines, `--check-db` Persian output.
- Live `hesab5 t`: dry run sends no INSERT (only reads), real write with `ACCOUNTING_STATUS_CODE` set, post-commit duplicate check, Persian messages for real driver texts (the native-number parsing assumes the usual `(18456)` / `[53]` form).
- **Set `ACCOUNTING_STATUS_CODE`** in the server `.env` (test copy: e.g. 0 after G2) — without it approve-payment refuses real writes, also on `hesab5 t`.
- The e2e scripts (`shopapi/scripts/e2e_order_dryrun.py`, `shopadmin/scripts/e2e_*.py`) place orders: outside a sales window press «باز کردن فروش» first (or `SALES_WINDOWS_ENABLED=false`).
- Real Telegram channel timing (post time vs. 13:30/20:30) and Bale texts on a real client.

## v2.4.0 — forgot password, server edition without login, test-DB mode (2026-10-13, branch `claude/amazing-mccarthy-dob95x`, from `claude/invoice-card-v3`) — DONE in code (Linux); GUI/Windows UNVERIFIED

- **Version 2.4.0** in `shopapi/app/control.py` and `shopadmin/installer/ShopAdmin.iss`; `shopapi/tests/test_v240.py::test_server_and_installer_versions_match` fails if they differ.
- **Remember-me checkmark**: Qt style sheets do not load `data:` URIs, so the glyph never showed. `theme.indicator_images()` now renders the check/radio PNGs to `%TEMP%\ShopAdmin-ui` and the stylesheet points at the files. Test renders a checked box offscreen and looks for the white mark.
- **Forgot password**: public `POST /auth/forgot` (+ `/forgot/status`, `/forgot/complete`) with a per-request secret (stored hashed), new table `password_requests`, event `password_request`; admins (`admin`, `super_admin`; permission `passwords.decide`) approve/reject in the new ShopAdmin page «درخواست‌های گذرواژه»; an admin cannot decide a super admin's request. After approval (30 min window) the requester picks the new password in the login window's dialog; the old password and all sessions die. Unknown usernames get an identical answer. Passwords stay salted scrypt hashes (the server has always used scrypt, not bcrypt).
- **Super admin**: «بازنشانی به ۱۲۳۴۵» (`POST /admin/staff/{id}/reset-default`: hash of 12345 + must-change-password, sessions dropped; until changed the account can do nothing but change its password) and the existing «تغییر گذرواژه» (now with an optional must-change checkbox).
- **Server edition** (the full build / ShopServerSetup; detected by the presence of `app.server_setup`, override `SHOPADMIN_EDITION`): no login screen, no logout/lock/change-password. It signs in with `POST /auth/console-login` — service key from `%ProgramData%\ShopServer\.env` + loopback only → session of the first active super admin. Client edition, bot/API keys unchanged.
- **Test mode**: `Settings.is_test_db()` (`ACCOUNTING_DATABASE` = `hesab5 t`) ⇒ `write_allowed()` is true with no switch/host check; `/admin/system-info` and `/admin/server/status` report `test_mode` and write enabled. Any other database keeps the old `ACCOUNTING_WRITE_ENABLED` + allowed-host rule.
- Also fixed two Linux-only test races (login window prefill / main-window header after the store closed).
- Tests: shopapi 303, shopadmin all green offscreen, shopbots 218, shoptg 45 (+2 skipped), shopsystem 36 (+12 skipped; `test_local_backup_dir` fails only because it asserts a Windows path).
- **Not verified**: anything on Windows (UAC/ACL read of the server `.env` by the server edition, real window rendering, installer build), live `hesab5 t` writes, the checkmark on a real display.

## Idempotency, e2e scripts, ShopAdmin UI leftovers (2026-10-13, branch `claude/magical-ride-7p262r`, from `claude/invoice-card-v3`) — DONE in code (Linux)

- `POST /orders` accepts `Idempotency-Key` (8–128 chars): same key + same customer → the original order (HTTP 200, no new reservation); another customer's key → 409; keys live 24 h in SQLite (`idempotency_keys`). The bot keeps one key per cart in its `kv` (retry/double tap reuses it; a changed cart or a finished checkout gets a new one). Tests: shopapi 293, shopbots 219.
- `shopadmin/scripts/e2e_check.py` and `e2e_app_live.py` rewritten for server-side login (`SHOPADMIN_USER`/`SHOPADMIN_PASSWORD` env, optional `SHOPADMIN_BOOTSTRAP_KEY`/`SHOPADMIN_CERT_FILE`); how to run is in their headers. Both were run on Linux against a fake-backed shopapi (all pass); **not run against `hesab5 t` / on Windows**.
- ShopAdmin: two-column login (`LoginWindow._build_brand_panel`), `widgets.add_shadow` on stat cards and the login card, `_CenteredOverlay` background scoped by object name, deferred login prefill tolerates a closed store. contrast_audit 95/95. Screens re-rendered on Linux into `shopadmin/docs/screens/` (fonts differ from Windows).
- Known on Linux: `test_sidebar_badges_and_close_to_tray` fails (closed SQLite in a Qt callback; also fails without these changes); shopsystem `test_local_backup_dir` fails (Windows path).
- `CLAUDE.md` shortened; its old status/backlog moved to the archive at the end of this file.

## Bot image cards v3.2 — small fixes (2026-10-13, branch `claude/invoice-card-v3`) — DONE in code (Linux)

- Final invoice: the «✓ فاکتور شما صادر شد — شمارهٔ فاکتور: …» row is now forced onto one line (`nowrap`, font 24 → 17 px by text length); it wraps only beyond ~62 characters (about 8 invoice numbers).
- Price card: the lone «فروشگاه» footer line (signature) is gone; the footer is now the date box plus the same contact band as the invoices (address, phone, Bale bot ID from the `shop` block of `messages.fa.json`; no thank-you line). `price_card()` takes `contact=`; the engine passes it.
- Tests: shopbots 186 passed (Telegram-channel tests not collectable here). Samples re-rendered in `docs/card-samples/`.

## Bot image cards v3.1 — invoice numbers, logo in header (2026-10-13, branch `claude/invoice-card-v3`) — DONE in code (Linux)

- **Pre-invoice**: new status row «✓ سفارش شما ثبت شد — شمارهٔ پیگیری: <our order number>» (same style as before on the final invoice).
- **Final invoice**: the number is now the accounting invoice number. New `AccountingReader.invoice_numbers()`: `SELECT DISTINCT f.ordercode, f.Numfact FROM <db>.dbo.facto f WHERE f.ordercode IN (?,…) AND f.Numfact IS NOT NULL ORDER BY …` — parameterized, no 2012+ syntax (no OFFSET/STRING_AGG), only `facto.Numfact/ordercode` (already in `grant_shopbot_2008r2.sql`). `GET /orders/{id}` returns `invoice_numbers` (list of strings) **only for the admin/bot key** and only when the order is written and invoiced; accounting down → empty list. Card text «✓ فاکتور شما صادر شد — شمارهٔ فاکتور: ۲۶۷۲، ۲۶۸۰» (all numbers of a partial order, joined by «،»); with no numbers it says only «فاکتور شما صادر شد».
- **Logo**: `assets/logo.png` is now in the header of all three cards in place of the store/phone illustration (the illustration remains only as a fallback when the logo file is missing), and still at the bottom of the invoices.
- Tests: shopapi 289 passed (pyodbc stubbed), shopbots 184 passed (Telegram-channel tests not collectable here). Samples re-rendered in `docs/card-samples/`.
- **Pending live check on `hesab5 t`**: the `invoice_numbers` query against a real invoiced order (`Numfact` type/format, e.g. varchar vs int) and that the bot's admin key reaches it.

## Bot image cards v3 — invoice/price card changes (2026-10-13, branch `claude/invoice-card-v3`, from `claude/hopeful-hamilton-yd346p`) — DONE in code (Linux); cards still OFF by default

- **Logo**: `clip/img/logo_black.png` from `ghafoorianahmad/cloud` (branch `claude/vibrant-fermat-eu8xlh`, 1450×650 transparent PNG) → `shopbots/app/cards/assets/logo.png`, embedded in the card HTML. Missing file = card still renders without it.
- **Invoice cards** (`render.py`): signature box removed, logo in its place; no colour anywhere on invoices (colour column/sub-line removed; the **price card keeps its colour column**); label «مشتری» → «خریدار»; accounting row → «سفارش شما ثبت شد — شمارهٔ پیگیری: <order id>» (shown when the order has an accounting number, i.e. on the final invoice; the tracking number is the bot order number); grand total in words under the digits (`cards/numwords.py`, tests in `tests/test_numwords.py`); titles «پیش‌فاکتور» (placed) / «فاکتور فروش» (invoiced: the existing `order_invoiced*` events, driven by the `Facto.ordercode` sync); footer = date box + logo, then a band with address, phone, Bale bot ID and one thank-you line; no price-validity line on invoices.
- **Footer values** come from the `shop` block of `messages.fa.json` (editable copy in `%ProgramData%\ShopServer`): existing `shop_address`, `shop_phone`; **new keys** `bot_id` (default `@asrertebatat2_bot`, taken from CLAUDE.md — owner must confirm it is the Bale bot ID) and `invoice_thanks`. Placeholder values still in the JSON (e.g. «شماره تلفن فروشگاه») would be printed as is — fill them in before enabling cards.
- **Payment info**: new shopapi settings `PAYMENT_CARD_NUMBER` (16 digits), `PAYMENT_SHEBA` (IR + 24 digits), `PAYMENT_OWNER` (≤ 80 chars), editable remotely (`control.EDITABLE`, written to `.env`, restart as for other settings) and labelled in ShopAdmin's server-settings page (`shopadmin/app/server_settings.py`, no new UI code). `POST /orders` now returns `payment_card_number/sheba/owner` (None when empty); the pre-invoice shows the payment row only for the filled fields, nothing at all when all are empty (then a note says details follow in the next message). The old `card_number/card_owner/bank_name` of `messages.fa.json` are no longer used by the card (still used by the text message).
- **Price card**: only the word «حسابداری» removed from its note.
- Tests (Linux, fakes): shopapi 286 passed (pyodbc stubbed: libodbc missing here), shopbots 180 passed (+ `test_telegram_channel.py` not collected, Telethon missing). ShopAdmin tests not run (PySide6 missing); only the label/translation module was exercised by hand.
- Samples: `docs/card-samples/{pre-invoice,pre-invoice-no-payment,final-invoice,price-card,price-card-out-of-stock}.png`.
- **Still to verify on Windows**: all items of the v2 list below, plus the ShopAdmin settings page shows/saves the three new fields, and a real order shows them on the pre-invoice.

## Bot image cards v2 — light invoice-sheet style, HTML → headless browser (2026-10-12, branch `claude/hopeful-hamilton-yd346p`) — DONE in code (Linux); OFF by default

Replaces the dark Pillow cards below with the style of `docs/card-samples/invoice-reference.jpg`. Same public API (`price_card`, `pre_invoice_card`, `final_invoice_card`), same text fallback, `BOT_IMAGE_CARDS` still default `false`.

- **Look**: white/light-blue page, soft blue waves top and bottom, header with «عصر ارتباطات ۲» + inline store/phone illustration, rounded info box (order no., Shamsi date, optional customer), table with dark-blue header row and an icon per column/row, dark-blue totals panel with large bold numbers, notes box (bank card goes here on the pre-invoice), footer with date and signature line. Amounts in Rial, Persian digits.
- **Tech** (`shopbots/app/cards/render.py`): HTML/CSS template per card; Vazirmatn embedded as base64; icons = Tabler Icons subset (MIT, `assets/icons.json` + `ICONS-LICENSE-MIT.txt`) inlined as SVG; screenshot by running a Chromium-family binary with `--headless=new --screenshot` (no Playwright, no download). Browser lookup: `BOT_CARD_BROWSER` → on Windows Microsoft Edge (`Program Files (x86)\Microsoft\Edge\Application\msedge.exe`, then Chrome) → PATH → `/opt/pw-browsers`. Persian shaping/RTL are done by the browser, so `arabic-reshaper`/`python-bidi` were dropped from `requirements.txt` and `build_exe.bat`; Pillow stays, only to crop the screenshot (a headless window's viewport is shorter than `--window-size`, so the window is rendered 200 px taller and cropped). Render timeout 40 s; any failure (no browser, timeout, crash, bad image) → `None` → text message.
- **Samples** regenerated with Linux Chromium 141: `docs/card-samples/*.png` (+ README). Regenerate: `python shopbots/scripts/render_card_samples.py`.
- Tests: shopbots 146 passed (`tests/test_telegram_channel.py` not collected here: Telethon not installed in this container). Browser-dependent tests skip when no browser exists.

### Must be verified on Windows (not done here)
1. `msedge.exe --headless=new --screenshot` works from the **ShopServer service account** (`NT SERVICE\ShopServer`): it needs a writable temp dir (we use `%TEMP%` of that account) and Edge must start without a desktop session. If it fails, set `BOT_CARD_BROWSER` or run the service as a normal user; the bot just sends text.
2. Output size/crop: the PNG must come out exactly 1080 px wide with the whole page (footer + bottom wave) visible; the 200 px window padding assumes Edge's headless viewport is shorter by < 200 px.
3. Vazirmatn and icons render the same (fonts are embedded, so they should); compare against the Linux samples.
4. Card latency (~1–2 s per card) acceptable; many parallel cards spawn parallel Edge processes.
5. PyInstaller build still bundles `cards/assets` (now includes `icons.json`); `--collect-submodules PIL` kept.
6. Real Bale/Telegram upload and how the clients display the tall image (unchanged from v1, still untested).

## Bot image cards — price / pre-invoice / invoice (2026-10-12, branch `bot-cards`) — DONE in code (Linux, fakes only); OFF by default

Branched from `bot-design`. Samples with fake data: `docs/card-samples/` (regenerate: `shopbots/scripts/render_card_samples.py`).

### Done
- **Renderer** `shopbots/app/cards/render.py`: Pillow + `arabic-reshaper` + `python-bidi`, Vazirmatn Regular/Bold (OFL, bundled in `cards/assets/` with `OFL.txt`). Letters are reshaped, put in visual order and drawn with Pillow's BASIC layout, so output is identical with or without libraqm and nothing needs installing on Windows. Dark theme (#05070c, deep blue glow, frosted panels); optional `cards/assets/logo.png` replaces the text wordmark. Every function returns PNG bytes or `None` (never raises).
- **Shaping proof** (`tests/test_cards.py`): joined presentation forms, RTL visual order, Latin model names/digits keep their order inside Persian, every emitted glyph exists in the font, Shamsi date (`cards/jdate.py`) and Persian digits.
- **Cards**: price card (name, colour, price in Rial, stock badge, shop name), pre-invoice (order no., Shamsi date, lines, total, bank card from `messages.fa.json`), final invoice (order no., lines, total, "invoice issued" / partial badge).
- **Sending**: `send_photo_bytes()` on the adapters (Bale = multipart `sendPhoto`; Telegram = Telethon `send_file` from memory). Photo + short caption (`CARD_CAPTION_*` in `messages.fa.json`). Any render/upload failure → the existing text message (flow never breaks).
  - Price card: on the **first colour pick per product view only**; later colour switches send just the existing short "new price" text.
  - Pre-invoice: right after checkout; the text payment instructions still follow (copyable card number, receipt prompt).
  - Invoice: on the existing `order_invoiced` / `order_partially_invoiced` events; the photo's caption is the usual invoiced message (text only if the photo fails).
- **Setting** `BOT_IMAGE_CARDS` (default `false`, `.env` only; not in shopapi's editable list). `shopbots/.env.example` updated.
- `requirements.txt`: Pillow 12.3.0, arabic-reshaper 3.0.1, python-bidi 0.6.11.
- `shopsystem/build_exe.bat`: added `--add-data` for `cards/assets` and `--collect-data arabic_reshaper`, `--collect-submodules bidi/PIL` (**untested: no Windows build in this session**).
- Tests (Linux): shopbots **177 passed** (was 160; +17 in `tests/test_cards.py`).

### Final invoice data — what is used and what a true invoice needs
Used today (no grant change): the order's own lines (`order_items`: name, colour, qty, unit price), total, `accounting_order_no`, `invoiced_at` from shopapi's SQLite. The card therefore shows the **order's** prices/quantities, not what was actually invoiced, and no invoice number.
For an invoice-based card, these **read-only** grants would be needed (not added; to be applied by the owner on Windows / a DBA):
- `GRANT SELECT ON dbo.facto (Gey, Mab) TO shopbot;` — actual unit price / line amount invoiced (currently granted on `facto`: `Numfact, Codekala, Meg, ordercode, orderdetailcode`; `Numfact` = the invoice number and `Meg` = invoiced quantity are therefore already readable).
- `GRANT SELECT ON dbo.Fact (Numfact, <invoice-date column>) TO shopbot;` — the invoice date. The exact column name is **not confirmed**: check `Fact` on `hesab5 t` (`SAZEH_DB_REFERENCE.md` lists `Facto`, the line table, but the `Fact` header columns need a look).
Then shopapi's tracking (`tracking.py`) must also read and store them; that is a separate task.

### Pending / for the user
- Review the samples, then set `BOT_IMAGE_CARDS=true` in the server `.env` to enable.
- Not tested: real Bale `sendPhoto` multipart upload, Telethon `send_file` of bytes, the Windows PyInstaller build (assets/fonts bundled), and the card in the real Bale/Telegram clients (cropping of tall images).
- The card number shows exactly what is in `messages.fa.json`; with the placeholder, the pre-invoice says payment details follow.
- Persian digits are used on the cards; the captions keep the existing Latin-digit format.

## Bot look & feel — option C applied (2026-10-12, branch `bot-design`)

Texts only: `shopbots/app/messages.fa.json` (98 values changed: 25 button labels + 73 messages). No code, flows, callback data, keys or placeholders changed (placeholder sets checked per message).
- Style = option C of `DESIGN_SAMPLES.md` (formal Persian, "فرمایید", ◆ ❖ ✦ ☑ ◈ markers, 12-char `────────────` separators) mixed with a few functional emojis: 📱 phones/contact, 🛒 cart, 📦 orders, 💳 payment, 🧾 receipt/invoice, 🚚 shipped, 📍 address, ☎️ phone, 🔒 closed, 🎨 colors, 📒 statement, 📨 inquiry.
- Test-driven wording kept: `«{shop_name}»` in WELCOME, "رنگ را انتخاب کنید", "قیمت ندارد", "شمارهٔ سفارش", "🔄" in COLOR_CHANGED.
- Not changed (still in `engine.py`): color buttons use 🎨/❌, unavailable products `❌ <name>` in lists. Admin-only notices were only lightly restyled.
- Tests (Linux): shopbots 160 ✓.
- Pending: look at it in real Bale/Telegram (◆ ❖ ✦ ◈ glyphs on Bale desktop; if broken swap for 🔹). Operators who copied `%ProgramData%\ShopServer\messages.fa.json` keep their old texts until they replace that file.

## Phase 7 — Telegram bot channel (2026-10-12) — DONE in code (Linux, fakes only); never connected to Telegram

Branch `phase7-telegram` (not merged). No token, `.env`, session or real Telegram traffic was used.

### Decisions (user, 2026-10-12)
- Proxy parsing + fake-TLS + `connection_for` moved into a small shared package **`shared/tgproxy`** (`shop-tgproxy` 1.0.0), used by shoptg and shopbots. No importlib-by-path loading.
- The bot both **reads** the proxy ranking and **reports** health to shopapi (`/worker/proxies`, `/worker/proxies/report`).
- Reuses shoptg's `TG_API_ID` / `TG_API_HASH` (one Telegram app). Only `TELEGRAM_BOT_TOKEN` is new.

### Done
- `shared/` (`pyproject.toml`, `tgproxy/{proxies,faketls,connection}.py`): files moved with `git mv` from `shoptg/app`; shoptg imports and tests updated, behaviour unchanged. `import tgproxy` does not import Telethon; `faketls`/`connection` do (lazily from `connection_for`).
- `shopbots/app/platforms/telegram.py` — `TelethonBotAdapter(PlatformAdapter)`, `platform = "telegram"`:
  - bot login (`sign_in(bot_token=…)`) over an outgoing MTProto connection; no webhook, no inbound port;
  - Telethon events (new message, callback) become Bot-API-shaped update dicts in a queue, so **`polling.py` and `engine.py` are unchanged** and every Bale flow works as is: contact-only registration (contact `user_id` 0/missing → `None` → refused; `!= sender` refused by the existing core check), R4 auto-approval, catalog/search, `m_<slug>`/copied text/names, colors with per-color price, cart/order, receipt (photo or PNG/JPEG file, size checked from the message and while streaming), tracking messages, statement, closed mode;
  - messages > 4096 chars are split (keyboard on the last part); callback data > 64 bytes is refused with an error; Telethon's default Markdown parse mode is switched off; groups and bot senders are ignored; update ids are time based, so they keep growing across restarts (the engine stores the last id).
- `shopbots/app/platforms/tg_pool.py` — `ProxyPool`: shopapi ranking (best first) → local `TG_PROXY` links → direct (`TG_ALLOW_DIRECT`). Reports `{"id","ok","latency_ms"}` after every connection attempt and every health ping.
- **Auto-switch:** each `get_updates` call (re)connects through the first working candidate; a failed ping (every `TG_HEALTH_INTERVAL_SEC`, default 180 s), a dropped socket or a network error drops the connection, reports the proxy as failed and raises a network `BotApiError`; `poll_platform`'s existing backoff retries, which connects through the next proxy within seconds. A wrong bot token / api id is fatal (401 line) and does not cycle through the pool. All proxies dead → the retry loop continues; shopapi raises its `proxies_all_dead` alert from the reports.
- Config (`shopbots/app/config.py`, `.env.example`): `TELEGRAM_BOT_TOKEN`, `TG_API_ID`, `TG_API_HASH`, `WORKER_API_KEY`, `TG_PROXY`, `TG_ALLOW_DIRECT`, `TG_BOT_SESSION` (default `tg_bot.session` next to `SQLITE_PATH`), `TG_HEALTH_INTERVAL_SEC`, `TG_CONNECT_TIMEOUT_SEC`. The channel starts only when token + api id + api hash are all set and Telethon is installed (otherwise one log line, Bale unaffected). Secrets are `repr=False`; the log redactor also masks `api_hash`.
- **Owner alerts stay on Bale / admin isolation:** `ADMIN_CHAT_IDS` now means Bale only (a bare id used to match *any* platform; a Telegram user id equal to the owner's Bale id would have become an admin). `telegram:<id>` entries are ignored. Tested.
- The bot's Telethon session is an SQLite file (keeps update state with `catch_up=True`, so messages sent while the bot was down are delivered, and the entity cache so proactive tracking messages work after a restart). It is git-ignored (`*.session`) but holds the bot's auth key: treat it as a secret.
- Packaging: `shoptg/requirements.txt` + `shopbots/requirements.txt` + `shopsystem/requirements.txt` list `shop-tgproxy==1.0.0` / `../shared`; `shoptg/install.ps1 -Dev` and `shopbots/setup.ps1` install `..\shared` first; `shoptg/build_package.ps1` builds the shared wheel into `wheels\`; `shopsystem/build_exe.bat` adds `--collect-submodules telethon` and `tgproxy`.

### Tests (Linux, fakes; no network)
- shopbots **160** ✓ (+32: `tests/test_telegram_channel.py`, `tests/tg_fakes.py`): connector per secret kind (ee/dd/plain), ranking order, failover on ping failure and dropped socket, all-dead and recovery, fatal token, reports, pool client (local dedupe, direct last, keyless, API down), full engine flows on platform `telegram` (registration refusals, R4, model links, colors, order + receipt, statement, closed mode + tracking), split messages, polling loop unchanged, admin isolation, secrets absent from logs, the real Telethon client accepts our options.
- shoptg **45 ✓ + 2 skipped** (same as before the move), shopapi **281** ✓ (needs `unixodbc`).
- shopadmin: 2 failures in `test_notifications` / `test_ui` that **also occur without my changes** (sqlite "closed database", differs per run; Qt on Linux); the code is untouched by this phase. shopsystem: 36 ✓, 12 skipped, 1 failed (`test_local_backup_dir`, expects the Windows path `E:\ShopBackup`).

### Must be verified on Windows / live (not done)
- A real BotFather bot: login, `/start`, contact button, inline buttons, receipt photo download, **`/start m_<slug>` deep link** (`t.me/<bot>?start=m_<slug>`), message editing, a callback toast.
- Telethon 1.45.0 uses the newer TL layer: reply/inline buttons are `Button`/`KeyboardInlineButton` with `.type`; confirm `request_phone` really shows the share-contact button and that the contact message carries `user_id` for the user's own number.
- Fake-TLS (`ee`) against real proxies **for a bot login** (shoptg only proved the user-session path); latency/failover timings; behaviour when Telegram is blocked without a proxy.
- Two Telethon processes (shoptg user session + the bot) using the same api id from one IP: no interference expected, unproven.
- `catch_up` on first start with an empty session file; update delivery after a restart.
- `WORKER_API_KEY` reaches ShopSystem's environment so the in-process bot can read `/worker/proxies` (the launcher already writes it for shoptg).
- **PyInstaller / ShopSystem.exe:** `Telethon` and `shop-tgproxy` must be installed in `shopsystem`'s venv (`pip install -r requirements.txt` from `shopsystem\`, which now includes `../shared`); `--collect-submodules telethon`/`tgproxy` were added to `build_exe.bat` untested; the packages are renamed `shopbots_app`, so `shopbots_app.platforms.telegram` is imported lazily — check it is in the bundle, that the exe size is acceptable, and that `build_all.bat` still passes.
- `shoptg\install.ps1 -Dev`, `build_package.ps1` (shared wheel + offline install probe) and `shopbots\setup.ps1`: edited on Linux, never run.
- ShopAdmin shows no Telegram bot status yet (the health snapshot has the platform; no UI change was made).

### Next step
Owner: create the bot with BotFather, put `TELEGRAM_BOT_TOKEN` in the server `.env`, run the checks above on a test bot, then add the Telegram button on the site (same `m_<slug>` mechanism, REQUIREMENTS §9).

## Phase 6b — catalog-model mapping, fuzzy suggestions, nightly check, bot resolution (2026-10-12) — DONE in code; not tested on SQL or live Bale

### Decisions (user, 2026-10-12)
- Plan approved with one change to the nightly check (now in REQUIREMENTS §9a):
  - if the `kala_code` still exists and the new name is still a strong fuzzy match (`MODEL_DRIFT_MIN_SCORE`, default 0.7), the model **stays visible** and the item is only flagged «drifted» in ShopAdmin, with no Bale alert;
  - the model is hidden and the owner alerted only when the product is missing/inactive or the similarity is below the threshold.
- Price-list rows reach a model through the same `kala_code` (`price_mappings.kala_code` = `catalog_model_items.kala_code`), so each model is mapped once. One accounting product belongs to one model only.

### Done
**shopapi**
- `app/fuzzy.py` — normalized matching:
  - case, ی/ي, ک/ك, Persian/Arabic digits, ZWNJ/diacritics;
  - letter/digit split (`17pro`);
  - Persian↔English model words (آیفون/iphone, پرو/pro, گیگ/gb, «سی» = c, «ای» next to a number = e).
  - Identity first: numbers, model qualifiers (Pro/Max/Ultra/…, and any single latin letter: 17/17e, 14/14c) and accessory words (قاب/گلس/…) on one side only cost a lot. Colors/units cost little.
  - `coverage()` ranks suggestions (model name → accounting name). `similarity()` is used for drift. `similarity(model_only=True)` ignores storage/color in a customer's text.
- Tables `catalog_models` (slug, name, brand, aliases, hidden) and `catalog_model_items` (kala_code UNIQUE, label, confirmed/current name, state ok/drifted/missing, score, candidates JSON).
- `app/catalog_models.py`: repo, `run_check`, `nightly_loop` (started in the lifespan; once a day after `MODEL_CHECK_HOUR`, default 02:00 server time, -1 = off), `resolve`.
  - **Nightly check:**
    - unchanged name → ok;
    - small change → drifted (visible, no alert);
    - gone/inactive or below the threshold → missing: candidates (searched by the confirmed name, excluding products already mapped) + model hidden + `model_review` event + **one** Bale message (`owner_alerts`) for newly hidden models only.
    - A failed or empty accounting read changes nothing. Never re-maps on its own.
- Reader `product_names()`: `SELECT Code, Name FROM Kala WHERE active = 1`, no user input.
- `app/routers/catalog.py`:
  - `/admin/catalog-models`: list + counts + last check; `import` (upsert by slug, site aliases merged, mappings untouched); `check` (now); `{id}` GET/PATCH; `{id}/suggestions`; `{id}/items` POST; `items/{id}` PATCH (relabel/replace) / DELETE; `items/{id}/accept`; `{id}/confirm`.
  - New permission `catalog.manage` (admin + super admin). Every change is audited.
  - **Confirm is refused while any item is «missing»**: a code that was reused for another product must be replaced, removed or accepted on its own, never by a model-wide confirm. This was found by a test where the code became a charger.
  - `GET /catalog/resolve?text=` (bot key) → found (items + labels) / ambiguous (≤3 options) / unavailable / unknown. Products are returned only for a visible, mapped model.
- `.env.example`: `MODEL_CHECK_HOUR`, `MODEL_DRIFT_MIN_SCORE`, `MODEL_RESOLVE_MIN_SCORE` (0.75).

**shopbots**
- `looks_like_model_ref` (shape only): `m_<slug>`, «کد مدل»/«كد مدل», a bare hyphenated slug. Resolution itself is on the server.
- `/start m_<slug>`, a pasted text, a bare slug, or (free text) a strong name match:
  - one product → open it;
  - several → label buttons (`kp:<code>`);
  - ambiguous → model buttons (`mdl:<i>`, slugs kept in the conversation because 64-byte callbacks are too short for a 62-char slug);
  - hidden/unmapped/unknown → `MODEL_UNAVAILABLE` / `MODEL_UNKNOWN` with the shop phone. Plain chat still goes to the main menu.
- A model reference sent before registration is kept and shown after the contact (`MODEL_AFTER_CONTACT`).
- 5 new texts in `messages.fa.json`. An older operator copy in ProgramData falls back to them key by key.

**shopadmin**
- New page «مدل‌های سایت» (`app/ui/pages/catalog_models.py`; sidebar `catalog`; `catalog.view` for every role, `catalog.manage` for admin/super admin):
  - banner with the last check and the hidden/unmapped counts;
  - filters (hidden / drifted / unmapped / ok / all) and search;
  - «ورود مدل‌ها از سایت…» reads the site's `assets/products.js` as text (never executed): slug, name, brand, aliases;
  - «بررسی اکنون».
  - Detail: items with state, current name, similarity and price-list row count. Actions: add (suggestion dialog), replace (nightly candidates first), accept current name, label, delete, aliases, «تأیید و نمایش به مشتری».
- `model_review` → tray warning, opens the page on the «hidden» filter.

**Other:** `SECURITY.md` website row (an edited/unknown slug gets "not found + phone", never a guess). REQUIREMENTS §9a refinement.

### Tests
- shopapi **281** ✓ (+36: fuzzy, drift classes, routes/permissions, nightly hide/alert-once/confirm, failed read, loop, resolve paths, aliases, storage/color in customer text).
- shopbots **128** ✓ (+8). shopadmin **434** ✓ (+15, exit 0). shopsystem **49** ✓, shoptg **47** ✓ (unchanged).
- The real site catalog (66 models of the redesign `products.js`): every name, alias, `m_<slug>` and copied text resolves to its own model, except 4 aliases the site gives to two models. For those the bot asks, which is the intended behavior:
  - «شیائومی پوکو» → poco-x6-pro / poco-x7-pro;
  - «شیائومی ردمی ۱۵» → redmi-15 / redmi-note-15.
  - The first run found «iPhone 17» vs «17e» ambiguous; fixed (single letters = model identity).

### Pending / for the user
1. On `hesab5 t` (regular PowerShell, not from the Claude app): start shopapi, import `products.js` in ShopAdmin, check that the suggestions on real Sazeh names make sense, map a few models, run «بررسی اکنون». `product_names()` has not run on real SQL yet.
2. Bale: `/start m_<slug>` still depends on Bale passing the start parameter (2 of 8 in the live test). The pasted text and the bare slug are the fallback and are handled.
3. Site data: the two shared aliases above. Make them specific in `products.js` if you prefer that the bot never asks.
4. Then push the redesign repo (branch `redesign`) and purge the Arvan cache (Phase 6 pending item 1).

### Next step
Phase 7 (optional): Telegram bot channel on the shared core via the proxy pool, or the live-test items above.

## Phase 6 — website: static showcase, model slugs, ArvanCloud guide (2026-10-12) — DONE; committed, not pushed

**Live site = `E:\DSH-Workspace\projects\asr-ertebatat-2-redesign`** (GitHub `ghafoorianahmad/asr-ertebatat-2`, branch `redesign`). This was found after the first pass:
- every live file (`index`, brand pages, `products.js`, `site.js`, `site.css`, `theme.css`) is byte-identical to `origin/redesign` `141d9c1`;
- `redesign-2`-only files and `design-samples/` return 404;
- the live site is already served from Arvan Object Storage `ir-thr-at1`.

GitHub itself could not be queried: both repos are private and the local token has no access.

Phase 6 is in **both** site repos, with identical slugs:
- redesign `e98eaef` on branch `redesign` (the asset diff replayed from the main site + the same page edits; every assertion matched);
- `asr-ertebatat-shop` `1524dc1` + `5258adf` on local branch `backup-local-2026-10-10` (not `main`; that site is not published).

Nothing is pushed: the owner pushes after Phase 6b. The Next.js folder `E:\projects\mobile-shop` is an unused Sep-17 prototype.

### Decisions (user, 2026-10-12) — added to REQUIREMENTS §9, new §9a, phase 6b
- **No accounting codes on the site.** `Kala.Code` can change after stocktaking and Sazeh names are inconsistent. Each model has a **permanent slug** (`id` in `products.js`, e.g. `iphone-17-pro`; never renamed or reused). Slugs are model-level because the site shows models, not storage sizes. Storage and color are picked in the bot; storage-level slugs can be added later.
- Mapping slug ↔ accounting product(s) lives in shopapi/ShopAdmin (one catalog-model table shared with price-list rows), with:
  - fuzzy suggestions and one-time confirmation by the owner;
  - a nightly check that hides a model and sends a Bale alert on drift.
  This is **Phase 6b** (§9a); not started.
- No order submission from the site; it stays static with no server connection.

### Done (site)
- Card, detail and order modals show «کد مدل: <slug>».
- The button «استعلام قیمت و سفارش در بله»:
  - copies «name + کد مدل: slug» (Clipboard API on HTTPS, textarea fallback);
  - opens `ble.ir/asrertebatat2_bot?start=m_<slug>`;
  - has a «کپی» button, the hint «این متن را در ربات بفرستید» and a `tel:09155000432` fallback.
- The floating action button opens Bale, not Telegram.
- The Telegram **bot** is hidden everywhere (`data-telegram-bot hidden` + `TELEGRAM_BOT_ENABLED=false` in `site.js`); the channel link is untouched. Telegram claims in the page text and meta descriptions now say Bale.
- `site.js`: `isSlug`/`SLUG_RE` (starts with a letter, ≤62 chars so `m_`+slug fits Bale/Telegram's 64-char `[A-Za-z0-9_-]` start payload). A numeric or unsafe "slug" is never put in a URL.
- `tools/check_site.js` (Node, no dependencies; also runs on the unpacked zip) checks:
  - slug format and uniqueness; no price/stock/code fields;
  - deep links and copied text, by evaluating the real `site.js` helpers;
  - no `fetch`/XHR/WebSocket/forms/keys/`shopapi`/price text in served files;
  - Telegram bot gated; phone fallback present;
  - every local `src`/`href`/`url()` exists.
- `DEPLOY_ARVAN_FA.md`: step-by-step Persian guide, checked against docs.arvancloud.ir on 2026-10-12. It covers:
  - bucket + public-read files, the «وب‌سایت استاتیک» feature (index `index.html`, error `404.html`);
  - adding the domain to the CDN, NS change at IRNIC (copy MX/TXT from Cloudflare first);
  - free HTTPS, the bucket «دامنه اختصاصی» (ANAME root + CNAME www, Host Header = static-website host);
  - cache rules + purge, test checklist, update and rollback (keep Cloudflare for 2 weeks).

### Tests
- `check_site.js`: **1249 ✓** on the repo and on the unpacked release zip. A mutation run (numeric slug, `fetch`, price text, unhidden Telegram) fails as expected.
- shopbots **120 ✓** (+1: site slugs, `m_<slug>` and the copied text are never parsed as a Kala code).
- Headless Chrome (375 px dark/light, 1366 px): no horizontal overflow and no clipped card buttons. Order modal within the viewport. Click flow verified (deep link, copied text, toast, FAB → plain bot link).
- Found and fixed on the way:
  - the long Bale label (`nowrap`) widened the modal past the phone screen;
  - `.order-note` was an existing dashed class, so mine was renamed `.order-intro`;
  - the card CTA clipped the label at desktop widths.

### Output
- **Live:** `E:\Outputs\StoreWebsite-Redesign\StoreWebsite-Redesign_2026-10-12.zip`. 316 files, SHA-256 `1430A348…2AADD2`, `check_site.js` 1249 ✓ unpacked. The redesign was also checked with headless screenshots (375 px dark/light, 1366 px) and a click flow.
- Not published: `E:\Outputs\StoreWebsite\StoreWebsite_2026-10-12.zip`. 179 files, built before `5258adf`.
- Each folder also has `DEPLOY_ARVAN_FA.md` + README; the previous 2026-10-08 zips are kept.
- Missed in the first pass and fixed in both repos: the hero «ثبت سفارش در ربات» button still had a Telegram icon.

### Pending / for the user
1. Push the redesign repo (branch `redesign`, `e98eaef`) after Phase 6b, then purge the Arvan CDN cache and run step 8 of the guide.
   - The live site is already on Arvan Object Storage, so the bucket/DNS steps of `DEPLOY_ARVAN_FA.md` are reference only.
   - Make sure the publish excludes `DEPLOY_ARVAN_FA.md` and `tools/`; the current setup already excludes `design-samples/` and `MISSING_IMAGES.md`.
2. ~~Until Phase 6b, the bot opens at the main menu for `m_<slug>` and pasted text.~~ Done in Phase 6b.
3. `asr-ertebatat-shop`'s Phase 6 commits are on local branch `backup-local-2026-10-10`, not `main`; merge or keep as you prefer (not published).
4. Still open on the site: Telegram channel link, map link, photos for 3 models.

### Next step
Phase 6b — catalog-model mapping (§9a): table + fuzzy suggestions in ShopAdmin, nightly validation with hide + Bale alert, bot resolution of `m_<slug>` / pasted text / fuzzy name.

## Phase 5 — security hardening, SECURITY.md, backups (2026-10-12) — DONE in code; nothing installed or applied on the shop server yet

Rollback point: `1867321` (Phase 4). Version **2.2.0**.

### Decisions (user, 2026-10-12)
- The off-server backup copy is **encrypted with AES-256-GCM**. The passphrase is in the server `.env` for the nightly job and **on paper** with the owner. Losing it makes the off-server copies unrecoverable, and README_FA §10 says so in a boxed warning.
- The local daily zip is complete (plain), protected by the data-folder ACL.
- **The Telegram (Telethon) session is never backed up**: DPAPI LocalMachine binds it to this machine. After a restore on new hardware, log in again.

### Done
**A. Daily backup — `shopsystem/backup.py`, supervisor thread**
- Runs at `BACKUP_HOUR` (3), or at once if the last attempt is more than 24 h old. It backs up:
  - `shopapi.db` / `shopbots.db` through SQLite's online-backup API, consistent while the server writes and including WAL content;
  - `.env`, `messages.fa.json`, `receipts\`, `pricelists\`, `tls\`.
- It never backs up `shoptg\`, logs or `backups\`.
- Output: `backups\daily\ShopServer_<stamp>.zip` with `manifest.json` (SHA-256 per file, row counts). `BACKUP_KEEP_DAYS` (14) are kept.
- **Restore test after every backup:** hashes, `PRAGMA integrity_check`, row counts == manifest.
- **Off-server copy** in `BACKUP_COPY_DIR`:
  - `.ssbk` = scrypt (n=2¹⁵, r=8, p=1) → AES-256-GCM in 1 MiB chunks. The nonce = prefix | index | last flag and the header is AAD, so truncation, reordering and edits are detected.
  - Each copy is read back, decrypted and compared to the local zip.
  - Without a passphrase nothing is copied, and the backup counts as failed.
- Status: `backups\status.json`. It shows in shopapi as the health check `backup` (down if the last run failed or there has been no success for 30 h → Bale + tray), in `/admin/server/status.backup` (no paths or secrets) and in a ShopAdmin server-page row.
- CLI:
  - `--backup-now`, `--verify-backup <zip|ssbk>`, `--decrypt-backup … --out …`, `--restore-backup <file>`;
  - `--set-backup-passphrase`: interactive; shows a generated 8×4 passphrase (160 bits) once, makes the owner type it back from paper, writes it to `.env` and clears the screen.
  - The passphrase comes from `SHOPSERVER_BACKUP_PASSPHRASE`, else `.env`, else a hidden prompt (real console only); never from argv.
- `--install-service` grants the service account Modify on a local `BACKUP_COPY_DIR`. A drive root or a UNC path is not granted; README explains it.
- `deploy/restore.ps1`:
  1. restore test first; a bad file or wrong passphrase changes nothing (exit 1);
  2. stop the service, safety copy to `backups\pre_restore_<t>`;
  3. restore, start, `/health`;
  4. if unhealthy, put the old data back automatically (exit 3/4).
- `common.ps1` now carries the SQLite `-wal/-shm` files with backups and update rollbacks (a WAL can hold committed rows after a crash). `restore_to` deletes a stale WAL.
- `build_exe.bat` copies `deploy\{common,restore,firewall_sql}.ps1` + README next to the exe (`ShopSystem\deploy\`), so a ShopServerSetup install has them too; `build_package.ps1` adds them to the zip.

**B. Hardening**
- **Suspicious-activity alerts — `shopapi/app/security_watch.py`.**
  - Every report is audited (`suspicious_<kind>`, masked source `…1234`). A per-source threshold within 1 h triggers one Bale message + `security_alert` event (ShopAdmin tray). It repeats at most once per source and kind per hour, and at most 6 alerts per hour overall.
  - Kinds:
    - bot: `contact_not_own` (3), `rate_limited` (3), `receipt_flood` (2);
    - shopapi: `order_probe` (5; someone else's order via GET or receipt), `login_failed` (10 per address), `login_throttled`, `account_locked`.
  - Bot side: new `POST /security/report` (bot/admin key, whitelisted kinds). `engine._report_security` sends at most one report per chat and kind per 60 s and never breaks the chat.
- **Log redaction — `shopbots/app/logging_setup.RedactingFilter`**, on every root handler, including the launcher's `app.log` and `supervisor.log`. It masks `bot<token>`, bare Bot API tokens, X-API-Key/Authorization/Bearer and `password|pwd|passphrase|api_key|secret|token=` values, in messages and exception text.
- **`sa` refused:** `Settings.accounting_connection_string()` raises for `sa` (any case). A test asserts that no shopapi code mentions `Options.ini`.
- The launcher warns when `API_HOST` is not loopback and `API_TLS` is off.
- `verify_permissions.sql`:
  - new probes: DELETE KalaOrder, UPDATE KalaOrderDetail, DELETE name_mo, `name_mo.mobile`, INSERT/UPDATE/DELETE KOL, UPDATE setting / Telegram_Setting, db_owner/datareader/datawriter membership, sysadmin;
  - a test checks the grant script DENYs §10's tables and the verify script probes them.
- **`deploy/firewall_sql.ps1`:**
  - limits sqlservr.exe of the instance (+ SQL Browser UDP 1434) to `-AllowedIPs`;
  - lists and disables (never deletes) broader allow rules, saved for `-Undo`;
  - is a dry run without `-Apply`.
  - **Not run anywhere.**
- `BACKUP_*` settings are not remotely editable (test).

**C. Docs**
- `SECURITY.md`: assets, trust boundaries, a compromise table (bot token, customer account, abuse, website, ShopAdmin PC, staff password, shoptg session, `shopbot` login, server admin, LAN, stolen USB), the `sa` problem, secrets, detection, backups, incident steps, known limits.
- `deploy/README_FA.txt` §10 (backup, passphrase warning, Telegram session, restore, quarterly restore drill) and §11 (SQL firewall). `.env.example` has a `BACKUP_*` block.

### Tests
- shopapi **245** ✓ (+15 `test_phase5.py`)
- shopbots **119** ✓ (+5)
- shopadmin **419** ✓ (+3)
- shoptg **47** ✓
- shopsystem **49** ✓ (+26):
  - `test_backup.py`: contents, live WAL, tamper, encryption round trip/wrong passphrase/truncation/reorder, no-passphrase never copies plain, prune, due/health, restore, CLI end to end;
  - `test_deploy.py`: restore.ps1 in real PowerShell against the fake service — OK, bad backup, unhealthy → rollback, encrypted copy with wrong/right passphrase.
- Sandbox note: pytest needs `--basetemp` in the scratchpad from the Claude app (`pytest-of-Lenovo` is not readable here).
- Found by the tests: `isatty()` is True for NUL on Windows, so a non-interactive run would hang in getpass. `interactive_console()` now checks `GetConsoleMode`.

### Pending / for the user (on the server, elevated)
1. Plug in a USB/second disk. Then:
   - set `BACKUP_COPY_DIR=E:\ShopBackup`;
   - run `ShopSystem.exe --install-service`, then `--set-backup-passphrase` (write it on paper, keep it away from the server and the USB);
   - run `--backup-now`. Expect `ok: true`, and the server page shows «موفق و آزموده».
2. Restore drill on another PC: `--verify-backup <latest .ssbk>` with the paper passphrase. Repeat every 3 months.
3. SQL firewall:
   - run `deploy\firewall_sql.ps1 -Instance SAZEHHESAB -AllowedIPs <accounting PCs>`, read the dry run, then add `-Apply`;
   - open «سازه حساب» on every PC; if anything breaks, run `-Undo`.
4. Run `shopapi\sql\create_api_user.sql` (DBA) and `verify_permissions.sql`. Every `(0)` row must show 0, and `is_sysadmin` must be 0.
5. Still from Phase 4: live service install/reboot test. Not verified live: Bale delivery of security/backup alerts, restore on real hardware.

### Next step
Phase 6 — website: static showcase, deep links + printed product code, ArvanCloud deployment guide (§9).

## Phase 4 — service, install/update/rollback, tray, alerts, health (2026-10-12) — DONE in code; service not installed on any PC yet

Rollback point: `4a151d0` (Phase 3). Version 2.1.0.

### Decisions (user, 2026-10-12)
- Real Windows service (pywin32), not NSSM: no unsigned third-party download. Account = virtual service account **`NT SERVICE\ShopServer`** (dedicated, not admin, no password).
- shopapi stays on **LAN HTTPS** for ShopAdmin clients (the network is VLAN-segmented). Firewall = LocalSubnet by default; optional allowed-IP list (`FIREWALL_ALLOWED_IPS`). No port is opened to the internet.
- Tray = part of ShopAdmin (`--tray`), not a separate app: it already has the server session.
- Health alerts go **straight from shopapi to Bale** (`owner_alerts.py`), so "bot down" still arrives; other owner alerts still go through the bot.

### Done
**A. Windows service — `shopsystem/winservice.py`, `launcher.py`**
- Service `ShopServer`: `ShopSystem.exe --winservice --data-dir …`. Auto start at boot, no login needed. SCM restarts it 10 s / 30 s / 60 s; `failureflag 1`; `sidtype unrestricted`.
- `--install-service` / `--uninstall-service` / `--start-service` / `--stop-service` / `--service-status` print JSON.
  - Install grants the account Modify on the data folder and on files that have their own ACL (`.env`, dbs, `tls\*`). With `SHOPTG_DIR` set, it also grants Read on `shoptg\.env` and Modify on the session folder `%ProgramData%\ShopServer\shoptg`.
  - It removes the old `ShopServer` boot task.
  - Uninstall takes the grants back. Data stays.
- The supervisor runs separate children, each with its own restart and back-off: (1) API + Bale bot; (2) **shoptg** when `SHOPTG_DIR` is set.
  - shoptg's environment is filtered: it gets only the local HTTPS URL, the CA file, `WORKER_API_KEY` and `TG_SERVICE_ACCOUNT`, never the Bale token or the SQL password.
  - A child failing 3× in 10 min → one Bale alert per hour.
  - A service stop terminates the children.
- `--health-check [--timeout N]` waits for `/health` using the pinned certificate (used by update.ps1).
- `--init-config` now generates `WORKER_API_KEY`; `SHOPTG_DIR` and `FIREWALL_ALLOWED_IPS` are setup fields.
- Build: pywin32 + pdfplumber hidden imports/collects; `build_exe.bat` also runs the shopsystem tests.

**B. Install / update / rollback — `shopsystem/deploy/`**
- `install.ps1` copies the program, locks the data folder, registers the service, opens the firewall, then starts it and checks health. Without a `.env` it registers but does not start.
- `update.ps1` steps:
  1. Stop the service, then back up the program plus `.env`, dbs, `messages.fa.json`, `receipts\`, `pricelists\`, `tls\` → `backups\update_<time>\`.
  2. Swap in the new program and start it.
  3. `/health` within 120 s → done.
  4. Otherwise it **puts back the old program and data**, restarts and exits 3 (4 if the old version is unhealthy too).
  - Keeps 3 backups. Accepts a zip.
- `uninstall.ps1` removes the service and firewall rule; `-RemoveProgram` also removes the program folder. Data is kept.
- `README_FA.txt` covers the service, install/update/uninstall, a SQL login for `NT SERVICE\ShopServer` if Windows auth is used, the firewall, shoptg, alerts, and **BIOS "Restore on AC Power Loss" + UPS**.
- `build_package.ps1` builds `ShopServer_<ver>_<date>.zip`. The exe, scripts and README go in; `.env`/db/log/key are refused.

**C. Health monitoring — `shopapi/app/monitor.py`, `owner_alerts.py`**
- Every `HEALTH_CHECK_SECONDS` (60) it checks: SQL ping, bot loop running, Bale reachable (≥3 failed polls and no success for 3 min), and shoptg status freshness (`TG_STATUS_STALE_MINUTES` 20; ignored until the worker has ever reported).
- Down after `HEALTH_FAIL_THRESHOLD` (2) bad checks, up on the first good one. Each change produces one event `health_<check>_down/up` plus one direct Bale message.
- `/admin/server/status` now has `health` and `telegram_worker` (connected/proxy/login/error/time only).
- Both settings are remote-editable.

**D. ShopAdmin**
- The server wizard registers the **service** (no Windows password any more). The Windows-auth option explains the SQL login the service account needs. New optional fields: allowed IPs (validated) and the shoptg folder.
- Tray:
  - health and server warnings (price list held/failed, all proxies dead, Telegram login/unreachable) appear as warning balloons. They are not counted as unread; price-list warnings open the price-list page.
  - `--tray` starts hidden with the remembered session. Without one, it shows an icon that offers to sign in. A second `--tray` start sends "ping" instead of "show".
- Settings → اعلان‌ها:
  - "run at Windows sign-in", via HKCU Run `ShopAdmin.exe --tray`;
  - "remind when سازه حساب opens" (`sazeh_watch.py`): `tasklist` every 10 s, prefix `Sazeh Hesab` (the exe name carries the version); on start → "X سفارش جدید، Y مشتری در انتظار تأیید", and a click opens the page.
- Server page: rows «کارگر تلگرام» and «پایش سلامت».
- Inno:
  - uninstall runs `--uninstall-service` (plus legacy task delete);
  - an upgrade does `net stop ShopServer` before copying;
  - an old task-based install is moved to the service and started again in `ssPostInstall`.

### Tests
- shopapi **230** ✓ (+12 `test_phase4.py`), run with `PYTHONPATH=.venv\Lib\site-packages python -m pytest`.
- shopbots **114** ✓ (unchanged).
- shopadmin **416** ✓ (+15 `test_phase4.py`; task tests replaced by service/firewall tests).
- shoptg **47** ✓.
- shopsystem **23** ✓ (new):
  - service commands with a fake runner;
  - supervisor restart, stop and crash-loop alerts;
  - the shoptg environment filter;
  - health check against a local HTTP server;
  - **update.ps1 run in real PowerShell against a fake service**: update OK, rollback of program + data after a "migration", old version unhealthy → 4, zip + keep 3, no service, bad package;
  - firewall list; service path parsing.
- Sandbox note: the shopapi venv (Store Python) cannot create temp files from the Claude app. `build_exe.bat` therefore has an opt-in `SHOP_TESTS_ALREADY_RUN=1` to skip its shopapi/shopbots test step after both suites were run separately; this build used it. On a normal PowerShell, run `build_all.bat` without it.

### Build / outputs (`E:\Outputs\ShopSystem\`)
- `ShopServerSetup_2.1.0_2026-10-12.exe` (64 MB; bigger because of pywin32 + pdfplumber) and `ShopAdminSetup_2.1.0_2026-10-12.exe` (33 MB).
- `ShopServer_2.1.0_2026-10-12.zip` is the server package for `install.ps1` / `update.ps1`: 254 files, no `.env`/db/log/key.
- SHA-256 values are in `E:\Outputs\ShopSystem\README_FA.txt`; the 2.0.0 pair is kept as the previous version.
- Smoke test of the frozen exe: `--service-status` → `state: null` (not installed); `--health-check` returns JSON; pywin32 and pdfminer are bundled.

### Pending / for the user (on the server, elevated)
1. **Live service test** (not done on any PC — it changes the system):
   - install with ShopServerSetup, or move the current task install with `install.ps1`;
   - `Get-Service ShopServer`, reboot without logging in, check the bot answers;
   - kill `ShopSystem.exe --worker` in Task Manager → it comes back;
   - `update.ps1` with the same zip (expect 0).
2. The service account must reach SQL:
   - with SQL auth (`shopbot`) nothing changes;
   - with Windows auth, create `LOGIN [NT SERVICE\ShopServer]` (README §5).
3. The dev xray proxy at 127.0.0.1:10808 needs a logged-in user; Bale needs no proxy. shoptg uses its own `TG_PROXY`.
4. shoptg: set `SHOPTG_DIR` in the server `.env`, run `--install-service` again, restart (`shoptg/SERVER_GUIDE.md` §6). The shoptg zip in `E:\Outputs\ShopTG` still has the old guide; the updated guide is next to it.
5. BIOS "Restore on AC Power Loss" + UPS (README §9).
6. ShopAdmin on the owner PC: Settings → اعلان‌ها → autostart + «سازه حساب» reminder; tick «مرا به خاطر بسپار» once.
- Not verified live: Bale delivery of health alerts, `tasklist` names on the shop PC (prefix setting `sazeh_process_names` if different), Inno upgrade from 2.0.0 (task → service migration path).

### Next step
Phase 5 — security hardening, `SECURITY.md`, daily backups of SQLite + receipts + config with an off-server copy and a restore test (§10).

## Phase 3 — Telegram worker, price list, proxy pool (2026-10-12) — DONE in code; live Telegram login pending (on the server)

Part 1 is WIP commit `db48ce3` (rollback point: `5d7a0cf`). Part 2 is committed on top of it.

### Done — part 1 (shopapi / shopbots / shopadmin)
- **shopapi**
  - PDF parser `app/pricelist/parser.py`. On the sample: 195 rows, 15 sections, date 1405/07/19. Scrambled Persian text is matched by its letter multiset.
  - Pricing `pricing.py`: روال×10,000 Rial; else نقد×10,000 + 5,000,000 Rial; no price = inquiry.
  - Import with safety checks, `importer.py`. Outcomes: duplicate / older / failed / held. A list is held on a >15% change of a mapped price, or when most mapped rows are missing. A copy of each PDF goes to `pricelists/`.
  - Tables: `price_lists`, `price_list_rows`, `price_mappings` (map or ignore, by row key), `inquiries`, `proxies`, `proxy_days`.
  - Routes `/admin/pricelists*`, `/admin/price-mappings*`, `/admin/inquiries*`, `/admin/proxies*` and `/worker/*`. `WORKER_API_KEY` is loopback-only and limited to `/worker/*`.
  - Permissions: `pricelist.manage` for admin and super admin; `proxies.manage` for super admin only.
  - Products and orders have per-color variants, from mapped rows only. Phones are sold on list availability. A list older than `PRICELIST_MAX_AGE_HOURS` allows inquiries only.
  - Proxy pool `app/proxypool.py`: ranked by stability; probation → main; retired after N bad days, but never below 3 main proxies; days when no proxy worked are ignored; all-dead alert.
- **shopbots**
  - Color picker: the price shows only after a color is picked. Changing the color announces the new price, re-read from shopapi on each pick.
  - Cart lines are per color (the cart table was migrated). An inquiry button.
  - Owner alerts: pricelist held/failed, all proxies dead, Telegram login required/unreachable, price inquiry.
- **shopadmin**: page «لیست قیمت».
  - Rows tab: mapping dialog, ignore, section/brand filter, search.
  - Lists tab: PDF upload, approve/reject a held list.
  - Proxies tab (super admin only).

### Done — part 2 (this session)
**A. `shoptg/` — new component: Telegram worker, its own venv, Telethon 1.45**
- `app/gateway.py` is the only module that uses Telethon. It is read-only: connect, read public channel messages, download, ping. It never joins, posts or marks messages as read.
- **Fake-TLS (`ee`) proxy support: `app/faketls.py`.**
  - Telethon 1.x throws away the domain of an `ee` secret and cannot use fake-TLS proxies, which are the most common kind in Iran.
  - The new connector does the full handshake: a signed 517-byte ClientHello with SNI, verification of the proxy's HMAC, then obfuscated2 inside TLS records.
  - It is tested against a local fake proxy that checks what mtprotoproxy/mtg check (HMAC, time, SNI) and decrypts the obfuscated2 header (tag `dddddddd`, DC id).
  - `dd` proxies use RandomizedIntermediate; plain proxies use Intermediate.
- **Session security: `app/secure_store.py`.**
  - The StringSession is encrypted with DPAPI **LocalMachine** scope plus app entropy, so the Phase 4 service account can decrypt it on this server only.
  - The file and folder get an NTFS ACL with inheritance removed: SYSTEM + Administrators full control (by SID, so it works on any Windows language), plus `TG_SERVICE_ACCOUNT` read.
  - The file is written atomically.
  - Honest limit: any local administrator can decrypt it. The ACL is what keeps other accounts out.
- **Worker loop: `app/worker.py`.**
  - Price channel every 30 min. PDFs newer than the cursor `tg_price_last_id` go to `/worker/pricelists`. The cursor also moves past images and text posts. On the first run only the newest PDF is sent. If shopapi is down, the cursor is not advanced.
  - Proxy channels weekly: links found in the text, in link entities and in buttons go to `/worker/proxies/candidates`.
  - Health check every 3 min. On a failure it switches at once to the next proxy: the shopapi ranking first, then `TG_PROXY`, then a direct connection (`TG_ALLOW_DIRECT`).
  - Every hour it probes up to 15 other proxies in rotation with an **anonymous** client. The shop session is never used for probes: the same auth key from two IPs risks `AUTH_KEY_DUPLICATED`.
  - Alerts go to `/worker/alerts`: login required (missing or revoked session), unreachable (after 15 min).
  - A status JSON is kept in `tg_status`. Logs show host:port and kind only, never secrets.
- **Scripts**
  - `login.ps1` → `scripts/login.py`: elevated PowerShell only. Phone, code, 2FA password and proxy are all typed into hidden prompts. 3 tries each. Nothing secret is printed.
  - `check_pricelist.ps1` → `scripts/check_pricelist.py`: read-only and works **without shopapi**. It takes the newest PDF of the price channel, parses it with the vendored parser and prints a summary. `-Save` keeps a copy; `-ProxyChannels` counts proxy links.
  - `run.ps1 [-Check]`: the check prints names and yes/no only, never values.
  - `install.ps1`:
    - creates the venv, installing **offline from the bundled wheels** when the server has Python 3.12 x64, otherwise from PyPI;
    - creates `.env` and limits it to SYSTEM and Administrators;
    - creates the data folder `%ProgramData%\ShopServer\shoptg` with the same ACL;
    - `-Dev` is for this PC.
  - `build_package.ps1` builds the zip:
    - app, scripts, ps1 files, guide;
    - `vendor/pricelist` = shopapi's `parser.py` + `pricing.py`;
    - 20 wheels for Python 3.12 x64;
    - an offline-install probe;
    - a check that no `.env`/db/log/session file is inside.
- **SERVER_GUIDE.md**: step-by-step guide for the server — copy, install, `.env` by hand, login, read-only test, troubleshooting.
- **Tests: 47**, using a fake Telethon client and a fake shopapi (httpx MockTransport), no network. They cover:
  - worker failover, direct fallback, probe rotation, cursor rules, weekly collection, alerts, status;
  - fake-TLS;
  - a real DPAPI round trip and the ACL arguments;
  - the config, and parity of proxy-link parsing with shopapi;
  - that real Telethon accepts our client options;
  - the login script (wrong code, 2FA, nothing secret in the output);
  - the check script on the real sample PDF (195 rows) and on a broken PDF.

**B. shopadmin**
- The sidebar test now expects 9 entries, including `pricelist`.
- `tests/test_pricelist.py` (24 tests):
  - helpers, permissions per role, rows/counts/sections/banner, server-side section filter, local search;
  - map (dialog), ignore, clear, cancel;
  - operator read-only; admin without the proxies tab;
  - lists: approve/reject held, upload (active vs held), non-PDF refused;
  - proxies: add, toggle, delete; mapping dialog search/pick/validation; no callback errors on any tab.
- The fake shopapi in `conftest.py` gained the price-list, mapping and proxy endpoints.

**C. Other**
- The WIP commit had committed pytest temp files (`shopapi/pytest-of-Lenovo/…`). They are now untracked, and `pytest-of-*/`, `shoptg/wheels/` and `shoptg/vendor/` are git-ignored.

### Tests
- shopapi **218** ✓. Run it with the regular Python 3.12: `PYTHONPATH=.venv\Lib\site-packages`. The Store-Python venv cannot write temp files from the Claude app.
- shopbots **114** ✓.
- shopadmin **401** ✓ (exit 0; pytest's summary line is lost at Qt teardown in this sandbox).
- shoptg **47** ✓.

### Server package
- `E:\Outputs\ShopTG\shoptg_server_1.0.0_2026-10-12.zip`; SHA-256 is in `E:\Outputs\ShopTG\README_FA.txt`.
- The guide is `shoptg/SERVER_GUIDE.md`, also inside the zip.

### Pending / for the user (the live Telegram day, on the server)
1. Install Python 3.12 x64 for all users. Copy and extract the zip to `C:\ShopServer\`, then run `install.ps1` from an elevated PowerShell.
2. `notepad .env`: type `TG_API_ID`, `TG_API_HASH` and `TG_PROXY` yourself. **Never paste them in chat.**
3. Run `login.ps1` (hidden prompts), then `check_pricelist.ps1 -Save`. Send me the output; it contains no secrets.
- **Not verified live:**
  - fake-TLS against a real proxy (tested only against a local fake proxy built to the protocol);
  - Telethon reading the channel;
  - the format of the real channel posts (document MIME type and file name).
- shopapi is not on the server yet. The worker itself (`run.ps1`) needs shopapi plus `WORKER_API_KEY`, which comes in Phase 4.
- Phase 4 carry-overs:
  - pdfplumber in the ShopSystem PyInstaller build;
  - `--init-config` must generate `WORKER_API_KEY`;
  - the shoptg service with `TG_SERVICE_ACCOUNT` (read grant on the session; no new login needed);
  - shopapi's `/admin/server/status` could show `tg_status`.

### Next step
Phase 4 — services (NSSM or equivalent), install/update/rollback scripts, tray app, alerts and health monitoring (§1, §8).

## Live test session after Phase 2 (2026-10-11) — DONE

No new features, except the deep-link fallback the user approved after the start parameter proved unreliable.

### Live results
**Bale** (`@asr_test_bot`, `shopbots/scripts/check_start_param.py [--formats]`; the token is read from `shopbots/.env`, with `BALE_TOKEN` as a fallback for `BALE_TEST_TOKEN`)
- ✅ A shared contact carries `contact.user_id` (int) and it **equals `from.id`**. The fields are `first_name`, `phone_number`, `user_id`. Contact-only registration works as built.
- ⚠ **The `/start` parameter is unreliable.** First run: a bare `/start`. Then, with the chat deleted and 5 variants opened (`kala_289`, `kala289`, `KALA289`, `289`, `kala%5F289`), 8 `/start` messages arrived. Only 2 carried a parameter: `/start 289` and `/start kala_289`; the other 6 were bare. So Bale *can* pass it, but often doesn't. It is unclear when (first open vs. reopen, app vs. web). Both forms that did arrive are handled.
- → **Fallback (approved), now the main path:** the site shows the product code; the customer sends it to the bot.
  - Accepted forms: `289`, `kala_289`, `kala289`, `kala-289`, `کد 289`, `کد کالا: ۲۸۹`, `#289`. Persian digits work.
  - A code sent before registering is kept and the product is shown right after the contact is shared (`PRODUCT_AFTER_CONTACT`).
  - The welcome and help texts tell customers to send the code.
  - `/start <code>` still works, in case Bale ever passes the parameter.
  - Phone-length numbers are never taken as codes.
  - The site (Phase 6) must print the code next to the "order in Bale" button.

**SQL on `.\SQLEXPRESS` / `hesab5 t`** (`shopapi/scripts/live_db_check_all.ps1` → `live_db_check.py kol|r5|person`)
- Must be run from a normal PowerShell window. Processes started by the Claude app are refused by SQL shared memory ("access denied", error 5). Only shared memory is enabled on the instance; TCP, named pipes and SQL Browser are off.
- **KOL statement ✅**
  - Columns: `Num_kol int`, `Date1 varchar(10)` (`1405/07/19` format), `Va char(1)`, `N_sanad int`, `Bed/Bes money`, `Sharh nvarchar(500)`, `Noa char(1)`, `Codkol int`, `Cod_n int`.
  - Checked on the 3 persons with the most rows (2139/540/366 rows):
    - totals = the reference §3 formula;
    - rows come out oldest first;
    - the newest running balance = the balance, including when truncated to `STATEMENT_MAX_ROWS` (the carried-over opening balance works);
    - no fractional amounts.
  - `Va` codes seen: `8 Z f n t w ^ a r` and a Persian letter. Only `f` has a label; the rest show as «سند».
- **R5 tracking ⚠ partly verified.** The query runs. Ordered quantities are correct and a missing `Codlp` → `None`. But the test DB has only 3 orders and **no invoice with `ordercode`**, so the partial/full invoiced path still needs GUI test G3.
- **create_person ✅**
  - Duplicate check: an existing mobile (also given as `+98…` or with Persian digits) returns `existing=True` with the same code and writes nothing, even with `dry_run=False`.
  - Dry-run leaves no rows.
  - Real create: `Code = MAX+1`, `Gcod=4`, `l_gey=1`, `taf(como=13, codgtaf=59, va=1, Cota=Code)` linked through `codetaf`, `DetailTBL(type 3, Va 0, darfn 1)`. R4 then finds it.
  - No triggers on `name_mo/taf/DetailTBL`.
  - The test person (09990007731) was deleted afterwards and the row counts were restored. Only the IDENTITY counters of `taf`/`DetailTBL` moved on.

### Decisions applied (REQUIREMENTS §3/§4 updated)
- **All money is in Rial**, the same unit as the accounting software. The bot's `currency` is now «ریال», as are ShopAdmin `format_money`, the report column and the filter hint. The editable copy `%ProgramData%\ShopServer\messages.fa.json` must be changed by hand if it still says «تومان».
- **No amount cap for pending customers.** `PENDING_MAX_ORDER_TOTAL` was removed from the API check, config, the remote-editable settings, launcher defaults, ShopAdmin labels and both `.env.example`; old lines in a `.env` are ignored. Only `PENDING_MAX_ORDER_ITEMS` remains.
- Phase 3: distributor PDF price (thousand Toman) ×10,000 = Rial; "نقد + 500,000 Toman" = +5,000,000 Rial.

### Other
- `shopbots/.env.example` was restored (it was deleted in the working tree).
- Tests: shopapi **173** ✓, shopbots **104** ✓ (+3 fallback), shopadmin **377** ✓.

### Pending
- GUI tests G1–G4, especially G3 (invoice an order) to verify R5 end to end.
- Installers were not rebuilt; `E:\Outputs` is unchanged.

## Phase 2 — Bale bot (2026-10-11) — DONE

Rollback point: commit `428016f` (Phase 1). Phase 2 is committed on top of it.

### Done
**A. Verification (§3)**
- Bot: registration is **contact-only**. `/start` asks for Bale's share-contact button. A typed number is refused, as is a contact whose `user_id` ≠ `from.id` (or has no `user_id`), and a non-Iranian number. The name comes from the contact, then the Bale profile; there is no name step any more. Conversations left in the old `await_name`/`await_phone` states continue as contact-only.
- shopapi `POST /users/register`: needs a real mobile (422 otherwise; stored as `09…`). R4 then gives exactly one person not linked to another customer → **approved at once** (`customer_auto_approved` event, no staff alert). Otherwise the customer is pending (`customer_registered` → Bale alert to the owner as before). Accounting down = pending, never an error. A pending customer who shares again is re-matched (covers in-store customers entered later).
- `POST /admin/users/{id}/approve`: `person_code` is optional. Without it, `create_person` (§5.1) runs with `first_name`/`last_name` from the request. If the mobile already exists, the customer is linked to that person; a mobile shared by 2+ persons → 409. **Dry-run → 409 "Accounting writes are disabled; the person was not created"** (nothing is faked).
- ShopAdmin approve dialog: "link to existing person" (with the mobile suggestion) / "**create new person**". The name fields are pre-filled from the Bale name with emoji/symbols stripped and are editable; letters/space/ZWNJ/hyphen only, ≤ 50 chars, last name required. Create mode is chosen automatically when nobody matches.
- Pending customers may order within `PENDING_MAX_ORDER_TOTAL` (default 50,000,000, accounting price unit) and `PENDING_MAX_ORDER_ITEMS` (default 3). Both count their other open orders; 0 items = may not order. Approve-payment of a pending customer's order → 409 until the customer is approved. Rejected customers cannot order. The statement needs an approved, linked customer.

**B. Catalog / deep link**
- Price level 3 (`gey3`) for the bot: config default was already 3. Now also in `shopsystem/.env.example` and the launcher's first-run defaults (they said 1). `shopapi/.env.example` stays 1 for the dev copy (only level 1 has a catalogue there).
- `GET /products/{code}` (also out of stock; 404 if price ≤ 0). Bot: `/start kala_289` opens the product. An unregistered user gets it right after registering. Fallbacks: sending `kala_289` or a bare code (Persian digits OK).

**C. Receipts**
- Photo **or** image document (JPEG/PNG by MIME or file name), ≤ `RECEIPT_MAX_BYTES` (5 MB). The size is checked from the message, then from `getFile`, then while streaming, so an oversized file is never held in memory. The bytes must start with a JPEG/PNG signature, checked in both the bot and shopapi.
- The bot uploads the image base64 in `POST /orders/{id}/receipt` (`data_b64`). shopapi stores it as `receipts/order<id>_<time>_<rand>.<ext>` next to the SQLite file (`RECEIPTS_DIR`); there are no customer data in file names. The `receipts/` folder is git-ignored.
- `GET /admin/orders/{id}/receipt` (view permission; path-traversal safe). ShopAdmin order dialog: "نمایش تصویر رسید".
- Per-customer receipt limit: `RECEIPT_RATE_COUNT=5` per `RECEIPT_RATE_WINDOW=600` s (on top of the general message limiter).

**D. Tracking**
- New `orders` columns (added by an `ALTER TABLE` migration at startup): `invoice_state` (partial/full), `invoiced_qty`, `invoiced_at`, `shipped_at`. `payments` gets `file_name`, `content_type`, `created_at`.
- `tracking.sync_invoices`: R5 over written orders → `order_partially_invoiced` / `order_invoiced` events (once each). It runs in the API lifespan every `INVOICE_SYNC_SECONDS` (300; 0 = off) and on demand via `POST /admin/orders/sync-invoices`. An order deleted in accounting is skipped (not yet shown anywhere).
- `POST /admin/orders/{id}/ship` (new permission `orders.ship`: operator/admin/super) → `order_shipped`. ShopAdmin: "ثبت ارسال" button + "پیگیری" row.
- The bot tells the customer once per event: payment approved/rejected → invoiced (partial/full) → shipped. If the bot has no record of the chat, it is found via the new `GET /admin/users/{id}` and `user_id` in `OrderOut`. "My orders" shows the furthest step.

**E. Statement**
- `GET /users/{platform}/{chat_id}/statement?page=&page_size=`: bot/service key only (site key → 403); approved and linked customers only. KOL rows use the same filter as the verified balance formula, newest first, with a running balance (debtor/creditor/settled). At most `STATEMENT_MAX_ROWS` (2000) rows are read; older rows are carried as the opening balance. `Va='f'` → "فاکتور فروش", other codes → "سند". The description is cut to 60 chars.
- Bot: "📒 گردش حساب" in the menu (approved customers only), paginated (`STATEMENT_PAGE_SIZE=8`).
- Grant: `KOL (…, Num_kol, Date1, N_sanad, Sharh)` added to `sql/create_api_user.sql`; 2 probes added to `verify_permissions.sql`. KOL column names come from the reference/snapshot tool; **not checked live** (see Pending).

**F. Closed mode**
- `shop_state` table; `GET /shop/state` (any channel key), `GET/PUT /admin/shop/state` (new permission `shop.state`: admin/super) + audit + `shop_closed`/`shop_opened` events.
- Bot (state cached 60 s): orders are still accepted; the checkout message adds "🔒 … reviewed when the shop reopens". ShopAdmin dashboard: "وضعیت فروشگاه" panel with an open/close button (with confirmation).

**G. Texts / settings**
- New Persian texts in `messages.fa.json`; the layout is kept. Removed: `ASK_NAME`, `ASK_PHONE*`, `PHONE_INVALID`, `NAME_INVALID`. Operator copies in `%ProgramData%` fall back to the new defaults automatically.
- Remote-editable settings (+ ShopAdmin labels): `PENDING_MAX_ORDER_TOTAL`, `PENDING_MAX_ORDER_ITEMS`, `INVOICE_SYNC_SECONDS`.
- Small fix: the bot's admin `/order <id>` command used the bot key without an owner, so it always got 404. It now uses the service key.

**H. Tests** (fake DB / Bot API, no network)
- shopapi **173 passed** (was 145): `tests/test_phase2.py` (28).
- shopbots **101 passed** (was 80): contact-only flow rewritten in `test_customer_flow.py`, plus `test_phase2.py` (12) and core tests.
- shopadmin **377 passed** (was 364): `tests/test_phase2.py` (13).
- Run with `--basetemp .pytest_tmp` (git-ignored) in this sandbox.

### Bale start parameter — NOT tested live
No Bale **test** token is configured: no `shopbots/.env`, no `BALE_TEST_TOKEN`. The only token is in the running ShopServer's `%ProgramData%` config. It is not a designated test bot, and a second poller would steal its updates, so it was not used. Ready to run: `shopbots/scripts/check_start_param.py`. Set `BALE_TEST_TOKEN` for a separate test bot; the script prints `https://ble.ir/<bot>?start=kala_289` and reports what `/start` text arrives (the token is never printed). The link format itself is part of what it checks. Until then, the typed-code fallback covers a lost parameter.

### Decisions
- Name from the contact (no name step). Pending customers may order within limits (user-approved defaults).
- Orders of pending customers wait in our SQLite; they are written to accounting only after customer approval + payment approval (unchanged write moment: approve-payment).
- "Registered" = the checkout confirmation. Tracking statuses live in extra columns, not in the `orders.status` CHECK (SQLite cannot alter it).
- Receipt image travels as base64 JSON (`python-multipart` is not installed; 5 MB → ~6.7 MB request, local only).

### Pending / for the user
- ~~Live checks on `hesab5 t`~~ → done in the live test session above.
- ~~Bale start-parameter / contact `user_id`~~ → see the live test session above. Still open: `getFile` `file_size`; document MIME types.
- ~~Price unit of `PENDING_MAX_ORDER_TOTAL`~~ → the setting was removed; all money is in Rial.
- Orders deleted in accounting (cancelled there) are not surfaced yet.
- Installers/ShopSystem were not rebuilt; `E:\Outputs` unchanged.

### Next step
Phase 3 — Telegram worker: Telethon login, MTProto proxy pool (§6), distributor PDF parser + mapping UI + phone pricing (§4–5).

## Phase 1 — bug fixes, Telegram removal, shared core (2026-10-11) — DONE

Rollback point: commit `6f7eca5` ("Checkpoint before Phase 1"). Phase 1 was committed as `428016f`.

### Done
**A. Bug fixes (REQUIREMENTS §11, reference §9/§11) — shopapi**
- Mobile lookup → recipe R4: `DetailTBL` types 1 and 3, last 10 ASCII digits (`text.mobile_key`; accepts 09…, +98…, 0098…, Persian digits). `name_mo.mobile` is no longer read. Returns the code only (`masked_name` is now always `null`: the least-privilege user cannot read names). A number shared by 2+ persons = no match → manual approval.
- `ACCOUNTING_STATUS_CODE` default `6808` → `0` (`config.py`, `shopapi/.env.example`, `shopsystem/.env.example`, launcher first-run defaults).
- Writer: `UPDLOCK,HOLDLOCK` → `sp_getapplock 'shop:KalaOrder'` (transaction owner, 15s). It is taken before the idempotency check. A lock failure raises `AccountingLockTimeout` and rolls back. Header columns now follow §5.2 (`Taf2` no longer written, `keraye=0` added). `Mablp` = Σ(qty×price), not rounded.
- **New `AccountingWriter.create_person`** (§5.1, dry-run by default, not called by any endpoint yet). Under `sp_getapplock 'shop:name_mo'` it first runs R4 inside the same transaction. If the mobile already exists, it **links to that person instead of creating a duplicate** (`existing=True`, `ambiguous` if shared). The accounting UI forbids duplicate phones, but the DB has no unique constraint.
- Reservation → recipe R2: only `va=0` orders, invoices matched per line (`ordercode`+`orderdetailcode`+`Codekala`), clamped per line. Groups: `Code > 0`.
- `sql/create_api_user.sql` replaced with the least-privilege script (from `research_tools/recipes/grant_shopbot_2008r2.sql`), plus column SELECT on `KOL(Noa,Codkol,Bed,Bes,Va,Cod_n)` and DENY on KOL writes. `sql/verify_permissions.sql` now lists all column grants plus 14 `HAS_PERMS_BY_NAME` probes. **Not run on any DB.**

**B. Old Telegram Bot-API code removed (REQUIREMENTS §2)**
- shopbots: `platforms/telegram.py`, `TELEGRAM_TOKEN/TELEGRAM_API_BASE/TELEGRAM_PROXY/PROXY_URL`, `describe_proxy`/`proxy_for`, `socksio`. `ADMIN_CHAT_IDS` accepts `bale:<id>` or a bare id; leftover `telegram:` entries are ignored.
- shopapi `control.EDITABLE`: Telegram token/proxy keys removed (now refused as unknown). Chat-id validator is Bale-only.
- shopsystem launcher (status, setup fields, logs), `build_exe.bat` (`socksio`, script copies), README/NOTES.
- shopadmin: server-settings labels, setup-wizard Telegram token and proxy fields.
- Root `scripts/set_telegram_token.ps1` and `scripts/test_telegram_proxy.ps1` deleted.

**C. Shared core — `shopbots/app/core/`**
- `catalog.py` (groups, product pages, search normalization ی/ي ک/ك + digits), `cart.py` (limits, totals, order payload), `orders.py` (checkout, receipt outcomes, order list), `customers.py` (status, name/phone validation, registration).
- `engine.py` now only routes, holds conversation state and renders texts and keyboards. Adding a channel = one adapter in `app/platforms/`. No behaviour change.

**D. Tests** (unit tests, fake DB/Bot API; no real SQL or network)
- shopapi **145 passed** (was 120): new `tests/test_person_and_reservation.py`, applock/person tests in `test_writer.py`.
- shopbots **80 passed**: `test_telegram_shop.py` → `test_shop_features.py` (Bale; the proxy tests were dropped), new `test_core.py`.
- shopadmin **364 passed** (offscreen).
- Run note: in this sandbox, shopbots/shopadmin need `--basetemp <writable dir>` (the default pytest temp folder is not writable here).

### Decisions
- `'telegram'` stays a valid platform value in shopapi (SQLite CHECK + schema) and in the shopadmin labels: old rows keep displaying, and phase 7 reuses it. No migration.
- `create_person` is built and tested now, but is wired to an endpoint only in Phase 2 (§3 pending-approval flow).
- KOL grant covers only the balance formula's columns. Phase 2 must add the date/description columns for the paginated statement once they are confirmed on the test DB.

### Pending / for the user
- **Local `.env` files are not touched by design.** `shopapi/.env` sets `ACCOUNTING_STATUS_CODE` explicitly: change it to `0`. Old `TELEGRAM_*`/`PROXY_URL` lines in any `.env` (including `%ProgramData%\ShopServer\.env`) are now ignored and can be deleted.
- Live check on `hesab5 t` (read-only R4 lookup, dry-run order with applock), then the scripts in `shopapi/sql/` with a DBA.
- `installer`/ShopSystem were not rebuilt, so `E:\Outputs` was not updated.
- Still open from §13/backlog: GUI tests G1–G4 (real `Status`), Bale verification with a real test bot.

### Next step
Phase 2 — Bale bot: contact-only verification (§3, R4 + `create_person` on approval), catalog/search/deep link, price level 3, cart/order, receipts, tracking (R5/R6), statement (KOL), closed mode.

---

## Archive — CLAUDE.md status and backlog as of 2026-10-12 (moved here 2026-10-13)

Historical text, kept verbatim (Persian). The live status is in `CLAUDE.md`.

#### وضعیت (به‌روز 2026-10-12)

- **فاز ۷ (کانال تلگرام) در کد کامل شد (2026-10-12، شاخهٔ `phase7-telegram`؛ جزئیات در `PROGRESS.md`).** ربات تلگرام با Telethon (توکن BotFather) از طریق استخر پراکسی MTProto؛ آداپتر نازک `shopbots/app/platforms/telegram.py` روی همان هستهٔ مشترک، پکیج مشترک `shared/tgproxy` (لینک پراکسی + fake-TLS) برای shoptg و shopbots، خواندن و گزارش سلامت پراکسی از/به shopapi. فقط `TELEGRAM_BOT_TOKEN` جدید است؛ `TG_API_ID/HASH` همان shoptg. اعلان مالک فقط بله (`ADMIN_CHAT_IDS` فقط بله). **روی تلگرام واقعی و بیلد ویندوز آزموده نشده.** تست‌ها (لینوکس): shopbots ۱۶۰ ✓، shopapi ۲۸۱ ✓، shoptg ۴۵ ✓.

- **فاز ۶b انجام شد (2026-10-12)؛ جزئیات در `PROGRESS.md`.** جدول مدل‌های سایت در shopapi (slug ↔ کالاهای حسابداری؛ ردیف‌های لیست قیمت از همان `kala_code`)، تطبیق فازی (`app/fuzzy.py`)، بررسی شبانه (`MODEL_CHECK_HOUR`): تغییر کوچک نام = «drifted» و مدل نمایش داده می‌شود؛ کالای گم‌شده یا شباهت زیر `MODEL_DRIFT_MIN_SCORE` = پنهان + هشدار بله. ربات `m_<slug>`، متن کپی‌شده، slug خالی و نام را با `GET /catalog/resolve` می‌شناسد و هرگز حدس نمی‌زند. صفحهٔ ShopAdmin «مدل‌های سایت» (ورود از `products.js`). **روی `hesab5 t` و بلهٔ واقعی آزموده نشده.** تست‌ها: shopapi ۲۸۱ ✓، shopbots ۱۲۸ ✓، shopadmin ۴۳۴ ✓، shopsystem ۴۹ ✓، shoptg ۴۷ ✓.

- **فاز ۶ (سایت) انجام شد (2026-10-12)؛ جزئیات در `PROGRESS.md`.** سایت زنده = `projects\asr-ertebatat-2-redesign` (شاخهٔ `redesign`، commit `e98eaef`، **push نشده**؛ نسخهٔ منتشرنشدهٔ `asr-ertebatat-shop` هم `1524dc1`+`5258adf`): «کد مدل» دائمی (slug، بدون کد حسابداری/قیمت/موجودی)، دکمهٔ «استعلام قیمت و سفارش در بله» (کپی نام+کد و `start=m_<slug>`)، تلفن پشتیبان، ربات تلگرام پنهان، `tools/check_site.js`، راهنمای `DEPLOY_ARVAN_FA.md`. zip سایت زنده در `E:\Outputs\StoreWebsite-Redesign\`. تصمیم جدید: نگاشت slug ↔ کالای حسابداری با پیشنهاد فازی + بررسی شبانه = **فاز ۶b** (REQUIREMENTS §9a)، انجام شد. shopbots ۱۲۰ ✓.

- **فاز ۵ در کد کامل شد (2026-10-12)؛ جزئیات در `PROGRESS.md`، مدل تهدید در `SECURITY.md`.** پشتیبان روزانه (`shopsystem/backup.py`، رشتهٔ سرپرست، ساعت ۳): zip کامل محلی + آزمون بازگردانی خودکار + نسخهٔ بیرون از سرور **فقط رمزگذاری‌شده** (AES-256-GCM، عبارت عبور در `.env` و روی کاغذ مالک؛ `--set-backup-passphrase`)؛ نشست تلگرام هرگز پشتیبان نمی‌شود. `deploy/restore.ps1` با برگشت خودکار. هشدار فعالیت مشکوک (`shopapi/app/security_watch.py` + `POST /security/report` از ربات)، فیلتر حذف اسرار از لاگ، رد `sa`، `deploy/firewall_sql.ps1` (اجرا نشده). نسخه ۲٫۲٫۰. **هیچ‌چیز روی سرور فروشگاه نصب/اعمال نشده.** تست‌ها: shopapi ۲۴۵ ✓، shopbots ۱۱۹ ✓، shopadmin ۴۱۹ ✓، shoptg ۴۷ ✓، shopsystem ۴۹ ✓.

- **فاز ۴ در کد کامل شد (2026-10-12)؛ جزئیات در `PROGRESS.md`.** سرور = سرویس ویندوز `ShopServer` با حساب مجازی `NT SERVICE\ShopServer` (pywin32؛ جای Scheduled Task قدیمی را می‌گیرد و آن را حذف می‌کند)؛ سرپرست، سرور+ربات و (با `SHOPTG_DIR`) کارگر تلگرام را جدا اجرا/بازراه‌اندازی می‌کند. اسکریپت‌ها: `shopsystem/deploy/{install,update,uninstall}.ps1` (update با پشتیبان و برگشت خودکار)، بسته با `shopsystem/build_package.ps1`. پایش سلامت `shopapi/app/monitor.py` (SQL/ربات/بله/تلگرام → پیام مستقیم بله + اعلان ShopAdmin). ShopAdmin: `--tray`، اجرای خودکار با ورود ویندوز، یادآوری با باز شدن «سازه حساب». دیوار آتش: LocalSubnet یا `FIREWALL_ALLOWED_IPS`. **سرویس روی هیچ رایانه‌ای نصب/آزمون زنده نشده.** نسخه ۲٫۱٫۰. تست‌ها: shopapi ۲۳۰ ✓، shopbots ۱۱۴ ✓، shopadmin ۴۱۶ ✓، shoptg ۴۷ ✓، shopsystem ۲۳ ✓.

- **فاز ۳ در کد کامل شد (2026-10-12)؛ جزئیات در `PROGRESS.md`.** جزء جدید `shoptg/` (کارگر تلگرام با Telethon، venv جدا): کانال قیمت هر ۳۰ دقیقه → `/worker/pricelists`، جمع‌آوری هفتگی پراکسی، health check و failover، پشتیبانی fake-TLS (`ee`) که Telethon ندارد، نشست با DPAPI LocalMachine + ACL. بستهٔ سرور: `E:\Outputs\ShopTG\` + `shoptg/SERVER_GUIDE.md`. **ورود تلگرام و تست زنده هنوز انجام نشده** (فقط روی سرور فروشگاه، توسط کاربر). تست‌ها: shopapi ۲۱۸ ✓، shopbots ۱۱۴ ✓، shopadmin ۴۰۱ ✓، shoptg ۴۷ ✓.

- **جلسهٔ آزمون زنده بعد از فاز ۲ (2026-10-11)؛ جزئیات در `PROGRESS.md`.** بله: `contact.user_id` هست و با `from.id` برابر است ✓؛ **پارامتر start نامطمئن است** (۲ از ۸ بار رسید: `kala_289` و `289`) ← fallback: مشتری کد کالا را می‌فرستد (پیش از ثبت‌نام هم نگه داشته می‌شود). SQL روی `hesab5 t`: گردش KOL ✓، `create_person` + بررسی تکراری ✓ (دادهٔ آزمون پاک شد)، R5 فقط بخش بدون فاکتور (فاکتور با `ordercode` در DB تست نیست ← G3). همهٔ مبالغ **ریال**؛ سقف مبلغ مشتری تأییدنشده حذف شد (فقط سقف تعداد). اسکریپت SQL را فقط از PowerShell معمولی اجرا کنید (پروسه‌های اپ Claude را shared memory رد می‌کند). تست‌ها: shopapi ۱۷۳ ✓، shopbots ۱۰۴ ✓، shopadmin ۳۷۷ ✓.

- **فاز ۲ از `REQUIREMENTS.md` انجام و commit شد (2026-10-11)؛ جزئیات در `PROGRESS.md`.** ثبت‌نام فقط با دکمهٔ اشتراک شماره + تطبیق خودکار R4، ساخت شخص با نام ویرایش‌شده در ShopAdmin، سفارش محدود مشتری تأییدنشده، لینک عمیق `kala_<code>`، رسید عکس/فایل ≤۵MB با ذخیره روی سرور، پیگیری فاکتور/ارسال، گردش حساب از KOL، حالت تعطیل. تست‌ها: shopapi ۱۷۳ ✓، shopbots ۱۰۱ ✓، shopadmin ۳۷۷ ✓. **پارامتر start بله و ستون‌های KOL زنده بررسی نشده‌اند** (توکن تست نیست؛ SQL از این جلسه در دسترس نبود).

- **فاز ۱ از `REQUIREMENTS.md` انجام شد (2026-10-11)؛ جزئیات و کارهای بعدی در `PROGRESS.md`.** تلگرام Bot-API حذف شد (فقط بله)؛ هستهٔ مشترک `shopbots/app/core/`؛ R4/R2/`sp_getapplock`/`Status=0`/`create_person` بدون شخص تکراری. تست‌ها: shopapi ۱۴۵ ✓، shopbots ۸۰ ✓، shopadmin ۳۶۴ ✓. هنوز commit نشده (نقطهٔ بازگشت `6f7eca5`).

- تست‌ها: shopapi ۱۰۹ ✓، shopbots ۷۷ ✓، shopadmin ۳۶۴ ✓ (2026-10-07، بعد از کار تلگرام).
- **کلاینت هرگز سرور را اجرا نمی‌کند** (باگ Sandbox «ShopSystem.exe not found»): `child_process.py`/`jobobject.py` حذف؛ `services/connection.py` فقط `/health` را پروب می‌کند و در قطعی «سرور در دسترس نیست» + نشانی + «تلاش دوباره» نشان می‌دهد. بیلد کلاینت جدا (`build_shopadmin.py --variant client` → `dist/client`، بدون `server_setup`، بررسی خودکار صفر ارجاع به ShopSystem حتی داخل PYZ). باگ `build_installer.bat` (کپی قدیمی اسکریپت بعد از `:fail`) رفع شد.
- **متن سفید روی زمینهٔ روشن** (دکمهٔ «ادامه» و OK دیالوگ‌ها) در سورس از 7bcabe8 رفع شده بود؛ installerهای قبلی قدیمی بودند. `contrast_audit.py` حالا دکمه‌های واقعی رندرشده (ویزاردها، ورود، MessageDialog/ConfirmDialog/QMessageBox روی هر پنجره) را اندازه می‌گیرد: ۹۵/۹۵ AA؛ قاعدهٔ قدیمی را ۱٫۰۶:۱ تشخیص می‌دهد.
- هر دو installer در 2026-10-07 ۱۰:۵۰ از نو ساخته شدند (`ShopAdminSetup.exe` ۳۳MB، `ShopServerSetup.exe` ۵۱MB)؛ ShopSystem/سرور دست نخورد، `ACCOUNTING_WRITE_ENABLED=false`. نصب آزمایشی دوباره در Sandbox لازم است.
- **ثبت در حسابداری:** خاموش (`ACCOUNTING_WRITE_ENABLED=false`)؛ کد وضعیت `6808` در `TabaghehBandi` تأیید نشده — باید DBA در production تأیید کند.
- **نشت `.env`:** راه بسته شد (`build_installer.bat` بعد از کپی، `.env`/`*.db`/`*.log` را از staging پاک می‌کند و اگر چیزی ماند متوقف می‌شود؛ `.iss` هم `Excludes` دارد). `ShopAdminSetup.exe` در 2026-10-07 از نو ساخته شد (نسخهٔ آلودهٔ 2026-10-05 جایگزین شد؛ اگر کپی‌ای از آن جای دیگری هست، دور بریز).
- `.env` کنار `shopsystem/dist/ShopSystem/ShopSystem.exe` (تنظیمات تست توسعه‌دهنده) عمداً آنجا می‌ماند و rebuild حفظش می‌کند؛ فقط نباید وارد installer شود.

#### کارهای پیش رو (backlog)

##### ۰. دستورات جدید کاربر
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

##### ۱. سروسامان (مرحلهٔ ۱ — انجام شد 2026-10-07)
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

##### ۲. مرحلهٔ ۲ — معماری نهایی (تصمیم کاربر 2026-10-07)
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

##### ۲-قدیم. نصب‌کننده (از `shopadmin/CLAUDE.md`)
- [x] exclude کردن `.env`, `app.log`, `*.db` از staging (بیلد مجدد = بند آخر مرحلهٔ ۱).
- [ ] پوشهٔ دادهٔ ShopSystem: launcher آرگومان/متغیر پوشهٔ داده بگیرد (مثلاً `%LOCALAPPDATA%\ShopAdmin\service`) تا نصب در Program Files مشکل مجوز نداشته باشد.
- [ ] ساخت `.env` سرویس هنگام نصب/اجرای اول (کلیدهای تصادفی قوی، DB_SERVER/DB_NAME + تست اتصال، توکن بات‌ها، `ADMIN_CHAT_IDS`, `BANK_ACCOUNT_TEXT`).
- [ ] تمیزکاری `.iss`: حذف CustomMessageهای سرویس ویندوز بی‌استفاده؛ بستن ShopAdmin/ShopSystem در حال اجرا هنگام آپدیت؛ چک پیش‌نیاز ODBC Driver 17/SQL.
- [ ] نصب‌کنندهٔ جدا «فقط کلاینت» و «فقط سرور».
- [x] تضمین بیلد تازهٔ ShopSystem پیش از installer ← `build_all.bat`.

##### ۳. باز از shopapi / shopbots
- [ ] راستی‌آزمایی بله با ربات واقعی (`tapi.bale.ai`، long-poll، inline keyboard، request_contact، getFile، …).
- [ ] کلید ایدمپوتنسی برای `POST /orders`.
- [ ] (اختیاری) اعتبارسنجی platform↔نقش کلید؛ credential هر مشتری برای خواندن پروفایل/سفارش؛ redact دلیل رد در audit_log؛ بازبینی grant `TabaghehBandi`.
- [ ] تست استقرار چندکاره (ShopAdmin روی PC دیگر با آدرس راه دور).
- [ ] اتصال سایت به shopapi (سمت سرور، با `SITE_API_KEY`) — فیچر آینده.
- [ ] پیش از production: کاربر `shopbot` با `sql/create_api_user.sql`، تأیید `6808`، امضای دیجیتال installer.

##### ۴. تصمیم‌های باز (از کاربر پرسیده شده)
- [ ] فقط برای «عصر ارتباطات ۲» یا فروش به فروشگاه‌های دیگر؟
- [ ] یک PC یا سرور + چند کلاینت؟
- [ ] سرویس فقط هم‌زمان با ShopAdmin، یا همیشه روشن (پیشنهاد: Scheduled Task هنگام بوت) تا ربات‌ها ۲۴ ساعته جواب دهند؟


