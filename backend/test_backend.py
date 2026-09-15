import sys
import os
import time

# Add backend directory to sys.path
backend_dir = r"c:\Kubernetes Fin-ops\Kubernetes-FinOps-Cost-Optimization-Dashboard\backend"
sys.path.insert(0, backend_dir)

from app.db.database import engine, Base, SessionLocal
from app.db.models import MetricsSnapshot, ZombieWorkload, Recommendation, ActionLog, SystemSetting
from app.engine.mock_generator import MockDataGenerator
from app.engine.cost_calculator import CostCalculator

print("1. Creating database tables...")
Base.metadata.create_all(bind=engine)

print("2. Seeding initial mock data...")
db = SessionLocal()
try:
    MockDataGenerator.seed_initial_data(db, force=True)
    
    # Query database records
    snaps_count = db.query(MetricsSnapshot).count()
    zombies_count = db.query(ZombieWorkload).count()
    recs_count = db.query(Recommendation).count()
    actions_count = db.query(ActionLog).count()
    settings_count = db.query(SystemSetting).count()
    
    print(f"Snapshots seeded: {snaps_count}")
    print(f"Zombies seeded: {zombies_count}")
    print(f"Recommendations seeded: {recs_count}")
    print(f"Actions seeded: {actions_count}")
    print(f"Settings seeded: {settings_count}")
    
    # Calculate sample pod cost
    c_info = CostCalculator.calculate_pod_cost(2.0, 0.45, 4096.0, 1800.0, 0.048, 0.006)
    print(f"Cost calc check: monthly_cost=${c_info['monthly_cost']}, efficiency={c_info['efficiency_pct']}%")
    
    assert snaps_count > 0, "Error: No snapshots created!"
    assert zombies_count > 0, "Error: No zombies created!"
    assert recs_count > 0, "Error: No recommendations created!"
    print("\nBackend Data Model & OpenCost Engine Verification: SUCCESS!")
finally:
    db.close()
