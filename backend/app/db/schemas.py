from datetime import datetime

from pydantic import BaseModel, Field


class SystemSettingSchema(BaseModel):
    key: str
    value: str
    description: str | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True

class SettingsUpdateSchema(BaseModel):
    cpu_hourly_rate: float = Field(gt=0, description="Cost per vCPU hour ($)")
    ram_hourly_rate: float = Field(gt=0, description="Cost per GB RAM hour ($)")
    idle_cpu_threshold_pct: float = Field(ge=0, le=100)
    evaluation_window_hours: int = Field(gt=0)
    auto_remediation_enabled: bool
    mock_mode: bool

class PodMetricSchema(BaseModel):
    pod_name: str
    namespace: str
    workload_type: str
    cpu_req: float
    cpu_usage: float
    mem_req_mb: float
    mem_usage_mb: float
    net_rx_kb: float
    net_tx_kb: float
    hourly_cost: float
    monthly_cost: float
    efficiency_pct: float
    status_color: str # green, yellow, red

class NamespaceMetricSchema(BaseModel):
    name: str
    pod_count: int
    total_cpu_req: float
    total_cpu_usage: float
    total_mem_req_mb: float
    total_mem_usage_mb: float
    efficiency_pct: float
    monthly_cost: float
    wasted_monthly_cost: float
    status_color: str
    lifecycle_stage: str

class ZombieWorkloadSchema(BaseModel):
    id: int
    namespace: str
    pod_name: str
    workload_name: str
    workload_type: str
    cpu_usage_avg: float
    mem_usage_avg_mb: float
    net_activity_kb: float
    idle_duration_hours: float
    wasted_monthly_cost: float
    status: str
    recommended_action: str
    detected_at: datetime

    class Config:
        from_attributes = True

class RecommendationSchema(BaseModel):
    id: int
    namespace: str
    pod_name: str
    workload_name: str
    workload_type: str
    current_cpu_req: float
    current_mem_req_mb: float
    recommended_cpu_req: float
    recommended_mem_req_mb: float
    current_monthly_cost: float
    recommended_monthly_cost: float
    monthly_savings: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class ActionLogSchema(BaseModel):
    id: int
    action_type: str
    target_resource: str
    namespace: str
    pod_name: str
    monthly_savings: float
    status: str
    applied_by: str
    timestamp: datetime
    details: str | None = None

    class Config:
        from_attributes = True

class OverviewSummarySchema(BaseModel):
    total_monthly_cost: float
    total_potential_savings: float
    realized_monthly_savings: float
    total_namespaces: int
    total_pods: int
    total_nodes: int
    zombie_count: int
    active_recommendations_count: int
    overall_efficiency_pct: float
    mock_mode: bool
    last_updated: datetime

class CostTrendPointSchema(BaseModel):
    date: str
    actual_cost: float
    potential_optimized_cost: float
