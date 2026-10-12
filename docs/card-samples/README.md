# Bot image cards — samples (fake data only)

Rendered by `shopbots/scripts/render_card_samples.py` (Pillow + arabic-reshaper + python-bidi, Vazirmatn).
Not sent anywhere; `BOT_IMAGE_CARDS` is off by default.

| File | Card |
| --- | --- |
| `price-card.png` | Price card (first colour pick of a product view) — in stock |
| `price-card-out-of-stock.png` | Same card, out of stock, very long mixed Persian/Latin name (shrinks to fit) |
| `pre-invoice.png` | Pre-invoice sent right after the order is placed (card number is a placeholder) |
| `final-invoice.png` | Invoice sent on the `order_invoiced` event |
