import logging
import random
import time

import httpx

from finops_agent import __version__

logger = logging.getLogger("agent.http")
RETRYABLE = {408, 429, 500, 502, 503, 504}


class FatalPushError(Exception):
    """Not worth retrying (bad token, disabled cluster, invalid payload)."""


class PrometheusClient:
    def __init__(self, base_url: str, timeout: float = 30.0, http: httpx.Client | None = None):
        self.base_url = base_url
        self.http = http or httpx.Client(timeout=timeout)

    def instant(self, query: str, at: float) -> list[tuple[dict, float]]:
        r = self.http.get(f"{self.base_url}/api/v1/query", params={"query": query, "time": at})
        r.raise_for_status()
        body = r.json()
        if body.get("status") != "success":
            raise RuntimeError(f"Prometheus error: {body.get('error')}")
        return [(item["metric"], float(item["value"][1])) for item in body["data"]["result"]
                if item["value"][1] not in ("NaN", "+Inf", "-Inf")]


class ServerClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0, max_retries: int = 5,
                 http: httpx.Client | None = None, sleep=time.sleep):
        self.base_url = base_url
        self.max_retries = max_retries
        self.sleep = sleep
        self.http = http or httpx.Client(timeout=timeout)
        self.headers = {"Authorization": f"Bearer {token}", "User-Agent": f"kubefinops-agent/{__version__}"}

    def get(self, path: str) -> dict:
        r = self.http.get(f"{self.base_url}{path}", headers=self.headers)
        if r.status_code in (401, 403):
            raise FatalPushError(f"GET {path} -> {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
        return r.json()

    def post(self, path: str, payload: dict) -> dict:
        for attempt in range(self.max_retries + 1):
            try:
                r = self.http.post(f"{self.base_url}{path}", json=payload, headers=self.headers)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise
                logger.warning("POST %s failed (%s); retrying", path, exc.__class__.__name__)
            else:
                if r.status_code < 300:
                    return r.json()
                if r.status_code not in RETRYABLE:
                    raise FatalPushError(f"POST {path} -> {r.status_code}: {r.text[:300]}")
                if attempt == self.max_retries:
                    r.raise_for_status()
                logger.warning("POST %s -> %s; retrying", path, r.status_code)
            # Exponential back-off with jitter: 1, 2, 4, 8... seconds (cap 60).
            self.sleep(min(60.0, 2**attempt) * (0.5 + random.random() / 2))
        raise RuntimeError("unreachable")
