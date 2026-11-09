import pytest

from kfo_research.simulate import Trace, replay, static, strategy, summarize
from kfo_research.workloads import ARCHETYPES, generate, population
from app.engines.rightsizing import ContainerSpec, UsagePoint

GIB = 2**30


def flat_trace(days=10, cpu=0.5, mem=1 * GIB, req_cpu=2.0, req_mem=4 * GIB):
    pts = [UsagePoint(ts=1_788_220_800 + i * 300, cpu_mean=cpu, mem_mean=mem, cpu_peak=cpu, mem_peak=mem)
           for i in range(days * 288)]
    return Trace("flat", "test", pts, ContainerSpec(req_cpu, req_mem))


def test_static_strategy_reproduces_original_cost():
    o = replay(flat_trace(), "static", static)
    assert o.windows == 3 * 288                        # 10 days - 7 warm-up
    assert o.cost == pytest.approx(o.orig_cost)
    assert o.savings_pct == pytest.approx(0)
    assert o.cpu_under_windows == 0 and o.oom_events == 0


def test_downsizing_saves_and_respects_step_cap():
    o = replay(flat_trace(days=12), "slo_aware", strategy("slo_aware"))
    assert o.savings_pct > 40
    # Day 1 halves (cap), day 2 halves again..., never below what was observed.
    assert o.final_cpu >= 0.5 and o.final_mem >= 1 * GIB
    assert o.cpu_under_windows == 0 and o.oom_events == 0


def test_oom_events_are_counted_and_fed_back():
    t = flat_trace(days=12, mem=3 * GIB, req_mem=2 * GIB)   # memory request already too small
    o = replay(t, "slo_aware", strategy("slo_aware"))
    assert o.orig_oom_events > 0
    assert o.oom_events < o.orig_oom_events                # the strategy raised the request
    assert o.final_mem > 2 * GIB


def test_true_peak_is_used_for_under_provisioning():
    t = flat_trace(days=9)
    t.true_cpu_peak = [5.0] * len(t.points)                # demand far above anything observed
    o = replay(t, "static", static)
    assert o.cpu_under_rate == 1.0 and o.cpu_deficit_core_hours > 0


@pytest.mark.parametrize("archetype", ARCHETYPES)
def test_every_archetype_generates_a_valid_trace(archetype):
    t = generate(archetype, 0, days=10)
    assert len(t.points) == 10 * 288
    assert t.original.cpu_request > 0 and t.original.mem_request > 0
    assert all(p.cpu_peak >= p.cpu_mean - 1e-9 for p in t.points)
    if archetype == "cpu_capped":
        assert t.original.cpu_limit and max(p.cpu_peak for p in t.points) <= t.original.cpu_limit + 1e-9
        assert max(t.true_cpu_peak) > t.original.cpu_limit          # demand really is clipped


def test_generation_is_deterministic():
    a, b = generate("spiky_api", 3, days=8), generate("spiky_api", 3, days=8)
    assert [p.cpu_mean for p in a.points[:50]] == [p.cpu_mean for p in b.points[:50]]


def test_summary_aggregates():
    outs = [replay(t, "static", static) for t in population(per_archetype=1, days=9)]
    s = summarize(outs)
    assert s.containers == len(ARCHETYPES) and s.savings_pct == pytest.approx(0)


def test_raising_the_limit_is_reobserved_and_does_not_explode():
    """Regression: replaying a clipped trace kept reporting the old throttling
    after the strategy raised the limit, and the strategy compounded."""
    t = generate("cpu_capped", 1, days=14)
    o = replay(t, "slo_aware", strategy("slo_aware"))
    assert o.final_cpu < 3 * max(t.true_cpu_peak)               # bounded
    assert o.savings_pct > -300
    base = replay(t, "static", static)
    assert o.cpu_under_rate < base.cpu_under_rate                # correction helps
