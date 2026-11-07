import pytest

from app.db.models import ActionLog

API = "/api/v1"


@pytest.mark.parametrize(
    "path",
    ["/overview", "/cost-trend?range=7d", "/cost-trend?range=30d", "/namespaces", "/zombies",
     "/recommendations", "/actions/history", "/lifecycle", "/settings"],
)
def test_read_endpoints_return_200(client, path):
    assert client.get(API + path).status_code == 200


def test_overview_reflects_seeded_cluster(client):
    ov = client.get(f"{API}/overview").json()
    assert ov["total_namespaces"] == 8
    assert ov["total_pods"] == 23
    assert ov["total_monthly_cost"] > 0


def test_cost_trend_rejects_unknown_range(client):
    assert client.get(f"{API}/cost-trend?range=1y").status_code == 422


def test_namespace_pods_404_for_unknown_namespace(client):
    assert client.get(f"{API}/namespaces/does-not-exist/pods").status_code == 404


def test_remediating_zombie_writes_audit_log_and_is_idempotent(client, db):
    zombie = next(z for z in client.get(f"{API}/zombies").json() if z["status"] == "ACTIVE")
    before = db.query(ActionLog).count()

    r = client.post(f"{API}/zombies/{zombie['id']}/remediate")
    assert r.status_code == 200
    assert r.json()["action_type"] == "SCALE_DOWN"
    assert db.query(ActionLog).count() == before + 1

    # Second attempt must not double-count savings.
    assert client.post(f"{API}/zombies/{zombie['id']}/remediate").status_code == 400


def test_applying_recommendation_marks_it_applied(client):
    rec = next(r for r in client.get(f"{API}/recommendations").json() if r["status"] == "PENDING")
    assert client.post(f"{API}/recommendations/{rec['id']}/apply").status_code == 200
    updated = next(r for r in client.get(f"{API}/recommendations").json() if r["id"] == rec["id"])
    assert updated["status"] == "APPLIED"
    assert client.post(f"{API}/recommendations/{rec['id']}/apply").status_code == 400


def test_settings_validation_rejects_negative_price(client):
    payload = client.get(f"{API}/settings").json() | {"cpu_hourly_rate": -1}
    assert client.post(f"{API}/settings", json=payload).status_code == 422


def test_settings_update_reprices_cluster(client):
    current = client.get(f"{API}/settings").json()
    cost_before = client.get(f"{API}/overview").json()["total_monthly_cost"]
    doubled = current | {"cpu_hourly_rate": current["cpu_hourly_rate"] * 2,
                         "ram_hourly_rate": current["ram_hourly_rate"] * 2}
    assert client.post(f"{API}/settings", json=doubled).status_code == 200
    cost_after = client.get(f"{API}/overview").json()["total_monthly_cost"]
    assert cost_after == pytest.approx(cost_before * 2, rel=0.01)
    client.post(f"{API}/settings", json=current)
