import copy
from types import SimpleNamespace as NS

import pytest

from finops_agent.executor import Executor, diff, snapshot


def deployment(replicas=2, cpu="1", mem="1Gi", limits=None):
    return NS(spec=NS(replicas=replicas, template=NS(spec=NS(containers=[
        NS(name="api", resources=NS(requests={"cpu": cpu, "memory": mem}, limits=limits)),
        NS(name="sidecar", resources=NS(requests={"cpu": "50m"}, limits=None)),
    ]))))


class FakeApps:
    """Applies strategic-merge patches for replicas and container resources."""

    def __init__(self):
        self.obj = deployment()
        self.calls = []

    def read_namespaced_deployment(self, name, namespace):
        return copy.deepcopy(self.obj)

    def patch_namespaced_deployment(self, name, namespace, body, dry_run=None):
        self.calls.append(("patch", dry_run))
        new = copy.deepcopy(self.obj)
        spec = body.get("spec", {})
        if "replicas" in spec:
            new.spec.replicas = spec["replicas"]
        for c in spec.get("template", {}).get("spec", {}).get("containers", []):
            target = next(x for x in new.spec.template.spec.containers if x.name == c["name"])
            for section in ("requests", "limits"):
                if section in c.get("resources", {}):
                    cur = dict(getattr(target.resources, section) or {})
                    for k, v in c["resources"][section].items():
                        if v is None:
                            cur.pop(k, None)
                        else:
                            cur[k] = v
                    setattr(target.resources, section, cur)
        if dry_run != "All":
            self.obj = new
        return new


class FakeServer:
    def __init__(self, actions):
        self.actions = actions
        self.results = []

    def get(self, path):
        return {"actions": self.actions}

    def post(self, path, payload):
        self.results.append((path, payload))
        return {}


PATCH = {"spec": {"template": {"spec": {"containers": [
    {"name": "api", "resources": {"requests": {"cpu": "500m", "memory": "512Mi"}}}]}}}}


def action(phase, patch=PATCH, kind="Deployment"):
    return {"id": 7, "phase": phase, "type": "RIGHTSIZE", "namespace": "shop", "kind": kind, "name": "api",
            "container": "api", "patch": patch}


def test_dry_run_reports_diff_and_changes_nothing():
    apps = FakeApps()
    server = FakeServer([action("dry_run")])
    Executor(apps, server).run_once()
    path, result = server.results[0]
    assert path == "/api/v1/agent/actions/7/result" and result["ok"]
    assert result["diff"]["containers"]["api"]["after"]["requests"] == {"cpu": "500m", "memory": "512Mi"}
    assert "sidecar" not in result["diff"]["containers"]
    assert apps.calls == [("patch", "All")]
    assert apps.obj.spec.template.spec.containers[0].resources.requests["cpu"] == "1"


def test_apply_captures_previous_spec_for_rollback():
    apps = FakeApps()
    server = FakeServer([action("apply")])
    Executor(apps, server).run_once()
    result = server.results[0][1]
    assert result["ok"] and result["phase"] == "apply"
    assert result["previous_spec"]["containers"]["api"]["requests"] == {"cpu": "1", "memory": "1Gi"}
    assert result["previous_spec"]["replicas"] == 2
    assert apps.obj.spec.template.spec.containers[0].resources.requests["cpu"] == "500m"


def test_failures_are_reported_not_raised():
    class Boom(FakeApps):
        def patch_namespaced_deployment(self, *a, **kw):
            raise RuntimeError("admission webhook denied: requests below policy minimum")

    server = FakeServer([action("dry_run")])
    Executor(Boom(), server).run_once()
    result = server.results[0][1]
    assert result["ok"] is False and "admission webhook denied" in result["error"]


def test_unsupported_kind_is_reported():
    server = FakeServer([action("apply", kind="DaemonSet")])
    Executor(FakeApps(), server).run_once()
    assert server.results[0][1]["ok"] is False


@pytest.mark.parametrize("before,after,expected", [
    ({"replicas": 1, "containers": {}}, {"replicas": 0, "containers": {}}, {"replicas": {"before": 1, "after": 0}}),
    ({"replicas": 1, "containers": {"a": {"requests": {}}}}, {"replicas": 1, "containers": {"a": {"requests": {}}}},
     {}),
])
def test_diff(before, after, expected):
    assert diff(before, after) == expected


def test_snapshot_handles_missing_resources():
    obj = NS(spec=NS(replicas=1, template=NS(spec=NS(containers=[NS(name="x", resources=None)]))))
    assert snapshot(obj) == {"replicas": 1, "containers": {"x": {"requests": {}, "limits": {}}}}
