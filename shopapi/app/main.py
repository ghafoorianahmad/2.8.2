"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import contextlib
import math
import logging
import sqlite3
from contextlib import asynccontextmanager

import pyodbc
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import (archive, catalog_models, control, deps, monitor, order_timeout, site_catalog,
               sql_errors, tracking)
from .db_own import OwnDB
from .routers import (
    admin, auth, catalog, pricelist, public, server_admin, shop_catalog, staff_admin,
)


class UTF8JSONResponse(JSONResponse):
    """JSON with an explicit charset.

    JSON is UTF-8 by definition, but Windows PowerShell 5.1 falls back to
    Latin-1 when the Content-Type has no charset, which turns Persian product
    names into mojibake in the console. Naming the charset keeps
    `Invoke-RestMethod` and older clients correct.
    """

    media_type = "application/json; charset=utf-8"


def _json_safe(value):
    """Make a structure JSON-encodable: NaN/Infinity are not valid JSON and would
    otherwise crash the serializer while building an error response."""
    if isinstance(value, float):
        return str(value) if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the own SQLite database file/schema exists at startup.
    settings = deps.get_settings()
    OwnDB(settings.sqlite_path)
    # Invoice tracking (R5): written orders -> "invoiced" events for the bots.
    db_factory = lambda: deps.get_db(settings)  # noqa: E731
    reader_factory = lambda: deps.get_reader(settings)  # noqa: E731
    tasks = [
        asyncio.create_task(tracking.invoice_sync_loop(settings, db_factory, reader_factory)),
        # Health monitoring (§8): SQL / bot / Bale / Telegram worker -> events + Bale.
        asyncio.create_task(monitor.health_loop(settings, db_factory, reader_factory)),
        # Nightly check of the site model mapping (§9a): hide + Bale alert on loss.
        asyncio.create_task(catalog_models.nightly_loop(settings, db_factory, reader_factory)),
        # v2.9.3: the live site's models once a month (+ mapping after a new price list)
        asyncio.create_task(site_catalog.monthly_loop(settings, db_factory, reader_factory)),
        # Receipt deadline (30 min) -> local cancel; sales window transitions -> events.
        asyncio.create_task(order_timeout.order_timeout_loop(settings, db_factory)),
        # v2.8.0: Thursday 23:30 (Tehran) -> finished orders / requests to «بایگانی».
        asyncio.create_task(archive.archive_loop(db_factory)),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    application = FastAPI(
        title="shopapi",
        version=control.VERSION,
        lifespan=lifespan,
        default_response_class=UTF8JSONResponse,
    )
    application.include_router(public.router)
    application.include_router(admin.router)
    application.include_router(auth.router)
    application.include_router(staff_admin.router)
    application.include_router(server_admin.router)
    application.include_router(pricelist.router)
    application.include_router(catalog.router)
    application.include_router(shop_catalog.router)

    @application.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Sanitize first: a non-finite float in the rejected input would otherwise
        # break JSON encoding and turn a clean 422 into a crash.
        return JSONResponse(
            status_code=422, content={"detail": _json_safe(jsonable_encoder(exc.errors()))}
        )

    @application.exception_handler(pyodbc.Error)
    async def _accounting_unavailable(request: Request, exc: pyodbc.Error) -> JSONResponse:
        # Clear error instead of a crash; never leak SQL, the server name, the
        # login or a stack trace: only the error number and a Persian sentence.
        info = sql_errors.describe(exc)
        logging.getLogger("shopapi.sql").warning(
            "accounting error %s on %s", info.code or "?", request.url.path)
        return JSONResponse(
            status_code=503,
            content={"detail": "Accounting database unavailable",
                     "error_code": info.code, "message_fa": info.message_fa},
        )

    @application.exception_handler(sqlite3.Error)
    async def _own_db_unavailable(request: Request, exc: sqlite3.Error) -> JSONResponse:
        return JSONResponse(
            status_code=503, content={"detail": "Own database unavailable"}
        )

    return application


app = create_app()
