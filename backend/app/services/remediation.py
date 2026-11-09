"""Safe remediation workflow.

The server never talks to a cluster API directly (agents pull work), so:

1. A user proposes an action (from a recommendation, an idle finding, or
   manually). Guardrails run first: protected namespaces, supported kinds,
   per-cluster rate limit.
2. The agent runs a **server-side dry-run** (``dryRun=All``) and returns the
   resulting diff -> ``pending_approval`` (or ``dry_run_failed``).
3. A *different* operator approves it (two-person rule) -> ``approved``.
4. Inside the change window the agent captures the current spec (for
   rollback), applies the patch and reports -> ``applied``.
5. After the verification period the server compares OOM kills and
   throttling after vs. before the change. If it got worse, it creates an
   auto-approved ROLLBACK that restores the captured spec; otherwise the
   action becomes ``verified``.
Every transition is written to the hash-chained audit log.
"""

import datetime
import json
import math

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import Principal
from app.core.config import settings
from app.db.platform_models import (
    Cluster,
    RemediationAction,
    RightsizingRecommendation,
    UsageSample,
    WasteFinding,
    utcnow,
)
from app.services import audit

SUPPORTED_KINDS = ("Deployment", "StatefulSet")
REDISPATCH_AFTER = datetime.timedelta(minutes=10)
SYSTEM = "system:auto-rollback"


# --- patches ------------------------------------------------------------------------


def cpu_quantity(cores: float) -> str:
    return f"{max(1, math.ceil(cores * 1000))}m"


def mem_quantity(num_bytes: float) -> str:
    return f"{max(1, math.ceil(num_bytes / 2**20))}Mi"


def rightsize_patch(container: str, cpu_request: float, mem_request: float, cpu_limit: float | None,
                    mem_limit: float | None) -> dict:
    resources: dict = {"requests": {"cpu": cpu_quantity(cpu_request), "memory": mem_quantity(mem_request)}}
    limits = {}
    if cpu_limit:
        limits["cpu"] = cpu_quantity(cpu_limit)
    if mem_limit:
        limits["memory"] = mem_quantity(mem_limit)
    if limits:
        resources["limits"] = limits
    # Strategic merge patch: containers are merged by name.
    return {"spec": {"template": {"spec": {"containers": [{"name": container, "resources": resources}]}}}}


def scale_patch(replicas: int) -> dict:
    return {"spec": {"replicas": replicas}}


def rollback_patch(previous_spec: dict, applied_patch: dict | None = None) -> dict:
    """Restore the captured spec. A strategic merge only overwrites keys it
    names, so any request/limit the applied patch *added* is set to null
    (deleted) explicitly; otherwise a rollback would leave it behind."""
    patch: dict = {"spec": {}}
    if "replicas" in previous_spec:
        patch["spec"]["replicas"] = previous_spec["replicas"]
    applied = {c["name"]: c.get("resources", {}) for c in
               ((applied_patch or {}).get("spec", {}).get("template", {}).get("spec", {}).get("containers") or [])}
    containers = []
    for name, res in (previous_spec.get("containers") or {}).items():
        restored = {"requests": dict(res.get("requests") or {}), "limits": dict(res.get("limits") or {})}
        for section in ("requests", "limits"):
            for key in (applied.get(name, {}).get(section) or {}):
                restored[section].setdefault(key, None)
        containers.append({"name": name, "resources": {k: v for k, v in restored.items() if v}})
    if containers:
        patch["spec"]["template"] = {"spec": {"containers": containers}}
    return patch


def gitops_patch_yaml(a: RemediationAction) -> str:
    """Kustomize strategic-merge patch for teams that change clusters only via Git.
    JSON is valid YAML 1.2, so the manifest body is emitted as indented JSON."""
    manifest = {"apiVersion": "apps/v1", "kind": a.workload_kind,
                "metadata": {"name": a.workload_name, "namespace": a.namespace}, **a.patch}
    return (f"# KubeFinOps action #{a.id} ({a.type}) - add to your kustomization.yaml `patches:`\n"
            f"# Expected saving: ${a.expected_monthly_savings:.2f}/month\n" + json.dumps(manifest, indent=2) + "\n")


# --- guardrails ---------------------------------------------------------------------


def in_change_window(now: datetime.datetime, window: str | None = None) -> bool:
    window = window or settings.change_window_utc
    start_s, end_s = window.split("-")
    to_min = lambda s: int(s[:2]) * 60 + int(s[3:5])  # noqa: E731
    start, end, cur = to_min(start_s), to_min(end_s), now.hour * 60 + now.minute
    if start == end or (start == 0 and end == 24 * 60):
        return True
    return start <= cur < end if start < end else (cur >= start or cur < end)  # wraps midnight


def _guard(db: Session, cluster: Cluster, namespace: str, kind: str) -> None:
    if namespace in settings.protected_namespaces:
        raise HTTPException(422, f"Namespace '{namespace}' is protected; remediation is not allowed there")
    if kind not in SUPPORTED_KINDS:
        raise HTTPException(422, f"Automatic remediation supports {', '.join(SUPPORTED_KINDS)}, not {kind}")
    recent = db.query(func.count(RemediationAction.id)).filter(
        RemediationAction.cluster_id == cluster.id,
        RemediationAction.created_at >= utcnow() - datetime.timedelta(hours=1),
        RemediationAction.type != "ROLLBACK").scalar()
    if recent >= settings.max_actions_per_cluster_per_hour:
        raise HTTPException(429, "Too many remediation actions for this cluster in the last hour")


def _open_action_exists(db: Session, cluster: Cluster, namespace: str, kind: str, name: str) -> bool:
    return db.query(RemediationAction.id).filter(
        RemediationAction.cluster_id == cluster.id, RemediationAction.namespace == namespace,
        RemediationAction.workload_kind == kind, RemediationAction.workload_name == name,
        RemediationAction.status.in_(("dry_run_pending", "pending_approval", "approved", "applied", "rolling_back")),
    ).first() is not None


def _create(db: Session, cluster: Cluster, p: Principal, **fields) -> RemediationAction:
    _guard(db, cluster, fields["namespace"], fields["workload_kind"])
    if _open_action_exists(db, cluster, fields["namespace"], fields["workload_kind"], fields["workload_name"]):
        raise HTTPException(409, "This workload already has an action in progress")
    a = RemediationAction(cluster_id=cluster.id, status="dry_run_pending", requested_by=p.subject, **fields)
    db.add(a)
    db.flush()
    audit.record(db, p.subject, "remediation.propose", cluster_id=cluster.id, target=_target(a),
                 details={"id": a.id, "type": a.type, "patch": a.patch, "reason": a.reason})
    db.commit()
    db.refresh(a)
    return a


def _target(a: RemediationAction) -> str:
    return f"{a.namespace}/{a.workload_kind}/{a.workload_name}" + (f"/{a.container}" if a.container else "")


def propose_from_recommendation(db: Session, cluster: Cluster, rec: RightsizingRecommendation,
                                p: Principal) -> RemediationAction:
    if rec.status != "open":
        raise HTTPException(409, f"Recommendation is {rec.status}")
    return _create(db, cluster, p, type="RIGHTSIZE", namespace=rec.namespace, workload_kind=rec.workload_kind,
                   workload_name=rec.workload_name, container=rec.container, recommendation_id=rec.id,
                   expected_monthly_savings=rec.monthly_savings,
                   patch=rightsize_patch(rec.container, rec.recommended_cpu_request, rec.recommended_mem_request,
                                         rec.recommended_cpu_limit, rec.recommended_mem_limit),
                   reason=f"Right-size ({rec.strategy}): " + "; ".join(rec.reasons)[:400])


def propose_from_finding(db: Session, cluster: Cluster, f: WasteFinding, p: Principal) -> RemediationAction:
    if f.kind != "IDLE_WORKLOAD":
        raise HTTPException(422, f"{f.kind} needs a manual change (see the finding's action); "
                                 "only idle workloads can be scaled automatically")
    if f.status != "open":
        raise HTTPException(409, f"Finding is {f.status}")
    kind, name = f.evidence["workload_kind"], f.evidence["workload_name"]
    return _create(db, cluster, p, type="SCALE", namespace=f.namespace, workload_kind=kind, workload_name=name,
                   finding_id=f.id, expected_monthly_savings=f.monthly_savings, patch=scale_patch(0),
                   reason="Idle workload: scale to 0 replicas (reversible)")


def propose_manual(db: Session, cluster: Cluster, p: Principal, *, namespace: str, workload_kind: str,
                   workload_name: str, container: str | None, cpu_request: float | None, mem_request: float | None,
                   cpu_limit: float | None, mem_limit: float | None, replicas: int | None,
                   reason: str | None) -> RemediationAction:
    if replicas is not None:
        patch, type_ = scale_patch(replicas), "SCALE"
    else:
        if not container or cpu_request is None or mem_request is None:
            raise HTTPException(422, "Right-sizing needs container, cpu_request and mem_request (or give replicas)")
        patch, type_ = rightsize_patch(container, cpu_request, mem_request, cpu_limit, mem_limit), "RIGHTSIZE"
    return _create(db, cluster, p, type=type_, namespace=namespace, workload_kind=workload_kind,
                   workload_name=workload_name, container=container, patch=patch, reason=reason or "manual")


# --- human decisions ------------------------------------------------------------------


def approve(db: Session, a: RemediationAction, p: Principal) -> RemediationAction:
    if a.status != "pending_approval":
        raise HTTPException(409, f"Only actions pending approval can be approved (this one is {a.status})")
    if settings.require_two_person_approval and p.subject == a.requested_by:
        raise HTTPException(403, "Two-person rule: the requester cannot approve their own change")
    a.status, a.approved_by, a.updated_at = "approved", p.subject, utcnow()
    audit.record(db, p.subject, "remediation.approve", cluster_id=a.cluster_id, target=_target(a),
                 details={"id": a.id})
    db.commit()
    db.refresh(a)
    return a


def reject(db: Session, a: RemediationAction, p: Principal, reason: str) -> RemediationAction:
    if a.status not in ("dry_run_pending", "pending_approval", "approved"):
        raise HTTPException(409, f"Cannot reject an action that is {a.status}")
    a.status, a.error, a.updated_at = "rejected", reason, utcnow()
    audit.record(db, p.subject, "remediation.reject", cluster_id=a.cluster_id, target=_target(a),
                 details={"id": a.id, "reason": reason})
    db.commit()
    db.refresh(a)
    return a


# --- agent protocol ---------------------------------------------------------------------


def work_for_agent(db: Session, cluster: Cluster, now: datetime.datetime | None = None) -> list[dict]:
    """Dry-runs always; applies only inside the change window (rollbacks always)."""
    now = now or utcnow()
    open_window = in_change_window(now)
    stale = now - REDISPATCH_AFTER
    rows = db.query(RemediationAction).filter(
        RemediationAction.cluster_id == cluster.id,
        RemediationAction.status.in_(("dry_run_pending", "approved"))).order_by(RemediationAction.id).all()
    out = []
    for a in rows:
        if a.dispatched_at and a.dispatched_at > stale:
            continue   # in flight
        phase = "dry_run" if a.status == "dry_run_pending" else "apply"
        if phase == "apply" and not open_window and a.type != "ROLLBACK":
            continue
        a.dispatched_at = now
        out.append({"id": a.id, "phase": phase, "type": a.type, "namespace": a.namespace, "kind": a.workload_kind,
                    "name": a.workload_name, "container": a.container, "patch": a.patch})
    db.commit()
    return out


def report_result(db: Session, cluster: Cluster, action_id: int, phase: str, ok: bool, *, diff: dict | None = None,
                  previous_spec: dict | None = None, error: str | None = None) -> RemediationAction:
    a = db.get(RemediationAction, action_id)
    if a is None or a.cluster_id != cluster.id:
        raise HTTPException(404, "Action not found")
    expected = "dry_run_pending" if phase == "dry_run" else "approved"
    if a.status != expected:
        raise HTTPException(409, f"Action is {a.status}, not expecting a {phase} result")
    now = utcnow()
    actor = f"agent:{cluster.name}"
    a.updated_at, a.dispatched_at = now, None
    if phase == "dry_run":
        a.status = "pending_approval" if ok else "dry_run_failed"
        a.dry_run_diff, a.error = diff, error
    elif ok:
        a.status, a.applied_at, a.previous_spec = "applied", now, previous_spec
        if a.type == "ROLLBACK":
            a.status, a.verified_at = "verified", now
            original = db.get(RemediationAction, a.rollback_of)
            if original is not None:
                original.status, original.updated_at = "rolled_back", now
        if a.recommendation_id:
            rec = db.get(RightsizingRecommendation, a.recommendation_id)
            if rec is not None:
                rec.status, rec.updated_at = "applied", now
        if a.finding_id:
            f = db.get(WasteFinding, a.finding_id)
            if f is not None:
                f.status, f.resolved_at = "resolved", now
    else:
        a.status, a.error = "failed", error
    audit.record(db, actor, f"remediation.{phase}_{'ok' if ok else 'failed'}", cluster_id=cluster.id,
                 target=_target(a), details={"id": a.id, "diff": diff, "error": error})
    if phase == "dry_run" and ok:
        _notify(db, a, f"Approval needed: {a.type.lower()} {_target(a)}",
                f"{a.requested_by} proposed a change; the dry-run passed. It needs a second operator's approval.")
    elif not ok:
        _notify(db, a, f"Remediation {phase.replace('_', '-')} failed: {_target(a)}", error or "unknown error")
    db.commit()
    db.refresh(a)
    return a


def _notify(db: Session, a: RemediationAction, subject: str, text: str) -> None:
    from app.services import notify

    notify.dispatch(db, "remediation", subject, text,
                    {"Action": f"#{a.id} {a.type}", "Target": _target(a), "Requested by": a.requested_by,
                     "Link": f"{settings.public_url}/clusters/{a.cluster_id}/actions/{a.id}"}, cluster_id=a.cluster_id)


# --- verification & automatic rollback ----------------------------------------------------


def _health(db: Session, a: RemediationAction, start: datetime.datetime, end: datetime.datetime) -> dict:
    S = UsageSample
    q = db.query(func.coalesce(func.sum(S.oom_kills), 0), func.coalesce(func.sum(S.restarts), 0),
                 func.coalesce(func.sum(S.cpu_throttled_seconds), 0.0),
                 func.coalesce(func.sum(S.duration_seconds), 0)).filter(
        S.cluster_id == a.cluster_id, S.namespace == a.namespace, S.workload_kind == a.workload_kind,
        S.workload_name == a.workload_name, S.ts >= start, S.ts < end)
    if a.container:
        q = q.filter(S.container == a.container)
    ooms, restarts, throttled, seconds = q.one()
    slots = q.with_entities(func.count(func.distinct(S.ts))).scalar()
    return {"oom_kills": int(ooms), "restarts": int(restarts),
            "throttled_share": round(float(throttled) / seconds, 4) if seconds else 0.0,
            "samples_seconds": seconds, "slots": int(slots or 0)}


SLOT = datetime.timedelta(minutes=5)
MIN_AFTER_COVERAGE = 0.6   # share of the watch period's slots that must have arrived
NO_DATA_GIVE_UP = 3        # x watch period without data -> treat as a regression


def _floor_slot(ts: datetime.datetime) -> datetime.datetime:
    return ts.replace(minute=ts.minute - ts.minute % 5, second=0, microsecond=0)


def verify_applied(db: Session, now: datetime.datetime | None = None) -> int:
    """Compare health before vs. after each applied change.

    Samples are keyed by slot *start*, so the slot in which the change was
    applied mixes old and new pods: it belongs to neither side. "Before" =
    slots that ended before the apply; "after" = slots that started after it.
    The verdict waits until the after-window's data has actually arrived
    (agents report a slot a minute or so after it closes) - judging on an
    empty window would bless a change that broke the workload.
    """
    now = now or utcnow()
    window = datetime.timedelta(minutes=settings.remediation_verify_minutes)
    needed_slots = max(1, int(window / SLOT * MIN_AFTER_COVERAGE))
    done = 0
    for a in db.query(RemediationAction).filter(RemediationAction.status == "applied",
                                                RemediationAction.type != "ROLLBACK").all():
        if a.applied_at is None or a.applied_at + window > now:
            continue
        # Windows on slot boundaries, never on the apply timestamp itself:
        # an offset like "applied - 5 min + 1 s" leaks the straddling slot
        # into "before" whenever the apply lands in a slot's last second.
        straddling = _floor_slot(a.applied_at)
        before = _health(db, a, straddling - window, straddling)
        after = _health(db, a, straddling + SLOT, straddling + SLOT + window)
        scaled_to_zero = a.type == "SCALE" and a.patch.get("spec", {}).get("replicas") == 0
        regressions = []
        if not scaled_to_zero and after["slots"] < needed_slots:
            if now < a.applied_at + window * NO_DATA_GIVE_UP:
                continue   # data still arriving: decide later
            regressions.append(f"no usage data for {NO_DATA_GIVE_UP}x the watch period after the change")
        if settings.rollback_on_oom and after["oom_kills"] > before["oom_kills"]:
            regressions.append(f"OOM kills rose from {before['oom_kills']} to {after['oom_kills']}")
        if after["restarts"] > before["restarts"] and after["restarts"] > after["oom_kills"]:
            regressions.append(f"container restarts rose from {before['restarts']} to {after['restarts']}")
        if after["throttled_share"] > settings.rollback_throttle_share and \
                after["throttled_share"] > before["throttled_share"] * 1.5:
            regressions.append(f"CPU throttling rose to {after['throttled_share']:.0%} of the time")
        if scaled_to_zero:
            regressions = []  # scaled to zero on purpose: no usage is the expected outcome
        a.verification = {"before": before, "after": after, "regressions": regressions, "checked_at": now.isoformat()}
        a.updated_at = now
        if regressions and a.previous_spec:
            a.status = "rolling_back"
            rb = RemediationAction(cluster_id=a.cluster_id, type="ROLLBACK", status="approved", namespace=a.namespace,
                                   workload_kind=a.workload_kind, workload_name=a.workload_name,
                                   container=a.container, patch=rollback_patch(a.previous_spec, a.patch),
                                   rollback_of=a.id,
                                   reason="; ".join(regressions), requested_by=SYSTEM, approved_by=SYSTEM)
            db.add(rb)
            db.flush()
            audit.record(db, SYSTEM, "remediation.auto_rollback", cluster_id=a.cluster_id, target=_target(a),
                         details={"id": a.id, "rollback_id": rb.id, "regressions": regressions})
            _notify(db, a, f"Automatic rollback: {_target(a)}",
                    "The change made the workload worse and is being rolled back: " + "; ".join(regressions))
        else:
            a.status, a.verified_at = "verified", now
            audit.record(db, "system:verifier", "remediation.verified", cluster_id=a.cluster_id, target=_target(a),
                         details={"id": a.id, "before": before, "after": after})
        done += 1
    db.commit()
    return done
