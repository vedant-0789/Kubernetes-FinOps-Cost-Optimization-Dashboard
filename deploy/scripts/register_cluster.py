"""Register a cluster with a KubeFinOps server (or rotate its token if it
exists) and print the agent token. Stdlib only, so it can run inside the API
pod:  kubectl exec -i deploy/finops-server-api -- python - NAME PROVIDER REGION < register_cluster.py

Env: FINOPS_URL (default http://127.0.0.1:8000), FINOPS_ADMIN_API_KEY.
"""

import json
import os
import sys
import urllib.error
import urllib.request

base = os.environ.get("FINOPS_URL", "http://127.0.0.1:8000").rstrip("/")
headers = {"Content-Type": "application/json"}
if os.environ.get("FINOPS_ADMIN_API_KEY"):
    headers["X-Admin-Key"] = os.environ["FINOPS_ADMIN_API_KEY"]


def call(method, path, body=None):
    req = urllib.request.Request(base + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


name, provider, region = (sys.argv[1:] + ["kind-local", "aws", "us-east-1"][len(sys.argv) - 1:])[:3]
existing = next((c for c in call("GET", "/api/v1/clusters") if c["name"] == name), None)
if existing:
    token = call("POST", f"/api/v1/clusters/{existing['id']}/rotate-token")["agent_token"]
else:
    token = call("POST", "/api/v1/clusters", {"name": name, "provider": provider, "region": region})["agent_token"]
print(token)
