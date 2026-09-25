from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import deps, events
from ..database import get_db
from ..models import Tag, User, note_tags, notebook_tags
from ..schemas import TagIn, TagOut, TagUsage

router = APIRouter(prefix="/api/tags", tags=["tags"])


def _usage(db: Session, user_id: int) -> list[TagUsage]:
    """Contagens agregadas: uma consulta por lado, nenhuma coleção carregada tag a tag."""
    notebook_counts = dict(
        db.execute(
            select(notebook_tags.c.tag_id, func.count(notebook_tags.c.notebook_id)).group_by(
                notebook_tags.c.tag_id
            )
        ).all()
    )
    note_counts = dict(
        db.execute(
            select(note_tags.c.tag_id, func.count(note_tags.c.note_id)).group_by(note_tags.c.tag_id)
        ).all()
    )
    tags = db.scalars(select(Tag).where(Tag.owner_id == user_id).order_by(Tag.name)).all()
    return [
        TagUsage(
            id=tag.id,
            name=tag.name,
            color=tag.color,
            notebooks_count=notebook_counts.get(tag.id, 0),
            notes_count=note_counts.get(tag.id, 0),
        )
        for tag in tags
    ]


@router.get("", response_model=list[TagUsage])
def list_tags(
    user: User = Depends(deps.current_user), db: Session = Depends(get_db)
) -> list[TagUsage]:
    return _usage(db, user.id)


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(
    payload: TagIn,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> TagOut:
    """Idempotent by name: Ctrl+Space on an existing name returns that tag."""
    existing = db.scalars(
        select(Tag).where(func.lower(Tag.name) == payload.name.lower(), Tag.owner_id == user.id)
    ).one_or_none()
    if existing is not None:
        return TagOut.model_validate(existing)
    tag = Tag(name=payload.name, color=payload.color, owner_id=user.id)
    db.add(tag)
    events.record(db, user, "created", "tag", tag.name)
    db.commit()
    return TagOut.model_validate(tag)


@router.patch("/{tag_id}", response_model=TagOut)
def update_tag(
    tag_id: int,
    payload: TagIn,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> TagOut:
    tag = deps.tag_for(db, user, tag_id)
    tag.name = payload.name
    tag.color = payload.color
    events.record(db, user, "updated", "tag", tag.name)
    db.commit()
    return TagOut.model_validate(tag)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> Response:
    tag = deps.tag_for(db, user, tag_id)
    name = tag.name  # a tag some no delete, então o rótulo sai antes
    db.delete(tag)
    events.record(db, user, "deleted", "tag", name)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
