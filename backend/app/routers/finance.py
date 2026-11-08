import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_admin_role, require_operator, require_viewer
from app.db.database import get_db
from app.db.platform_models import Budget, CostAnomaly, Notification, NotificationChannel, utcnow
from app.routers.clusters import get_cluster_or_404
from app.services import audit, notify
from app.services.finance import budget_status, forecast_report, parse_scope, run_finance
from app.services.reports import showback, showback_csv, showback_pdf

router = APIRouter(tags=["Forecasts, budgets & reports"])


# --- forecasts & anomalies ---------------------------------------------------------


@router.get("/clusters/{cluster_id}/forecast",
            summary="Daily cost history, Holt-Winters forecast with 80/95 % intervals, month-end projection")
def get_forecast(cluster_id: str, scope: str = Query("cluster", description="cluster | namespace:<ns> | "
                                                                            "label:<key>=<value>"),
                 days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db),
                 _: Principal = Depends(require_viewer)):
    parse_scope(scope)
    return forecast_report(db, get_cluster_or_404(cluster_id, db), scope, days)


class AnomalyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scope: str
    name: str
    day: datetime.datetime
    actual: float
    expected: float
    delta: float
    score: float
    status: str
    acknowledged_by: str | None
    detected_at: datetime.datetime


@router.get("/clusters/{cluster_id}/anomalies", response_model=list[AnomalyOut])
def list_anomalies(cluster_id: str, status: Literal["open", "acknowledged", "all"] = "open",
                   db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    get_cluster_or_404(cluster_id, db)
    q = db.query(CostAnomaly).filter(CostAnomaly.cluster_id == cluster_id)
    if status != "all":
        q = q.filter(CostAnomaly.status == status)
    return q.order_by(CostAnomaly.day.desc(), CostAnomaly.delta.desc()).all()


@router.post("/clusters/{cluster_id}/anomalies/{anomaly_id}/ack", response_model=AnomalyOut)
def ack_anomaly(cluster_id: str, anomaly_id: int, db: Session = Depends(get_db),
                p: Principal = Depends(require_operator)):
    a = db.get(CostAnomaly, anomaly_id)
    if a is None or a.cluster_id != cluster_id:
        raise HTTPException(404, "Anomaly not found")
    a.status, a.acknowledged_by = "acknowledged", p.subject
    audit.record(db, p.subject, "anomaly.ack", cluster_id=cluster_id, target=f"{a.scope}/{a.name}",
                 details={"id": a.id, "day": a.day.date().isoformat()})
    db.commit()
    db.refresh(a)
    return a


@router.post("/finance/run", summary="Run anomaly detection and budget evaluation now")
def run_now(db: Session = Depends(get_db), p: Principal = Depends(require_operator)):
    result = run_finance(db)
    audit.record(db, p.subject, "finance.run", details=result, commit=True)
    return result


# --- budgets -------------------------------------------------------------------------


class BudgetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: Literal["cluster", "namespace", "label"] = "cluster"
    scope_key: str | None = Field(default=None, max_length=100)
    scope_value: str | None = Field(default=None, max_length=253)
    monthly_amount: float = Field(gt=0, le=1e9)
    thresholds: list[int] = Field(default_factory=lambda: [50, 80, 100])
    enabled: bool = True

    @model_validator(mode="after")
    def _check(self):
        if self.scope == "namespace" and not self.scope_value:
            raise ValueError("namespace budgets need scope_value")
        if self.scope == "label" and not (self.scope_key and self.scope_value):
            raise ValueError("label budgets need scope_key and scope_value")
        if any(t <= 0 or t > 500 for t in self.thresholds):
            raise ValueError("thresholds are percentages between 1 and 500")
        self.thresholds = sorted(set(self.thresholds))
        return self


class BudgetOut(BudgetIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cluster_id: str
    created_by: str
    created_at: datetime.datetime


def _budget(db: Session, cluster_id: str, budget_id: int) -> Budget:
    b = db.get(Budget, budget_id)
    if b is None or b.cluster_id != cluster_id:
        raise HTTPException(404, "Budget not found")
    return b


@router.post("/clusters/{cluster_id}/budgets", response_model=BudgetOut, status_code=201)
def create_budget(cluster_id: str, body: BudgetIn, db: Session = Depends(get_db),
                  p: Principal = Depends(require_operator)):
    get_cluster_or_404(cluster_id, db)
    b = Budget(cluster_id=cluster_id, created_by=p.subject, **body.model_dump())
    db.add(b)
    db.flush()
    audit.record(db, p.subject, "budget.create", cluster_id=cluster_id, target=b.name, details=body.model_dump())
    db.commit()
    db.refresh(b)
    return b


@router.get("/clusters/{cluster_id}/budgets", response_model=list[BudgetOut])
def list_budgets(cluster_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    get_cluster_or_404(cluster_id, db)
    return db.query(Budget).filter(Budget.cluster_id == cluster_id).order_by(Budget.name).all()


@router.get("/clusters/{cluster_id}/budgets/status", summary="Every budget with spend, projection and state")
def budgets_status(cluster_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    get_cluster_or_404(cluster_id, db)
    return [budget_status(db, b) for b in db.query(Budget).filter(Budget.cluster_id == cluster_id,
                                                                  Budget.enabled.is_(True))]


@router.get("/clusters/{cluster_id}/budgets/{budget_id}")
def get_budget(cluster_id: str, budget_id: int, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    b = _budget(db, cluster_id, budget_id)
    return {"budget": BudgetOut.model_validate(b), "status": budget_status(db, b)}


@router.put("/clusters/{cluster_id}/budgets/{budget_id}", response_model=BudgetOut)
def update_budget(cluster_id: str, budget_id: int, body: BudgetIn, db: Session = Depends(get_db),
                  p: Principal = Depends(require_operator)):
    b = _budget(db, cluster_id, budget_id)
    for k, v in body.model_dump().items():
        setattr(b, k, v)
    audit.record(db, p.subject, "budget.update", cluster_id=cluster_id, target=b.name, details=body.model_dump())
    db.commit()
    db.refresh(b)
    return b


@router.delete("/clusters/{cluster_id}/budgets/{budget_id}", status_code=204)
def delete_budget(cluster_id: str, budget_id: int, db: Session = Depends(get_db),
                  p: Principal = Depends(require_operator)):
    b = _budget(db, cluster_id, budget_id)
    audit.record(db, p.subject, "budget.delete", cluster_id=cluster_id, target=b.name)
    db.delete(b)
    db.commit()


# --- notification channels ------------------------------------------------------------


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["slack", "webhook", "email"]
    url: str | None = Field(default=None, max_length=2000, pattern=r"^https?://")
    to: list[str] = Field(default_factory=list, max_length=50)
    events: list[Literal["budget", "anomaly", "remediation"]] = Field(
        default_factory=lambda: ["budget", "anomaly", "remediation"])
    cluster_id: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _check(self):
        if self.type in ("slack", "webhook") and not self.url:
            raise ValueError(f"{self.type} channels need url")
        if self.type == "email" and not self.to:
            raise ValueError("email channels need at least one recipient in 'to'")
        return self


def _channel_out(c: NotificationChannel) -> dict:
    return {"id": c.id, "name": c.name, "type": c.type, "config": notify.masked_config(c), "events": c.events,
            "cluster_id": c.cluster_id, "enabled": c.enabled, "created_by": c.created_by, "created_at": c.created_at}


@router.post("/notification-channels", status_code=201)
def create_channel(body: ChannelIn, db: Session = Depends(get_db), p: Principal = Depends(require_admin_role)):
    if db.query(NotificationChannel).filter(NotificationChannel.name == body.name).first():
        raise HTTPException(409, "A channel with this name exists")
    if body.cluster_id:
        get_cluster_or_404(body.cluster_id, db)
    config = {"url": body.url} if body.type != "email" else {"to": body.to}
    c = NotificationChannel(name=body.name, type=body.type, config=config, events=body.events,
                            cluster_id=body.cluster_id, enabled=body.enabled, created_by=p.subject)
    db.add(c)
    db.flush()
    audit.record(db, p.subject, "channel.create", target=c.name, details={"type": c.type, "events": c.events})
    db.commit()
    db.refresh(c)
    return _channel_out(c)


@router.get("/notification-channels")
def list_channels(db: Session = Depends(get_db), _: Principal = Depends(require_admin_role)):
    return [_channel_out(c) for c in db.query(NotificationChannel).order_by(NotificationChannel.name)]


@router.delete("/notification-channels/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: Session = Depends(get_db), p: Principal = Depends(require_admin_role)):
    c = db.get(NotificationChannel, channel_id)
    if c is None:
        raise HTTPException(404, "Channel not found")
    audit.record(db, p.subject, "channel.delete", target=c.name)
    db.delete(c)
    db.commit()


@router.post("/notification-channels/{channel_id}/test", summary="Send a test message and report the outcome")
def test_channel(channel_id: int, db: Session = Depends(get_db), _: Principal = Depends(require_admin_role)):
    c = db.get(NotificationChannel, channel_id)
    if c is None:
        raise HTTPException(404, "Channel not found")
    n = notify.deliver(db, c, "test", "KubeFinOps test notification",
                       "If you can read this, alerts from KubeFinOps will reach this channel.")
    db.commit()
    return {"status": n.status, "error": n.error}


@router.get("/notifications", summary="Delivery log")
def list_notifications(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db),
                       _: Principal = Depends(require_admin_role)):
    rows = db.query(Notification).order_by(Notification.id.desc()).limit(limit).all()
    return [{"id": n.id, "channel_id": n.channel_id, "event_type": n.event_type, "cluster_id": n.cluster_id,
             "subject": n.subject, "status": n.status, "error": n.error, "created_at": n.created_at} for n in rows]


# --- reports ---------------------------------------------------------------------------


def _report(db, cluster_id, month, aggregate, shared, include_idle):
    cluster = get_cluster_or_404(cluster_id, db)
    return cluster, showback(db, cluster, month, aggregate, shared, include_idle)


@router.get("/clusters/{cluster_id}/reports/showback", summary="Monthly showback/chargeback as JSON")
def report_json(cluster_id: str, month: str | None = Query(None, description="YYYY-MM (default: this month)"),
                aggregate: str = "label:team", shared: Literal["separate", "distribute"] = "distribute",
                include_idle: bool = True, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    return _report(db, cluster_id, month, aggregate, shared, include_idle)[1]


@router.get("/clusters/{cluster_id}/reports/showback.csv")
def report_csv(cluster_id: str, month: str | None = None, aggregate: str = "label:team",
               shared: Literal["separate", "distribute"] = "distribute", include_idle: bool = True,
               db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    _, rep = _report(db, cluster_id, month, aggregate, shared, include_idle)
    name = f"showback-{rep['cluster']}-{rep['month']}.csv"
    return Response(showback_csv(rep), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/clusters/{cluster_id}/reports/showback.pdf")
def report_pdf(cluster_id: str, month: str | None = None, aggregate: str = "label:team",
               shared: Literal["separate", "distribute"] = "distribute", include_idle: bool = True,
               db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    cluster, rep = _report(db, cluster_id, month, aggregate, shared, include_idle)
    name = f"showback-{rep['cluster']}-{rep['month']}.pdf"
    return Response(showback_pdf(db, cluster, rep), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


__all__ = ["router", "utcnow"]
