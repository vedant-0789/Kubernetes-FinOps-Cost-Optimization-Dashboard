"""v2 platform schema: clusters, inventory, usage time series, allocations.

All timestamps are naive UTC (``utcnow()``), identical on SQLite and PostgreSQL.
``usage_samples``, ``cost_allocations`` and ``node_costs`` become TimescaleDB
hypertables on PostgreSQL (see migration 0002); their primary keys therefore
start with the time column.
"""

import datetime
import uuid

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(20), default="aws")  # aws | gcp | azure | onprem
    region: Mapped[str | None] = mapped_column(String(50))
    # Negotiated / on-prem unit prices; override the catalog when both set.
    custom_cpu_hourly: Mapped[float | None] = mapped_column(Float)
    custom_ram_hourly: Mapped[float | None] = mapped_column(Float)
    # Agent credential: only a SHA-256 hash is stored; the prefix finds the row.
    token_prefix: Mapped[str] = mapped_column(String(16), index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    agent_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("cluster_id", "name", name="uq_nodes_cluster_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(253))
    instance_type: Mapped[str | None] = mapped_column(String(60))
    capacity_type: Mapped[str] = mapped_column(String(20), default="on_demand")  # on_demand | spot
    region: Mapped[str | None] = mapped_column(String(50))
    zone: Mapped[str | None] = mapped_column(String(50))
    vcpu: Mapped[float] = mapped_column(Float)
    memory_gib: Mapped[float] = mapped_column(Float)
    reported_hourly: Mapped[float | None] = mapped_column(Float)
    hourly_price: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_hourly_per_core: Mapped[float] = mapped_column(Float, default=0.0)
    ram_hourly_per_gib: Mapped[float] = mapped_column(Float, default=0.0)
    price_source: Mapped[str] = mapped_column(String(20), default="fallback")
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class Workload(Base):
    """A pod owner (Deployment, StatefulSet, DaemonSet, Job, CronJob, or a bare Pod)."""

    __tablename__ = "workloads"
    __table_args__ = (
        UniqueConstraint("cluster_id", "namespace", "kind", "name", name="uq_workloads_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    namespace: Mapped[str] = mapped_column(String(63), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(253))
    replicas: Mapped[int | None] = mapped_column(Integer)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class UsageSample(Base):
    """One container over one scrape window (typically 5 minutes)."""

    __tablename__ = "usage_samples"
    __table_args__ = (Index("ix_usage_samples_cluster_ts", "cluster_id", "ts"),)

    ts: Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(63), primary_key=True)
    pod: Mapped[str] = mapped_column(String(253), primary_key=True)
    container: Mapped[str] = mapped_column(String(253), primary_key=True)
    node: Mapped[str | None] = mapped_column(String(253))
    workload_kind: Mapped[str | None] = mapped_column(String(40))
    workload_name: Mapped[str | None] = mapped_column(String(253))
    duration_seconds: Mapped[int] = mapped_column(Integer, default=300)
    cpu_request_cores: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_limit_cores: Mapped[float | None] = mapped_column(Float)
    cpu_usage_cores: Mapped[float] = mapped_column(Float, default=0.0)       # mean over window
    cpu_usage_max_cores: Mapped[float | None] = mapped_column(Float)         # peak within window
    cpu_throttled_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    mem_request_bytes: Mapped[float] = mapped_column(Float, default=0.0)
    mem_limit_bytes: Mapped[float | None] = mapped_column(Float)
    mem_usage_bytes: Mapped[float] = mapped_column(Float, default=0.0)       # working set, mean
    mem_usage_max_bytes: Mapped[float | None] = mapped_column(Float)
    net_rx_bytes: Mapped[float] = mapped_column(Float, default=0.0)
    net_tx_bytes: Mapped[float] = mapped_column(Float, default=0.0)
    restarts: Mapped[int] = mapped_column(Integer, default=0)
    oom_kills: Mapped[int] = mapped_column(Integer, default=0)


class NodeSample(Base):
    """Node heartbeat per scrape window. Gives exact node uptime per hour, so
    autoscaled and spot-interrupted nodes are billed only while they run."""

    __tablename__ = "node_samples"
    __table_args__ = (Index("ix_node_samples_cluster_ts", "cluster_id", "ts"),)

    ts: Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node: Mapped[str] = mapped_column(String(253), primary_key=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=300)


class CostAllocation(Base):
    __tablename__ = "cost_allocations"
    __table_args__ = (
        Index("ix_cost_alloc_cluster_window", "cluster_id", "window_start"),
        Index("ix_cost_alloc_cluster_ns_window", "cluster_id", "namespace", "window_start"),
    )

    window_start: Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(63), primary_key=True)
    pod: Mapped[str] = mapped_column(String(253), primary_key=True)
    container: Mapped[str] = mapped_column(String(253), primary_key=True)
    window_hours: Mapped[float] = mapped_column(Float, default=1.0)
    node: Mapped[str | None] = mapped_column(String(253))
    workload_kind: Mapped[str | None] = mapped_column(String(40))
    workload_name: Mapped[str | None] = mapped_column(String(253))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    cpu_core_hours: Mapped[float] = mapped_column(Float, default=0.0)
    ram_gib_hours: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_request_core_hours: Mapped[float] = mapped_column(Float, default=0.0)
    ram_request_gib_hours: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_usage_core_hours: Mapped[float] = mapped_column(Float, default=0.0)
    ram_usage_gib_hours: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_cost: Mapped[float] = mapped_column(Float, default=0.0)
    ram_cost: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_usage_cost: Mapped[float] = mapped_column(Float, default=0.0)
    ram_usage_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)


class NodeCost(Base):
    __tablename__ = "node_costs"

    window_start: Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node: Mapped[str] = mapped_column(String(253), primary_key=True)
    hourly_price: Mapped[float] = mapped_column(Float, default=0.0)
    price_source: Mapped[str] = mapped_column(String(20), default="fallback")
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_cost: Mapped[float] = mapped_column(Float, default=0.0)
    ram_cost: Mapped[float] = mapped_column(Float, default=0.0)
    idle_cpu_cost: Mapped[float] = mapped_column(Float, default=0.0)
    idle_ram_cost: Mapped[float] = mapped_column(Float, default=0.0)


class AllocationWatermark(Base):
    """Last fully allocated window per cluster, so the job is incremental."""

    __tablename__ = "allocation_watermarks"

    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), primary_key=True)
    last_window_start: Mapped[datetime.datetime] = mapped_column(DateTime)


# --- M3: extra inventory ------------------------------------------------------------


class Volume(Base):
    """PersistentVolumeClaim (orphaned-volume detection)."""

    __tablename__ = "volumes"
    __table_args__ = (UniqueConstraint("cluster_id", "namespace", "name", name="uq_volumes_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    namespace: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(253))
    storage_class: Mapped[str | None] = mapped_column(String(100))
    capacity_gib: Mapped[float] = mapped_column(Float, default=0.0)
    phase: Mapped[str] = mapped_column(String(20), default="Bound")
    mounted_by: Mapped[list] = mapped_column(JSON, default=list)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    first_seen: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class ServiceInv(Base):
    """Kubernetes Service (unused LoadBalancer detection)."""

    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("cluster_id", "namespace", "name", name="uq_services_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    namespace: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(253))
    type: Mapped[str] = mapped_column(String(20), default="ClusterIP")
    has_endpoints: Mapped[bool] = mapped_column(Boolean, default=True)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    first_seen: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class Autoscaler(Base):
    """HorizontalPodAutoscaler (right-sizing must not fight it)."""

    __tablename__ = "autoscalers"
    __table_args__ = (UniqueConstraint("cluster_id", "namespace", "name", name="uq_autoscalers_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    namespace: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(253))
    target_kind: Mapped[str] = mapped_column(String(40))
    target_name: Mapped[str] = mapped_column(String(253))
    cpu_target_utilization: Mapped[float | None] = mapped_column(Float)  # 0..1
    min_replicas: Mapped[int | None] = mapped_column(Integer)
    max_replicas: Mapped[int | None] = mapped_column(Integer)
    first_seen: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


# --- M3: analysis results -------------------------------------------------------------


class RightsizingRecommendation(Base):
    __tablename__ = "rightsizing_recommendations"
    __table_args__ = (
        UniqueConstraint("cluster_id", "namespace", "workload_kind", "workload_name", "container", "strategy",
                         name="uq_rightsizing_identity"),
        Index("ix_rightsizing_cluster_status", "cluster_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"))
    namespace: Mapped[str] = mapped_column(String(63))
    workload_kind: Mapped[str] = mapped_column(String(40))
    workload_name: Mapped[str] = mapped_column(String(253))
    container: Mapped[str] = mapped_column(String(253))
    strategy: Mapped[str] = mapped_column(String(30), default="slo_aware")
    action: Mapped[str] = mapped_column(String(20))          # downsize | upsize
    # open -> applied | dismissed ; open -> resolved (no longer needed)
    status: Mapped[str] = mapped_column(String(20), default="open")
    replicas: Mapped[float] = mapped_column(Float, default=1.0)
    current_cpu_request: Mapped[float] = mapped_column(Float)
    current_mem_request: Mapped[float] = mapped_column(Float)
    current_cpu_limit: Mapped[float | None] = mapped_column(Float)
    current_mem_limit: Mapped[float | None] = mapped_column(Float)
    recommended_cpu_request: Mapped[float] = mapped_column(Float)
    recommended_mem_request: Mapped[float] = mapped_column(Float)
    recommended_cpu_limit: Mapped[float | None] = mapped_column(Float)
    recommended_mem_limit: Mapped[float | None] = mapped_column(Float)
    monthly_savings: Mapped[float] = mapped_column(Float, default=0.0)  # negative = costs more (upsize)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_label: Mapped[str] = mapped_column(String(10), default="low")
    risk: Mapped[str] = mapped_column(String(10), default="medium")
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    dismissed_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class WasteFinding(Base):
    __tablename__ = "waste_findings"
    __table_args__ = (
        UniqueConstraint("cluster_id", "kind", "namespace", "name", name="uq_waste_identity"),
        Index("ix_waste_cluster_status", "cluster_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    namespace: Mapped[str] = mapped_column(String(63), default="")   # "" for cluster-scoped (nodes)
    name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | dismissed | resolved
    monthly_savings: Mapped[float] = mapped_column(Float, default=0.0)
    risk: Mapped[str] = mapped_column(String(10), default="medium")
    action: Mapped[str] = mapped_column(String(300))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    dismissed_reason: Mapped[str | None] = mapped_column(String(500))
    first_detected: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    last_detected: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), primary_key=True)
    last_run_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    containers_analyzed: Mapped[int] = mapped_column(Integer, default=0)
