"""Agent loop: `python -m finops_agent.main`."""

import datetime
import logging
import signal
import threading
import time

from prometheus_client import Counter, Gauge, start_http_server

from finops_agent import __version__
from finops_agent.clients import FatalPushError, PrometheusClient, ServerClient
from finops_agent.config import AgentConfig
from finops_agent.inventory import collect_inventory
from finops_agent.usage import build_samples, render_queries

logger = logging.getLogger("agent")

SLOTS_PUSHED = Counter("finops_agent_slots_pushed_total", "Usage slots pushed to the server")
SAMPLES_PUSHED = Counter("finops_agent_samples_pushed_total", "Container samples pushed")
ERRORS = Counter("finops_agent_errors_total", "Collection or push errors", ["stage"])
LAST_SLOT = Gauge("finops_agent_last_slot_timestamp_seconds", "Start of the last slot pushed")
LAST_INVENTORY = Gauge("finops_agent_last_inventory_timestamp_seconds", "Last successful inventory push")


def floor_slot(epoch: float, slot: int) -> int:
    return int(epoch // slot * slot)


class Agent:
    def __init__(self, cfg: AgentConfig, prom: PrometheusClient, server: ServerClient, kube_apis=None,
                 clock=time.time):
        self.cfg = cfg
        self.prom = prom
        self.server = server
        self.kube_apis = kube_apis  # (core, apps, batch, autoscaling) or None
        self.clock = clock
        self.queries = render_queries(cfg.slot_seconds)
        self.next_slot: int | None = None
        self.last_inventory = 0.0

    # --- one slot ------------------------------------------------------------------
    def collect_slot(self, slot_start: int) -> tuple[list[dict], list[dict]]:
        at = slot_start + self.cfg.slot_seconds
        results = {name: self.prom.instant(q, at) for name, q in self.queries.items()}
        ts = datetime.datetime.fromtimestamp(slot_start, datetime.UTC)
        return build_samples(results, ts, self.cfg.slot_seconds, self.cfg.excluded_namespaces)

    def push_slot(self, slot_start: int) -> int:
        samples, nodes = self.collect_slot(slot_start)
        size = self.cfg.batch_size
        for i in range(0, max(len(samples), 1), size):
            chunk = samples[i:i + size]
            payload = {"samples": chunk, "node_samples": nodes if i == 0 else []}
            if chunk or payload["node_samples"]:
                self.server.post("/api/v1/ingest/samples", payload)
        SLOTS_PUSHED.inc()
        SAMPLES_PUSHED.inc(len(samples))
        LAST_SLOT.set(slot_start)
        return len(samples)

    def push_inventory(self) -> None:
        if self.kube_apis is None:
            return
        core, apps, batch, autoscaling = self.kube_apis
        payload = collect_inventory(core, apps, batch, self.cfg.excluded_namespaces, autoscaling)
        payload["agent_version"] = f"kubefinops-agent/{__version__}"
        self.server.post("/api/v1/ingest/inventory", payload)
        self.last_inventory = self.clock()
        LAST_INVENTORY.set(self.last_inventory)

    # --- loop ------------------------------------------------------------------------
    def latest_ready_slot(self) -> int:
        """Most recent slot whose window has closed and been scraped."""
        return floor_slot(self.clock() - self.cfg.scrape_lag_seconds, self.cfg.slot_seconds) - self.cfg.slot_seconds

    def tick(self) -> int:
        """Do whatever work is due. Returns number of slots pushed."""
        if self.clock() - self.last_inventory >= self.cfg.inventory_interval_seconds:
            try:
                self.push_inventory()
            except FatalPushError:
                raise
            except Exception:
                ERRORS.labels("inventory").inc()
                logger.exception("Inventory push failed")

        ready = self.latest_ready_slot()
        if self.next_slot is None:
            self.next_slot = ready - self.cfg.backfill_hours * 3600 + self.cfg.slot_seconds
        pushed = 0
        while self.next_slot <= ready:
            try:
                n = self.push_slot(self.next_slot)
            except FatalPushError:
                raise
            except Exception:
                ERRORS.labels("usage").inc()
                logger.exception("Slot %s failed; will retry next tick", self.next_slot)
                break
            logger.info("Pushed slot %s (%d samples)",
                        datetime.datetime.fromtimestamp(self.next_slot, datetime.UTC).isoformat(), n)
            self.next_slot += self.cfg.slot_seconds
            pushed += 1
        return pushed


def _kube_apis():
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api(), client.AppsV1Api(), client.BatchV1Api(), client.AutoscalingV2Api()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per query is noise
    cfg = AgentConfig.from_env()
    start_http_server(cfg.metrics_port)
    agent = Agent(cfg, PrometheusClient(cfg.prometheus_url, cfg.request_timeout_seconds),
                  ServerClient(cfg.server_url, cfg.token, cfg.request_timeout_seconds, cfg.max_retries),
                  kube_apis=_kube_apis())
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    logger.info("Agent %s started: server=%s prometheus=%s", __version__, cfg.server_url, cfg.prometheus_url)
    while not stop.is_set():
        try:
            agent.tick()
        except FatalPushError as exc:
            # Wrong/revoked token or disabled cluster: keep running (so the
            # pod is visible and fixable) but don't hammer the server.
            ERRORS.labels("fatal").inc()
            logger.error("%s - check the agent token / cluster status", exc)
            stop.wait(300)
            continue
        stop.wait(30)
    logger.info("Agent stopped")


if __name__ == "__main__":
    main()
