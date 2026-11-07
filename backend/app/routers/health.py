from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db

router = APIRouter(tags=["Health"])


@router.get("/healthz", summary="Liveness probe")
def healthz():
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe (checks the database)")
def readyz(response: Response, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised only when DB is down
        response.status_code = 503
        return {"status": "unavailable", "database": str(exc.__class__.__name__)}
    return {"status": "ready", "database": "ok", "version": settings.version}


@router.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
