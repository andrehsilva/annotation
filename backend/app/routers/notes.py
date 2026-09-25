from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import deps, events, links, services
from ..database import get_db
from ..markdown import UNTITLED
from ..models import Block, Note, NoteRelation, User
from ..schemas import (
    BlockIn,
    BlockOut,
    BlockReorder,
    NoteIn,
    NoteOut,
    NotePatch,
    NoteRelated,
    NoteRelationIn,
    NoteSummary,
)

router = APIRouter(prefix="/api", tags=["notes"])


def _serialize(db: Session, note: Note) -> NoteOut:
    """A note plus the relations that touch it; the rest of the links come from /related."""
    out = NoteOut.model_validate(note)
    out.relations = services.note_relations_for(db, note)
    return out


@router.get("/notes", response_model=list[NoteSummary])
def list_all_notes(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=300, ge=1, le=300),
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> list[NoteSummary]:
    """Every note of this user, most recently edited first."""
    return services.all_note_summaries(db, user.id, q, limit)


@router.get("/notebooks/{notebook_id}/notes", response_model=list[NoteSummary])
def list_notes(
    notebook_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> list[NoteSummary]:
    notebook = deps.notebook_for(db, user, notebook_id, "viewer")
    counts = services.block_counts_for_notes(db, [note.id for note in notebook.notes])
    return [
        services.note_summary(note, counts.get(note.id), notebook.title)
        for note in notebook.notes
    ]


@router.post(
    "/notebooks/{notebook_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED
)
def create_note(
    notebook_id: int,
    payload: NoteIn,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NoteOut:
    notebook = deps.notebook_for(db, user, notebook_id)
    position = max((note.position for note in notebook.notes), default=-1) + 1
    note = Note(notebook_id=notebook.id, title=payload.title.strip(), position=position)
    note.blocks.append(Block(position=0, type="text", text=payload.text))
    db.add(note)
    db.flush()
    for block in note.blocks:
        links.reindex_block(db, block, user.id)
    events.record(db, user, "created", "note", note.title)
    db.commit()
    return _serialize(db, note)


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(
    note_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NoteOut:
    return _serialize(db, deps.note_for(db, user, note_id, "viewer"))


@router.get("/notes/{note_id}/related", response_model=NoteRelated)
def get_related(
    note_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NoteRelated:
    """Declared relations, notes this one cites, and the blocks elsewhere that cite it."""
    return services.note_related(db, deps.note_for(db, user, note_id, "viewer"))


@router.post("/notes/{note_id}/relations", response_model=NoteRelated)
def create_relation(
    note_id: int,
    payload: NoteRelationIn,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NoteRelated:
    note = deps.note_for(db, user, note_id)
    if payload.target_id == note_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uma nota não pode se relacionar consigo")
    target = deps.note_for(db, user, payload.target_id)
    existing = db.scalars(
        select(NoteRelation).where(
            NoteRelation.source_id == note_id, NoteRelation.target_id == payload.target_id
        )
    ).one_or_none()
    if existing is None:
        db.add(
            NoteRelation(
                source_id=note_id,
                target_id=payload.target_id,
                label=payload.label.strip(),
            )
        )
        events.record(
            db, user, "linked", "relation", f"{note.title or UNTITLED} → {target.title or UNTITLED}"
        )
        db.commit()
    return services.note_related(db, note)


@router.delete("/notes/{note_id}/relations/{relation_id}", response_model=NoteRelated)
def delete_relation(
    note_id: int,
    relation_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NoteRelated:
    note = deps.note_for(db, user, note_id)
    relation = db.get(NoteRelation, relation_id)
    if relation is None or note_id not in (relation.source_id, relation.target_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relação não encontrada")
    other_id = relation.target_id if relation.source_id == note_id else relation.source_id
    other = deps.note_for(db, user, other_id)  # o outro lado também precisa ser do dono
    db.delete(relation)
    events.record(
            db, user, "unlinked", "relation", f"{note.title or UNTITLED} → {other.title or UNTITLED}"
        )
    db.commit()
    return services.note_related(db, note)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int,
    payload: NotePatch,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NoteOut:
    note = deps.note_for(db, user, note_id)
    previous_title = note.title
    if payload.title is not None:
        note.title = payload.title.strip()
    if payload.position is not None:
        note.position = payload.position
    links.rename_in_mentions(db, previous_title, note.title, user.id)
    events.record(db, user, "updated", "note", note.title)
    db.commit()
    return _serialize(db, note)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> Response:
    note = deps.note_for(db, user, note_id)
    title = note.title  # a nota some no delete, então o rótulo sai antes
    db.delete(note)
    events.record(db, user, "deleted", "note", title)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/notes/{note_id}/tags/{tag_id}", response_model=NoteOut)
def attach_tag(
    note_id: int,
    tag_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NoteOut:
    note = deps.note_for(db, user, note_id)
    tag = deps.tag_for(db, user, tag_id)
    if tag not in note.tags:
        note.tags.append(tag)
        events.record(db, user, "tagged", "note", note.title, tag.name)
    notebook = deps.notebook_for(db, user, note.notebook_id)
    if tag not in notebook.tags:
        notebook.tags.append(tag)
    db.commit()
    return _serialize(db, note)


@router.delete("/notes/{note_id}/tags/{tag_id}", response_model=NoteOut)
def detach_tag(
    note_id: int,
    tag_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NoteOut:
    note = deps.note_for(db, user, note_id)
    tag = deps.tag_for(db, user, tag_id)
    if tag in note.tags:
        note.tags.remove(tag)
        events.record(db, user, "untagged", "note", note.title, tag.name)
        db.commit()
    return _serialize(db, note)


@router.post("/notes/{note_id}/blocks", response_model=BlockOut, status_code=status.HTTP_201_CREATED)
def create_block(
    note_id: int,
    payload: BlockIn,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> BlockOut:
    note = deps.note_for(db, user, note_id)
    position = (
        payload.position
        if payload.position is not None
        else max((block.position for block in note.blocks), default=-1) + 1
    )
    block = Block(
        note_id=note.id,
        position=position,
        type=payload.type,
        text=payload.text,
        language=payload.language,
        url=payload.url,
        caption=payload.caption,
    )
    db.add(block)
    db.flush()
    links.reindex_block(db, block, user.id)
    events.record(db, user, "created", "block", note.title)
    db.commit()
    return BlockOut.model_validate(block)


@router.post("/notes/{note_id}/blocks/reorder", response_model=list[BlockOut])
def reorder_blocks(
    note_id: int,
    payload: BlockReorder,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> list[BlockOut]:
    note = deps.note_for(db, user, note_id)
    owned = {block.id: block for block in note.blocks}
    if set(payload.block_ids) != set(owned):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A lista precisa conter todos os blocos da nota"
        )
    for position, block_id in enumerate(payload.block_ids):
        owned[block_id].position = position
    db.commit()
    return [BlockOut.model_validate(owned[block_id]) for block_id in payload.block_ids]
