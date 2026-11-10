# Project summary

## One paragraph

KubeFinOps is an open-source, multi-cluster Kubernetes cost-optimisation platform:
* An in-cluster agent sends inventory and Prometheus usage to a central FastAPI and TimescaleDB server.
* The server allocates cost with the OpenCost model, including idle and shared cost.
* It finds waste and recommends container requests with an **SLO-aware right-sizing method**, whose risk target
  is explicit.
* It forecasts spend and detects anomalies.
* It applies changes through server-side dry-run, two-person approval and automatic rollback.

It installs with Helm on any Kubernetes cluster. In a trace-driven evaluation on 2,037 production containers
from Alibaba's cluster trace, the right-sizing method removed 64 % of requested cost while being short of CPU
8–20× less often than p95 and VPA-style baselines.

## Key numbers

| | |
| :--- | :--- |
| Code | ~7.6k lines Python (server + agent), ~2k lines React, ~0.8k lines research, ~1.2k lines Helm/deploy |
| Tests | ~250 automated: backend 170 (SQLite and TimescaleDB), agent 46, UI 15, simulator 18 |
| Deploy | 2 Helm charts, docker compose, one-command 4-node kind environment with Prometheus |
| Real-trace result | 63.8 % savings at 0.39 % CPU under-provisioning (vs 77.5 % / 3.2 % and 80.0 % / 7.9 %) |
| Synthetic result | 41.4 % savings, 0.47 % under-provisioning, 0 OOM (VPA-style: 18.8 %, 67 OOM) |

## CV bullets

Pick 3–4. They are written to be verifiable from the repository.

* Built **KubeFinOps**, a multi-cluster Kubernetes FinOps platform: a Python in-cluster agent, a FastAPI +
  TimescaleDB backend, a React UI and Helm charts. It does OpenCost-compatible cost allocation (idle and shared
  cost, spot/on-demand pricing for AWS, GCP and Azure) and showback reports.
* Designed an **SLO-aware right-sizing algorithm**: a risk-targeted quantile of peak demand, variability
  headroom, censoring correction for CPU throttling, and OOM and memory-leak feedback. On **2,037 Alibaba
  production containers** it cut requested cost by **64 %** with 8–20× fewer CPU shortfalls than VPA-style and
  p95 baselines. Wrote it up as an IEEE-format paper.
* Implemented **safe automated remediation**: server-side dry-run, two-person approval, change windows,
  post-change verification against OOM kills, restarts and throttling, and **automatic rollback**. Every step
  goes to a SHA-256 hash-chained audit log, and changes can be exported as GitOps patches.
* Added **spend forecasting** (Holt-Winters with weekly seasonality), **cost anomaly detection** (robust z-score
  of forecast errors) and **budgets** with Slack, webhook and email alerts.
* Production engineering: JWT auth with RBAC, hashed agent tokens, non-root read-only containers, Prometheus
  metrics, JSON logs with request IDs, Alembic migrations, and an HPA and PDB. About 250 automated tests and
  GitHub Actions CI (lint, Postgres integration tests, Helm lint, multi-image builds to GHCR).
* Built a **trace-replay simulator** that evaluates the production right-sizing code itself. It found and fixed
  two engine bugs, including a compounding censoring correction, before they reached users.

**Short version** (one line): *KubeFinOps – Kubernetes cost platform (FastAPI, TimescaleDB, React, Helm) with an
SLO-aware right-sizing method that cut requested cost by 64 % on Alibaba production traces with 8–20× fewer
CPU shortfalls than VPA-style baselines; safe remediation with approval and auto-rollback.*

**Skills shown**: Kubernetes (operators' view: RBAC, Helm, HPA/PDB, dry-run, strategic-merge patches),
Prometheus/PromQL, Python/FastAPI, SQLAlchemy/Alembic, PostgreSQL/TimescaleDB, React, Docker, GitHub Actions,
time-series forecasting, robust statistics, experimental evaluation.

## Presenting it as a team (4 areas)

The project splits naturally into four areas of similar size, one per presenter:

| Area | What to present | Where in the repo |
| :--- | :--- | :--- |
| Data collection & deployment | Agent, Prometheus queries, Helm charts, kind environment, CI | `agent/`, `deploy/`, `.github/` |
| Cost engine & finance | Allocation model, pricing catalogs, forecasting, anomalies, budgets, reports | `backend/app/engines/allocation.py`, `forecast.py`, `services/finance.py`, `services/reports.py` |
| Optimisation & safe remediation | Right-sizing, waste detection, approval workflow, rollback, audit | `backend/app/engines/rightsizing.py`, `waste.py`, `services/remediation.py`, `services/audit.py` |
| UI & research | Dashboard walkthrough, replay simulator, Alibaba evaluation, paper | `frontend/`, `research/` |

## Publishing the paper

`research/paper/main.tex` (IEEEtran) is complete apart from the author names and affiliations (the red
`	odo{}` marks). Build it on Overleaf, or locally with
`latexmk -pdf -cd research/paper/main.tex`. Suitable venues are workshop or short-paper tracks on cloud and
systems: for example IEEE CLOUD workshops, ACM SoCC posters, IEEE/ACM UCC, or a regional IEEE conference.
