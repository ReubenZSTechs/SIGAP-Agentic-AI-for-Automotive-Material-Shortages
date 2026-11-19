import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401  (registrasi semua model ke Base.metadata)
from app.api.deps import request_lang
from app.api.v1.api import api_router
from app.config import settings
from app.core import perf
from app.core.exceptions import AppError
from app.core.i18n import translate
from app.database import Base, engine
from app import db_migrate


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)         # MVP: tanpa Alembic
    db_migrate.apply(engine)                 # kolom baru pada tabel lama (mis. Supabase produksi)
    yield
    from app.chatbot import tracing
    tracing.flush()                          # jejak agent yang masih antre ditulis sebelum berhenti


app = FastAPI(
    title="MRP & Vendor Sourcing API",
    version="0.1.0",
    description="MVP backend: Master Material & Supplier → BOM → Stock Planning → "
                "Smart Sourcing → PO Multi-Vendor → Goods Receipt.",
    lifespan=lifespan,
)
log = logging.getLogger("app")


@app.middleware("http")
async def unhandled_errors(request: Request, call_next):
    """Turns an unexpected exception into a JSON 500 INSIDE the CORS middleware.

    Starlette's own 500 page is produced outside CORSMiddleware, so it has no CORS headers and the browser
    reports it as "cannot connect to server" instead of showing the error.
    """
    try:
        return await call_next(request)
    except Exception:  # noqa: BLE001
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": translate("Terjadi kesalahan di server",
                                                                           request_lang(request))})


app.middleware("http")(perf.server_timing)                   # Server-Timing: jumlah query & waktu SQL per request
app.add_middleware(GZipMiddleware, minimum_size=1024)      # daftar besar (PO, stok, misi) jauh lebih kecil
app.add_middleware(                 # ditambahkan terakhir = lapisan terluar: setiap respons (termasuk 500) ber-CORS
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,   # default "*" (CORS_ORIGINS di .env / manifest)
    allow_credentials=False,        # tanpa cookie/auth di MVP (wajib False untuk origin "*")
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Server-Timing"],
)
app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """Error body {detail}; translated to English when the browser asks for it (Accept-Language: en)."""
    return JSONResponse(status_code=exc.status_code,
                        content={"detail": translate(exc.detail, request_lang(request)), **exc.extra})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    # Pengaman terakhir untuk pelanggaran constraint DB (mis. race duplikat).
    return JSONResponse(status_code=409, content={"detail": translate("Pelanggaran constraint database",
                                                                       request_lang(request))})


@app.get("/health")
def health():
    return {"status": "ok"}
