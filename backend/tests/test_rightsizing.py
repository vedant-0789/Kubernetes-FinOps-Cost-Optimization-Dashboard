import math
import random

import pytest

from app.engines.rightsizing import (
    GIB,
    MIB,
    ContainerSpec,
    Policy,
    UsagePoint,
    p95_buffer,
    recommend,
    slo_aware,
    vpa,
    weighted_quantile,
)

STEP = 300
T0 = 1_790_000_000 // 3600 * 3600


def series(days=7, cpu=lambda t, r: 0.2, mem=lambda t, r: 256 * MIB, peak_factor=1.3, seed=1, **kw):
    """5-minute points; cpu/mem are functions of (hours since start, rng)."""
    rng = random.Random(seed)
    pts = []
    for i in range(int(days * 24 * 12)):
        h = i / 12
        c, m = cpu(h, rng), mem(h, rng)
        pts.append(UsagePoint(ts=T0 + i * STEP, cpu_mean=c, mem_mean=m, cpu_peak=c * peak_factor,
                              mem_peak=m * 1.02, **{k: (v(h, rng) if callable(v) else v) for k, v in kw.items()}))
    return pts


def diurnal(base, amp):
    return lambda h, r: max(0.001, base * (1 + amp * math.cos(2 * math.pi * (h - 15) / 24)) * r.gauss(1, 0.05))


SPEC = ContainerSpec(cpu_request=2.0, mem_request=4 * GIB, cpu_limit=None, mem_limit=None)


def test_weighted_quantile_basics():
    assert weighted_quantile([1, 2, 3, 4], [1, 1, 1, 1], 0.5) == 2
    assert weighted_quantile([1, 100], [99, 1], 0.95) == 1
    assert weighted_quantile([1, 100], [99, 1], 0.995) == 100


def test_insufficient_history_gives_no_change():
    r = slo_aware(series(days=0.5), SPEC)
    assert r.action == "insufficient_data"
    assert (r.cpu_request, r.mem_request) == (SPEC.cpu_request, SPEC.mem_request)


def test_overprovisioned_steady_service_is_downsized_within_step_cap():
    r = slo_aware(series(cpu=diurnal(0.3, 0.4)), SPEC)
    assert r.action == "downsize"
    assert r.cpu_request == pytest.approx(1.0)       # capped at -50 % in one step
    assert r.mem_request == pytest.approx(2 * GIB)
    assert r.confidence_label == "high"


def test_without_step_cap_recommendation_covers_peaks_with_slo_budget():
    pts = series(cpu=diurnal(0.3, 0.4))
    r = slo_aware(pts, SPEC, Policy(max_reduction=1.0))
    peaks = sorted(p.cpu_peak for p in pts)
    exceed = sum(p > r.cpu_request for p in peaks) / len(peaks)
    assert exceed <= 0.01                             # SLO budget epsilon = 1 %
    assert r.cpu_request < 0.7                        # but still a big cut from 2 cores
    assert r.mem_request == pytest.approx(256 * MIB * 1.02 * (1 + r.evidence["mem_headroom"]), rel=1e-3)


def test_peak_based_cpu_protects_spiky_service_better_than_p95_of_means():
    spiky = series(cpu=lambda h, r: 0.2 * (4 if r.random() < 0.03 else 1), peak_factor=1.5)
    ours = slo_aware(spiky, SPEC, Policy(max_reduction=1.0))
    naive = p95_buffer(spiky, SPEC)

    def exceed(rec):
        return sum((p.cpu_peak or p.cpu_mean) > rec.cpu_request + 1e-9 for p in spiky) / len(spiky)

    assert exceed(ours) <= 0.01 < exceed(naive)


def test_nightly_batch_job_gets_no_volatility_penalty():
    # Runs 01:00-04:00 at ~3.2 cores every night, idle otherwise: the nightly
    # peak is the same every day, so headroom should stay small.
    batch = series(days=7, cpu=lambda h, r: (3.2 if 1 <= h % 24 < 4 else 0.05) * r.gauss(1, 0.03), peak_factor=1.1)
    r = slo_aware(batch, ContainerSpec(4.0, 8 * GIB), Policy(max_reduction=1.0))
    assert r.evidence["cpu_cv"] > 1.0            # overall CV is huge (on/off) ...
    assert r.evidence["cpu_headroom"] < 0.1      # ... but daily peaks are stable
    assert r.cpu_request < 4.2


def test_variable_daily_peaks_get_more_headroom():
    stable = series(days=7, cpu=diurnal(0.5, 0.3))
    erratic = series(days=7, cpu=lambda h, r: 0.5 * (1 + (int(h // 24) % 3)) * r.gauss(1, 0.05))
    assert slo_aware(erratic, SPEC).evidence["cpu_headroom"] > slo_aware(stable, SPEC).evidence["cpu_headroom"]


def test_throttled_container_is_treated_as_censored_and_upsized():
    spec = ContainerSpec(cpu_request=0.1, mem_request=64 * MIB, cpu_limit=0.25, mem_limit=128 * MIB)
    # Usage pinned at the 0.25 limit and throttled the whole window.
    pts = series(cpu=lambda h, r: 0.25, mem=lambda h, r: 10 * MIB, peak_factor=1.0, throttled_seconds=290.0)
    r = slo_aware(pts, spec)
    assert r.evidence["cpu_censored"] is True
    assert r.cpu_request > spec.cpu_limit
    assert r.action == "upsize" and r.risk == "high"
    # The VPA approximation trusts the clipped data and lands at ~limit.
    assert vpa(pts, spec).cpu_request <= spec.cpu_limit * 1.15 + 1e-9


def test_oom_kills_raise_memory_above_the_limit():
    spec = ContainerSpec(cpu_request=0.1, mem_request=128 * MIB, mem_limit=192 * MIB)

    def sawtooth(h, r):
        return (64 + (h % 2) * 60) * MIB      # grows to ~184 MiB then restarts every 2 h

    pts = series(mem=sawtooth, oom_kills=lambda h, r: 1 if (h % 2) < 1 / 12 and h > 0 else 0)
    r = slo_aware(pts, spec)
    assert r.evidence["oom_kills"] > 0
    assert r.mem_request > spec.mem_limit
    assert r.mem_limit == r.mem_request
    assert r.risk == "high"


def test_leak_blocks_memory_reduction():
    spec = ContainerSpec(cpu_request=0.5, mem_request=4 * GIB)
    leaking = series(days=3, mem=lambda h, r: (500 + 20 * h) * MIB)   # +20 MiB/h
    r = slo_aware(leaking, spec)
    assert r.evidence["leak_suspected"] is True
    assert r.mem_request >= spec.mem_request


def test_steady_memory_is_not_flagged_as_leak():
    r = slo_aware(series(mem=lambda h, r: 512 * MIB * r.gauss(1, 0.02)), SPEC)
    assert r.evidence["leak_suspected"] is False


def test_hpa_target_prevents_scale_out_feedback():
    pts = series(cpu=diurnal(0.6, 0.3))
    plain = slo_aware(pts, SPEC, Policy(max_reduction=1.0))
    with_hpa = slo_aware(pts, ContainerSpec(2.0, 4 * GIB, hpa_target_cpu_utilization=0.5), Policy(max_reduction=1.0))
    p95 = with_hpa.evidence["cpu_mean_p95"]
    assert with_hpa.cpu_request == pytest.approx(max(p95 / 0.5, plain.cpu_request), rel=1e-3)
    assert with_hpa.cpu_request >= plain.cpu_request


def test_floors_and_keep_action():
    tiny = slo_aware(series(cpu=lambda h, r: 0.0001, mem=lambda h, r: 1 * MIB),
                     ContainerSpec(0.01, 32 * MIB), Policy(max_reduction=1.0))
    assert tiny.cpu_request == 0.01 and tiny.mem_request == 32 * MIB
    assert tiny.action == "keep"


def test_monthly_delta_uses_replicas_and_prices():
    r = slo_aware(series(cpu=diurnal(0.3, 0.4)), ContainerSpec(2.0, 4 * GIB, replicas=3))
    saving = r.monthly_delta(ContainerSpec(2.0, 4 * GIB, replicas=3), cpu_hourly=0.03, ram_hourly_per_gib=0.004)
    expected = ((2.0 - r.cpu_request) * 0.03 + (4 - r.mem_request / GIB) * 0.004) * 730 * 3
    assert saving == pytest.approx(expected)
    assert saving > 0


def test_recent_behaviour_dominates_with_decay():
    # A week at 1.0 core, then the last day at 0.2 cores (workload got lighter).
    pts = series(days=8, cpu=lambda h, r: 1.0 if h < 7 * 24 else 0.2, peak_factor=1.0)
    # With a 2 h half-life the old regime keeps < epsilon of the weight; with 6 h it
    # still holds ~6 % (> 1 % budget), so the method rightly stays conservative.
    fast = slo_aware(pts, SPEC, Policy(max_reduction=1.0, half_life_hours=2))
    slow = slo_aware(pts, SPEC, Policy(max_reduction=1.0, half_life_hours=10_000))
    assert fast.cpu_request < 0.5 < slow.cpu_request


@pytest.mark.parametrize("strategy", ["slo_aware", "vpa", "p95_buffer"])
def test_all_strategies_return_valid_recommendations(strategy):
    r = recommend(series(cpu=diurnal(0.3, 0.4)), SPEC, strategy)
    assert r.strategy == strategy and r.cpu_request > 0 and r.mem_request > 0


def test_unknown_strategy():
    with pytest.raises(ValueError):
        recommend(series(), SPEC, "magic")
