import pytest

from app.core.auth import check_production_config, ensure_bootstrap_admin, hash_password, verify_password
from app.core.config import settings
from app.db.platform_models import AuditEvent, User
from tests.helpers_auth import PASSWORD, ensure_user, login

API = "/api/v1"


def test_password_hashing_is_salted_and_verifiable():
    a, b = hash_password("s3cret-password!"), hash_password("s3cret-password!")
    assert a != b and a.startswith("pbkdf2_sha256$600000$")
    assert verify_password("s3cret-password!", a) and not verify_password("wrong", a)
    assert not verify_password("x", "garbage")


def test_unauthenticated_requests_are_rejected(client, auth_on):
    assert client.get(f"{API}/clusters").status_code == 401
    assert client.get(f"{API}/clusters", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_login_and_roles(client, db, auth_on):
    ensure_user(db, "viewer@example.com", "viewer")
    ensure_user(db, "admin@example.com", "admin")
    viewer = login(client, "viewer@example.com")
    assert client.get(f"{API}/auth/me", headers=viewer).json()["role"] == "viewer"
    assert client.get(f"{API}/clusters", headers=viewer).status_code == 200
    assert client.post(f"{API}/clusters", json={"name": "nope"}, headers=viewer).status_code == 403
    assert client.get(f"{API}/users", headers=viewer).status_code == 403
    assert client.get(f"{API}/users", headers=login(client, "admin@example.com")).status_code == 200


def test_bad_password_is_rejected_and_audited(client, db, auth_on):
    ensure_user(db, "viewer@example.com", "viewer")
    r = client.post(f"{API}/auth/login", json={"email": "viewer@example.com", "password": "wrong"})
    assert r.status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": "ghost@example.com", "password": "x"}).status_code == 401
    last = db.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
    assert last.action == "auth.login_failed"


def test_demotion_and_disabling_apply_immediately(client, db, auth_on):
    user = ensure_user(db, "op@example.com", "operator")
    headers = login(client, "op@example.com")
    user.role = "viewer"
    db.commit()
    assert client.get(f"{API}/auth/me", headers=headers).json()["role"] == "viewer"
    user.is_active = False
    db.commit()
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 401


def test_expired_token(client, db, auth_on, monkeypatch):
    ensure_user(db, "viewer@example.com", "viewer")
    monkeypatch.setattr(settings, "jwt_ttl_minutes", -1)
    headers = login(client, "viewer@example.com")
    r = client.get(f"{API}/auth/me", headers=headers)
    assert r.status_code == 401 and r.json()["detail"] == "Token expired"


def test_user_management(client, db, auth_on):
    admin = ensure_user(db, "admin@example.com", "admin")
    headers = login(client, "admin@example.com")
    r = client.post(f"{API}/users", json={"email": "new@example.com", "password": "short"}, headers=headers)
    assert r.status_code == 422  # min 12 characters
    r = client.post(f"{API}/users", json={"email": "new.user@example.com", "password": "long-enough-pass",
                                          "role": "operator"}, headers=headers)
    assert r.status_code in (201, 409)
    assert client.patch(f"{API}/users/{admin.id}", json={"role": "viewer"}, headers=headers).status_code == 400


def test_admin_key_is_an_admin(client, monkeypatch, auth_on):
    monkeypatch.setattr(settings, "admin_api_key", "k3y")
    assert client.get(f"{API}/users", headers={"X-Admin-Key": "k3y"}).status_code == 200
    assert client.get(f"{API}/users", headers={"X-Admin-Key": "wrong"}).status_code == 401


def test_bootstrap_admin_only_when_no_users(db, monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", "boot@example.com")
    monkeypatch.setattr(settings, "bootstrap_admin_password", PASSWORD)
    before = db.query(User).count()
    ensure_bootstrap_admin(db)
    created = db.query(User).filter(User.email == "boot@example.com").first()
    assert (created is not None) == (before == 0)


def test_production_requires_a_jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "auth_required", True)
    monkeypatch.setattr(settings, "jwt_secret", None)
    with pytest.raises(RuntimeError):
        check_production_config()
