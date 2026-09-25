from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import acl, deps, services
from ..database import get_db
from ..models import Block, Note, NoteRelation, Notebook, Tag, User
from ..schemas import SearchResults, Stats, empty_counts

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=SearchResults)
def search(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=8, ge=1, le=30),
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> SearchResults:
    return SearchResults(query=q, hits=services.search(db, user.id, q, limit))


@router.get("/stats", response_model=Stats)
def stats(
    user: User = Depends(deps.current_user), db: Session = Depends(get_db)
) -> Stats:
    """Totais do painel: só o que é do dono, nunca o banco inteiro."""
    rows = db.execute(
        select(Block.type, func.count(Block.id))
        .where(Block.note_id.in_(acl.readable_note_ids(user.id)))
        .group_by(Block.type)
    ).all()
    counts = empty_counts()
    for block_type, total in rows:
        counts[block_type] = total
    return Stats(
        notebooks=db.scalar(
            select(func.count(Notebook.id)).where(
                Notebook.id.in_(acl.readable_notebook_ids(user.id))
            )
        )
        or 0,
        notes=db.scalar(
            select(func.count(Note.id)).where(Note.id.in_(acl.readable_note_ids(user.id)))
        )
        or 0,
        blocks=db.scalar(
            select(func.count(Block.id)).where(Block.note_id.in_(acl.readable_note_ids(user.id)))
        )
        or 0,
        tags=db.scalar(select(func.count(Tag.id)).where(Tag.owner_id == user.id)) or 0,
        relations=db.scalar(
            select(func.count(NoteRelation.id)).where(
                NoteRelation.source_id.in_(acl.readable_note_ids(user.id)),
                NoteRelation.target_id.in_(acl.readable_note_ids(user.id)),
            )
        )
        or 0,
        counts=counts,
    )
