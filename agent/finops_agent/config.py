import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"FINOPS_AGENT_{name}", default)


@dataclass(frozen=True)
class AgentConfig:
    server_url: str
    token: str
    prometheus_url: str = "http://prometheus-operated.monitoring.svc:9090"
    slot_seconds: int = 300
    # Prometheus needs a moment to scrape the end of a window before we read it.
    scrape_lag_seconds: int = 60
    backfill_hours: int = 6
    inventory_interval_seconds: int = 300
    batch_size: int = 2000
    request_timeout_seconds: float = 30.0
    max_retries: int = 5
    metrics_port: int = 9101
    excluded_namespaces: frozenset[str] = field(default_factory=frozenset)
    remediation_enabled: bool = False

    @classmethod
    def from_env(cls) -> "AgentConfig":
        server, token = _env("SERVER_URL"), _env("TOKEN")
        if not server or not token:
            raise SystemExit("FINOPS_AGENT_SERVER_URL and FINOPS_AGENT_TOKEN are required")
        excluded = frozenset(n.strip() for n in (_env("EXCLUDED_NAMESPACES", "") or "").split(",") if n.strip())
        return cls(
            server_url=server.rstrip("/"),
            token=token,
            prometheus_url=(_env("PROMETHEUS_URL", cls.prometheus_url) or "").rstrip("/"),
            slot_seconds=int(_env("SLOT_SECONDS", "300")),
            scrape_lag_seconds=int(_env("SCRAPE_LAG_SECONDS", "60")),
            backfill_hours=int(_env("BACKFILL_HOURS", "6")),
            inventory_interval_seconds=int(_env("INVENTORY_INTERVAL_SECONDS", "300")),
            batch_size=int(_env("BATCH_SIZE", "2000")),
            metrics_port=int(_env("METRICS_PORT", "9101")),
            excluded_namespaces=excluded,
            remediation_enabled=(_env("REMEDIATION_ENABLED", "false") or "").lower() == "true",
        )
