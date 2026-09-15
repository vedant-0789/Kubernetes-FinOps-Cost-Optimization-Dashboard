import random
import datetime
from sqlalchemy.orm import Session
from app.db.models import MetricsSnapshot, ZombieWorkload, Recommendation, ActionLog, SystemSetting
from app.engine.cost_calculator import CostCalculator

NAMESPACES = [
    {"name": "frontend-prod", "stage": "Attribute", "pods_count": 4},
    {"name": "backend-api", "stage": "Measure", "pods_count": 4},
    {"name": "payments-service", "stage": "Recommend", "pods_count": 3},
    {"name": "ml-training-job", "stage": "Attribute", "pods_count": 2},
    {"name": "logging-stack", "stage": "Observe", "pods_count": 3},
    {"name": "monitoring", "stage": "Observe", "pods_count": 2},
    {"name": "analytics-worker", "stage": "Recommend", "pods_count": 2},
    {"name": "staging-zombies", "stage": "Detect", "pods_count": 3},
]

POD_PRESETS = [
    # Well-utilized prod pods
    {"ns": "frontend-prod", "name": "frontend-ui-7d9f8b4c-12a1", "cpu_req": 1.0, "cpu_usage": 0.78, "mem_req": 2048, "mem_usage": 1720, "net_rx": 450, "net_tx": 890, "type": "Deployment"},
    {"ns": "frontend-prod", "name": "frontend-ui-7d9f8b4c-98b4", "cpu_req": 1.0, "cpu_usage": 0.71, "mem_req": 2048, "mem_usage": 1650, "net_rx": 410, "net_tx": 830, "type": "Deployment"},
    {"ns": "frontend-prod", "name": "cdn-edge-router-54c12d-a11f", "cpu_req": 0.5, "cpu_usage": 0.42, "mem_req": 1024, "mem_usage": 890, "net_rx": 1200, "net_tx": 2400, "type": "DaemonSet"},
    {"ns": "frontend-prod", "name": "web-cache-redis-0", "cpu_req": 2.0, "cpu_usage": 1.65, "mem_req": 4096, "mem_usage": 3580, "net_rx": 900, "net_tx": 1100, "type": "StatefulSet"},

    # Over-provisioned backend pods
    {"ns": "backend-api", "name": "auth-service-6b4d91-x99a", "cpu_req": 4.0, "cpu_usage": 0.45, "mem_req": 8192, "mem_usage": 1800, "net_rx": 120, "net_tx": 140, "type": "Deployment"},
    {"ns": "backend-api", "name": "auth-service-6b4d91-z23b", "cpu_req": 4.0, "cpu_usage": 0.41, "mem_req": 8192, "mem_usage": 1750, "net_rx": 110, "net_tx": 135, "type": "Deployment"},
    {"ns": "backend-api", "name": "user-profile-api-88f1-c4", "cpu_req": 2.0, "cpu_usage": 0.32, "mem_req": 4096, "mem_usage": 980, "net_rx": 80, "net_tx": 95, "type": "Deployment"},
    {"ns": "backend-api", "name": "search-index-gateway-0", "cpu_req": 4.0, "cpu_usage": 0.88, "mem_req": 8192, "mem_usage": 6200, "net_rx": 650, "net_tx": 910, "type": "StatefulSet"},

    # Over-provisioned payments pods
    {"ns": "payments-service", "name": "stripe-connector-99b-f1", "cpu_req": 2.0, "cpu_usage": 0.18, "mem_req": 4096, "mem_usage": 850, "net_rx": 45, "net_tx": 60, "type": "Deployment"},
    {"ns": "payments-service", "name": "ledger-sync-worker-12a-77", "cpu_req": 4.0, "cpu_usage": 0.35, "mem_req": 16384, "mem_usage": 2400, "net_rx": 120, "net_tx": 180, "type": "Deployment"},
    {"ns": "payments-service", "name": "fraud-risk-eval-0", "cpu_req": 2.0, "cpu_usage": 0.22, "mem_req": 4096, "mem_usage": 1100, "net_rx": 90, "net_tx": 105, "type": "StatefulSet"},

    # ML Training (High Usage)
    {"ns": "ml-training-job", "name": "churn-model-trainer-cuda-0", "cpu_req": 8.0, "cpu_usage": 7.40, "mem_req": 32768, "mem_usage": 29800, "net_rx": 1400, "net_tx": 400, "type": "StatefulSet"},
    {"ns": "ml-training-job", "name": "feature-store-ingest-44a", "cpu_req": 4.0, "cpu_usage": 1.10, "mem_req": 16384, "mem_usage": 4200, "net_rx": 890, "net_tx": 310, "type": "Deployment"},

    # Logging & Monitoring
    {"ns": "logging-stack", "name": "fluentbit-agent-d99", "cpu_req": 0.5, "cpu_usage": 0.28, "mem_req": 512, "mem_usage": 410, "net_rx": 780, "net_tx": 1200, "type": "DaemonSet"},
    {"ns": "logging-stack", "name": "elasticsearch-master-0", "cpu_req": 4.0, "cpu_usage": 2.90, "mem_req": 16384, "mem_usage": 14100, "net_rx": 950, "net_tx": 880, "type": "StatefulSet"},
    {"ns": "logging-stack", "name": "kibana-dashboard-77c", "cpu_req": 1.0, "cpu_usage": 0.35, "mem_req": 2048, "mem_usage": 1150, "net_rx": 150, "net_tx": 320, "type": "Deployment"},

    {"ns": "monitoring", "name": "prometheus-server-0", "cpu_req": 4.0, "cpu_usage": 3.10, "mem_req": 8192, "mem_usage": 6900, "net_rx": 1800, "net_tx": 220, "type": "StatefulSet"},
    {"ns": "monitoring", "name": "grafana-ui-54c-88a", "cpu_req": 0.5, "cpu_usage": 0.15, "mem_req": 1024, "mem_usage": 480, "net_rx": 85, "net_tx": 140, "type": "Deployment"},

    # Analytics overprovisioned
    {"ns": "analytics-worker", "name": "spark-driver-main-99a", "cpu_req": 8.0, "cpu_usage": 0.85, "mem_req": 32768, "mem_usage": 5400, "net_rx": 210, "net_tx": 180, "type": "Deployment"},
    {"ns": "analytics-worker", "name": "clickhouse-analytics-0", "cpu_req": 4.0, "cpu_usage": 1.20, "mem_req": 16384, "mem_usage": 4900, "net_rx": 400, "net_tx": 820, "type": "StatefulSet"},

    # Staging Zombie / Idle Pods
    {"ns": "staging-zombies", "name": "legacy-qa-testbench-77a-99", "cpu_req": 4.0, "cpu_usage": 0.01, "mem_req": 8192, "mem_usage": 120, "net_rx": 0.1, "net_tx": 0.1, "type": "Deployment"},
    {"ns": "staging-zombies", "name": "deprecated-report-worker-22b", "cpu_req": 2.0, "cpu_usage": 0.005, "mem_req": 4096, "mem_usage": 90, "net_rx": 0.0, "net_tx": 0.0, "type": "Deployment"},
    {"ns": "staging-zombies", "name": "temp-loadtest-generator-0", "cpu_req": 4.0, "cpu_usage": 0.02, "mem_req": 8192, "mem_usage": 180, "net_rx": 0.4, "net_tx": 0.2, "type": "Deployment"}
]

class MockDataGenerator:
    """
    Seeds database with initial mock settings, pod metric snapshots, 
    30 days of cost trends, zombie workloads, recommendations, and sample audit history.
    """

    @staticmethod
    def seed_initial_data(db: Session, force: bool = False):
        # Check if already seeded
        if not force and db.query(MetricsSnapshot).first() is not None:
            return

        print("Seeding initial FinOps mock data...")
        
        # 1. Seed System Settings
        default_settings = [
            SystemSetting(key="cpu_hourly_rate", value="0.048", description="Cost per vCPU hour ($)"),
            SystemSetting(key="ram_hourly_rate", value="0.006", description="Cost per GB RAM hour ($)"),
            SystemSetting(key="idle_cpu_threshold_pct", value="5.0", description="Idle CPU threshold (%)"),
            SystemSetting(key="evaluation_window_hours", value="24", description="Evaluation window (hrs)"),
            SystemSetting(key="auto_remediation_enabled", value="false", description="Auto apply low-risk recs"),
            SystemSetting(key="mock_mode", value="true", description="Enable mock mode"),
        ]
        for setting in default_settings:
            existing = db.query(SystemSetting).filter_by(key=setting.key).first()
            if not existing:
                db.add(setting)
        db.commit()

        cpu_rate = 0.048
        ram_rate = 0.006
        now = datetime.datetime.utcnow()

        # 2. Seed Current Metric Snapshots
        for pod in POD_PRESETS:
            cost_info = CostCalculator.calculate_pod_cost(
                pod["cpu_req"], pod["cpu_usage"], pod["mem_req"], pod["mem_usage"], cpu_rate, ram_rate
            )
            snap = MetricsSnapshot(
                timestamp=now,
                namespace=pod["ns"],
                pod_name=pod["name"],
                workload_type=pod["type"],
                cpu_req=pod["cpu_req"],
                cpu_usage=pod["cpu_usage"],
                mem_req_mb=pod["mem_req"],
                mem_usage_mb=pod["mem_usage"],
                net_rx_bytes=pod["net_rx"] * 1024,
                net_tx_bytes=pod["net_tx"] * 1024,
                hourly_cost=cost_info["hourly_cost"],
                monthly_cost=cost_info["monthly_cost"],
                efficiency_pct=cost_info["efficiency_pct"]
            )
            db.add(snap)
            
        # 3. Seed 30 Days of Historical Snapshots for Trend Charting
        for day in range(30, 0, -1):
            historical_time = now - datetime.timedelta(days=day)
            # Add slight fluctuation factor (0.92 to 1.08)
            fluc = random.uniform(0.92, 1.08)
            for pod in POD_PRESETS:
                cpu_u = max(0.01, round(pod["cpu_usage"] * fluc, 3))
                mem_u = max(50.0, round(pod["mem_usage"] * fluc, 1))
                c_info = CostCalculator.calculate_pod_cost(
                    pod["cpu_req"], cpu_u, pod["mem_req"], mem_u, cpu_rate, ram_rate
                )
                h_snap = MetricsSnapshot(
                    timestamp=historical_time,
                    namespace=pod["ns"],
                    pod_name=pod["name"],
                    workload_type=pod["type"],
                    cpu_req=pod["cpu_req"],
                    cpu_usage=cpu_u,
                    mem_req_mb=pod["mem_req"],
                    mem_usage_mb=mem_u,
                    net_rx_bytes=pod["net_rx"] * 1024 * fluc,
                    net_tx_bytes=pod["net_tx"] * 1024 * fluc,
                    hourly_cost=c_info["hourly_cost"],
                    monthly_cost=c_info["monthly_cost"],
                    efficiency_pct=c_info["efficiency_pct"]
                )
                db.add(h_snap)

        # 4. Seed Zombie Workloads (Flagged Idle Pods)
        zombies = [
            ZombieWorkload(
                namespace="staging-zombies",
                pod_name="legacy-qa-testbench-77a-99",
                workload_name="legacy-qa-testbench",
                workload_type="Deployment",
                cpu_usage_avg=0.01,
                mem_usage_avg_mb=120.0,
                net_activity_kb=0.2,
                idle_duration_hours=72.0,
                wasted_monthly_cost=175.20,
                status="ACTIVE",
                recommended_action="Scale deployment to 0 replicas",
                detected_at=now - datetime.timedelta(hours=36)
            ),
            ZombieWorkload(
                namespace="staging-zombies",
                pod_name="deprecated-report-worker-22b",
                workload_name="deprecated-report-worker",
                workload_type="Deployment",
                cpu_usage_avg=0.005,
                mem_usage_avg_mb=90.0,
                net_activity_kb=0.0,
                idle_duration_hours=120.0,
                wasted_monthly_cost=87.60,
                status="ACTIVE",
                recommended_action="Scale deployment to 0 replicas",
                detected_at=now - datetime.timedelta(hours=72)
            ),
            ZombieWorkload(
                namespace="staging-zombies",
                pod_name="temp-loadtest-generator-0",
                workload_name="temp-loadtest-generator",
                workload_type="Deployment",
                cpu_usage_avg=0.02,
                mem_usage_avg_mb=180.0,
                net_activity_kb=0.6,
                idle_duration_hours=48.0,
                wasted_monthly_cost=175.20,
                status="ACTIVE",
                recommended_action="Scale deployment to 0 replicas",
                detected_at=now - datetime.timedelta(hours=24)
            )
        ]
        for z in zombies:
            db.add(z)

        # 5. Seed Recommendations (Over-provisioned Right-Sizing Suggestions)
        recs = [
            Recommendation(
                namespace="backend-api",
                pod_name="auth-service-6b4d91-x99a",
                workload_name="auth-service",
                workload_type="Deployment",
                current_cpu_req=4.0,
                current_mem_req_mb=8192.0,
                recommended_cpu_req=0.60,
                recommended_mem_req_mb=2160.0,
                current_monthly_cost=175.20,
                recommended_monthly_cost=30.50,
                monthly_savings=144.70,
                status="PENDING",
                created_at=now - datetime.timedelta(hours=12)
            ),
            Recommendation(
                namespace="payments-service",
                pod_name="ledger-sync-worker-12a-77",
                workload_name="ledger-sync-worker",
                workload_type="Deployment",
                current_cpu_req=4.0,
                current_mem_req_mb=16384.0,
                recommended_cpu_req=0.50,
                recommended_mem_req_mb=2880.0,
                current_monthly_cost=211.70,
                recommended_monthly_cost=30.20,
                monthly_savings=181.50,
                status="PENDING",
                created_at=now - datetime.timedelta(hours=8)
            ),
            Recommendation(
                namespace="analytics-worker",
                pod_name="spark-driver-main-99a",
                workload_name="spark-driver-main",
                workload_type="Deployment",
                current_cpu_req=8.0,
                current_mem_req_mb=32768.0,
                recommended_cpu_req=1.20,
                recommended_mem_req_mb=6480.0,
                current_monthly_cost=423.40,
                recommended_monthly_cost=70.80,
                monthly_savings=352.60,
                status="PENDING",
                created_at=now - datetime.timedelta(hours=4)
            )
        ]
        for r in recs:
            db.add(r)

        # 6. Seed Sample Action Logs (Historical audit records)
        actions = [
            ActionLog(
                action_type="SCALE_DOWN",
                target_resource="Deployment / dev-redis-cache",
                namespace="staging-zombies",
                pod_name="dev-redis-cache-11x",
                monthly_savings=120.0,
                status="SUCCESS",
                applied_by="MANUAL",
                timestamp=now - datetime.timedelta(days=2),
                details="Scaled deployment dev-redis-cache replicas from 2 to 0 due to zero traffic for 5+ days."
            ),
            ActionLog(
                action_type="RIGHT_SIZE",
                target_resource="Deployment / notification-dispatcher",
                namespace="backend-api",
                pod_name="notification-dispatcher-88b",
                monthly_savings=64.50,
                status="SUCCESS",
                applied_by="AUTO_REMEDIATION",
                timestamp=now - datetime.timedelta(days=1),
                details="Patched CPU request from 2.0 to 0.4 vCPU, memory from 4096MB to 1024MB based on p95 metrics."
            )
        ]
        for a in actions:
            db.add(a)

        db.commit()
        print("Mock data seeded successfully!")
