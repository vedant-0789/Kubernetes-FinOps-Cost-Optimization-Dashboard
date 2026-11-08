"""Tamper-evident audit trail (hash chain).

hash_n = SHA-256(hash_{n-1} || canonical-JSON(ts, actor, action, cluster, target, details))

Any edit, deletion or reordering of past rows breaks the chain, which
``verify_chain`` reports with the first bad event id. On PostgreSQL a
transaction-scoped advisory lock serialises appends across API replicas.
"""

import hashlib
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.platform_models import AuditEvent, utcnow

GENESIS = "0" * 64
_LOCK_KEY = 7_241_993_002


def _digest(prev_hash: str, ts, actor, action, cluster_id, target, details) -> str:
    body = json.dumps({"ts": ts.isoformat(timespec="microseconds"), "actor": actor, "action": action,
                       "cluster_id": cluster_id, "target": target, "details": details},
                      sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def record(db: Session, actor: str, action: str, *, cluster_id: str | None = None, target: str | None = None,
           details: dict | None = None, commit: bool = False) -> AuditEvent:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    last = db.query(AuditEvent.hash).order_by(AuditEvent.id.desc()).first()
    prev = last[0] if last else GENESIS
    ts = utcnow()
    details = json.loads(json.dumps(details or {}, default=str))  # store exactly what was hashed
    event = AuditEvent(ts=ts, actor=actor, action=action, cluster_id=cluster_id, target=target, details=details,
                       prev_hash=prev, hash=_digest(prev, ts, actor, action, cluster_id, target, details))
    db.add(event)
    db.flush()
    if commit:
        db.commit()
    return event


def verify_chain(db: Session) -> dict:
    prev, count = GENESIS, 0
    for e in db.query(AuditEvent).order_by(AuditEvent.id).yield_per(1000):
        expected = _digest(prev, e.ts, e.actor, e.action, e.cluster_id, e.target, e.details)
        if e.prev_hash != prev or e.hash != expected:
            return {"valid": False, "events_checked": count, "first_invalid_id": e.id}
        prev, count = e.hash, count + 1
    return {"valid": True, "events_checked": count, "first_invalid_id": None}
