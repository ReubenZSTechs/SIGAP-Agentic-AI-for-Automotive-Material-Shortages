from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

# TCP keepalive menjaga koneksi idle tetap hidup (dan mendeteksi yang putus) tanpa query tambahan.
KEEPALIVE = {"keepalives": 1, "keepalives_idle": 60, "keepalives_interval": 10, "keepalives_count": 3}

engine = create_engine(
    settings.DATABASE_URL,
    # Tanpa pool_pre_ping: ping = 1 round trip ekstra per request (~140-200 ms dari SAP BTP ke AWS RDS us-east-1).
    # Koneksi yang ternyata putus dikenali SQLAlchemy (is_disconnect) dan dibuang dari pool; keepalive + recycle
    # mencegah sebagian besar kasus itu.
    pool_recycle=1800,
    pool_size=10,
    max_overflow=10,
    connect_args=KEEPALIVE,
)

SessionLocal = sessionmaker(autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass