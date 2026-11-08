import datetime
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_admin
from app.db.database import get_db
from app.db.platform_models import RightsizingRecommendation, UsageSample, WasteFinding, utcnow
from app.engines import rightsizing as rs
from app.routers.clusters import get_cluster_or_404
from app.services.analysis import _epoch, analyze_cluster, savings_summary

router = APIRouter(prefix="/clusters/{cluster_id}", tags=["Right-sizing & waste"],
                   dependencies=[Depends(require_admin)])


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    namespace: str
    workload_kind: str
    workload_name: str
    container: str
    strategy: str
    action: str
    status: str
    replicas: float
    current_cpu_request: float
    current_mem_request: float
    current_cpu_limit: float | None
    current_mem_limit: float | None
    recommended_cpu_request: float
    recommended_mem_request: float
    recommended_cpu_limit: float | None
    recommended_mem_limit: float | None
    monthly_savings: float
    confidence: float
    confidence_label: str
    risk: str
    reasons: list[str]
    evidence: dict
    dismissed_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class UsageBucket(BaseModel):
    start: datetime.datetime
    cpu_p50: float
    cpu_max: float
    mem_p50: float
    mem_max: float
    throttled_seconds: float
    oom_kills: int


class RecommendationDetail(RecommendationOut):
    usage: list[UsageBucket]


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    namespace: str
    name: str
    status: str
    monthly_savings: float
    risk: str
    action: str
    evidence: dict
    dismissed_reason: str | None
    first_detected: datetime.datetime
    last_detected: datetime.datetime
    resolved_at: datetime.datetime | None


class DismissIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


Status = Literal["open", "applied", "dismissed", "resolved", "all"]


@router.post("/analyze", summary="Run right-sizing and waste analysis now")
def analyze_now(cluster_id: str, db: Session = Depends(get_db)):
    return analyze_cluster(db, get_cluster_or_404(cluster_id, db))


@router.get("/savings", summary="Non-overlapping potential monthly savings by category")
def get_savings(cluster_id: str, db: Session = Depends(get_db)):
    return savings_summary(db, get_cluster_or_404(cluster_id, db))


@router.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(cluster_id: str, status: Status = "open", namespace: str | None = None,
                         action: Literal["downsize", "upsize"] | None = None, db: Session = Depends(get_db)):
    get_cluster_or_404(cluster_id, db)
    R = RightsizingRecommendation
    q = db.query(R).filter(R.cluster_id == cluster_id, R.strategy == settings.rightsizing_strategy)
    if status != "all":
        q = q.filter(R.status == status)
    if namespace:
        q = q.filter(R.namespace == namespace)
    if action:
        q = q.filter(R.action == action)
    # Reliability fixes (upsize) first, then biggest savings.
    return sorted(q.all(), key=lambda r: (r.action != "upsize", -r.monthly_savings))


def _get_rec(db: Session, cluster_id: str, rec_id: int) -> RightsizingRecommendation:
    rec = db.get(RightsizingRecommendation, rec_id)
    if rec is None or rec.cluster_id != cluster_id:
        raise HTTPException(404, "Recommendation not found")
    return rec


def _usage_buckets(db: Session, cluster_id: str, ns: str, kind: str, name: str, container: str,
                   days: int = 7) -> list[UsageBucket]:
    S = UsageSample
    since = utcnow() - datetime.timedelta(days=days)
    rows = db.query(S.ts, S.cpu_usage_cores, S.cpu_usage_max_cores, S.mem_usage_bytes, S.mem_usage_max_bytes,
                    S.cpu_throttled_seconds, S.oom_kills).filter(
        S.cluster_id == cluster_id, S.namespace == ns, S.workload_kind == kind, S.workload_name == name,
        S.container == container, S.ts >= since).all()
    hours: dict = defaultdict(list)
    for r in rows:
        hours[r.ts.replace(minute=0, second=0, microsecond=0)].append(r)
    out = []
    for h in sorted(hours):
        rs_ = hours[h]
        cpu = sorted(r.cpu_usage_cores for r in rs_)
        mem = sorted(r.mem_usage_bytes for r in rs_)
        out.append(UsageBucket(
            start=h, cpu_p50=round(cpu[len(cpu) // 2], 5),
            cpu_max=round(max((r.cpu_usage_max_cores or r.cpu_usage_cores) for r in rs_), 5),
            mem_p50=mem[len(mem) // 2], mem_max=max((r.mem_usage_max_bytes or r.mem_usage_bytes) for r in rs_),
            throttled_seconds=round(sum(r.cpu_throttled_seconds for r in rs_), 1),
            oom_kills=sum(r.oom_kills for r in rs_)))
    return out


@router.get("/recommendations/{rec_id}", response_model=RecommendationDetail,
            summary="Recommendation with hourly usage (for the request-vs-usage chart)")
def get_recommendation(cluster_id: str, rec_id: int, days: int = Query(7, ge=1, le=35),
                       db: Session = Depends(get_db)):
    rec = _get_rec(db, cluster_id, rec_id)
    usage = _usage_buckets(db, cluster_id, rec.namespace, rec.workload_kind, rec.workload_name, rec.container, days)
    return RecommendationDetail(**RecommendationOut.model_validate(rec).model_dump(), usage=usage)


@router.post("/recommendations/{rec_id}/dismiss", response_model=RecommendationOut)
def dismiss_recommendation(cluster_id: str, rec_id: int, body: DismissIn, db: Session = Depends(get_db)):
    rec = _get_rec(db, cluster_id, rec_id)
    rec.status, rec.dismissed_reason, rec.updated_at = "dismissed", body.reason, utcnow()
    db.commit()
    db.refresh(rec)
    return rec


@router.get("/recommendations/{rec_id}/compare",
            summary="All strategies side by side on the same history (SLO-aware vs VPA vs p95+20%)")
def compare_strategies(cluster_id: str, rec_id: int, db: Session = Depends(get_db)):
    rec = _get_rec(db, cluster_id, rec_id)
    S = UsageSample
    since = utcnow() - datetime.timedelta(days=settings.analysis_window_days)
    rows = db.query(S).filter(S.cluster_id == cluster_id, S.namespace == rec.namespace,
                              S.workload_kind == rec.workload_kind, S.workload_name == rec.workload_name,
                              S.container == rec.container, S.ts >= since).all()
    points = [rs.UsagePoint(_epoch(r.ts), r.cpu_usage_cores, r.mem_usage_bytes, r.cpu_usage_max_cores,
                            r.mem_usage_max_bytes, r.cpu_throttled_seconds, r.duration_seconds, r.oom_kills)
              for r in rows]
    spec = rs.ContainerSpec(rec.current_cpu_request, rec.current_mem_request, rec.current_cpu_limit,
                            rec.current_mem_limit, rec.replicas)
    out = {}
    peaks = [p.cpu_peak if p.cpu_peak is not None else p.cpu_mean for p in points]
    for name in rs.STRATEGIES:
        r = rs.recommend(points, spec, name)
        exceed = sum(v > r.cpu_request for v in peaks) / len(peaks) if peaks else 0.0
        mem_peaks = [p.mem_peak or p.mem_mean for p in points]
        mem_exceed = sum(v > r.mem_request for v in mem_peaks) / len(mem_peaks) if mem_peaks else 0.0
        out[name] = {"action": r.action, "cpu_request": r.cpu_request, "mem_request": r.mem_request,
                     "risk": r.risk, "cpu_peak_exceedance": round(exceed, 4),
                     "mem_peak_exceedance": round(mem_exceed, 4)}
    return {"recommendation_id": rec.id, "samples": len(points), "strategies": out}


@router.get("/waste", response_model=list[FindingOut])
def list_waste(cluster_id: str, status: Status = "open", kind: str | None = None, db: Session = Depends(get_db)):
    get_cluster_or_404(cluster_id, db)
    q = db.query(WasteFinding).filter(WasteFinding.cluster_id == cluster_id)
    if status != "all":
        q = q.filter(WasteFinding.status == status)
    if kind:
        q = q.filter(WasteFinding.kind == kind)
    return q.order_by(WasteFinding.monthly_savings.desc()).all()


@router.post("/waste/{finding_id}/dismiss", response_model=FindingOut)
def dismiss_finding(cluster_id: str, finding_id: int, body: DismissIn, db: Session = Depends(get_db)):
    f = db.get(WasteFinding, finding_id)
    if f is None or f.cluster_id != cluster_id:
        raise HTTPException(404, "Finding not found")
    f.status, f.dismissed_reason = "dismissed", body.reason
    db.commit()
    db.refresh(f)
    return f
