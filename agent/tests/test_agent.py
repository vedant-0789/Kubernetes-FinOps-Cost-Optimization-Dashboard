import httpx
import pytest

from finops_agent.clients import FatalPushError, PrometheusClient, ServerClient
from finops_agent.config import AgentConfig
from finops_agent.main import Agent

NOW = 1_794_312_000  # 2026-11-10T12:00:00Z, a multiple of 300


class FakeProm:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def instant(self, query, at):
        self.calls.append(at)
        if self.fail_at is not None and at == self.fail_at:
            raise httpx.ConnectError("prometheus down")
        if "container_cpu_usage_seconds_total" in query and "max_over_time" not in query:
            return [({"namespace": "a", "pod": "p", "container": "c"}, 0.1)]
        if "kube_node_info" in query:
            return [({"node": "n1"}, 10)]
        return []


class FakeServer:
    def __init__(self, fatal=False):
        self.posts = []
        self.fatal = fatal

    def post(self, path, payload):
        if self.fatal:
            raise FatalPushError("401")
        self.posts.append((path, payload))
        return {"accepted": len(payload.get("samples", []))}


def cfg(**kw):
    base = dict(server_url="http://server", token="kfo_x_y", backfill_hours=1, scrape_lag_seconds=60)
    return AgentConfig(**(base | kw))


def test_first_tick_backfills_then_only_new_slots():
    clock = [NOW + 61]
    server = FakeServer()
    agent = Agent(cfg(), FakeProm(), server, clock=lambda: clock[0])
    assert agent.tick() == 12  # one hour of 5-minute slots
    sample_posts = [p for path, p in server.posts if path.endswith("/samples")]
    assert len(sample_posts) == 12
    assert sample_posts[0]["node_samples"][0]["node"] == "n1"
    assert agent.tick() == 0  # nothing new yet
    clock[0] += 300
    assert agent.tick() == 1


def test_failed_slot_is_retried_on_next_tick_not_skipped():
    clock = [NOW + 61]
    ready = NOW - 300  # latest ready slot start
    prom = FakeProm(fail_at=ready - 300 + 300)  # second-to-last slot's evaluation time
    agent = Agent(cfg(), prom, FakeServer(), clock=lambda: clock[0])
    pushed = agent.tick()
    assert pushed == 10 and agent.next_slot == ready - 300
    prom.fail_at = None
    assert agent.tick() == 2


def test_fatal_push_errors_propagate():
    agent = Agent(cfg(), FakeProm(), FakeServer(fatal=True), clock=lambda: NOW + 61)
    with pytest.raises(FatalPushError):
        agent.tick()


def test_large_slots_are_split_into_batches():
    class BigProm(FakeProm):
        def instant(self, query, at):
            if "container_cpu_usage_seconds_total" in query and "max_over_time" not in query:
                return [({"namespace": "a", "pod": f"p{i}", "container": "c"}, 0.1) for i in range(5)]
            return super().instant(query, at)

    server = FakeServer()
    agent = Agent(cfg(batch_size=2), BigProm(), server, clock=lambda: NOW + 61)
    agent.push_slot(NOW - 300)
    sizes = [len(p["samples"]) for _, p in server.posts]
    assert sizes == [2, 2, 1]
    assert sum(len(p["node_samples"]) for _, p in server.posts) == 1  # heartbeats sent once


# --- HTTP clients ------------------------------------------------------------------


def test_server_client_retries_5xx_then_succeeds():
    responses = iter([httpx.Response(503), httpx.Response(502), httpx.Response(200, json={"accepted": 1})])
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        return next(responses)

    client = ServerClient("http://s", "kfo_tok", http=httpx.Client(transport=httpx.MockTransport(handler)),
                          sleep=lambda s: None)
    assert client.post("/x", {})["accepted"] == 1
    assert seen == ["Bearer kfo_tok"] * 3


@pytest.mark.parametrize("status", [401, 403, 422])
def test_server_client_does_not_retry_client_errors(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, text="nope")

    client = ServerClient("http://s", "t", http=httpx.Client(transport=httpx.MockTransport(handler)),
                          sleep=lambda s: None)
    with pytest.raises(FatalPushError):
        client.post("/x", {})
    assert len(calls) == 1


def test_prometheus_client_parses_vectors_and_drops_nan():
    body = {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"pod": "a"}, "value": [1, "0.5"]}, {"metric": {"pod": "b"}, "value": [1, "NaN"]}]}}
    prom = PrometheusClient("http://p", http=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=body))))
    assert prom.instant("up", 1) == [({"pod": "a"}, 0.5)]
