"""Synthetic demo cluster with realistic usage, fed through the real ingestion path.

The workload mix models a small e-commerce company on AWS: daily traffic
waves and quieter weekends, noisy and spiky services, a nightly batch job, a
memory leak that ends in OOM kills, over-provisioned services, two forgotten
idle workloads, shared platform namespaces, and a lightly packed spot node.
Everything is deterministic (seeded by workload and time slot), so the same
history is generated on every run, and live samples continue it seamlessly.
"""

import datetime
import logging
import math
import random
import zlib
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import new_agent_token
from app.db.platform_models import Cluster, UsageSample, utcnow
from app.schemas.platform import (
    AutoscalerIn,
    InventoryIn,
    NodeIn,
    NodeSampleIn,
    SampleIn,
    ServiceIn,
    VolumeIn,
    WorkloadIn,
)
from app.services.ingestion import ingest_inventory, ingest_samples

logger = logging.getLogger("demo")

DEMO_CLUSTER_NAME = "demo-aws-prod"
SLOT = datetime.timedelta(minutes=5)
GIB = 1024**3
SLOTS_PER_CHUNK = 288  # one day of samples per ingestion call


@dataclass(frozen=True)
class DemoNode:
    name: str
    instance_type: str
    vcpu: float
    memory_gib: float
    capacity_type: str = "on_demand"
    zone: str = "us-east-1a"
    peak_only: bool = False      # added by the autoscaler on weekdays 08-20 UTC
    incident_only: bool = False  # only during the runaway-load-test incident


@dataclass(frozen=True)
class DemoWorkload:
    namespace: str
    kind: str
    name: str
    replicas: int
    cpu_req: float
    mem_req_gib: float
    cpu_use: float               # mean cores at the daily average
    mem_use_gib: float
    labels: dict = field(default_factory=dict)
    diurnal: float = 0.0         # amplitude of the daily wave (0..1)
    weekend: float = 1.0         # multiplier on Sat/Sun
    noise: float = 0.05          # relative std-dev per slot
    spike_prob: float = 0.0      # chance a slot is a spike
    spike_mult: float = 1.0
    night_batch: bool = False    # runs 01:00-04:00 UTC only
    leak_gib_per_hour: float = 0.0
    cpu_limit: float | None = None
    mem_limit_gib: float | None = None
    net_kbps: float = 50.0
    nodes: tuple[str, ...] = ()  # one per replica (DaemonSets: all nodes)
    pod_offset: int = 0          # extra replicas of an existing workload (HPA scale-out)
    peak_only: bool = False
    incident_only: bool = False


NODES = [
    DemoNode("ip-10-0-1-11", "m5.2xlarge", 8, 32),
    DemoNode("ip-10-0-1-12", "m5.2xlarge", 8, 32, zone="us-east-1b"),
    DemoNode("ip-10-0-2-21", "r5.2xlarge", 8, 64),
    DemoNode("ip-10-0-3-31", "c5.2xlarge", 8, 16, capacity_type="spot", zone="us-east-1c"),
    DemoNode("ip-10-0-3-32", "c5.2xlarge", 8, 16, capacity_type="spot", zone="us-east-1c"),
    DemoNode("ip-10-0-4-41", "m5.2xlarge", 8, 32, zone="us-east-1b", peak_only=True),
    # Scaled out by the cluster autoscaler for the runaway load test (cost incident).
    DemoNode("ip-10-0-5-51", "c5.4xlarge", 16, 32, zone="us-east-1a", incident_only=True),
    DemoNode("ip-10-0-5-52", "c5.4xlarge", 16, 32, zone="us-east-1b", incident_only=True),
]
ALL_NODES = tuple(n.name for n in NODES)


def _l(team, cc, env="prod"):
    return {"team": team, "cost-center": cc, "env": env}


WORKLOADS = [
    DemoWorkload("storefront", "Deployment", "frontend-web", 3, 1.0, 2, 0.45, 1.1, _l("web", "cc-100"),
                 diurnal=0.6, weekend=0.7, noise=0.08, cpu_limit=2, mem_limit_gib=3, net_kbps=900,
                 nodes=("ip-10-0-1-11", "ip-10-0-1-12", "ip-10-0-3-31")),
    # HPA scale-out during weekday peaks, scheduled onto the autoscaled node.
    DemoWorkload("storefront", "Deployment", "frontend-web", 2, 1.0, 2, 0.55, 1.2, _l("web", "cc-100"),
                 diurnal=0.4, noise=0.08, cpu_limit=2, mem_limit_gib=3, net_kbps=900,
                 nodes=("ip-10-0-4-41", "ip-10-0-4-41"), pod_offset=3, peak_only=True),
    DemoWorkload("storefront", "Deployment", "checkout-api", 2, 2.0, 4, 0.45, 1.3, _l("payments", "cc-200"),
                 diurnal=0.3, noise=0.10, spike_prob=0.02, spike_mult=2.5, cpu_limit=3, mem_limit_gib=6,
                 net_kbps=300, nodes=("ip-10-0-4-41", "ip-10-0-4-41"), pod_offset=2, peak_only=True),
    DemoWorkload("storefront", "Deployment", "checkout-api", 2, 2.0, 4, 0.30, 1.2, _l("payments", "cc-200"),
                 diurnal=0.5, weekend=0.8, noise=0.10, spike_prob=0.02, spike_mult=2.5, cpu_limit=3,
                 mem_limit_gib=6, net_kbps=300, nodes=("ip-10-0-1-11", "ip-10-0-1-12")),
    DemoWorkload("payments", "Deployment", "payment-gateway", 2, 1.0, 2, 0.55, 1.5, _l("payments", "cc-200"),
                 diurnal=0.5, weekend=0.8, noise=0.06, cpu_limit=1.2, mem_limit_gib=2.5, net_kbps=250,
                 nodes=("ip-10-0-1-11", "ip-10-0-1-12")),
    DemoWorkload("payments", "Deployment", "ledger-worker", 1, 4.0, 16, 0.35, 2.4, _l("payments", "cc-200"),
                 diurnal=0.2, noise=0.05, net_kbps=60, nodes=("ip-10-0-2-21",)),
    DemoWorkload("search", "StatefulSet", "search-api", 2, 2.0, 8, 1.2, 6.0, _l("search", "cc-300"),
                 diurnal=0.4, weekend=0.85, noise=0.15, spike_prob=0.04, spike_mult=1.8, cpu_limit=2.5,
                 mem_limit_gib=10, net_kbps=600, nodes=("ip-10-0-1-11", "ip-10-0-1-12")),
    DemoWorkload("data", "Deployment", "nightly-etl", 1, 4.0, 6, 3.2, 5.0, _l("data", "cc-400"),
                 night_batch=True, noise=0.05, net_kbps=1200, nodes=("ip-10-0-3-31",)),
    DemoWorkload("data", "Deployment", "report-generator", 1, 2.0, 4, 0.004, 0.10, _l("data", "cc-400"),
                 noise=0.2, net_kbps=0.02, nodes=("ip-10-0-2-21",)),
    DemoWorkload("staging", "Deployment", "legacy-qa-testbench", 1, 2.0, 4, 0.006, 0.12,
                 _l("qa", "cc-500", "staging"), noise=0.2, net_kbps=0.05, nodes=("ip-10-0-3-32",)),
    DemoWorkload("ml", "Deployment", "recommender-inference", 2, 1.5, 6, 0.9, 3.0, _l("ml", "cc-600"),
                 diurnal=0.45, weekend=0.75, noise=0.07, leak_gib_per_hour=0.12, cpu_limit=2, mem_limit_gib=6,
                 net_kbps=200, nodes=("ip-10-0-1-12", "ip-10-0-3-31")),
    # Cost incident: a load test someone forgot to stop pins two extra nodes for 14 h.
    DemoWorkload("staging", "Deployment", "runaway-loadtest", 4, 7.0, 12, 6.6, 9.0, _l("qa", "cc-500", "staging"),
                 noise=0.03, net_kbps=5000, nodes=("ip-10-0-5-51", "ip-10-0-5-51", "ip-10-0-5-52", "ip-10-0-5-52"),
                 incident_only=True),
    DemoWorkload("kube-system", "Deployment", "coredns", 2, 0.1, 0.07, 0.03, 0.03, _l("platform", "cc-900"),
                 diurnal=0.3, noise=0.1, net_kbps=80, nodes=("ip-10-0-1-11", "ip-10-0-2-21")),
    DemoWorkload("kube-system", "DaemonSet", "kube-proxy", len(ALL_NODES), 0.1, 0.13, 0.02, 0.05,
                 _l("platform", "cc-900"), noise=0.1, net_kbps=30, nodes=ALL_NODES),
    DemoWorkload("monitoring", "StatefulSet", "prometheus", 1, 1.0, 4, 0.6, 2.8, _l("platform", "cc-900"),
                 diurnal=0.1, noise=0.05, net_kbps=400, nodes=("ip-10-0-2-21",)),
]


# Storage and load balancers: one forgotten export volume and one LoadBalancer
# left behind by a decommissioned frontend, next to healthy ones.
VOLUMES = [
    VolumeIn(namespace="monitoring", name="prometheus-db-prometheus-0", storage_class="gp3", capacity_gib=100,
             mounted_by=["prometheus-0"], labels={"team": "platform"}),
    VolumeIn(namespace="search", name="data-search-api-0", storage_class="gp3", capacity_gib=200,
             mounted_by=["search-api-0"], labels={"team": "search"}),
    VolumeIn(namespace="search", name="data-search-api-1", storage_class="gp3", capacity_gib=200,
             mounted_by=["search-api-1"], labels={"team": "search"}),
    VolumeIn(namespace="data", name="q3-export-backup", storage_class="gp3", capacity_gib=500, mounted_by=[],
             labels={"team": "data"}),
    VolumeIn(namespace="staging", name="qa-fixtures", storage_class="gp2", capacity_gib=50, mounted_by=[],
             labels={"team": "qa"}),
]
SERVICES = [
    ServiceIn(namespace="storefront", name="storefront-public", type="LoadBalancer", has_endpoints=True,
              labels={"team": "web"}),
    ServiceIn(namespace="storefront", name="legacy-checkout-lb", type="LoadBalancer", has_endpoints=False,
              labels={"team": "payments"}),
]


def _pod_names(w: DemoWorkload) -> list[str]:
    if w.kind == "StatefulSet":
        return [f"{w.name}-{i}" for i in range(w.replicas)]
    suffix = f"{zlib.crc32(w.name.encode()) % 0xFFFFF:05x}"
    if w.kind == "DaemonSet":
        return [f"{w.name}-{zlib.crc32(n.encode()) % 0xFFFFF:05x}" for n in w.nodes]
    return [f"{w.name}-7d9f{suffix[:2]}-{suffix[2:]}{i}" for i in range(w.pod_offset, w.pod_offset + w.replicas)]


def _rng(*parts) -> random.Random:
    return random.Random(zlib.crc32("|".join(map(str, parts)).encode()))


def _sample(w: DemoWorkload, pod: str, node: str, ts: datetime.datetime) -> SampleIn:
    r = _rng(w.namespace, pod, ts.isoformat())
    hour = ts.hour + ts.minute / 60
    if w.night_batch:
        level = 1.0 if 1 <= hour < 4 else 0.015
    else:
        level = 1.0 + w.diurnal * math.cos(2 * math.pi * (hour - 15) / 24)
        if ts.weekday() >= 5:
            level *= w.weekend
    level *= max(0.2, r.gauss(1.0, w.noise))
    if w.spike_prob and r.random() < w.spike_prob:
        level *= w.spike_mult

    cpu = max(0.001, w.cpu_use * level)
    cpu_max = cpu * (1 + abs(r.gauss(0, w.noise * 2 + 0.05)))
    throttled = 0.0
    if w.cpu_limit and cpu_max > w.cpu_limit:
        cpu = min(cpu, w.cpu_limit)
        throttled = (cpu_max - w.cpu_limit) / cpu_max * 300 * 0.5
        cpu_max = w.cpu_limit

    mem = w.mem_use_gib * (0.9 + 0.1 * min(level, 2.0))
    oom = 0
    if w.leak_gib_per_hour and w.mem_limit_gib:
        cycle_h = (w.mem_limit_gib - w.mem_use_gib) / w.leak_gib_per_hour
        phase_seed = zlib.crc32(pod.encode()) % 1000 / 1000 * cycle_h
        epoch_h = ts.timestamp() / 3600 + phase_seed
        mem = w.mem_use_gib + w.leak_gib_per_hour * (epoch_h % cycle_h)
        if (epoch_h % cycle_h) < SLOT.total_seconds() / 3600:
            oom = 1  # the slot right after the limit was hit: killed and restarted
    mem_max = mem * (1 + abs(r.gauss(0, 0.03)))
    if w.mem_limit_gib:
        mem_max = min(mem_max, w.mem_limit_gib)
    net = w.net_kbps * 1024 * SLOT.total_seconds() * max(level, 0.0)

    return SampleIn(
        ts=ts, namespace=w.namespace, pod=pod, container=w.name, node=node, workload_kind=w.kind,
        workload_name=w.name, duration_seconds=int(SLOT.total_seconds()), cpu_request_cores=w.cpu_req,
        cpu_limit_cores=w.cpu_limit, cpu_usage_cores=round(cpu, 5), cpu_usage_max_cores=round(cpu_max, 5),
        cpu_throttled_seconds=round(throttled, 2), mem_request_bytes=w.mem_req_gib * GIB,
        mem_limit_bytes=w.mem_limit_gib * GIB if w.mem_limit_gib else None, mem_usage_bytes=round(mem * GIB),
        mem_usage_max_bytes=round(mem_max * GIB), net_rx_bytes=round(net * 0.6), net_tx_bytes=round(net * 0.4),
        restarts=oom, oom_kills=oom,
    )


NODE_BY_NAME = {n.name: n for n in NODES}

# The incident happened 5 days before the process started (09:00-23:00 UTC),
# so a fresh demo always has it inside its 14-day history. Tests replaying a
# fixed date set this to None.
_today = datetime.datetime.now(datetime.UTC).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
INCIDENT: tuple[datetime.datetime, datetime.datetime] | None = (
    _today - datetime.timedelta(days=5) + datetime.timedelta(hours=9),
    _today - datetime.timedelta(days=5) + datetime.timedelta(hours=23),
)


def _is_peak(ts: datetime.datetime) -> bool:
    return ts.weekday() < 5 and 8 <= ts.hour < 20


def _in_incident(ts: datetime.datetime) -> bool:
    return INCIDENT is not None and INCIDENT[0] <= ts < INCIDENT[1]


def node_active(name: str, ts: datetime.datetime) -> bool:
    n = NODE_BY_NAME[name]
    if n.incident_only:
        return _in_incident(ts)
    return not n.peak_only or _is_peak(ts)


def samples_for_slot(ts: datetime.datetime) -> list[SampleIn]:
    out = []
    for w in WORKLOADS:
        if (w.peak_only and not _is_peak(ts)) or (w.incident_only and not _in_incident(ts)):
            continue
        for pod, node in zip(_pod_names(w), w.nodes, strict=True):
            if node_active(node, ts):
                out.append(_sample(w, pod, node, ts))
    return out


def node_samples_for_slot(ts: datetime.datetime) -> list[NodeSampleIn]:
    return [NodeSampleIn(ts=ts, node=n.name, duration_seconds=int(SLOT.total_seconds()))
            for n in NODES if node_active(n.name, ts)]


def inventory() -> InventoryIn:
    return InventoryIn(
        agent_version="demo-generator/2.0",
        nodes=[NodeIn(name=n.name, instance_type=n.instance_type, capacity_type=n.capacity_type, region="us-east-1",
                      zone=n.zone, vcpu=n.vcpu, memory_gib=n.memory_gib,
                      labels={"node.kubernetes.io/instance-type": n.instance_type,
                              "karpenter.sh/capacity-type": n.capacity_type}) for n in NODES],
        workloads=list({(w.namespace, w.kind, w.name): WorkloadIn(
            namespace=w.namespace, kind=w.kind, name=w.name, replicas=w.replicas, labels=w.labels)
            for w in reversed(WORKLOADS)}.values()),
        volumes=VOLUMES,
        services=SERVICES,
        autoscalers=[AutoscalerIn(namespace="storefront", name="frontend-web", target_kind="Deployment",
                                  target_name="frontend-web", cpu_target_utilization=0.6, min_replicas=3,
                                  max_replicas=8)],
    )


def floor_slot(ts: datetime.datetime) -> datetime.datetime:
    return ts.replace(minute=ts.minute - ts.minute % 5, second=0, microsecond=0)


def _emit_range(db: Session, cluster: Cluster, start: datetime.datetime, end: datetime.datetime,
                now: datetime.datetime) -> int:
    """Emit samples for slots in [start, end]."""
    count, batch, node_batch, ts = 0, [], [], start
    slots_in_batch = 0
    while ts <= end:
        batch.extend(samples_for_slot(ts))
        node_batch.extend(node_samples_for_slot(ts))
        slots_in_batch += 1
        ts += SLOT
        if slots_in_batch == SLOTS_PER_CHUNK or ts > end:
            count += ingest_samples(db, cluster, batch, now=now, node_samples=node_batch).accepted
            batch, node_batch, slots_in_batch = [], [], 0
    return count


def ensure_demo_cluster(db: Session, backfill_days: int, now: datetime.datetime | None = None) -> Cluster:
    """Create the demo cluster with history on first run (no-op afterwards)."""
    now = now or utcnow()
    cluster = db.query(Cluster).filter(Cluster.name == DEMO_CLUSTER_NAME).first()
    if cluster is not None:
        return cluster
    _, prefix, token_hash = new_agent_token()  # token discarded: nobody needs to push to the demo
    cluster = Cluster(name=DEMO_CLUSTER_NAME, provider="aws", region="us-east-1", token_prefix=prefix,
                      token_hash=token_hash, agent_version="demo-generator/2.0")
    db.add(cluster)
    db.commit()
    db.refresh(cluster)

    start = floor_slot(now - datetime.timedelta(days=backfill_days))
    ingest_inventory(db, cluster, inventory(), now=now, first_seen=start)
    n = _emit_range(db, cluster, start, floor_slot(now) - SLOT, now)
    logger.info("Demo cluster %s seeded with %d samples over %d days", cluster.name, n, backfill_days)
    return cluster


def demo_tick(db: Session, now: datetime.datetime | None = None) -> int:
    """Continue the demo cluster's time series up to now (called periodically)."""
    now = now or utcnow()
    cluster = db.query(Cluster).filter(Cluster.name == DEMO_CLUSTER_NAME).first()
    if cluster is None:
        return 0
    last = db.query(func.max(UsageSample.ts)).filter(UsageSample.cluster_id == cluster.id).scalar()
    target = floor_slot(now) - SLOT
    start = (last + SLOT) if last else target
    start = max(start, target - datetime.timedelta(days=1))
    ingest_inventory(db, cluster, inventory(), now=now)  # node/workload heartbeat
    if start > target:
        return 0
    return _emit_range(db, cluster, start, target, now)
