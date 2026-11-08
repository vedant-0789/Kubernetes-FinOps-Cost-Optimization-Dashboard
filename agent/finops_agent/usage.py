"""Usage collection from Prometheus (cAdvisor + kube-state-metrics).

Each 5-minute slot ``[ts, ts+5m)`` is read with instant queries evaluated at
``ts+5m`` over a ``[5m]`` range, so the same slot can be re-read later (for
back-fill) and gives the same answer. ``build_samples`` is pure and is what
the unit tests exercise.
"""

import datetime
from collections import defaultdict
from collections.abc import Callable

# Real containers only: drop the pause container and cgroup aggregates.
C = 'container!="",container!="POD",image!=""'

QUERIES: dict[str, str] = {
    "cpu_usage": f"sum by (namespace,pod,container) (rate(container_cpu_usage_seconds_total{{{C}}}[{{w}}]))",
    "cpu_max": (f"max by (namespace,pod,container) (max_over_time("
                f"rate(container_cpu_usage_seconds_total{{{C}}}[1m])[{{w}}:30s]))"),
    "mem_usage": f"max by (namespace,pod,container) (avg_over_time(container_memory_working_set_bytes{{{C}}}[{{w}}]))",
    "mem_max": f"max by (namespace,pod,container) (max_over_time(container_memory_working_set_bytes{{{C}}}[{{w}}]))",
    # Fraction of CFS periods throttled. (kube-prometheus-stack drops
    # container_cpu_cfs_throttled_seconds_total by default but keeps the
    # period counters.) Converted to seconds of the window in build_samples.
    "cpu_throttled_ratio": ("sum by (namespace,pod,container) "
                            "(increase(container_cpu_cfs_throttled_periods_total{container!=\"\"}[{w}])) / "
                            "sum by (namespace,pod,container) "
                            "(increase(container_cpu_cfs_periods_total{container!=\"\"}[{w}]))"),
    "net_rx": "sum by (namespace,pod) (increase(container_network_receive_bytes_total[{w}]))",
    "net_tx": "sum by (namespace,pod) (increase(container_network_transmit_bytes_total[{w}]))",
    "cpu_request": ("max by (namespace,pod,container) (max_over_time("
                    "kube_pod_container_resource_requests{resource=\"cpu\"}[{w}]))"),
    "cpu_limit": ("max by (namespace,pod,container) (max_over_time("
                  "kube_pod_container_resource_limits{resource=\"cpu\"}[{w}]))"),
    "mem_request": ("max by (namespace,pod,container) (max_over_time("
                    "kube_pod_container_resource_requests{resource=\"memory\"}[{w}]))"),
    "mem_limit": ("max by (namespace,pod,container) (max_over_time("
                  "kube_pod_container_resource_limits{resource=\"memory\"}[{w}]))"),
    "restarts": ("sum by (namespace,pod,container) "
                 "(increase(kube_pod_container_status_restarts_total[{w}]))"),
    "oom": ("max by (namespace,pod,container) (max_over_time("
            "kube_pod_container_status_last_terminated_reason{reason=\"OOMKilled\"}[{w}]))"),
    "pod_node": "max by (namespace,pod,node) (max_over_time(kube_pod_info{node!=\"\"}[{w}]))",
    "pod_owner": "max by (namespace,pod,owner_kind,owner_name) (max_over_time(kube_pod_owner[{w}]))",
    "rs_owner": ("max by (namespace,replicaset,owner_kind,owner_name) "
                 "(max_over_time(kube_replicaset_owner[{w}]))"),
    "job_owner": ("max by (namespace,job_name,owner_kind,owner_name) "
                  "(max_over_time(kube_job_owner{owner_kind=\"CronJob\"}[{w}]))"),
    "node_up": "count by (node) (count_over_time(kube_node_info[{w}]))",
}

Vector = list[tuple[dict, float]]


def render_queries(window_seconds: int) -> dict[str, str]:
    w = f"{window_seconds}s"
    return {name: q.replace("{w}", w) for name, q in QUERIES.items()}


def _index(vec: Vector, *keys: str) -> dict[tuple, float]:
    return {tuple(m.get(k, "") for k in keys): v for m, v in vec}


def resolve_owner(namespace: str, pod: str, pod_owner: dict, rs_owner: dict, job_owner: dict) -> tuple[str, str]:
    """Walk Pod -> ReplicaSet -> Deployment and Pod -> Job -> CronJob."""
    kind, name = pod_owner.get((namespace, pod), ("Pod", pod))
    if kind == "ReplicaSet":
        kind, name = rs_owner.get((namespace, name), ("ReplicaSet", name))
    elif kind == "Job":
        kind, name = job_owner.get((namespace, name), ("Job", name))
    if kind in ("<none>", ""):
        kind, name = "Pod", pod
    return kind, name


def _owner_map(vec: Vector, key_label: str) -> dict[tuple, tuple[str, str]]:
    out = {}
    for m, _ in vec:
        if m.get("owner_kind") and m.get("owner_kind") != "<none>":
            out[(m.get("namespace", ""), m.get(key_label, ""))] = (m["owner_kind"], m.get("owner_name", ""))
    return out


def build_samples(results: dict[str, Vector], ts: datetime.datetime, window_seconds: int,
                  excluded_namespaces: frozenset[str] = frozenset()) -> tuple[list[dict], list[dict]]:
    """Turn query results for one slot into (container samples, node heartbeats)."""
    key = ("namespace", "pod", "container")
    idx = {name: _index(results.get(name, []), *key) for name in
           ("cpu_usage", "cpu_max", "mem_usage", "mem_max", "cpu_throttled_ratio", "cpu_request", "cpu_limit",
            "mem_request", "mem_limit", "restarts", "oom")}
    net_rx = _index(results.get("net_rx", []), "namespace", "pod")
    net_tx = _index(results.get("net_tx", []), "namespace", "pod")
    pod_node = {(m.get("namespace", ""), m.get("pod", "")): m.get("node") for m, _ in results.get("pod_node", [])}
    pod_owner = _owner_map(results.get("pod_owner", []), "pod")
    rs_owner = _owner_map(results.get("rs_owner", []), "replicaset")
    job_owner = _owner_map(results.get("job_owner", []), "job_name")

    # A container exists in this slot if it used CPU/memory or had a request.
    containers = set(idx["cpu_usage"]) | set(idx["mem_usage"]) | set(idx["cpu_request"])
    containers = {c for c in containers if all(c) and c[0] not in excluded_namespaces}

    # Pod network is per pod: split it evenly over the pod's containers.
    per_pod = defaultdict(int)
    for ns, pod, _ in containers:
        per_pod[(ns, pod)] += 1

    samples = []
    iso = ts.replace(tzinfo=datetime.UTC).isoformat() if ts.tzinfo is None else ts.isoformat()
    for c in sorted(containers):
        ns, pod, container = c
        kind, name = resolve_owner(ns, pod, pod_owner, rs_owner, job_owner)
        get: Callable[[str], float | None] = lambda q, c=c: idx[q].get(c)  # noqa: E731
        share = per_pod[(ns, pod)] or 1
        restarts = int(round(get("restarts") or 0))
        samples.append({
            "ts": iso, "namespace": ns, "pod": pod, "container": container, "node": pod_node.get((ns, pod)),
            "workload_kind": kind, "workload_name": name, "duration_seconds": window_seconds,
            "cpu_request_cores": max(get("cpu_request") or 0.0, 0.0),
            "cpu_limit_cores": get("cpu_limit"),
            "cpu_usage_cores": max(get("cpu_usage") or 0.0, 0.0),
            "cpu_usage_max_cores": get("cpu_max"),
            "cpu_throttled_seconds": round(min(max(get("cpu_throttled_ratio") or 0.0, 0.0), 1.0) * window_seconds, 2),
            "mem_request_bytes": max(get("mem_request") or 0.0, 0.0),
            "mem_limit_bytes": get("mem_limit"),
            "mem_usage_bytes": max(get("mem_usage") or 0.0, 0.0),
            "mem_usage_max_bytes": get("mem_max"),
            "net_rx_bytes": max(net_rx.get((ns, pod), 0.0), 0.0) / share,
            "net_tx_bytes": max(net_tx.get((ns, pod), 0.0), 0.0) / share,
            "restarts": restarts,
            "oom_kills": restarts if (get("oom") or 0) >= 1 and restarts else 0,
        })

    nodes = [{"ts": iso, "node": m["node"], "duration_seconds": window_seconds}
             for m, v in results.get("node_up", []) if m.get("node") and v > 0]
    return samples, nodes
