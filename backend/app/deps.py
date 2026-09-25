"""Request identity plus the loaders that answer somebody else's id with a 404.

404 instead of 403 on purpose: a stranger's id must not even confirm that the resource exists.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import acl, security
from .database import SessionLocal, get_db
from .models import Block, Note, Notebook, SessionToken, Tag, User, utcnow

COOKIE_NAME = "notai_session"
LAST_SEEN_INTERVAL = timedelta(minutes=1)

NOT_FOUND_NOTEBOOK = "Caderno não encontrado"
NOT_FOUND_NOTE = "Nota não encontrada"
NOT_FOUND_BLOCK = "Bloco não encontrado"
NOT_FOUND_TAG = "Tag não encontrada"
UNAUTHORIZED = "Sessão inválida ou expirada. Entre de novo."


def cookie_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def session_user_id(request: Request) -> int | None:
    """Identity for callers outside the dependency graph — the Drive sync middleware."""
    token = cookie_token(request)
    if token is None:
        return None
    with SessionLocal() as db:
        row = db.get(SessionToken, security.hash_token(token))
        if row is None or row.expires_at <= utcnow():
            return None
        return row.user_id


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = cookie_token(request)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, UNAUTHORIZED)
    row = db.get(SessionToken, security.hash_token(token))
    if row is None or row.expires_at <= utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, UNAUTHORIZED)
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, UNAUTHORIZED)
    now = utcnow()
    if now - row.last_seen_at >= LAST_SEEN_INTERVAL:
        row.last_seen_at = now
        db.commit()
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Só o administrador pode fazer isso")
    return user


def notebook_for(db: Session, user: User, notebook_id: int, minimum: str = "editor") -> Notebook:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or not acl.allows(acl.role_for(db, user.id, notebook_id), minimum):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_NOTEBOOK)
    return notebook


def note_for(db: Session, user: User, note_id: int, minimum: str = "editor") -> Note:
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_NOTE)
    notebook_for(db, user, note.notebook_id, minimum)
    return note


def block_for(db: Session, user: User, block_id: int, minimum: str = "editor") -> Block:
    block = db.get(Block, block_id)
    if block is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_BLOCK)
    note_for(db, user, block.note_id, minimum)
    return block


def tag_for(db: Session, user: User, tag_id: int) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None or tag.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_TAG)
    return tag
