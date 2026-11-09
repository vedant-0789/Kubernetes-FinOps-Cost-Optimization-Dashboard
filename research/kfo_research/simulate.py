"""Trace replay: evaluate a right-sizing strategy on one container's history.

Protocol (per container, per strategy)
--------------------------------------
* The trace is a sequence of 5-minute windows with observed mean/peak CPU and
  memory, and optionally the *true* CPU peak (synthetic traces, where observed
  CPU is clipped by a CPU limit and the real demand is known).
* After a warm-up of ``warmup_days``, the strategy is re-run once per day on
  the history so far (rolling window) and its requests apply to the next day.
  Requests start from the container's original (developer-set) requests, so
  per-step caps make the strategy converge gradually, as in production.
* Memory limit = memory request (the usual "Guaranteed" memory setting): a
  window whose memory peak exceeds the request is an OOM event. For real
  traces flagged ``original_mem_is_safe`` (usage observed under the original
  limit without kills), only a limit lowered below the original can OOM. OOM events
  are fed back into the history the strategy sees from then on, exactly as
  the agent reports ``oom_kills`` in production.
* CPU is burstable: a window whose true CPU peak exceeds the request is an
  under-provisioned window (contention risk); the CPU deficit is the
  core-hours of demand above the request.

Costs use the OpenCost default unit prices, so savings are comparable across
containers of different sizes.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from kfo_research import REPO  # noqa: F401  (puts backend/ on sys.path)

from app.engines.rightsizing import ContainerSpec, Policy, Recommendation, UsagePoint, recommend  # noqa: E402

CPU_PRICE = 0.031611   # $/core-hour (OpenCost default)
RAM_PRICE = 0.004237   # $/GiB-hour
GIB = 1024**3
DAY = 86400


def throttled_seconds(true_peak: float, limit: float | None, slot: float = 300.0) -> float:
    """CFS throttling in a window whose demand peak is ``true_peak`` under a
    CPU ``limit``: 30 % of the window at the threshold, rising with the excess
    (cAdvisor commonly reports 30-100 % for services pinned at their limit)."""
    if not limit or true_peak <= limit:
        return 0.0
    return min(1.0, 0.3 + 0.7 * ((true_peak - limit) / limit) / 0.5) * slot


@dataclass
class Trace:
    """One container's history plus what the developer originally asked for."""

    name: str
    archetype: str
    points: list[UsagePoint]            # observed (what the agent would report)
    original: ContainerSpec
    true_cpu_peak: list[float] | None = None   # ground truth when observed CPU is clipped
    meta: dict = field(default_factory=dict)
    true_cpu_mean: list[float] | None = None   # ground truth mean (clipped traces only)


@dataclass
class Outcome:
    strategy: str
    trace: str
    archetype: str
    windows: int = 0
    cpu_core_hours: float = 0.0
    mem_gib_hours: float = 0.0
    orig_cpu_core_hours: float = 0.0
    orig_mem_gib_hours: float = 0.0
    cpu_under_windows: int = 0
    cpu_deficit_core_hours: float = 0.0
    oom_events: int = 0
    orig_oom_events: int = 0
    recommendations: int = 0
    final_cpu: float = 0.0
    final_mem: float = 0.0

    @property
    def cost(self) -> float:
        return self.cpu_core_hours * CPU_PRICE + self.mem_gib_hours * RAM_PRICE

    @property
    def orig_cost(self) -> float:
        return self.orig_cpu_core_hours * CPU_PRICE + self.orig_mem_gib_hours * RAM_PRICE

    @property
    def savings_pct(self) -> float:
        return (1 - self.cost / self.orig_cost) * 100 if self.orig_cost else 0.0

    @property
    def cpu_under_rate(self) -> float:
        return self.cpu_under_windows / self.windows if self.windows else 0.0


StrategyFn = Callable[[Sequence[UsagePoint], ContainerSpec], Recommendation]


def strategy(name: str, policy: Policy | None = None) -> StrategyFn:
    """A strategy from the product engine, optionally with a non-default policy."""
    if policy is None:
        return lambda pts, spec: recommend(pts, spec, name)
    return lambda pts, spec: recommend(pts, spec, name, policy)


def static(points, spec):  # the developer's requests, never changed
    return Recommendation("static", "keep", spec.cpu_request, spec.mem_request, spec.cpu_limit, spec.mem_limit,
                          1.0, "high", "low")


def replay(trace: Trace, name: str, fn: StrategyFn, warmup_days: int = 7, history_days: int = 14) -> Outcome:
    pts = trace.points
    if not pts:
        return Outcome(name, trace.name, trace.archetype)
    t0 = pts[0].ts
    day_of = [int((p.ts - t0) // DAY) for p in pts]
    last_day = day_of[-1]
    out = Outcome(name, trace.name, trace.archetype)
    spec = trace.original
    history: list[UsagePoint] = []
    # Real traces: usage observed under the original allocation ran without
    # OOM kills (Alibaba memory includes reclaimable page cache and may exceed
    # mem_size), so only a limit *below* the original can cause one.
    original_safe = bool(trace.meta.get("original_mem_is_safe"))
    i = 0
    for day in range(last_day + 1):
        # Points of this day.
        j = i
        while j < len(pts) and day_of[j] == day:
            j += 1
        if day >= warmup_days:
            window = [p for p in history if p.ts >= pts[i].ts - history_days * DAY]
            rec = fn(window, spec)
            out.recommendations += 1
            if rec.action not in ("insufficient_data", "keep"):
                spec = replace(spec, cpu_request=rec.cpu_request, mem_request=rec.mem_request,
                               cpu_limit=rec.cpu_limit if spec.cpu_limit else None,
                               mem_limit=rec.mem_request)
        for k in range(i, j):
            p = pts[k]
            h = p.duration_seconds / 3600
            true_cpu = trace.true_cpu_peak[k] if trace.true_cpu_peak else (p.cpu_peak or p.cpu_mean)
            mem_peak = p.mem_peak or p.mem_mean
            oom = mem_peak > spec.mem_request and (not original_safe
                                                   or spec.mem_request < trace.original.mem_request - 1e-9)
            if day >= warmup_days:
                out.windows += 1
                out.cpu_core_hours += spec.cpu_request * h
                out.mem_gib_hours += spec.mem_request / GIB * h
                out.orig_cpu_core_hours += trace.original.cpu_request * h
                out.orig_mem_gib_hours += trace.original.mem_request / GIB * h
                if true_cpu > spec.cpu_request + 1e-9:
                    out.cpu_under_windows += 1
                    out.cpu_deficit_core_hours += (true_cpu - spec.cpu_request) * h
                out.oom_events += int(oom)
                out.orig_oom_events += int(mem_peak > trace.original.mem_request and not original_safe)
            # The agent reports what happened under the requests in force:
            # for clipped traces, re-observe the true demand under the CPU
            # limit now in force (a raised limit stops the throttling).
            if trace.true_cpu_mean is not None and trace.original.cpu_limit:
                lim = spec.cpu_limit
                p = replace(p, cpu_peak=min(true_cpu, lim) if lim else true_cpu,
                            cpu_mean=min(trace.true_cpu_mean[k], lim) if lim else trace.true_cpu_mean[k],
                            throttled_seconds=throttled_seconds(true_cpu, lim, p.duration_seconds))
            history.append(replace(p, oom_kills=int(oom)) if oom else p)
        i = j
    out.final_cpu, out.final_mem = spec.cpu_request, spec.mem_request
    return out


@dataclass
class Summary:
    strategy: str
    containers: int
    savings_pct: float            # cost-weighted
    cpu_under_rate: float         # window-weighted
    cpu_deficit_share: float      # deficit core-hours / requested core-hours
    oom_events: int
    containers_with_oom: int
    containers_cpu_under_gt_5pct: int


def summarize(outcomes: Sequence[Outcome]) -> Summary:
    cost = sum(o.cost for o in outcomes)
    orig = sum(o.orig_cost for o in outcomes)
    windows = sum(o.windows for o in outcomes)
    core_h = sum(o.cpu_core_hours for o in outcomes)
    return Summary(
        strategy=outcomes[0].strategy if outcomes else "",
        containers=len(outcomes),
        savings_pct=(1 - cost / orig) * 100 if orig else 0.0,
        cpu_under_rate=sum(o.cpu_under_windows for o in outcomes) / windows if windows else 0.0,
        cpu_deficit_share=sum(o.cpu_deficit_core_hours for o in outcomes) / core_h if core_h else 0.0,
        oom_events=sum(o.oom_events for o in outcomes),
        containers_with_oom=sum(1 for o in outcomes if o.oom_events),
        containers_cpu_under_gt_5pct=sum(1 for o in outcomes if o.cpu_under_rate > 0.05),
    )
