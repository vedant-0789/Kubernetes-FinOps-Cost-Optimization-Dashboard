"""Request-ID propagation and Prometheus metrics for the API itself.

The platform that measures cluster efficiency should itself be observable:
`/metrics` is scraped by the same Prometheus that the agent queries.
"""

import re
import time
import uuid

from prometheus_client import Counter, Histogram

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


_PARAM = re.compile(r"\{[^}/]+\}")


class _RouteTemplates:
    """Maps a raw request path to its full route template (/api/v1/zombies/{id}).

    Built from the app's OpenAPI paths: a public, version-stable source of full
    templates. (How routers store their prefix internally changed between
    FastAPI releases, so reading route objects is not reliable.) Literal
    segments are preferred over parameters when both match.
    """

    def __init__(self, templates):
        compiled = []
        for t in templates:
            regex = "^" + _PARAM.sub("[^/]+", re.escape(t).replace(r"\{", "{").replace(r"\}", "}")) + "$"
            compiled.append((t.count("{"), re.compile(regex), t))
        self._compiled = sorted(compiled, key=lambda c: c[0])

    def match(self, path: str) -> str:
        for _, regex, template in self._compiled:
            if regex.match(path):
                return template
        return "unmatched"


class RequestContextMiddleware:
    """Pure ASGI middleware (not BaseHTTPMiddleware): the router writes the
    matched route into the *same* scope dict we hold, so we can label metrics
    by route template (/api/v1/zombies/{id}) instead of raw path, keeping
    Prometheus label cardinality bounded. It also avoids BaseHTTPMiddleware's
    per-request task overhead."""

    def __init__(self, app):
        self.app = app
        self._templates: _RouteTemplates | None = None

    def _route_template(self, scope) -> str:
        if self._templates is None:
            fastapi_app = scope.get("app")
            paths = list(fastapi_app.openapi().get("paths", {})) if hasattr(fastapi_app, "openapi") else []
            self._templates = _RouteTemplates(paths + ["/metrics", "/"])
        return self._templates.match(scope.get("path", ""))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        rid = headers.get(b"x-request-id", b"").decode("latin-1") or uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", rid.encode("latin-1"))]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = self._route_template(scope)
            method = scope.get("method", "GET")
            HTTP_REQUESTS.labels(method, route, str(status)).inc()
            HTTP_LATENCY.labels(method, route).observe(time.perf_counter() - start)
            request_id_ctx.reset(token)
