from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from .. import acl, deps, events, services
from ..schemas import (
    GroupOut,
    NotebookGroupIn,
    NotebookMemberOut,
    NotebookGroupOut,
    NotebookSharingOut,
    NotebookIn,
    NotebookOut,
    NotebookPatch,
    NotebookSummary,
)
from ..store import Conflict, documents, store
from ..store.client import Store, equal

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


def _drop_all(db: Store, table: str, column: str, values: list[str]) -> None:
    """Apaga as linhas de `table` cujo `column` está em `values`.

    `equal` com vários valores é um OR e o dialeto só aceita `services.QUERY_VALUES` por chamada:
    os ids vão em lotes desse tamanho.
    """
    for start in range(0, len(values), services.QUERY_VALUES):
        db.delete_where(table, [equal(column, *values[start : start + services.QUERY_VALUES])])


@router.get("", response_model=list[NotebookSummary])
def list_notebooks(
    user: documents.Row = Depends(deps.current_user), db: Store = Depends(deps.get_db)
) -> list[NotebookSummary]:
    return services.list_notebook_summaries(db, user.id)


@router.post("", response_model=NotebookOut, status_code=status.HTTP_201_CREATED)
def create_notebook(
    payload: NotebookIn,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NotebookOut:
    title = payload.title.strip()
    with store().transaction() as tx:
        now = documents.now()
        notebook = documents.write(
            "notebooks",
            documents.record_id("notebooks"),
            {
                "title": title,
                "description": payload.description.strip(),
                "owner_id": str(user.id),
                "created_at": now,
                "updated_at": now,
            },
            owner_id=user.id,
            transaction_id=tx,
        )
        # o caderno nasce com uma nota vazia e o primeiro bloco dela, no mesmo commit
        note = documents.write(
            "notes",
            documents.record_id("notes"),
            {
                "notebook_id": str(notebook.id),
                "title": "",
                "position": 0,
                "created_at": now,
                "updated_at": now,
            },
            owner_id=user.id,
            transaction_id=tx,
        )
        documents.write(
            "blocks",
            documents.record_id("blocks"),
            {
                "note_id": str(note.id),
                "position": 0,
                "type": "text",
                "text": "",
                "created_by": str(user.id),
                "created_at": now,
                "updated_at": now,
            },
            owner_id=user.id,
            transaction_id=tx,
        )
        store().stage(
            tx,
            [
                # o dono nasce junto com o caderno
                documents.operation(
                    "notebook_members",
                    f"{user.id}_{notebook.id}",
                    {
                        "user_id": str(user.id),
                        "notebook_id": str(notebook.id),
                        "role": "owner",
                        "created_at": now,
                    },
                ),
                events.operation(user.id, "created", "notebook", title, notebook_id=notebook.id),
            ],
        )
    store().invalidate(user.id)  # a foto lida dentro da transação ainda é a de antes do commit
    acl.touch_notebook(db, notebook.id)  # quem mais é membro precisa ver isto
    return services.notebook_detail(db, user.id, deps.notebook_for(db, user, notebook.id))


@router.get("/{notebook_id}", response_model=NotebookOut)
def get_notebook(
    notebook_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NotebookOut:
    notebook = deps.notebook_for(db, user, notebook_id, "viewer")
    return services.notebook_detail(db, user.id, notebook)


@router.patch("/{notebook_id}", response_model=NotebookOut)
def update_notebook(
    notebook_id: int,
    payload: NotebookPatch,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NotebookOut:
    notebook = deps.notebook_for(db, user, notebook_id, "owner")
    data: dict = {}
    if payload.title is not None:
        data["title"] = payload.title.strip()
    if payload.description is not None:
        data["description"] = payload.description.strip()
    with store().transaction() as tx:
        if data:
            data["updated_at"] = documents.now()
            notebook = documents.change(
                "notebooks", notebook_id, data, owner_id=user.id, transaction_id=tx
            )
        store().stage(
            tx,
            [events.operation(user.id, "updated", "notebook", notebook.title, notebook_id=notebook.id)],
        )
    store().invalidate(user.id)
    acl.touch_notebook(db, notebook_id)  # quem mais é membro precisa ver isto
    return services.notebook_detail(db, user.id, notebook)


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notebook(
    notebook_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> Response:
    notebook = deps.notebook_for(db, user, notebook_id, "owner")
    title = notebook.title  # o caderno some no delete, então o rótulo sai antes
    photo = db.snapshot(user.id)
    note_ids = {note.id for note in photo["notes"] if note.notebook_id == notebook_id}
    block_ids = {block.id for block in photo["blocks"] if block.note_id in note_ids}
    note_args = [str(note_id) for note_id in note_ids]
    block_args = [str(block_id) for block_id in block_ids]
    with store().transaction() as tx:
        # o que o banco apagava em cascata com o caderno: notas, blocos, vínculos, menções e tags
        _drop_all(db, "block_links", "block_id", block_args)
        _drop_all(db, "block_links", "note_id", note_args)
        _drop_all(db, "note_tags", "note_id", note_args)
        _drop_all(db, "note_relations", "source_id", note_args)
        _drop_all(db, "note_relations", "target_id", note_args)
        _drop_all(db, "blocks", "note_id", note_args)
        for note_id in note_args:
            documents.remove("drive_files", documents.drive_file_id(user.id, note_id))  # espelho por conta
            documents.remove("notes", note_id, owner_id=user.id)
        db.delete_where("notebook_tags", [equal("notebook_id", str(notebook_id))])
        db.delete_where("notebook_members", [equal("notebook_id", str(notebook_id))])
        documents.remove("notebooks", notebook_id, owner_id=user.id)
        store().stage(tx, [events.operation(user.id, "deleted", "notebook", title, notebook_id=notebook_id)])
    store().invalidate(user.id)
    acl.touch_notebook(db, notebook_id)  # quem mais é membro precisa ver isto
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _sharing(db: Store, user: documents.Row, notebook: documents.Row) -> NotebookSharingOut:
    """Quem alcança o caderno e com quais grupos ele está compartilhado.

    Lido direto das tabelas (e não da foto): o painel de compartilhar precisa do estado de agora,
    inclusive o grupo que entrou há segundos.
    """
    shares = list(db.page("notebook_groups", [equal("notebook_id", str(notebook.id))]))
    group_ids = [row["group_id"] for row in shares]
    names = {
        str(row["$id"]): row.get("name") or ""
        for row in db.page_in("groups", "$id", group_ids)
    }
    counts = {
        row["group_id"]: db.count("group_members", [equal("group_id", row["group_id"])])
        for row in shares
    }
    return NotebookSharingOut(
        role=acl.role_for(db, user.id, notebook.id) or "viewer",
        can_share=acl.is_owner(db, user.id, notebook.id),
        members=[NotebookMemberOut(**member) for member in acl.members_of(db, notebook.id)],
        groups=[
            NotebookGroupOut(
                group_id=documents.to_int(row["group_id"]),
                name=names.get(row["group_id"], ""),
                role=row.get("role") or "editor",
                members=counts.get(row["group_id"], 0),
            )
            for row in sorted(shares, key=lambda row: names.get(row["group_id"], "").lower())
        ],
        # A lista para escolher: todos os grupos do servidor (quem compõe cada um é o admin), e só
        # para quem pode compartilhar.
        available=(
            [
                GroupOut(
                    id=row.id,
                    name=row.name,
                    created_at=row.created_at,
                    members=db.count("group_members", [equal("group_id", str(row.id))]),
                )
                for row in sorted(documents.all_rows("groups"), key=lambda row: row.name.lower())
            ]
            if acl.is_owner(db, user.id, notebook.id)
            else []
        ),
    )


@router.get("/{notebook_id}/members", response_model=NotebookSharingOut)
def list_members(
    notebook_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NotebookSharingOut:
    notebook = deps.notebook_for(db, user, notebook_id, "viewer")
    return _sharing(db, user, notebook)


@router.post(
    "/{notebook_id}/groups/{group_id}",
    response_model=NotebookSharingOut,
    status_code=status.HTTP_201_CREATED,
)
def share_with_group(
    notebook_id: int,
    group_id: int,
    payload: NotebookGroupIn,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NotebookSharingOut:
    """Compartilha o caderno com um grupo — só o dono, e com qualquer grupo do servidor.

    Quem entra no grupo depois alcança o caderno sozinho: o vínculo é com o grupo, não com cada
    pessoa. Quem compõe os grupos é o admin (`/api/admin/groups`); o dono só escolhe entre eles.
    """
    notebook = deps.notebook_for(db, user, notebook_id, "owner")
    group = documents.get("groups", group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo não encontrado")
    role = payload.role if payload.role in acl.ROLES else "editor"
    with store().transaction() as tx:
        acl.share_group(db, notebook.id, group.id, role)
        store().stage(
            tx,
            [events.operation(user.id, "shared", "share", notebook.title, group.name, notebook_id=notebook.id)],
        )
    return _sharing(db, user, notebook)


@router.delete("/{notebook_id}/groups/{group_id}", response_model=NotebookSharingOut)
def unshare_group(
    notebook_id: int,
    group_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NotebookSharingOut:
    notebook = deps.notebook_for(db, user, notebook_id, "owner")
    group = documents.get("groups", group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo não encontrado")
    with store().transaction() as tx:
        acl.unshare_group(db, notebook.id, group.id)
        store().stage(
            tx,
            [events.operation(user.id, "unshared", "share", notebook.title, group.name, notebook_id=notebook.id)],
        )
    return _sharing(db, user, notebook)


@router.post("/{notebook_id}/tags/{tag_id}", response_model=NotebookOut)
def attach_tag(
    notebook_id: int,
    tag_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NotebookOut:
    notebook = deps.notebook_for(db, user, notebook_id)
    tag = deps.tag_for(db, user, tag_id)
    attached = any(
        link.notebook_id == notebook_id and link.tag_id == tag.id
        for link in db.snapshot(user.id)["notebook_tags"]
    )
    if not attached:
        try:
            with store().transaction() as tx:
                store().stage(
                    tx,
                    [
                        documents.operation(
                            "notebook_tags",
                            f"{notebook_id}_{tag.id}",
                            {
                                "notebook_id": str(notebook_id),
                                "tag_id": str(tag.id),
                                "created_at": documents.now(),
                            },
                        ),
                        events.operation(
                            user.id, "tagged", "notebook", notebook.title, tag.name, notebook_id=notebook_id
                        ),
                    ],
                )
        except Conflict:
            pass  # a tag entrou entre a leitura e a escrita: já é o estado desejado
        store().invalidate(user.id)
        acl.touch_notebook(db, notebook_id)  # quem mais é membro precisa ver isto
    return services.notebook_detail(db, user.id, notebook)


@router.delete("/{notebook_id}/tags/{tag_id}", response_model=NotebookOut)
def detach_tag(
    notebook_id: int,
    tag_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> NotebookOut:
    notebook = deps.notebook_for(db, user, notebook_id)
    tag = deps.tag_for(db, user, tag_id)
    attached = any(
        link.notebook_id == notebook_id and link.tag_id == tag.id
        for link in db.snapshot(user.id)["notebook_tags"]
    )
    if attached:
        with store().transaction() as tx:
            db.delete_where(
                "notebook_tags",
                [equal("notebook_id", str(notebook_id)), equal("tag_id", str(tag.id))],
            )
            store().stage(
                tx,
                [
                    events.operation(
                        user.id, "untagged", "notebook", notebook.title, tag.name, notebook_id=notebook_id
                    )
                ],
            )
        store().invalidate(user.id)
        acl.touch_notebook(db, notebook_id)  # quem mais é membro precisa ver isto
    return services.notebook_detail(db, user.id, notebook)
