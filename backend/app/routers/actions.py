
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ActionLog
from app.db.schemas import ActionLogSchema

router = APIRouter(prefix="/actions", tags=["Action Audit History"])

@router.get("/history", response_model=list[ActionLogSchema])
def get_action_history(db: Session = Depends(get_db)):
    actions = db.query(ActionLog).order_by(ActionLog.timestamp.desc()).all()
    return actions
