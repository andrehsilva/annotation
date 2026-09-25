"""User administration. Every route here is admin-only, and the account that acts can't lock itself out."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import acl, drive, events
from ..database import MEDIA_DIR, get_db
from ..deps import admin_user
from ..models import (
    Block,
    MediaFile,
    Note,
    Notebook,
    SessionToken,
    User,
    notebook_members,
)
from ..schemas import AdminPasswordIn, AdminUserOut, UserCreateIn, UserOut, UserUpdateIn
from ..security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _summary(db: Session, user: User) -> AdminUserOut:
    readable = acl.readable_notebook_ids(user.id)
    notebooks = db.scalar(
        select(func.count()).select_from(notebook_members).where(notebook_members.c.user_id == user.id)
    )
    notes = db.scalar(select(func.count(Note.id)).where(Note.notebook_id.in_(readable)))
    blocks = db.scalar(
        select(func.count(Block.id)).join(Note, Block.note_id == Note.id).where(Note.notebook_id.in_(readable))
    )
    media_bytes = db.scalar(
        select(func.coalesce(func.sum(MediaFile.size), 0)).where(MediaFile.owner_id == user.id)
    )
    return AdminUserOut(
        **UserOut.model_validate(user).model_dump(),
        notebooks=notebooks or 0,
        notes=notes or 0,
        blocks=blocks or 0,
        media_bytes=media_bytes or 0,
    )


def _load(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")
    return user


def _other_active_admin(db: Session, user_id: int) -> bool:
    return (
        db.scalar(
            select(func.count(User.id)).where(
                User.role == "admin", User.is_active.is_(True), User.id != user_id
            )
        )
        or 0
    ) > 0


@router.get("/users", response_model=list[AdminUserOut])
def list_users(db: Session = Depends(get_db), _admin: User = Depends(admin_user)) -> list[AdminUserOut]:
    users = db.scalars(select(User).order_by(User.email)).all()
    return [_summary(db, user) for user in users]


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateIn, db: Session = Depends(get_db), admin: User = Depends(admin_user)
) -> AdminUserOut:
    existing = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe um usuário com esse e-mail")
    user = User(
        email=payload.email,
        display_name=payload.display_name or payload.email.split("@")[0],
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    events.record(db, admin, "created", "user", user.email)
    db.commit()
    return _summary(db, user)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    payload: UserUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_user),
) -> AdminUserOut:
    user = _load(db, user_id)
    demoting = payload.role is not None and payload.role != "admin" and user.role == "admin"
    disabling = payload.is_active is False and user.is_active
    if user.id == admin.id and (demoting or disabling):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Você não pode rebaixar nem desativar a própria conta"
        )
    if (demoting or disabling) and not _other_active_admin(db, user.id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Esse é o último admin ativo; promova outro antes"
        )
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if not payload.is_active:
            db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
    events.record(db, admin, "updated", "user", user.email)
    db.commit()
    return _summary(db, user)


@router.post("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: int,
    payload: AdminPasswordIn,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_user),
) -> Response:
    user = _load(db, user_id)
    user.password_hash = hash_password(payload.password)
    db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
    events.record(db, admin, "reset", "user", user.email)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int, db: Session = Depends(get_db), admin: User = Depends(admin_user)
) -> Response:
    """Takes the user's data with it: their notebooks (whole tree) and their uploaded files."""
    user = _load(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não pode apagar a própria conta")
    if user.role == "admin" and user.is_active and not _other_active_admin(db, user.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esse é o último admin ativo")

    memberships = db.execute(
        select(notebook_members.c.notebook_id).where(notebook_members.c.user_id == user.id)
    ).scalars().all()
    for notebook_id in memberships:
        others = db.execute(
            select(notebook_members.c.user_id, notebook_members.c.role)
            .where(notebook_members.c.notebook_id == notebook_id, notebook_members.c.user_id != user.id)
            .order_by(notebook_members.c.user_id)
        ).all()
        if not others:
            db.execute(delete(Notebook).where(Notebook.id == notebook_id))
            continue
        # Shared notebook: hand it to the oldest remaining member instead of deleting their work.
        db.execute(
            delete(notebook_members).where(
                notebook_members.c.notebook_id == notebook_id,
                notebook_members.c.user_id == user.id,
            )
        )
        if not any(role == "owner" for _member_id, role in others):
            db.execute(
                notebook_members.update()
                .where(
                    notebook_members.c.notebook_id == notebook_id,
                    notebook_members.c.user_id == others[0][0],
                )
                .values(role="owner")
            )

    files = db.scalars(select(MediaFile.filename).where(MediaFile.owner_id == user.id)).all()
    email = user.email  # o usuário some no delete, então o rótulo sai antes
    db.delete(user)
    events.record(db, admin, "deleted", "user", email)
    db.commit()
    for filename in files:
        (MEDIA_DIR / filename).unlink(missing_ok=True)
    drive.forget_files(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
