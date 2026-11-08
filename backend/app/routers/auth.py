import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth import (
    Principal,
    get_principal,
    hash_password,
    issue_token,
    require_admin_role,
    require_viewer,
    verify_password,
)
from app.db.database import get_db
from app.db.platform_models import AuditEvent, User, utcnow
from app.services import audit

router = APIRouter(tags=["Auth & users"])
Role = Literal["viewer", "operator", "admin"]


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime.datetime
    role: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime.datetime
    last_login_at: datetime.datetime | None


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(default="", max_length=120)
    password: str = Field(min_length=12, max_length=200, description="At least 12 characters")
    role: Role = "viewer"


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=200)


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime.datetime
    actor: str
    action: str
    cluster_id: str | None
    target: str | None
    details: dict
    hash: str


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    # Same error and comparable work whether the user exists or not.
    ok = verify_password(body.password, user.password_hash if user else hash_password("x" * 12))
    if not user or not ok or not user.is_active:
        audit.record(db, body.email.lower(), "auth.login_failed", commit=True)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    user.last_login_at = utcnow()
    audit.record(db, user.email, "auth.login")
    db.commit()
    token, expires = issue_token(user)
    return TokenOut(access_token=token, expires_at=expires, role=user.role)


@router.get("/auth/me")
def me(principal: Principal = Depends(get_principal)):
    return {"subject": principal.subject, "role": principal.role, "user_id": principal.user_id}


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: Principal = Depends(require_admin_role)):
    return db.query(User).order_by(User.email).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), p: Principal = Depends(require_admin_role)):
    email = body.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "User already exists")
    user = User(email=email, name=body.name, role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    audit.record(db, p.subject, "user.create", target=email, details={"role": body.role})
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                p: Principal = Depends(require_admin_role)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_unset=True)
    if user.id == p.user_id and (changes.get("role", "admin") != "admin" or changes.get("is_active") is False):
        raise HTTPException(400, "You cannot demote or disable yourself")
    if "password" in changes:
        user.password_hash = hash_password(changes.pop("password"))
        changes["password"] = "changed"
    for k, v in changes.items():
        if k != "password":
            setattr(user, k, v)
    audit.record(db, p.subject, "user.update", target=user.email, details=changes)
    db.commit()
    db.refresh(user)
    return user


@router.get("/audit", response_model=list[AuditOut])
def list_audit(cluster_id: str | None = None, action: str | None = None, limit: int = Query(200, ge=1, le=1000),
               db: Session = Depends(get_db), _: Principal = Depends(require_viewer)):
    q = db.query(AuditEvent)
    if cluster_id:
        q = q.filter(AuditEvent.cluster_id == cluster_id)
    if action:
        q = q.filter(AuditEvent.action.like(f"{action}%"))
    return q.order_by(AuditEvent.id.desc()).limit(limit).all()


@router.get("/audit/verify", summary="Recompute the hash chain; detects edited or deleted events")
def verify_audit(db: Session = Depends(get_db), _: Principal = Depends(require_admin_role)):
    return audit.verify_chain(db)
