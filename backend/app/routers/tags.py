from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from .. import deps, events
from ..schemas import TagIn, TagOut, TagUsage
from ..store import DATABASE_ID, Conflict, Store, documents, equal, limit
from ..store.documents import Row

router = APIRouter(prefix="/api/tags", tags=["tags"])


def _usage(db: Store, user_id: int) -> list[TagUsage]:
    """Contagem de uso sai da foto do usuário: sem `GROUP BY`, a soma é feita em memória."""
    photo = db.snapshot(user_id)
    notebook_counts = Counter(link.tag_id for link in photo["notebook_tags"])
    note_counts = Counter(link.tag_id for link in photo["note_tags"])
    return [
        TagUsage(
            id=tag.id,
            name=tag.name,
            color=tag.color,
            notebooks_count=notebook_counts.get(tag.id, 0),
            notes_count=note_counts.get(tag.id, 0),
        )
        for tag in sorted(photo["tags"], key=lambda tag: tag.name)
    ]


def _by_name_key(db: Store, key: str) -> Row | None:
    """A tag do dono com aquele nome: `name_key` é o índice unique global que o Appwrite tem."""
    rows = db.list_rows("tags", [equal("name_key", key), limit(1)]).rows
    return documents.normalize("tags", rows[0]) if rows else None


def _delete(table: str, row_id: str) -> dict[str, Any]:
    """Operação de delete para `stage` (o `documents.operation` monta só `create`)."""
    return {"action": "delete", "databaseId": DATABASE_ID, "tableId": table, "rowId": row_id}


@router.get("", response_model=list[TagUsage])
def list_tags(
    user: Row = Depends(deps.current_user), db: Store = Depends(deps.get_db)
) -> list[TagUsage]:
    return _usage(db, user.id)


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(
    payload: TagIn,
    user: Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> TagOut:
    """Idempotente por nome: Ctrl+Space num nome que já existe devolve aquela tag."""
    key = documents.tag_key(user.id, payload.name)
    existing = _by_name_key(db, key)
    if existing is not None:
        return TagOut.model_validate(existing)
    try:
        with db.transaction() as tx:
            tag = documents.write(
                "tags",
                documents.record_id("tags"),
                {
                    "owner_id": str(user.id),
                    "name": payload.name,
                    "name_key": key,
                    "color": payload.color,
                    "created_at": documents.now(),
                },
                owner_id=user.id,
                transaction_id=tx,
            )
            db.stage(tx, [events.operation(user.id, "created", "tag", payload.name)])
    except Conflict:
        # Corrida: alguém criou a mesma tag entre a consulta e o commit. Quem manda é o índice
        # unique — devolve a tag que ficou, nunca deixa o 409 vazar para o cliente.
        existing = _by_name_key(db, key)
        if existing is None:
            raise
        return TagOut.model_validate(existing)
    return TagOut.model_validate(tag)


@router.patch("/{tag_id}", response_model=TagOut)
def update_tag(
    tag_id: int,
    payload: TagIn,
    user: Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> TagOut:
    tag = deps.tag_for(db, user, tag_id)
    try:
        with db.transaction() as tx:
            updated = documents.change(
                "tags",
                tag.id,
                {
                    "name": payload.name,
                    "name_key": documents.tag_key(user.id, payload.name),
                    "color": payload.color,
                },
                owner_id=user.id,
                transaction_id=tx,
            )
            db.stage(tx, [events.operation(user.id, "updated", "tag", payload.name)])
    except Conflict:
        # Renomear para um nome que já é de outra tag: antes era `IntegrityError` cru (500); agora
        # é o 409 com a razão em português.
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma tag com esse nome") from None
    return TagOut.model_validate(updated)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: int,
    user: Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> Response:
    tag = deps.tag_for(db, user, tag_id)
    name = tag.name  # a tag some no delete, então o rótulo sai antes
    # Sem cascata no servidor: os vínculos daquela tag saem primeiro, senão ficam apontando para
    # uma linha que não existe mais.
    db.delete_where("notebook_tags", [equal("tag_id", str(tag.id))])
    db.delete_where("note_tags", [equal("tag_id", str(tag.id))])
    with db.transaction() as tx:
        db.stage(
            tx,
            [_delete("tags", tag.row_id), events.operation(user.id, "deleted", "tag", name)],
        )
    db.invalidate(user.id)  # o delete por transação não passa pelo `documents.write`
    return Response(status_code=status.HTTP_204_NO_CONTENT)
