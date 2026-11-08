import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_operator, require_viewer
from app.core.security import authenticate_agent
from app.db.database import get_db
from app.db.platform_models import Cluster, RemediationAction, RightsizingRecommendation, WasteFinding
from app.routers.clusters import get_cluster_or_404
from app.services import remediation as svc

router = APIRouter(tags=["Remediation"])


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cluster_id: str
    type: str
    status: str
    namespace: str
    workload_kind: str
    workload_name: str
    container: str | None
    patch: dict
    recommendation_id: int | None
    finding_id: int | None
    rollback_of: int | None
    expected_monthly_savings: float
    dry_run_diff: dict | None
    previous_spec: dict | None
    verification: dict | None
    error: str | None
    reason: str | None
    requested_by: str
    approved_by: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    applied_at: datetime.datetime | None
    verified_at: datetime.datetime | None


class ProposeIn(BaseModel):
    recommendation_id: int | None = None
    finding_id: int | None = None
    # manual
    namespace: str | None = Field(default=None, max_length=63)
    workload_kind: Literal["Deployment", "StatefulSet"] | None = None
    workload_name: str | None = Field(default=None, max_length=253)
    container: str | None = Field(default=None, max_length=253)
    cpu_request: float | None = Field(default=None, gt=0, le=512)
    mem_request: float | None = Field(default=None, gt=0, description="bytes")
    cpu_limit: float | None = Field(default=None, gt=0, le=512)
    mem_limit: float | None = Field(default=None, gt=0)
    replicas: int | None = Field(default=None, ge=0, le=1000)
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _one_source(self):
        manual = self.namespace is not None
        if sum([self.recommendation_id is not None, self.finding_id is not None, manual]) != 1:
            raise ValueError("give exactly one of recommendation_id, finding_id or a manual target (namespace, ...)")
        if manual and not (self.workload_kind and self.workload_name):
            raise ValueError("manual actions need namespace, workload_kind and workload_name")
        return self


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class AgentResultIn(BaseModel):
    phase: Literal["dry_run", "apply"]
    ok: bool
    diff: dict | None = None
    previous_spec: dict | None = None
    error: str | None = Field(default=None, max_length=2000)


def _action(db: Session, cluster_id: str, action_id: int) -> RemediationAction:
    a = db.get(RemediationAction, action_id)
    if a is None or a.cluster_id != cluster_id:
        raise HTTPException(404, "Action not found")
    return a


@router.post("/clusters/{cluster_id}/actions", response_model=ActionOut, status_code=201,
             summary="Propose a change (from a recommendation, an idle finding, or manual); starts with a dry-run")
def propose(cluster_id: str, body: ProposeIn, db: Session = Depends(get_db), p: Principal = Depends(require_operator)):
    cluster = get_cluster_or_404(cluster_id, db)
    if body.recommendation_id is not None:
        rec = db.get(RightsizingRecommendation, body.recommendation_id)
        if rec is None or rec.cluster_id != cluster_id:
            raise HTTPException(404, "Recommendation not found")
        return svc.propose_from_recommendation(db, cluster, rec, p)
    if body.finding_id is not None:
        f = db.get(WasteFinding, body.finding_id)
        if f is None or f.cluster_id != cluster_id:
            raise HTTPException(404, "Finding not found")
        return svc.propose_from_finding(db, cluster, f, p)
    return svc.propose_manual(db, cluster, p, namespace=body.namespace, workload_kind=body.workload_kind,
                              workload_name=body.workload_name, container=body.container,
                              cpu_request=body.cpu_request, mem_request=body.mem_request, cpu_limit=body.cpu_limit,
                              mem_limit=body.mem_limit, replicas=body.replicas, reason=body.reason)


@router.get("/clusters/{cluster_id}/actions", response_model=list[ActionOut])
def list_actions(cluster_id: str, status: str | None = None, db: Session = Depends(get_db),
                 _: Principal = Depends(require_viewer)):
    get_cluster_or_404(cluster_id, db)
    q = db.query(RemediationAction).filter(RemediationAction.cluster_id == cluster_id)
    if status:
        q = q.filter(RemediationAction.status == status)
    return q.order_by(RemediationAction.id.desc()).all()


@router.get("/clusters/{cluster_id}/actions/{action_id}", response_model=ActionOut)
def get_action(cluster_id: str, action_id: int, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    return _action(db, cluster_id, action_id)


@router.get("/clusters/{cluster_id}/actions/{action_id}/patch.yaml",
            summary="GitOps export: the change as a kustomize strategic-merge patch")
def get_patch(cluster_id: str, action_id: int, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    a = _action(db, cluster_id, action_id)
    return Response(svc.gitops_patch_yaml(a), media_type="application/yaml",
                    headers={"Content-Disposition": f'attachment; filename="kubefinops-action-{a.id}.yaml"'})


@router.post("/clusters/{cluster_id}/actions/{action_id}/approve", response_model=ActionOut)
def approve(cluster_id: str, action_id: int, db: Session = Depends(get_db), p: Principal = Depends(require_operator)):
    return svc.approve(db, _action(db, cluster_id, action_id), p)


@router.post("/clusters/{cluster_id}/actions/{action_id}/reject", response_model=ActionOut)
def reject(cluster_id: str, action_id: int, body: RejectIn, db: Session = Depends(get_db),
           p: Principal = Depends(require_operator)):
    return svc.reject(db, _action(db, cluster_id, action_id), p, body.reason)


# --- agent side (cluster token) ---------------------------------------------------------


@router.get("/agent/actions", summary="Agent: actions to dry-run or apply now")
def agent_work(cluster: Cluster = Depends(authenticate_agent), db: Session = Depends(get_db)):
    return {"actions": svc.work_for_agent(db, cluster)}


@router.post("/agent/actions/{action_id}/result", response_model=ActionOut, summary="Agent: report a result")
def agent_result(action_id: int, body: AgentResultIn, cluster: Cluster = Depends(authenticate_agent),
                 db: Session = Depends(get_db)):
    return svc.report_result(db, cluster, action_id, body.phase, body.ok, diff=body.diff,
                             previous_spec=body.previous_spec, error=body.error)
