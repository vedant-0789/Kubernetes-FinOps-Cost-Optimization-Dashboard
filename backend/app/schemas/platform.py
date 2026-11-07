"""Request/response models for the v2 platform API (clusters, ingestion, allocation)."""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

K8sName = Field(min_length=1, max_length=253)
Provider = Literal["aws", "gcp", "azure", "onprem"]

# --- clusters ------------------------------------------------------------------


class ClusterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
    provider: Provider = "aws"
    region: str | None = Field(default=None, max_length=50)
    custom_cpu_hourly: float | None = Field(default=None, gt=0)
    custom_ram_hourly: float | None = Field(default=None, gt=0)


class ClusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    provider: str
    region: str | None
    custom_cpu_hourly: float | None
    custom_ram_hourly: float | None
    is_active: bool
    agent_version: str | None
    created_at: datetime.datetime
    last_seen_at: datetime.datetime | None


class ClusterWithToken(ClusterOut):
    agent_token: str = Field(description="Shown once. Store it in the agent's Kubernetes Secret.")


# --- ingestion -------------------------------------------------------------------


class NodeIn(BaseModel):
    name: str = K8sName
    instance_type: str | None = Field(default=None, max_length=60)
    capacity_type: Literal["on_demand", "spot"] = "on_demand"
    region: str | None = Field(default=None, max_length=50)
    zone: str | None = Field(default=None, max_length=50)
    vcpu: float = Field(gt=0, le=1024)
    memory_gib: float = Field(gt=0, le=32768)
    hourly_price: float | None = Field(default=None, gt=0, description="From a billing integration, if any")
    created_at: datetime.datetime | None = Field(
        default=None, description="Node metadata.creationTimestamp; lets back-filled history be priced correctly")
    labels: dict[str, str] = Field(default_factory=dict)


class WorkloadIn(BaseModel):
    namespace: str = Field(min_length=1, max_length=63)
    kind: str = Field(min_length=1, max_length=40)
    name: str = K8sName
    replicas: int | None = Field(default=None, ge=0)
    labels: dict[str, str] = Field(default_factory=dict)


class InventoryIn(BaseModel):
    agent_version: str | None = Field(default=None, max_length=40)
    collected_at: datetime.datetime | None = None
    nodes: list[NodeIn] = Field(default_factory=list, max_length=5000)
    workloads: list[WorkloadIn] = Field(default_factory=list, max_length=50000)


class SampleIn(BaseModel):
    ts: datetime.datetime = Field(description="Start of the window, UTC")
    namespace: str = Field(min_length=1, max_length=63)
    pod: str = K8sName
    container: str = K8sName
    node: str | None = Field(default=None, max_length=253)
    workload_kind: str | None = Field(default=None, max_length=40)
    workload_name: str | None = Field(default=None, max_length=253)
    duration_seconds: int = Field(default=300, ge=10, le=3600)
    cpu_request_cores: float = Field(default=0, ge=0)
    cpu_limit_cores: float | None = Field(default=None, ge=0)
    cpu_usage_cores: float = Field(ge=0)
    cpu_usage_max_cores: float | None = Field(default=None, ge=0)
    cpu_throttled_seconds: float = Field(default=0, ge=0)
    mem_request_bytes: float = Field(default=0, ge=0)
    mem_limit_bytes: float | None = Field(default=None, ge=0)
    mem_usage_bytes: float = Field(ge=0)
    mem_usage_max_bytes: float | None = Field(default=None, ge=0)
    net_rx_bytes: float = Field(default=0, ge=0)
    net_tx_bytes: float = Field(default=0, ge=0)
    restarts: int = Field(default=0, ge=0)
    oom_kills: int = Field(default=0, ge=0)


class NodeSampleIn(BaseModel):
    ts: datetime.datetime = Field(description="Start of the window, UTC")
    node: str = K8sName
    duration_seconds: int = Field(default=300, ge=10, le=3600, description="Seconds the node was up in the window")


class SamplesIn(BaseModel):
    samples: list[SampleIn] = Field(default_factory=list)
    node_samples: list[NodeSampleIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _not_empty(self):
        if not self.samples and not self.node_samples:
            raise ValueError("samples and node_samples cannot both be empty")
        return self


class IngestResult(BaseModel):
    accepted: int
    duplicates: int = 0
    rejected: int = 0
    node_samples_accepted: int = 0
    detail: list[str] = Field(default_factory=list)


# --- allocation ----------------------------------------------------------------


class AllocationItem(BaseModel):
    name: str
    cpu_cost: float
    ram_cost: float
    total_cost: float
    cpu_core_hours: float
    ram_gib_hours: float
    cpu_efficiency: float
    ram_efficiency: float
    efficiency: float
    shared_cost_added: float = 0.0


class AllocationReport(BaseModel):
    cluster_id: str
    window_start: datetime.datetime
    window_end: datetime.datetime
    aggregate: str
    shared_mode: Literal["separate", "distribute"]
    total_cost: float
    allocated_cost: float
    idle_cost: float
    shared_cost: float
    efficiency: float
    items: list[AllocationItem]


class TimeseriesPoint(BaseModel):
    start: datetime.datetime
    total_cost: float
    idle_cost: float
    by_group: dict[str, float]


class ClusterSummary(BaseModel):
    cluster: ClusterOut
    nodes: int
    spot_nodes: int
    workloads: int
    hourly_run_rate: float
    monthly_run_rate: float
    cost_last_24h: float
    idle_cost_last_24h: float
    idle_pct: float
    efficiency: float
    last_allocated_window: datetime.datetime | None
