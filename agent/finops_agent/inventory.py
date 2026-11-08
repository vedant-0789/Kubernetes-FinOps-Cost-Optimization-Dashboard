"""Inventory from the Kubernetes API (read-only: list nodes and workload owners)."""

import datetime

CAPACITY_TYPE_LABELS = (
    # label, value meaning spot (case-insensitive)
    ("finops.io/capacity-type", "spot"),
    ("karpenter.sh/capacity-type", "spot"),
    ("eks.amazonaws.com/capacityType", "spot"),
    ("cloud.google.com/gke-spot", "true"),
    ("cloud.google.com/gke-preemptible", "true"),
    ("kubernetes.azure.com/scalesetpriority", "spot"),
)
INSTANCE_TYPE_LABELS = ("node.kubernetes.io/instance-type", "beta.kubernetes.io/instance-type")
PRICE_LABEL = "finops.io/hourly-price"  # explicit price, e.g. for on-prem or kind
# Simulated clusters (kind, k3d) report the whole host as every node's
# capacity; these labels let them pretend to be a given instance size.
CPU_OVERRIDE_LABEL = "finops.io/capacity-cpu"
MEMORY_OVERRIDE_LABEL = "finops.io/capacity-memory"
OWNED_JOB = "CronJob"

_UNITS = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50,
          "k": 10**3, "K": 10**3, "M": 10**6, "G": 10**9, "T": 10**12, "P": 10**15}


def parse_cpu(q: str) -> float:
    q = str(q)
    if q.endswith("m"):
        return float(q[:-1]) / 1000
    if q.endswith("n"):
        return float(q[:-1]) / 1e9
    return float(q)


def parse_bytes(q: str) -> float:
    q = str(q)
    for suffix in sorted(_UNITS, key=len, reverse=True):
        if q.endswith(suffix):
            return float(q[: -len(suffix)]) * _UNITS[suffix]
    return float(q)


def capacity_type(labels: dict[str, str]) -> str:
    for label, spot_value in CAPACITY_TYPE_LABELS:
        if label in labels:
            return "spot" if labels[label].lower() == spot_value else "on_demand"
    return "on_demand"


def node_payload(name: str, labels: dict[str, str], capacity: dict[str, str],
                 created: datetime.datetime | None) -> dict:
    instance_type = next((labels[k] for k in INSTANCE_TYPE_LABELS if k in labels), None)
    price = labels.get(PRICE_LABEL)
    return {
        "name": name,
        "instance_type": instance_type,
        "capacity_type": capacity_type(labels),
        "region": labels.get("topology.kubernetes.io/region"),
        "zone": labels.get("topology.kubernetes.io/zone"),
        "vcpu": parse_cpu(labels.get(CPU_OVERRIDE_LABEL) or capacity.get("cpu", "0")),
        "memory_gib": parse_bytes(labels.get(MEMORY_OVERRIDE_LABEL) or capacity.get("memory", "0")) / 2**30,
        "hourly_price": float(price) if price else None,
        "created_at": created.isoformat() if created else None,
        "labels": dict(labels),
    }


def _iso(ts) -> str | None:
    return ts.isoformat() if ts else None


def _selector_matches(selector: dict[str, str] | None, labels: dict[str, str] | None) -> bool:
    return bool(selector) and all((labels or {}).get(k) == v for k, v in selector.items())


def _pod_ready(pod) -> bool:
    if (pod.status.phase if pod.status else None) != "Running":
        return False
    return any(c.type == "Ready" and c.status == "True" for c in (pod.status.conditions or []))


def collect_storage_and_services(core, excluded_namespaces: frozenset[str] = frozenset()) -> dict:
    """PVCs with the pods mounting them, and LoadBalancer Services with whether
    any ready pod backs them. Both derived from the pod list (no extra RBAC)."""
    pods = [p for p in core.list_pod_for_all_namespaces().items if p.metadata.namespace not in excluded_namespaces]
    mounts: dict[tuple[str, str], list[str]] = {}
    for p in pods:
        if (p.status.phase if p.status else None) in ("Succeeded", "Failed"):
            continue
        for vol in (p.spec.volumes or []):
            claim = getattr(vol, "persistent_volume_claim", None)
            if claim is not None:
                mounts.setdefault((p.metadata.namespace, claim.claim_name), []).append(p.metadata.name)

    volumes = []
    for c in core.list_persistent_volume_claim_for_all_namespaces().items:
        ns = c.metadata.namespace
        if ns in excluded_namespaces:
            continue
        status_cap = (c.status.capacity if c.status else None) or {}
        requested = (c.spec.resources.requests if c.spec.resources else None) or {}
        size = status_cap.get("storage") or requested.get("storage", "0")
        volumes.append({"namespace": ns, "name": c.metadata.name, "storage_class": c.spec.storage_class_name,
                        "capacity_gib": parse_bytes(size) / 2**30,
                        "phase": c.status.phase if c.status else "Pending",
                        "mounted_by": sorted(mounts.get((ns, c.metadata.name), [])),
                        "created_at": _iso(c.metadata.creation_timestamp),
                        "labels": dict(c.metadata.labels or {})})

    services = []
    for svc in core.list_service_for_all_namespaces().items:
        ns = svc.metadata.namespace
        if svc.spec.type != "LoadBalancer" or ns in excluded_namespaces:
            continue
        backed = any(p.metadata.namespace == ns and _pod_ready(p)
                     and _selector_matches(svc.spec.selector, p.metadata.labels) for p in pods)
        services.append({"namespace": ns, "name": svc.metadata.name, "type": svc.spec.type,
                         "has_endpoints": backed, "created_at": _iso(svc.metadata.creation_timestamp),
                         "labels": dict(svc.metadata.labels or {})})
    return {"volumes": volumes, "services": services}


def collect_autoscalers(autoscaling, excluded_namespaces: frozenset[str] = frozenset()) -> list[dict]:
    """HPAs (autoscaling/v2) with their CPU utilisation target, if any."""
    out = []
    for h in autoscaling.list_horizontal_pod_autoscaler_for_all_namespaces().items:
        if h.metadata.namespace in excluded_namespaces:
            continue
        cpu_target = None
        for m in (h.spec.metrics or []):
            res = getattr(m, "resource", None)
            target = getattr(res, "target", None) if res is not None else None
            if m.type == "Resource" and res.name == "cpu" and target is not None and target.average_utilization:
                cpu_target = target.average_utilization / 100
        out.append({"namespace": h.metadata.namespace, "name": h.metadata.name,
                    "target_kind": h.spec.scale_target_ref.kind, "target_name": h.spec.scale_target_ref.name,
                    "cpu_target_utilization": cpu_target, "min_replicas": h.spec.min_replicas,
                    "max_replicas": h.spec.max_replicas})
    return out


def collect_inventory(core, apps, batch, excluded_namespaces: frozenset[str] = frozenset(),
                      autoscaling=None) -> dict:
    """Kubernetes CoreV1Api / AppsV1Api / BatchV1Api / AutoscalingV2Api clients."""
    nodes = [node_payload(n.metadata.name, n.metadata.labels or {}, n.status.capacity or {},
                          n.metadata.creation_timestamp) for n in core.list_node().items]

    workloads = []

    def add(kind, items, replicas_of=lambda o: None):
        for o in items:
            ns = o.metadata.namespace
            if ns in excluded_namespaces:
                continue
            workloads.append({"namespace": ns, "kind": kind, "name": o.metadata.name,
                              "replicas": replicas_of(o), "labels": dict(o.metadata.labels or {})})

    add("Deployment", apps.list_deployment_for_all_namespaces().items, lambda o: o.spec.replicas)
    add("StatefulSet", apps.list_stateful_set_for_all_namespaces().items, lambda o: o.spec.replicas)
    add("DaemonSet", apps.list_daemon_set_for_all_namespaces().items,
        lambda o: o.status.desired_number_scheduled if o.status else None)
    add("CronJob", batch.list_cron_job_for_all_namespaces().items)
    standalone_jobs = [j for j in batch.list_job_for_all_namespaces().items
                       if not any(r.kind == OWNED_JOB for r in (j.metadata.owner_references or []))]
    add("Job", standalone_jobs)
    inv = {"nodes": nodes, "workloads": workloads, **collect_storage_and_services(core, excluded_namespaces)}
    inv["autoscalers"] = collect_autoscalers(autoscaling, excluded_namespaces) if autoscaling is not None else []
    return inv
