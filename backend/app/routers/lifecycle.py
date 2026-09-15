from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import MetricsSnapshot, ZombieWorkload, Recommendation, ActionLog
from app.engine.mock_generator import NAMESPACES

router = APIRouter(prefix="/api/lifecycle", tags=["FinOps Lifecycle"])

FINOPS_STAGES = [
    {"id": "Observe", "title": "1. Observe", "desc": "Ingest real-time cAdvisor & Prometheus metrics across all nodes/pods."},
    {"id": "Measure", "title": "2. Measure", "desc": "Compute baseline resource usage (CPU vCPU-hrs, Memory GB-hrs, Network IO)."},
    {"id": "Attribute", "title": "3. Attribute", "desc": "OpenCost allocation per namespace, service, and owner tag."},
    {"id": "Detect", "title": "4. Detect", "desc": "Continuous background scanning for zombie/idle workloads (<5% usage)."},
    {"id": "Recommend", "title": "5. Recommend", "desc": "Calculate right-sizing recommendations based on p95 usage + safety buffer."},
    {"id": "Optimize", "title": "6. Optimize", "desc": "Remediate waste via scaling deployments down or patching CPU/RAM requests."},
    {"id": "Verify", "title": "7. Verify", "desc": "Track realized savings in audit logs and verify cost curve reduction."}
]

@router.get("")
def get_lifecycle_summary(db: Session = Depends(get_db)):
    latest_snaps = db.query(MetricsSnapshot).order_by(MetricsSnapshot.timestamp.desc()).all()
    
    pod_map = {}
    for s in latest_snaps:
        k = f"{s.namespace}/{s.pod_name}"
        if k not in pod_map:
            pod_map[k] = s
            
    stage_ns_map = {ns["name"]: ns["stage"] for ns in NAMESPACES}
    
    active_zombies = db.query(ZombieWorkload).filter(ZombieWorkload.status == "ACTIVE").count()
    active_recs = db.query(Recommendation).filter(Recommendation.status == "PENDING").count()
    applied_actions = db.query(ActionLog).filter(ActionLog.status == "SUCCESS").count()
    
    stage_data = []
    for stage in FINOPS_STAGES:
        s_id = stage["id"]
        
        # Matching namespaces
        ns_list = [ns["name"] for ns in NAMESPACES if ns["stage"] == s_id]
        
        # Pods in these namespaces
        matching_pods = [p for p in pod_map.values() if p.namespace in ns_list]
        cost_sum = sum(p.monthly_cost for p in matching_pods)
        
        badge_text = f"{len(ns_list)} Namespaces"
        if s_id == "Detect":
            badge_text = f"{active_zombies} Zombies Flagged"
        elif s_id == "Recommend":
            badge_text = f"{active_recs} Active Recs"
        elif s_id == "Optimize" or s_id == "Verify":
            badge_text = f"{applied_actions} Remediations Executed"
            
        stage_data.append({
            "stage_id": s_id,
            "title": stage["title"],
            "description": stage["desc"],
            "namespaces": ns_list,
            "pod_count": len(matching_pods),
            "monthly_cost": round(cost_sum, 2),
            "badge": badge_text
        })
        
    return {
        "stages": stage_data,
        "total_active_workloads": len(pod_map)
    }
