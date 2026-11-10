# Demo script (about 12 minutes)

A walkthrough for a presentation or viva. It uses the local kind environment (`deploy/scripts/up.ps1`) so
that a real agent, real Prometheus data and real Kubernetes changes are on screen. Everything except
part 6 also works on the quick local setup (`start.ps1`) with the synthetic `demo-aws-prod` cluster.

**Before you start** (at least 2–3 hours earlier, so right-sizing has history):

```powershell
.\deploy\scripts\up.ps1
kubectl -n finops port-forward svc/finops-server-ui 8080:80
```

Sign in at http://localhost:8080. Keep a terminal open with `kubectl get pods -A -w` for part 6.

---

## 1. The problem (1 min)

> Kubernetes bills are paid per node, but teams reserve resources per container. Analyses of production
> traces (Borg, Alibaba) show most reserved capacity is never used. Nobody sees who is wasting what, and
> nobody dares shrink requests because under-provisioning causes outages.

KubeFinOps answers three questions: **who spends what**, **what is wasted**, and **what can safely change**.
Then it changes it safely.

## 2. Architecture (1 min)

Show the diagram in `docs/architecture.md`.

* One agent per cluster, read-only by default, which only pushes data out.
* A central server: API, worker, TimescaleDB, UI.
* Installed with Helm on EKS, GKE, AKS or on-prem; this demo is a 4-node kind cluster with AWS-like nodes,
  including a spot node.

## 3. Overview and cost allocation (2 min)

**Overview**:
* Run rate, idle %, efficiency and the stacked 30-day cost.
* Point at the **cost spike five days ago**: it is a runaway load test, and the anomaly detector found it.

**Cost allocation** (group by *Team (label)*):
* The OpenCost model: containers pay `max(request, usage)`, and unreserved node capacity is shown as **idle**.
* Toggle *Spread shared costs*: `kube-system` and `monitoring` are distributed over the teams.
* Export **Report (PDF)**: a one-page showback for finance. Rows plus shared plus idle reconcile to the bill.

## 4. Forecast, anomalies and budgets (1.5 min)

**Forecast & anomalies**:
* Holt-Winters with weekly seasonality, an 80 % band and a month-end projection.
* Anomalies are days the model did not expect, so cheap weekends are not flagged.

**Budgets**:
* Create one: team `payments`, $100/month, thresholds 80 % / 100 %.
* It also alerts when the *forecast* will exceed the budget, while there is still time to act.

## 5. Waste and right-sizing (2.5 min)

**Waste**:
* An idle `report-generator`, the orphaned `old-export` volume, and the `legacy-public` LoadBalancer with no
  endpoints.
* Idle workloads are not right-sized as well, so savings never double count.

**Right-sizing**: open `shop/checkout-api` (over-provisioned):
* The chart shows hourly peaks against the current and recommended request.
* **Why**: the request is the p99 of *peak* CPU plus headroom from day-to-day variability. That is the
  SLO-aware method: the user chooses the risk (ε = 1 %), and the method picks the smallest safe request.
* Compare tab: VPA-style and p95+20 % recommend less, but would have been exceeded more often.

Then open `ml/recommender` (memory leak):
* OOM kills are shown; the recommendation **raises** memory and blocks reductions. This appears as a
  *reliability fix* that costs money.

## 6. Safe remediation, live (2.5 min)

1. On `shop/checkout-api`, click **Propose this change**. The agent runs a **server-side dry-run** in the
   cluster, and the diff appears.
2. Show that the proposer **cannot approve** their own change (two-person rule). Sign in as a second operator
   (create one in *Users*) and approve.
3. The agent applies it inside the change window. In the terminal, the pods roll with the new requests:
   `kubectl -n shop get deploy checkout-api -o jsonpath='{.spec.template.spec.containers[0].resources}'`.
4. After the watch period (5 min on kind) the change is **verified**.
5. **Rollback story**: approve a downsize of `ml/recommender` memory. The leak hits the new limit, the pod is
   OOM-killed, and the platform **rolls back automatically** to the captured spec. Show the timeline on the
   action.
6. **Audit log**: every step is hash-chained. Click **Verify chain**.

Mention GitOps: every action can be downloaded as a kustomize patch instead of being applied directly.

## 7. The research (1.5 min)

Show `research/paper/figures/pareto_alibaba.png`.

* The same right-sizing code was replayed on **2,037 production containers from Alibaba's cluster trace**.
  * SLO-aware saves 63.8 % of requested cost at 0.39 % CPU under-provisioning.
  * p95+20 % saves 77.5 % at 3.2 %, and VPA-style 80.0 % at 7.9 %: 8 to 20 times more often short of CPU.
* ε is an honest knob: for targets of 0.5–5 %, the realised under-provisioning stays below the target.
* The replay also found two bugs in the engine (a compounding censoring correction and an unfair VPA baseline),
  which were fixed in the product.

## 8. Engineering quality (30 s)

* About 250 automated tests (backend on SQLite and TimescaleDB, agent, UI, simulator), CI with lint, Helm lint
  and image builds.
* Non-root, read-only containers; a read-only agent by default; hashed tokens and passwords; a tamper-evident
  audit log.

---

### Likely questions

* **Why not just use VPA?** VPA has no cost view and optimises a fixed percentile; it does not use OOM kills or
  throttling as evidence that demand is higher than observed. Its in-place updates also restart pods without
  approvals. KubeFinOps adds the cost model, an explicit risk target, approvals and rollback.
* **How is it different from Kubecost/OpenCost?** The allocation model is OpenCost-compatible. The additions are
  the SLO-aware recommender, guarded remediation with auto-rollback, and the research evaluation.
* **What about multiple clusters?** One agent per cluster, each with its own token; one server. The UI has a
  cluster switcher.
* **Does it scale?** The API is stateless with an HPA. Usage lives in TimescaleDB hypertables with compression.
  The next step is continuous aggregates for clusters with tens of thousands of containers.
* **Is it safe to give it write access?** Write access is opt-in. Every change is dry-run, approved by a second
  person, limited to a change window and protected namespaces, and rolled back automatically on regressions.
