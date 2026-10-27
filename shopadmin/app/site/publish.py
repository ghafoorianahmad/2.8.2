"""v2.11.0: «انتشار در سایت» and «برگرداندن انتشار قبلی» — the local data
(``SiteStore``) to the site repository (``GitHubPublisher``), no UI here.

v2.12.0: the look and layout (``assets/catalog/site.json`` + its pictures) go
with the same commit, so one «برگرداندن» undoes both."""
from __future__ import annotations

from . import catalog as cat
from . import look as lk
from .github import GitHubError, GitHubPublisher
from .store import SiteDataError, SiteStore

CATALOG_PATH = f"{cat.SITE_CATALOG_DIR}/catalog.json"
LOOK_PATH = f"{cat.SITE_CATALOG_DIR}/{lk.LOOK_FILE}"
#: a site.js that reads site.json says so in a comment (the site repo's v2.12 code)
LOOK_MARKER = b"asr-site-look"
COMMIT_MESSAGE = "سایت: به‌روزرسانی کاتالوگ و ظاهر از «مدیریت فروشگاه»"
ROLLBACK_MESSAGE = "سایت: برگرداندن انتشار قبلی از «مدیریت فروشگاه»"
OLD_SITE_NOTE = ("توجه: کد سایت در GitHub هنوز «ظاهر و چیدمان» را نمی‌شناسد؛ تا نسخهٔ تازهٔ "
                 "سایت (commitهای محلی) در GitHub نباشد، گوشی‌ها و لوازم جانبی به‌روز می‌شوند "
                 "ولی رنگ، بنر، چیدمان و اطلاعات فروشگاه همان قبلی می‌ماند.")


def publish(store: SiteStore, publisher: GitHubPublisher, *, generator: str) -> dict:
    """Commit catalog.json + site.json + the pictures they name. Returns
    {"commit", "written", "deploy_started", "note"}; raises SiteDataError /
    GitHubError (Persian)."""
    catalog, files = store.build(generator)
    site, look_files = store.build_look(generator)
    problems = cat.validate_catalog(catalog)
    if problems:
        raise SiteDataError("انتشار انجام نشد: " + "، ".join(problems[:3]))
    before = (store.published() or {}).get("snapshot")
    payload = {path: source.read_bytes() for path, source in {**files, **look_files}.items()}
    payload[CATALOG_PATH] = cat.catalog_bytes(catalog)
    payload[LOOK_PATH] = lk.site_json_bytes(site)
    result = publisher.publish(payload, COMMIT_MESSAGE)
    if not result["commit"]:
        return {"commit": None, "written": 0, "deploy_started": False,
                "note": "همه‌چیز در سایت همین است؛ چیزی فرستاده نشد."}
    store.add_history({"commit": result["commit"], "previous": result["previous"],
                       "snapshot_before": before})
    store.mark_published(catalog, commit=result["commit"], site=site)
    started, note = publisher.start_deploy()
    if not site_reads_look(publisher):
        note += "\n\n" + OLD_SITE_NOTE
    return {"commit": result["commit"], "written": result["written"],
            "deploy_started": started, "note": note}


def site_reads_look(publisher: GitHubPublisher) -> bool:
    """Whether the site's own code (assets/site.js on GitHub) reads site.json."""
    try:
        code = publisher.read_file("assets/site.js") or b""
    except GitHubError:
        return True             # unknown: say nothing rather than a wrong warning
    return LOOK_MARKER in code


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
    built-in products.js + site.js. Items already here are kept. v2.12.0: the
    site's look (site.json) too, while nothing was arranged here."""
    store.import_look(publisher.read_file(LOOK_PATH),
                      lambda name: publisher.read_file(f"{cat.SITE_CATALOG_DIR}/look/{name}"))
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


__all__ = ["publish", "rollback", "seed_from_github", "site_reads_look", "GitHubError",
           "SiteDataError"]
