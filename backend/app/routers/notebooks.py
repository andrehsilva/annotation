from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from .. import deps, events, services
from ..schemas import (
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
                events.operation(user.id, "created", "notebook", title),
            ],
        )
    store().invalidate(user.id)  # a foto lida dentro da transação ainda é a de antes do commit
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
    notebook = deps.notebook_for(db, user, notebook_id)
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
        store().stage(tx, [events.operation(user.id, "updated", "notebook", notebook.title)])
    store().invalidate(user.id)
    return services.notebook_detail(db, user.id, notebook)


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notebook(
    notebook_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> Response:
    notebook = deps.notebook_for(db, user, notebook_id)
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
            documents.remove("drive_files", note_id)  # o rowId do espelho é o id da nota
            documents.remove("notes", note_id, owner_id=user.id)
        db.delete_where("notebook_tags", [equal("notebook_id", str(notebook_id))])
        db.delete_where("notebook_members", [equal("notebook_id", str(notebook_id))])
        documents.remove("notebooks", notebook_id, owner_id=user.id)
        store().stage(tx, [events.operation(user.id, "deleted", "notebook", title)])
    store().invalidate(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
                        events.operation(user.id, "tagged", "notebook", notebook.title, tag.name),
                    ],
                )
        except Conflict:
            pass  # a tag entrou entre a leitura e a escrita: já é o estado desejado
        store().invalidate(user.id)
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
            store().stage(tx, [events.operation(user.id, "untagged", "notebook", notebook.title, tag.name)])
        store().invalidate(user.id)
    return services.notebook_detail(db, user.id, notebook)
