"""Right-sizing recommendation strategies.

``slo_aware`` is KubeFinOps' method (the research contribution); the others
are baselines used for comparison in the product and in research/:

* ``p95_buffer``: p95 of mean usage + 20 % (the common "rule of thumb").
* ``vpa``: an approximation of the Kubernetes VPA recommender: decaying
  histogram, CPU target p90 + 15 % margin, memory p90 of window peaks + 15 %,
  OOM bump-up x1.2.

SLO-aware method, per container (pooling all replicas of a workload):

CPU is compressible: under-provisioning causes contention/throttling, not
failure. We pick the request ``r`` so that the fraction of (recency-weighted)
time in which *peak* demand exceeds ``r`` stays within an SLO budget
``epsilon``, i.e. the (1 - epsilon) weighted quantile of per-window peaks, plus
headroom ``k_cpu * CV_daily_peak``: the day-to-day variability of the daily
peak, i.e. how likely the *next* peak is to exceed past ones. (The CV of all
samples would punish on/off batch jobs whose nightly peak never changes.) **Censoring correction**: when a container
is throttled at its limit, observed peaks are clipped at that limit and
under-state demand; we detect this and lift the estimate above the limit in
proportion to the throttled fraction instead of trusting the clipped data.

Memory is incompressible: exceeding the limit kills the container. We start
from the peak working set over the window, add headroom that grows with
volatility, and treat each OOM kill as a *censored* observation of demand
>= limit (raising the request above the old limit). Sustained growth (leak
signature) adds a projection over a horizon and blocks any reduction.

Every recommendation carries a confidence (history length x completeness),
a risk label, and is limited to a maximum reduction per step so that changes
are applied gradually and can be verified.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

MIB = 1024**2
GIB = 1024**3
HOURS_PER_MONTH = 730.0


@dataclass(slots=True)
class UsagePoint:
    ts: float                         # epoch seconds, window start
    cpu_mean: float                   # cores
    mem_mean: float                   # bytes (working set)
    cpu_peak: float | None = None     # cores, max within window
    mem_peak: float | None = None     # bytes, max within window
    throttled_seconds: float = 0.0
    duration_seconds: float = 300.0
    oom_kills: int = 0


@dataclass(frozen=True)
class ContainerSpec:
    cpu_request: float                # cores
    mem_request: float                # bytes
    cpu_limit: float | None = None
    mem_limit: float | None = None
    replicas: float = 1.0
    hpa_target_cpu_utilization: float | None = None  # e.g. 0.7 if an HPA scales on CPU


@dataclass(frozen=True)
class Policy:
    cpu_slo_exceedance: float = 0.01   # epsilon: share of time peak CPU may exceed the request
    half_life_hours: float = 48.0      # recency weighting
    min_history_hours: float = 24.0    # below this: no recommendation
    target_history_hours: float = 168.0
    cpu_cv_factor: float = 1.0         # headroom = factor x CV of daily peaks
    cpu_headroom_cap: float = 0.5
    mem_base_headroom: float = 0.10
    mem_cv_factor: float = 0.5
    mem_headroom_cap: float = 0.6
    oom_step: float = 0.25             # extra memory headroom per OOM kill
    oom_cap: float = 1.0
    throttle_threshold: float = 0.05   # throttled share above which peaks count as censored
    leak_growth_threshold: float = 0.15  # relative growth per day that counts as a leak
    leak_horizon_hours: float = 24.0
    max_reduction: float = 0.5         # never cut more than 50 % in one step
    change_threshold: float = 0.10     # ignore changes smaller than 10 %
    min_cpu: float = 0.01
    min_mem: float = 32 * MIB


DEFAULT_POLICY = Policy()


@dataclass
class Recommendation:
    strategy: str
    action: str                       # downsize | upsize | keep | insufficient_data
    cpu_request: float
    mem_request: float
    cpu_limit: float | None
    mem_limit: float | None
    confidence: float
    confidence_label: str
    risk: str                         # low | medium | high
    reasons: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    def monthly_delta(self, spec: ContainerSpec, cpu_hourly: float, ram_hourly_per_gib: float) -> float:
        """Monthly saving (positive) or extra cost (negative) of applying this."""
        d_cpu = spec.cpu_request - self.cpu_request
        d_mem = (spec.mem_request - self.mem_request) / GIB
        return (d_cpu * cpu_hourly + d_mem * ram_hourly_per_gib) * HOURS_PER_MONTH * spec.replicas


# --- statistics helpers -------------------------------------------------------------


def weighted_quantile(values: Sequence[float], weights: Sequence[float], q: float) -> float:
    pairs = sorted((v, w) for v, w in zip(values, weights, strict=True) if w > 0)
    if not pairs:
        return 0.0
    total = sum(w for _, w in pairs)
    target = q * total
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= target - 1e-12:
            return v
    return pairs[-1][0]


def weighted_cv(values: Sequence[float], weights: Sequence[float]) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    mean = sum(v * w for v, w in zip(values, weights, strict=True)) / total
    if mean <= 0:
        return 0.0
    var = sum(w * (v - mean) ** 2 for v, w in zip(values, weights, strict=True)) / total
    return math.sqrt(var) / mean


def decay_weights(points: Sequence[UsagePoint], half_life_hours: float) -> list[float]:
    now = max(p.ts for p in points)
    hl = half_life_hours * 3600
    return [p.duration_seconds * 0.5 ** ((now - p.ts) / hl) for p in points]


def history(points: Sequence[UsagePoint], expected_step: float = 300.0) -> tuple[float, float]:
    """(history span in hours, completeness 0..1 of distinct time slots)."""
    slots = sorted({p.ts for p in points})
    if not slots:
        return 0.0, 0.0
    span = (slots[-1] - slots[0] + expected_step) / 3600
    expected = span * 3600 / expected_step
    return span, min(1.0, len(slots) / expected) if expected else 0.0


def growth_per_day(points: Sequence[UsagePoint], window_hours: float = 48.0) -> float:
    """Relative growth per day of hourly-max memory over the last window (least squares).

    Uses hourly maxima so a sawtooth leak (grow -> OOM -> restart) still shows
    up as positive growth within each tooth; resets are excluded by only
    fitting the most recent monotone run.
    """
    if not points:
        return 0.0
    end = max(p.ts for p in points)
    hourly: dict[int, float] = {}
    for p in points:
        if p.ts >= end - window_hours * 3600:
            h = int(p.ts // 3600)
            hourly[h] = max(hourly.get(h, 0.0), p.mem_peak or p.mem_mean)
    hours = sorted(hourly)
    if len(hours) < 6:
        return 0.0
    # Most recent run without a big drop (a drop > 30 % = restart).
    run = [hours[-1]]
    for h in reversed(hours[:-1]):
        if hourly[h] > hourly[run[0]] * 1.3:
            break
        run.insert(0, h)
    if len(run) < 6:
        return 0.0
    xs = [h - run[0] for h in run]
    ys = [hourly[h] for h in run]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0 or my <= 0:
        return 0.0
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx  # bytes per hour
    return slope * 24 / my


def daily_peak_cv(points: Sequence[UsagePoint]) -> float:
    """Coefficient of variation of the per-day maximum CPU peak.

    Only (nearly) complete UTC days count: a partial first/last day may miss
    the daily peak entirely (e.g. a nightly batch) and would inflate the CV.
    """
    days: dict[int, float] = {}
    slots: dict[int, set] = {}
    step = min((p.duration_seconds for p in points), default=300.0) or 300.0
    for p in points:
        d = int(p.ts // 86400)
        days[d] = max(days.get(d, 0.0), p.cpu_peak if p.cpu_peak is not None else p.cpu_mean)
        slots.setdefault(d, set()).add(p.ts)
    full = 0.8 * 86400 / step
    vals = [v for d, v in days.items() if len(slots[d]) >= full]
    if len(vals) < 3:
        return 0.2   # not enough days to tell: assume moderate variability
    return weighted_cv(vals, [1.0] * len(vals))


def _confidence(span_h: float, completeness: float, policy: Policy) -> tuple[float, str]:
    c = min(1.0, span_h / policy.target_history_hours) * completeness
    return round(c, 3), ("high" if c >= 0.7 else "medium" if c >= 0.35 else "low")


def _cap_reduction(current: float, rec: float, policy: Policy) -> float:
    return max(rec, current * (1 - policy.max_reduction)) if current > 0 else rec


def _finish(strategy: str, spec: ContainerSpec, cpu: float, mem: float, cpu_limit, mem_limit, policy: Policy,
            confidence: float, label: str, risk: str, reasons: list[str], evidence: dict) -> Recommendation:
    cpu = max(policy.min_cpu, cpu)
    mem = max(policy.min_mem, mem)
    rel_cpu = abs(cpu - spec.cpu_request) / spec.cpu_request if spec.cpu_request else 1.0
    rel_mem = abs(mem - spec.mem_request) / spec.mem_request if spec.mem_request else 1.0
    if rel_cpu < policy.change_threshold and rel_mem < policy.change_threshold:
        action = "keep"
    elif (cpu > spec.cpu_request * (1 + policy.change_threshold)
          or mem > spec.mem_request * (1 + policy.change_threshold)):
        action = "upsize"
    else:
        action = "downsize"
    return Recommendation(strategy, action, round(cpu, 4), float(round(mem)), cpu_limit, mem_limit, confidence, label,
                          risk, reasons, evidence)


def _insufficient(strategy: str, spec: ContainerSpec, span_h: float) -> Recommendation:
    return Recommendation(strategy, "insufficient_data", spec.cpu_request, spec.mem_request, spec.cpu_limit,
                          spec.mem_limit, 0.0, "low", "high", [f"only {span_h:.1f} h of history"],
                          {"history_hours": round(span_h, 2)})


# --- strategies ----------------------------------------------------------------------


def slo_aware(points: Sequence[UsagePoint], spec: ContainerSpec, policy: Policy = DEFAULT_POLICY) -> Recommendation:
    span_h, completeness = history(points)
    if span_h < policy.min_history_hours:
        return _insufficient("slo_aware", spec, span_h)
    w = decay_weights(points, policy.half_life_hours)
    reasons: list[str] = []

    # CPU ------------------------------------------------------------------------
    cpu_peaks = [p.cpu_peak if p.cpu_peak is not None else p.cpu_mean for p in points]
    cpu_means = [p.cpu_mean for p in points]
    q_peak = weighted_quantile(cpu_peaks, w, 1 - policy.cpu_slo_exceedance)
    cpu_cv = weighted_cv(cpu_means, w)
    peak_cv = daily_peak_cv(points)
    headroom = min(policy.cpu_headroom_cap, policy.cpu_cv_factor * peak_cv)
    throttled_share = sum(p.throttled_seconds for p in points) / max(1.0, sum(p.duration_seconds for p in points))
    censored = bool(spec.cpu_limit and throttled_share > policy.throttle_threshold)
    cpu = q_peak * (1 + headroom)
    if censored:
        # Peaks are clipped at the limit: true demand is at least the limit,
        # and the more time spent throttled, the further above it.
        cpu = max(cpu, spec.cpu_limit * (1 + throttled_share))
        reasons.append(f"CPU throttled {throttled_share:.0%} of the time at its limit: demand is under-observed")
    if spec.hpa_target_cpu_utilization:
        p95_mean = weighted_quantile(cpu_means, w, 0.95)
        hpa_floor = p95_mean / spec.hpa_target_cpu_utilization
        if cpu < hpa_floor:
            cpu = hpa_floor
            reasons.append("kept high enough not to trigger HPA scale-out")
    if not censored:
        cpu = _cap_reduction(spec.cpu_request, cpu, policy)

    # Memory -----------------------------------------------------------------------
    mem_peaks = [p.mem_peak if p.mem_peak is not None else p.mem_mean for p in points]
    mem_max = max(mem_peaks)
    mem_cv = weighted_cv([p.mem_mean for p in points], w)
    mem_headroom = min(policy.mem_headroom_cap, policy.mem_base_headroom + policy.mem_cv_factor * mem_cv)
    ooms = sum(p.oom_kills for p in points)
    growth = growth_per_day(points)
    leak = growth > policy.leak_growth_threshold
    mem = mem_max * (1 + mem_headroom)
    if leak:
        mem += mem_max * growth * policy.leak_horizon_hours / 24
        reasons.append(f"memory grows {growth:.0%}/day: possible leak, reduction blocked")
    if ooms:
        bump = min(policy.oom_cap, policy.oom_step * ooms)
        ref = spec.mem_limit or mem_max
        mem = max(mem, ref * (1 + bump))
        reasons.append(f"{ooms} OOM kill(s) in the window: memory demand exceeds the limit")
    if leak or ooms:
        mem = max(mem, spec.mem_request)
    else:
        mem = _cap_reduction(spec.mem_request, mem, policy)

    # Limits: keep the shape the workload already uses.
    cpu_limit = None
    if spec.cpu_limit:
        ratio = spec.cpu_limit / spec.cpu_request if spec.cpu_request else 2.0
        cpu_limit = round(max(cpu * ratio, max(cpu_peaks) * 1.1, cpu * 1.2), 4)
    mem_limit = float(round(mem)) if spec.mem_limit else None  # memory: request == limit (no overcommit of RAM)

    conf, label = _confidence(span_h, completeness, policy)
    reduction = max(1 - cpu / spec.cpu_request if spec.cpu_request else 0,
                    1 - mem / spec.mem_request if spec.mem_request else 0)
    if leak or ooms or label == "low" or censored:
        risk = "high"
    elif reduction > 0.4 or cpu_cv > 0.5 or label == "medium":
        risk = "medium"
    else:
        risk = "low"
    if not reasons:
        reasons.append(f"p{(1 - policy.cpu_slo_exceedance) * 100:g} of peak CPU {q_peak:.3f} cores, "
                       f"peak memory {mem_max / MIB:.0f} MiB")
    evidence = {
        "history_hours": round(span_h, 1), "completeness": round(completeness, 3),
        "cpu_peak_quantile": round(q_peak, 4), "cpu_cv": round(cpu_cv, 3),
        "cpu_daily_peak_cv": round(peak_cv, 3), "cpu_headroom": round(headroom, 3),
        "cpu_throttled_share": round(throttled_share, 4), "cpu_censored": censored,
        "mem_peak_bytes": mem_max, "mem_cv": round(mem_cv, 3), "mem_headroom": round(mem_headroom, 3),
        "oom_kills": ooms, "mem_growth_per_day": round(growth, 3), "leak_suspected": leak,
        "cpu_mean_p50": round(weighted_quantile(cpu_means, w, 0.5), 4),
        "cpu_mean_p95": round(weighted_quantile(cpu_means, w, 0.95), 4),
    }
    return _finish("slo_aware", spec, cpu, mem, cpu_limit, mem_limit, policy, conf, label, risk, reasons, evidence)


def p95_buffer(points: Sequence[UsagePoint], spec: ContainerSpec, policy: Policy = DEFAULT_POLICY,
               buffer: float = 0.20) -> Recommendation:
    span_h, completeness = history(points)
    if span_h < policy.min_history_hours:
        return _insufficient("p95_buffer", spec, span_h)
    w = [p.duration_seconds for p in points]
    cpu = weighted_quantile([p.cpu_mean for p in points], w, 0.95) * (1 + buffer)
    mem = weighted_quantile([p.mem_mean for p in points], w, 0.95) * (1 + buffer)
    conf, label = _confidence(span_h, completeness, policy)
    return _finish("p95_buffer", spec, cpu, mem, spec.cpu_limit and cpu * 2, spec.mem_limit and mem, policy,
                   conf, label, "medium", ["p95 of mean usage + 20%"], {})


def vpa(points: Sequence[UsagePoint], spec: ContainerSpec, policy: Policy = DEFAULT_POLICY) -> Recommendation:
    """Approximation of the VPA recommender (target estimator, 24 h half-life)."""
    span_h, completeness = history(points)
    if span_h < policy.min_history_hours:
        return _insufficient("vpa", spec, span_h)
    w = decay_weights(points, 24.0)
    cpu = weighted_quantile([p.cpu_mean for p in points], w, 0.90) * 1.15
    # VPA's memory histogram is fed per-interval peaks; OOMs are recorded as
    # samples of max(1.2 x usage, usage + 100 MiB) at the kill.
    mem_samples = [p.mem_peak or p.mem_mean for p in points]
    mem_w = list(w)
    for p, weight in zip(points, w, strict=True):
        if p.oom_kills:
            base = spec.mem_limit or (p.mem_peak or p.mem_mean)
            mem_samples.append(max(base * 1.2, base + 100 * MIB))
            mem_w.append(weight)
    mem = weighted_quantile(mem_samples, mem_w, 0.90) * 1.15
    conf, label = _confidence(span_h, completeness, policy)
    return _finish("vpa", spec, max(cpu, 0.025), max(mem, 250 * MIB), spec.cpu_limit and cpu * 2,
                   spec.mem_limit and mem, policy, conf, label, "medium", ["VPA-style p90 + 15% margin"], {})


STRATEGIES = {"slo_aware": slo_aware, "vpa": vpa, "p95_buffer": p95_buffer}


def recommend(points: Sequence[UsagePoint], spec: ContainerSpec, strategy: str = "slo_aware",
              policy: Policy = DEFAULT_POLICY) -> Recommendation:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {sorted(STRATEGIES)}")
    return STRATEGIES[strategy](points, spec, policy)


__all__ = ["UsagePoint", "ContainerSpec", "Policy", "DEFAULT_POLICY", "Recommendation", "recommend",
           "STRATEGIES", "slo_aware", "vpa", "p95_buffer", "weighted_quantile"]
