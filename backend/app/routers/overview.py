import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ActionLog, MetricsSnapshot, Recommendation, SystemSetting, ZombieWorkload
from app.db.schemas import CostTrendPointSchema, OverviewSummarySchema

router = APIRouter(prefix="", tags=["Overview"])

@router.get("/overview", response_model=OverviewSummarySchema)
def get_overview_summary(db: Session = Depends(get_db)):
    # Fetch latest snapshot for active pods
    latest_snaps = db.query(MetricsSnapshot).order_by(MetricsSnapshot.timestamp.desc()).all()

    # Deduplicate to latest timestamp per pod
    pod_map = {}
    for snap in latest_snaps:
        key = f"{snap.namespace}/{snap.pod_name}"
        if key not in pod_map:
            pod_map[key] = snap

    active_pods = list(pod_map.values())

    total_cost = sum(p.monthly_cost for p in active_pods)

    # Active zombie waste & right-sizing potential savings
    active_zombies = db.query(ZombieWorkload).filter(ZombieWorkload.status == "ACTIVE").all()
    zombie_waste = sum(z.wasted_monthly_cost for z in active_zombies)

    active_recs = db.query(Recommendation).filter(Recommendation.status == "PENDING").all()
    rec_savings = sum(r.monthly_savings for r in active_recs)

    total_potential_savings = round(zombie_waste + rec_savings, 2)

    # Realized savings from action logs
    realized_actions = db.query(ActionLog).filter(ActionLog.status == "SUCCESS").all()
    realized_savings = round(sum(a.monthly_savings for a in realized_actions), 2)

    namespaces = set(p.namespace for p in active_pods)

    eff_sum = sum(p.efficiency_pct for p in active_pods)
    overall_eff = round(eff_sum / len(active_pods), 1) if active_pods else 0.0

    # Mock mode setting
    mock_setting = db.query(SystemSetting).filter(SystemSetting.key == "mock_mode").first()
    is_mock = (mock_setting.value.lower() == "true") if mock_setting else True

    return OverviewSummarySchema(
        total_monthly_cost=round(total_cost, 2),
        total_potential_savings=total_potential_savings,
        realized_monthly_savings=realized_savings,
        total_namespaces=len(namespaces),
        total_pods=len(active_pods),
        total_nodes=3, # Standard cluster node representation
        zombie_count=len(active_zombies),
        active_recommendations_count=len(active_recs),
        overall_efficiency_pct=overall_eff,
        mock_mode=is_mock,
        last_updated=datetime.datetime.utcnow()
    )

@router.get("/cost-trend", response_model=list[CostTrendPointSchema])
def get_cost_trend(range: str = Query("30d", pattern="^(7d|30d)$"), db: Session = Depends(get_db)):
    days = 7 if range == "7d" else 30
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    snapshots = db.query(MetricsSnapshot).filter(MetricsSnapshot.timestamp >= cutoff).all()

    # Group by YYYY-MM-DD
    daily_groups = {}
    for snap in snapshots:
        date_str = snap.timestamp.strftime("%Y-%m-%d")
        if date_str not in daily_groups:
            daily_groups[date_str] = []
        daily_groups[date_str].append(snap)

    trend_points = []
    sorted_dates = sorted(daily_groups.keys())

    for d in sorted_dates:
        snaps = daily_groups[d]
        # Sum unique pod cost per day
        pod_daily_cost = {}
        for s in snaps:
            key = f"{s.namespace}/{s.pod_name}"
            if key not in pod_daily_cost:
                pod_daily_cost[key] = s.monthly_cost

        day_total = sum(pod_daily_cost.values())
        # Potential optimized cost is actual cost minus 25% waste margin
        optimized = round(day_total * 0.72, 2)

        trend_points.append(CostTrendPointSchema(
            date=d,
            actual_cost=round(day_total, 2),
            potential_optimized_cost=optimized
        ))

    return trend_points
