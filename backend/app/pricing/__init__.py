"""Node pricing.

Resolution order for a node's hourly price:
  1. explicit price reported by the agent (e.g. from a billing integration)
  2. per-cluster custom rates (on-prem / negotiated discounts)
  3. provider catalog by instance type x region multiplier x spot discount
  4. fallback: capacity x default per-vCPU / per-GiB rates
The CPU/RAM split of a node price follows OpenCost: keep the default
CPU:RAM price ratio and scale both so they add up to the node price.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CATALOG_DIR = Path(__file__).parent / "catalogs"
PROVIDERS = ("aws", "gcp", "azure")

# Default unit prices (GCP E2-equivalent, the OpenCost defaults). Used for the
# CPU:RAM ratio and as the fallback when an instance type is unknown.
DEFAULT_CPU_HOURLY = 0.031611  # $ per vCPU-hour
DEFAULT_RAM_HOURLY = 0.004237  # $ per GiB-hour


@dataclass(frozen=True)
class NodePrice:
    hourly: float
    cpu_hourly_per_core: float
    ram_hourly_per_gib: float
    source: str  # agent | custom | catalog | fallback


@lru_cache
def load_catalog(provider: str) -> dict:
    path = CATALOG_DIR / f"{provider}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def split_node_price(hourly: float, vcpu: float, memory_gib: float,
                     cpu_base: float = DEFAULT_CPU_HOURLY, ram_base: float = DEFAULT_RAM_HOURLY) -> tuple[float, float]:
    """Split a node's hourly price into per-core and per-GiB prices, keeping
    the base CPU:RAM ratio, so cores*cpu + gib*ram == hourly."""
    base_total = vcpu * cpu_base + memory_gib * ram_base
    if base_total <= 0:
        return 0.0, 0.0
    factor = hourly / base_total
    return cpu_base * factor, ram_base * factor


def resolve_node_price(
    *,
    provider: str,
    region: str | None,
    instance_type: str | None,
    capacity_type: str,
    vcpu: float,
    memory_gib: float,
    reported_hourly: float | None = None,
    custom_cpu_hourly: float | None = None,
    custom_ram_hourly: float | None = None,
) -> NodePrice:
    if reported_hourly is not None and reported_hourly > 0:
        cpu, ram = split_node_price(reported_hourly, vcpu, memory_gib)
        return NodePrice(reported_hourly, cpu, ram, "agent")

    if custom_cpu_hourly is not None and custom_ram_hourly is not None:
        hourly = vcpu * custom_cpu_hourly + memory_gib * custom_ram_hourly
        return NodePrice(hourly, custom_cpu_hourly, custom_ram_hourly, "custom")

    catalog = load_catalog(provider)
    entry = catalog.get("instances", {}).get(instance_type or "")
    if entry:
        multiplier = catalog.get("region_multipliers", {}).get(region or catalog.get("default_region"), 1.0)
        hourly = entry["hourly"] * multiplier
        if capacity_type == "spot":
            hourly *= 1.0 - catalog.get("spot_discount", 0.0)
        cpu, ram = split_node_price(hourly, vcpu, memory_gib)
        return NodePrice(hourly, cpu, ram, "catalog")

    hourly = vcpu * DEFAULT_CPU_HOURLY + memory_gib * DEFAULT_RAM_HOURLY
    if capacity_type == "spot":
        hourly *= 0.35
    cpu, ram = split_node_price(hourly, vcpu, memory_gib)
    return NodePrice(hourly, cpu, ram, "fallback")


DEFAULT_STORAGE_GIB_MONTH = 0.10   # $/GiB-month when a storage class is unknown
DEFAULT_LB_HOURLY = 0.025          # $/hour per cloud load balancer


def storage_price_gib_month(provider: str, storage_class: str | None) -> float:
    prices = load_catalog(provider).get("storage_gib_month", {})
    return prices.get(storage_class or "", prices.get("default", DEFAULT_STORAGE_GIB_MONTH))


def load_balancer_hourly(provider: str) -> float:
    if provider == "onprem":
        return 0.0
    return load_catalog(provider).get("load_balancer_hourly", DEFAULT_LB_HOURLY)
