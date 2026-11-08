"""Application settings.

All settings are read from environment variables prefixed with ``FINOPS_``
(or from a ``.env`` file), so the same image runs unchanged in docker-compose,
Kubernetes (ConfigMap/Secret) and tests.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINOPS_", env_file=".env", extra="ignore")

    project_name: str = "KubeFinOps"
    version: str = "2.0.0-dev"
    environment: Literal["dev", "test", "prod"] = "dev"

    # --- Database -----------------------------------------------------------
    # SQLite for local dev/tests, PostgreSQL/TimescaleDB in docker-compose & K8s:
    #   postgresql+psycopg://finops:finops@db:5432/finops
    database_url: str = "sqlite:///./finops.db"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Run `alembic upgrade head` on API start-up. Disable in prod, where a
    # dedicated migration job/init-container runs it once per release.
    auto_migrate: bool = True

    # --- HTTP -----------------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- Logging ----------------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = False

    # --- Background work --------------------------------------------------------
    # In dev the API process also runs the periodic jobs; in prod a separate
    # `python -m app.worker` deployment does it so the API can scale horizontally.
    run_scheduler_in_api: bool = True
    collection_interval_seconds: int = 30

    allocation_interval_seconds: int = 300
    # Re-allocate this many recent hours each run so late-arriving samples count.
    allocation_lookback_hours: int = 2
    shared_namespaces: list[str] = Field(
        default_factory=lambda: ["kube-system", "kube-public", "kube-node-lease", "monitoring"]
    )

    # --- Security -----------------------------------------------------------------
    # Protects cluster-registry endpoints until user auth/RBAC lands (M4).
    # Unset = open (dev only; a warning is logged in prod).
    admin_api_key: str | None = None
    max_samples_per_request: int = 5000

    # --- Demo data --------------------------------------------------------------
    seed_demo_data: bool = True
    # The demo cluster is synthesised through the same ingestion code path a
    # real agent uses; this many days of 5-minute history are back-filled.
    demo_backfill_days: int = 14

    # --- Pricing / policy defaults (overridable at runtime via the Settings API) --
    default_cpu_hourly_rate: float = 0.048  # $ per vCPU-hour
    default_ram_hourly_rate: float = 0.006  # $ per GiB-hour
    idle_cpu_threshold_pct: float = 5.0
    evaluation_window_hours: int = 24
    safety_buffer_pct: float = 20.0

    @field_validator("cors_origins", "shared_namespaces", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
