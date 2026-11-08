"""Write path for agent data. Used by the HTTP ingestion API *and* the demo
generator, so demo data exercises exactly the production code path."""

import datetime

from prometheus_client import Counter
from sqlalchemy.orm import Session

from app.db.platform_models import (
    Autoscaler,
    Cluster,
    Node,
    NodeSample,
    ServiceInv,
    UsageSample,
    Volume,
    Workload,
    utcnow,
)
from app.db.upsert import insert_ignore, upsert
from app.pricing import resolve_node_price
from app.schemas.platform import IngestResult, InventoryIn, NodeSampleIn, SampleIn

INGESTED = Counter("finops_ingested_samples_total", "Usage samples accepted", ["cluster"])
DUPLICATES = Counter("finops_duplicate_samples_total", "Usage samples already stored", ["cluster"])
REJECTED = Counter("finops_rejected_samples_total", "Usage samples rejected", ["cluster", "reason"])

MAX_FUTURE_SKEW = datetime.timedelta(minutes=10)
MAX_SAMPLE_AGE = datetime.timedelta(days=35)


def _naive_utc(ts: datetime.datetime) -> datetime.datetime:
    if ts.tzinfo is not None:
        ts = ts.astimezone(datetime.UTC).replace(tzinfo=None)
    return ts


def ingest_inventory(db: Session, cluster: Cluster, payload: InventoryIn, now: datetime.datetime | None = None,
                     first_seen: datetime.datetime | None = None) -> IngestResult:
    """Upsert nodes (with resolved prices) and workloads; bump last_seen.

    ``first_seen`` lets the demo back-fill pretend the inventory existed earlier.
    """
    now = now or utcnow()
    first_seen = first_seen or now

    node_rows = []
    for n in payload.nodes:
        price = resolve_node_price(
            provider=cluster.provider, region=n.region or cluster.region, instance_type=n.instance_type,
            capacity_type=n.capacity_type, vcpu=n.vcpu, memory_gib=n.memory_gib, reported_hourly=n.hourly_price,
            custom_cpu_hourly=cluster.custom_cpu_hourly, custom_ram_hourly=cluster.custom_ram_hourly,
        )
        node_rows.append(dict(
            cluster_id=cluster.id, name=n.name, instance_type=n.instance_type, capacity_type=n.capacity_type,
            region=n.region or cluster.region, zone=n.zone, vcpu=n.vcpu, memory_gib=n.memory_gib,
            reported_hourly=n.hourly_price, hourly_price=price.hourly, cpu_hourly_per_core=price.cpu_hourly_per_core,
            ram_hourly_per_gib=price.ram_hourly_per_gib, price_source=price.source, labels=n.labels,
            first_seen=min(first_seen, _naive_utc(n.created_at)) if n.created_at else first_seen, last_seen=now,
        ))
    upsert(db, Node, node_rows, ["cluster_id", "name"],
           ["instance_type", "capacity_type", "region", "zone", "vcpu", "memory_gib", "reported_hourly",
            "hourly_price", "cpu_hourly_per_core", "ram_hourly_per_gib", "price_source", "labels", "last_seen"])

    wl_rows = [dict(cluster_id=cluster.id, namespace=w.namespace, kind=w.kind, name=w.name, replicas=w.replicas,
                    labels=w.labels, first_seen=first_seen, last_seen=now) for w in payload.workloads]
    upsert(db, Workload, wl_rows, ["cluster_id", "namespace", "kind", "name"], ["replicas", "labels", "last_seen"])

    ident = ["cluster_id", "namespace", "name"]
    upsert(db, Volume, [dict(
        cluster_id=cluster.id, namespace=v.namespace, name=v.name, storage_class=v.storage_class,
        capacity_gib=v.capacity_gib, phase=v.phase, mounted_by=v.mounted_by, labels=v.labels,
        created_at=_naive_utc(v.created_at) if v.created_at else None, first_seen=first_seen, last_seen=now,
    ) for v in payload.volumes], ident,
        ["storage_class", "capacity_gib", "phase", "mounted_by", "labels", "created_at", "last_seen"])
    upsert(db, ServiceInv, [dict(
        cluster_id=cluster.id, namespace=sv.namespace, name=sv.name, type=sv.type, has_endpoints=sv.has_endpoints,
        labels=sv.labels, created_at=_naive_utc(sv.created_at) if sv.created_at else None,
        first_seen=first_seen, last_seen=now,
    ) for sv in payload.services], ident, ["type", "has_endpoints", "labels", "created_at", "last_seen"])
    upsert(db, Autoscaler, [dict(
        cluster_id=cluster.id, namespace=a.namespace, name=a.name, target_kind=a.target_kind,
        target_name=a.target_name, cpu_target_utilization=a.cpu_target_utilization, min_replicas=a.min_replicas,
        max_replicas=a.max_replicas, first_seen=first_seen, last_seen=now,
    ) for a in payload.autoscalers], ident,
        ["target_kind", "target_name", "cpu_target_utilization", "min_replicas", "max_replicas", "last_seen"])

    cluster.last_seen_at = now
    if payload.agent_version:
        cluster.agent_version = payload.agent_version
    db.commit()
    return IngestResult(accepted=len(node_rows) + len(wl_rows) + len(payload.volumes) + len(payload.services)
                        + len(payload.autoscalers))


def _in_range(ts: datetime.datetime, now: datetime.datetime, enforce_age: bool) -> str | None:
    if ts > now + MAX_FUTURE_SKEW:
        return "future"
    if enforce_age and ts < now - MAX_SAMPLE_AGE:
        return "too_old"
    return None


def ingest_samples(db: Session, cluster: Cluster, samples: list[SampleIn],
                   now: datetime.datetime | None = None, enforce_age: bool = True,
                   node_samples: list[NodeSampleIn] = ()) -> IngestResult:
    """Store container usage and node heartbeat samples idempotently
    (re-sent windows are counted as duplicates, never double-stored)."""
    now = now or utcnow()
    rows, node_rows, rejected = [], [], 0
    for s in samples:
        ts = _naive_utc(s.ts)
        if reason := _in_range(ts, now, enforce_age):
            rejected += 1
            REJECTED.labels(cluster.name, reason).inc()
            continue
        row = s.model_dump()
        row["ts"] = ts
        row["cluster_id"] = cluster.id
        rows.append(row)
    for n in node_samples:
        ts = _naive_utc(n.ts)
        if reason := _in_range(ts, now, enforce_age):
            rejected += 1
            REJECTED.labels(cluster.name, reason).inc()
            continue
        node_rows.append({"ts": ts, "cluster_id": cluster.id, "node": n.node, "duration_seconds": n.duration_seconds})
    detail = [f"{rejected} sample(s) outside the accepted time range were rejected"] if rejected else []

    inserted = insert_ignore(db, UsageSample, rows)
    nodes_inserted = insert_ignore(db, NodeSample, node_rows)
    cluster.last_seen_at = now
    db.commit()

    INGESTED.labels(cluster.name).inc(inserted)
    DUPLICATES.labels(cluster.name).inc(len(rows) - inserted)
    return IngestResult(accepted=inserted, duplicates=len(rows) - inserted, rejected=rejected,
                        node_samples_accepted=nodes_inserted, detail=detail)
