# syntax=docker/dockerfile:1.7
# One image, three roles: API (default), worker (`python -m app.worker`),
# migrations (`alembic upgrade head`).

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FINOPS_ENVIRONMENT=prod \
    FINOPS_LOG_JSON=true
RUN groupadd --system --gid 10001 finops && useradd --system --uid 10001 --gid finops --no-create-home finops
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=finops:finops alembic.ini ./
COPY --chown=finops:finops migrations ./migrations
COPY --chown=finops:finops app ./app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
