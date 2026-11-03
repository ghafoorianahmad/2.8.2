"""v2.18.0: the mini app and the form go out with «انتشار», and never with a price or Google Fonts."""
from __future__ import annotations

import json
import re

from app.site import publish


def test_the_package_is_complete():
    files = publish.miniapp_files()
    for name in ("app/index.html", "app/form/index.html", "app/form/validators.js",
                 "app/shop-info.json", "app/fonts/Vazirmatn-Regular.ttf",
                 "app/fonts/Vazirmatn-Bold.ttf"):
        assert name in files, name
    assert any(n.startswith("app/assets/index-") and n.endswith(".js") for n in files)
    assert not any("aistudio" in n for n in files)


def test_no_google_fonts_and_the_sdks_stay():
    files = publish.miniapp_files()
    for name in ("app/index.html", "app/form/index.html"):
        html = files[name].decode("utf-8")
        assert "fonts.googleapis" not in html and "fonts.gstatic" not in html, name
        assert "tapi.bale.ai/miniapp.js" in html and "telegram-web-app.js" in html, name
    assert "@font-face" in files["app/index.html"].decode("utf-8")


def test_the_form_is_the_shops_own():
    html = publish.miniapp_files()["app/form/index.html"].decode("utf-8")
    assert "عصر ارتباطات ۲" in html and "فروشگاه موبایل نوا" not in html
    for demo in ("download_zip", "json_output", "preset_valid", "id=\"docs-section\""):
        assert demo not in html, demo
    assert "sendData" in html and "parsePrefillParams" in html


def test_no_price_field_in_the_shop_data():
    data = json.loads(publish.miniapp_files()["app/products.json"].decode("utf-8"))
    text = json.dumps(data, ensure_ascii=False)
    assert not re.search(r'"(price|unit_price|price_rial)"', text)


def _store_and_publisher(tmp_path):
    from app.site.store import SiteStore

    class Publisher:
        sent = None

        def publish(self, files, message):
            Publisher.sent = files
            return {"commit": "abc", "written": len(files), "previous": {}}

        def start_deploy(self):
            return True, ""

        def read_file(self, _path):
            return b"asr-site-look"

    return SiteStore(tmp_path), Publisher()


def test_publish_sends_the_app_with_the_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(publish.cat, "validate_catalog", lambda *a: [])
    store, publisher = _store_and_publisher(tmp_path)
    assert publish.publish(store, publisher, generator="test")["commit"] == "abc"
    sent = publisher.sent
    assert "assets/catalog/catalog.json" in sent and "app/index.html" in sent
    assert "app/form/index.html" in sent
    # nothing of the site's own pages goes with it: the live look stays as it is
    assert not [p for p in sent if p.endswith(".html") and not p.startswith("app/")]
    assert not [p for p in sent if p.endswith(("site.css", "theme.css", "site.js"))]
