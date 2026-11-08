"""Right-sizing + waste analysis job.

Per cluster, over the analysis window:
1. pool container samples per workload/container (all replicas together);
2. detect idle workloads first; an idle workload gets an IDLE_WORKLOAD
   finding and **no** right-sizing recommendation (its whole cost is the
   saving), so savings never overlap;
3. right-size every other container with the configured strategy, pricing
   the change at the workload's *effective* unit prices from allocation;
4. detect orphaned volumes, unused load balancers, consolidatable nodes;
5. upsert results: keep dismissed items dismissed, resolve items that are
   no longer detected.
"""

import datetime
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.platform_models import (
    AnalysisRun,
    Autoscaler,
    Cluster,
    CostAllocation,
    Node,
    NodeSample,
    RightsizingRecommendation,
    ServiceInv,
    UsageSample,
    Volume,
    WasteFinding,
    utcnow,
)
from app.engines import rightsizing as rs
from app.engines import waste as wst
from app.pricing import DEFAULT_CPU_HOURLY, DEFAULT_RAM_HOURLY, load_balancer_hourly, storage_price_gib_month

logger = logging.getLogger("analysis")
GIB = 1024**3
RECENT = datetime.timedelta(hours=1)
HOURS_PER_MONTH = 730.0


@dataclass
class ContainerSeries:
    points: list[rs.UsagePoint] = field(default_factory=list)
    latest_ts: datetime.datetime | None = None
    spec_row: tuple | None = None                     # requests/limits at the latest sample
    pods_per_slot: dict = field(default_factory=lambda: defaultdict(set))


@dataclass
class WorkloadAgg:
    slots: dict = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0, 0.0]))  # ts -> cpu, mem, net
    first: datetime.datetime | None = None
    last: datetime.datetime | None = None


_EPOCH = datetime.datetime(1970, 1, 1)


def _epoch(ts: datetime.datetime) -> float:
    return (ts - _EPOCH).total_seconds()  # naive UTC -> epoch, no tz object per row


def _load_series(db: Session, cluster: Cluster, since: datetime.datetime):
    S = UsageSample
    cols = (S.ts, S.namespace, S.pod, S.container, S.workload_kind, S.workload_name, S.duration_seconds,
            S.cpu_request_cores, S.cpu_limit_cores, S.cpu_usage_cores, S.cpu_usage_max_cores,
            S.cpu_throttled_seconds, S.mem_request_bytes, S.mem_limit_bytes, S.mem_usage_bytes,
            S.mem_usage_max_bytes, S.net_rx_bytes, S.net_tx_bytes, S.oom_kills)
    containers: dict[tuple, ContainerSeries] = defaultdict(ContainerSeries)
    workloads: dict[tuple, WorkloadAgg] = defaultdict(WorkloadAgg)
    q = db.query(*cols).filter(S.cluster_id == cluster.id, S.ts >= since).order_by(S.ts).yield_per(5000)
    for r in q:
        wkey = (r.namespace, r.workload_kind or "Pod", r.workload_name or r.pod)
        c = containers[(*wkey, r.container)]
        c.points.append(rs.UsagePoint(
            ts=_epoch(r.ts), cpu_mean=r.cpu_usage_cores, mem_mean=r.mem_usage_bytes, cpu_peak=r.cpu_usage_max_cores,
            mem_peak=r.mem_usage_max_bytes, throttled_seconds=r.cpu_throttled_seconds,
            duration_seconds=r.duration_seconds, oom_kills=r.oom_kills))
        c.latest_ts = r.ts
        c.spec_row = (r.cpu_request_cores, r.mem_request_bytes, r.cpu_limit_cores, r.mem_limit_bytes)
        c.pods_per_slot[r.ts].add(r.pod)
        w = workloads[wkey]
        slot = w.slots[r.ts]
        slot[0] += r.cpu_usage_cores
        slot[1] += r.mem_usage_bytes
        slot[2] += r.net_rx_bytes + r.net_tx_bytes
        w.first = w.first or r.ts
        w.last = r.ts
    return containers, workloads


def _unit_prices(db: Session, cluster: Cluster, since: datetime.datetime) -> tuple[dict, dict, tuple[float, float]]:
    """Effective $/core-hour and $/GiB-hour per workload (from allocation), plus
    the cluster average as a fallback."""
    C = CostAllocation
    rows = db.query(C.namespace, C.workload_kind, C.workload_name, func.sum(C.cpu_cost), func.sum(C.cpu_core_hours),
                    func.sum(C.ram_cost), func.sum(C.ram_gib_hours), func.sum(C.total_cost),
                    func.count(func.distinct(C.window_start))) \
        .filter(C.cluster_id == cluster.id, C.window_start >= since) \
        .group_by(C.namespace, C.workload_kind, C.workload_name).all()
    prices, monthly_cost = {}, {}
    tot = [0.0, 0.0, 0.0, 0.0]
    for ns, kind, name, cpu_cost, cpu_h, ram_cost, ram_h, total, hours in rows:
        key = (ns, kind or "Pod", name)
        prices[key] = ((cpu_cost / cpu_h) if cpu_h else None, (ram_cost / ram_h) if ram_h else None)
        monthly_cost[key] = (total or 0.0) / max(hours or 1, 1) * HOURS_PER_MONTH
        tot = [tot[0] + (cpu_cost or 0), tot[1] + (cpu_h or 0), tot[2] + (ram_cost or 0), tot[3] + (ram_h or 0)]
    avg = (tot[0] / tot[1] if tot[1] else DEFAULT_CPU_HOURLY, tot[2] / tot[3] if tot[3] else DEFAULT_RAM_HOURLY)
    return prices, monthly_cost, avg


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, int(q * len(v)))]


def analyze_cluster(db: Session, cluster: Cluster, now: datetime.datetime | None = None,
                    strategy: str | None = None, policy: rs.Policy = rs.DEFAULT_POLICY,
                    waste_policy: wst.WastePolicy = wst.WastePolicy()) -> dict:
    started = time.perf_counter()
    now = now or utcnow()
    strategy = strategy or settings.rightsizing_strategy
    since = now - datetime.timedelta(days=settings.analysis_window_days)
    containers, workloads = _load_series(db, cluster, since)
    prices, monthly_cost, avg_price = _unit_prices(db, cluster, now - datetime.timedelta(days=7))
    hpas = {(a.namespace, a.target_kind, a.target_name): a.cpu_target_utilization
            for a in db.query(Autoscaler).filter(Autoscaler.cluster_id == cluster.id,
                                                 Autoscaler.last_seen >= now - RECENT)}
    live_cutoff = max((c.latest_ts for c in containers.values() if c.latest_ts), default=now) - \
        datetime.timedelta(minutes=30)

    # 1. idle workloads -------------------------------------------------------------
    usage = []
    for (ns, kind, name), w in workloads.items():
        if w.last is None or w.last < live_cutoff:
            continue   # workload gone: nothing to save any more
        latest_req = sum(c.spec_row[0] for k, c in containers.items()
                         if k[:3] == (ns, kind, name) and c.latest_ts == w.last)
        latest_mem = sum(c.spec_row[1] for k, c in containers.items()
                         if k[:3] == (ns, kind, name) and c.latest_ts == w.last)
        hours = (w.last - w.first).total_seconds() / 3600 + 5 / 60
        cpu_vals = [s[0] for s in w.slots.values()]
        mem_vals = [s[1] for s in w.slots.values()]
        net_total = sum(s[2] for s in w.slots.values())
        usage.append(wst.WorkloadUsage(ns, kind, name, hours, latest_req, latest_mem / GIB, _quantile(cpu_vals, 0.95),
                                       _quantile(mem_vals, 0.95) / GIB, net_total / max(hours, 1e-6),
                                       monthly_cost.get((ns, kind, name), 0.0)))
    findings = wst.detect_idle_workloads(usage, waste_policy)
    idle_keys = {(f.namespace, f.evidence["workload_kind"], f.evidence["workload_name"]) for f in findings}

    # 2. right-sizing (non-idle, still running) ------------------------------------------
    recs = []
    for key, c in containers.items():
        ns, kind, name, container = key
        if (ns, kind, name) in idle_keys or c.latest_ts is None or c.latest_ts < live_cutoff:
            continue
        recent_slots = [s for s in c.pods_per_slot if s >= c.latest_ts - datetime.timedelta(hours=24)]
        replicas = sum(len(c.pods_per_slot[s]) for s in recent_slots) / max(len(recent_slots), 1)
        cpu_req, mem_req, cpu_lim, mem_lim = c.spec_row
        spec = rs.ContainerSpec(cpu_req, mem_req, cpu_lim, mem_lim, replicas, hpas.get((ns, kind, name)))
        rec = rs.recommend(c.points, spec, strategy, policy)
        if rec.action not in ("downsize", "upsize"):
            continue
        cpu_p, ram_p = prices.get((ns, kind, name), (None, None))
        delta = rec.monthly_delta(spec, cpu_p or avg_price[0], ram_p or avg_price[1])
        if rec.action == "downsize" and delta < settings.min_monthly_savings:
            continue
        recs.append((key, spec, rec, delta))

    # 3. other waste -----------------------------------------------------------------
    vols = [wst.Volume(v.namespace, v.name, v.storage_class, v.capacity_gib, bool(v.mounted_by),
                       (now - (v.created_at or v.first_seen)).total_seconds() / 3600, v.phase)
            for v in db.query(Volume).filter(Volume.cluster_id == cluster.id, Volume.last_seen >= now - RECENT)]
    findings += wst.detect_orphaned_volumes(vols, lambda sc: storage_price_gib_month(cluster.provider, sc),
                                            waste_policy)
    lbs = [wst.LoadBalancer(s.namespace, s.name, s.has_endpoints,
                            (now - (s.created_at or s.first_seen)).total_seconds() / 3600)
           for s in db.query(ServiceInv).filter(ServiceInv.cluster_id == cluster.id, ServiceInv.type == "LoadBalancer",
                                                ServiceInv.last_seen >= now - RECENT)]
    findings += wst.detect_unused_load_balancers(lbs, load_balancer_hourly(cluster.provider), waste_policy)
    findings += wst.detect_underutilized_nodes(_node_loads(db, cluster, containers, now), waste_policy)

    _persist(db, cluster, strategy, recs, findings, now)
    db.merge(AnalysisRun(cluster_id=cluster.id, last_run_at=now,
                         duration_ms=int((time.perf_counter() - started) * 1000),
                         containers_analyzed=len(containers)))
    db.commit()
    return {"containers": len(containers), "recommendations": len(recs), "findings": len(findings)}


def _node_loads(db: Session, cluster: Cluster, containers: dict, now: datetime.datetime) -> list[wst.NodeLoad]:
    """Requests per node at the latest slot (from samples), for running nodes."""
    latest = max((c.latest_ts for c in containers.values() if c.latest_ts), default=None)
    if latest is None:
        return []
    S = UsageSample
    req = dict(((n, (cpu or 0.0, mem or 0.0)) for n, cpu, mem in db.query(
        S.node, func.sum(S.cpu_request_cores), func.sum(S.mem_request_bytes)).filter(
        S.cluster_id == cluster.id, S.ts == latest).group_by(S.node)))
    beating = {n for (n,) in db.query(NodeSample.node).filter(
        NodeSample.cluster_id == cluster.id, NodeSample.ts >= latest - datetime.timedelta(minutes=15)).distinct()}
    nodes = db.query(Node).filter(Node.cluster_id == cluster.id, Node.last_seen >= now - RECENT).all()
    if beating:
        nodes = [n for n in nodes if n.name in beating]
    return [wst.NodeLoad(n.name, n.vcpu, n.memory_gib, req.get(n.name, (0, 0))[0], req.get(n.name, (0, 0))[1] / GIB,
                         n.hourly_price, n.capacity_type) for n in nodes]


def _persist(db: Session, cluster: Cluster, strategy: str, recs, findings, now: datetime.datetime) -> None:
    R = RightsizingRecommendation
    existing = {(r.namespace, r.workload_kind, r.workload_name, r.container): r
                for r in db.query(R).filter(R.cluster_id == cluster.id, R.strategy == strategy)}
    seen = set()
    for key, spec, rec, delta in recs:
        seen.add(key)
        values = dict(
            action=rec.action, replicas=spec.replicas, current_cpu_request=spec.cpu_request,
            current_mem_request=spec.mem_request, current_cpu_limit=spec.cpu_limit, current_mem_limit=spec.mem_limit,
            recommended_cpu_request=rec.cpu_request, recommended_mem_request=rec.mem_request,
            recommended_cpu_limit=rec.cpu_limit, recommended_mem_limit=rec.mem_limit,
            monthly_savings=round(delta, 2), confidence=rec.confidence, confidence_label=rec.confidence_label,
            risk=rec.risk, reasons=rec.reasons, evidence=rec.evidence, updated_at=now,
        )
        row = existing.get(key)
        if row is None:
            db.add(R(cluster_id=cluster.id, namespace=key[0], workload_kind=key[1], workload_name=key[2],
                     container=key[3], strategy=strategy, status="open", created_at=now, **values))
        elif row.status == "dismissed":
            continue   # respect the user's decision
        else:
            for k, v in values.items():
                setattr(row, k, v)
            row.status = "open"
    for key, row in existing.items():
        if key not in seen and row.status == "open":
            row.status, row.updated_at = "resolved", now

    W = WasteFinding
    existing_f = {(f.kind, f.namespace, f.name): f for f in db.query(W).filter(W.cluster_id == cluster.id)}
    seen_f = set()
    for f in findings:
        key = (f.kind, f.namespace or "", f.name)
        seen_f.add(key)
        row = existing_f.get(key)
        if row is None:
            db.add(W(cluster_id=cluster.id, kind=f.kind, namespace=f.namespace or "", name=f.name, status="open",
                     monthly_savings=f.monthly_savings, risk=f.risk, action=f.action, evidence=f.evidence,
                     first_detected=now, last_detected=now))
            continue
        row.monthly_savings, row.risk, row.action, row.evidence, row.last_detected = (
            f.monthly_savings, f.risk, f.action, f.evidence, now)
        if row.status == "resolved":
            row.status, row.resolved_at = "open", None
    for key, row in existing_f.items():
        if key not in seen_f and row.status == "open":
            row.status, row.resolved_at = "resolved", now


def run_analysis(db: Session, now: datetime.datetime | None = None) -> int:
    done = 0
    for cluster in db.query(Cluster).filter(Cluster.is_active.is_(True)).all():
        try:
            analyze_cluster(db, cluster, now)
            done += 1
        except Exception:
            db.rollback()
            logger.exception("Analysis failed for cluster %s", cluster.name)
    return done


def savings_summary(db: Session, cluster: Cluster) -> dict:
    """Non-overlapping potential savings. Node consolidation is reported
    separately because it overlaps with right-sizing (smaller requests are
    what frees the node)."""
    recs = db.query(RightsizingRecommendation).filter(
        RightsizingRecommendation.cluster_id == cluster.id, RightsizingRecommendation.status == "open",
        RightsizingRecommendation.strategy == settings.rightsizing_strategy).all()
    finds = db.query(WasteFinding).filter(WasteFinding.cluster_id == cluster.id, WasteFinding.status == "open").all()
    by_kind: dict[str, dict] = defaultdict(lambda: {"count": 0, "monthly_savings": 0.0})
    for f in finds:
        by_kind[f.kind]["count"] += 1
        by_kind[f.kind]["monthly_savings"] += f.monthly_savings
    down = [r for r in recs if r.action == "downsize"]
    up = [r for r in recs if r.action == "upsize"]
    additive = sum(r.monthly_savings for r in down) + sum(
        v["monthly_savings"] for k, v in by_kind.items() if k != "UNDERUTILIZED_NODE")
    run = db.get(AnalysisRun, cluster.id)
    return {
        "total_monthly_savings": round(additive, 2),
        "rightsizing": {"count": len(down), "monthly_savings": round(sum(r.monthly_savings for r in down), 2)},
        "reliability_fixes": {"count": len(up), "monthly_cost": round(-sum(r.monthly_savings for r in up), 2)},
        "waste": {k: {"count": v["count"], "monthly_savings": round(v["monthly_savings"], 2)}
                  for k, v in sorted(by_kind.items())},
        "overlapping": ["UNDERUTILIZED_NODE"],
        "strategy": settings.rightsizing_strategy,
        "last_analysis_at": run.last_run_at if run else None,
    }
