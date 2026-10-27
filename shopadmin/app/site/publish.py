"""v2.11.0: «انتشار در سایت» and «برگرداندن انتشار قبلی» — the local data
(``SiteStore``) to the site repository (``GitHubPublisher``), no UI here."""
from __future__ import annotations

from . import catalog as cat
from .github import GitHubError, GitHubPublisher
from .store import SiteDataError, SiteStore

CATALOG_PATH = f"{cat.SITE_CATALOG_DIR}/catalog.json"
COMMIT_MESSAGE = "سایت: به‌روزرسانی کاتالوگ از «مدیریت فروشگاه»"
ROLLBACK_MESSAGE = "سایت: برگرداندن انتشار قبلی از «مدیریت فروشگاه»"


def publish(store: SiteStore, publisher: GitHubPublisher, *, generator: str) -> dict:
    """Commit catalog.json + the photos it names. Returns {"commit", "written",
    "deploy_started", "note"}; raises SiteDataError / GitHubError (Persian)."""
    catalog, files = store.build(generator)
    problems = cat.validate_catalog(catalog)
    if problems:
        raise SiteDataError("انتشار انجام نشد: " + "، ".join(problems[:3]))
    before = (store.published() or {}).get("snapshot")
    payload = {path: source.read_bytes() for path, source in files.items()}
    payload[CATALOG_PATH] = cat.catalog_bytes(catalog)
    result = publisher.publish(payload, COMMIT_MESSAGE)
    if not result["commit"]:
        return {"commit": None, "written": 0, "deploy_started": False,
                "note": "همه‌چیز در سایت همین است؛ چیزی فرستاده نشد."}
    store.add_history({"commit": result["commit"], "previous": result["previous"],
                       "snapshot_before": before})
    store.mark_published(catalog, commit=result["commit"])
    started, note = publisher.start_deploy()
    return {"commit": result["commit"], "written": result["written"],
            "deploy_started": started, "note": note}


def rollback(store: SiteStore, publisher: GitHubPublisher) -> dict:
    """Undo the newest publish of the last 48 hours."""
    found = store.last_rollback()
    if found is None:
        raise SiteDataError("انتشاری در ۴۸ ساعت گذشته نیست که برگردانده شود.")
    path, record = found
    commit = publisher.rollback(record.get("previous") or {}, ROLLBACK_MESSAGE)
    store.finish_rollback(path, record, commit)
    started, note = publisher.start_deploy()
    return {"commit": commit, "deploy_started": started, "note": note}


def seed_from_github(store: SiteStore, publisher: GitHubPublisher) -> dict:
    """«خواندن از سایت»: the site repository's catalogue and photos to this
    computer — its catalog.json when the site already uses one, otherwise its
    built-in products.js + site.js. Items already here are kept."""
    published = publisher.read_file(CATALOG_PATH)
    if published:
        return store.seed_from_catalog(
            published, lambda name: publisher.read_file(f"{cat.SITE_CATALOG_DIR}/images/{name}"),
            source="github")
    products = publisher.read_file("assets/products.js")
    if not products:
        raise SiteDataError("در مخزن سایت فایل assets/products.js پیدا نشد.")
    site = publisher.read_file("assets/site.js") or b""
    return store.seed(products.decode("utf-8"), site.decode("utf-8"),
                      lambda name: publisher.read_file(f"assets/products/{name}"),
                      source="github")


__all__ = ["publish", "rollback", "seed_from_github", "GitHubError", "SiteDataError"]
