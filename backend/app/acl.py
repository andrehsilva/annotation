"""Who may see which notebook — the single place that answers it.

Today every notebook has exactly one member (`owner`), written when the notebook is created. Sharing
means inserting another row here; no router changes.

Matriz de papéis por operação (o `minimum` que cada rota passa para `deps.notebook_for`):

| operação                                        | mínimo |
| ----------------------------------------------- | ------ |
| ler caderno, notas, blocos, tags, busca, grafo    | viewer |
| criar/editar/apagar nota, bloco, vínculo e tag    | editor |
| renomear ou apagar o **caderno** (e membros)      | owner  |

O papel `owner` existe no modelo e a migração do SQLite o copia literalmente: um `editor` de uma
instalação migrada não pode apagar o caderno dos outros, que é o que a matriz acima garante.
"""

from __future__ import annotations

from .store import documents
from .store.client import Store

ROLE_RANK: dict[str, int] = {"viewer": 0, "editor": 1, "owner": 2}


def role_for(db: Store, user_id: int, notebook_id: int) -> str | None:
    """O papel vem da linha de vínculo, cujo rowId é `"<user_id>_<notebook_id>"`.

    A leitura pontual é a resposta autoritativa (e a única com esta chave); a foto cobre a linha
    que não segue essa chave — vínculo antigo, gravado por outro caminho.
    """
    member = documents.get("notebook_members", f"{user_id}_{notebook_id}")
    if member is not None:
        return member.role
    for row in db.snapshot(user_id)["notebook_members"]:
        if row.notebook_id == notebook_id:
            return row.role
    return None


def allows(role: str | None, minimum: str) -> bool:
    return role is not None and ROLE_RANK.get(role, -1) >= ROLE_RANK[minimum]


def readable_notebook_ids(db: Store, user_id: int) -> list[str]:
    """Todo caderno em que o usuário é membro: a lista que filtrava notas e blocos.

    Devolve ids em string — é o formato do Appwrite —, sem repetição e em ordem estável, que é o
    que uma lista (antes, uma subquery sem ordem garantida) pode prometer.
    """
    return _ids(db.snapshot(user_id)["notebook_members"], "notebook_id")


def writable_notebook_ids(db: Store, user_id: int) -> list[str]:
    """Os cadernos em que o usuário pode escrever: `owner` ou `editor`."""
    members = db.snapshot(user_id)["notebook_members"]
    return _ids([row for row in members if row.role in ("owner", "editor")], "notebook_id")


def readable_note_ids(db: Store, user_id: int) -> list[str]:
    """Notas e blocos pendem do caderno, então é este o filtro que libera os dois."""
    notebooks = set(readable_notebook_ids(db, user_id))
    return _ids([row for row in db.snapshot(user_id)["notes"] if str(row.notebook_id) in notebooks])


def readable_block_ids(db: Store, user_id: int) -> list[str]:
    notes = set(readable_note_ids(db, user_id))
    return _ids([row for row in db.snapshot(user_id)["blocks"] if str(row.note_id) in notes])


def _ids(rows: list, column: str = "id") -> list[str]:
    return sorted({str(getattr(row, column)) for row in rows})


def add_member(db: Store, notebook_id: int, user_id: int, role: str = "owner") -> None:
    """O dono nasce junto com o caderno; a linha pertence a ele e invalida a foto dele.

    `documents.write` é o caminho do dono — grava as permissões com `owner_permissions(user_id)` e
    derruba o cache, para o caderno novo já aparecer na próxima foto.
    """
    documents.write(
        "notebook_members",
        f"{user_id}_{notebook_id}",
        {
            "user_id": str(user_id),
            "notebook_id": str(notebook_id),
            "role": role,
            "created_at": documents.now(),
        },
        owner_id=user_id,
    )
