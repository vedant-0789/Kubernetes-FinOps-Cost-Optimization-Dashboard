"""OpenCost-compatible cost allocation.

For one time window (normally one hour) and one cluster:

* every node costs ``hourly_price x active_hours``, split into a CPU part and
  a RAM part (see ``app.pricing.split_node_price``);
* every container is allocated ``max(request, usage)`` of CPU and RAM for the
  duration of each sample, charged at its node's unit prices;
* whatever node capacity is not allocated is **idle cost**, reported per node
  (it is real spend: the cloud bills the whole node);
* containers in ``shared_namespaces`` (kube-system, monitoring, ...) are
  flagged ``shared`` so reports can show them separately or spread them over
  tenants.

Invariant (tested): sum(container costs) + sum(idle costs) == sum(node costs)
whenever no node is over-committed.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.pricing import DEFAULT_CPU_HOURLY, DEFAULT_RAM_HOURLY

GIB = 1024**3
DEFAULT_SHARED_NAMESPACES = frozenset({"kube-system", "kube-public", "kube-node-lease", "monitoring"})


@dataclass(frozen=True)
class NodeInfo:
    name: str
    vcpu: float
    memory_gib: float
    hourly_price: float
    cpu_hourly_per_core: float
    ram_hourly_per_gib: float
    active_hours: float  # overlap of the node's lifetime with the window


@dataclass(frozen=True)
class ContainerSample:
    namespace: str
    pod: str
    container: str
    node: str | None
    duration_hours: float
    cpu_request_cores: float
    cpu_usage_cores: float
    mem_request_bytes: float
    mem_usage_bytes: float
    workload_kind: str | None = None
    workload_name: str | None = None


@dataclass
class ContainerAllocation:
    namespace: str
    pod: str
    container: str
    node: str | None
    workload_kind: str | None
    workload_name: str | None
    shared: bool
    cpu_core_hours: float = 0.0          # allocated = max(request, usage)
    ram_gib_hours: float = 0.0
    cpu_usage_core_hours: float = 0.0
    ram_usage_gib_hours: float = 0.0
    cpu_request_core_hours: float = 0.0
    ram_request_gib_hours: float = 0.0
    cpu_cost: float = 0.0
    ram_cost: float = 0.0
    cpu_usage_cost: float = 0.0          # what the *used* resources cost
    ram_usage_cost: float = 0.0
    priced_by_fallback: bool = False

    @property
    def total_cost(self) -> float:
        return self.cpu_cost + self.ram_cost


@dataclass
class NodeCost:
    node: str
    total_cost: float
    cpu_cost: float
    ram_cost: float
    allocated_cpu_cost: float = 0.0
    allocated_ram_cost: float = 0.0

    @property
    def idle_cpu_cost(self) -> float:
        return max(0.0, self.cpu_cost - self.allocated_cpu_cost)

    @property
    def idle_ram_cost(self) -> float:
        return max(0.0, self.ram_cost - self.allocated_ram_cost)

    @property
    def idle_cost(self) -> float:
        return self.idle_cpu_cost + self.idle_ram_cost


@dataclass
class AllocationResult:
    containers: list[ContainerAllocation] = field(default_factory=list)
    nodes: list[NodeCost] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(n.total_cost for n in self.nodes) + sum(
            c.total_cost for c in self.containers if c.priced_by_fallback
        )


def allocate(
    nodes: Iterable[NodeInfo],
    samples: Iterable[ContainerSample],
    shared_namespaces: frozenset[str] = DEFAULT_SHARED_NAMESPACES,
) -> AllocationResult:
    node_map = {n.name: n for n in nodes}
    node_costs = {
        n.name: NodeCost(
            node=n.name,
            total_cost=n.hourly_price * n.active_hours,
            cpu_cost=n.vcpu * n.cpu_hourly_per_core * n.active_hours,
            ram_cost=n.memory_gib * n.ram_hourly_per_gib * n.active_hours,
        )
        for n in node_map.values()
    }

    containers: dict[tuple, ContainerAllocation] = {}
    for s in samples:
        key = (s.namespace, s.pod, s.container)
        alloc = containers.get(key)
        if alloc is None:
            alloc = containers[key] = ContainerAllocation(
                namespace=s.namespace, pod=s.pod, container=s.container, node=s.node,
                workload_kind=s.workload_kind, workload_name=s.workload_name,
                shared=s.namespace in shared_namespaces,
            )
        h = s.duration_hours
        cpu_alloc = max(s.cpu_request_cores, s.cpu_usage_cores) * h
        ram_alloc = max(s.mem_request_bytes, s.mem_usage_bytes) / GIB * h

        node = node_map.get(s.node or "")
        if node is not None:
            cpu_price, ram_price = node.cpu_hourly_per_core, node.ram_hourly_per_gib
        else:
            # Pod on a node we have no inventory for: price it at default
            # rates and mark it, rather than silently dropping cost.
            cpu_price, ram_price = DEFAULT_CPU_HOURLY, DEFAULT_RAM_HOURLY
            alloc.priced_by_fallback = True

        cpu_cost, ram_cost = cpu_alloc * cpu_price, ram_alloc * ram_price
        alloc.cpu_core_hours += cpu_alloc
        alloc.ram_gib_hours += ram_alloc
        alloc.cpu_usage_core_hours += s.cpu_usage_cores * h
        alloc.ram_usage_gib_hours += s.mem_usage_bytes / GIB * h
        alloc.cpu_request_core_hours += s.cpu_request_cores * h
        alloc.ram_request_gib_hours += s.mem_request_bytes / GIB * h
        alloc.cpu_cost += cpu_cost
        alloc.ram_cost += ram_cost
        alloc.cpu_usage_cost += s.cpu_usage_cores * h * cpu_price
        alloc.ram_usage_cost += s.mem_usage_bytes / GIB * h * ram_price
        if node is not None:
            nc = node_costs[node.name]
            nc.allocated_cpu_cost += cpu_cost
            nc.allocated_ram_cost += ram_cost

    return AllocationResult(containers=list(containers.values()), nodes=list(node_costs.values()))


def efficiency(cpu_usage_cost: float, ram_usage_cost: float, total_cost: float) -> float:
    """Cost-weighted efficiency in [0, 1]: what fraction of the money paid
    for allocated resources was actually used."""
    if total_cost <= 0:
        return 0.0
    return min(1.0, (cpu_usage_cost + ram_usage_cost) / total_cost)

