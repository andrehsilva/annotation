from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import acl, deps, events, links
from ..database import get_db
from ..models import Block, Note, User
from ..schemas import BlockListItem, BlockOut, BlockPatch, BlockType

router = APIRouter(prefix="/api/blocks", tags=["blocks"])


@router.get("", response_model=list[BlockListItem])
def list_blocks(
    type: BlockType | None = None,
    limit: int = Query(default=300, ge=1, le=1000),
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> list[BlockListItem]:
    """Every block of one kind across all notebooks, newest first, with no grouping."""
    statement = (
        select(Block)
        .options(selectinload(Block.note).selectinload(Note.notebook))
        .where(Block.note_id.in_(acl.readable_note_ids(user.id)))
        .order_by(Block.updated_at.desc(), Block.id.desc())
        .limit(limit)
    )
    if type is not None:
        statement = statement.where(Block.type == type)
    return [
        BlockListItem(
            id=block.id,
            type=block.type,
            text=block.text,
            language=block.language,
            url=block.url,
            caption=block.caption,
            updated_at=block.updated_at,
            note_id=block.note_id,
            note_title=block.note.title,
            notebook_id=block.note.notebook_id,
            notebook_title=block.note.notebook.title,
        )
        for block in db.scalars(statement).all()
    ]


@router.patch("/{block_id}", response_model=BlockOut)
def update_block(
    block_id: int,
    payload: BlockPatch,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> BlockOut:
    block = deps.block_for(db, user, block_id)
    note_title = block.note.title  # sai antes da mutação, caso ela mexa nos vínculos
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(block, field, value)
    links.reindex_block(db, block, user.id)
    events.record(db, user, "updated", "block", note_title)
    db.commit()
    return BlockOut.model_validate(block)


@router.delete("/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(
    block_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> Response:
    block = deps.block_for(db, user, block_id)
    note_id = block.note_id
    note_title = block.note.title  # o bloco some no delete, então o rótulo sai antes
    db.delete(block)
    db.flush()
    survivors = db.scalars(
        select(Block).where(Block.note_id == note_id).order_by(Block.position, Block.id)
    ).all()
    for position, survivor in enumerate(survivors):
        survivor.position = position
    events.record(db, user, "deleted", "block", note_title)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
