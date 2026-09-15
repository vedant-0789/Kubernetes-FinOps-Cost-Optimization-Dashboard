from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import SystemSetting
from app.db.schemas import SettingsUpdateSchema

router = APIRouter(prefix="/api/settings", tags=["Settings"])

@router.get("")
def get_settings(db: Session = Depends(get_db)):
    settings_rows = db.query(SystemSetting).all()
    s_map = {s.key: s.value for s in settings_rows}
    
    return {
        "cpu_hourly_rate": float(s_map.get("cpu_hourly_rate", 0.048)),
        "ram_hourly_rate": float(s_map.get("ram_hourly_rate", 0.006)),
        "idle_cpu_threshold_pct": float(s_map.get("idle_cpu_threshold_pct", 5.0)),
        "evaluation_window_hours": int(s_map.get("evaluation_window_hours", 24)),
        "auto_remediation_enabled": s_map.get("auto_remediation_enabled", "false").lower() == "true",
        "mock_mode": s_map.get("mock_mode", "true").lower() == "true",
    }

@router.post("")
def update_settings(payload: SettingsUpdateSchema, db: Session = Depends(get_db)):
    updates = {
        "cpu_hourly_rate": str(payload.cpu_hourly_rate),
        "ram_hourly_rate": str(payload.ram_hourly_rate),
        "idle_cpu_threshold_pct": str(payload.idle_cpu_threshold_pct),
        "evaluation_window_hours": str(payload.evaluation_window_hours),
        "auto_remediation_enabled": "true" if payload.auto_remediation_enabled else "false",
        "mock_mode": "true" if payload.mock_mode else "false",
    }
    
    for key, val in updates.items():
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row:
            row.value = val
        else:
            db.add(SystemSetting(key=key, value=val))
            
    db.commit()
    
    # Recalculate cost snapshots with new pricing
    from app.engine.cost_calculator import CostCalculator
    from app.db.models import MetricsSnapshot
    snaps = db.query(MetricsSnapshot).all()
    for snap in snaps:
        c_info = CostCalculator.calculate_pod_cost(
            snap.cpu_req, snap.cpu_usage, snap.mem_req_mb, snap.mem_usage_mb,
            payload.cpu_hourly_rate, payload.ram_hourly_rate
        )
        snap.hourly_cost = c_info["hourly_cost"]
        snap.monthly_cost = c_info["monthly_cost"]
        snap.efficiency_pct = c_info["efficiency_pct"]
    db.commit()
    
    return {"message": "Settings updated successfully", "settings": get_settings(db)}
