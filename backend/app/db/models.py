import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.db.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(50), primary_key=True, index=True)
    value = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class MetricsSnapshot(Base):
    __tablename__ = "metrics_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    namespace = Column(String(100), index=True)
    pod_name = Column(String(150), index=True)
    workload_type = Column(String(50), default="Deployment") # Deployment, StatefulSet, DaemonSet

    cpu_req = Column(Float, default=0.0)      # vCPUs requested
    cpu_usage = Column(Float, default=0.0)    # vCPUs actually used
    mem_req_mb = Column(Float, default=0.0)   # MB requested
    mem_usage_mb = Column(Float, default=0.0) # MB actually used

    net_rx_bytes = Column(Float, default=0.0)
    net_tx_bytes = Column(Float, default=0.0)

    hourly_cost = Column(Float, default=0.0)
    monthly_cost = Column(Float, default=0.0)
    efficiency_pct = Column(Float, default=0.0)

class ZombieWorkload(Base):
    __tablename__ = "zombie_workloads"

    id = Column(Integer, primary_key=True, index=True)
    namespace = Column(String(100), index=True)
    pod_name = Column(String(150), index=True)
    workload_name = Column(String(150), index=True)
    workload_type = Column(String(50), default="Deployment")

    cpu_usage_avg = Column(Float, default=0.0)
    mem_usage_avg_mb = Column(Float, default=0.0)
    net_activity_kb = Column(Float, default=0.0)

    idle_duration_hours = Column(Float, default=24.0)
    wasted_monthly_cost = Column(Float, default=0.0)

    status = Column(String(50), default="ACTIVE", index=True) # ACTIVE, REMEDIATED, IGNORED
    recommended_action = Column(String(100), default="Scale to 0 replicas")
    detected_at = Column(DateTime, default=datetime.datetime.utcnow)

class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    namespace = Column(String(100), index=True)
    pod_name = Column(String(150), index=True)
    workload_name = Column(String(150), index=True)
    workload_type = Column(String(50), default="Deployment")

    current_cpu_req = Column(Float, default=0.0)
    current_mem_req_mb = Column(Float, default=0.0)

    recommended_cpu_req = Column(Float, default=0.0)
    recommended_mem_req_mb = Column(Float, default=0.0)

    current_monthly_cost = Column(Float, default=0.0)
    recommended_monthly_cost = Column(Float, default=0.0)
    monthly_savings = Column(Float, default=0.0)

    status = Column(String(50), default="PENDING", index=True) # PENDING, APPLIED, DISMISSED
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class ActionLog(Base):
    __tablename__ = "action_logs"

    id = Column(Integer, primary_key=True, index=True)
    action_type = Column(String(50), index=True) # RIGHT_SIZE, SCALE_DOWN, DELETE_POD
    target_resource = Column(String(150))
    namespace = Column(String(100))
    pod_name = Column(String(150))

    monthly_savings = Column(Float, default=0.0)
    status = Column(String(50), default="SUCCESS")
    applied_by = Column(String(50), default="MANUAL") # MANUAL, AUTO_REMEDIATION
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    details = Column(Text, nullable=True)


# v2 platform tables (registered on the same metadata)
from app.db.platform_models import *  # noqa: E402,F401,F403
