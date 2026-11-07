import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ActionLog, SystemSetting, ZombieWorkload
from app.db.schemas import ActionLogSchema, ZombieWorkloadSchema
from app.engine.k8s_client import K8sClient

router = APIRouter(prefix="/zombies", tags=["Zombie Workloads"])

@router.get("", response_model=list[ZombieWorkloadSchema])
def get_zombie_workloads(db: Session = Depends(get_db)):
    zombies = db.query(ZombieWorkload).order_by(ZombieWorkload.wasted_monthly_cost.desc()).all()
    return zombies

@router.post("/{id}/remediate", response_model=ActionLogSchema)
def remediate_zombie_workload(id: int, db: Session = Depends(get_db)):
    zombie = db.query(ZombieWorkload).filter(ZombieWorkload.id == id).first()
    if not zombie:
        raise HTTPException(status_code=404, detail="Zombie workload not found.")

    if zombie.status == "REMEDIATED":
        raise HTTPException(status_code=400, detail="Workload has already been remediated.")

    # Check mock mode setting
    mock_setting = db.query(SystemSetting).filter(SystemSetting.key == "mock_mode").first()
    is_mock = (mock_setting.value.lower() == "true") if mock_setting else True

    k8s = K8sClient(mock_mode=is_mock)
    res = k8s.scale_deployment(zombie.namespace, zombie.workload_name, replicas=0, db=db)

    if not res["success"]:
        raise HTTPException(status_code=500, detail=res["message"])

    # Update zombie status
    zombie.status = "REMEDIATED"

    # Log audit history
    action = ActionLog(
        action_type="SCALE_DOWN",
        target_resource=f"{zombie.workload_type} / {zombie.workload_name}",
        namespace=zombie.namespace,
        pod_name=zombie.pod_name,
        monthly_savings=zombie.wasted_monthly_cost,
        status="SUCCESS",
        applied_by="MANUAL",
        timestamp=datetime.datetime.utcnow(),
        details=f"Eliminated idle zombie workload. {res['message']} Realized ${zombie.wasted_monthly_cost:.2f}/mo savings."
    )
    db.add(action)
    db.commit()
    db.refresh(action)

    return action
