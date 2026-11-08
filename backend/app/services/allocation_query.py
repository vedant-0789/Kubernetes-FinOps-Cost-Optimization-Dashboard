"""Read side of cost allocation: reports, time series and summaries.

Aggregation runs in SQL (GROUP BY) so it scales with the hypertables; only
label-based grouping does a small in-memory join against the workloads table.
"""

import datetime
import re
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.platform_models import (
    AllocationWatermark,
    Cluster,
    CostAllocation,
    Node,
    NodeCost,
    NodeSample,
    Workload,
    utcnow,
)
from app.schemas.platform import AllocationItem, AllocationReport, ClusterOut, ClusterSummary, TimeseriesPoint
from app.services.allocation_job import floor_hour

IDLE, SHARED, UNALLOCATED = "__idle__", "__shared__", "__unallocated__"
_WINDOW = re.compile(r"^(\d{1,4})([hd])$")
SUM_FIELDS = ("cpu_cost", "ram_cost", "cpu_usage_cost", "ram_usage_cost", "cpu_core_hours", "ram_gib_hours",
              "total_cost")


def parse_window(window: str, now: datetime.datetime | None = None) -> tuple[datetime.datetime, datetime.datetime]:
    m = _WINDOW.match(window)
    if not m:
        raise HTTPException(422, "window must look like 24h, 7d or 30d")
    n, unit = int(m.group(1)), m.group(2)
    delta = datetime.timedelta(hours=n) if unit == "h" else datetime.timedelta(days=n)
    if delta > datetime.timedelta(days=400):
        raise HTTPException(422, "window may not exceed 400d")
    end = floor_hour(now or utcnow())
    return end - delta, end


def _group_columns(aggregate: str):
    C = CostAllocation
    if aggregate == "namespace":
        return [C.namespace]
    if aggregate == "workload" or aggregate.startswith("label:"):
        return [C.namespace, C.workload_kind, C.workload_name]
    if aggregate == "node":
        return [C.node]
    if aggregate == "pod":
        return [C.namespace, C.pod]
    if aggregate == "cluster":
        return []
    raise HTTPException(422,
                        "aggregate must be one of: cluster, namespace, workload, node, pod, label:<key>")


def _labeller(db: Session, cluster_id: str, aggregate: str):
    if aggregate.startswith("label:"):
        key = aggregate.split(":", 1)[1]
        if not key:
            raise HTTPException(422, "label key missing")
        labels = {(w.namespace, w.kind, w.name): (w.labels or {})
                  for w in db.query(Workload).filter(Workload.cluster_id == cluster_id)}
        return lambda g: labels.get((g[0], g[1], g[2]), {}).get(key, UNALLOCATED)
    if aggregate == "workload":
        return lambda g: f"{g[0]}/{(g[1] or 'Pod')}/{g[2] or UNALLOCATED}"
    if aggregate == "pod":
        return lambda g: f"{g[0]}/{g[1]}"
    if aggregate == "cluster":
        return lambda g: "cluster"
    return lambda g: g[0] or UNALLOCATED


def _ratio(a: float, b: float) -> float:
    return round(min(1.0, a / b), 4) if b > 0 else 0.0


def _item(name: str, v: dict, shared_added: float = 0.0) -> AllocationItem:
    usage = v["cpu_usage_cost"] + v["ram_usage_cost"]
    return AllocationItem(
        name=name, cpu_cost=round(v["cpu_cost"], 4), ram_cost=round(v["ram_cost"], 4),
        total_cost=round(v["total_cost"] + shared_added, 4), cpu_core_hours=round(v["cpu_core_hours"], 3),
        ram_gib_hours=round(v["ram_gib_hours"], 3), cpu_efficiency=_ratio(v["cpu_usage_cost"], v["cpu_cost"]),
        ram_efficiency=_ratio(v["ram_usage_cost"], v["ram_cost"]), efficiency=_ratio(usage, v["total_cost"]),
        shared_cost_added=round(shared_added, 4),
    )


def idle_cost(db: Session, cluster_id: str, start, end) -> float:
    total = db.query(func.coalesce(func.sum(NodeCost.idle_cpu_cost + NodeCost.idle_ram_cost), 0.0)).filter(
        NodeCost.cluster_id == cluster_id, NodeCost.window_start >= start, NodeCost.window_start < end).scalar()
    return float(total or 0.0)


def allocation_report(db: Session, cluster: Cluster, window: str, aggregate: str, shared_mode: str,
                      include_idle: bool, now: datetime.datetime | None = None) -> AllocationReport:
    start, end = parse_window(window, now)
    cols = _group_columns(aggregate)
    C = CostAllocation
    q = db.query(*cols, C.shared, *[func.sum(getattr(C, f)).label(f) for f in SUM_FIELDS]).filter(
        C.cluster_id == cluster.id, C.window_start >= start, C.window_start < end)
    if cols:
        q = q.group_by(*cols, C.shared)
    else:
        q = q.group_by(C.shared)

    name_of = _labeller(db, cluster.id, aggregate)
    groups: dict[str, dict] = defaultdict(lambda: dict.fromkeys(SUM_FIELDS, 0.0))
    shared_totals = dict.fromkeys(SUM_FIELDS, 0.0)
    for row in q.all():
        g = tuple(row[: len(cols)])
        is_shared = row[len(cols)]
        values = {f: float(getattr(row, f) or 0.0) for f in SUM_FIELDS}
        target = shared_totals if is_shared else groups[name_of(g)]
        for f in SUM_FIELDS:
            target[f] += values[f]

    shared_cost = shared_totals["total_cost"]
    items: list[AllocationItem] = []
    tenant_total = sum(v["total_cost"] for v in groups.values())
    for name, v in groups.items():
        added = shared_cost * v["total_cost"] / tenant_total if shared_mode == "distribute" and tenant_total else 0.0
        items.append(_item(name, v, added))
    if shared_cost and (shared_mode == "separate" or not tenant_total):
        items.append(_item(SHARED, shared_totals))

    idle = idle_cost(db, cluster.id, start, end)
    if include_idle and idle > 0:
        items.append(AllocationItem(name=IDLE, cpu_cost=0, ram_cost=0, total_cost=round(idle, 4), cpu_core_hours=0,
                                    ram_gib_hours=0, cpu_efficiency=0, ram_efficiency=0, efficiency=0))
    items.sort(key=lambda i: i.total_cost, reverse=True)

    allocated = tenant_total + shared_cost
    usage = sum(v["cpu_usage_cost"] + v["ram_usage_cost"] for v in groups.values()) + \
        shared_totals["cpu_usage_cost"] + shared_totals["ram_usage_cost"]
    total = allocated + idle
    return AllocationReport(
        cluster_id=cluster.id, window_start=start, window_end=end, aggregate=aggregate, shared_mode=shared_mode,
        total_cost=round(total, 4), allocated_cost=round(allocated, 4), idle_cost=round(idle, 4),
        shared_cost=round(shared_cost, 4), efficiency=_ratio(usage, total), items=items,
    )


def cost_timeseries(db: Session, cluster: Cluster, window: str, step: str, top: int = 6,
                    now: datetime.datetime | None = None) -> list[TimeseriesPoint]:
    start, end = parse_window(window, now)
    if step not in ("1h", "1d"):
        raise HTTPException(422, "step must be 1h or 1d")

    def bucket(ts: datetime.datetime) -> datetime.datetime:
        return ts if step == "1h" else ts.replace(hour=0)

    C = CostAllocation
    rows = db.query(C.window_start, C.namespace, func.sum(C.total_cost)).filter(
        C.cluster_id == cluster.id, C.window_start >= start, C.window_start < end
    ).group_by(C.window_start, C.namespace).all()
    idle_rows = db.query(NodeCost.window_start, func.sum(NodeCost.idle_cpu_cost + NodeCost.idle_ram_cost)).filter(
        NodeCost.cluster_id == cluster.id, NodeCost.window_start >= start, NodeCost.window_start < end
    ).group_by(NodeCost.window_start).all()

    ns_totals: dict[str, float] = defaultdict(float)
    for _, ns, cost in rows:
        ns_totals[ns] += cost or 0.0
    keep = set(sorted(ns_totals, key=ns_totals.get, reverse=True)[:top])

    points: dict[datetime.datetime, dict] = defaultdict(lambda: {"by": defaultdict(float), "idle": 0.0})
    for ts, ns, cost in rows:
        points[bucket(ts)]["by"][ns if ns in keep else "other"] += cost or 0.0
    for ts, idle in idle_rows:
        points[bucket(ts)]["idle"] += idle or 0.0

    return [
        TimeseriesPoint(start=ts, total_cost=round(sum(p["by"].values()) + p["idle"], 4),
                        idle_cost=round(p["idle"], 4), by_group={k: round(v, 4) for k, v in p["by"].items()})
        for ts, p in sorted(points.items())
    ]


def cluster_summary(db: Session, cluster: Cluster, now: datetime.datetime | None = None) -> ClusterSummary:
    report = allocation_report(db, cluster, "24h", "cluster", "separate", True, now)
    now = now or utcnow()
    cutoff = now - datetime.timedelta(hours=1)
    # "Running now" = heartbeat in the last 15 minutes when the agent sends
    # heartbeats; otherwise inventory seen in the last hour.
    recent = {n for (n,) in db.query(NodeSample.node).filter(
        NodeSample.cluster_id == cluster.id, NodeSample.ts >= now - datetime.timedelta(minutes=15)).distinct()}
    candidates = db.query(Node).filter(Node.cluster_id == cluster.id, Node.last_seen >= cutoff).all()
    live_nodes = [n for n in candidates if n.name in recent] if recent else candidates
    workloads = db.query(func.count(Workload.id)).filter(
        Workload.cluster_id == cluster.id, Workload.last_seen >= cutoff).scalar()
    hourly = sum(n.hourly_price for n in live_nodes)
    wm = db.get(AllocationWatermark, cluster.id)
    return ClusterSummary(
        cluster=ClusterOut.model_validate(cluster), nodes=len(live_nodes),
        spot_nodes=sum(1 for n in live_nodes if n.capacity_type == "spot"), workloads=workloads or 0,
        hourly_run_rate=round(hourly, 4), monthly_run_rate=round(hourly * 730, 2),
        cost_last_24h=report.total_cost, idle_cost_last_24h=report.idle_cost,
        idle_pct=_ratio(report.idle_cost, report.total_cost), efficiency=report.efficiency,
        last_allocated_window=wm.last_window_start if wm else None,
    )
