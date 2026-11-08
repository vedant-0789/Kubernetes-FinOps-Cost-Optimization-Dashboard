import datetime
import json

import httpx
import pytest

from app.db.platform_models import (
    BudgetAlert,
    Cluster,
    CostAllocation,
    CostAnomaly,
    NodeCost,
    Notification,
    Workload,
    utcnow,
)
from app.services import notify
from app.services.allocation_query import allocation_report
from app.services.finance import day_floor, evaluate_budgets

API = "/api/v1"
SPIKE_DAYS_AGO = 3


def hourly_cost(day: datetime.datetime) -> tuple[float, float]:
    """(shop $/h, data $/h): weekends cheaper, one spike day for `data`."""
    shop = 1.5 if day.weekday() < 5 else 1.2
    data = 0.5
    if day == day_floor(utcnow()) - datetime.timedelta(days=SPIKE_DAYS_AGO):
        data += 1.5      # runaway batch: +$36 that day
    return shop, data


@pytest.fixture
def cluster(client, db, request):
    name = "fin-" + "".join(ch if ch.isalnum() else "-" for ch in request.node.name.lower())[:50].strip("-")
    c = client.post(f"{API}/clusters", json={"name": name}).json()
    now = utcnow()
    start = day_floor(now) - datetime.timedelta(days=28)
    rows, idle = [], []
    h = start
    while h < now.replace(minute=0, second=0, microsecond=0):
        shop, data = hourly_cost(day_floor(h))
        rows += [CostAllocation(window_start=h, cluster_id=c["id"], namespace="shop", pod="web-1", container="web",
                                workload_kind="Deployment", workload_name="web", total_cost=shop, cpu_cost=shop),
                 CostAllocation(window_start=h, cluster_id=c["id"], namespace="data", pod="etl-1", container="etl",
                                workload_kind="Deployment", workload_name="etl", total_cost=data, cpu_cost=data)]
        idle.append(NodeCost(window_start=h, cluster_id=c["id"], node="n1", total_cost=0.2, idle_cpu_cost=0.2))
        h += datetime.timedelta(hours=1)
    db.add_all(rows + idle + [
        Workload(cluster_id=c["id"], namespace="shop", kind="Deployment", name="web", labels={"team": "web"}),
        Workload(cluster_id=c["id"], namespace="data", kind="Deployment", name="etl", labels={"team": "data"})])
    db.commit()
    yield c
    client.delete(f"{API}/clusters/{c['id']}")


@pytest.fixture
def webhook(client, db, monkeypatch):
    """A webhook channel whose deliveries are captured instead of sent."""
    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200)

    monkeypatch.setattr(notify, "_http", httpx.Client(transport=httpx.MockTransport(handler)))
    r = client.post(f"{API}/notification-channels",
                    json={"name": f"hook-{len(received)}-{id(received)}", "type": "webhook",
                          "url": "https://hooks.example.com/kubefinops/secret-token-123456"})
    assert r.status_code == 201, r.text
    yield received
    client.delete(f"{API}/notification-channels/{r.json()['id']}")


# --- forecast -------------------------------------------------------------------------


def test_forecast_endpoint(client, cluster):
    r = client.get(f"{API}/clusters/{cluster['id']}/forecast", params={"days": 14}).json()
    assert len(r["history"]) == 28 and len(r["forecast"]) == 14
    assert r["method"] == "holt_winters"
    assert r["backtest_mape_7d"] is not None and r["backtest_mape_7d"] < 0.25
    me = r["month_end"]
    assert me["actual_to_date"] > 0 and me["lo80"] <= me["projected"] <= me["hi80"]
    assert me["projected"] >= me["actual_to_date"]


def test_forecast_by_label_and_namespace(client, cluster):
    team = client.get(f"{API}/clusters/{cluster['id']}/forecast", params={"scope": "label:team=web"}).json()
    ns = client.get(f"{API}/clusters/{cluster['id']}/forecast", params={"scope": "namespace:shop"}).json()
    assert [h["cost"] for h in team["history"]] == [h["cost"] for h in ns["history"]]
    for bad in ("label:team", "namespace:", "planet"):
        assert client.get(f"{API}/clusters/{cluster['id']}/forecast", params={"scope": bad}).status_code == 422


# --- anomalies ------------------------------------------------------------------------


def test_spike_day_is_detected_once_and_notified(client, cluster, webhook):
    client.post(f"{API}/finance/run")
    found = client.get(f"{API}/clusters/{cluster['id']}/anomalies").json()
    spike_day = (day_floor(utcnow()) - datetime.timedelta(days=SPIKE_DAYS_AGO)).date().isoformat()
    scopes = {(a["scope"], a["name"]) for a in found if a["day"].startswith(spike_day)}
    assert ("namespace", "data") in scopes and ("cluster", cluster["name"]) in scopes
    assert all(a["day"].startswith(spike_day) for a in found)          # weekends are not anomalies

    client.post(f"{API}/finance/run")
    again = client.get(f"{API}/clusters/{cluster['id']}/anomalies").json()
    assert len(again) == len(found)                                      # no duplicates

    r = client.post(f"{API}/clusters/{cluster['id']}/anomalies/{found[0]['id']}/ack")
    assert r.json()["status"] == "acknowledged"


def test_recent_anomaly_is_sent_to_channels(client, cluster, webhook, db):
    # Move the detection clock so the spike is "yesterday".
    from app.services.finance import detect_cost_anomalies

    now = utcnow() - datetime.timedelta(days=SPIKE_DAYS_AGO - 1)
    db.query(CostAnomaly).filter(CostAnomaly.cluster_id == cluster["id"]).delete()
    db.commit()
    detect_cost_anomalies(db, db.get(Cluster, cluster["id"]), now=now)
    events = [m for m in webhook if m["event"] == "anomaly"]
    assert events and "data" in " ".join(m["subject"] for m in events)


# --- budgets --------------------------------------------------------------------------


def test_budget_thresholds_fire_once_per_month(client, cluster, webhook, db):
    status_before = client.get(f"{API}/clusters/{cluster['id']}/forecast").json()["month_end"]
    spent = status_before["actual_to_date"]
    # Budget set so that 50 % is already spent but 100 % is not: only the 50 % alert fires now...
    amount = spent * 1.6
    r = client.post(f"{API}/clusters/{cluster['id']}/budgets",
                    json={"name": "cluster-monthly", "monthly_amount": round(amount, 2)})
    assert r.status_code == 201
    bid = r.json()["id"]
    evaluate_budgets(db)
    alerts = db.query(BudgetAlert).filter(BudgetAlert.budget_id == bid).all()
    assert {(a.kind, a.threshold) for a in alerts} >= {("actual", 50)}
    assert ("actual", 100) not in {(a.kind, a.threshold) for a in alerts}
    first = len(alerts)
    evaluate_budgets(db)
    assert db.query(BudgetAlert).filter(BudgetAlert.budget_id == bid).count() == first  # not again
    assert any(m["event"] == "budget" and "50%" in m["subject"] for m in webhook)

    st = client.get(f"{API}/clusters/{cluster['id']}/budgets/{bid}").json()["status"]
    assert st["pct_actual"] == pytest.approx(spent / amount * 100, rel=0.02)
    assert st["state"] in ("ok", "at_risk")


def test_forecast_to_exceed_alert(client, cluster, webhook, db):
    spent = client.get(f"{API}/clusters/{cluster['id']}/forecast").json()["month_end"]
    if spent["projected"] - spent["actual_to_date"] < 1:
        pytest.skip("last hours of the month: nothing left to forecast")
    amount = (spent["actual_to_date"] + spent["projected"]) / 2     # spent < amount < projected
    bid = client.post(f"{API}/clusters/{cluster['id']}/budgets",
                      json={"name": "tight", "monthly_amount": round(amount, 2), "thresholds": [100]}).json()["id"]
    evaluate_budgets(db)
    kinds = {(a.kind, a.threshold) for a in db.query(BudgetAlert).filter(BudgetAlert.budget_id == bid)}
    assert kinds == {("forecast", 100)}
    st = client.get(f"{API}/clusters/{cluster['id']}/budgets/status").json()
    assert next(s for s in st if s["budget_id"] == bid)["state"] == "at_risk"


@pytest.mark.parametrize("body", [{"name": "x", "monthly_amount": -5}, {"name": "x", "monthly_amount": 10,
                                  "scope": "namespace"}, {"name": "x", "monthly_amount": 10, "scope": "label",
                                                          "scope_key": "team"}, {"name": "x", "monthly_amount": 10,
                                                                                 "thresholds": [0]}])
def test_budget_validation(client, cluster, body):
    assert client.post(f"{API}/clusters/{cluster['id']}/budgets", json=body).status_code == 422


# --- channels -------------------------------------------------------------------------


def test_channel_urls_are_masked_and_test_messages_logged(client, webhook):
    channels = client.get(f"{API}/notification-channels").json()
    hook = next(c for c in channels if c["type"] == "webhook")
    assert "secret-token" not in hook["config"]["url"]
    r = client.post(f"{API}/notification-channels/{hook['id']}/test").json()
    assert r["status"] == "sent" and webhook[-1]["subject"] == "KubeFinOps test notification"


def test_failed_delivery_is_logged_not_raised(client, db, monkeypatch):
    monkeypatch.setattr(notify, "_http", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    c = client.post(f"{API}/notification-channels", json={"name": "broken-slack", "type": "slack",
                                                          "url": "https://hooks.slack.com/services/T/B/X"}).json()
    r = client.post(f"{API}/notification-channels/{c['id']}/test").json()
    assert r["status"] == "failed" and "500" in r["error"]
    email = client.post(f"{API}/notification-channels", json={"name": "mail", "type": "email",
                                                             "to": ["finops@example.com"]}).json()
    r = client.post(f"{API}/notification-channels/{email['id']}/test").json()
    assert r["status"] == "failed" and "SMTP is not configured" in r["error"]
    assert db.query(Notification).filter(Notification.status == "failed").count() >= 2
    for ch in (c, email):
        client.delete(f"{API}/notification-channels/{ch['id']}")


def test_channel_validation(client):
    assert client.post(f"{API}/notification-channels", json={"name": "a", "type": "slack"}).status_code == 422
    assert client.post(f"{API}/notification-channels", json={"name": "b", "type": "email"}).status_code == 422
    assert client.post(f"{API}/notification-channels",
                       json={"name": "c", "type": "webhook", "url": "ftp://x"}).status_code == 422


# --- reports --------------------------------------------------------------------------


def test_showback_csv_reconciles_with_allocation(client, cluster, db):
    month = utcnow().strftime("%Y-%m")
    r = client.get(f"{API}/clusters/{cluster['id']}/reports/showback.csv",
                   params={"month": month, "aggregate": "label:team"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
    header, *rows = [ln.split(",") for ln in lines]
    total_row = rows[-1]
    body_total = sum(float(r[header.index("total_cost")]) for r in rows[:-1])
    assert float(total_row[header.index("total_cost")]) == pytest.approx(body_total, abs=0.05)
    rep = client.get(f"{API}/clusters/{cluster['id']}/reports/showback", params={"month": month}).json()
    start = datetime.datetime.fromisoformat(rep["period_start"])
    end = datetime.datetime.fromisoformat(rep["period_end"])
    direct = allocation_report(db, db.get(Cluster, cluster["id"]), "", "label:team", "distribute", True,
                               period=(start, end))
    assert rep["total_cost"] == pytest.approx(direct.total_cost, abs=0.01)
    assert {"web", "data", "__idle__"} <= {row["name"] for row in rep["rows"]}


def test_showback_pdf(client, cluster):
    r = client.get(f"{API}/clusters/{cluster['id']}/reports/showback.pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-" and len(r.content) > 1500


@pytest.mark.parametrize("month", ["2026-13", "26-01", "2999-01"])
def test_report_month_validation(client, cluster, month):
    assert client.get(f"{API}/clusters/{cluster['id']}/reports/showback.csv", params={"month": month}).status_code \
        == 422


# --- remediation alerts ---------------------------------------------------------------------


def test_remediation_events_reach_channels(client, webhook):
    c = client.post(f"{API}/clusters", json={"name": "fin-remediation-alerts"}).json()
    agent = {"Authorization": f"Bearer {c['agent_token']}"}
    a = client.post(f"{API}/clusters/{c['id']}/actions", json={
        "namespace": "shop", "workload_kind": "Deployment", "workload_name": "api", "replicas": 1}).json()
    client.get(f"{API}/agent/actions", headers=agent)
    client.post(f"{API}/agent/actions/{a['id']}/result", json={"phase": "dry_run", "ok": True, "diff": {}},
                headers=agent)
    assert any(m["event"] == "remediation" and m["subject"].startswith("Approval needed") for m in webhook)
    client.delete(f"{API}/clusters/{c['id']}")
