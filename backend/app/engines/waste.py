"""Waste detection taxonomy (pure functions).

Each detector returns ``Finding`` objects with a monthly saving and the
evidence that justifies it. Savings are made non-overlapping by the caller
(see ``app.services.analysis``): an idle workload is removed entirely, so it
gets no right-sizing recommendation as well.

Categories
  IDLE_WORKLOAD      requests capacity but uses ~no CPU and no network for the
                     whole evaluation window -> scale to zero / delete
  ORPHANED_VOLUME    PersistentVolumeClaim mounted by no pod -> snapshot + delete
  UNUSED_LB          LoadBalancer Service with no ready backends -> delete
  UNDERUTILIZED_NODE node whose pods fit on the other nodes' free capacity
                     -> cordon, drain, remove (consolidation)
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

HOURS_PER_MONTH = 730.0


@dataclass(frozen=True)
class WastePolicy:
    idle_window_hours: float = 24.0
    idle_cpu_ratio: float = 0.05          # p95 CPU below 5 % of request ...
    idle_cpu_abs: float = 0.005           # ... or below 5 millicores
    idle_net_bytes_per_hour: float = 512 * 1024  # and < 512 KiB/h of traffic
    orphan_min_age_hours: float = 24.0
    lb_min_age_hours: float = 1.0
    node_util_threshold: float = 0.30     # requests below 30 % of capacity (CPU and memory)
    node_fill_target: float = 0.85        # don't pack receiving nodes above 85 %


@dataclass
class Finding:
    kind: str
    namespace: str | None
    name: str
    monthly_savings: float
    risk: str
    action: str
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class WorkloadUsage:
    namespace: str
    kind: str
    name: str
    observed_hours: float
    cpu_request: float          # summed over replicas (cores)
    mem_request_gib: float
    cpu_p95: float              # p95 of summed usage (cores)
    mem_p95_gib: float
    net_bytes_per_hour: float
    monthly_cost: float


@dataclass(frozen=True)
class Volume:
    namespace: str
    name: str
    storage_class: str | None
    capacity_gib: float
    mounted: bool
    age_hours: float
    phase: str = "Bound"


@dataclass(frozen=True)
class LoadBalancer:
    namespace: str
    name: str
    has_endpoints: bool
    age_hours: float


@dataclass(frozen=True)
class NodeLoad:
    name: str
    vcpu: float
    memory_gib: float
    cpu_requested: float
    mem_requested_gib: float
    hourly_price: float
    capacity_type: str = "on_demand"
    has_unmovable_pods: bool = False   # e.g. local storage, PDB-blocked


def detect_idle_workloads(workloads: Sequence[WorkloadUsage], policy: WastePolicy = WastePolicy(),
                          ignore_kinds: frozenset[str] = frozenset({"DaemonSet", "Job", "CronJob"})) -> list[Finding]:
    out = []
    for w in workloads:
        if w.kind in ignore_kinds or w.cpu_request <= 0 or w.observed_hours < policy.idle_window_hours:
            continue
        cpu_idle = w.cpu_p95 <= max(policy.idle_cpu_abs, policy.idle_cpu_ratio * w.cpu_request)
        net_idle = w.net_bytes_per_hour <= policy.idle_net_bytes_per_hour
        if cpu_idle and net_idle:
            out.append(Finding(
                kind="IDLE_WORKLOAD", namespace=w.namespace, name=f"{w.kind}/{w.name}",
                monthly_savings=round(w.monthly_cost, 2), risk="medium",
                action="Confirm with the owner, then scale to 0 replicas (reversible) or delete",
                evidence={"observed_hours": round(w.observed_hours, 1), "cpu_p95_cores": round(w.cpu_p95, 4),
                          "cpu_request_cores": w.cpu_request, "mem_p95_gib": round(w.mem_p95_gib, 3),
                          "net_bytes_per_hour": round(w.net_bytes_per_hour), "workload_kind": w.kind,
                          "workload_name": w.name},
            ))
    return out


def detect_orphaned_volumes(volumes: Sequence[Volume], price_gib_month, policy: WastePolicy = WastePolicy()
                            ) -> list[Finding]:
    """``price_gib_month(storage_class) -> $`` for the cluster's provider."""
    out = []
    for v in volumes:
        if v.mounted or v.age_hours < policy.orphan_min_age_hours:
            continue
        cost = v.capacity_gib * price_gib_month(v.storage_class)
        out.append(Finding(
            kind="ORPHANED_VOLUME", namespace=v.namespace, name=f"PersistentVolumeClaim/{v.name}",
            monthly_savings=round(cost, 2), risk="medium",
            action="Snapshot the volume, then delete the claim",
            evidence={"capacity_gib": v.capacity_gib, "storage_class": v.storage_class, "phase": v.phase,
                      "age_hours": round(v.age_hours, 1)},
        ))
    return out


def detect_unused_load_balancers(lbs: Sequence[LoadBalancer], lb_hourly: float,
                                 policy: WastePolicy = WastePolicy()) -> list[Finding]:
    return [
        Finding(kind="UNUSED_LB", namespace=lb.namespace, name=f"Service/{lb.name}",
                monthly_savings=round(lb_hourly * HOURS_PER_MONTH, 2), risk="low",
                action="Delete the Service (or switch it to ClusterIP)",
                evidence={"has_endpoints": False, "age_hours": round(lb.age_hours, 1),
                          "lb_hourly": lb_hourly})
        for lb in lbs if not lb.has_endpoints and lb.age_hours >= policy.lb_min_age_hours
    ]


def detect_underutilized_nodes(nodes: Sequence[NodeLoad], policy: WastePolicy = WastePolicy()) -> list[Finding]:
    """Greedy consolidation: drain the emptiest nodes first while their
    requests still fit into the remaining nodes below ``node_fill_target``."""
    if len(nodes) < 2:
        return []

    # Current (simulated) load, updated as nodes are drained onto others.
    load_cpu = {n.name: n.cpu_requested for n in nodes}
    load_mem = {n.name: n.mem_requested_gib for n in nodes}

    def util(n: NodeLoad) -> float:
        return max(load_cpu[n.name] / n.vcpu if n.vcpu else 1.0,
                   load_mem[n.name] / n.memory_gib if n.memory_gib else 1.0)

    def room(m: NodeLoad) -> tuple[float, float]:
        return (m.vcpu * policy.node_fill_target - load_cpu[m.name],
                m.memory_gib * policy.node_fill_target - load_mem[m.name])

    removed: set[str] = set()
    out = []
    for n in sorted(nodes, key=util):
        u = util(n)
        if u >= policy.node_util_threshold or n.has_unmovable_pods:
            continue
        receivers = [m for m in nodes if m.name != n.name and m.name not in removed]
        if not receivers:
            break
        need_cpu, need_mem = load_cpu[n.name], load_mem[n.name]
        if need_cpu > sum(max(0.0, room(m)[0]) for m in receivers) or \
                need_mem > sum(max(0.0, room(m)[1]) for m in receivers):
            continue
        # Best fit: fill the fullest receivers first, so other near-empty
        # nodes stay empty and can be removed too.
        for m in sorted(receivers, key=util, reverse=True):
            free_c, free_m = room(m)
            take_c, take_m = min(need_cpu, max(0.0, free_c)), min(need_mem, max(0.0, free_m))
            load_cpu[m.name] += take_c
            load_mem[m.name] += take_m
            need_cpu -= take_c
            need_mem -= take_m
            if need_cpu <= 1e-9 and need_mem <= 1e-9:
                break
        load_cpu[n.name] = load_mem[n.name] = 0.0
        removed.add(n.name)
        out.append(Finding(
            kind="UNDERUTILIZED_NODE", namespace=None, name=f"Node/{n.name}",
            monthly_savings=round(n.hourly_price * HOURS_PER_MONTH, 2),
            risk="medium" if n.capacity_type == "spot" else "low",
            action="Cordon and drain; let the autoscaler remove it (or lower the node group minimum)",
            evidence={"cpu_requested": round(n.cpu_requested, 3), "vcpu": n.vcpu,
                      "mem_requested_gib": round(n.mem_requested_gib, 2), "memory_gib": n.memory_gib,
                      "utilization": round(u, 3), "capacity_type": n.capacity_type,
                      "fits_on": sorted(m.name for m in receivers)},
        ))
    return out
