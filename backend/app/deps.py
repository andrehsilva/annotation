"""Identidade da requisição e os carregadores que respondem 404 para id de outra conta.

404 no lugar de 403 de propósito: o id alheio não pode nem confirmar que o recurso existe.

A sessão mora em `sessions` com o sha256 do token como rowId; quem fornece o Store é `get_db()`,
no lugar da conexão de banco que existia antes.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status

from . import acl, security, values
from .store import Store, documents, store
from .store.documents import Row

COOKIE_NAME = "notai_session"
LAST_SEEN_INTERVAL = timedelta(minutes=1)

NOT_FOUND_NOTEBOOK = "Caderno não encontrado"
NOT_FOUND_NOTE = "Nota não encontrada"
NOT_FOUND_BLOCK = "Bloco não encontrado"
NOT_FOUND_TAG = "Tag não encontrada"
UNAUTHORIZED = "Sessão inválida ou expirada. Entre de novo."


def get_db() -> Iterator[Store]:
    """O Store é um singleton: não há recurso por requisição para abrir nem fechar."""
    yield store()


def cookie_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def session_user_id(request: Request) -> int | None:
    """Identidade para quem está fora do grafo de dependências — o middleware de sync do Drive."""
    token = cookie_token(request)
    if token is None:
        return None
    row = documents.session_by_token_hash(security.hash_token(token))
    if row is None or row.expires_at is None or row.expires_at <= values.utcnow():
        return None
    return row.user_id


def current_user(request: Request, db: Store = Depends(get_db)) -> Row:
    token = cookie_token(request)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, UNAUTHORIZED)
    row = documents.session_by_token_hash(security.hash_token(token))
    if row is None or row.expires_at is None or row.expires_at <= values.utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, UNAUTHORIZED)
    user = documents.get("users", row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, UNAUTHORIZED)
    now = values.utcnow()
    # Sessão migrada pode vir sem `last_seen_at`: sem a checagem, a subtração estouraria.
    if row.last_seen_at is None or now - row.last_seen_at >= LAST_SEEN_INTERVAL:
        documents.change("sessions", row.row_id, {"last_seen_at": now}, owner_id=None)
    return user


def admin_user(user: Row = Depends(current_user)) -> Row:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Só o administrador pode fazer isso")
    return user


def notebook_for(db: Store, user: Row, notebook_id: int, minimum: str = "editor") -> Row:
    notebook = documents.get("notebooks", notebook_id)
    if notebook is None or not acl.allows(acl.role_for(db, user.id, notebook_id), minimum):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_NOTEBOOK)
    return notebook


def note_for(db: Store, user: Row, note_id: int, minimum: str = "editor") -> Row:
    note = documents.get("notes", note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_NOTE)
    notebook_for(db, user, note.notebook_id, minimum)
    return note


def block_for(db: Store, user: Row, block_id: int, minimum: str = "editor") -> Row:
    block = documents.get("blocks", block_id)
    if block is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_BLOCK)
    note_for(db, user, block.note_id, minimum)
    return block


def tag_for(db: Store, user: Row, tag_id: int) -> Row:
    tag = documents.get("tags", tag_id)
    if tag is None or tag.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_TAG)
    return tag
