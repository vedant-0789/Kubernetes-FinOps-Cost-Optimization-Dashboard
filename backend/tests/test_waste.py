import pytest

from app.engines.waste import (
    LoadBalancer,
    NodeLoad,
    Volume,
    WorkloadUsage,
    detect_idle_workloads,
    detect_orphaned_volumes,
    detect_underutilized_nodes,
    detect_unused_load_balancers,
)


def wl(name, cpu_p95, net=0.0, kind="Deployment", hours=48, req=2.0, cost=100.0):
    return WorkloadUsage("ns", kind, name, hours, req, 4, cpu_p95, 0.1, net, cost)


def test_idle_workload_needs_low_cpu_and_low_network_for_the_whole_window():
    found = {f.name for f in detect_idle_workloads([
        wl("zombie", 0.004),
        wl("busy", 0.8),
        wl("quiet-but-serving", 0.004, net=50 * 1024**2),  # little CPU but real traffic
        wl("too-new", 0.0, hours=3),
        wl("agent", 0.0, kind="DaemonSet"),
    ])}
    assert found == {"Deployment/zombie"}


def test_idle_saving_is_full_workload_cost():
    [f] = detect_idle_workloads([wl("zombie", 0.0, cost=175.2)])
    assert f.monthly_savings == pytest.approx(175.2)
    assert f.evidence["cpu_request_cores"] == 2.0


def test_orphaned_volumes_priced_by_storage_class():
    prices = {"gp3": 0.08, None: 0.10}.get
    found = detect_orphaned_volumes([
        Volume("data", "old-export", "gp3", 100, mounted=False, age_hours=72),
        Volume("data", "in-use", "gp3", 100, mounted=True, age_hours=72),
        Volume("data", "brand-new", "gp3", 100, mounted=False, age_hours=1),
    ], lambda sc: prices(sc, 0.10))
    assert [(f.name, f.monthly_savings) for f in found] == [("PersistentVolumeClaim/old-export", 8.0)]


def test_unused_load_balancer():
    found = detect_unused_load_balancers([LoadBalancer("shop", "legacy", False, 10),
                                          LoadBalancer("shop", "live", True, 10)], lb_hourly=0.025)
    assert [(f.name, f.monthly_savings) for f in found] == [("Service/legacy", 18.25)]


def node(name, cpu_req, mem_req, vcpu=8, mem=32, price=0.384, **kw):
    return NodeLoad(name, vcpu, mem, cpu_req, mem_req, price, **kw)


def test_node_consolidation_when_pods_fit_elsewhere():
    found = detect_underutilized_nodes([node("a", 5, 20), node("b", 5, 18), node("c", 1, 2)])
    assert [f.name for f in found] == ["Node/c"]
    assert found[0].monthly_savings == pytest.approx(0.384 * 730, rel=1e-3)
    assert found[0].evidence["utilization"] == pytest.approx(1 / 8)


def test_no_consolidation_when_others_are_full():
    assert detect_underutilized_nodes([node("a", 7.5, 30), node("b", 7.5, 30), node("c", 2, 4)]) == []


def test_consolidation_does_not_double_book_free_capacity():
    # Two near-empty nodes, but the big node only has room for one of them.
    found = detect_underutilized_nodes([node("big", 3, 10), node("x", 2, 4), node("y", 2, 4)])
    assert len(found) == 1


def test_unmovable_pods_block_consolidation():
    assert detect_underutilized_nodes([node("a", 1, 2), node("b", 1, 2, has_unmovable_pods=True)])[0].name == "Node/a"
