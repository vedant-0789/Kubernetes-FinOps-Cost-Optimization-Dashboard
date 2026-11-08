from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_viewer
from app.db.database import get_db
from app.routers.clusters import get_cluster_or_404
from app.schemas.platform import AllocationReport, ClusterSummary, TimeseriesPoint
from app.services.allocation_query import allocation_report, cluster_summary, cost_timeseries

router = APIRouter(prefix="/clusters/{cluster_id}", tags=["Cost allocation"], dependencies=[Depends(require_viewer)])


@router.get("/summary", response_model=ClusterSummary)
def get_summary(cluster_id: str, db: Session = Depends(get_db)):
    return cluster_summary(db, get_cluster_or_404(cluster_id, db))


@router.get("/allocation", response_model=AllocationReport,
            summary="Cost allocation over a window, grouped by namespace/workload/node/pod/label:<key>")
def get_allocation(
    cluster_id: str,
    window: str = Query("7d", description="e.g. 24h, 7d, 30d"),
    aggregate: str = Query("namespace", description="cluster | namespace | workload | node | pod | label:<key>"),
    shared: Literal["separate", "distribute"] = Query(
        "separate", description="Show shared namespaces separately or spread them over tenants by cost"),
    include_idle: bool = True,
    db: Session = Depends(get_db),
):
    return allocation_report(db, get_cluster_or_404(cluster_id, db), window, aggregate, shared, include_idle)


@router.get("/cost-timeseries", response_model=list[TimeseriesPoint])
def get_timeseries(
    cluster_id: str,
    window: str = Query("30d"),
    step: Literal["1h", "1d"] = Query("1d"),
    top: int = Query(6, ge=1, le=20, description="Top-N namespaces; the rest are grouped as 'other'"),
    db: Session = Depends(get_db),
):
    return cost_timeseries(db, get_cluster_or_404(cluster_id, db), window, step, top)
