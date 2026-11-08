import datetime

import pytest

from finops_agent.usage import QUERIES, build_samples, render_queries, resolve_owner

TS = datetime.datetime(2026, 11, 4, 12, 0)


def m(**labels):
    return labels


def base_results():
    web = m(namespace="shop", pod="web-7d9f-abc", container="web")
    side = m(namespace="shop", pod="web-7d9f-abc", container="istio-proxy")
    job = m(namespace="data", pod="etl-2900-xyz", container="etl")
    bare = m(namespace="dev", pod="debug", container="sh")
    return {
        "cpu_usage": [(web, 0.25), (side, 0.05), (job, 1.5), (bare, 0.0)],
        "cpu_max": [(web, 0.4)],
        "mem_usage": [(web, 512 * 2**20), (side, 64 * 2**20), (job, 2**30), (bare, 10 * 2**20)],
        "mem_max": [(web, 600 * 2**20)],
        "cpu_request": [(web, 1.0), (side, 0.1), (job, 2.0)],
        "cpu_limit": [(web, 2.0)],
        "mem_request": [(web, 2**30), (side, 128 * 2**20), (job, 4 * 2**30)],
        "mem_limit": [(web, 2 * 2**30)],
        "cpu_throttled_ratio": [(web, 0.01)],
        "restarts": [(job, 1.0)],
        "oom": [(job, 1.0)],
        "net_rx": [(m(namespace="shop", pod="web-7d9f-abc"), 1000.0)],
        "net_tx": [(m(namespace="shop", pod="web-7d9f-abc"), 400.0)],
        "pod_node": [(m(namespace="shop", pod="web-7d9f-abc", node="n1"), 1),
                     (m(namespace="data", pod="etl-2900-xyz", node="n2"), 1)],
        "pod_owner": [(m(namespace="shop", pod="web-7d9f-abc", owner_kind="ReplicaSet", owner_name="web-7d9f"), 1),
                      (m(namespace="data", pod="etl-2900-xyz", owner_kind="Job", owner_name="etl-2900"), 1),
                      (m(namespace="dev", pod="debug", owner_kind="<none>", owner_name="<none>"), 1)],
        "rs_owner": [(m(namespace="shop", replicaset="web-7d9f", owner_kind="Deployment", owner_name="web"), 1)],
        "job_owner": [(m(namespace="data", job_name="etl-2900", owner_kind="CronJob", owner_name="etl"), 1)],
        "node_up": [(m(node="n1"), 10), (m(node="n2"), 10)],
    }


def by_container(samples):
    return {(s["namespace"], s["pod"], s["container"]): s for s in samples}


def test_every_query_renders_with_the_window():
    rendered = render_queries(300)
    assert set(rendered) == set(QUERIES)
    assert all("{w}" not in q and "300s" in q for q in rendered.values())


def test_samples_carry_usage_requests_and_limits():
    samples, _ = build_samples(base_results(), TS, 300)
    web = by_container(samples)[("shop", "web-7d9f-abc", "web")]
    assert web["cpu_usage_cores"] == 0.25 and web["cpu_usage_max_cores"] == 0.4
    assert web["cpu_request_cores"] == 1.0 and web["cpu_limit_cores"] == 2.0
    assert web["mem_usage_bytes"] == 512 * 2**20 and web["mem_limit_bytes"] == 2 * 2**30
    assert web["cpu_throttled_seconds"] == 3.0  # 1% of a 300 s window
    assert web["node"] == "n1"
    assert web["ts"].startswith("2026-11-04T12:00:00") and web["duration_seconds"] == 300


def test_owner_chain_is_resolved():
    s = by_container(build_samples(base_results(), TS, 300)[0])
    assert (s[("shop", "web-7d9f-abc", "web")]["workload_kind"],
            s[("shop", "web-7d9f-abc", "web")]["workload_name"]) == ("Deployment", "web")
    assert (s[("data", "etl-2900-xyz", "etl")]["workload_kind"],
            s[("data", "etl-2900-xyz", "etl")]["workload_name"]) == ("CronJob", "etl")
    assert (s[("dev", "debug", "sh")]["workload_kind"], s[("dev", "debug", "sh")]["workload_name"]) == ("Pod", "debug")


def test_pod_network_is_split_across_containers():
    s = by_container(build_samples(base_results(), TS, 300)[0])
    assert s[("shop", "web-7d9f-abc", "web")]["net_rx_bytes"] == 500
    assert s[("shop", "web-7d9f-abc", "istio-proxy")]["net_tx_bytes"] == 200


def test_oom_kills_require_a_restart_in_the_window():
    s = by_container(build_samples(base_results(), TS, 300)[0])
    assert s[("data", "etl-2900-xyz", "etl")]["oom_kills"] == 1
    results = base_results()
    results["restarts"] = []  # terminated reason is sticky; no restart now => no new OOM
    s = by_container(build_samples(results, TS, 300)[0])
    assert s[("data", "etl-2900-xyz", "etl")]["oom_kills"] == 0


def test_excluded_namespaces_and_node_heartbeats():
    samples, nodes = build_samples(base_results(), TS, 300, frozenset({"dev"}))
    assert all(s["namespace"] != "dev" for s in samples)
    assert {n["node"] for n in nodes} == {"n1", "n2"}


@pytest.mark.parametrize("pod_owner,expected", [
    ({}, ("Pod", "p")),
    ({("ns", "p"): ("StatefulSet", "db")}, ("StatefulSet", "db")),
    ({("ns", "p"): ("ReplicaSet", "orphan-rs")}, ("ReplicaSet", "orphan-rs")),
    ({("ns", "p"): ("Job", "once")}, ("Job", "once")),
])
def test_resolve_owner_edge_cases(pod_owner, expected):
    assert resolve_owner("ns", "p", pod_owner, {}, {}) == expected
