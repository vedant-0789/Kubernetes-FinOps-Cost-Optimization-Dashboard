"""Application settings.

All settings are read from environment variables prefixed with ``FINOPS_``
(or from a ``.env`` file), so the same image runs unchanged in docker-compose,
Kubernetes (ConfigMap/Secret) and tests.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    # NoDecode: accept plain comma-separated env values (pydantic-settings would
    # otherwise insist on JSON for list fields and crash on `a,b`).
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])

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
    shared_namespaces: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["kube-system", "kube-public", "kube-node-lease", "monitoring"]
    )

    # Right-sizing & waste analysis (M3)
    analysis_interval_seconds: int = 900
    analysis_window_days: int = 14
    rightsizing_strategy: str = "slo_aware"
    min_monthly_savings: float = 1.0   # don't surface downsizes worth less than this

    # --- Users & auth (M4) ----------------------------------------------------------
    # Off only for local development and the test-suite; the Helm chart and
    # docker-compose turn it on.
    auth_required: bool = True
    jwt_secret: str | None = None          # required when auth_required in prod
    jwt_ttl_minutes: int = 60
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # --- Remediation guardrails (M4) -----------------------------------------------------
    require_two_person_approval: bool = True
    protected_namespaces: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["kube-system", "kube-public", "kube-node-lease"]
    )
    change_window_utc: str = "00:00-24:00"   # e.g. "02:00-06:00"; agents only receive actions inside it
    max_actions_per_cluster_per_hour: int = 20
    remediation_verify_minutes: int = 30     # watch period after apply before marking verified
    rollback_on_oom: bool = True
    rollback_throttle_share: float = 0.25    # roll back if >25 % of the window is throttled after apply

    # --- Forecasts, budgets & notifications (M5) -------------------------------------
    finance_interval_seconds: int = 3600       # budget evaluation + anomaly detection
    anomaly_threshold: float = 3.5             # robust z-score of the forecast error
    anomaly_min_delta: float = 5.0             # $/day; ignore smaller swings
    public_url: str = "http://localhost:8080"  # links in alerts
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "kubefinops@localhost"
    smtp_starttls: bool = True

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

    @field_validator("cors_origins", "shared_namespaces", "protected_namespaces", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
