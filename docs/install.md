# Installation and operations

There are four ways to run KubeFinOps, from quickest to most production-like:

| Option | What you get | Needs |
| :--- | :--- | :--- |
| [1. Local dev](#1-local-development) | API + UI with a synthetic demo cluster, SQLite | Python 3.11+, Node 22+ |
| [2. docker compose](#2-docker-compose) | Full server stack (TimescaleDB, API, worker, UI), demo cluster | Docker |
| [3. kind cluster](#3-local-kubernetes-kind) | Everything on a 4-node Kubernetes cluster: Prometheus, Helm charts, a real agent and real demo workloads | Docker, kind, kubectl, helm |
| [4. Production](#4-production-eks--gke--aks--on-prem) | Helm install on EKS / GKE / AKS / on-prem, one agent per cluster | A cluster, managed PostgreSQL with TimescaleDB (or the bundled one) |

## 1. Local development

```powershell
.\start.ps1            # Windows (or start.bat)
```

or manually on any OS:

```bash
cd backend && pip install -r requirements.txt && python run_backend.py     # API  http://127.0.0.1:8000/docs
cd frontend && npm ci && npm run dev                                        # UI   http://localhost:5173
```

On first run `run_backend.py` writes `backend/.env` (git-ignored) with a random JWT secret and a local admin
account. Sign in as `admin@kubefinops.localhost`; the password is `FINOPS_BOOTSTRAP_ADMIN_PASSWORD` in
`backend/.env`. The API seeds the `demo-aws-prod` cluster, which has 14 days of 5-minute history generated
through the same ingestion code an agent uses.

Tests:

```bash
cd backend  && pip install -r requirements-dev.txt && ruff check . && pytest
cd agent    && pip install -r requirements.txt pytest ruff && ruff check . && pytest
cd frontend && npm test
cd research && pip install -r requirements.txt pytest && pytest
```

## 2. docker compose

```bash
docker compose -f deploy/docker-compose.yml up --build
```

* UI: http://localhost:8080
* API docs: http://localhost:8000/docs

Configuration comes from `deploy/.env.example`. **Change `FINOPS_JWT_SECRET` and the bootstrap admin password
before the stack is reachable by anyone else.** Migrations run once in the `migrate` service, and the worker
runs separately from the API.

## 3. Local Kubernetes (kind)

One script creates the cluster and installs everything:

```powershell
.\deploy\scripts\up.ps1            # Windows
./deploy/scripts/up.sh             # Linux / macOS
```

It runs these steps:

1. Creates the kind cluster `kubefinops`: 4 nodes with AWS-like labels (instance types, zones, one spot node).
2. Installs kube-prometheus-stack 65.8.1 (Prometheus, kube-state-metrics, node-exporter).
3. Builds the server, UI and agent images and side-loads them into kind (`-SkipBuild` to reuse them).
4. Installs `finops-server`: bundled TimescaleDB, API, worker and UI.
5. Registers the cluster and installs `finops-agent` with its token, with remediation enabled.
6. Deploys demo workloads, each a real problem the platform should find:

| Workload | Namespace | What KubeFinOps should find |
| :--- | :--- | :--- |
| `checkout-api` | shop | over-provisioned: right-sizing recommendation |
| `web` + `loadgen` | shop | a normally loaded service (control) |
| `report-generator` | data | idle workload: scale to 0 |
| `cpu-batch` | data | CPU-throttled on a spot node: the censoring correction raises CPU |
| `recommender` | ml | memory leak, OOM-killed: memory raised, reductions blocked |
| `old-export` (PVC) | data | orphaned volume |
| `legacy-public` (Service) | shop | LoadBalancer without endpoints |

Open it with port-forwards:

```bash
kubectl -n finops port-forward svc/finops-server-ui 8080:80          # http://localhost:8080
kubectl -n finops port-forward svc/finops-server-api 8000:8000       # http://localhost:8000/docs
```

* Sign in with the local-only account in `deploy/kind/server-values.yaml`.
* Real data appears after about 15 minutes, and right-sizing needs a few hours of history to become confident.
  The synthetic `demo-aws-prod` cluster is kept alongside for a full picture straight away.
* Tear down with `kind delete cluster --name kubefinops`.

## 4. Production (EKS / GKE / AKS / on-prem)

### Server (once)

Images are published by CI to GHCR:

* `ghcr.io/vedant-0789/kubefinops-{server,ui,agent}`
* tags: `latest` and `sha-<commit>` from main; `X.Y.Z` and `X.Y` for a `vX.Y.Z` git tag

The charts default to their `appVersion`. To use your own registry, override `image.*`.

```bash
kubectl create namespace finops
kubectl -n finops create secret generic finops-server-secrets \
  --from-literal=FINOPS_DATABASE_URL='postgresql+psycopg://finops:<password>@<host>:5432/finops' \
  --from-literal=FINOPS_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  --from-literal=FINOPS_BOOTSTRAP_ADMIN_EMAIL='finops-admin@your-company.com' \
  --from-literal=FINOPS_BOOTSTRAP_ADMIN_PASSWORD='<initial password, change after first login>'

helm upgrade --install finops-server deploy/helm/finops-server -n finops \
  --set secrets.existingSecret=finops-server-secrets \
  --set database.bundled.enabled=false \
  --set ingress.enabled=true --set ingress.className=nginx --set ingress.host=finops.your-company.com \
  --set serviceMonitor.enabled=true
```

* **Database**: PostgreSQL 14+ with the TimescaleDB extension: Timescale Cloud, self-hosted, or the bundled
  StatefulSet (`database.bundled.enabled=true`, fine for evaluation). Migrations run in an init container,
  serialised by an advisory lock, so rolling upgrades are safe with several API replicas.
* **HA**: 2 API replicas with an HPA and a PDB, 2 UI replicas, 1 worker. The pods run non-root with a read-only
  root filesystem.
* **JWT secret**: if you leave it empty, the chart generates it once and keeps it across upgrades.

### Agent (per cluster)

1. Register the cluster. In the UI, go to **Clusters → Register cluster**; the token is shown once, together
   with the Helm command. Or use the API:

   ```bash
   curl -X POST https://finops.your-company.com/api/v1/clusters -H "Authorization: Bearer <admin JWT>" \
        -H 'Content-Type: application/json' -d '{"name":"prod-eu","provider":"aws","region":"eu-central-1"}'
   ```

2. Install the agent in that cluster. It needs Prometheus with cAdvisor and kube-state-metrics, for example
   kube-prometheus-stack:

   ```bash
   helm upgrade --install finops-agent deploy/helm/finops-agent -n finops --create-namespace \
     --set agent.serverUrl=https://finops.your-company.com \
     --set agent.token=<token> \
     --set agent.prometheusUrl=http://prometheus-operated.monitoring:9090
   ```

The agent is read-only by default. To let KubeFinOps apply approved changes, add
`--set rbac.allowRemediation=true`. Changes still require a dry-run, approval by a second operator and the
change window.

### Node pricing

| Environment | Where node prices come from |
| :--- | :--- |
| EKS / Karpenter / GKE / AKS | Read from standard node labels: instance type, zone, capacity type |
| On-prem / custom | Label nodes with `finops.io/hourly-price=<USD per hour>`, or set custom rates per cluster |
| Simulated clusters (kind) | `finops.io/capacity-cpu` / `finops.io/capacity-memory` override the reported capacity |

## Configuration reference

All server settings are environment variables with the `FINOPS_` prefix (`backend/app/core/config.py`). In
Helm, plain settings go in `config:` and secrets in `secrets:` or `existingSecret`.

| Variable | Default | Meaning |
| :--- | :--- | :--- |
| `FINOPS_DATABASE_URL` | `sqlite:///./finops.db` | SQLAlchemy URL; use PostgreSQL + TimescaleDB in production |
| `FINOPS_AUTH_REQUIRED` | `true` | Require sign-in (only tests turn it off) |
| `FINOPS_JWT_SECRET` | – | Required in `prod` |
| `FINOPS_BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` | – | First admin, created only if there are no users |
| `FINOPS_SEED_DEMO_DATA` | `true` | Create the synthetic `demo-aws-prod` cluster (the Helm chart sets `false`) |
| `FINOPS_SHARED_NAMESPACES` | `kube-system,kube-public,kube-node-lease,monitoring` | Shared-cost namespaces |
| `FINOPS_ANALYSIS_WINDOW_DAYS` | `14` | History used for right-sizing and waste |
| `FINOPS_RIGHTSIZING_STRATEGY` | `slo_aware` | `slo_aware`, `vpa` or `p95_buffer` |
| `FINOPS_REQUIRE_TWO_PERSON_APPROVAL` | `true` | Proposer cannot approve their own change |
| `FINOPS_PROTECTED_NAMESPACES` | `kube-system,kube-public,kube-node-lease` | Never changed |
| `FINOPS_CHANGE_WINDOW_UTC` | `00:00-24:00` | e.g. `02:00-06:00`; rollbacks bypass it |
| `FINOPS_REMEDIATION_VERIFY_MINUTES` | `30` | Watch period after a change |
| `FINOPS_ROLLBACK_ON_OOM` / `FINOPS_ROLLBACK_THROTTLE_SHARE` | `true` / `0.25` | Rollback triggers |
| `FINOPS_ANOMALY_THRESHOLD` | `3.5` | Robust z-score for cost anomalies |
| `FINOPS_PUBLIC_URL` | `http://localhost:8080` | Links in notifications |
| `FINOPS_SMTP_*` | – | Email notifications (Slack and webhooks are set up in the UI) |

## Operations

* **Health**: `/healthz` (liveness) and `/readyz` (database). The charts wire both into probes.
* **Metrics**: `/metrics` on the API and the worker (port 9100). Enable `serviceMonitor.enabled` for
  Prometheus Operator.
* **Logs**: JSON with `request_id`. Send `X-Request-ID` to correlate a request with its log lines.
* **Upgrades**: `helm upgrade`; migrations run automatically, once.
* **Backups**: back up the PostgreSQL database. It holds users, history, recommendations and the audit chain.
  Verify the chain after a restore with `GET /api/v1/audit/verify`.

## Troubleshooting

| Symptom | Check |
| :--- | :--- |
| Cluster shows "last seen" long ago | Agent logs: `kubectl -n finops logs deploy/finops-agent-agent`. Token valid? `agent.serverUrl` reachable from the cluster? |
| No usage or cost for real workloads | Agent's `prometheusUrl` correct? Run `container_cpu_usage_seconds_total` and `kube_pod_owner` in Prometheus. |
| All nodes cost the same / $0 | Node labels missing: set `finops.io/hourly-price` or per-cluster custom rates. |
| Right-sizing says "insufficient data" | It needs about a day of history, and full confidence after 7 days. |
| Change stuck in `dry_run_pending` | The agent needs `rbac.allowRemediation=true`, and the change window must be open. |
| Cannot sign in locally | Delete `backend/.env` and the local `finops.db` to start fresh. |
