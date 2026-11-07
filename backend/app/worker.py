"""Standalone worker process: `python -m app.worker`.

Runs the periodic FinOps jobs outside the API so API replicas can scale
horizontally without each one running (and racing) the same jobs.
Exposes its own Prometheus metrics on FINOPS_WORKER_METRICS_PORT (default 9100).
"""

import logging
import os
import signal
import threading

from prometheus_client import start_http_server

from app.core.config import settings
from app.core.logging import configure_logging
from app.engine.scheduler import periodic_metrics_collection, start_scheduler, stop_scheduler

logger = logging.getLogger("worker")


def main() -> None:
    configure_logging(settings.log_level, settings.log_json)
    start_http_server(int(os.environ.get("FINOPS_WORKER_METRICS_PORT", "9100")))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    periodic_metrics_collection()  # run once immediately
    start_scheduler(settings.collection_interval_seconds)
    logger.info("Worker started.")
    stop.wait()
    stop_scheduler()
    logger.info("Worker stopped.")


if __name__ == "__main__":
    main()
