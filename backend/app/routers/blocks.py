from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from .. import deps, events, links
from ..schemas import BlockListItem, BlockOut, BlockPatch, BlockType
from ..store import documents, store
from ..store.client import Store, equal

router = APIRouter(prefix="/api/blocks", tags=["blocks"])


def _blocks_of(db: Store, user_id: int, note_id: int) -> list[documents.Row]:
    """Os blocos da nota na ordem de `position` (mesmo desempate que o antigo `note.blocks`)."""
    rows = [block for block in db.snapshot(user_id)["blocks"] if block.note_id == note_id]
    return sorted(rows, key=lambda block: (block.position, block.id))


@router.get("", response_model=list[BlockListItem])
def list_blocks(
    type: BlockType | None = None,
    limit: int = Query(default=300, ge=1, le=1000),
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> list[BlockListItem]:
    """Every block of one kind across all notebooks, newest first, with no grouping."""
    photo = db.snapshot(user.id)
    notes = {note.id: note for note in photo["notes"]}
    titles = {notebook.id: notebook.title for notebook in photo["notebooks"]}
    blocks = [block for block in photo["blocks"] if block.note_id in notes]
    if type is not None:
        blocks = [block for block in blocks if block.type == type]
    blocks.sort(key=lambda block: (block.updated_at, block.id), reverse=True)
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
            note_title=notes[block.note_id].title,
            notebook_id=notes[block.note_id].notebook_id,
            notebook_title=titles.get(notes[block.note_id].notebook_id, ""),
        )
        for block in blocks[:limit]
    ]


@router.patch("/{block_id}", response_model=BlockOut)
def update_block(
    block_id: int,
    payload: BlockPatch,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> BlockOut:
    block = deps.block_for(db, user, block_id)
    # o rótulo do evento sai antes da mutação, que logo abaixo mexe nos vínculos do bloco
    note_title = documents.get("notes", block.note_id).title
    fields = payload.model_dump(exclude_unset=True)
    with store().transaction() as tx:
        if fields:
            fields["updated_at"] = documents.now()
            block = documents.change("blocks", block_id, fields, owner_id=user.id, transaction_id=tx)
        links.reindex_block(db, block, user.id, tx)
        store().stage(tx, [events.operation(user.id, "updated", "block", note_title)])
    store().invalidate(user.id)
    return BlockOut.model_validate(block)


@router.delete("/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(
    block_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> Response:
    block = deps.block_for(db, user, block_id)
    note_id = block.note_id
    note_title = documents.get("notes", note_id).title  # o bloco some, então o rótulo sai antes
    with store().transaction() as tx:
        db.delete_where("block_links", [equal("block_id", str(block_id))])
        documents.remove("blocks", block_id, owner_id=user.id)
        # o buraco na ordem fecha: os sobreviventes voltam a ser 0..n-1, como antes
        for position, survivor in enumerate(_blocks_of(db, user.id, note_id)):
            if survivor.position != position:
                documents.change(
                    "blocks",
                    survivor.id,
                    {"position": position, "updated_at": documents.now()},
                    owner_id=user.id,
                    transaction_id=tx,
                )
        store().stage(tx, [events.operation(user.id, "deleted", "block", note_title)])
    store().invalidate(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
