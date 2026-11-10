#!/usr/bin/env bash
# One-command local environment (Linux / macOS / CI). See up.ps1 for Windows.
# Requirements: docker, kind, helm, kubectl.   Usage: deploy/scripts/up.sh [--skip-build]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CLUSTER=kubefinops
ADMIN_KEY=kind-local-admin-key
step() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }

step "kind cluster '$CLUSTER'"
kind get clusters | grep -qx "$CLUSTER" || kind create cluster --config "$ROOT/deploy/kind/cluster.yaml" --wait 120s
kubectl config use-context "kind-$CLUSTER"

step "kube-prometheus-stack"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
helm upgrade --install kps prometheus-community/kube-prometheus-stack --version 65.8.1 \
  -n monitoring --create-namespace -f "$ROOT/deploy/kind/kube-prometheus-values.yaml" --wait --timeout 10m

if [[ "${1:-}" != "--skip-build" ]]; then
  step "Build images"
  docker build -t kubefinops-server:dev "$ROOT/backend"
  docker build -t kubefinops-ui:dev "$ROOT/frontend"
  docker build -t kubefinops-agent:dev "$ROOT/agent"
fi
step "Load images into kind"
kind load docker-image kubefinops-server:dev kubefinops-ui:dev kubefinops-agent:dev --name "$CLUSTER"

step "finops-server"
helm upgrade --install finops-server "$ROOT/deploy/helm/finops-server" -n finops --create-namespace \
  -f "$ROOT/deploy/kind/server-values.yaml" --wait --timeout 10m
kubectl -n finops rollout restart deploy/finops-server-api deploy/finops-server-worker deploy/finops-server-ui
kubectl -n finops rollout status deploy/finops-server-api --timeout 5m

step "Register this cluster"
TOKEN=$(kubectl -n finops exec -i deploy/finops-server-api -c api -- \
  env FINOPS_ADMIN_API_KEY="$ADMIN_KEY" python - kind-local aws us-east-1 < "$ROOT/deploy/scripts/register_cluster.py" | tail -n1)
[[ -n "$TOKEN" ]] || { echo "cluster registration failed" >&2; exit 1; }

step "finops-agent"
helm upgrade --install finops-agent "$ROOT/deploy/helm/finops-agent" -n finops \
  --set image.repository=kubefinops-agent --set image.tag=dev --set image.pullPolicy=Never \
  --set agent.serverUrl=http://finops-server-api.finops:8000 \
  --set agent.prometheusUrl=http://prometheus-operated.monitoring:9090 \
  --set agent.backfillHours=1 --set agent.token="$TOKEN" --set serviceMonitor.enabled=true --set rbac.allowRemediation=true --wait
kubectl -n finops rollout restart deploy/finops-agent-agent

step "Demo workloads"
kubectl apply -f "$ROOT/deploy/kind/demo-workloads.yaml"

cat <<EOF

Done.
UI:   kubectl -n finops port-forward svc/finops-server-ui 8080:80      -> http://localhost:8080
API:  kubectl -n finops port-forward svc/finops-server-api 8000:8000   -> http://localhost:8000/docs (X-Admin-Key: $ADMIN_KEY)
Agent logs: kubectl -n finops logs deploy/finops-agent-agent -f
Teardown:   kind delete cluster --name $CLUSTER
EOF
