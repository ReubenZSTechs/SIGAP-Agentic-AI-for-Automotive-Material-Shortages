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

    # Chatbot (opsional): kredensial SAP AI Core. Bila kosong, endpoint /chat mengembalikan 503.
    AICORE_AUTH_URL: str | None = None
    AICORE_CLIENT_ID: str | None = None
    AICORE_CLIENT_SECRET: str | None = None
    AICORE_BASE_URL: str | None = None
    AICORE_RESOURCE_GROUP: str = "default"
    # URL role database read-only khusus chatbot; bila kosong memakai DATABASE_URL (tetap READ ONLY).
    CHAT_DATABASE_URL: str | None = None

    @field_validator("CHAT_DATABASE_URL")
    @classmethod
    def _chat_db(cls, v: str | None) -> str | None:
        return normalize_db_url(v.strip()) if v and v.strip() else None

    @property
    def aicore_configured(self) -> bool:
        return all((self.AICORE_AUTH_URL, self.AICORE_CLIENT_ID,
                    self.AICORE_CLIENT_SECRET, self.AICORE_BASE_URL))

    # hide_input_in_errors: jangan cetak isi URL (berisi password) saat validasi gagal.
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore", hide_input_in_errors=True)


settings = Settings()