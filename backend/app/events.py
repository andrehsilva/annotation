"""Quem fez o quê: uma linha por escrita, e o feed que a campainha mostra no topo do app.

A linha do evento entra na **mesma transação** da escrita que a gerou (`operation` +
`store().stage(tx, [...])`), então uma ação que falha no meio não deixa rastro. `record` é a
exceção: escreve na hora, fora de transação, para `manage.py`, `seed.py` e scripts.
"""

from __future__ import annotations

from typing import Any

from .store import client, documents
from .store.documents import Row

FEED_LIMIT = 5
FEED_MAX = 50

ACTIONS = (
    "created",
    "updated",
    "deleted",
    "tagged",
    "untagged",
    "linked",
    "unlinked",
    "uploaded",
)

ENTITIES = ("notebook", "note", "block", "tag", "relation", "media", "user")


def _fields(
    user_id: int, action: str, entity: str, target: str, detail: str
) -> dict[str, Any]:
    """Os mesmos cortes de antes: espaços colapsados e 200/80 caracteres por coluna.

    `created_at` sai em ISO porque quem escreve é `create_row` cru (o SDK serializa o corpo com
    `json.dumps`) — `documents.write` já faria essa conversão, `db.create` não.
    """
    return {
        "user_id": str(user_id),
        "action": action,
        "entity": entity,
        "target": " ".join((target or "").split())[:200],
        "detail": " ".join((detail or "").split())[:80],
        "created_at": documents.to_iso(documents.now()),
    }


def record(db, user, action: str, entity: str, target: str = "", detail: str = "") -> None:
    """Escreve o evento na hora, sem transação: scripts e `manage.py`, não rota."""
    db.create("events", documents.record_id("events"), _fields(user.id, action, entity, target, detail))


def operation(
    user_id: int, action: str, entity: str, target: str = "", detail: str = ""
) -> dict[str, Any]:
    """A operação de auditoria para `store().stage(tx, [...])`, junto com a escrita da entidade."""
    return documents.operation(
        "events", documents.record_id("events"), _fields(user_id, action, entity, target, detail)
    )


def visible(user: Row) -> list[str]:
    """O admin acompanha a plataforma inteira; todo mundo só os próprios movimentos."""
    if user.role == "admin":
        return []
    return [client.equal("user_id", str(user.id))]


def feed(db, user: Row, limit: int = FEED_LIMIT) -> list[Row]:
    """As últimas ações visíveis, mais novas primeiro."""
    queries = visible(user) + [client.order_desc("created_at"), client.limit(limit)]
    return documents.many("events", db.list_rows("events", queries).rows)


def unseen(db, user: Row) -> int:
    """Quantas ações chegaram depois do último instante que o usuário abriu a campainha."""
    queries = visible(user)
    if user.activity_seen_at is not None:
        # `greaterThan` em coluna `datetime`: o dialeto quer a string ISO (não há helper pronto).
        queries = queries + [
            client.q(
                method="greaterThan",
                attribute="created_at",
                values=[documents.to_iso(user.activity_seen_at)],
            )
        ]
    return db.count("events", queries)


def mark_seen(db, user: Row) -> None:
    """A partir de agora o `unread` só conta o que vier depois."""
    documents.change("users", user.id, {"activity_seen_at": documents.now()}, owner_id=None)


def actors(db, rows: list[Row]) -> dict[int, str]:
    """Nome de cada autor da página, numa consulta só: `equal` aceita vários ids."""
    ids = {str(row.user_id) for row in rows}
    if not ids:
        return {}
    queries = [client.equal("$id", *ids), client.limit(len(ids))]
    people = documents.many("users", db.list_rows("users", queries).rows)
    return {person.id: person.display_name or person.email for person in people}
