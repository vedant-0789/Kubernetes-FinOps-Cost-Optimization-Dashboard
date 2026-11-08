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


def collect_inventory(core, apps, batch, excluded_namespaces: frozenset[str] = frozenset()) -> dict:
    """``core``/``apps``/``batch`` are kubernetes CoreV1Api/AppsV1Api/BatchV1Api."""
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
    return {"nodes": nodes, "workloads": workloads}
