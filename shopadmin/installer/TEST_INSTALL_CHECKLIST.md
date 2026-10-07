# چک‌لیست نصب آزمایشی ShopServerSetup.exe (PC تست، نه سرور اصلی)

1. پیش‌نیاز: ویندوز تمیز/VM، حساب Administrator، ODBC Driver 17 یا 18، SQL Server Express با نسخهٔ `hesab5 t` (هرگز دیتابیس production). از VM یک snapshot بگیرید.
2. فایل را از `dist\installer\ShopServerSetup.exe` کپی کنید؛ اندازه ≈ ۵۱MB. هشدار SmartScreen طبیعی است (امضا نشده).
3. نصب با Run as administrator؛ پوشهٔ نصب `{Program Files}\ShopServer`. اگر ODBC نباشد باید هشدار بدهد.
4. در پایان ویزارد سرور خودکار باز می‌شود (UAC): آدرس SQL (`.\SQLEXPRESS`)، دیتابیس `[hesab5 t]`، تست اتصال → سبز؛ `ACCOUNTING_WRITE_ENABLED` را false بگذارید.
5. توکن ربات‌ها و `ADMIN_CHAT_IDS` را وارد کنید (یا خالی تا بعداً)، مدیر کل اول را بسازید (گذرواژهٔ قوی).
6. بعد از ویزارد بررسی کنید: `%ProgramData%\ShopServer` ساخته شده؛ `.env`، `*.db`، `tls\` فقط برای SYSTEM و Administrators قابل دسترسی‌اند (`icacls`).
7. `taskschd.msc`: task روی Boot، حساب SYSTEM (یا حساب انتخابی)، RestartOnFailure؛ در `wf.msc` قانون فقط LocalSubnet (profile خصوصی/دامنه).
8. وضعیت: `https://127.0.0.1:<پورت>/health` پاسخ بدهد؛ `ShopSystem.exe --fingerprint` اثرانگشت چاپ کند و با ویزارد یکی باشد.
9. ریبوت: بدون ورود کاربر، سرور باید بالا بیاید (`supervisor.log`)؛ پروسهٔ worker را بکشید → خودکار برگردد.
10. Sanity امنیتی: `.env` در `{app}` وجود ندارد؛ از PC دیگر با آدرس شبکه و بدون کلید، `/admin/*` رد شود؛ کلیدهای سرویس فقط از loopback کار کنند.
11. کلاینت: `ShopAdminSetup.exe` روی PC دوم نصب کنید، آدرس سرور بدهید، اثرانگشت را تأیید کنید، با کاربر مدیر وارد شوید؛ اعلان سفارش/فیش جدید برسد.
12. ربات: یک پیام تست از تلگرام/بله؛ سفارش آزمایشی فقط dry-run ثبت شود (نوار «حالت آزمایشی»).
13. ارتقا: نصب دوباره روی همان نسخه → برنامه‌های در حال اجرا بسته شوند، `.env`/داده در ProgramData دست‌نخورده بماند.
14. حذف: Uninstall → task و قانون فایروال برداشته شوند؛ پوشهٔ دادهٔ ProgramData باید بماند (عمدی).
15. نتیجه و هر خطا را در `shopadmin/NOTES.md` ثبت کنید؛ بعد از آزمون VM را به snapshot برگردانید.
