import datetime
import json

import pytest

from app.core.config import settings
from app.db.platform_models import AuditEvent, Cluster, RemediationAction, WasteFinding, utcnow
from app.services import audit
from app.services.demo import DEMO_CLUSTER_NAME
from app.services.remediation import in_change_window, rollback_patch, verify_applied
from tests.helpers_auth import ensure_user, login

API = "/api/v1"
GIB = 1024**3


@pytest.fixture
def team(client, db, auth_on):
    ensure_user(db, "alice@example.com", "operator")
    ensure_user(db, "bob@example.com", "operator")
    ensure_user(db, "admin@example.com", "admin")
    ensure_user(db, "vera@example.com", "viewer")
    return {n: login(client, f"{n}@example.com") for n in ("alice", "bob", "admin", "vera")}


@pytest.fixture
def cluster(client, team, request):
    name = "rem-" + "".join(ch if ch.isalnum() else "-" for ch in request.node.name.lower())[:50].strip("-")
    r = client.post(f"{API}/clusters", json={"name": name}, headers=team["admin"])
    assert r.status_code == 201, r.text
    c = r.json()
    c["agent"] = {"Authorization": f"Bearer {c['agent_token']}"}
    yield c
    client.delete(f"{API}/clusters/{c['id']}", headers=team["admin"])


def propose(client, cluster, who, **body):
    payload = {"namespace": "shop", "workload_kind": "Deployment", "workload_name": "api", "container": "api",
               "cpu_request": 0.5, "mem_request": 512 * 2**20, "reason": "test"} | body
    return client.post(f"{API}/clusters/{cluster['id']}/actions", json=payload, headers=who)


def agent_work(client, cluster):
    return client.get(f"{API}/agent/actions", headers=cluster["agent"]).json()["actions"]


def agent_report(client, cluster, action_id, **body):
    r = client.post(f"{API}/agent/actions/{action_id}/result", json=body, headers=cluster["agent"])
    assert r.status_code == 200, r.text
    return r.json()


PREVIOUS = {"replicas": 2, "containers": {"api": {"requests": {"cpu": "1", "memory": "1Gi"}, "limits": {}}}}


def run_to_applied(client, cluster, team):
    a = propose(client, cluster, team["alice"]).json()
    [work] = agent_work(client, cluster)
    assert work["phase"] == "dry_run"
    agent_report(client, cluster, a["id"], phase="dry_run", ok=True, diff={"containers": {"api": {}}})
    client.post(f"{API}/clusters/{cluster['id']}/actions/{a['id']}/approve", headers=team["bob"])
    [work] = agent_work(client, cluster)
    assert work["phase"] == "apply"
    done = agent_report(client, cluster, a["id"], phase="apply", ok=True, previous_spec=PREVIOUS)
    # Move the apply an hour into the past so the whole watch period can be
    # filled with samples (ingestion rejects timestamps in the future).
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        row = db.get(RemediationAction, done["id"])
        row.applied_at = row.applied_at - datetime.timedelta(hours=1)
        db.commit()
        done["applied_at"] = row.applied_at.isoformat()
    return done


def push_samples(client, cluster, start, minutes, oom_every=None, throttled=0.0):
    samples = []
    for i in range(minutes // 5):
        ts = start + datetime.timedelta(minutes=5 * i)
        samples.append({"ts": ts.isoformat(), "namespace": "shop", "pod": "api-1", "container": "api",
                        "workload_kind": "Deployment", "workload_name": "api", "cpu_request_cores": 0.5,
                        "cpu_usage_cores": 0.2, "mem_request_bytes": 512 * 2**20, "mem_usage_bytes": 400 * 2**20,
                        "cpu_throttled_seconds": throttled,
                        "oom_kills": 1 if oom_every and i % oom_every == 0 else 0,
                        "restarts": 1 if oom_every and i % oom_every == 0 else 0})
    assert client.post(f"{API}/ingest/samples", json={"samples": samples}, headers=cluster["agent"]).status_code == 200


def test_full_lifecycle_with_two_person_rule(client, cluster, team, db):
    a = propose(client, cluster, team["alice"])
    assert a.status_code == 201 and a.json()["status"] == "dry_run_pending"
    a = a.json()
    assert a["patch"]["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"] == \
        {"cpu": "500m", "memory": "512Mi"}

    [work] = agent_work(client, cluster)
    assert (work["id"], work["phase"]) == (a["id"], "dry_run")
    assert agent_work(client, cluster) == []  # in flight: not handed out twice
    agent_report(client, cluster, a["id"], phase="dry_run", ok=True, diff={"containers": {"api": {"after": {}}}})

    url = f"{API}/clusters/{cluster['id']}/actions/{a['id']}"
    assert client.post(f"{url}/approve", headers=team["alice"]).status_code == 403   # own change
    assert client.post(f"{url}/approve", headers=team["vera"]).status_code == 403    # viewer
    r = client.post(f"{url}/approve", headers=team["bob"])
    assert r.json()["status"] == "approved" and r.json()["approved_by"] == "bob@example.com"

    [work] = agent_work(client, cluster)
    assert work["phase"] == "apply"
    done = agent_report(client, cluster, a["id"], phase="apply", ok=True, previous_spec=PREVIOUS)
    assert done["status"] == "applied" and done["previous_spec"] == PREVIOUS

    actions = [e.action for e in db.query(AuditEvent).filter(AuditEvent.cluster_id == cluster["id"])]
    assert ["remediation.propose", "remediation.dry_run_ok", "remediation.approve", "remediation.apply_ok"] == \
        [x for x in actions if x.startswith("remediation.")]
    assert client.get(f"{API}/audit/verify", headers=team["admin"]).json()["valid"] is True


def test_dry_run_failure_stops_the_action(client, cluster, team):
    a = propose(client, cluster, team["alice"]).json()
    agent_work(client, cluster)
    r = agent_report(client, cluster, a["id"], phase="dry_run", ok=False, error="admission webhook denied")
    assert r["status"] == "dry_run_failed"
    url = f"{API}/clusters/{cluster['id']}/actions/{a['id']}/approve"
    assert client.post(url, headers=team["bob"]).status_code == 409


def test_healthy_change_is_verified(client, cluster, team, db):
    a = run_to_applied(client, cluster, team)
    applied = datetime.datetime.fromisoformat(a["applied_at"])
    push_samples(client, cluster, applied - datetime.timedelta(minutes=30), 60)
    verify_applied(db, now=applied + datetime.timedelta(minutes=settings.remediation_verify_minutes + 1))
    r = client.get(f"{API}/clusters/{cluster['id']}/actions/{a['id']}", headers=team["vera"]).json()
    assert r["status"] == "verified" and r["verification"]["regressions"] == []


def test_regression_triggers_automatic_rollback(client, cluster, team, db, monkeypatch):
    a = run_to_applied(client, cluster, team)
    applied = datetime.datetime.fromisoformat(a["applied_at"])
    push_samples(client, cluster, applied - datetime.timedelta(minutes=30), 30)               # healthy before
    push_samples(client, cluster, applied, 30, oom_every=2)                                     # OOMs after
    verify_applied(db, now=applied + datetime.timedelta(minutes=settings.remediation_verify_minutes + 1))

    original = client.get(f"{API}/clusters/{cluster['id']}/actions/{a['id']}", headers=team["vera"]).json()
    assert original["status"] == "rolling_back"
    assert "OOM kills rose" in original["verification"]["regressions"][0]

    # Rollbacks bypass the change window and the approval step.
    monkeypatch.setattr(settings, "change_window_utc", "03:00-03:01" if utcnow().hour != 3 else "05:00-05:01")
    [work] = agent_work(client, cluster)
    assert work["type"] == "ROLLBACK" and work["phase"] == "apply"
    restored = work["patch"]["spec"]["template"]["spec"]["containers"][0]["resources"]
    assert restored["requests"] == {"cpu": "1", "memory": "1Gi"}
    agent_report(client, cluster, work["id"], phase="apply", ok=True, previous_spec={})
    original = client.get(f"{API}/clusters/{cluster['id']}/actions/{a['id']}", headers=team["vera"]).json()
    assert original["status"] == "rolled_back"
    events = [e.action for e in db.query(AuditEvent).filter(AuditEvent.cluster_id == cluster["id"])]
    assert "remediation.auto_rollback" in events


def test_verification_waits_for_data_instead_of_blessing_an_empty_window(client, cluster, team, db):
    """Regression (found live on kind): verification ran before the agent had
    reported the after-window, saw no problems in no data, and marked a change
    that crash-looped the pods as verified."""
    a = run_to_applied(client, cluster, team)
    applied = datetime.datetime.fromisoformat(a["applied_at"])
    push_samples(client, cluster, applied - datetime.timedelta(minutes=30), 30)   # only "before" data so far
    verify_applied(db, now=applied + datetime.timedelta(minutes=settings.remediation_verify_minutes + 1))
    url = f"{API}/clusters/{cluster['id']}/actions/{a['id']}"
    assert client.get(url, headers=team["vera"]).json()["status"] == "applied"     # still waiting

    # Still nothing after 3x the watch period: treat silence as a failure.
    verify_applied(db, now=applied + datetime.timedelta(minutes=3 * settings.remediation_verify_minutes + 1))
    r = client.get(url, headers=team["vera"]).json()
    assert r["status"] == "rolling_back" and "no usage data" in r["verification"]["regressions"][0]


@pytest.mark.parametrize("offset_seconds", [0.2, 150, 299.5])
def test_slot_straddling_the_apply_counts_on_neither_side(client, cluster, team, db, offset_seconds):
    """Regression (found live on kind, then again on CI): the 5-minute slot in
    which the change was applied (keyed by its start) must count on neither
    side. A first fix still leaked it into "before" when the apply landed in a
    slot's last second, so the dangerous offsets are pinned explicitly."""
    a = run_to_applied(client, cluster, team)
    applied = datetime.datetime.fromisoformat(a["applied_at"])
    slot_start = applied.replace(minute=applied.minute - applied.minute % 5, second=0, microsecond=0)
    applied = slot_start + datetime.timedelta(seconds=offset_seconds)
    row = db.get(RemediationAction, a["id"])
    row.applied_at = applied
    db.commit()
    push_samples(client, cluster, slot_start - datetime.timedelta(minutes=30), 30)        # healthy before
    push_samples(client, cluster, slot_start, 5, oom_every=1)                             # straddling slot
    push_samples(client, cluster, slot_start + datetime.timedelta(minutes=5), 30, oom_every=1)  # after
    verify_applied(db, now=applied + datetime.timedelta(minutes=settings.remediation_verify_minutes + 6))
    db.expire_all()
    r = client.get(f"{API}/clusters/{cluster['id']}/actions/{a['id']}", headers=team["vera"]).json()
    assert r["verification"]["before"]["oom_kills"] == 0
    assert r["verification"]["after"]["oom_kills"] > 0
    assert r["status"] == "rolling_back"


def test_crash_loop_without_oom_is_a_regression(client, cluster, team, db):
    a = run_to_applied(client, cluster, team)
    applied = datetime.datetime.fromisoformat(a["applied_at"])
    push_samples(client, cluster, applied - datetime.timedelta(minutes=30), 30)
    after = applied.replace(second=0, microsecond=0) + datetime.timedelta(minutes=5 - applied.minute % 5)
    samples = [{"ts": (after + datetime.timedelta(minutes=5 * i)).isoformat(), "namespace": "shop", "pod": "api-2",
                "container": "api", "workload_kind": "Deployment", "workload_name": "api",
                "cpu_usage_cores": 0.0, "mem_usage_bytes": 0, "restarts": 2} for i in range(6)]
    client.post(f"{API}/ingest/samples", json={"samples": samples}, headers=cluster["agent"])
    verify_applied(db, now=applied + datetime.timedelta(minutes=settings.remediation_verify_minutes + 6))
    r = client.get(f"{API}/clusters/{cluster['id']}/actions/{a['id']}", headers=team["vera"]).json()
    assert r["status"] == "rolling_back" and "restarts rose" in " ".join(r["verification"]["regressions"])


def test_rollback_removes_limits_the_change_added():
    applied = {"spec": {"template": {"spec": {"containers": [
        {"name": "api", "resources": {"requests": {"cpu": "500m"}, "limits": {"cpu": "1", "memory": "1Gi"}}}]}}}}
    previous = {"replicas": 1, "containers": {"api": {"requests": {"cpu": "2"}, "limits": {}}}}
    res = rollback_patch(previous, applied)["spec"]["template"]["spec"]["containers"][0]["resources"]
    assert res == {"requests": {"cpu": "2"}, "limits": {"cpu": None, "memory": None}}


def test_change_window_holds_applies_but_not_dry_runs(client, cluster, team, monkeypatch):
    now = utcnow()
    closed = f"{(now.hour + 2) % 24:02d}:00-{(now.hour + 3) % 24:02d}:00"
    monkeypatch.setattr(settings, "change_window_utc", closed)
    a = propose(client, cluster, team["alice"]).json()
    [work] = agent_work(client, cluster)
    assert work["phase"] == "dry_run"
    agent_report(client, cluster, a["id"], phase="dry_run", ok=True, diff={})
    client.post(f"{API}/clusters/{cluster['id']}/actions/{a['id']}/approve", headers=team["bob"])
    assert agent_work(client, cluster) == []
    monkeypatch.setattr(settings, "change_window_utc", "00:00-24:00")
    assert agent_work(client, cluster)[0]["phase"] == "apply"


@pytest.mark.parametrize("window,hour,minute,inside", [
    ("00:00-24:00", 13, 0, True), ("02:00-06:00", 3, 30, True), ("02:00-06:00", 6, 0, False),
    ("22:00-04:00", 23, 15, True), ("22:00-04:00", 3, 59, True), ("22:00-04:00", 12, 0, False)])
def test_change_window_parsing(window, hour, minute, inside):
    assert in_change_window(datetime.datetime(2026, 1, 1, hour, minute), window) is inside


def test_guardrails(client, cluster, team, monkeypatch):
    assert propose(client, cluster, team["alice"], namespace="kube-system").status_code == 422
    assert propose(client, cluster, team["alice"], workload_kind="DaemonSet").status_code == 422
    assert propose(client, cluster, team["vera"]).status_code == 403
    assert propose(client, cluster, team["alice"]).status_code == 201
    assert propose(client, cluster, team["alice"]).status_code == 409          # already in progress
    monkeypatch.setattr(settings, "max_actions_per_cluster_per_hour", 1)
    assert propose(client, cluster, team["alice"], workload_name="other").status_code == 429


def test_reject_and_gitops_export(client, cluster, team):
    a = propose(client, cluster, team["alice"], replicas=0, container=None, cpu_request=None,
                mem_request=None).json()
    assert a["type"] == "SCALE" and a["patch"] == {"spec": {"replicas": 0}}
    r = client.get(f"{API}/clusters/{cluster['id']}/actions/{a['id']}/patch.yaml", headers=team["vera"])
    assert r.headers["content-type"].startswith("application/yaml")
    manifest = json.loads("\n".join(line for line in r.text.splitlines() if not line.startswith("#")))
    assert manifest["kind"] == "Deployment" and manifest["metadata"]["name"] == "api"
    r = client.post(f"{API}/clusters/{cluster['id']}/actions/{a['id']}/reject", json={"reason": "owner said no"},
                    headers=team["bob"])
    assert r.json()["status"] == "rejected"
    assert agent_work(client, cluster) == []


def test_actions_from_demo_findings(client, db, team):
    demo = next(c for c in client.get(f"{API}/clusters", headers=team["vera"]).json() if c["name"] == DEMO_CLUSTER_NAME)
    client.post(f"{API}/clusters/{demo['id']}/analyze", headers=team["alice"])
    idle = db.query(WasteFinding).filter(WasteFinding.cluster_id == demo["id"], WasteFinding.kind == "IDLE_WORKLOAD",
                                         WasteFinding.status == "open").first()
    r = client.post(f"{API}/clusters/{demo['id']}/actions", json={"finding_id": idle.id}, headers=team["alice"])
    assert r.status_code == 201 and r.json()["patch"] == {"spec": {"replicas": 0}}
    lb = db.query(WasteFinding).filter(WasteFinding.cluster_id == demo["id"],
                                       WasteFinding.kind != "IDLE_WORKLOAD").first()
    if lb is not None:
        r = client.post(f"{API}/clusters/{demo['id']}/actions", json={"finding_id": lb.id}, headers=team["alice"])
        assert r.status_code == 422
    db.query(RemediationAction).filter(RemediationAction.cluster_id == demo["id"]).delete()
    db.commit()


def test_agent_cannot_touch_other_clusters_actions(client, cluster, team, db):
    a = propose(client, cluster, team["alice"]).json()
    other = db.query(Cluster).filter(Cluster.name == DEMO_CLUSTER_NAME).first()
    assert other is not None
    r = client.post(f"{API}/agent/actions/{a['id']}/result", json={"phase": "dry_run", "ok": True},
                    headers={"Authorization": "Bearer kfo_deadbeef_x"})
    assert r.status_code == 401


def test_audit_chain_detects_tampering(client, db, team):
    audit.record(db, "tester", "test.event", details={"n": 1}, commit=True)
    assert client.get(f"{API}/audit/verify", headers=team["admin"]).json()["valid"] is True
    victim = db.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
    original = victim.details
    victim.details = {"n": 999}
    db.commit()
    result = client.get(f"{API}/audit/verify", headers=team["admin"]).json()
    assert result["valid"] is False and result["first_invalid_id"] == victim.id
    victim.details = original
    db.commit()
    assert client.get(f"{API}/audit/verify", headers=team["admin"]).json()["valid"] is True
