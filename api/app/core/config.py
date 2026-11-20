from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "VMS"
    public_web_url: str = "http://localhost:5173"

    # Two database URLs on purpose:
    #  - DATABASE_URL: the restricted `vms_app` role. Row-Level Security applies to it.
    #  - DATABASE_ADMIN_URL: the table-owner role. Used ONLY by migrations, platform
    #    (super-admin) routes, login lookup, signup and background jobs.
    database_url: str = "postgresql+asyncpg://vms_app:vms_app@localhost:5432/vms"
    database_admin_url: str = "postgresql+asyncpg://vms:vms@localhost:5432/vms"
    db_echo: bool = False

    # "memory://" uses an in-process fake Redis (local dev without Docker / tests only).
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = Field(default="dev-insecure-change-me-0123456789abcdef", min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    refresh_cookie_name: str = "vms_refresh"
    cookie_secure: bool = False

    cors_origins: list[str] = ["http://localhost:5173"]
    # Serve the built web app (web/dist) from the API too, so one process on one port
    # is the whole site (scripts in serve-public.bat). Empty = API only.
    web_dist_dir: str = ""

    # Storage. "local" keeps files under LOCAL_MEDIA_DIR (dev without MinIO / tests).
    storage_backend: Literal["s3", "local"] = "s3"
    local_media_dir: str = ".media"
    s3_endpoint_url: str | None = "http://localhost:9000"
    # Host browsers use for presigned links, if different (e.g. http://localhost:9000
    # while the API reaches MinIO as http://minio:9000 inside Docker).
    s3_public_endpoint_url: str | None = None
    s3_region: str = "ap-south-1"
    s3_bucket: str = "vms-media"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    default_data_region: str = "ap-south-1"
    default_timezone: str = "Asia/Kolkata"

    # Visitor passes are signed with Ed25519 (PEM, PKCS8). Empty in dev/test = a key is
    # generated and kept in PASS_KEY_FILE so passes survive restarts.
    pass_signing_key: str = ""
    pass_key_file: str = ".pass_signing_key.pem"

    # WhatsApp. "mock" logs every message to the DB; /dev/whatsapp shows them.
    # "off" runs without WhatsApp: no visitor codes, hosts are alerted by web push, the
    # visitor keeps their screen open for the answer and the pass, and links are shared
    # by people from their own WhatsApp.
    whatsapp_provider: Literal["mock", "meta", "off"] = "mock"
    whatsapp_app_secret: str = ""  # verifies X-Hub-Signature-256 on webhooks
    whatsapp_verify_token: str = "dev-verify-token"
    # Meta Cloud API (WHATSAPP_PROVIDER=meta): the platform's shared business number.
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""  # a System User token with whatsapp_business_messaging
    whatsapp_waba_id: str = ""  # only needed to create templates (scripts.whatsapp_templates)
    whatsapp_graph_url: str = "https://graph.facebook.com/v21.0"
    whatsapp_template_prefix: str = "vms_"
    whatsapp_timeout_seconds: float = 10.0

    # Web push (alerts on hosts' phones). VAPID private key, PEM. Empty in dev/test =
    # a key is generated and kept in VAPID_KEY_FILE.
    vapid_private_key: str = ""
    vapid_key_file: str = ".vapid_key.pem"
    vapid_subject: str = "mailto:admin@example.com"  # who push services can contact

    # Visitor check-in
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_seconds: int = 30
    otp_per_phone_limit: int = 3  # sends per phone per 10 minutes
    otp_per_ip_limit: int = 20
    otp_per_gate_limit: int = 200
    visitor_token_ttl_minutes: int = 30

    # Background jobs. None = run them inside the API process when REDIS_URL is memory://
    # (no worker available); with real Redis the ARQ worker runs them.
    jobs_in_process: bool | None = None
    sweep_interval_seconds: int = 15

    # Rate limits
    login_rate_limit: int = 10  # attempts per identifier per window
    login_rate_window_seconds: int = 300
    signup_rate_limit: int = 5  # per IP per hour
    # Public /signup (anyone can create an organization). Off for a company's own
    # server: the super admin creates organizations in /platform instead.
    allow_signup: bool = True

    @property
    def whatsapp_enabled(self) -> bool:
        return self.whatsapp_provider != "off"

    @property
    def run_jobs_in_process(self) -> bool:
        if self.jobs_in_process is not None:
            return self.jobs_in_process
        return self.redis_url.startswith("memory://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
