"""As notas e tudo o que pende delas: blocos, tags, vínculos e o compartilhamento.

Não há caderno: a nota é a unidade do app — ela tem dono, papel e público, e é entre notas que os
vínculos acontecem. Quem alcança a nota decide o resto, e `acl.py` é o único lugar que responde isso.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from .. import acl, deps, events, links, services
from ..markdown import UNTITLED
from ..schemas import (
    BlockIn,
    BlockOut,
    BlockReorder,
    NoteGroupIn,
    NoteIn,
    NoteOut,
    NotePatch,
    NoteRelated,
    NoteRelationIn,
    NoteSharingOut,
    NoteSummary,
)
from ..store import Conflict, documents, store
from ..store.client import Store, equal

router = APIRouter(prefix="/api", tags=["notes"])


def _blocks_of(db: Store, user_id: int, note_id: int) -> list[documents.Row]:
    """Os blocos da nota na ordem de `position`, como o antigo `note.blocks`."""
    rows = [block for block in db.snapshot(user_id)["blocks"] if block.note_id == note_id]
    return sorted(rows, key=lambda block: (block.position, block.id))


def _sharing(db: Store, user: documents.Row, note: documents.Row) -> NoteSharingOut:
    """Quem alcança a nota e com quais grupos ela está compartilhada.

    Lido direto das tabelas (e não da foto): o painel de compartilhar precisa do estado de agora,
    inclusive o grupo que entrou há segundos.
    """
    members = acl.members_of(db, note.id)
    shares = list(db.page("note_groups", [equal("note_id", str(note.id))]))
    names = {
        str(row["$id"]): row.get("name") or ""
        for row in db.page_in("groups", "$id", [row["group_id"] for row in shares])
    }
    counts = {
        row["group_id"]: db.count("group_members", [equal("group_id", row["group_id"])])
        for row in shares
    }
    return NoteSharingOut(
        role=acl.role_for(db, user.id, note.id) or "viewer",
        can_share=acl.is_owner(db, user.id, note.id),
        members=members,
        groups=[
            {
                "group_id": documents.to_int(row["group_id"]),
                "name": names.get(row["group_id"], ""),
                "role": row.get("role") or "viewer",
                "members": counts.get(row["group_id"], 0),
            }
            for row in sorted(shares, key=lambda row: names.get(row["group_id"], "").lower())
        ],
        available=[{"id": row.id, "name": row.name, "created_at": row.created_at, "members": 0} for row in acl.my_groups(db, user.id)],
    )


@router.get("/notes", response_model=list[NoteSummary])
def list_notes(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=300, ge=1, le=300),
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> list[NoteSummary]:
    """As notas que a conta alcança — as dela e as compartilhadas com ela —, mais recentes primeiro."""
    return services.all_note_summaries(db, user.id, q, limit)


@router.post("/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def create_note(
    payload: NoteIn,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteOut:
    """Cria a nota (com o primeiro bloco, no mesmo commit) e já deixa o dono como `owner` dela."""
    photo = services.snapshot(db, user.id)
    position = max(
        (note.position for note in photo["notes"] if note.owner_id == user.id), default=-1
    ) + 1
    title = payload.title.strip()
    with store().transaction() as tx:
        now = documents.now()
        note = documents.write(
            "notes",
            documents.record_id("notes"),
            {
                "owner_id": str(user.id),
                "title": title,
                "position": position,
                "created_at": now,
                "updated_at": now,
            },
            owner_id=user.id,
            transaction_id=tx,
        )
        acl.add_member(db, note.id, user.id, role="owner")
        block = documents.write(
            "blocks",
            documents.record_id("blocks"),
            {
                "note_id": str(note.id),
                "position": 0,
                "type": "text",
                "text": payload.text,
                "created_by": str(user.id),
                "created_at": now,
                "updated_at": now,
            },
            owner_id=user.id,
            transaction_id=tx,
        )
        links.reindex_block(db, block, user.id, tx)
        store().stage(tx, [events.operation(user.id, "created", "note", title, note_id=note.id)])
    return services.note_detail(db, user.id, note)


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(
    note_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteOut:
    return services.note_detail(db, user.id, deps.note_for(db, user, note_id, "viewer"))


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int,
    payload: NotePatch,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteOut:
    note = deps.note_for(db, user, note_id, "owner")  # renomear é do dono
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
        store().stage(
            tx, [events.operation(user.id, "updated", "note", note.title, note_id=note.id)]
        )
    acl.touch_note(db, note.id, skip=user.id)  # quem mais alcança precisa ver isto
    return services.note_detail(db, user.id, note)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> Response:
    note = deps.note_for(db, user, note_id, "owner")  # apagar é do dono
    title = note.title  # a nota some no delete, então o rótulo sai antes
    block_ids = [str(block.id) for block in _blocks_of(db, user.id, note_id)]
    with store().transaction() as tx:
        # o que um banco apagaria em cascata junto com a nota: blocos, vínculos, menções, tags e o
        # compartilhamento dela
        for start in range(0, len(block_ids), services.QUERY_VALUES):
            chunk = block_ids[start : start + services.QUERY_VALUES]
            db.delete_where("block_links", [equal("block_id", *chunk)])
        db.delete_where("block_links", [equal("note_id", str(note_id))])
        db.delete_where("note_tags", [equal("note_id", str(note_id))])
        db.delete_where("note_relations", [equal("source_id", str(note_id))])
        db.delete_where("note_relations", [equal("target_id", str(note_id))])
        db.delete_where("blocks", [equal("note_id", str(note_id))])
        db.delete_where("note_members", [equal("note_id", str(note_id))])
        db.delete_where("note_groups", [equal("note_id", str(note_id))])
        documents.remove("drive_files", documents.drive_file_id(user.id, note_id))
        documents.remove("notes", note_id, owner_id=user.id)
        store().stage(tx, [events.operation(user.id, "deleted", "note", title, note_id=note_id)])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ vínculos


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
                            note_id=note.id,
                        ),
                    ],
                )
        except Conflict:
            pass  # o vínculo entrou entre a leitura e a escrita: já é o estado desejado
        acl.touch_note(db, note.id, skip=user.id)  # quem mais alcança precisa ver isto
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
    other = deps.note_for(db, user, other_id)  # o outro lado também precisa estar ao meu alcance
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
                    note_id=note.id,
                )
            ],
        )
    acl.touch_note(db, note.id, skip=user.id)  # quem mais alcança precisa ver isto
    return services.note_related(db, note)


# ------------------------------------------------------------------ tags


@router.post("/notes/{note_id}/tags/{tag_id}", response_model=NoteOut)
def attach_tag(
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
    if not attached:
        try:
            with store().transaction() as tx:
                store().stage(
                    tx,
                    [
                        documents.operation(
                            "note_tags",
                            f"{note_id}_{tag.id}",
                            {
                                "note_id": str(note_id),
                                "tag_id": str(tag.id),
                                "created_at": documents.now(),
                            },
                        ),
                        events.operation(user.id, "tagged", "note", note.title, tag.name, note_id=note.id),
                    ],
                )
        except Conflict:
            pass  # a tag entrou entre a leitura e a escrita: já é o estado desejado
        acl.touch_note(db, note.id, skip=user.id)  # quem mais alcança precisa ver isto
    return services.note_detail(db, user.id, note)


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
            store().stage(
                tx,
                [
                    events.operation(
                        user.id, "untagged", "note", note.title, tag.name, note_id=note.id
                    )
                ],
            )
        acl.touch_note(db, note.id, skip=user.id)  # quem mais alcança precisa ver isto
    return services.note_detail(db, user.id, note)


# ------------------------------------------------------------------ compartilhar


@router.get("/notes/{note_id}/members", response_model=NoteSharingOut)
def list_members(
    note_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteSharingOut:
    """Quem alcança a nota: o dono, os membros diretos e quem veio por grupo."""
    note = deps.note_for(db, user, note_id, "viewer")
    return _sharing(db, user, note)


@router.post("/notes/{note_id}/groups/{group_id}", response_model=NoteSharingOut)
def share_with_group(
    note_id: int,
    group_id: int,
    payload: NoteGroupIn,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteSharingOut:
    """Compartilha a nota com um grupo — só o dono, e com qualquer grupo do servidor.

    Repetir o grupo não duplica: o papel é reescrito, então a tela troca um `editor` por `viewer`
    pelo mesmo caminho.
    """
    note = deps.note_for(db, user, note_id, "owner")
    group = documents.get("groups", group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo não encontrado")
    role = payload.role if payload.role in acl.ROLES else "editor"
    with store().transaction() as tx:
        acl.share_group(db, note.id, group.id, role)
        store().stage(
            tx,
            [events.operation(user.id, "shared", "share", note.title, group.name, note_id=note.id)],
        )
    return _sharing(db, user, note)


@router.delete("/notes/{note_id}/groups/{group_id}", response_model=NoteSharingOut)
def unshare_group(
    note_id: int,
    group_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NoteSharingOut:
    note = deps.note_for(db, user, note_id, "owner")
    group = documents.get("groups", group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo não encontrado")
    with store().transaction() as tx:
        acl.unshare_group(db, note.id, group.id)
        store().stage(
            tx,
            [events.operation(user.id, "unshared", "share", note.title, group.name, note_id=note.id)],
        )
    return _sharing(db, user, note)


# ------------------------------------------------------------------ blocos


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
                "created_by": str(user.id),
                "created_at": now,
                "updated_at": now,
            },
            owner_id=user.id,
            transaction_id=tx,
        )
        links.reindex_block(db, block, user.id, tx)
        store().stage(tx, [events.operation(user.id, "created", "block", note.title, note_id=note.id)])
    acl.touch_note(db, note.id, skip=user.id)  # quem mais alcança precisa ver isto
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
    photo = db.snapshot(user.id)
    owner = services.note_owner(photo, note.id)
    authors = services.block_authors(db, user.id, [(block, owner) for block in ordered])
    return [
        BlockOut.model_validate({**block, "author": authors.get(block.id, "")}) for block in ordered
    ]
