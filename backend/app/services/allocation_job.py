"""Hourly cost allocation job.

For each cluster, allocates every completed hour since its watermark (minus a
short look-back so late samples are included). Each hour is recomputed
atomically (delete + insert), so the job is idempotent and safe to re-run.
"""

import datetime
import logging

from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.platform_models import (
    AllocationWatermark,
    Cluster,
    CostAllocation,
    Node,
    NodeCost,
    NodeSample,
    UsageSample,
    utcnow,
)
from app.engines.allocation import ContainerSample, NodeInfo, allocate

logger = logging.getLogger("allocation")
HOUR = datetime.timedelta(hours=1)
# A node whose inventory heartbeat is this recent counts as alive to window end.
NODE_HEARTBEAT_GRACE = datetime.timedelta(minutes=10)
# Never back-fill more than this per run (bounds the work after long outages).
MAX_WINDOWS_PER_RUN = 24 * 35


def floor_hour(ts: datetime.datetime) -> datetime.datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def _node_infos(db: Session, cluster: Cluster, nodes: list[Node], start: datetime.datetime,
                end: datetime.datetime) -> list[NodeInfo]:
    """Node uptime within the window.

    Preferred: sum of node heartbeat samples (exact for autoscaled / spot
    nodes that come and go). Fallback when an agent sends no heartbeats:
    the overlap of [first_seen, last_seen + grace] with the window.
    """
    uptime = dict(db.query(NodeSample.node, func.sum(NodeSample.duration_seconds)).filter(
        NodeSample.cluster_id == cluster.id, NodeSample.ts >= start, NodeSample.ts < end
    ).group_by(NodeSample.node).all())
    window_h = (end - start).total_seconds() / 3600
    infos = []
    for n in nodes:
        if uptime:
            hours = (uptime.get(n.name) or 0) / 3600
        else:
            alive_until = n.last_seen + NODE_HEARTBEAT_GRACE
            hours = (min(end, alive_until) - max(start, n.first_seen)).total_seconds() / 3600
        if hours <= 0:
            continue
        infos.append(NodeInfo(n.name, n.vcpu, n.memory_gib, n.hourly_price, n.cpu_hourly_per_core,
                              n.ram_hourly_per_gib, min(window_h, hours)))
    return infos


def allocate_window(db: Session, cluster: Cluster, start: datetime.datetime, nodes: list[Node]) -> tuple[int, float]:
    end = start + HOUR
    rows = db.query(UsageSample).filter(
        UsageSample.cluster_id == cluster.id, UsageSample.ts >= start, UsageSample.ts < end
    ).all()
    samples = [
        ContainerSample(
            namespace=r.namespace, pod=r.pod, container=r.container, node=r.node,
            duration_hours=r.duration_seconds / 3600, cpu_request_cores=r.cpu_request_cores,
            cpu_usage_cores=r.cpu_usage_cores, mem_request_bytes=r.mem_request_bytes,
            mem_usage_bytes=r.mem_usage_bytes, workload_kind=r.workload_kind, workload_name=r.workload_name,
        )
        for r in rows
    ]
    result = allocate(_node_infos(db, cluster, nodes, start, end), samples, frozenset(settings.shared_namespaces))

    db.execute(delete(CostAllocation).where(CostAllocation.cluster_id == cluster.id,
                                            CostAllocation.window_start == start))
    db.execute(delete(NodeCost).where(NodeCost.cluster_id == cluster.id, NodeCost.window_start == start))
    node_by_name = {n.name: n for n in nodes}
    db.add_all(
        CostAllocation(
            window_start=start, cluster_id=cluster.id, namespace=c.namespace, pod=c.pod, container=c.container,
            window_hours=1.0, node=c.node, workload_kind=c.workload_kind, workload_name=c.workload_name,
            shared=c.shared, cpu_core_hours=c.cpu_core_hours, ram_gib_hours=c.ram_gib_hours,
            cpu_request_core_hours=c.cpu_request_core_hours, ram_request_gib_hours=c.ram_request_gib_hours,
            cpu_usage_core_hours=c.cpu_usage_core_hours, ram_usage_gib_hours=c.ram_usage_gib_hours,
            cpu_cost=c.cpu_cost, ram_cost=c.ram_cost, cpu_usage_cost=c.cpu_usage_cost,
            ram_usage_cost=c.ram_usage_cost, total_cost=c.total_cost,
        )
        for c in result.containers
    )
    db.add_all(
        NodeCost(
            window_start=start, cluster_id=cluster.id, node=n.node, hourly_price=node_by_name[n.node].hourly_price,
            price_source=node_by_name[n.node].price_source, total_cost=n.total_cost, cpu_cost=n.cpu_cost,
            ram_cost=n.ram_cost, idle_cpu_cost=n.idle_cpu_cost, idle_ram_cost=n.idle_ram_cost,
        )
        for n in result.nodes
    )
    return len(result.containers), result.total_cost


def run_allocation_for_cluster(db: Session, cluster: Cluster, now: datetime.datetime | None = None) -> int:
    """Allocate pending windows for one cluster. Returns the number of windows written."""
    now = now or utcnow()
    last_complete = floor_hour(now) - HOUR
    wm = db.get(AllocationWatermark, cluster.id)
    if wm is not None:
        start = wm.last_window_start - datetime.timedelta(hours=settings.allocation_lookback_hours - 1)
    else:
        # Start at whatever came first: a sample, a node heartbeat, or a known
        # node's creation. (Starting at the first sample would skip hours in
        # which nodes already cost money, and a later run would add them.)
        candidates = [
            db.query(func.min(UsageSample.ts)).filter(UsageSample.cluster_id == cluster.id).scalar(),
            db.query(func.min(NodeSample.ts)).filter(NodeSample.cluster_id == cluster.id).scalar(),
            db.query(func.min(Node.first_seen)).filter(Node.cluster_id == cluster.id).scalar(),
        ]
        candidates = [c for c in candidates if c is not None]
        if not candidates:
            return 0
        start = floor_hour(min(candidates))
    start = max(start, last_complete - HOUR * (MAX_WINDOWS_PER_RUN - 1))

    nodes = db.query(Node).filter(Node.cluster_id == cluster.id).all()
    windows = 0
    window = start
    while window <= last_complete:
        allocate_window(db, cluster, window, nodes)
        windows += 1
        window += HOUR
    if windows:
        if wm is None:
            db.add(AllocationWatermark(cluster_id=cluster.id, last_window_start=last_complete))
        else:
            wm.last_window_start = last_complete
        db.commit()
    return windows


def run_allocation(db: Session, now: datetime.datetime | None = None) -> int:
    total = 0
    for cluster in db.query(Cluster).filter(Cluster.is_active.is_(True)).all():
        try:
            total += run_allocation_for_cluster(db, cluster, now)
        except Exception:
            db.rollback()
            logger.exception("Allocation failed for cluster %s", cluster.name)
    return total
