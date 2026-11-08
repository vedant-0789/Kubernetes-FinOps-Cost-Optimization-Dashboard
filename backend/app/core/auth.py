"""User authentication and role-based access control.

* Passwords: PBKDF2-HMAC-SHA256, 600 000 iterations, per-user salt (OWASP 2023).
* Sessions: short-lived HS256 JWTs (``Authorization: Bearer <jwt>``).
* Machine access: the ``X-Admin-Key`` header (automation / bootstrap) acts as
  an admin; agents use their own cluster tokens (``app.core.security``).
* Roles are ordered: viewer < operator < admin.
"""

import base64
import datetime
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.db.platform_models import User, utcnow

logger = logging.getLogger("auth")
ROLES = ("viewer", "operator", "admin")
PBKDF2_ITERATIONS = 600_000
_DEV_SECRET = secrets.token_urlsafe(32)  # per-process fallback for local dev only


@dataclass(frozen=True)
class Principal:
    subject: str          # email, "admin-key" or "anonymous"
    role: str
    user_id: int | None = None

    def has(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)


# --- passwords -----------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iterations))
    return hmac.compare_digest(dk, base64.b64decode(hash_b64))


# --- tokens --------------------------------------------------------------------------


def _secret() -> str:
    return settings.jwt_secret or _DEV_SECRET


def issue_token(user: User) -> tuple[str, datetime.datetime]:
    expires = utcnow() + datetime.timedelta(minutes=settings.jwt_ttl_minutes)
    token = jwt.encode({"sub": user.email, "uid": user.id, "role": user.role,
                        "exp": expires.replace(tzinfo=datetime.UTC), "iat": datetime.datetime.now(datetime.UTC)},
                       _secret(), algorithm="HS256")
    return token, expires


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def get_principal(
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Principal:
    if x_admin_key is not None:
        if settings.admin_api_key and hmac.compare_digest(x_admin_key, settings.admin_api_key):
            return Principal("admin-key", "admin")
        raise _unauthorized("Invalid admin key")
    if authorization and authorization.lower().startswith("bearer "):
        try:
            claims = jwt.decode(authorization[7:].strip(), _secret(), algorithms=["HS256"])
        except jwt.ExpiredSignatureError as exc:
            raise _unauthorized("Token expired") from exc
        except jwt.PyJWTError as exc:
            raise _unauthorized("Invalid token") from exc
        user = db.get(User, claims.get("uid"))
        if user is None or not user.is_active or user.email != claims.get("sub"):
            raise _unauthorized("User disabled or unknown")
        return Principal(user.email, user.role, user.id)  # role from DB: demotions apply immediately
    if not settings.auth_required and settings.admin_api_key is None:
        return Principal("anonymous", "admin")  # local development / tests only
    raise _unauthorized()


def require_role(role: str):
    if role not in ROLES:
        raise ValueError(role)

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.has(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{role}' (you are '{principal.role}')")
        return principal

    return dependency


require_viewer = require_role("viewer")
require_operator = require_role("operator")
require_admin_role = require_role("admin")


def ensure_bootstrap_admin(db: Session) -> None:
    """Create the first admin from settings if there are no users yet."""
    if not (settings.bootstrap_admin_email and settings.bootstrap_admin_password):
        return
    if db.query(User).count() > 0:
        return
    db.add(User(email=settings.bootstrap_admin_email.lower(), name="Administrator", role="admin",
                password_hash=hash_password(settings.bootstrap_admin_password)))
    db.commit()
    logger.info("Bootstrap admin %s created", settings.bootstrap_admin_email)


def check_production_config() -> None:
    if settings.environment == "prod" and settings.auth_required and not settings.jwt_secret:
        raise RuntimeError("FINOPS_JWT_SECRET must be set in production (all API replicas must share it)")
