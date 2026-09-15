import random
import datetime
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from app.db.database import SessionLocal
from app.db.models import MetricsSnapshot, SystemSetting
from app.engine.cost_calculator import CostCalculator
from app.engine.zombie_detector import ZombieDetector
from app.engine.right_sizer import RightSizer

logger = logging.getLogger("scheduler")
scheduler = BackgroundScheduler()

def periodic_metrics_collection():
    """
    Periodic job that runs every 30 seconds to refresh metrics, recalculate costs,
    and trigger continuous FinOps optimization logic.
    """
    db = SessionLocal()
    try:
        # Load system settings
        settings_dict = {}
        for s in db.query(SystemSetting).all():
            settings_dict[s.key] = s.value
            
        cpu_rate = float(settings_dict.get("cpu_hourly_rate", 0.048))
        ram_rate = float(settings_dict.get("ram_hourly_rate", 0.006))
        idle_threshold = float(settings_dict.get("idle_cpu_threshold_pct", 5.0))
        mock_mode = settings_dict.get("mock_mode", "true").lower() == "true"
        
        if mock_mode:
            # Simulate real-time metric jitter (±3%)
            latest_snaps = db.query(MetricsSnapshot).order_by(MetricsSnapshot.timestamp.desc()).limit(25).all()
            now = datetime.datetime.utcnow()
            for snap in latest_snaps:
                if snap.cpu_req > 0: # Active pod
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
            
        # Re-run zombie detector & right-sizer engine
        ZombieDetector.evaluate(db, idle_cpu_threshold_pct=idle_threshold, cpu_rate=cpu_rate, ram_rate=ram_rate)
        RightSizer.evaluate(db, safety_buffer_pct=20.0, cpu_rate=cpu_rate, ram_rate=ram_rate)
        
    except Exception as e:
        logger.error(f"Scheduler job error: {e}")
    finally:
        db.close()

def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(periodic_metrics_collection, 'interval', seconds=30, id='finops_collector')
        scheduler.start()
        logger.info("FinOps background scheduler started (30s interval).")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
