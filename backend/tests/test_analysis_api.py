import pytest

from app.db.platform_models import Cluster
from app.services.analysis import analyze_cluster
from app.services.demo import DEMO_CLUSTER_NAME, VOLUMES, inventory
from app.services.ingestion import ingest_inventory

API = "/api/v1"


@pytest.fixture(scope="module")
def demo(client):
    c = next(c for c in client.get(f"{API}/clusters").json() if c["name"] == DEMO_CLUSTER_NAME)
    assert client.post(f"{API}/clusters/{c['id']}/analyze").status_code == 200
    return c


def recs(client, demo, **params):
    return client.get(f"{API}/clusters/{demo['id']}/recommendations", params=params).json()


def by_workload(items):
    return {(r["namespace"], r["workload_name"]): r for r in items}


def test_overprovisioned_services_get_downsized(client, demo):
    r = by_workload(recs(client, demo))
    ledger = r[("payments", "ledger-worker")]
    assert ledger["action"] == "downsize" and ledger["monthly_savings"] > 0
    assert ledger["recommended_cpu_request"] < ledger["current_cpu_request"]
    assert ledger["recommended_mem_request"] < ledger["current_mem_request"]
    assert r[("storefront", "checkout-api")]["action"] == "downsize"


def test_oom_killed_service_gets_more_memory_not_less(client, demo):
    ml = by_workload(recs(client, demo))[("ml", "recommender-inference")]
    assert ml["action"] == "upsize" and ml["risk"] == "high"
    assert ml["recommended_mem_request"] > ml["current_mem_limit"]
    assert any("OOM" in reason for reason in ml["reasons"])


def test_idle_workloads_are_findings_not_rightsizing(client, demo):
    """No double counting: an idle workload's saving is its whole cost, once."""
    rightsized = {(r["namespace"], r["workload_name"]) for r in recs(client, demo, status="all")}
    idle = {(f["namespace"], f["evidence"]["workload_name"])
            for f in client.get(f"{API}/clusters/{demo['id']}/waste", params={"kind": "IDLE_WORKLOAD"}).json()}
    assert {("data", "report-generator"), ("staging", "legacy-qa-testbench")} <= idle
    assert not idle & rightsized


def test_orphaned_volumes_and_unused_load_balancer(client, demo):
    waste = client.get(f"{API}/clusters/{demo['id']}/waste").json()
    found = {(f["kind"], f["name"]): f for f in waste}
    # 500 GiB gp3 at $0.08 and 50 GiB gp2 at $0.10 per GiB-month
    assert found[("ORPHANED_VOLUME", "PersistentVolumeClaim/q3-export-backup")]["monthly_savings"] == 40.0
    assert found[("ORPHANED_VOLUME", "PersistentVolumeClaim/qa-fixtures")]["monthly_savings"] == 5.0
    assert found[("UNUSED_LB", "Service/legacy-checkout-lb")]["monthly_savings"] == 18.25
    assert ("UNUSED_LB", "Service/storefront-public") not in found
    assert ("ORPHANED_VOLUME", "PersistentVolumeClaim/data-search-api-0") not in found


def test_savings_summary_is_non_overlapping(client, demo):
    s = client.get(f"{API}/clusters/{demo['id']}/savings").json()
    waste = client.get(f"{API}/clusters/{demo['id']}/waste").json()
    down = [r for r in recs(client, demo) if r["action"] == "downsize"]
    expected = sum(r["monthly_savings"] for r in down) + sum(
        f["monthly_savings"] for f in waste if f["kind"] != "UNDERUTILIZED_NODE")
    assert s["total_monthly_savings"] == pytest.approx(expected, abs=0.05)
    assert s["reliability_fixes"]["count"] >= 1 and s["reliability_fixes"]["monthly_cost"] > 0
    assert "UNDERUTILIZED_NODE" in s["overlapping"]


def test_detail_has_usage_chart_and_compare_runs_all_strategies(client, demo):
    rec = by_workload(recs(client, demo))[("payments", "ledger-worker")]
    detail = client.get(f"{API}/clusters/{demo['id']}/recommendations/{rec['id']}").json()
    assert len(detail["usage"]) >= 24
    assert {"cpu_p50", "cpu_max", "mem_max", "oom_kills"} <= set(detail["usage"][0])
    cmp = client.get(f"{API}/clusters/{demo['id']}/recommendations/{rec['id']}/compare").json()
    assert set(cmp["strategies"]) == {"slo_aware", "vpa", "p95_buffer"}
    assert cmp["strategies"]["slo_aware"]["cpu_peak_exceedance"] <= 0.01


def test_dismissed_recommendation_stays_dismissed(client, demo, db):
    rec = by_workload(recs(client, demo))[("storefront", "checkout-api")]
    r = client.post(f"{API}/clusters/{demo['id']}/recommendations/{rec['id']}/dismiss",
                    json={"reason": "peak season next week"})
    assert r.json()["status"] == "dismissed"
    analyze_cluster(db, db.get(Cluster, demo["id"]))
    after = {x["id"]: x for x in recs(client, demo, status="all")}[rec["id"]]
    assert after["status"] == "dismissed" and after["dismissed_reason"] == "peak season next week"
    assert client.post(f"{API}/clusters/{demo['id']}/recommendations/{rec['id']}/dismiss",
                       json={"reason": ""}).status_code == 422


def test_fixed_waste_is_resolved_automatically(client, demo, db):
    cluster = db.get(Cluster, demo["id"])
    inv = inventory()
    inv.volumes = [v.model_copy(update={"mounted_by": ["restore-job-x"]}) if v.name == "qa-fixtures" else v
                   for v in VOLUMES]
    ingest_inventory(db, cluster, inv)
    analyze_cluster(db, cluster)
    resolved = client.get(f"{API}/clusters/{demo['id']}/waste", params={"status": "resolved"}).json()
    assert "PersistentVolumeClaim/qa-fixtures" in {f["name"] for f in resolved}


def test_unknown_ids_404(client, demo):
    assert client.get(f"{API}/clusters/{demo['id']}/recommendations/999999").status_code == 404
    assert client.post(f"{API}/clusters/{demo['id']}/waste/999999/dismiss", json={"reason": "nope"}).status_code == 404


def test_v1_dashboard_no_longer_double_counts_zombies(client, db):
    from app.db.models import Recommendation, ZombieWorkload
    from app.engine.right_sizer import RightSizer

    RightSizer.evaluate(db)
    zombie_pods = {(z.namespace, z.pod_name) for z in db.query(ZombieWorkload)}
    assert not zombie_pods & {(r.namespace, r.pod_name) for r in db.query(Recommendation)}
