def test_liveness(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readiness_checks_database(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"


def test_request_id_is_propagated(client):
    r = client.get("/healthz", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


def test_prometheus_metrics_exposed(client):
    client.get("/api/v1/overview")
    body = client.get("/metrics").text
    assert "finops_http_requests_total" in body
    # Route templates, not raw paths, keep label cardinality bounded.
    assert 'route="/api/v1/overview"' in body
