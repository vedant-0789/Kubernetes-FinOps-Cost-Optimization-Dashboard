# Kubernetes FinOps & Cost-Optimization Dashboard

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18.2+-61dafb.svg)](https://react.dev)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind-3.4+-38bdf8.svg)](https://tailwindcss.com)
[![OpenCost](https://img.shields.io/badge/FinOps-OpenCost%20Model-10b981.svg)](https://www.opencost.io)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-API%20Client-326ce5.svg)](https://kubernetes.io)

A full-stack, production-grade **Kubernetes FinOps & Cost-Optimization Dashboard** built to monitor cluster resource usage, estimate cloud costs per namespace and pod using OpenCost allocation models, automatically detect idle/"zombie" workloads, generate p95 right-sizing recommendations, and execute automated waste remediation.

Designed as a Cloud Computing course project demonstrating a closed-loop FinOps workflow: converting raw Kubernetes cAdvisor / Prometheus metrics into real financial visibility and automated waste elimination.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph K8sTelemetry [Data & Metric Ingestion]
        MockStream[Synthetic K8s Cluster Metrics Stream]
        RealK8s[Live Kubernetes API + Prometheus]
    end

    subgraph BackendCore [FastAPI Python Backend - Port 8000]
        Scheduler[APScheduler Continuous Telemetry Collector]
        CostEngine[OpenCost Allocation Formula Engine]
        ZombieDetector[Zombie Workload Detector Engine]
        RightSizer[Right-Sizing Engine - p95 + 20% Safety Buffer]
        RemediationEngine[Remediation Handler - Scale to 0 / Patch Requests]
        SQLite[(SQLite Database - finops.db)]
    end

    subgraph APIEndpoints [REST API Layer]
        API_Overview[GET /api/overview & /api/cost-trend]
        API_NS[GET /api/namespaces & pods]
        API_Zombies[GET /api/zombies & POST remediate]
        API_Recs[GET /api/recommendations & POST apply]
        API_History[GET /api/actions/history]
        API_Lifecycle[GET /api/lifecycle]
        API_Settings[GET/POST /api/settings]
    end

    subgraph FrontendUI [React + Tailwind SaaS Dashboard - Port 5173]
        OverviewPage[Cluster Overview & Financial Highlights]
        NamespacePage[Namespace Cost Attribution]
        ZombiePage[Zombie Workload Cleanup Engine]
        RightSizingPage[p95 Pod Right-Sizing]
        AuditPage[Remediation Action Audit Log]
        LifecyclePage[FinOps 7-Stage Stepper View]
        SettingsPage[Pricing & Policy Config]
    end

    MockStream -->|Mock Mode| Scheduler
    RealK8s -->|Real Mode| Scheduler
    Scheduler --> CostEngine
    CostEngine --> SQLite
    CostEngine --> ZombieDetector
    CostEngine --> RightSizer
    ZombieDetector --> SQLite
    RightSizer --> SQLite

    SQLite <--> API_Overview & API_NS & API_Zombies & API_Recs & API_History & API_Lifecycle & API_Settings
    API_Zombies --> RemediationEngine
    API_Recs --> RemediationEngine
    RemediationEngine --> RealK8s
    RemediationEngine --> SQLite

    APIEndpoints <--> FrontendUI
```

---

## 🎯 Key Features

1. **Dual Execution Mode (Mock vs Live K8s Cluster)**:
   - **Mock Mode (Default)**: Out-of-the-box synthetic telemetry stream with 8 namespaces (`frontend-prod`, `backend-api`, `payments-service`, `ml-training-job`, `logging-stack`, `monitoring`, `analytics-worker`, `staging-zombies`), 22+ pods, and 30 days of pre-seeded trend data.
   - **Real Mode**: Connects directly to a live Kubernetes cluster using `kubectl` / `kubernetes` Python SDK and Prometheus queries.

2. **OpenCost Financial Cost Modeling**:
   - Calculates resource cost allocation using configurable hourly unit rates:
     $$\text{Hourly Cost} = \max(\text{CPU Req}, \text{CPU Usage}) \times \text{CPU Rate} + \max(\text{RAM Req GB}, \text{RAM Usage GB}) \times \text{RAM Rate}$$
     $$\text{Monthly Run Rate} = \text{Hourly Cost} \times 730\text{ hours}$$

3. **Zombie Workload Detection**:
   - Continuous background rule engine flagging workloads with sustained $\le 5\%$ CPU utilization and zero/low network IO for over 24 hours.
   - Dedicated Zombie Workloads page with one-click "Scale Deployment to 0 Replicas" remediation.

4. **Right-Sizing Recommendation Engine**:
   - Computes optimal CPU and RAM requests based on historical **p95 peak utilization + 20% safety margin**.
   - Calculates exact monthly financial savings ($/mo) per workload.
   - "Apply Recommendation" patches container resource requests via the K8s API or updates mock telemetry.

5. **Automated Remediation & Audit Log**:
   - Safety guardrail: Manual confirmation required by default (with toggle for Auto-Apply low-risk recommendations in Settings).
   - Permanent audit log tracking executed actions, timestamps, before/after metrics, and realized monthly savings.

6. **FinOps 7-Stage Lifecycle View**:
   - Visual stepper illustrating the 7 operational stages: **Observe → Measure → Attribute → Detect → Recommend → Optimize → Verify**.

---

## 🚧 v2 platform (in progress)

The project is being rebuilt into a deployable, multi-cluster FinOps platform
(TimescaleDB, in-cluster agent, Helm charts, SLO-aware right-sizing). Already in place:

- **API v1** under `/api/v1/*`, health probes `/healthz` & `/readyz`, Prometheus metrics at `/metrics`, request-ID tracing.
- **Database migrations** with Alembic (`backend/migrations`); PostgreSQL/TimescaleDB in production, SQLite for local dev.
- **Separate worker** process (`python -m app.worker`) so API replicas scale horizontally.
- **Containers**: `backend/Dockerfile` (non-root, healthcheck), `frontend/Dockerfile` (unprivileged nginx).
- **Tests & CI**: `pytest` suite run on SQLite and TimescaleDB, `ruff` lint, image builds to GHCR.

```bash
# Full stack in Docker (UI on :8080, API docs on :8000/docs)
docker compose -f deploy/docker-compose.yml up --build

# Backend tests
cd backend && pip install -r requirements-dev.txt && ruff check . && pytest
```

All settings are environment variables prefixed with `FINOPS_` (see `backend/app/core/config.py`).

### Multi-cluster ingestion & cost allocation (M1)

Each cluster is registered once and gets an agent token (only its SHA-256 hash is stored):

```bash
curl -X POST localhost:8000/api/v1/clusters -H 'Content-Type: application/json' \
     -d '{"name": "prod-eu", "provider": "aws", "region": "eu-central-1"}'   # -> agent_token, shown once
```

| Method | Endpoint | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/ingest/inventory` | Agent: nodes (instance type, spot/on-demand, creation time) and workload owners with labels |
| `POST` | `/api/v1/ingest/samples` | Agent: 5-minute container usage samples + node heartbeats (idempotent) |
| `GET` | `/api/v1/clusters/{id}/summary` | Run rate, idle %, efficiency, spot share |
| `GET` | `/api/v1/clusters/{id}/allocation?window=7d&aggregate=label:team&shared=distribute` | Showback/chargeback by `namespace`, `workload`, `node`, `pod` or any label |
| `GET` | `/api/v1/clusters/{id}/cost-timeseries?window=30d&step=1d` | Daily/hourly cost by top namespaces, plus idle |

**How cost is allocated** (OpenCost-compatible): each node's hourly price comes from the agent, per-cluster
custom rates, or the AWS/GCP/Azure catalogs in `backend/app/pricing/catalogs` (region multipliers, spot discount),
and is split into per-core and per-GiB prices. Containers pay for `max(request, usage)`; capacity nobody
reserved is reported as **idle cost**; `kube-system`/`monitoring` are **shared cost**, shown separately or
spread over teams. Node heartbeats make autoscaled and spot nodes cost only while they run. Container cost +
idle cost always reconciles to the node bill (tested).

### In-cluster agent, Helm charts & local Kubernetes (M2)

- **`agent/`** – a stateless Python agent (one Deployment per cluster, read-only RBAC). Every 5 minutes it reads
  inventory from the Kubernetes API (node instance type / zone / spot labels from EKS, Karpenter, GKE, AKS;
  workload owners and labels) and usage from Prometheus (cAdvisor + kube-state-metrics: CPU mean/peak, working
  set, throttling, network, restarts, OOM kills, Pod→ReplicaSet→Deployment and Job→CronJob ownership), then
  pushes both to the server with retries. On restart it re-sends a back-fill window; the server de-duplicates.
- **`deploy/helm/finops-server`** – API (+ HPA, PDB, migration init container serialised by a PostgreSQL
  advisory lock), single worker, UI, optional bundled TimescaleDB, Ingress, ServiceMonitor; non-root,
  read-only root filesystem, dropped capabilities.
- **`deploy/helm/finops-agent`** – agent with a read-only ClusterRole (no Secrets/ConfigMaps); write verbs only
  with `rbac.allowRemediation=true`.
- Node labels the agent understands beyond the cloud defaults: `finops.io/hourly-price` (explicit price, e.g.
  on-prem) and `finops.io/capacity-cpu` / `finops.io/capacity-memory` (simulated clusters such as kind, whose
  nodes all report the host's full capacity).

One command builds everything and runs it on a local 4-node kind cluster (AWS-like node labels incl. a spot
node), with kube-prometheus-stack and real demo workloads (over-provisioned API, idle deployment, CPU-throttled
batch on spot, a memory leak that gets OOM-killed, an orphaned PVC, a LoadBalancer with no endpoints):

```powershell
.\deploy\scripts\up.ps1          # Windows   (Linux/macOS: deploy/scripts/up.sh)
kubectl -n finops port-forward svc/finops-server-api 8000:8000   # http://localhost:8000/docs
```

The same charts install on EKS/GKE/AKS: point `secrets.databaseUrl` at a managed PostgreSQL with TimescaleDB,
set `secrets.adminApiKey`, enable `ingress`, and install `finops-agent` in each cluster with its own token.

The built-in demo cluster `demo-aws-prod` (6 nodes incl. spot and a weekday-peak autoscaled node, 12 workloads,
14 days of 5-minute history) is generated through the same ingestion code an agent uses.

## ⚡ Quick Start Guide

### Prerequisites
- Python 3.10+
- Node.js 18+
- npm or yarn

### Option 1: One-Click Startup (Windows)
Double-click `start.bat` or run in PowerShell:
```powershell
.\start.ps1
```

### Option 2: Manual Terminal Startup

#### 1. Launch FastAPI Backend
```bash
cd backend
python -m pip install -r requirements.txt
python run_backend.py
```
- **Backend API**: `http://127.0.0.1:8000`
- **Swagger Documentation**: `http://127.0.0.1:8000/docs`

#### 2. Launch React Frontend
Open a new terminal:
```bash
cd frontend
npm install
npm run dev
```
- **Frontend Dashboard**: `http://localhost:5173`

---

## 🔌 API Endpoints Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/overview` | Cluster summary statistics & key metrics |
| `GET` | `/api/cost-trend?range=7d|30d` | Time-series cost data points |
| `GET` | `/api/namespaces` | List of namespaces with cost attribution & efficiency scores |
| `GET` | `/api/namespaces/{name}/pods` | Detailed pod metrics for a specific namespace |
| `GET` | `/api/zombies` | List of flagged idle/zombie workloads |
| `POST` | `/api/zombies/{id}/remediate` | Remediate zombie workload (scale deployment to 0 replicas) |
| `GET` | `/api/recommendations` | Active p95 right-sizing recommendations |
| `POST` | `/api/recommendations/{id}/apply` | Apply right-sizing patch to container requests |
| `GET` | `/api/actions/history` | Remediation audit trail & realized savings log |
| `GET` | `/api/lifecycle` | 7-stage FinOps lifecycle summary mapping |
| `GET/POST` | `/api/settings` | Read or update hourly cloud pricing & threshold policies |

---

## 🌐 Connecting to a Real Cluster

To switch from Mock Mode to a Live Kubernetes Cluster:
1. Ensure your local `~/.kube/config` file is configured for your cluster (e.g. Minikube, EKS, GKE, or Kind).
2. On the **Settings** page in the dashboard UI (or via `.env`), uncheck **Simulated Mock Data Mode**.
3. The backend will automatically initialize the official `kubernetes` Python client to query live pods and patch deployment specifications.

---

## 📜 License
Developed as an academic Cloud Computing FinOps course project. Open-source under the MIT License.
