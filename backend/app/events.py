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

ENTITIES = ("note", "block", "tag", "relation", "media", "user", "group", "share")


def _fields(
    user_id: int, action: str, entity: str, target: str, detail: str, note_id: int | str | None = None
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
        # Onde a ação aconteceu: é por esta coluna que quem recebeu a nota compartilhada vê a
        # atividade dela. Fora de uma nota (conta, tag, upload) fica vazio.
        "note_id": str(note_id) if note_id else "",
        "created_at": documents.to_iso(documents.now()),
    }


def record(
    db, user, action: str, entity: str, target: str = "", detail: str = "", note_id: int | None = None
) -> None:
    """Escreve o evento na hora, sem transação: scripts e `manage.py`, não rota."""
    db.create(
        "events",
        documents.record_id("events"),
        _fields(user.id, action, entity, target, detail, note_id),
    )


def operation(
    user_id: int,
    action: str,
    entity: str,
    target: str = "",
    detail: str = "",
    note_id: int | None = None,
) -> dict[str, Any]:
    """A operação de auditoria para `store().stage(tx, [...])`, junto com a escrita da entidade."""
    return documents.operation(
        "events",
        documents.record_id("events"),
        _fields(user_id, action, entity, target, detail, note_id)
    )


def visible(user: Row) -> list[str]:
    """Só os próprios movimentos. É o filtro usado quando não há nota compartilhada em jogo."""
    return [client.equal("user_id", str(user.id))]


def _note_ids(db, user: Row) -> list[str]:
    """As notas que esta conta alcança — a segunda consulta do feed."""
    from . import acl

    return acl.readable_note_ids(db, user.id)


def _merge(db, user: Row, limit: int) -> list[Row]:
    """Minhas ações + as da nota em que eu participo, mais novas primeiro.

    O Appwrite combina as queries com AND e não tem OR: são duas consultas (a minha e a das notas
    que eu alcanço, cada uma já ordenada e limitada) e a junção acontece aqui.
    """
    order = [client.order_desc("created_at"), client.limit(limit)]
    rows: dict[str, dict] = {}
    for row in db.list_rows("events", [client.equal("user_id", str(user.id)), *order]).rows:
        rows[row["$id"]] = row
    if user.role != "admin":
        note_ids = _note_ids(db, user)
        for start in range(0, len(note_ids), client.IN_VALUES):
            chunk = note_ids[start : start + client.IN_VALUES]
            for row in db.list_rows("events", [client.equal("note_id", *chunk), *order]).rows:
                rows[row["$id"]] = row
    ordered = sorted(rows.values(), key=lambda row: row.get("created_at") or "", reverse=True)
    return documents.many("events", ordered[:limit])


def feed(db, user: Row, limit: int = FEED_LIMIT) -> list[Row]:
    """As últimas ações visíveis, mais novas primeiro."""
    if user.role == "admin":
        queries = [client.order_desc("created_at"), client.limit(limit)]
        return documents.many("events", db.list_rows("events", queries).rows)
    return _merge(db, user, limit)


def unseen(db, user: Row) -> int:
    """Quantas ações chegaram depois do último instante que o usuário abriu a campainha.

    Mesmas duas consultas do feed, mas contando em vez de trazer linha: o número pode passar do teto
    da página (`FEED_LIMIT`) e ainda assim estar certo.
    """
    since: list[str] = []
    if user.activity_seen_at is not None:
        # `greaterThan` em coluna `datetime`: o dialeto quer a string ISO (não há helper pronto).
        since = [
            client.q(
                method="greaterThan",
                attribute="created_at",
                values=[documents.to_iso(user.activity_seen_at)],
            )
        ]
    total = db.count("events", visible(user) + since)
    if user.role == "admin":
        return total
    note_ids = _note_ids(db, user)
    for start in range(0, len(note_ids), client.IN_VALUES):
        chunk = note_ids[start : start + client.IN_VALUES]
        total += db.count("events", [client.equal("note_id", *chunk), *since])
    return total


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
