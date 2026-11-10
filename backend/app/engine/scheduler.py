import datetime
import logging
import random
import time
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.core.observability import JOB_DURATION, JOB_RUNS
from app.db.database import SessionLocal
from app.db.models import MetricsSnapshot, SystemSetting
from app.engine.cost_calculator import CostCalculator
from app.engine.right_sizer import RightSizer
from app.engine.zombie_detector import ZombieDetector

logger = logging.getLogger("scheduler")
scheduler = BackgroundScheduler()


def _instrumented(name: str, fn: Callable) -> Callable[[], None]:
    def run() -> None:
        start = time.perf_counter()
        db = SessionLocal()
        try:
            fn(db)
            JOB_RUNS.labels(name, "success").inc()
        except Exception:
            db.rollback()
            JOB_RUNS.labels(name, "error").inc()
            logger.exception("Job %s failed", name)
        finally:
            db.close()
            JOB_DURATION.labels(name).observe(time.perf_counter() - start)

    run.__name__ = f"job_{name}"
    return run


def _legacy_collect(db) -> None:
    """v1 dashboard: jitter the synthetic snapshots and re-run the v1 engines."""
    settings_dict = {s.key: s.value for s in db.query(SystemSetting).all()}
    cpu_rate = float(settings_dict.get("cpu_hourly_rate", 0.048))
    ram_rate = float(settings_dict.get("ram_hourly_rate", 0.006))
    idle_threshold = float(settings_dict.get("idle_cpu_threshold_pct", 5.0))
    mock_mode = settings_dict.get("mock_mode", "true").lower() == "true"

    if mock_mode:
        latest_snaps = db.query(MetricsSnapshot).order_by(MetricsSnapshot.timestamp.desc()).limit(25).all()
        now = datetime.datetime.utcnow()
        for snap in latest_snaps:
            if snap.cpu_req > 0:
                jitter = random.uniform(0.97, 1.03)
                new_cpu_u = max(0.005, round(snap.cpu_usage * jitter, 3))
                new_mem_u = max(20.0, round(snap.mem_usage_mb * jitter, 1))
                c_info = CostCalculator.calculate_pod_cost(
                    snap.cpu_req, new_cpu_u, snap.mem_req_mb, new_mem_u, cpu_rate, ram_rate
                )
                snap.cpu_usage = new_cpu_u
                snap.mem_usage_mb = new_mem_u
                snap.hourly_cost = c_info["hourly_cost"]
                snap.monthly_cost = c_info["monthly_cost"]
                snap.efficiency_pct = c_info["efficiency_pct"]
                snap.timestamp = now
        db.commit()

    ZombieDetector.evaluate(db, idle_cpu_threshold_pct=idle_threshold, cpu_rate=cpu_rate, ram_rate=ram_rate)
    RightSizer.evaluate(db, safety_buffer_pct=20.0, cpu_rate=cpu_rate, ram_rate=ram_rate)


def _demo_tick(db) -> None:
    from app.services.demo import demo_tick

    demo_tick(db)


def _allocate(db) -> None:
    from app.services.allocation_job import run_allocation

    run_allocation(db)


def _analyze(db) -> None:
    from app.services.analysis import run_analysis

    run_analysis(db)


def _verify(db) -> None:
    from app.services.remediation import verify_applied

    verify_applied(db)


def _finance(db) -> None:
    from app.services.finance import run_finance

    run_finance(db)


# Kept for the worker's "run once at start" call and existing imports.
periodic_metrics_collection = _instrumented("collect", _legacy_collect)


def run_all_once() -> None:
    periodic_metrics_collection()
    if settings.seed_demo_data:
        _instrumented("demo", _demo_tick)()
    _instrumented("allocate", _allocate)()
    _instrumented("analyze", _analyze)()
    _instrumented("finance", _finance)()


def start_scheduler(interval_seconds: int = 30):
    if scheduler.running:
        return
    jobs = [("collect", _legacy_collect, interval_seconds),
            ("allocate", _allocate, settings.allocation_interval_seconds),
            ("analyze", _analyze, settings.analysis_interval_seconds),
            ("verify", _verify, 60),
            ("finance", _finance, settings.finance_interval_seconds)]
    if settings.seed_demo_data:
        jobs.append(("demo", _demo_tick, 60))
    for name, fn, every in jobs:
        scheduler.add_job(_instrumented(name, fn), "interval", seconds=every, id=f"finops_{name}",
                          max_instances=1, coalesce=True, replace_existing=True)
    scheduler.start()
    logger.info("Background scheduler started: %s", ", ".join(f"{n}/{s}s" for n, _, s in jobs))


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
