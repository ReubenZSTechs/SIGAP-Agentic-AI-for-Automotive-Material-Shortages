"""Fixture test — berjalan di PostgreSQL lokal (BUKAN SQLite, BUKAN Supabase).

WAJIB set TEST_DATABASE_URL ke database KHUSUS TEST di Postgres lokal docker compose (versi sama dengan
Supabase, skema dibuat dari model yang sama). Skema di-drop & dibuat ulang saat test dimulai, dan semua
tabel dikosongkan sebelum tiap test. URL Supabase selalu ditolak.

    # backend/.env (atau export di terminal)
    TEST_DATABASE_URL=postgresql://mrp:mrp@localhost:5433/mrp_test
"""
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine.url import make_url

_BACKEND = Path(__file__).resolve().parents[1]
_PG_PREFIXES = ("postgres://", "postgresql://")


def _norm(url: str) -> str:
    url = (url or "").strip()
    for p in _PG_PREFIXES:
        if url.startswith(p):
            url = "postgresql+psycopg2://" + url[len(p):]
    return url


def _same_db(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return make_url(_norm(a)).render_as_string(hide_password=True) == \
           make_url(_norm(b)).render_as_string(hide_password=True)


def is_supabase(url: str) -> bool:
    # Sengaja tidak mengimpor app.config: impor itu membuat Settings() dari .env SEBELUM DATABASE_URL test di-set.
    host = (make_url(_norm(url)).host or "").lower()
    return any(host == h or host.endswith("." + h) for h in ("supabase.com", "supabase.co"))


def _resolve_test_url() -> str:
    env_file = dotenv_values(_BACKEND / ".env")
    test_url = os.environ.get("TEST_DATABASE_URL") or env_file.get("TEST_DATABASE_URL")
    if not test_url:
        pytest.exit("TEST_DATABASE_URL belum diisi. Set ke database PostgreSQL khusus test "
                    "(lihat docstring tests/conftest.py).", returncode=2)
    if not _norm(test_url).startswith("postgresql"):
        pytest.exit("TEST_DATABASE_URL harus URL PostgreSQL.", returncode=2)
    if is_supabase(test_url):
        pytest.exit("TEST_DATABASE_URL menunjuk ke Supabase. Test menghapus semua tabel dan hanya boleh "
                    "berjalan di Postgres lokal (docker compose, database mrp_test).", returncode=2)
    # Pengaman: tolak bila sama dengan database aplikasi (.env / env var), karena test melakukan drop_all.
    for real in (env_file.get("DATABASE_URL"), os.environ.get("DATABASE_URL")):
        if _same_db(test_url, real):
            pytest.exit("TEST_DATABASE_URL sama dengan DATABASE_URL aplikasi. Test menghapus semua "
                        "tabel — gunakan database terpisah.", returncode=2)
    return test_url


TEST_URL = _resolve_test_url()
# Paksa aplikasi memakai DB test (env var menimpa .env). Harus sebelum import app.*
os.environ["DATABASE_URL"] = TEST_URL
os.environ["APP_ENV"] = "development"         # pagar Supabase selalu aktif saat test
os.environ["TELEGRAM_MODE"] = "sandbox"      # tes tidak pernah memakai bot Telegram sungguhan
os.environ.pop("TELEGRAM_MANAGER_CHAT_ID", None)

from fastapi.testclient import TestClient          # noqa: E402
from sqlalchemy import text                         # noqa: E402
from sqlalchemy.orm import sessionmaker            # noqa: E402

import app.models  # noqa: E402,F401
from app.api.deps import get_db                    # noqa: E402
from app.database import Base, engine as _engine   # noqa: E402
from app.main import app as fastapi_app            # noqa: E402
from tests.spec_seed import seed as seed_db       # noqa: E402  (data tes tetap, bukan seed demo)


@pytest.fixture(scope="session")
def engine():
    """Skema dibuat sekali per sesi test (lebih cepat daripada per test, penting di Supabase remote)."""
    Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)
    yield _engine
    _engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(engine):
    """Kosongkan semua tabel + reset sequence sebelum tiap test -> tiap test mulai dari DB kosong."""
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def _no_background_dispatch(monkeypatch):
    """`PATCH /status ISSUED` memulai dispatch di thread latar (layanan live). Di test, dispatch dijalankan
    eksplisit dengan layanan fake; thread latar akan memegang lock baris dan memblokir TRUNCATE test berikutnya."""
    import app.supplier_chat.service as chat_service
    monkeypatch.setattr(chat_service, "dispatch_in_background", lambda: None)


@pytest.fixture()
def Session(engine):
    return sessionmaker(autoflush=False, bind=engine)


@pytest.fixture()
def db(Session):
    with Session() as s:
        yield s


@pytest.fixture()
def seeded(db):
    return seed_db(db)


@pytest.fixture()
def client(Session):
    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()
    fastapi_app.dependency_overrides[get_db] = _override
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()