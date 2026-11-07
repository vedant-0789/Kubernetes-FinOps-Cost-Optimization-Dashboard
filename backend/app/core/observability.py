"""Request-ID propagation and Prometheus metrics for the API itself.

The platform that measures cluster efficiency should itself be observable:
`/metrics` is scraped by the same Prometheus that the agent queries.
"""

import time
import uuid

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import request_id_ctx

HTTP_REQUESTS = Counter(
    "finops_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "finops_http_request_duration_seconds", "HTTP request latency", ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
JOB_RUNS = Counter("finops_job_runs_total", "Background job runs", ["job", "outcome"])
JOB_DURATION = Histogram("finops_job_duration_seconds", "Background job duration", ["job"])


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = rid
            return response
        finally:
            # Use the route template (/api/v1/zombies/{id}) not the raw path,
            # so metric cardinality stays bounded.
            route = request.scope.get("route")
            route_label = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(request.method, route_label, str(status)).inc()
            HTTP_LATENCY.labels(request.method, route_label).observe(time.perf_counter() - start)
            request_id_ctx.reset(token)
