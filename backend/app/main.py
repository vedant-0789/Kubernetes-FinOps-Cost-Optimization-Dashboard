import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.observability import RequestContextMiddleware
from app.db.database import SessionLocal
from app.engine.mock_generator import MockDataGenerator
from app.engine.scheduler import start_scheduler, stop_scheduler
from app.routers import (
    actions,
    allocation,
    analysis,
    clusters,
    health,
    ingest,
    lifecycle,
    namespaces,
    overview,
    recommendations,
    zombies,
)
from app.routers import settings as settings_router

API_V1 = "/api/v1"
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_migrate:
        from app.db.migrate import upgrade_head

        logger.info("Applying database migrations...")
        upgrade_head(settings.database_url)

    if settings.environment == "prod" and settings.admin_api_key is None:
        logger.warning("FINOPS_ADMIN_API_KEY is not set: cluster registry endpoints are unauthenticated")

    if settings.seed_demo_data:
        from app.services.allocation_job import run_allocation
        from app.services.demo import ensure_demo_cluster

        db = SessionLocal()
        try:
            MockDataGenerator.seed_initial_data(db)
            ensure_demo_cluster(db, settings.demo_backfill_days)
            run_allocation(db)
            from app.services.analysis import run_analysis

            run_analysis(db)
        finally:
            db.close()

    if settings.run_scheduler_in_api:
        start_scheduler(settings.collection_interval_seconds)
    logger.info("%s API ready (env=%s)", settings.project_name, settings.environment)
    yield
    if settings.run_scheduler_in_api:
        stop_scheduler()


def create_app() -> FastAPI:
    configure_logging(settings.log_level, settings.log_json)
    app = FastAPI(
        title=f"{settings.project_name} API",
        description=(
            "Kubernetes FinOps platform: cost allocation, waste detection, "
            "SLO-aware right-sizing and safe automated remediation."
        ),
        version=settings.version,
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    for r in (overview, namespaces, zombies, recommendations, actions, lifecycle, settings_router,
              clusters, ingest, allocation, analysis):
        app.include_router(r.router, prefix=API_V1)

    @app.get("/", include_in_schema=False)
    def root():
        return {"service": settings.project_name, "version": settings.version, "docs": "/docs"}

    return app


app = create_app()
