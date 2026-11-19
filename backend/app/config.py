from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import make_url

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


SUPABASE_HOSTS = ("supabase.com", "supabase.co")


def is_supabase(url: str | None) -> bool:
    """True bila host URL adalah Supabase (dipakai untuk memagari development & test)."""
    if not url:
        return False
    try:
        host = (make_url(normalize_db_url(url.strip())).host or "").lower()
    except Exception:  # noqa: BLE001  (URL rusak ditolak validator lain)
        return False
    return any(host == h or host.endswith("." + h) for h in SUPABASE_HOSTS)


class Settings(BaseSettings):
    # development (default): Postgres lokal (docker compose). URL Supabase DITOLAK agar kode lokal tidak
    # pernah menyentuh database produksi. production: SAP BTP Cloud Foundry + Supabase (lihat docs/DEPLOYMENT.md).
    APP_ENV: Literal["development", "production"] = "development"

    # WAJIB. Development: postgresql://mrp:mrp@localhost:5433/mrp (docker compose).
    # Production: URL pooler Supabase, di-set lewat manifest.yml + deploy/vars.yml.
    # Satu database untuk aplikasi DAN chatbot (chatbot memakai transaksi READ ONLY di URL yang sama).
    DATABASE_URL: str

    @field_validator("DATABASE_URL")
    @classmethod
    def _postgres_only(cls, v: str) -> str:
        v = normalize_db_url(v.strip())
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL harus URL PostgreSQL/Supabase (postgresql://...). "
                             "SQLite tidak didukung lagi.")
        return v

    # Origin frontend yang diizinkan, dipisah koma. Default "*" = semua origin (API tanpa cookie/kredensial,
    # jadi aman). Persempit bila perlu, mis. CORS_ORIGINS=http://localhost:5173,https://app.contoh.com
    CORS_ORIGINS: str = "*"

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
        origins = [o for o in self.CORS_ORIGINS.split(",") if o]
        return ["*"] if "*" in origins else origins

    # Chatbot (opsional): kredensial SAP AI Core. Bila kosong, endpoint /chat mengembalikan 503.
    AICORE_AUTH_URL: str | None = None
    AICORE_CLIENT_ID: str | None = None
    AICORE_CLIENT_SECRET: str | None = None
    AICORE_BASE_URL: str | None = None
    AICORE_RESOURCE_GROUP: str = "default"
    # Supplier Telegram: "sandbox" (pesan hanya disimpan di DB, supplier/manajer diperankan dari
    # Hub Supplier di frontend) atau "telegram" (Bot API sungguhan, long polling oleh worker).
    TELEGRAM_MODE: Literal["sandbox", "telegram"] = "sandbox"
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_BOT_USERNAME: str | None = None        # untuk deep link t.me/<username>?start=<token>
    TELEGRAM_MANAGER_CHAT_ID: int | None = None     # chat manajer penerima eskalasi & opsi revisi

    # Pencatatan setiap panggilan agent LLM (tabel agent_runs, dibaca Agent Hub Streamlit).
    AGENT_TRACE_ENABLED: bool = True
    AGENT_TRACE_RETENTION_DAYS: int = 30
    AGENT_TRACE_ASYNC: bool = True        # tulis agent_runs/tool_runs di thread latar (tes: False)

    @model_validator(mode="after")
    def _no_supabase_in_development(self) -> "Settings":
        if self.APP_ENV != "production" and is_supabase(self.DATABASE_URL):
            raise ValueError("DATABASE_URL menunjuk ke Supabase tetapi APP_ENV=development. Development & test "
                             "wajib memakai Postgres lokal (docker compose); Supabase hanya untuk APP_ENV=production.")
        return self

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def telegram_live(self) -> bool:
        return self.TELEGRAM_MODE == "telegram" and bool(self.TELEGRAM_BOT_TOKEN)

    @property
    def aicore_configured(self) -> bool:
        return all((self.AICORE_AUTH_URL, self.AICORE_CLIENT_ID,
                    self.AICORE_CLIENT_SECRET, self.AICORE_BASE_URL))

    # hide_input_in_errors: jangan cetak isi URL (berisi password) saat validasi gagal.
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore", hide_input_in_errors=True)


settings = Settings()