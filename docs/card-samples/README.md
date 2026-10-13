# Bot image cards — samples (fake data only)

Style reference: `invoice-reference.jpg` (light theme, blue waves, rounded info boxes, dark-blue table header and totals panel).

Rendered by `shopbots/scripts/render_card_samples.py`: HTML/CSS templates (Vazirmatn embedded, Tabler icons inline, MIT)
screenshotted with headless Chromium (`--headless --screenshot`; Microsoft Edge on the Windows server).
Not sent anywhere; `BOT_IMAGE_CARDS` is off by default.

| File | Card |
| --- | --- |
| `price-card.png` | Price card (first colour pick of a product view) — in stock |
| `price-card-out-of-stock.png` | Same card, out of stock, very long mixed Persian/Latin name (wraps to 2 lines) |
| `pre-invoice.png` | Pre-invoice «پیش‌فاکتور» sent right after the order is placed, with payment info (fake card/sheba/owner) |
| `pre-invoice-no-payment.png` | Same, payment info not configured: the payment section is absent |
| `final-invoice.png` | «فاکتور فروش» sent on the `order_invoiced` event (logo, total in words, tracking line, shop footer) |
