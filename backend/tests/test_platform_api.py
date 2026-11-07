import datetime
import re

import pytest

from app.core.config import settings
from app.db.platform_models import Node, utcnow
from app.services.allocation_job import floor_hour, run_allocation_for_cluster
from app.services.demo import DEMO_CLUSTER_NAME, NODES, SLOT, floor_slot, node_active

API = "/api/v1"
GIB = 1024**3


@pytest.fixture
def cluster(client, request):
    name = re.sub(r"[^a-z0-9]+", "-", request.node.name.lower()).strip("-")[:60]
    r = client.post(f"{API}/clusters", json={"name": name, "provider": "aws", "region": "us-east-1"})
    assert r.status_code == 201, r.text
    body = r.json()
    yield body
    client.delete(f"{API}/clusters/{body['id']}")


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _node(name="node-a", instance_type="m5.xlarge", vcpu=4, mem=16, **kw):
    return {"name": name, "instance_type": instance_type, "vcpu": vcpu, "memory_gib": mem, **kw}


def _sample(ts, pod="web-1", ns="shop", cpu_req=1.0, cpu_use=0.25, mem_req=2, mem_use=1, node="node-a", **kw):
    return {"ts": ts.isoformat(), "namespace": ns, "pod": pod, "container": "app", "node": node,
            "workload_kind": "Deployment", "workload_name": pod.rsplit("-", 1)[0], "duration_seconds": 300,
            "cpu_request_cores": cpu_req, "cpu_usage_cores": cpu_use, "mem_request_bytes": mem_req * GIB,
            "mem_usage_bytes": mem_use * GIB, **kw}


# --- registry & credentials --------------------------------------------------------


def test_register_cluster_returns_token_once(client, cluster):
    assert cluster["agent_token"].startswith("kfo_")
    listed = client.get(f"{API}/clusters").json()
    row = next(c for c in listed if c["id"] == cluster["id"])
    assert "agent_token" not in row and "token_hash" not in row


def test_duplicate_and_invalid_cluster_names(client, cluster):
    assert client.post(f"{API}/clusters", json={"name": cluster["name"]}).status_code == 409
    assert client.post(f"{API}/clusters", json={"name": "Bad_Name!"}).status_code == 422


@pytest.mark.parametrize("header", [None, "Bearer nonsense", "Bearer kfo_deadbeef_wrongsecret", "Basic abc"])
def test_ingest_rejects_bad_credentials(client, header):
    headers = {"Authorization": header} if header else {}
    assert client.post(f"{API}/ingest/inventory", json={}, headers=headers).status_code == 401


def test_disabled_cluster_is_forbidden(client, cluster):
    client.post(f"{API}/clusters/{cluster['id']}/disable")
    assert client.post(f"{API}/ingest/inventory", json={}, headers=auth(cluster["agent_token"])).status_code == 403


def test_token_rotation_revokes_old_token(client, cluster):
    new = client.post(f"{API}/clusters/{cluster['id']}/rotate-token").json()["agent_token"]
    assert client.post(f"{API}/ingest/inventory", json={}, headers=auth(cluster["agent_token"])).status_code == 401
    assert client.post(f"{API}/ingest/inventory", json={}, headers=auth(new)).status_code == 200


def test_admin_key_protects_registry(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "s3cret")
    assert client.get(f"{API}/clusters").status_code == 401
    assert client.get(f"{API}/clusters", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.get(f"{API}/clusters", headers={"X-Admin-Key": "s3cret"}).status_code == 200


# --- ingestion ----------------------------------------------------------------------


def test_inventory_prices_nodes_from_catalog(client, cluster, db):
    body = {"nodes": [_node(), _node("node-spot", "c5.2xlarge", 8, 16, capacity_type="spot"),
                      _node("node-odd", "weird.type", 2, 4)],
            "workloads": [{"namespace": "shop", "kind": "Deployment", "name": "web", "labels": {"team": "web"}}]}
    r = client.post(f"{API}/ingest/inventory", json=body, headers=auth(cluster["agent_token"]))
    assert r.status_code == 200 and r.json()["accepted"] == 4
    nodes = {n.name: n for n in db.query(Node).filter(Node.cluster_id == cluster["id"])}
    assert nodes["node-a"].hourly_price == pytest.approx(0.192)
    assert nodes["node-a"].price_source == "catalog"
    assert nodes["node-spot"].hourly_price == pytest.approx(0.34 * 0.35)
    assert nodes["node-odd"].price_source == "fallback"


def test_inventory_tolerates_duplicate_entries(client, cluster):
    body = {"nodes": [_node(), _node(vcpu=8, mem=32)],
            "workloads": [{"namespace": "a", "kind": "Deployment", "name": "x"}] * 2}
    assert client.post(f"{API}/ingest/inventory", json=body, headers=auth(cluster["agent_token"])).status_code == 200


def test_node_heartbeats_bill_only_uptime(client, cluster, db):
    from app.db.platform_models import Cluster

    hour = floor_hour(utcnow()) - datetime.timedelta(hours=1)
    token = auth(cluster["agent_token"])
    client.post(f"{API}/ingest/inventory", json={"nodes": [_node(created_at=hour.isoformat())]}, headers=token)
    # Node up for the first 30 minutes only (e.g. a reclaimed spot node).
    beats = [{"ts": (hour + datetime.timedelta(minutes=5 * i)).isoformat(), "node": "node-a"} for i in range(6)]
    assert client.post(f"{API}/ingest/samples", json={"node_samples": beats},
                       headers=token).json()["node_samples_accepted"] == 6
    run_allocation_for_cluster(db, db.get(Cluster, cluster["id"]))
    rep = client.get(f"{API}/clusters/{cluster['id']}/allocation?window=24h").json()
    assert rep["total_cost"] == pytest.approx(0.192 / 2, rel=1e-3)
    assert client.post(f"{API}/ingest/samples", json={"samples": []}, headers=token).status_code == 422


def test_first_run_bills_node_hours_before_first_sample(client, cluster, db):
    """Regression: the first run used to start at the first *sample*, so a node
    that existed earlier was only billed for those hours on a later run."""
    from app.db.platform_models import Cluster

    hour = floor_hour(utcnow()) - datetime.timedelta(hours=1)
    token = auth(cluster["agent_token"])
    created = hour - datetime.timedelta(hours=5)
    client.post(f"{API}/ingest/inventory", json={"nodes": [_node(created_at=created.isoformat())]}, headers=token)
    client.post(f"{API}/ingest/samples", json={"samples": [_sample(hour)]}, headers=token)

    c = db.get(Cluster, cluster["id"])
    assert run_allocation_for_cluster(db, c) == 6
    first = client.get(f"{API}/clusters/{cluster['id']}/allocation?window=24h").json()["total_cost"]
    run_allocation_for_cluster(db, c)
    again = client.get(f"{API}/clusters/{cluster['id']}/allocation?window=24h").json()["total_cost"]
    assert first == pytest.approx(6 * 0.192, rel=1e-3)
    assert again == pytest.approx(first)


def test_samples_are_idempotent_and_validated(client, cluster):
    ts = floor_hour(utcnow()) - datetime.timedelta(hours=1)
    batch = {"samples": [_sample(ts), _sample(ts + datetime.timedelta(minutes=5))]}
    first = client.post(f"{API}/ingest/samples", json=batch, headers=auth(cluster["agent_token"])).json()
    again = client.post(f"{API}/ingest/samples", json=batch, headers=auth(cluster["agent_token"])).json()
    assert (first["accepted"], first["duplicates"]) == (2, 0)
    assert (again["accepted"], again["duplicates"]) == (0, 2)

    future = {"samples": [_sample(utcnow() + datetime.timedelta(hours=2))]}
    r = client.post(f"{API}/ingest/samples", json=future, headers=auth(cluster["agent_token"]))
    assert r.json()["rejected"] == 1

    negative = {"samples": [_sample(ts, cpu_use=-1)]}
    assert client.post(f"{API}/ingest/samples", json=negative, headers=auth(cluster["agent_token"])).status_code == 422


def test_oversized_batch_is_rejected(client, cluster, monkeypatch):
    monkeypatch.setattr(settings, "max_samples_per_request", 1)
    ts = floor_hour(utcnow()) - datetime.timedelta(hours=1)
    batch = {"samples": [_sample(ts), _sample(ts, pod="web-2")]}
    assert client.post(f"{API}/ingest/samples", json=batch, headers=auth(cluster["agent_token"])).status_code == 413


# --- allocation end to end ------------------------------------------------------------


def test_allocation_reconciles_to_node_bill(client, cluster, db):
    hour = floor_hour(utcnow()) - datetime.timedelta(hours=1)
    token = auth(cluster["agent_token"])
    inv = {"nodes": [_node(created_at=hour.isoformat())],
           "workloads": [{"namespace": "shop", "kind": "Deployment", "name": "web", "labels": {"team": "web"}},
                         {"namespace": "kube-system", "kind": "Deployment", "name": "dns",
                          "labels": {"team": "platform"}}]}
    client.post(f"{API}/ingest/inventory", json=inv, headers=token)
    samples = []
    for i in range(12):
        ts = hour + datetime.timedelta(minutes=5 * i)
        samples.append(_sample(ts, pod="web-1", cpu_req=1, cpu_use=0.25, mem_req=2, mem_use=1))
        samples.append(_sample(ts, pod="dns-1", ns="kube-system", cpu_req=0.5, cpu_use=0.1, mem_req=1, mem_use=0.5))
    assert client.post(f"{API}/ingest/samples", json={"samples": samples}, headers=token).json()["accepted"] == 24

    from app.db.platform_models import Cluster
    assert run_allocation_for_cluster(db, db.get(Cluster, cluster["id"])) >= 1

    rep = client.get(f"{API}/clusters/{cluster['id']}/allocation?window=24h&aggregate=namespace").json()
    # One m5.xlarge for one hour = $0.192, whether allocated, shared or idle.
    assert rep["total_cost"] == pytest.approx(0.192, rel=1e-3)
    assert rep["allocated_cost"] + rep["idle_cost"] == pytest.approx(rep["total_cost"], rel=1e-6)
    names = {i["name"] for i in rep["items"]}
    assert {"shop", "__shared__", "__idle__"} <= names
    shop = next(i for i in rep["items"] if i["name"] == "shop")
    assert shop["cpu_efficiency"] == pytest.approx(0.25, abs=1e-3)

    dist = client.get(f"{API}/clusters/{cluster['id']}/allocation?window=24h&shared=distribute").json()
    shop_d = next(i for i in dist["items"] if i["name"] == "shop")
    assert shop_d["shared_cost_added"] == pytest.approx(rep["shared_cost"], rel=1e-3)
    assert "__shared__" not in {i["name"] for i in dist["items"]}

    by_team = client.get(f"{API}/clusters/{cluster['id']}/allocation?window=24h&aggregate=label:team").json()
    assert {"web", "__idle__"} <= {i["name"] for i in by_team["items"]}

    # Re-running allocation must not double count.
    run_allocation_for_cluster(db, db.get(Cluster, cluster["id"]))
    again = client.get(f"{API}/clusters/{cluster['id']}/allocation?window=24h").json()
    assert again["total_cost"] == pytest.approx(rep["total_cost"])


@pytest.mark.parametrize("query", ["window=1y", "window=500d", "aggregate=planet", "aggregate=label:"])
def test_allocation_rejects_bad_parameters(client, cluster, query):
    assert client.get(f"{API}/clusters/{cluster['id']}/allocation?{query}").status_code == 422


def test_unknown_cluster_404(client):
    assert client.get(f"{API}/clusters/nope/allocation").status_code == 404


# --- demo cluster (seeded through the ingestion path) -----------------------------------


@pytest.fixture
def demo(client):
    return next(c for c in client.get(f"{API}/clusters").json() if c["name"] == DEMO_CLUSTER_NAME)


def test_demo_cluster_summary(client, demo):
    s = client.get(f"{API}/clusters/{demo['id']}/summary").json()
    running = sum(node_active(n.name, floor_slot(utcnow()) - SLOT) for n in NODES)
    assert s["nodes"] == running and s["spot_nodes"] == 2
    assert s["monthly_run_rate"] > 0
    assert 0 < s["idle_pct"] < 1          # the lightly packed spot node shows up as idle
    assert 0 < s["efficiency"] < 1
    assert s["last_allocated_window"] is not None


def test_demo_costs_by_team_and_timeseries(client, demo):
    teams = client.get(f"{API}/clusters/{demo['id']}/allocation?window=24h&aggregate=label:team").json()
    names = {i["name"] for i in teams["items"]}
    assert {"payments", "web", "data", "__shared__", "__idle__"} <= names

    series = client.get(f"{API}/clusters/{demo['id']}/cost-timeseries?window=24h&step=1h").json()
    assert len(series) >= 20


def test_autoscaled_node_makes_the_bill_follow_demand(db):
    """Deterministic: replay one fixed weekday of the demo into a fresh cluster."""
    from app.core.security import new_agent_token
    from app.db.platform_models import Cluster
    from app.services.allocation_query import cost_timeseries
    from app.services.demo import _emit_range, inventory
    from app.services.ingestion import ingest_inventory

    day = datetime.datetime(2026, 11, 4)  # a Wednesday
    now = day + datetime.timedelta(days=1, minutes=1)
    _, prefix, token_hash = new_agent_token()
    cluster = Cluster(name="replay-weekday", provider="aws", region="us-east-1", token_prefix=prefix,
                      token_hash=token_hash)
    db.add(cluster)
    db.commit()
    ingest_inventory(db, cluster, inventory(), now=now, first_seen=day)
    _emit_range(db, cluster, day, day + datetime.timedelta(hours=24) - SLOT, now)
    assert run_allocation_for_cluster(db, cluster, now=now) == 24

    series = {p.start.hour: p.total_cost for p in cost_timeseries(db, cluster, "24h", "1h", now=now)}
    m5_2xl = 0.384
    # Peak hours carry the extra m5.2xlarge; nights do not.
    assert series[12] - series[3] == pytest.approx(m5_2xl, rel=0.02)
    assert series[8] > series[7]
    assert series[20] < series[19]
    db.delete(cluster)
    db.commit()
