from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    # Koneksi idle bisa diputus server/pooler Supabase -> cek dulu sebelum dipakai.
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass