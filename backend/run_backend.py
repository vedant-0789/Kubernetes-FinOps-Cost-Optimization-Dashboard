"""Local development server (SQLite, demo cluster, auto-reload).

On first run it writes ``backend/.env`` (git-ignored) with a random JWT secret
and a random password for the local admin account, so the UI can be signed
into without any manual setup. Production deployments (docker-compose, Helm)
never use this file.
"""

import os
import secrets
import sys
from pathlib import Path

import uvicorn

BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"
DEV_ADMIN_EMAIL = "admin@kubefinops.localhost"


def ensure_dev_env() -> None:
    if ENV_FILE.exists():
        return
    ENV_FILE.write_text(
        "# Local development only (created by run_backend.py, git-ignored).\n"
        "FINOPS_ENVIRONMENT=dev\n"
        f"FINOPS_JWT_SECRET={secrets.token_urlsafe(48)}\n"
        f"FINOPS_BOOTSTRAP_ADMIN_EMAIL={DEV_ADMIN_EMAIL}\n"
        f"FINOPS_BOOTSTRAP_ADMIN_PASSWORD={secrets.token_urlsafe(12)}\n",
        encoding="utf-8",
    )
    print(f"Created {ENV_FILE} with a local admin account.")


if __name__ == "__main__":
    os.chdir(BACKEND_DIR)              # settings read .env from the working directory
    sys.path.insert(0, str(BACKEND_DIR))
    ensure_dev_env()
    print("Starting KubeFinOps API on http://127.0.0.1:8000 (docs: /docs)")
    print(f"Sign in to the UI as {DEV_ADMIN_EMAIL}; the password is FINOPS_BOOTSTRAP_ADMIN_PASSWORD in {ENV_FILE}")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
