from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Selalu baca backend/.env, apa pun folder tempat perintah dijalankan.
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def normalize_db_url(url: str) -> str:
    """Terima URL apa adanya dari dashboard Supabase.

    Supabase memberi `postgresql://...` (atau `postgres://...`). SQLAlchemy 2.x menolak
    `postgres://`, jadi diubah ke `postgresql+psycopg2://` agar driver-nya eksplisit.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


class Settings(BaseSettings):
    # WAJIB diisi di backend/.env dengan URL Supabase (tombol Connect -> Session pooler):
    #   DATABASE_URL=postgresql://postgres.<ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
    # Tidak ada default: bila kosong, aplikasi berhenti dengan pesan error (tidak diam-diam pindah DB).
    DATABASE_URL: str

    @field_validator("DATABASE_URL")
    @classmethod
    def _postgres_only(cls, v: str) -> str:
        v = normalize_db_url(v.strip())
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL harus URL PostgreSQL/Supabase (postgresql://...). "
                             "SQLite tidak didukung lagi.")
        return v

    # WAJIB diisi di backend/.env: origin frontend yang diizinkan, dipisah koma, mis.
    #   CORS_ORIGINS=http://localhost:5173,https://app.contoh.com
    # Tidak ada default: bila kosong, aplikasi berhenti dengan pesan error.
    CORS_ORIGINS: str

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _valid_origins(cls, v: str) -> str:
        origins = []
        for o in v.split(","):
            o = o.strip().rstrip("/")       # browser mengirim Origin TANPA "/" di akhir
            if not o:
                continue
            if o != "*" and not o.startswith(("http://", "https://")):
                raise ValueError(f"Origin tidak valid: {o!r} (harus diawali http:// atau https://)")
            origins.append(o)
        if not origins:
            raise ValueError("CORS_ORIGINS tidak boleh kosong.")
        return ",".join(origins)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o for o in self.CORS_ORIGINS.split(",") if o]

    # hide_input_in_errors: jangan cetak isi URL (berisi password) saat validasi gagal.
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore", hide_input_in_errors=True)


settings = Settings()