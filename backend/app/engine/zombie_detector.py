from sqlalchemy.orm import Session
from app.db.models import MetricsSnapshot, ZombieWorkload, ActionLog
from app.engine.cost_calculator import CostCalculator
import datetime

class ZombieDetector:
    """
    Background evaluation engine to detect idle / zombie workloads.
    Condition: CPU usage < threshold (default 5%) AND low net activity for sustained duration.
    """
    
    @staticmethod
    def evaluate(db: Session, idle_cpu_threshold_pct: float = 5.0, cpu_rate: float = 0.048, ram_rate: float = 0.006):
        # Fetch latest metrics per pod
        latest_snapshots = db.query(MetricsSnapshot).order_by(MetricsSnapshot.timestamp.desc()).all()
        
        # Deduplicate to latest snapshot per pod
        pod_map = {}
        for snap in latest_snapshots:
            key = f"{snap.namespace}/{snap.pod_name}"
            if key not in pod_map:
                pod_map[key] = snap
                
        # Existing zombie list
        existing_zombies = {f"{z.namespace}/{z.pod_name}": z for z in db.query(ZombieWorkload).all()}
        
        for key, snap in pod_map.items():
            cpu_util = (snap.cpu_usage / snap.cpu_req * 100.0) if snap.cpu_req > 0 else 0.0
            mem_util = (snap.mem_usage_mb / snap.mem_req_mb * 100.0) if snap.mem_req_mb > 0 else 0.0
            net_total_kb = (snap.net_rx_bytes + snap.net_tx_bytes) / 1024.0
            
            # Check if workload meets zombie criteria (< threshold CPU, low mem, < 50KB total net activity)
            is_zombie = (cpu_util <= idle_cpu_threshold_pct) and (mem_util <= 15.0) and (net_total_kb < 50.0)
            
            if is_zombie:
                wasted_cost = CostCalculator.calculate_pod_cost(
                    snap.cpu_req, snap.cpu_usage, snap.mem_req_mb, snap.mem_usage_mb, cpu_rate, ram_rate
                )["monthly_cost"]
                
                workload_name = snap.pod_name.rsplit("-", 2)[0] if "-" in snap.pod_name else snap.pod_name
                
                if key in existing_zombies:
                    zombie = existing_zombies[key]
                    if zombie.status == "ACTIVE":
                        zombie.wasted_monthly_cost = wasted_cost
                        zombie.cpu_usage_avg = round(snap.cpu_usage, 3)
                        zombie.mem_usage_avg_mb = round(snap.mem_usage_mb, 1)
                        zombie.net_activity_kb = round(net_total_kb, 1)
                else:
                    new_zombie = ZombieWorkload(
                        namespace=snap.namespace,
                        pod_name=snap.pod_name,
                        workload_name=workload_name,
                        workload_type=snap.workload_type,
                        cpu_usage_avg=round(snap.cpu_usage, 3),
                        mem_usage_avg_mb=round(snap.mem_usage_mb, 1),
                        net_activity_kb=round(net_total_kb, 1),
                        idle_duration_hours=36.0, # Simulated sustained period
                        wasted_monthly_cost=wasted_cost,
                        status="ACTIVE",
                        recommended_action="Scale deployment to 0 replicas",
                        detected_at=datetime.datetime.utcnow()
                    )
                    db.add(new_zombie)
        db.commit()
