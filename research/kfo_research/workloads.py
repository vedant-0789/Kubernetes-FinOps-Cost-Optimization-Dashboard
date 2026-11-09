"""Synthetic container workloads with known ground truth.

Eight archetypes cover the behaviours reported for production clusters
(diurnal services, bursty APIs, batch jobs, leaks, CPU-capped services,
growth, idle and under-provisioned containers). Parameters are drawn per
container from documented ranges with a fixed seed, so every table and figure
in the paper is reproducible.

Each trace has:
* observed 5-minute windows (mean & peak CPU, mean & peak working set,
  throttled seconds), i.e. what the agent would report;
* ``true_cpu_peak``: the demand before any CPU limit clipped it;
* ``original``: the requests a developer typically sets (mostly 1.5-4x the
  observed peak; some archetypes are under-provisioned).
"""

import math

import numpy as np

from kfo_research.simulate import GIB, Trace, throttled_seconds
from app.engines.rightsizing import ContainerSpec, UsagePoint

MIB = 2**20
SLOT = 300
T0 = 1_788_220_800  # 2026-09-01T00:00:00Z, a Tuesday

ARCHETYPES = ("web_diurnal", "spiky_api", "batch_nightly", "memory_leak", "cpu_capped", "growing",
              "idle", "under_provisioned")


def _clock(days: int):
    n = days * 288
    ts = T0 + np.arange(n) * SLOT
    hour = (ts % 86400) / 3600
    weekday = ((ts // 86400) + 2) % 7          # T0 is a Tuesday -> weekday index 1; Mon=0
    weekend = weekday >= 5
    return n, ts, hour, weekend


def _make(name, archetype, ts, cpu_mean, cpu_peak, mem_mean, mem_peak, original, true_peak=None, throttled=None,
          meta=None) -> Trace:
    throttled = throttled if throttled is not None else np.zeros_like(cpu_mean)
    pts = [UsagePoint(ts=float(t), cpu_mean=float(cm), mem_mean=float(mm), cpu_peak=float(cp), mem_peak=float(mp),
                      throttled_seconds=float(th), duration_seconds=SLOT)
           for t, cm, cp, mm, mp, th in zip(ts, cpu_mean, cpu_peak, mem_mean, mem_peak, throttled, strict=True)]
    return Trace(name, archetype, pts, original,
                 true_cpu_peak=[float(v) for v in true_peak] if true_peak is not None else None, meta=meta or {})


def generate(archetype: str, idx: int, days: int = 21, seed: int = 7) -> Trace:
    rng = np.random.default_rng(seed * 100_003 + idx * 7919 + ARCHETYPES.index(archetype))
    n, ts, hour, weekend = _clock(days)
    name = f"{archetype}-{idx:03d}"
    noise = lambda s: np.clip(rng.normal(1.0, s, n), 0.2, None)  # noqa: E731

    if archetype in ("web_diurnal", "growing", "under_provisioned", "cpu_capped"):
        base = rng.uniform(0.15, 1.5)
        amp = rng.uniform(0.3, 0.7)
        level = 1 + amp * np.cos(2 * math.pi * (hour - 15) / 24)
        level = np.where(weekend, level * rng.uniform(0.6, 0.85), level)
        if archetype == "growing":
            level = level * (1 + rng.uniform(0.02, 0.05)) ** ((ts - T0) / 86400)
        cpu = base * level * noise(rng.uniform(0.05, 0.15))
        burst = 1 + np.abs(rng.normal(0, rng.uniform(0.1, 0.3), n))
        true_peak = cpu * burst
        mem_base = rng.uniform(256, 4096) * MIB
        mem = mem_base * (0.85 + 0.15 * level / level.max()) * noise(0.02)
        mem_peak = mem * (1 + np.abs(rng.normal(0, 0.03, n)))
        peak_ref = np.quantile(true_peak, 0.99)
        if archetype == "under_provisioned":
            cpu_req = peak_ref * rng.uniform(0.45, 0.8)
            mem_req = np.max(mem_peak) * rng.uniform(1.05, 1.3)
        else:
            cpu_req = peak_ref * rng.uniform(1.5, 4.0)
            mem_req = np.max(mem_peak) * rng.uniform(1.5, 4.0)
        throttled = None
        observed_peak, observed_mean = true_peak, cpu
        cpu_limit = None
        if archetype == "cpu_capped":
            # A CPU limit below the real peaks: measurements are clipped and throttled.
            cpu_limit = float(np.quantile(true_peak, rng.uniform(0.70, 0.85)))
            cpu_req = cpu_limit * rng.uniform(0.5, 1.0)
            observed_peak = np.minimum(true_peak, cpu_limit)
            observed_mean = np.minimum(cpu, cpu_limit)
            throttled = np.array([throttled_seconds(float(tp), cpu_limit, SLOT) for tp in true_peak])
        original = ContainerSpec(float(cpu_req), float(mem_req), cpu_limit, float(mem_req))
        t = _make(name, archetype, ts, observed_mean, observed_peak, mem, mem_peak, original, true_peak, throttled,
                  {"base_cpu": base})
        if cpu_limit:
            t.true_cpu_mean = [float(v) for v in cpu]
        return t

    if archetype == "spiky_api":
        base = rng.uniform(0.05, 0.6)
        p = rng.uniform(0.01, 0.05)
        mult = rng.uniform(2.0, 5.0)
        spikes = np.where(rng.random(n) < p, mult, 1.0)
        cpu = base * spikes * noise(0.1)
        true_peak = cpu * (1 + np.abs(rng.normal(0, 0.3, n)))
        mem = rng.uniform(128, 2048) * MIB * (1 + 0.1 * (spikes > 1)) * noise(0.02)
        mem_peak = mem * 1.03
        original = ContainerSpec(float(np.quantile(true_peak, 0.99) * rng.uniform(1.2, 3.0)),
                                 float(mem_peak.max() * rng.uniform(1.5, 3.0)), None, None)
        return _make(name, archetype, ts, cpu, true_peak, mem, mem_peak, original, true_peak)

    if archetype == "batch_nightly":
        start = rng.uniform(0, 3)
        length = rng.uniform(2, 4)
        on = (hour >= start) & (hour < start + length)
        cpu_on = rng.uniform(1.0, 6.0)
        cpu = np.where(on, cpu_on, 0.01) * noise(0.04)
        true_peak = cpu * (1 + np.abs(rng.normal(0, 0.05, n)))
        mem_on = rng.uniform(1024, 8192) * MIB
        mem = np.where(on, mem_on, mem_on * 0.2) * noise(0.02)
        mem_peak = mem * 1.02
        original = ContainerSpec(float(cpu_on * rng.uniform(1.0, 2.0)), float(mem_on * rng.uniform(1.2, 2.5)),
                                 None, None)
        return _make(name, archetype, ts, cpu, true_peak, mem, mem_peak, original, true_peak)

    if archetype == "memory_leak":
        base = rng.uniform(0.1, 0.8)
        cpu = base * noise(0.1)
        true_peak = cpu * 1.3
        mem0 = rng.uniform(256, 1024) * MIB
        rate = rng.uniform(5, 25) * MIB / 3600            # bytes per second
        restart_h = rng.uniform(24, 96)                   # periodic redeploys reset the leak
        age = (ts - T0) % (restart_h * 3600)
        mem = mem0 + rate * age
        mem_peak = mem * 1.01
        cycle_peak = mem0 + rate * restart_h * 3600
        original = ContainerSpec(float(np.quantile(true_peak, 0.99) * rng.uniform(1.5, 3.0)),
                                 float(cycle_peak * rng.uniform(1.2, 2.0)), None, None)
        return _make(name, archetype, ts, cpu, true_peak, mem, mem_peak, original, true_peak,
                     meta={"leak_mib_per_hour": rate * 3600 / MIB})

    if archetype == "idle":
        cpu = rng.uniform(0.001, 0.01) * noise(0.3)
        mem = rng.uniform(32, 256) * MIB * noise(0.02)
        original = ContainerSpec(float(rng.uniform(0.25, 2.0)), float(rng.uniform(512, 4096) * MIB), None, None)
        return _make(name, archetype, ts, cpu, cpu * 1.5, mem, mem * 1.01, original, cpu * 1.5)

    raise ValueError(archetype)


def population(per_archetype: int = 15, days: int = 21, seed: int = 7) -> list[Trace]:
    return [generate(a, i, days, seed) for a in ARCHETYPES for i in range(per_archetype)]


__all__ = ["ARCHETYPES", "generate", "population", "GIB"]
