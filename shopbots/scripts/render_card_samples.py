"""Render the sample cards (fake data only) into docs/card-samples/.  Run: python scripts/render_card_samples.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import datetime as dt
from app.cards import price_card, pre_invoice_card, final_invoice_card
from pathlib import Path
out=str(Path(__file__).resolve().parents[2]/'docs'/'card-samples')+'/'
shop='عصر ارتباطات ۲'
items=[{"name":"گوشی Samsung Galaxy S25 Ultra 256GB","variant":"مشکی","qty":1,"unit_price":78500000},
 {"name":"کاور شفاف iPhone 17 Pro","qty":2,"unit_price":450000},
 {"name":"شارژر سریع ۶۵ وات Anker","qty":1,"unit_price":1850000}]
total=sum(i['qty']*i['unit_price'] for i in items)
d=dt.date(2026,10,12)
open(out+'price-card.png','wb').write(price_card(shop=shop,name='Apple iPhone 17 Pro Max 512GB',color='نارنجی کیهانی',price=118900000,in_stock=True,date=d))
open(out+'price-card-out-of-stock.png','wb').write(price_card(shop=shop,name='گوشی شیائومی Redmi Note 14 Pro+ 5G ظرفیت ۵۱۲ گیگابایت رم ۱۲',color='سبز',price=24500000,in_stock=False,date=d))
open(out+'pre-invoice.png','wb').write(pre_invoice_card(shop=shop,order_id=1042,items=items,total=total,card_number='6037-0000-1111-2222',card_owner='نام صاحب کارت (نمونه)',bank_name='بانک نمونه',date=d))
open(out+'final-invoice.png','wb').write(final_invoice_card(shop=shop,order_id=1042,items=items,total=total,accounting_no=2673,date=d))
