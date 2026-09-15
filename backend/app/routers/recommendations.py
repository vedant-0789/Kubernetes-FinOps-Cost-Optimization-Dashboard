from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Recommendation, ActionLog, SystemSetting
from app.db.schemas import RecommendationSchema, ActionLogSchema
from app.engine.k8s_client import K8sClient
from typing import List
import datetime

router = APIRouter(prefix="/api/recommendations", tags=["Right-Sizing Recommendations"])

@router.get("", response_model=List[RecommendationSchema])
def get_recommendations(db: Session = Depends(get_db)):
    recs = db.query(Recommendation).order_by(Recommendation.monthly_savings.desc()).all()
    return recs

@router.post("/{id}/apply", response_model=ActionLogSchema)
def apply_recommendation(id: int, db: Session = Depends(get_db)):
    rec = db.query(Recommendation).filter(Recommendation.id == id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
        
    if rec.status == "APPLIED":
        raise HTTPException(status_code=400, detail="Recommendation already applied.")
        
    mock_setting = db.query(SystemSetting).filter(SystemSetting.key == "mock_mode").first()
    is_mock = (mock_setting.value.lower() == "true") if mock_setting else True
    
    k8s = K8sClient(mock_mode=is_mock)
    res = k8s.patch_resource_requests(
        namespace=rec.namespace,
        workload_name=rec.workload_name,
        new_cpu_req=rec.recommended_cpu_req,
        new_mem_req_mb=rec.recommended_mem_req_mb,
        db=db
    )
    
    if not res["success"]:
        raise HTTPException(status_code=500, detail=res["message"])
        
    rec.status = "APPLIED"
    
    action = ActionLog(
        action_type="RIGHT_SIZE",
        target_resource=f"{rec.workload_type} / {rec.workload_name}",
        namespace=rec.namespace,
        pod_name=rec.pod_name,
        monthly_savings=rec.monthly_savings,
        status="SUCCESS",
        applied_by="MANUAL",
        timestamp=datetime.datetime.utcnow(),
        details=f"Right-sized CPU from {rec.current_cpu_req} to {rec.recommended_cpu_req} vCPU, Memory from {rec.current_mem_req_mb}MB to {rec.recommended_mem_req_mb}MB. Realized ${rec.monthly_savings:.2f}/mo savings."
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    
    return action

@router.post("/{id}/dismiss")
def dismiss_recommendation(id: int, db: Session = Depends(get_db)):
    rec = db.query(Recommendation).filter(Recommendation.id == id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    rec.status = "DISMISSED"
    db.commit()
    return {"message": "Recommendation dismissed"}
