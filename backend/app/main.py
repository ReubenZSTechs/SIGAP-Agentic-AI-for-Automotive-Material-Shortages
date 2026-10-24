from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401  (registrasi semua model ke Base.metadata)
from app.api.v1.api import api_router
from app.config import settings
from app.core.exceptions import AppError
from app.core.i18n import translate
from app.database import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)         # MVP: tanpa Alembic
    yield


app = FastAPI(
    title="MRP & Vendor Sourcing API",
    version="0.1.0",
    description="MVP backend: Master Material & Supplier → BOM → Stock Planning → "
                "Smart Sourcing → PO Multi-Vendor → Goods Receipt.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # untuk MVP, semua origin diizinkan
    allow_credentials=False,        # tanpa cookie/auth di MVP
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """Error body {detail}; translated to English when the browser asks for it (Accept-Language: en)."""
    lang = "en" if request.headers.get("accept-language", "").lower().startswith("en") else "id"
    return JSONResponse(status_code=exc.status_code, content={"detail": translate(exc.detail, lang), **exc.extra})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError):
    # Pengaman terakhir untuk pelanggaran constraint DB (mis. race duplikat).
    return JSONResponse(status_code=409, content={"detail": "Pelanggaran constraint database"})


@app.get("/health")
def health():
    return {"status": "ok"}
