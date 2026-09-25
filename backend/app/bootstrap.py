"""First run: without an admin nobody could log in, so one is created and the password is shown once."""

from __future__ import annotations

import os
import secrets

from sqlalchemy import select

from . import security
from .database import SessionLocal
from .models import User

DEFAULT_EMAIL = "admin@notai.local"


def ensure_admin() -> User:
    """The admin the migrated data belongs to; created only when there is none."""
    password = os.environ.get("CADERNO_ADMIN_PASSWORD", "")
    with SessionLocal() as db:
        admin = db.scalars(select(User).where(User.role == "admin").order_by(User.id)).first()
        if admin is not None:
            return admin
        generated = not password
        chosen = password or secrets.token_urlsafe(12)
        admin = User(
            email=os.environ.get("CADERNO_ADMIN_EMAIL", DEFAULT_EMAIL).strip().lower(),
            display_name="Admin",
            password_hash=security.hash_password(chosen),
            role="admin",
        )
        db.add(admin)
        db.commit()
        if generated:
            print(
                f"[notai] admin criado: {admin.email} / senha {chosen}"
                " — troque com `python manage.py set-password <e-mail>`",
                flush=True,
            )
        return admin
