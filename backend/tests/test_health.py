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


def test_metrics_use_route_templates_not_raw_ids(client):
    client.post("/api/v1/zombies/987654/remediate")  # 404, but still measured
    body = client.get("/metrics").text
    assert 'route="/api/v1/zombies/{id}/remediate"' in body
    assert "987654" not in body


def test_route_templates_prefer_literal_segments():
    from app.core.observability import _RouteTemplates

    t = _RouteTemplates(["/api/v1/namespaces/{name}/pods", "/api/v1/namespaces/{name}", "/api/v1/namespaces/top"])
    assert t.match("/api/v1/namespaces/top") == "/api/v1/namespaces/top"
    assert t.match("/api/v1/namespaces/prod") == "/api/v1/namespaces/{name}"
    assert t.match("/api/v1/namespaces/prod/pods") == "/api/v1/namespaces/{name}/pods"
    assert t.match("/nope") == "unmatched"
