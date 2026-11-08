from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_admin_role, require_viewer
from app.core.security import new_agent_token
from app.db.database import get_db
from app.db.platform_models import Cluster
from app.schemas.platform import ClusterCreate, ClusterOut, ClusterWithToken
from app.services import audit

router = APIRouter(prefix="/clusters", tags=["Clusters"])


def get_cluster_or_404(cluster_id: str, db: Session) -> Cluster:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cluster not found")
    return cluster


@router.post("", response_model=ClusterWithToken, status_code=status.HTTP_201_CREATED,
             summary="Register a cluster and issue its agent token (shown once)")
def create_cluster(body: ClusterCreate, db: Session = Depends(get_db),
                   p: Principal = Depends(require_admin_role)):
    if db.query(Cluster).filter(Cluster.name == body.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cluster '{body.name}' already exists")
    token, prefix, token_hash = new_agent_token()
    cluster = Cluster(**body.model_dump(), token_prefix=prefix, token_hash=token_hash)
    db.add(cluster)
    db.flush()
    audit.record(db, p.subject, "cluster.create", cluster_id=cluster.id, target=cluster.name,
                 details={"provider": cluster.provider, "region": cluster.region})
    db.commit()
    db.refresh(cluster)
    return ClusterWithToken(**ClusterOut.model_validate(cluster).model_dump(), agent_token=token)


@router.get("", response_model=list[ClusterOut])
def list_clusters(db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    return db.query(Cluster).order_by(Cluster.name).all()


@router.get("/{cluster_id}", response_model=ClusterOut)
def get_cluster(cluster_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    return get_cluster_or_404(cluster_id, db)


@router.post("/{cluster_id}/rotate-token", response_model=ClusterWithToken,
             summary="Issue a new agent token; the old one stops working immediately")
def rotate_token(cluster_id: str, db: Session = Depends(get_db), p: Principal = Depends(require_admin_role)):
    cluster = get_cluster_or_404(cluster_id, db)
    audit.record(db, p.subject, "cluster.rotate_token", cluster_id=cluster.id, target=cluster.name)
    token, prefix, token_hash = new_agent_token()
    cluster.token_prefix, cluster.token_hash = prefix, token_hash
    db.commit()
    db.refresh(cluster)
    return ClusterWithToken(**ClusterOut.model_validate(cluster).model_dump(), agent_token=token)


@router.post("/{cluster_id}/disable", response_model=ClusterOut)
def disable_cluster(cluster_id: str, db: Session = Depends(get_db), p: Principal = Depends(require_admin_role)):
    cluster = get_cluster_or_404(cluster_id, db)
    audit.record(db, p.subject, "cluster.disable", cluster_id=cluster.id, target=cluster.name)
    cluster.is_active = False
    db.commit()
    db.refresh(cluster)
    return cluster


@router.post("/{cluster_id}/enable", response_model=ClusterOut)
def enable_cluster(cluster_id: str, db: Session = Depends(get_db), p: Principal = Depends(require_admin_role)):
    cluster = get_cluster_or_404(cluster_id, db)
    audit.record(db, p.subject, "cluster.enable", cluster_id=cluster.id, target=cluster.name)
    cluster.is_active = True
    db.commit()
    db.refresh(cluster)
    return cluster


@router.delete("/{cluster_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a cluster and its inventory (time-series rows age out via retention)")
def delete_cluster(cluster_id: str, db: Session = Depends(get_db), p: Principal = Depends(require_admin_role)):
    cluster = get_cluster_or_404(cluster_id, db)
    audit.record(db, p.subject, "cluster.delete", cluster_id=cluster.id, target=cluster.name)
    db.delete(cluster)
    db.commit()
