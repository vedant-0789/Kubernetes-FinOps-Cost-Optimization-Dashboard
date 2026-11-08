"""KubeFinOps in-cluster agent.

Runs as a single Deployment per cluster with read-only RBAC. Every 5 minutes
it reads inventory from the Kubernetes API and usage from Prometheus
(cAdvisor + kube-state-metrics), then pushes both to the central server.
It holds no state: on restart it re-sends a back-fill window and the server
discards duplicates.
"""

__version__ = "2.0.0"
