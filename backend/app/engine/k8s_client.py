import os
import logging
from sqlalchemy.orm import Session
from app.db.models import ActionLog, MetricsSnapshot
import datetime

logger = logging.getLogger("k8s_client")

class K8sClient:
    """
    Unified Kubernetes operational client.
    Attempts real Kubernetes API connection if available and MOCK_MODE is false;
    otherwise executes simulated state changes.
    """
    
    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode
        self.k8s_available = False
        
        if not self.mock_mode:
            try:
                from kubernetes import client, config
                try:
                    config.load_incluster_config()
                except Exception:
                    config.load_kube_config()
                self.apps_v1 = client.AppsV1Api()
                self.core_v1 = client.CoreV1Api()
                self.k8s_available = True
                logger.info("Successfully connected to live Kubernetes cluster API.")
            except Exception as e:
                logger.warning(f"Failed to connect to live K8s cluster: {e}. Falling back to mock execution.")
                self.k8s_available = False

    def scale_deployment(self, namespace: str, deployment_name: str, replicas: int, db: Session) -> dict:
        """
        Scales a deployment down (or to 0 for zombie cleanup).
        """
        success = True
        msg = f"Scaled deployment {deployment_name} in namespace {namespace} to {replicas} replicas."
        
        if not self.mock_mode and self.k8s_available:
            try:
                body = {"spec": {"replicas": replicas}}
                self.apps_v1.patch_namespaced_deployment_scale(
                    name=deployment_name, namespace=namespace, body=body
                )
            except Exception as e:
                success = False
                msg = f"Live K8s scaling failed: {str(e)}"
        
        # In mock mode or after live execution, update database snapshots
        if success:
            snaps = db.query(MetricsSnapshot).filter(
                MetricsSnapshot.namespace == namespace,
                MetricsSnapshot.pod_name.like(f"{deployment_name}%")
            ).all()
            for snap in snaps:
                if replicas == 0:
                    snap.cpu_usage = 0.0
                    snap.mem_usage_mb = 0.0
                    snap.cpu_req = 0.0
                    snap.mem_req_mb = 0.0
                    snap.hourly_cost = 0.0
                    snap.monthly_cost = 0.0
            db.commit()
            
        return {"success": success, "message": msg}

    def patch_resource_requests(self, namespace: str, workload_name: str, new_cpu_req: float, new_mem_req_mb: float, db: Session) -> dict:
        """
        Patches container resource requests for right-sizing.
        """
        success = True
        msg = f"Patched resource requests for {workload_name} in {namespace} (CPU: {new_cpu_req} vCPU, Memory: {new_mem_req_mb} MB)."
        
        if not self.mock_mode and self.k8s_available:
            try:
                patch_body = {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [{
                                    "name": workload_name,
                                    "resources": {
                                        "requests": {
                                            "cpu": f"{int(new_cpu_req * 1000)}m",
                                            "memory": f"{int(new_mem_req_mb)}Mi"
                                        }
                                    }
                                }]
                            }
                        }
                    }
                }
                self.apps_v1.patch_namespaced_deployment(
                    name=workload_name, namespace=namespace, body=patch_body
                )
            except Exception as e:
                success = False
                msg = f"Live K8s patch failed: {str(e)}"

        if success:
            snaps = db.query(MetricsSnapshot).filter(
                MetricsSnapshot.namespace == namespace,
                MetricsSnapshot.pod_name.like(f"{workload_name}%")
            ).all()
            for snap in snaps:
                snap.cpu_req = new_cpu_req
                snap.mem_req_mb = new_mem_req_mb
                # Recalculate cost
                from app.engine.cost_calculator import CostCalculator
                c_info = CostCalculator.calculate_pod_cost(
                    new_cpu_req, snap.cpu_usage, new_mem_req_mb, snap.mem_usage_mb, 0.048, 0.006
                )
                snap.hourly_cost = c_info["hourly_cost"]
                snap.monthly_cost = c_info["monthly_cost"]
                snap.efficiency_pct = c_info["efficiency_pct"]
            db.commit()
            
        return {"success": success, "message": msg}
