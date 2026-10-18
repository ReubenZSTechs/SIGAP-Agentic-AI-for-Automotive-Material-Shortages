"""Fixture test — berjalan di PostgreSQL (BUKAN SQLite).

WAJIB set TEST_DATABASE_URL ke database KHUSUS TEST (mis. project Supabase terpisah atau
Postgres lokal). Skema di-drop & dibuat ulang saat test dimulai, dan semua tabel
dikosongkan sebelum tiap test, jadi JANGAN arahkan ke database yang berisi data asli.

    # backend/.env (atau export di terminal)
    TEST_DATABASE_URL=postgresql://postgres.<ref-test>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
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


def _resolve_test_url() -> str:
    env_file = dotenv_values(_BACKEND / ".env")
    test_url = os.environ.get("TEST_DATABASE_URL") or env_file.get("TEST_DATABASE_URL")
    if not test_url:
        pytest.exit("TEST_DATABASE_URL belum diisi. Set ke database PostgreSQL khusus test "
                    "(lihat docstring tests/conftest.py).", returncode=2)
    if not _norm(test_url).startswith("postgresql"):
        pytest.exit("TEST_DATABASE_URL harus URL PostgreSQL.", returncode=2)
    # Pengaman: tolak bila sama dengan database aplikasi (.env / env var), karena test melakukan drop_all.
    for real in (env_file.get("DATABASE_URL"), os.environ.get("DATABASE_URL")):
        if _same_db(test_url, real):
            pytest.exit("TEST_DATABASE_URL sama dengan DATABASE_URL aplikasi. Test menghapus semua "
                        "tabel — gunakan database terpisah.", returncode=2)
    return test_url


TEST_URL = _resolve_test_url()
# Paksa aplikasi memakai DB test (env var menimpa .env). Harus sebelum import app.*
os.environ["DATABASE_URL"] = TEST_URL
os.environ["CHAT_DATABASE_URL"] = TEST_URL   # engine read-only chatbot juga ke DB test

from fastapi.testclient import TestClient          # noqa: E402
from sqlalchemy import text                         # noqa: E402
from sqlalchemy.orm import sessionmaker            # noqa: E402

import app.models  # noqa: E402,F401
from app.api.deps import get_db                    # noqa: E402
from app.database import Base, engine as _engine   # noqa: E402
from app.main import app as fastapi_app            # noqa: E402
from scripts.seed import seed as seed_db           # noqa: E402


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