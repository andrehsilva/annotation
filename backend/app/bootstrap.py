"""Primeira execução: sem um admin ninguém conseguiria entrar, então um é criado e a senha sai uma vez."""

from __future__ import annotations

import os
import secrets

from . import security, values
from .store import documents, equal, store
from .store.documents import Row

DEFAULT_EMAIL = "admin@notai.local"


def ensure_admin() -> Row:
    """O admin a quem os dados migrados pertencem; criado só quando não existe nenhum."""
    admins = store().list_rows("users", [equal("role", "admin")])
    if admins.total:
        # Mesma escolha de antes (`order_by(User.id).first()`): o admin de menor id.
        return documents.normalize(
            "users", min(admins.rows, key=lambda row: documents.to_int(row["$id"]))
        )
    password = os.environ.get("CADERNO_ADMIN_PASSWORD", "")
    generated = not password
    chosen = password or secrets.token_urlsafe(12)
    admin = documents.write(
        "users",
        documents.record_id("users"),
        {
            "email": os.environ.get("CADERNO_ADMIN_EMAIL", DEFAULT_EMAIL).strip().lower(),
            "display_name": "Admin",
            "password_hash": security.hash_password(chosen),
            "role": "admin",
            "is_active": True,
            "created_at": values.utcnow(),
        },
        owner_id=None,
    )
    if generated:
        print(
            f"[notai] admin criado: {admin.email} / senha {chosen}"
            " — troque com `python manage.py set-password <e-mail>`",
            flush=True,
        )
    return admin
