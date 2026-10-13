"""Render the sample cards (fake data only) into docs/card-samples/.  Run: python scripts/render_card_samples.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import datetime as dt
from app.cards import price_card, pre_invoice_card, final_invoice_card

out = Path(__file__).resolve().parents[2] / 'docs' / 'card-samples'
shop = 'عصر ارتباطات ۲'
items = [{"name": "گوشی Samsung Galaxy S25 Ultra 256GB", "variant": "مشکی", "qty": 1, "unit_price": 78500000},
         {"name": "کاور شفاف iPhone 17 Pro", "qty": 2, "unit_price": 450000},
         {"name": "شارژر سریع ۶۵ وات Anker", "qty": 1, "unit_price": 1850000}]
contact = {'address': 'نشانی نمونه: تهران، خیابان نمونه، پلاک ۱۲', 'phone': '۰۲۱-۱۲۳۴۵۶۷۸', 'bot_id': '@sample_bot', 'thanks': 'از خرید شما سپاسگزاریم.'}
pay = {'card_number': '6037991122223333', 'sheba': 'IR062960000000100324200001', 'owner': 'احمد نمونه'}
total = sum(i['qty'] * i['unit_price'] for i in items)
d = dt.date(2026, 10, 12)
cards = {
    'price-card.png': price_card(shop=shop, name='Apple iPhone 17 Pro Max 512GB', color='نارنجی کیهانی', price=118900000, in_stock=True, date=d),
    'price-card-out-of-stock.png': price_card(shop=shop, name='گوشی شیائومی Redmi Note 14 Pro+ 5G ظرفیت ۵۱۲ گیگابایت رم ۱۲', color='سبز', price=24500000, in_stock=False, date=d),
    'pre-invoice.png': pre_invoice_card(shop=shop, order_id=1042, items=items, total=total, payment=pay, contact=contact, date=d, customer='احمد نمونه'),
    'pre-invoice-no-payment.png': pre_invoice_card(shop=shop, order_id=1042, items=items, total=total, contact=contact, date=d, customer='احمد نمونه'),
    'final-invoice.png': final_invoice_card(shop=shop, order_id=1042, items=items, total=total, invoice_numbers=['2672', '2680'], contact=contact, date=d, customer='احمد نمونه'),
}
for name, png in cards.items():
    if not png:
        sys.exit(f'render failed: {name} (no Chromium/Edge? set BOT_CARD_BROWSER)')
    (out / name).write_bytes(png)
    print('ok', name, len(png))
