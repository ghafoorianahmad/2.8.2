"""Site catalog models <-> accounting products (REQUIREMENTS §9a).

``/admin/catalog-models*``: signed-in staff (ShopAdmin); changes need
``catalog.manage``. ``/catalog/resolve``: any channel key (the bot), returns
products only for a visible, mapped model.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from .. import catalog_models as cm
from .. import deps, fuzzy
from ..accounting_reader import AccountingReader
from ..config import Settings
from ..db_own import OwnDB
from ..security import Identity, get_catalog_channel, require_permission
from ..staff import P_MODELS_EDIT, P_MODELS_VIEW

router = APIRouter()

CAN_VIEW = Depends(require_permission(P_MODELS_VIEW))
CAN_CATALOG = Depends(require_permission(P_MODELS_EDIT))


# ---- models -----------------------------------------------------------------
class ModelIn(BaseModel):
    slug: str = Field(min_length=1, max_length=cm.SLUG_MAX)
    name: str = Field(min_length=1, max_length=120)
    brand: str = Field(default="", max_length=60)
    aliases: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not cm.valid_slug(value):
            raise ValueError("invalid slug")
        return value

    @field_validator("name", "brand")
    @classmethod
    def _strip(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, value: list[str]) -> list[str]:
        return [" ".join(str(a).split())[:80] for a in value if str(a).strip()]


class ImportIn(BaseModel):
    models: list[ModelIn] = Field(min_length=1, max_length=2000)


class ModelPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    brand: Optional[str] = Field(default=None, max_length=60)
    aliases: Optional[str] = Field(default=None, max_length=1000)


class ItemIn(BaseModel):
    kala_code: int = Field(gt=0)
    label: str = Field(default="", max_length=60)


class ItemPatch(BaseModel):
    kala_code: Optional[int] = Field(default=None, gt=0)
    label: Optional[str] = Field(default=None, max_length=60)


# ---- helpers ----------------------------------------------------------------
def _model_or_404(repo: cm.CatalogModelRepo, model_id: int) -> dict:
    model = repo.get_model(model_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")
    return model


def _item_or_404(repo: cm.CatalogModelRepo, item_id: int) -> dict:
    item = repo.get_item(item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


def _accounting_names(reader: AccountingReader, settings: Settings, codes: list[int]) -> dict:
    found = reader.get_products_for_order(codes, settings.price_level_bot, {})
    return {int(code): (p.get("name") or "").strip() for code, p in found.items()}


def _product_name(reader: AccountingReader, settings: Settings, code: int) -> str:
    name = _accounting_names(reader, settings, [code]).get(int(code))
    if name is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Product not found in accounting (or inactive)")
    return name


def _not_taken(repo: cm.CatalogModelRepo, code: int, item_id: int | None = None) -> None:
    other = repo.item_for_code(code)
    if other is not None and other["id"] != item_id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Product already mapped to model {other['slug']}")


def _detail(repo: cm.CatalogModelRepo, model_id: int) -> dict:
    return {"model": _model_or_404(repo, model_id), "items": repo.items(model_id)}


# ---- staff ------------------------------------------------------------------
@router.get("/admin/catalog-models")
def list_models(db: OwnDB = Depends(deps.get_db), _: Identity = CAN_VIEW) -> dict:
    models = cm.CatalogModelRepo(db).list_models()
    counts = {key: sum(1 for m in models if m["status"] == key)
              for key in ("unmapped", "ok", "review")}
    counts["drifted"] = sum(1 for m in models if m["drifted_count"])
    counts["all"] = len(models)
    return {"models": models, "counts": counts, "last_check": cm.last_summary(db)}


@router.post("/admin/catalog-models/import")
def import_models(payload: ImportIn, db: OwnDB = Depends(deps.get_db),
                  who: Identity = CAN_CATALOG) -> dict:
    """Models from the site's ``products.js`` (parsed by ShopAdmin)."""
    seen: set[str] = set()
    for m in payload.models:
        if m.slug in seen:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate slug {m.slug}")
        seen.add(m.slug)
    result = cm.CatalogModelRepo(db).import_models(
        [m.model_dump() for m in payload.models], who.actor
    )
    db.audit(who.actor, "catalog_models_import",
             f"added={result['added']} updated={result['updated']}")
    return result


@router.post("/admin/catalog-models/check")
def check_now(db: OwnDB = Depends(deps.get_db),
              reader: AccountingReader = Depends(deps.get_reader),
              settings: Settings = Depends(deps.get_settings),
              who: Identity = CAN_CATALOG) -> dict:
    """The nightly check, now (same hide + alert rules)."""
    try:
        return cm.run_check(db, reader, settings, actor=who.actor)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - nothing was changed
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Accounting database unavailable") from None


@router.get("/admin/catalog-models/{model_id}")
def get_model(model_id: int, db: OwnDB = Depends(deps.get_db), _: Identity = CAN_VIEW) -> dict:
    return _detail(cm.CatalogModelRepo(db), model_id)


@router.patch("/admin/catalog-models/{model_id}")
def patch_model(model_id: int, payload: ModelPatch, db: OwnDB = Depends(deps.get_db),
                who: Identity = CAN_CATALOG) -> dict:
    repo = cm.CatalogModelRepo(db)
    _model_or_404(repo, model_id)
    fields = payload.model_dump(exclude_none=True)
    if "name" in fields:
        fields["name"] = " ".join(fields["name"].split())
    if "aliases" in fields:
        fields["aliases"] = cm.join_aliases(cm.split_aliases(fields["aliases"]))
    repo.update_model(model_id, who.actor, **fields)
    db.audit(who.actor, "catalog_model_edit", f"model id={model_id}")
    return _detail(repo, model_id)


@router.get("/admin/catalog-models/{model_id}/suggestions")
def suggestions(
    model_id: int,
    q: Optional[str] = Query(None, max_length=120),
    limit: int = Query(10, ge=1, le=50),
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    _: Identity = CAN_VIEW,
) -> list[dict]:
    """Accounting products ranked by fuzzy, normalized name match."""
    repo = cm.CatalogModelRepo(db)
    model = _model_or_404(repo, model_id)
    query = (q or "").strip() or model["name"]
    own = {int(i["kala_code"]) for i in repo.items(model_id)}
    taken = repo.mapped_codes()
    names = {c: n for c, n in reader.product_names().items() if c not in own}
    out = fuzzy.rank(query, names, limit=limit, min_score=0.3)
    for row in out:
        row["taken_by"] = taken.get(row["code"])
    return out


@router.post("/admin/catalog-models/{model_id}/items", status_code=status.HTTP_201_CREATED)
def add_item(model_id: int, payload: ItemIn, db: OwnDB = Depends(deps.get_db),
             reader: AccountingReader = Depends(deps.get_reader),
             settings: Settings = Depends(deps.get_settings),
             who: Identity = CAN_CATALOG) -> dict:
    """The owner confirms one accounting product for the model."""
    repo = cm.CatalogModelRepo(db)
    _model_or_404(repo, model_id)
    _not_taken(repo, payload.kala_code)
    name = _product_name(reader, settings, payload.kala_code)
    repo.add_item(model_id, payload.kala_code, name, payload.label.strip(), who.actor)
    db.audit(who.actor, "catalog_item_add", f"model id={model_id} kala={payload.kala_code}")
    return _detail(repo, model_id)


@router.patch("/admin/catalog-models/items/{item_id}")
def patch_item(item_id: int, payload: ItemPatch, db: OwnDB = Depends(deps.get_db),
               reader: AccountingReader = Depends(deps.get_reader),
               settings: Settings = Depends(deps.get_settings),
               who: Identity = CAN_CATALOG) -> dict:
    """Relabel, or replace the product (e.g. with a nightly-check candidate)."""
    repo = cm.CatalogModelRepo(db)
    item = _item_or_404(repo, item_id)
    label = payload.label.strip() if payload.label is not None else None
    if payload.kala_code is not None:
        _not_taken(repo, payload.kala_code, item_id)
        name = _product_name(reader, settings, payload.kala_code)
        repo.replace_item(item_id, payload.kala_code, name, who.actor, label)
        db.audit(who.actor, "catalog_item_replace",
                 f"item id={item_id} kala={item['kala_code']}->{payload.kala_code}")
    elif label is not None:
        repo.set_label(item_id, label)
    return _detail(repo, item["model_id"])


@router.post("/admin/catalog-models/items/{item_id}/accept")
def accept_item(item_id: int, db: OwnDB = Depends(deps.get_db),
                reader: AccountingReader = Depends(deps.get_reader),
                settings: Settings = Depends(deps.get_settings),
                who: Identity = CAN_CATALOG) -> dict:
    """Accept the product's current accounting name (a drifted item)."""
    repo = cm.CatalogModelRepo(db)
    item = _item_or_404(repo, item_id)
    name = _product_name(reader, settings, item["kala_code"])
    repo.accept_current(item_id, name, who.actor)
    db.audit(who.actor, "catalog_item_accept", f"item id={item_id} kala={item['kala_code']}")
    return _detail(repo, item["model_id"])


@router.delete("/admin/catalog-models/items/{item_id}")
def delete_item(item_id: int, db: OwnDB = Depends(deps.get_db),
                who: Identity = CAN_CATALOG) -> dict:
    repo = cm.CatalogModelRepo(db)
    item = _item_or_404(repo, item_id)
    repo.delete_item(item_id)
    db.audit(who.actor, "catalog_item_delete", f"item id={item_id} kala={item['kala_code']}")
    return _detail(repo, item["model_id"])


@router.post("/admin/catalog-models/{model_id}/confirm")
def confirm_model(model_id: int, db: OwnDB = Depends(deps.get_db),
                  reader: AccountingReader = Depends(deps.get_reader),
                  settings: Settings = Depends(deps.get_settings),
                  who: Identity = CAN_CATALOG) -> dict:
    """The owner checked the model: current names are accepted and the model is
    shown again. Refused while an item is missing (gone or renamed beyond the
    threshold) - that item is replaced, removed or accepted on its own first."""
    repo = cm.CatalogModelRepo(db)
    _model_or_404(repo, model_id)
    items = repo.items(model_id)
    if not items:
        raise HTTPException(status.HTTP_409_CONFLICT, "Map at least one product first")
    names = _accounting_names(reader, settings, [int(i["kala_code"]) for i in items])
    # a "missing" item is fixed one by one (replace / remove / accept that item),
    # never by a model-wide confirm: its code may now be a different product
    lost = [str(i["kala_code"]) for i in items
            if int(i["kala_code"]) not in names or i["state"] == "missing"]
    if lost:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Replace or remove products missing from accounting: " + ",".join(lost))
    for i in items:
        repo.accept_current(i["id"], names[int(i["kala_code"])], who.actor)
    repo.set_hidden(model_id, False, actor=who.actor)
    db.audit(who.actor, "catalog_model_confirm", f"model id={model_id}")
    return _detail(repo, model_id)


# ---- bot ----------------------------------------------------------------------
@router.get("/catalog/resolve")
def resolve(
    text: str = Query(min_length=1, max_length=400),
    _: str = Depends(get_catalog_channel),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> dict:
    """A site model reference (``m_<slug>``, pasted «name + کد مدل», a slug or a
    name) -> found / ambiguous / unavailable / unknown."""
    return cm.resolve(db, text, min_score=float(settings.model_resolve_min_score))
