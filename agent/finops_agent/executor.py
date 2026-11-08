"""Executes approved remediation actions in the cluster (opt-in).

Disabled unless FINOPS_AGENT_REMEDIATION_ENABLED=true and the chart grants
``rbac.allowRemediation`` (patch on deployments / statefulsets only).

* dry_run: server-side dry-run of the strategic-merge patch (``dryRun=All``):
  the API server validates and admits the change without persisting it, so
  admission webhooks / quotas / policies are exercised too. The before/after
  replicas and container resources are reported as a diff.
* apply: capture the current replicas and every container's resources
  (the server keeps them for rollback), then apply the patch.
"""

import logging

logger = logging.getLogger("agent.executor")
KINDS = {
    "Deployment": ("read_namespaced_deployment", "patch_namespaced_deployment"),
    "StatefulSet": ("read_namespaced_stateful_set", "patch_namespaced_stateful_set"),
}


def _resources(container) -> dict:
    res = container.resources
    return {"requests": dict((res.requests or {}) if res else {}), "limits": dict((res.limits or {}) if res else {})}


def snapshot(obj) -> dict:
    """The parts of a workload a KubeFinOps action can change."""
    return {"replicas": obj.spec.replicas,
            "containers": {c.name: _resources(c) for c in obj.spec.template.spec.containers}}


def diff(before: dict, after: dict) -> dict:
    out: dict = {}
    if before.get("replicas") != after.get("replicas"):
        out["replicas"] = {"before": before.get("replicas"), "after": after.get("replicas")}
    changed = {}
    for name, res in after.get("containers", {}).items():
        if before.get("containers", {}).get(name) != res:
            changed[name] = {"before": before.get("containers", {}).get(name), "after": res}
    if changed:
        out["containers"] = changed
    return out


class Executor:
    def __init__(self, apps_api, server):
        self.apps = apps_api
        self.server = server

    def _calls(self, kind: str):
        if kind not in KINDS:
            raise ValueError(f"unsupported kind {kind}")
        read, patch = KINDS[kind]
        return getattr(self.apps, read), getattr(self.apps, patch)

    def execute(self, action: dict) -> dict:
        read, patch = self._calls(action["kind"])
        name, ns = action["name"], action["namespace"]
        before = snapshot(read(name=name, namespace=ns))
        if action["phase"] == "dry_run":
            result = patch(name=name, namespace=ns, body=action["patch"], dry_run="All")
            return {"phase": "dry_run", "ok": True, "diff": diff(before, snapshot(result))}
        patch(name=name, namespace=ns, body=action["patch"])
        return {"phase": "apply", "ok": True, "previous_spec": before}

    def run_once(self) -> int:
        work = self.server.get("/api/v1/agent/actions").get("actions", [])
        for action in work:
            try:
                result = self.execute(action)
            except Exception as exc:  # report every failure; never crash the agent loop
                reason = getattr(exc, "reason", None) or exc.__class__.__name__
                body = getattr(exc, "body", None)
                result = {"phase": action["phase"], "ok": False, "error": f"{reason}: {body or exc}"[:2000]}
                logger.warning("Action %s (%s) failed: %s", action["id"], action["phase"], result["error"][:200])
            else:
                logger.info("Action %s %s ok", action["id"], action["phase"])
            self.server.post(f"/api/v1/agent/actions/{action['id']}/result", result)
        return len(work)
