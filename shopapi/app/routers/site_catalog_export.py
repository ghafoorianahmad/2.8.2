"""v2.10.0 «خروجی کاتالوگ برای سایت» (``site_export``): preview, export (zip
or a server folder, optional daily schedule), the site data of each model, its
photos, seeding from the site's own files and accessory PDFs.

Signed-in staff only: viewing needs ``models.view``, changes ``models.edit``;
anything that writes into a folder of the server needs ``server.edit``.
"""
from __future__ import annotations

import base64
import binascii
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from .. import accessory_pdf, control, deps, site_export
from ..catalog_models import CatalogModelRepo
from ..config import Settings
from ..db_own import OwnDB
from ..security import Identity, require_permission
from ..staff import P_MODELS_EDIT, P_MODELS_VIEW, P_SERVER_MANAGE

router = APIRouter()

CAN_VIEW = Depends(require_permission(P_MODELS_VIEW))
CAN_EDIT = Depends(require_permission(P_MODELS_EDIT))
CAN_SERVER = Depends(require_permission(P_SERVER_MANAGE))


def _generator() -> str:
    return f"ShopSystem {control.VERSION}"


def _bad(reason: str) -> HTTPException:
    return HTTPException(422, reason)


def _decode(data_b64: str, limit: int) -> bytes:
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise _bad("فایل درست فرستاده نشد") from None
    if len(data) > limit:
        raise _bad("فایل بیش از اندازهٔ مجاز است")
    return data


# ---- preview / export -------------------------------------------------------------------
@router.get("/admin/site-catalog/preview")
def preview(db: OwnDB = Depends(deps.get_db), settings: Settings = Depends(deps.get_settings),
            _: Identity = CAN_VIEW) -> dict:
    """What would change on the site compared with the last export."""
    return site_export.preview(db, settings, generator=_generator())


def _built(db: OwnDB, settings: Settings) -> dict:
    built = site_export.build(db, settings, generator=_generator())
    problems = site_export.validate_catalog(built["catalog"])
    if problems:
        raise _bad("خروجی ساخته نشد: " + "، ".join(problems[:3]))
    return built


@router.post("/admin/site-catalog/export")
def export_zip(db: OwnDB = Depends(deps.get_db), settings: Settings = Depends(deps.get_settings),
               who: Identity = CAN_EDIT) -> Response:
    """catalog.json + images/ as one zip (ShopAdmin saves it where the user says)."""
    built = _built(db, settings)
    data = site_export.to_zip(built)
    site_export.record(db, built, actor=who.actor, where="zip")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="site-catalog.zip"'})


class FolderIn(BaseModel):
    folder: str = Field(min_length=3, max_length=400)


@router.post("/admin/site-catalog/export-folder")
def export_folder(payload: FolderIn, db: OwnDB = Depends(deps.get_db),
                  settings: Settings = Depends(deps.get_settings),
                  who: Identity = CAN_SERVER) -> dict:
    """Write catalog.json + images/ into a folder on the server now."""
    built = _built(db, settings)
    try:
        written = site_export.to_folder(built, payload.folder)
    except ValueError as exc:
        raise _bad(str(exc)) from None
    except OSError:
        raise _bad("نوشتن در این پوشه ممکن نشد (دسترسی حساب سرویس را بررسی کنید)") from None
    return site_export.record(db, built, actor=who.actor, where="folder", detail=written)


class ScheduleIn(BaseModel):
    enabled: bool
    hour: int = Field(ge=0, le=23)
    folder: str = Field(default="", max_length=400)


@router.get("/admin/site-catalog/schedule")
def get_schedule(db: OwnDB = Depends(deps.get_db), _: Identity = CAN_VIEW) -> dict:
    return {"schedule": site_export.get_schedule(db), "last": site_export.last_export(db)}


@router.put("/admin/site-catalog/schedule")
def put_schedule(payload: ScheduleIn, db: OwnDB = Depends(deps.get_db),
                 who: Identity = CAN_SERVER) -> dict:
    try:
        return site_export.set_schedule(db, enabled=payload.enabled, hour=payload.hour,
                                        folder=payload.folder, actor=who.actor)
    except ValueError as exc:
        raise _bad(str(exc)) from None


# ---- the site data of one model -----------------------------------------------------------
class ColorIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    image: str = Field(default="", max_length=130)
    hex: str = Field(default="", max_length=7)


class SiteDataIn(BaseModel):
    published: bool = True
    tier: str = Field(default="", max_length=30)
    release_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    price_state: str = Field(default="", max_length=30)
    image: str = Field(default="", max_length=130)
    colors: list[ColorIn] = Field(default_factory=list, max_length=12)
    specs: list[list[str]] = Field(default_factory=list, max_length=20)
    group: str = Field(default="", max_length=20)
    brand_key: str = Field(default="", max_length=31)
    brand_name: str = Field(default="", max_length=40)


def _model(db: OwnDB, model_id: int) -> dict:
    model = CatalogModelRepo(db).get_model(model_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")
    return model


@router.get("/admin/site-catalog/models/{model_id}")
def get_site(model_id: int, db: OwnDB = Depends(deps.get_db),
             settings: Settings = Depends(deps.get_settings), _: Identity = CAN_VIEW) -> dict:
    model = _model(db, model_id)
    return {"model": {k: model[k] for k in ("id", "slug", "name", "brand", "kind")},
            "site": site_export.get_site_data(db, model_id),
            "images": sorted(site_export.list_images(settings)),
            "groups": list(site_export.GROUPS)}


@router.put("/admin/site-catalog/models/{model_id}")
def put_site(model_id: int, payload: SiteDataIn, db: OwnDB = Depends(deps.get_db),
             who: Identity = CAN_EDIT) -> dict:
    _model(db, model_id)
    return {"site": site_export.set_site_data(db, model_id, payload.model_dump(), who.actor)}


# ---- photos ----------------------------------------------------------------------------
class ImageIn(BaseModel):
    data_b64: str = Field(min_length=4)


@router.get("/admin/site-catalog/images")
def list_images(settings: Settings = Depends(deps.get_settings), _: Identity = CAN_VIEW) -> dict:
    return {"images": site_export.list_images(settings)}


@router.put("/admin/site-catalog/images/{name}")
def put_image(name: str, payload: ImageIn, settings: Settings = Depends(deps.get_settings),
              who: Identity = CAN_EDIT) -> dict:
    data = _decode(payload.data_b64, site_export.MAX_IMAGE_BYTES)
    try:
        return site_export.save_image(settings, name, data)
    except ValueError as exc:
        raise _bad(str(exc)) from None


# ---- seeding from the site's own files ---------------------------------------------------
class SeedIn(BaseModel):
    products_js: str = Field(min_length=10, max_length=site_export.MAX_SOURCE_BYTES)
    site_js: str = Field(default="", max_length=site_export.MAX_SOURCE_BYTES)
    overwrite: bool = False


@router.post("/admin/site-catalog/seed")
def seed(payload: SeedIn, db: OwnDB = Depends(deps.get_db),
         settings: Settings = Depends(deps.get_settings), who: Identity = CAN_EDIT) -> dict:
    """«خواندن از پوشهٔ سایت»: models, colours, specs and photo names from the
    site's products.js / site.js (as data). The answer lists the photos still
    missing on the server; ShopAdmin uploads them from the same folder."""
    try:
        return site_export.import_site_files(db, settings, payload.products_js, payload.site_js,
                                             actor=who.actor, overwrite=payload.overwrite)
    except site_export.JsLiteralError:
        raise _bad("فایل products.js سایت خوانده نشد") from None


# ---- accessory PDFs ----------------------------------------------------------------------
class AccessoryPdfIn(BaseModel):
    data_b64: str = Field(min_length=4)
    #: empty = only read and show; codes = add these candidates
    codes: list[str] = Field(default_factory=list, max_length=accessory_pdf.MAX_ITEMS)


@router.post("/admin/site-catalog/accessory-pdf")
def accessory_pdf_read(payload: AccessoryPdfIn, db: OwnDB = Depends(deps.get_db),
                       settings: Settings = Depends(deps.get_settings),
                       who: Identity = CAN_EDIT) -> dict:
    data = _decode(payload.data_b64, accessory_pdf.MAX_PDF_BYTES)
    # the same codes as when the file was shown: suggested next to the models of now
    taken = {m["slug"] for m in CatalogModelRepo(db).list_models()}
    try:
        items = accessory_pdf.read_pdf(data, taken_codes=taken)
    except ValueError as exc:
        raise _bad(str(exc)) from None
    out: dict = {"items": [item.public() for item in items]}
    if payload.codes:
        out["result"] = site_export.add_accessories(db, settings, items, payload.codes,
                                                    actor=who.actor)
    return out
