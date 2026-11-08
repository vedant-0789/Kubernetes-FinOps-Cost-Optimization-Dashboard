from app.core.auth import hash_password
from app.db.platform_models import User

PASSWORD = "correct-horse-battery"


def ensure_user(db, email, role):
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, name=email.split("@")[0], role=role, password_hash=hash_password(PASSWORD))
        db.add(user)
    user.role, user.is_active = role, True
    db.commit()
    return user


def login(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
