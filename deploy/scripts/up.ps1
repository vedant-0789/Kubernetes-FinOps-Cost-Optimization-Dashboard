<#
  One-command local environment (Windows / PowerShell):
    kind cluster (4 nodes, AWS-like labels) -> kube-prometheus-stack ->
    build + side-load images -> finops-server -> register cluster ->
    finops-agent -> demo workloads.
  Requirements: Docker Desktop running, kind, helm, kubectl.
  Usage:  .\deploy\scripts\up.ps1 [-SkipBuild]
#>
param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$Root = Resolve-Path "$PSScriptRoot\..\.."
$Cluster = 'kubefinops'
$Ctx = "kind-$Cluster"
$AdminKey = 'kind-local-admin-key'

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Run { & $args[0] $args[1..($args.Count - 1)]; if ($LASTEXITCODE -ne 0) { throw "failed: $args" } }

Step "kind cluster '$Cluster'"
if ((kind get clusters) -notcontains $Cluster) {
    Run kind create cluster --config "$Root\deploy\kind\cluster.yaml" --wait 120s
} else { Write-Host "already exists" }
Run kubectl config use-context $Ctx

Step "kube-prometheus-stack (Prometheus, kube-state-metrics, node-exporter)"
Run helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
Run helm upgrade --install kps prometheus-community/kube-prometheus-stack --version 65.8.1 `
    -n monitoring --create-namespace -f "$Root\deploy\kind\kube-prometheus-values.yaml" --wait --timeout 10m

if (-not $SkipBuild) {
    Step "Build images"
    Run docker build -t kubefinops-server:dev "$Root\backend"
    Run docker build -t kubefinops-ui:dev "$Root\frontend"
    Run docker build -t kubefinops-agent:dev "$Root\agent"
}
Step "Load images into kind"
Run kind load docker-image kubefinops-server:dev kubefinops-ui:dev kubefinops-agent:dev --name $Cluster

Step "finops-server (TimescaleDB, API, worker, UI)"
Run helm upgrade --install finops-server "$Root\deploy\helm\finops-server" -n finops --create-namespace `
    -f "$Root\deploy\kind\server-values.yaml" --wait --timeout 10m
Run kubectl -n finops rollout restart deploy/finops-server-api deploy/finops-server-worker deploy/finops-server-ui
Run kubectl -n finops rollout status deploy/finops-server-api --timeout 5m

Step "Register this cluster"
$token = Get-Content "$Root\deploy\scripts\register_cluster.py" -Raw |
    kubectl -n finops exec -i deploy/finops-server-api -c api -- env FINOPS_ADMIN_API_KEY=$AdminKey python - kind-local aws us-east-1
if ($LASTEXITCODE -ne 0 -or -not $token) { throw "cluster registration failed" }
$token = ($token | Select-Object -Last 1).Trim()

Step "finops-agent"
Run helm upgrade --install finops-agent "$Root\deploy\helm\finops-agent" -n finops `
    --set image.repository=kubefinops-agent --set image.tag=dev --set image.pullPolicy=Never `
    --set agent.serverUrl=http://finops-server-api.finops:8000 `
    --set agent.prometheusUrl=http://prometheus-operated.monitoring:9090 `
    --set agent.backfillHours=1 --set agent.token=$token --set serviceMonitor.enabled=true --wait
Run kubectl -n finops rollout restart deploy/finops-agent-agent

Step "Demo workloads"
Run kubectl apply -f "$Root\deploy\kind\demo-workloads.yaml"

Write-Host "`nDone." -ForegroundColor Green
Write-Host "UI:   kubectl -n finops port-forward svc/finops-server-ui 8080:80      -> http://localhost:8080"
Write-Host "API:  kubectl -n finops port-forward svc/finops-server-api 8000:8000   -> http://localhost:8000/docs (X-Admin-Key: $AdminKey)"
Write-Host "Agent logs: kubectl -n finops logs deploy/finops-agent-agent -f"
Write-Host "Teardown:   kind delete cluster --name $Cluster"
