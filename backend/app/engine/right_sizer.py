from sqlalchemy.orm import Session
from app.db.models import MetricsSnapshot, Recommendation
from app.engine.cost_calculator import CostCalculator
import datetime

class RightSizer:
    """
    Right-Sizing Recommendation Engine.
    For over-provisioned (non-zombie) workloads, computes optimal CPU/Memory requests
    using p95 peak usage + safety buffer (e.g. +20%).
    """
    
    @staticmethod
    def evaluate(db: Session, safety_buffer_pct: float = 20.0, cpu_rate: float = 0.048, ram_rate: float = 0.006):
        latest_snapshots = db.query(MetricsSnapshot).order_by(MetricsSnapshot.timestamp.desc()).all()
        
        # Unique pods
        pod_map = {}
        for snap in latest_snapshots:
            key = f"{snap.namespace}/{snap.pod_name}"
            if key not in pod_map:
                pod_map[key] = snap
                
        existing_recs = {f"{r.namespace}/{r.pod_name}": r for r in db.query(Recommendation).all()}
        
        buffer_factor = 1.0 + (safety_buffer_pct / 100.0)
        
        for key, snap in pod_map.items():
            # Calculate recommended requests (p95 peak simulated + safety buffer)
            # Ensure minimum floor (0.05 CPU, 64MB RAM)
            rec_cpu = max(0.05, round(snap.cpu_usage * buffer_factor, 2))
            rec_mem_mb = max(64.0, round(snap.mem_usage_mb * buffer_factor, 0))
            
            # Check if current request exceeds recommendation significantly (> 20% over-provisioned)
            cpu_over = snap.cpu_req > (rec_cpu * 1.2)
            mem_over = snap.mem_req_mb > (rec_mem_mb * 1.2)
            
            if cpu_over or mem_over:
                current_cost_info = CostCalculator.calculate_pod_cost(
                    snap.cpu_req, snap.cpu_usage, snap.mem_req_mb, snap.mem_usage_mb, cpu_rate, ram_rate
                )
                rec_cost_info = CostCalculator.calculate_pod_cost(
                    rec_cpu, snap.cpu_usage, rec_mem_mb, snap.mem_usage_mb, cpu_rate, ram_rate
                )
                
                curr_monthly = current_cost_info["monthly_cost"]
                rec_monthly = rec_cost_info["monthly_cost"]
                monthly_savings = round(max(0.0, curr_monthly - rec_monthly), 2)
                
                # Only log recommendation if savings >= $5/mo
                if monthly_savings >= 5.0:
                    workload_name = snap.pod_name.rsplit("-", 2)[0] if "-" in snap.pod_name else snap.pod_name
                    
                    if key in existing_recs:
                        rec = existing_recs[key]
                        if rec.status == "PENDING":
                            rec.recommended_cpu_req = rec_cpu
                            rec.recommended_mem_req_mb = rec_mem_mb
                            rec.current_monthly_cost = curr_monthly
                            rec.recommended_monthly_cost = rec_monthly
                            rec.monthly_savings = monthly_savings
                    else:
                        new_rec = Recommendation(
                            namespace=snap.namespace,
                            pod_name=snap.pod_name,
                            workload_name=workload_name,
                            workload_type=snap.workload_type,
                            current_cpu_req=snap.cpu_req,
                            current_mem_req_mb=snap.mem_req_mb,
                            recommended_cpu_req=rec_cpu,
                            recommended_mem_req_mb=rec_mem_mb,
                            current_monthly_cost=curr_monthly,
                            recommended_monthly_cost=rec_monthly,
                            monthly_savings=monthly_savings,
                            status="PENDING",
                            created_at=datetime.datetime.utcnow()
                        )
                        db.add(new_rec)
        db.commit()
