from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import authenticate_agent
from app.db.database import get_db
from app.db.platform_models import Cluster
from app.schemas.platform import IngestResult, InventoryIn, SamplesIn
from app.services.ingestion import ingest_inventory, ingest_samples

router = APIRouter(prefix="/ingest", tags=["Agent ingestion"])


@router.post("/inventory", response_model=IngestResult,
             summary="Agent pushes nodes and workload owners (idempotent upsert)")
def post_inventory(body: InventoryIn, cluster: Cluster = Depends(authenticate_agent), db: Session = Depends(get_db)):
    return ingest_inventory(db, cluster, body)


@router.post("/samples", response_model=IngestResult,
             summary="Agent pushes container usage samples (re-sent windows are ignored)")
def post_samples(body: SamplesIn, cluster: Cluster = Depends(authenticate_agent), db: Session = Depends(get_db)):
    if len(body.samples) + len(body.node_samples) > settings.max_samples_per_request:
        raise HTTPException(
            413,
            f"At most {settings.max_samples_per_request} samples per request; split the batch.",
        )
    return ingest_samples(db, cluster, body.samples, node_samples=body.node_samples)
