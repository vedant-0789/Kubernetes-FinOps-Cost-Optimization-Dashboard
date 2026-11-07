
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import MetricsSnapshot, ZombieWorkload
from app.db.schemas import NamespaceMetricSchema, PodMetricSchema
from app.engine.mock_generator import NAMESPACES

router = APIRouter(prefix="/namespaces", tags=["Namespaces"])

STAGE_MAP = {ns["name"]: ns["stage"] for ns in NAMESPACES}

@router.get("", response_model=list[NamespaceMetricSchema])
def get_namespaces(db: Session = Depends(get_db)):
    latest_snaps = db.query(MetricsSnapshot).order_by(MetricsSnapshot.timestamp.desc()).all()

    # Pod map to get latest pod states
    pod_map = {}
    for snap in latest_snaps:
        key = f"{snap.namespace}/{snap.pod_name}"
        if key not in pod_map:
            pod_map[key] = snap

    # Group by namespace
    ns_groups = {}
    for snap in pod_map.values():
        ns = snap.namespace
        if ns not in ns_groups:
            ns_groups[ns] = []
        ns_groups[ns].append(snap)

    active_zombies = db.query(ZombieWorkload).filter(ZombieWorkload.status == "ACTIVE").all()
    zombie_waste_by_ns = {}
    for z in active_zombies:
        zombie_waste_by_ns[z.namespace] = zombie_waste_by_ns.get(z.namespace, 0.0) + z.wasted_monthly_cost

    results = []
    for ns_name, pods in ns_groups.items():
        pod_count = len(pods)
        tot_cpu_req = sum(p.cpu_req for p in pods)
        tot_cpu_u = sum(p.cpu_usage for p in pods)
        tot_mem_req = sum(p.mem_req_mb for p in pods)
        tot_mem_u = sum(p.mem_usage_mb for p in pods)
        monthly_cost = sum(p.monthly_cost for p in pods)

        cpu_eff = (tot_cpu_u / tot_cpu_req * 100.0) if tot_cpu_req > 0 else 100.0
        mem_eff = (tot_mem_u / tot_mem_req * 100.0) if tot_mem_req > 0 else 100.0
        overall_eff = min(100.0, max(0.0, (cpu_eff + mem_eff) / 2.0))

        if overall_eff >= 65.0:
            status_color = "green"
        elif overall_eff >= 35.0:
            status_color = "yellow"
        else:
            status_color = "red"

        wasted = zombie_waste_by_ns.get(ns_name, 0.0)
        # If overprovisioned, add waste gap
        if overall_eff < 65.0:
            wasted += (monthly_cost * (1.0 - (overall_eff / 100.0))) * 0.5

        results.append(NamespaceMetricSchema(
            name=ns_name,
            pod_count=pod_count,
            total_cpu_req=round(tot_cpu_req, 2),
            total_cpu_usage=round(tot_cpu_u, 2),
            total_mem_req_mb=round(tot_mem_req, 0),
            total_mem_usage_mb=round(tot_mem_u, 0),
            efficiency_pct=round(overall_eff, 1),
            monthly_cost=round(monthly_cost, 2),
            wasted_monthly_cost=round(wasted, 2),
            status_color=status_color,
            lifecycle_stage=STAGE_MAP.get(ns_name, "Attribute")
        ))

    return sorted(results, key=lambda x: x.monthly_cost, reverse=True)

@router.get("/{name}/pods", response_model=list[PodMetricSchema])
def get_namespace_pods(name: str, db: Session = Depends(get_db)):
    latest_snaps = db.query(MetricsSnapshot).filter(MetricsSnapshot.namespace == name).order_by(MetricsSnapshot.timestamp.desc()).all()

    pod_map = {}
    for snap in latest_snaps:
        if snap.pod_name not in pod_map:
            pod_map[snap.pod_name] = snap

    if not pod_map:
        raise HTTPException(status_code=404, detail=f"Namespace {name} not found or has no active pods.")

    results = []
    for _pod_name, snap in pod_map.items():
        cpu_eff = (snap.cpu_usage / snap.cpu_req * 100.0) if snap.cpu_req > 0 else 100.0
        mem_eff = (snap.mem_usage_mb / snap.mem_req_mb * 100.0) if snap.mem_req_mb > 0 else 100.0
        eff = min(100.0, max(0.0, (cpu_eff + mem_eff) / 2.0))

        if eff >= 65.0:
            color = "green"
        elif eff >= 35.0:
            color = "yellow"
        else:
            color = "red"

        results.append(PodMetricSchema(
            pod_name=snap.pod_name,
            namespace=snap.namespace,
            workload_type=snap.workload_type,
            cpu_req=round(snap.cpu_req, 2),
            cpu_usage=round(snap.cpu_usage, 2),
            mem_req_mb=round(snap.mem_req_mb, 0),
            mem_usage_mb=round(snap.mem_usage_mb, 0),
            net_rx_kb=round(snap.net_rx_bytes / 1024.0, 1),
            net_tx_kb=round(snap.net_tx_bytes / 1024.0, 1),
            hourly_cost=round(snap.hourly_cost, 4),
            monthly_cost=round(snap.monthly_cost, 2),
            efficiency_pct=round(eff, 1),
            status_color=color
        ))

    return sorted(results, key=lambda x: x.monthly_cost, reverse=True)
