import pytest

from app.engines.allocation import GIB, ContainerSample, NodeInfo, allocate, efficiency
from app.pricing import DEFAULT_CPU_HOURLY, DEFAULT_RAM_HOURLY, resolve_node_price, split_node_price

# --- pricing -------------------------------------------------------------------


def test_split_preserves_node_price_and_ratio():
    cpu, ram = split_node_price(0.192, 4, 16)
    assert 4 * cpu + 16 * ram == pytest.approx(0.192)
    assert cpu / ram == pytest.approx(DEFAULT_CPU_HOURLY / DEFAULT_RAM_HOURLY)


def test_catalog_price_with_region_multiplier_and_spot():
    on_demand = resolve_node_price(provider="aws", region="us-east-1", instance_type="m5.xlarge",
                                   capacity_type="on_demand", vcpu=4, memory_gib=16)
    assert on_demand.hourly == pytest.approx(0.192)
    assert on_demand.source == "catalog"

    eu = resolve_node_price(provider="aws", region="eu-central-1", instance_type="m5.xlarge",
                            capacity_type="on_demand", vcpu=4, memory_gib=16)
    assert eu.hourly == pytest.approx(0.192 * 1.20)

    spot = resolve_node_price(provider="aws", region="us-east-1", instance_type="m5.xlarge",
                              capacity_type="spot", vcpu=4, memory_gib=16)
    assert spot.hourly == pytest.approx(0.192 * 0.35)


def test_agent_reported_price_wins():
    p = resolve_node_price(provider="aws", region="us-east-1", instance_type="m5.xlarge",
                           capacity_type="on_demand", vcpu=4, memory_gib=16, reported_hourly=0.10)
    assert (p.hourly, p.source) == (0.10, "agent")


def test_custom_rates_for_on_prem():
    p = resolve_node_price(provider="onprem", region=None, instance_type=None, capacity_type="on_demand",
                           vcpu=8, memory_gib=32, custom_cpu_hourly=0.02, custom_ram_hourly=0.003)
    assert p.hourly == pytest.approx(8 * 0.02 + 32 * 0.003)
    assert p.source == "custom"


def test_unknown_instance_falls_back_to_default_rates():
    p = resolve_node_price(provider="aws", region="us-east-1", instance_type="x99.mega",
                           capacity_type="on_demand", vcpu=2, memory_gib=8)
    assert p.source == "fallback"
    assert p.hourly == pytest.approx(2 * DEFAULT_CPU_HOURLY + 8 * DEFAULT_RAM_HOURLY)


# --- allocation ----------------------------------------------------------------


def _node(name="n1", vcpu=4, mem=16, cpu_price=0.04, ram_price=0.002, hours=1.0):
    return NodeInfo(name, vcpu, mem, vcpu * cpu_price + mem * ram_price, cpu_price, ram_price, hours)


def _sample(cpu_req, cpu_use, mem_req_gib, mem_use_gib, ns="app", pod="p", node="n1", hours=1.0):
    return ContainerSample(ns, pod, "c", node, hours, cpu_req, cpu_use, mem_req_gib * GIB, mem_use_gib * GIB)


def test_container_charged_on_max_of_request_and_usage():
    res = allocate([_node()], [_sample(cpu_req=1, cpu_use=0.2, mem_req_gib=2, mem_use_gib=3)])
    c = res.containers[0]
    assert c.cpu_cost == pytest.approx(1 * 0.04)      # request > usage
    assert c.ram_cost == pytest.approx(3 * 0.002)     # usage > request
    assert c.cpu_usage_core_hours == pytest.approx(0.2)


def test_idle_cost_is_unallocated_node_capacity():
    node = _node()  # 4*0.04 + 16*0.002 = 0.192 $/h
    res = allocate([node], [_sample(1, 0.5, 4, 2)])
    n = res.nodes[0]
    assert n.total_cost == pytest.approx(0.192)
    assert n.idle_cpu_cost == pytest.approx(3 * 0.04)
    assert n.idle_ram_cost == pytest.approx(12 * 0.002)


def test_costs_reconcile_to_node_bill():
    nodes = [_node("n1"), _node("n2", vcpu=8, mem=32)]
    samples = [_sample(1, 0.5, 2, 1, pod="a", node="n1"), _sample(2, 2.5, 8, 6, pod="b", node="n2"),
               _sample(0.5, 0.1, 1, 0.5, pod="c", node="n2", ns="kube-system")]
    res = allocate(nodes, samples)
    allocated = sum(c.total_cost for c in res.containers)
    idle = sum(n.idle_cost for n in res.nodes)
    assert allocated + idle == pytest.approx(sum(n.total_cost for n in res.nodes))
    assert next(c for c in res.containers if c.pod == "c").shared is True


def test_samples_accumulate_over_window():
    # Twelve 5-minute samples == one hour of a 1-core request.
    samples = [_sample(1, 0.5, 1, 1, hours=1 / 12) for _ in range(12)]
    c = allocate([_node()], samples).containers[0]
    assert c.cpu_core_hours == pytest.approx(1.0)
    assert c.cpu_cost == pytest.approx(0.04)


def test_partial_node_lifetime_is_billed_pro_rata():
    res = allocate([_node(hours=0.25)], [])
    assert res.nodes[0].total_cost == pytest.approx(0.192 / 4)


def test_unknown_node_priced_by_fallback_not_dropped():
    res = allocate([], [_sample(1, 1, 1, 1, node="ghost")])
    c = res.containers[0]
    assert c.priced_by_fallback
    assert c.total_cost == pytest.approx(DEFAULT_CPU_HOURLY + DEFAULT_RAM_HOURLY)
    assert res.total_cost == pytest.approx(c.total_cost)


def test_efficiency_bounds():
    assert efficiency(0, 0, 0) == 0
    assert efficiency(1, 1, 4) == pytest.approx(0.5)
    assert efficiency(5, 5, 4) == 1.0
