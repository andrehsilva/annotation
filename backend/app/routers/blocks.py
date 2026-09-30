from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from .. import acl, deps, events, links, services
from ..schemas import BlockListItem, BlockOut, BlockPatch, BlockType
from ..store import documents, store
from ..store.client import Store, equal

router = APIRouter(prefix="/api/blocks", tags=["blocks"])

# `editor` escreve à vontade na nota compartilhada, mas o bloco de outra conta é leitura: o conteúdo
# responde por quem o escreveu, e a mensagem diz o que fazer em vez de só recusar.
NOT_THE_AUTHOR = "Só quem escreveu este bloco pode mudá-lo ou apagá-lo. Copie o trecho para um bloco seu."


def _require_author(db: Store, user: documents.Row, block: documents.Row, note_id: int) -> None:
    """O bloco é de quem pediu? (o papel na nota não basta — ver a matriz em `acl.py`)"""
    if not acl.owns_block(db.snapshot(user.id), user.id, block, note_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_THE_AUTHOR)


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
    """Todo bloco de um tipo, em todas as notas ao meu alcance: mais novos primeiro, sem agrupar."""
    photo = db.snapshot(user.id)
    notes = {note.id: note for note in photo["notes"]}
    blocks = [block for block in photo["blocks"] if block.note_id in notes]
    if type is not None:
        blocks = [block for block in blocks if block.type == type]
    blocks.sort(key=lambda block: (block.updated_at, block.id), reverse=True)
    shown = blocks[:limit]
    authors = services.block_authors(
        db,
        user.id,
        [(block, notes[block.note_id].owner_id) for block in shown],
    )
    return [
        BlockListItem(
            id=block.id,
            type=block.type,
            text=block.text,
            language=block.language,
            url=block.url,
            caption=block.caption,
            author=authors.get(block.id, ""),
            updated_at=block.updated_at,
            note_id=block.note_id,
            note_title=notes[block.note_id].title,
        )
        for block in shown
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
    note = deps.note_for(db, user, block.note_id)
    _require_author(db, user, block, note.id)
    note_title = note.title
    fields = payload.model_dump(exclude_unset=True)
    with store().transaction() as tx:
        if fields:
            fields["updated_at"] = documents.now()
            block = documents.change("blocks", block_id, fields, owner_id=user.id, transaction_id=tx)
        links.reindex_block(db, block, user.id, tx)
        store().stage(
            tx, [events.operation(user.id, "updated", "block", note_title, note_id=note.id)]
        )
    acl.touch_note(db, note.id, skip=user.id)  # quem mais alcança precisa ver isto
    return BlockOut.model_validate(block)


@router.delete("/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(
    block_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> Response:
    block = deps.block_for(db, user, block_id)
    note_id = block.note_id
    note = deps.note_for(db, user, note_id)
    _require_author(db, user, block, note.id)
    note_title = note.title  # o bloco some, então o rótulo sai antes
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
        store().stage(
            tx, [events.operation(user.id, "deleted", "block", note_title, note_id=note.id)]
        )
    acl.touch_note(db, note.id, skip=user.id)  # quem mais alcança precisa ver isto
    return Response(status_code=status.HTTP_204_NO_CONTENT)
