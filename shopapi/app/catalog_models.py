"""Site catalog models: permanent slug -> accounting products (REQUIREMENTS §9a).

* The site shows models (``iphone-17-pro``); the shop sells accounting products
  (``Kala``, one per storage/color). The owner maps each model once, from fuzzy
  suggestions. Price-list rows reach a model through the same ``kala_code``.
* **Nightly check** (``MODEL_CHECK_HOUR``) of every mapped product:
  - unchanged name -> ok;
  - small change (still ``similarity >= MODEL_DRIFT_MIN_SCORE``, e.g. a color or
    spacing added) -> item "drifted", the model **stays visible**, no alert; the
    owner accepts the new name in ShopAdmin;
  - product gone/inactive, or the name changed beyond the threshold -> item
    "missing", candidates searched by the confirmed name, the model is **hidden**
    and the owner gets one Bale message (newly hidden models only).
  Never re-maps on its own; a failed accounting read changes nothing.
* **Resolve** what the site sends to the bot: ``m_<slug>``, «name + کد مدل: slug»,
  a bare slug, or (edited text) a fuzzy name. Hidden/unmapped models are
  "unavailable" - their products are never returned.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Callable, Optional

from . import fuzzy, owner_alerts
from .db_own import OwnDB
from .text import normalize_fa
from .util import now_iso

logger = logging.getLogger(__name__)

#: Same rule as the site (``site.js`` SLUG_RE / SLUG_MAX).
SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SLUG_MAX = 62
_SLUG_IN_TEXT = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+|[a-z][a-z0-9]*")
_CODE_LABEL = re.compile(r"کد\s*مدل\s*[:：]?\s*", re.IGNORECASE)
_DEEP = re.compile(r"^\s*(?:/start\s+)?m_([A-Za-z0-9-]{1,62})\s*$")

LAST_RUN_KEY = "catalog_check:last_date"
LAST_SUMMARY_KEY = "catalog_check:last"
#: Gap between the best and second-best model for a fuzzy "found".
RESOLVE_GAP = 0.12
MAX_CANDIDATES = 5


def valid_slug(slug: str | None) -> bool:
    return isinstance(slug, str) and len(slug) <= SLUG_MAX and bool(SLUG_RE.match(slug))


def split_aliases(raw: str | None) -> list[str]:
    """Aliases are stored one per line (, ، and ; also separate when typed)."""
    return [a.strip() for a in re.split(r"[\n,،;]", raw or "") if a.strip()]


def join_aliases(aliases: list[str]) -> str:
    seen: dict[str, str] = {}
    for alias in aliases:
        alias = " ".join(str(alias).split())
        if alias and fuzzy.light_key(alias) not in seen:
            seen[fuzzy.light_key(alias)] = alias
    return "\n".join(seen.values())


def _status(model: dict) -> str:
    if not model.get("item_count"):
        return "unmapped"
    return "review" if model.get("hidden") else "ok"


class CatalogModelRepo:
    """Tables ``catalog_models`` / ``catalog_model_items`` (under ``db._lock``)."""

    _MODEL_COLS = ("m.id, m.slug, m.name, m.brand, m.aliases, m.hidden, m.hidden_reason, "
                   "m.hidden_at, m.created_at, m.updated_at, m.updated_by, "
                   # v2.9.3: from the live site; phone / accessory; waiting suggestions
                   "m.source, m.kind, m.auto_suggest")
    _COUNTS = ("(SELECT COUNT(*) FROM catalog_model_items i WHERE i.model_id=m.id) AS item_count, "
               "(SELECT COUNT(*) FROM catalog_model_items i WHERE i.model_id=m.id "
               "AND i.state='drifted') AS drifted_count, "
               "(SELECT COUNT(*) FROM catalog_model_items i WHERE i.model_id=m.id "
               "AND i.state='missing') AS missing_count")

    def __init__(self, db: OwnDB):
        self.db = db

    @staticmethod
    def _out(model: dict | None) -> dict | None:
        if model is None:
            return None
        model["hidden"] = bool(model["hidden"])
        model["status"] = _status(model)
        try:
            suggest = json.loads(model.get("auto_suggest") or "[]")
        except ValueError:
            suggest = []
        model["suggestions"] = suggest if isinstance(suggest, list) else []
        return model

    # ---- models ---------------------------------------------------------------
    def list_models(self) -> list[dict]:
        with self.db._lock:
            rows = self.db._fetchall(
                f"SELECT {self._MODEL_COLS}, {self._COUNTS} FROM catalog_models m "
                "ORDER BY m.brand, m.name"
            )
        return [self._out(r) for r in rows]

    def get_model(self, model_id: int) -> dict | None:
        with self.db._lock:
            return self._out(self.db._fetchone(
                f"SELECT {self._MODEL_COLS}, {self._COUNTS} FROM catalog_models m WHERE m.id=?",
                (int(model_id),),
            ))

    def get_by_slug(self, slug: str) -> dict | None:
        with self.db._lock:
            return self._out(self.db._fetchone(
                f"SELECT {self._MODEL_COLS}, {self._COUNTS} FROM catalog_models m WHERE m.slug=?",
                (slug,),
            ))

    def import_models(self, models: list[dict], actor: str) -> dict:
        """Upsert by slug: name/brand follow the site, the site's aliases are added
        to the owner's; mappings are never touched. Slugs missing from the file
        stay (slugs are never reused)."""
        added = updated = unchanged = 0
        with self.db._lock:
            ts = now_iso()
            for m in models:
                row = self.db._fetchone(
                    "SELECT id, name, brand, aliases FROM catalog_models WHERE slug=?",
                    (m["slug"],),
                )
                if row is None:
                    self.db._conn.execute(
                        "INSERT INTO catalog_models (slug, name, brand, aliases, created_at, "
                        "updated_at, updated_by) VALUES (?,?,?,?,?,?,?)",
                        (m["slug"], m["name"], m.get("brand", ""),
                         join_aliases(m.get("aliases") or []), ts, ts, actor),
                    )
                    added += 1
                    continue
                aliases = join_aliases(split_aliases(row["aliases"]) + list(m.get("aliases") or []))
                new = (m["name"], m.get("brand", ""), aliases)
                if (row["name"], row["brand"], row["aliases"]) != new:
                    self.db._conn.execute(
                        "UPDATE catalog_models SET name=?, brand=?, aliases=?, updated_at=?, "
                        "updated_by=? WHERE id=?", (*new, ts, actor, row["id"]),
                    )
                    updated += 1
                else:
                    unchanged += 1
            self.db._commit()
        return {"added": added, "updated": updated, "unchanged": unchanged}

    def update_model(self, model_id: int, actor: str, **fields) -> dict | None:
        allowed = {k: v for k, v in fields.items() if k in ("name", "brand", "aliases")
                   and v is not None}
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            with self.db._lock:
                self.db._conn.execute(
                    f"UPDATE catalog_models SET {sets}, updated_at=?, updated_by=? WHERE id=?",
                    (*allowed.values(), now_iso(), actor, int(model_id)),
                )
                self.db._commit()
        return self.get_model(model_id)

    def set_hidden(self, model_id: int, hidden: bool, reason: str = "", actor: str = "") -> None:
        with self.db._lock:
            self.db._conn.execute(
                "UPDATE catalog_models SET hidden=?, hidden_reason=?, hidden_at=?, "
                "updated_at=?, updated_by=CASE WHEN ?<>'' THEN ? ELSE updated_by END WHERE id=?",
                (1 if hidden else 0, reason if hidden else "", now_iso() if hidden else None,
                 now_iso(), actor, actor, int(model_id)),
            )
            self.db._commit()

    # ---- items ----------------------------------------------------------------
    @staticmethod
    def _item_out(item: dict) -> dict:
        try:
            item["candidates"] = json.loads(item.get("candidates") or "[]")
        except ValueError:
            item["candidates"] = []
        return item

    def items(self, model_id: int) -> list[dict]:
        with self.db._lock:
            rows = self.db._fetchall(
                "SELECT i.*, (SELECT COUNT(*) FROM price_mappings p WHERE p.action='map' "
                "AND p.kala_code=i.kala_code) AS pricelist_rows "
                "FROM catalog_model_items i WHERE i.model_id=? ORDER BY i.sort, i.id",
                (int(model_id),),
            )
        return [self._item_out(r) for r in rows]

    def all_items(self) -> list[dict]:
        with self.db._lock:
            rows = self.db._fetchall("SELECT * FROM catalog_model_items ORDER BY model_id, id")
        return [self._item_out(r) for r in rows]

    def get_item(self, item_id: int) -> dict | None:
        with self.db._lock:
            row = self.db._fetchone("SELECT * FROM catalog_model_items WHERE id=?", (int(item_id),))
        return self._item_out(row) if row else None

    def item_for_code(self, kala_code: int) -> dict | None:
        with self.db._lock:
            return self.db._fetchone(
                "SELECT i.*, m.slug FROM catalog_model_items i JOIN catalog_models m "
                "ON m.id=i.model_id WHERE i.kala_code=?", (int(kala_code),),
            )

    def mapped_codes(self) -> dict[int, str]:
        """kala_code -> slug, for "already mapped elsewhere" hints."""
        with self.db._lock:
            rows = self.db._fetchall(
                "SELECT i.kala_code, m.slug FROM catalog_model_items i "
                "JOIN catalog_models m ON m.id=i.model_id"
            )
        return {int(r["kala_code"]): r["slug"] for r in rows}

    def add_item(self, model_id: int, kala_code: int, name: str, label: str, actor: str) -> dict:
        with self.db._lock:
            ts = now_iso()
            sort = self.db._fetchone(
                "SELECT COALESCE(MAX(sort), 0) + 1 AS s FROM catalog_model_items WHERE model_id=?",
                (int(model_id),),
            )["s"]
            cur = self.db._conn.execute(
                "INSERT INTO catalog_model_items (model_id, kala_code, label, confirmed_name, "
                "current_name, state, score, sort, confirmed_at, confirmed_by, checked_at) "
                "VALUES (?,?,?,?,?,'ok',1.0,?,?,?,?)",
                (int(model_id), int(kala_code), label, name, name, sort, ts, actor, ts),
            )
            self.db._commit()
            return self.get_item(cur.lastrowid)

    def replace_item(self, item_id: int, kala_code: int, name: str, actor: str,
                     label: str | None = None) -> dict:
        """The owner picked a product for this item (a candidate or a new code)."""
        with self.db._lock:
            ts = now_iso()
            self.db._conn.execute(
                "UPDATE catalog_model_items SET kala_code=?, confirmed_name=?, current_name=?, "
                "state='ok', score=1.0, candidates='[]', confirmed_at=?, confirmed_by=?, "
                "checked_at=?, label=COALESCE(?, label) WHERE id=?",
                (int(kala_code), name, name, ts, actor, ts, label, int(item_id)),
            )
            self.db._commit()
        return self.get_item(item_id)

    def set_label(self, item_id: int, label: str) -> dict | None:
        with self.db._lock:
            self.db._conn.execute(
                "UPDATE catalog_model_items SET label=? WHERE id=?", (label, int(item_id))
            )
            self.db._commit()
        return self.get_item(item_id)

    def delete_item(self, item_id: int) -> bool:
        with self.db._lock:
            cur = self.db._conn.execute("DELETE FROM catalog_model_items WHERE id=?", (int(item_id),))
            self.db._commit()
            return cur.rowcount > 0

    def accept_current(self, item_id: int, name: str, actor: str) -> None:
        """The owner accepts the current accounting name of an item."""
        with self.db._lock:
            ts = now_iso()
            self.db._conn.execute(
                "UPDATE catalog_model_items SET confirmed_name=?, current_name=?, state='ok', "
                "score=1.0, candidates='[]', confirmed_at=?, confirmed_by=?, checked_at=? "
                "WHERE id=?", (name, name, ts, actor, ts, int(item_id)),
            )
            self.db._commit()

    def record_check(self, item_id: int, *, state: str, current_name: str, score: float | None,
                     candidates: list[dict]) -> None:
        with self.db._lock:
            self.db._conn.execute(
                "UPDATE catalog_model_items SET state=?, current_name=?, score=?, candidates=?, "
                "checked_at=? WHERE id=?",
                (state, current_name, score, json.dumps(candidates, ensure_ascii=False),
                 now_iso(), int(item_id)),
            )
            self.db._commit()


# ---- nightly check -----------------------------------------------------------------
def classify(confirmed: str, current: Optional[str], min_score: float) -> tuple[str, float | None]:
    """(state, score) of one mapped product: ok / drifted / missing."""
    if current is None:
        return "missing", None
    if fuzzy.light_key(current) == fuzzy.light_key(confirmed):
        return "ok", 1.0
    score = fuzzy.similarity(confirmed, current)
    return ("drifted" if score >= min_score else "missing"), score


def _alert_text(newly_hidden: list[dict]) -> str:
    lines = [f"⚠️ بررسی شبانهٔ مدل‌های سایت: {len(newly_hidden)} مدل تا تأیید شما "
             "از دید مشتری پنهان شد (کالای نگاشته‌شده در حسابداری پیدا نشد یا نامش تغییر کرده):"]
    for m in newly_hidden[:10]:
        lines.append(f"• {m['name']} ({m['slug']})")
    if len(newly_hidden) > 10:
        lines.append(f"• … و {len(newly_hidden) - 10} مدل دیگر")
    lines.append("پیشنهادها و تأیید: ShopAdmin ← «مدل‌های سایت».")
    return "\n".join(lines)


def run_check(db: OwnDB, reader, settings, *, actor: str = "nightly",
              sender: Callable[[str], int] = owner_alerts.send_owner_alert) -> dict:
    """Check every mapped product once. Raises if accounting cannot be read
    (nothing is changed then)."""
    repo = CatalogModelRepo(db)
    items = repo.all_items()
    if not items:
        summary = {"at": now_iso(), "checked": 0, "drifted": 0, "missing": 0,
                   "newly_hidden": [], "alert_sent": 0}
        db.set_state(LAST_SUMMARY_KEY, json.dumps(summary, ensure_ascii=False), actor)
        return summary
    names = reader.product_names()
    if not names:
        raise RuntimeError("accounting returned no products")  # never hide everything on a bad read
    min_score = float(settings.model_drift_min_score)
    mapped = repo.mapped_codes()
    lost_models: dict[int, list[str]] = {}
    drifted = missing = 0
    for item in items:
        current = names.get(int(item["kala_code"]))
        state, score = classify(item["confirmed_name"], current, min_score)
        candidates: list[dict] = []
        if state == "missing":
            missing += 1
            pool = {c: n for c, n in names.items() if c not in mapped}
            candidates = fuzzy.rank(item["confirmed_name"], pool, limit=MAX_CANDIDATES,
                                    min_score=0.5)
            lost_models.setdefault(int(item["model_id"]), []).append(str(item["kala_code"]))
        elif state == "drifted":
            drifted += 1
        repo.record_check(item["id"], state=state, current_name=current or "",
                          score=score, candidates=candidates)

    newly_hidden = []
    for model_id, codes in lost_models.items():
        model = repo.get_model(model_id)
        if model is None:
            continue
        if not model["hidden"]:
            repo.set_hidden(model_id, True, "missing:" + ",".join(codes))
            newly_hidden.append({"id": model_id, "slug": model["slug"], "name": model["name"]})
            db.add_event("model_review", model_id, actor)
    sent = 0
    if newly_hidden:
        db.audit(actor, "catalog_models_hidden",
                 "slugs=" + ",".join(m["slug"] for m in newly_hidden))
        try:
            sent = sender(_alert_text(newly_hidden))
        except Exception as exc:  # noqa: BLE001 - the models are hidden anyway
            logger.warning("catalog check: owner alert failed (%s)", type(exc).__name__)
    summary = {"at": now_iso(), "checked": len(items), "drifted": drifted, "missing": missing,
               "newly_hidden": [m["slug"] for m in newly_hidden], "alert_sent": sent}
    db.set_state(LAST_SUMMARY_KEY, json.dumps(summary, ensure_ascii=False), actor)
    logger.info("catalog check: %s products, %s drifted, %s missing, %s models hidden",
                len(items), drifted, missing, len(newly_hidden))
    return summary


def last_summary(db: OwnDB) -> dict | None:
    raw = db.get_state(LAST_SUMMARY_KEY, "")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def due(db: OwnDB, settings, now: datetime) -> bool:
    hour = int(settings.model_check_hour)
    if hour < 0 or now.hour < hour:
        return False
    return db.get_state(LAST_RUN_KEY, "") != now.date().isoformat()


async def nightly_loop(settings, db_factory, reader_factory, *, poll_seconds: int = 300,
                       clock: Callable[[], datetime] = datetime.now) -> None:
    """Background loop started with the API: one check a day after
    ``MODEL_CHECK_HOUR`` (server local time). Never raises."""
    if int(settings.model_check_hour) < 0:
        return
    while True:
        await asyncio.sleep(poll_seconds)
        try:
            db = db_factory()
            now = clock()
            if not due(db, settings, now):
                continue
            await asyncio.to_thread(run_check, db, reader_factory(), settings)
            db.set_state(LAST_RUN_KEY, now.date().isoformat(), "nightly")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - retried on the next poll
            logger.warning("catalog check failed, will retry (%s)", type(exc).__name__)


# ---- resolve (bot) -------------------------------------------------------------------
def _model_texts(model: dict) -> list[str]:
    out = [model["name"], model["slug"].replace("-", " ")]
    out += split_aliases(model.get("aliases"))
    return out


def extract_slugs(text: str) -> tuple[list[str], bool]:
    """(slug candidates, explicit). ``explicit`` = the text clearly refers to a
    model code (``m_…``, «کد مدل: …» or one bare slug-shaped word)."""
    value = normalize_fa(text)
    deep = _DEEP.match(value)
    if deep:
        return [deep.group(1).lower()], True
    label = _CODE_LABEL.search(value)
    if label:
        found = _SLUG_IN_TEXT.match(value[label.end():].strip().lower())
        return ([found.group(0)] if found else []), True
    bare = value.strip().lower()
    if SLUG_RE.match(bare) and "-" in bare and len(bare) <= SLUG_MAX:
        return [bare], True
    return [], False


def _public_items(repo: CatalogModelRepo, model: dict) -> list[dict]:
    return [{"kala_code": int(i["kala_code"]), "label": i["label"] or i["confirmed_name"]}
            for i in repo.items(model["id"]) if i["state"] != "missing"]


def _model_out(model: dict) -> dict:
    return {"slug": model["slug"], "name": model["name"]}


def resolve(db: OwnDB, text: str, *, min_score: float) -> dict:
    """What a customer sent -> ``{status, explicit, model?, items?, options?}``.

    status: found | ambiguous | unavailable | unknown. Products are returned
    only for a visible, mapped model.
    """
    repo = CatalogModelRepo(db)
    slugs, explicit = extract_slugs(text)

    def found(model: dict) -> dict:
        if model["status"] != "ok":
            return {"status": "unavailable", "explicit": True, "model": _model_out(model)}
        items = _public_items(repo, model)
        if not items:
            return {"status": "unavailable", "explicit": True, "model": _model_out(model)}
        return {"status": "found", "explicit": True, "model": _model_out(model), "items": items}

    for slug in slugs:
        model = repo.get_by_slug(slug)
        if model is not None:
            return found(model)

    # an edited or free text: fuzzy against model names (name lines only)
    query = _CODE_LABEL.split(normalize_fa(text))[0].strip()[:200]
    if not query:
        return {"status": "unknown", "explicit": explicit}
    scored = []
    for model in repo.list_models():
        best = max((fuzzy.similarity(query, t, model_only=True) for t in _model_texts(model)),
                   default=0.0)
        if best >= min_score:
            scored.append((best, model))
    scored.sort(key=lambda s: (-s[0], s[1]["name"]))
    if not scored:
        return {"status": "unknown", "explicit": explicit}
    top_score, top = scored[0]
    close = [m for s, m in scored if top_score - s < RESOLVE_GAP]
    if len(close) == 1:
        return found(top)  # a strong name match counts as a model reference
    return {"status": "ambiguous", "explicit": explicit,
            "options": [_model_out(m) for m in close[:3]]}
