import datetime
import logging
import random
import time

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.observability import JOB_DURATION, JOB_RUNS
from app.db.database import SessionLocal
from app.db.models import MetricsSnapshot, SystemSetting
from app.engine.cost_calculator import CostCalculator
from app.engine.right_sizer import RightSizer
from app.engine.zombie_detector import ZombieDetector

logger = logging.getLogger("scheduler")
scheduler = BackgroundScheduler()


def periodic_metrics_collection():
    """Refresh metrics, recalculate costs and re-run the optimisation engines."""
    start = time.perf_counter()
    db = SessionLocal()
    try:
        settings_dict = {s.key: s.value for s in db.query(SystemSetting).all()}
        cpu_rate = float(settings_dict.get("cpu_hourly_rate", 0.048))
        ram_rate = float(settings_dict.get("ram_hourly_rate", 0.006))
        idle_threshold = float(settings_dict.get("idle_cpu_threshold_pct", 5.0))
        mock_mode = settings_dict.get("mock_mode", "true").lower() == "true"

        if mock_mode:
            latest_snaps = (
                db.query(MetricsSnapshot).order_by(MetricsSnapshot.timestamp.desc()).limit(25).all()
            )
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
        JOB_RUNS.labels("collect", "success").inc()
    except Exception:
        db.rollback()
        JOB_RUNS.labels("collect", "error").inc()
        logger.exception("Scheduler job failed")
    finally:
        db.close()
        JOB_DURATION.labels("collect").observe(time.perf_counter() - start)


def start_scheduler(interval_seconds: int = 30):
    if not scheduler.running:
        scheduler.add_job(
            periodic_metrics_collection, "interval", seconds=interval_seconds,
            id="finops_collector", max_instances=1, coalesce=True, replace_existing=True,
        )
        scheduler.start()
        logger.info("Background scheduler started (%ss interval).", interval_seconds)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
