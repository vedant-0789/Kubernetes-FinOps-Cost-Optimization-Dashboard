import pytest

from app.engine.cost_calculator import CostCalculator

CPU_RATE, RAM_RATE = 0.048, 0.006


def test_cost_uses_request_when_usage_is_lower():
    # 2 vCPU * 0.048 + 4 GiB * 0.006 = 0.12 $/h -> 87.60 $/month
    c = CostCalculator.calculate_pod_cost(2.0, 0.5, 4096, 1024, CPU_RATE, RAM_RATE)
    assert c["hourly_cost"] == pytest.approx(0.12)
    assert c["monthly_cost"] == pytest.approx(87.60)


def test_cost_uses_usage_when_it_exceeds_request():
    c = CostCalculator.calculate_pod_cost(1.0, 3.0, 1024, 1024, CPU_RATE, RAM_RATE)
    assert c["hourly_cost"] == pytest.approx(3.0 * CPU_RATE + 1.0 * RAM_RATE)


@pytest.mark.parametrize(
    "cpu_used,mem_used,color",
    [(0.9, 900, "green"), (0.5, 500, "yellow"), (0.1, 100, "red")],
)
def test_efficiency_colour_bands(cpu_used, mem_used, color):
    c = CostCalculator.calculate_pod_cost(1.0, cpu_used, 1000, mem_used, CPU_RATE, RAM_RATE)
    assert c["status_color"] == color


def test_zero_requests_do_not_divide_by_zero():
    c = CostCalculator.calculate_pod_cost(0, 0, 0, 0, CPU_RATE, RAM_RATE)
    assert c["monthly_cost"] == 0
