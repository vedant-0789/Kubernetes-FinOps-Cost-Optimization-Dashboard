"""Credentials for machine clients.

Agent tokens look like ``kfo_<prefix>_<secret>``. Only SHA-256(token) is
stored; the 8-char prefix locates the row so verification is one indexed
lookup plus a constant-time compare. Tokens are shown exactly once, on
creation or rotation.
"""

import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.platform_models import Cluster

TOKEN_SCHEME = "kfo"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_agent_token() -> tuple[str, str, str]:
    """Returns (token, prefix, sha256-hash)."""
    prefix = secrets.token_hex(4)
    token = f"{TOKEN_SCHEME}_{prefix}_{secrets.token_urlsafe(32)}"
    return token, prefix, hash_token(token)


def _parse_prefix(token: str) -> str | None:
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != TOKEN_SCHEME or len(parts[1]) != 8:
        return None
    return parts[1]


def authenticate_agent(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Cluster:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Invalid or missing agent token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized
    token = authorization[7:].strip()
    prefix = _parse_prefix(token)
    if prefix is None:
        raise unauthorized
    candidate_hash = hash_token(token)
    for cluster in db.query(Cluster).filter(Cluster.token_prefix == prefix).all():
        if hmac.compare_digest(cluster.token_hash, candidate_hash):
            if not cluster.is_active:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Cluster is disabled")
            return cluster
    raise unauthorized
