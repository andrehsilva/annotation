from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from .. import deps, events, links, services
from ..markdown import UNTITLED
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
from ..store import Conflict, documents, store
from ..store.client import Store, equal

router = APIRouter(prefix="/api", tags=["notes"])


def _notes_of(db: Store, user_id: int, notebook_id: int) -> list[documents.Row]:
    """As notas do caderno na ordem de `position`: o que o antigo `notebook.notes` entregava.

    Sai da `services.snapshot` de propósito: é ela que pendura os blocos e as tags em cada nota,
    que é o que o resumo da nota lê.
    """
    rows = [note for note in services.snapshot(db, user_id)["notes"] if note.notebook_id == notebook_id]
    return sorted(rows, key=lambda note: (note.position, note.id))


def _blocks_of(db: Store, user_id: int, note_id: int) -> list[documents.Row]:
    """Os blocos da nota na ordem de `position`, como o antigo `note.blocks`."""
    rows = [block for block in db.snapshot(user_id)["blocks"] if block.note_id == note_id]
    return sorted(rows, key=lambda block: (block.position, block.id))


def _serialize(db: Store, user: documents.Row, note: documents.Row) -> NoteOut:
    """A nota inteira montada da foto: blocos na ordem, tags por nome e as relações declaradas."""
    photo = db.snapshot(user.id)
    blocks = sorted(
        (row for row in photo["blocks"] if row.note_id == note.id),
        key=lambda row: (row.position, row.id),
    )
    tagged = {link.tag_id for link in photo["note_tags"] if link.note_id == note.id}
    tags = sorted(
        (tag for tag in photo["tags"] if tag.id in tagged), key=lambda tag: (tag.name, tag.id)
    )
    return NoteOut.model_validate(
        {**note, "tags": tags, "blocks": blocks, "relations": services.note_relations_for(db, note)}
    )


@router.get("/notes", response_model=list[NoteSummary])
def list_all_notes(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=300, ge=1, le=300),
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> list[NoteSummary]:
    """Every note of this user, most recently edited first."""
    return services.all_note_summaries(db, user.id, q, limit)


@router.get("/notebooks/{notebook_id}/notes", response_model=list[NoteSummary])
def list_notes(
    notebook_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> list[NoteSummary]:
    notebook = deps.notebook_for(db, user, notebook_id, "viewer")
    notes = _notes_of(db, user.id, notebook_id)
    counts = services.block_counts_for_notes(db, [note.id for note in notes])
    return [services.note_summary(note, counts.get(note.id), notebook.title) for note in notes]


@router.post(
    "/notebooks/{notebook_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED
)
def create_note(
    notebook_id: int,
    payload: NoteIn,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteOut:
    notebook = deps.notebook_for(db, user, notebook_id)
    position = max((note.position for note in _notes_of(db, user.id, notebook_id)), default=-1) + 1
    title = payload.title.strip()
    with store().transaction() as tx:
        now = documents.now()
        note = documents.write(
            "notes",
            documents.record_id("notes"),
            {
                "notebook_id": str(notebook_id),
                "title": title,
                "position": position,
                "created_at": now,
                "updated_at": now,
            },
            owner_id=user.id,
            transaction_id=tx,
        )
        # a nota já nasce com o primeiro bloco de texto, no mesmo commit
        block = documents.write(
            "blocks",
            documents.record_id("blocks"),
            {
                "note_id": str(note.id),
                "position": 0,
                "type": "text",
                "text": payload.text,
                "created_at": now,
                "updated_at": now,
            },
            owner_id=user.id,
            transaction_id=tx,
        )
        links.reindex_block(db, block, user.id, tx)
        store().stage(tx, [events.operation(user.id, "created", "note", title)])
    store().invalidate(user.id)  # a foto lida dentro da transação ainda é a de antes do commit
    return _serialize(db, user, note)


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(
    note_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteOut:
    return _serialize(db, user, deps.note_for(db, user, note_id, "viewer"))


@router.get("/notes/{note_id}/related", response_model=NoteRelated)
def get_related(
    note_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteRelated:
    """Declared relations, notes this one cites, and the blocks elsewhere that cite it."""
    return services.note_related(db, deps.note_for(db, user, note_id, "viewer"))


@router.post("/notes/{note_id}/relations", response_model=NoteRelated)
def create_relation(
    note_id: int,
    payload: NoteRelationIn,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteRelated:
    note = deps.note_for(db, user, note_id)
    if payload.target_id == note_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uma nota não pode se relacionar consigo")
    target = deps.note_for(db, user, payload.target_id)
    linked = any(
        relation.source_id == note_id and relation.target_id == payload.target_id
        for relation in db.snapshot(user.id)["note_relations"]
    )
    if not linked:
        try:
            with store().transaction() as tx:
                store().stage(
                    tx,
                    [
                        documents.operation(
                            # id do contador, não `<source>_<target>`: é ele que volta como
                            # `NoteRelationOut.id` e é por ele que a SPA apaga o vínculo
                            "note_relations",
                            documents.record_id("note_relations"),
                            {
                                "source_id": str(note_id),
                                "target_id": str(payload.target_id),
                                "label": payload.label.strip(),
                                "created_at": documents.now(),
                            },
                        ),
                        events.operation(
                            user.id,
                            "linked",
                            "relation",
                            f"{note.title or UNTITLED} → {target.title or UNTITLED}",
                        ),
                    ],
                )
        except Conflict:
            pass  # o vínculo entrou entre a leitura e a escrita: já é o estado desejado
        store().invalidate(user.id)
    return services.note_related(db, note)


@router.delete("/notes/{note_id}/relations/{relation_id}", response_model=NoteRelated)
def delete_relation(
    note_id: int,
    relation_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteRelated:
    note = deps.note_for(db, user, note_id)
    relation = documents.get("note_relations", relation_id)
    if relation is None or note_id not in (relation.source_id, relation.target_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relação não encontrada")
    other_id = relation.target_id if relation.source_id == note_id else relation.source_id
    other = deps.note_for(db, user, other_id)  # o outro lado também precisa ser do dono
    with store().transaction() as tx:
        documents.remove("note_relations", relation.id)
        store().stage(
            tx,
            [
                events.operation(
                    user.id,
                    "unlinked",
                    "relation",
                    f"{note.title or UNTITLED} → {other.title or UNTITLED}",
                )
            ],
        )
    store().invalidate(user.id)
    return services.note_related(db, note)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int,
    payload: NotePatch,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteOut:
    note = deps.note_for(db, user, note_id)
    previous_title = note.title
    data: dict = {}
    if payload.title is not None:
        data["title"] = payload.title.strip()
    if payload.position is not None:
        data["position"] = payload.position
    with store().transaction() as tx:
        if data:
            data["updated_at"] = documents.now()
            note = documents.change("notes", note_id, data, owner_id=user.id, transaction_id=tx)
        links.rename_in_mentions(db, previous_title, data.get("title", previous_title), user.id, tx)
        store().stage(tx, [events.operation(user.id, "updated", "note", note.title)])
    store().invalidate(user.id)
    return _serialize(db, user, note)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> Response:
    note = deps.note_for(db, user, note_id)
    title = note.title  # a nota some no delete, então o rótulo sai antes
    block_ids = [str(block.id) for block in _blocks_of(db, user.id, note_id)]
    with store().transaction() as tx:
        # o que o banco apagava em cascata junto com a nota: blocos, vínculos, menções e tags
        for start in range(0, len(block_ids), services.QUERY_VALUES):
            chunk = block_ids[start : start + services.QUERY_VALUES]
            db.delete_where("block_links", [equal("block_id", *chunk)])
        db.delete_where("block_links", [equal("note_id", str(note_id))])
        db.delete_where("note_tags", [equal("note_id", str(note_id))])
        db.delete_where("note_relations", [equal("source_id", str(note_id))])
        db.delete_where("note_relations", [equal("target_id", str(note_id))])
        db.delete_where("blocks", [equal("note_id", str(note_id))])
        documents.remove("drive_files", note_id)
        documents.remove("notes", note_id, owner_id=user.id)
        store().stage(tx, [events.operation(user.id, "deleted", "note", title)])
    store().invalidate(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/notes/{note_id}/tags/{tag_id}", response_model=NoteOut)
def attach_tag(
    note_id: int,
    tag_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteOut:
    note = deps.note_for(db, user, note_id)
    tag = deps.tag_for(db, user, tag_id)
    photo = db.snapshot(user.id)
    on_note = any(
        link.note_id == note_id and link.tag_id == tag.id for link in photo["note_tags"]
    )
    on_notebook = any(
        link.notebook_id == note.notebook_id and link.tag_id == tag.id
        for link in photo["notebook_tags"]
    )
    operations = []
    if not on_note:
        operations.append(
            documents.operation(
                "note_tags",
                f"{note_id}_{tag.id}",
                {"note_id": str(note_id), "tag_id": str(tag.id), "created_at": documents.now()},
            )
        )
        operations.append(events.operation(user.id, "tagged", "note", note.title, tag.name))
    if not on_notebook:
        # a tag nova também entra no caderno, como hoje
        operations.append(
            documents.operation(
                "notebook_tags",
                f"{note.notebook_id}_{tag.id}",
                {
                    "notebook_id": str(note.notebook_id),
                    "tag_id": str(tag.id),
                    "created_at": documents.now(),
                },
            )
        )
    if operations:
        try:
            with store().transaction() as tx:
                store().stage(tx, operations)
        except Conflict:
            pass  # a tag entrou entre a leitura e a escrita: já é o estado desejado
        store().invalidate(user.id)
    return _serialize(db, user, note)


@router.delete("/notes/{note_id}/tags/{tag_id}", response_model=NoteOut)
def detach_tag(
    note_id: int,
    tag_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteOut:
    note = deps.note_for(db, user, note_id)
    tag = deps.tag_for(db, user, tag_id)
    attached = any(
        link.note_id == note_id and link.tag_id == tag.id
        for link in db.snapshot(user.id)["note_tags"]
    )
    if attached:
        with store().transaction() as tx:
            db.delete_where(
                "note_tags", [equal("note_id", str(note_id)), equal("tag_id", str(tag.id))]
            )
            store().stage(tx, [events.operation(user.id, "untagged", "note", note.title, tag.name)])
        store().invalidate(user.id)
    return _serialize(db, user, note)


@router.post("/notes/{note_id}/blocks", response_model=BlockOut, status_code=status.HTTP_201_CREATED)
def create_block(
    note_id: int,
    payload: BlockIn,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> BlockOut:
    note = deps.note_for(db, user, note_id)
    position = (
        payload.position
        if payload.position is not None
        else max((block.position for block in _blocks_of(db, user.id, note_id)), default=-1) + 1
    )
    with store().transaction() as tx:
        now = documents.now()
        block = documents.write(
            "blocks",
            documents.record_id("blocks"),
            {
                "note_id": str(note_id),
                "position": position,
                "type": payload.type,
                "text": payload.text,
                "language": payload.language,
                "url": payload.url,
                "caption": payload.caption,
                "created_at": now,
                "updated_at": now,
            },
            owner_id=user.id,
            transaction_id=tx,
        )
        links.reindex_block(db, block, user.id, tx)
        store().stage(tx, [events.operation(user.id, "created", "block", note.title)])
    store().invalidate(user.id)
    return BlockOut.model_validate(block)


@router.post("/notes/{note_id}/blocks/reorder", response_model=list[BlockOut])
def reorder_blocks(
    note_id: int,
    payload: BlockReorder,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> list[BlockOut]:
    note = deps.note_for(db, user, note_id)
    owned = {block.id: block for block in _blocks_of(db, user.id, note_id)}
    if set(payload.block_ids) != set(owned):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A lista precisa conter todos os blocos da nota"
        )
    with store().transaction() as tx:
        now = documents.now()
        ordered = [
            documents.change(
                "blocks",
                block_id,
                {"position": position, "updated_at": now},
                owner_id=user.id,
                transaction_id=tx,
            )
            for position, block_id in enumerate(payload.block_ids)
        ]
    store().invalidate(user.id)
    return [BlockOut.model_validate(block) for block in ordered]

