"""As operações do app sobre o Appwrite, com a forma dos modelos antigos.

Toda linha sai daqui **normalizada**: `$id` vira `id: int`, `created_at`/`updated_at` viram
`datetime` ingênuo em UTC — exatamente o que `app/models.py` entregava. Assim os routers, os schemas
e o `services.py` continuam lendo os mesmos nomes de campo, e só a origem do dado mudou.

Escrita: cada mutação passa por `write`, que abre a transação, grava a entidade com as permissões do
dono e encaixa as operações extras (evento de auditoria, vínculo, tag) **no mesmo commit** — é o
`db.commit()` único de antes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .client import DATABASE_ID, Conflict, Store, _clean, owner_permissions, store

OWNER_TABLES = {"notebooks", "notes", "blocks", "tags", "media_files"}


class Row(dict):
    """Linha normalizada: `note.title` e `note["title"]` valem o mesmo.

    O app inteiro lia atributos (`user.id`, `block.text`, `note.position`); manter isso evita
    reescrever cada acesso. O que **não** existe é relacionamento (`note.blocks`, `notebook.notes`,
    `note.tags`) — isso sempre vem do snapshot do usuário, montado no serviço que precisar.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error


# ------------------------------------------------------------------ conversão


def to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        if "." not in text.split("+")[0]:
            text = text.split("+")[0] + ".000000+" + (text.split("+")[1] if "+" in text else "00:00")
        return datetime.fromisoformat(text).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _base(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": to_int(row["$id"]), "row_id": row["$id"]}


def _stamps(row: dict[str, Any]) -> dict[str, Any]:
    """`$createdAt`/`$updatedAt` do servidor entram quando a coluna própria não existe."""
    return {
        "created_at": parse_dt(row.get("created_at")) or parse_dt(row.get("$createdAt")),
        "updated_at": parse_dt(row.get("updated_at")) or parse_dt(row.get("$updatedAt")),
    }


def user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(row),
        "email": row.get("email") or "",
        "display_name": row.get("display_name") or "",
        "password_hash": row.get("password_hash") or "",
        "role": row.get("role") or "user",
        "is_active": bool(row.get("is_active", True)),
        "created_at": parse_dt(row.get("created_at")),
        "last_login_at": parse_dt(row.get("last_login_at")),
        "activity_seen_at": parse_dt(row.get("activity_seen_at")),
    }


def session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": row["$id"],
        "token_hash": row["$id"],
        "user_id": to_int(row.get("user_id")),
        "created_at": parse_dt(row.get("created_at")),
        "expires_at": parse_dt(row.get("expires_at")),
        "last_seen_at": parse_dt(row.get("last_seen_at")),
    }


def notebook(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(row),
        "title": row.get("title") or "",
        "description": row.get("description") or "",
        "owner_id": to_int(row.get("owner_id")),
        **_stamps(row),
    }


def note(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(row),
        "notebook_id": to_int(row.get("notebook_id")),
        "title": row.get("title") or "",
        "position": to_int(row.get("position")),
        **_stamps(row),
    }


def block(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(row),
        "note_id": to_int(row.get("note_id")),
        "position": to_int(row.get("position")),
        "type": row.get("type") or "text",
        "text": row.get("text") or "",
        "language": row.get("language") or "",
        "url": row.get("url") or "",
        "caption": row.get("caption") or "",
        **_stamps(row),
    }


def tag(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(row),
        "owner_id": to_int(row.get("owner_id")),
        "name": row.get("name") or "",
        "color": row.get("color") or "",
        "created_at": parse_dt(row.get("created_at")),
    }


def member(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": row["$id"],
        "user_id": to_int(row.get("user_id")),
        "notebook_id": to_int(row.get("notebook_id")),
        "role": row.get("role") or "viewer",
        "created_at": parse_dt(row.get("created_at")),
    }


def relation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(row),
        "source_id": to_int(row.get("source_id")),
        "target_id": to_int(row.get("target_id")),
        "label": row.get("label") or "",
        "created_at": parse_dt(row.get("created_at")),
    }


def link(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(row),
        "block_id": to_int(row.get("block_id")),
        "note_id": to_int(row.get("note_id")),
        "created_at": parse_dt(row.get("created_at")),
    }


def media(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": row["$id"],
        "owner_id": to_int(row.get("owner_id")),
        "filename": row["$id"],
        "original_name": row.get("original_name") or "",
        "content_type": row.get("content_type") or "",
        "size": to_int(row.get("size")),
        "created_at": parse_dt(row.get("created_at")),
    }


def event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(row),
        "user_id": to_int(row.get("user_id")),
        "action": row.get("action") or "",
        "entity": row.get("entity") or "",
        "target": row.get("target") or "",
        "detail": row.get("detail") or "",
        "created_at": parse_dt(row.get("created_at")),
    }


def note_tag(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": row["$id"],
        "note_id": to_int(row.get("note_id")),
        "tag_id": to_int(row.get("tag_id")),
        "created_at": parse_dt(row.get("created_at")),
    }


def notebook_tag(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": row["$id"],
        "notebook_id": to_int(row.get("notebook_id")),
        "tag_id": to_int(row.get("tag_id")),
        "created_at": parse_dt(row.get("created_at")),
    }


def drive_file(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": to_int(row["$id"]),
        "note_id": to_int(row["$id"]),
        "file_id": row.get("file_id") or "",
        "folder_id": row.get("folder_id") or "",
        "drive_path": row.get("drive_path") or "",
        "checksum": row.get("checksum") or "",
        "synced_at": parse_dt(row.get("synced_at")),
    }


def drive_state(row: dict[str, Any]) -> dict[str, Any]:
    user_id, _, key = row["$id"].partition("_")
    return {"user_id": to_int(user_id), "key": row.get("key") or key, "value": row.get("value") or ""}


NORMALIZE = {
    "users": user,
    "sessions": session,
    "notebooks": notebook,
    "notebook_members": member,
    "notes": note,
    "blocks": block,
    "tags": tag,
    "note_relations": relation,
    "block_links": link,
    "note_tags": note_tag,
    "notebook_tags": notebook_tag,
    "media_files": media,
    "events": event,
    "drive_files": drive_file,
    "drive_state": drive_state,
}

def normalize(table: str, row: dict[str, Any]) -> Row:
    return Row(NORMALIZE[table](row))


def many(table: str, rows: Iterable[dict[str, Any]]) -> list[Row]:
    return [normalize(table, row) for row in rows]


# ------------------------------------------------------------------ leitura


def _s() -> Store:
    return store()


def get(table: str, row_id: int | str) -> Row | None:
    row = _s().get(table, str(row_id))
    return normalize(table, row) if row else None


def user_by_email(email: str) -> dict[str, Any] | None:
    from .client import equal

    rows = _s().list_rows("users", [equal("email", email.strip().lower())]).rows
    return normalize("users", rows[0]) if rows else None


def session_id(token_hash: str) -> str:
    """rowId da sessão: o sha256 do token tem 64 chars e o Appwrite aceita no máximo 36.

    Guardamos os 32 primeiros (128 bits): forjar um token cujo sha256 comece igual continua fora de
    alcance, e a linha inteira é estado efêmero — por isso sessão também não é migrada do SQLite.
    """
    return token_hash[:32]


def session_by_token_hash(token_hash: str) -> dict[str, Any] | None:
    row = _s().get("sessions", session_id(token_hash))
    return normalize("sessions", row) if row else None


def media_by_filename(filename: str) -> dict[str, Any] | None:
    row = _s().get("media_files", filename)
    return normalize("media_files", row) if row else None


def all_rows(table: str, queries: list[str] | None = None) -> list[Row]:
    return [normalize(table, row) for row in _s().page(table, queries)]


# ------------------------------------------------------------------ escrita


def operation(table: str, row_id: int | str, data: dict[str, Any]) -> dict[str, Any]:
    """Uma linha extra para entrar na **mesma** transação da entidade.

    Vale para o que não precisa de permissão própria: evento de auditoria, vínculo, menção, tag
    aplicada, membro do caderno. A entidade principal vai por `write(..., transaction_id=)`, porque
    só `create_row`/`update_row` gravam permissões (`create_operations` descarta — medido).
    """
    return {
        "action": "create",
        "databaseId": DATABASE_ID,
        "tableId": table,
        "rowId": str(row_id),
        "data": _clean(data),
    }


def tag_key(owner_id: int | str, name: str) -> str:
    """`name_key`: é o índice unique global que faz "nome de tag único por dono"."""
    return f"{owner_id}::{name.strip().lower()}"


def record_id(table: str, explicit: int | str | None = None) -> str:
    """Id do Appwrite como string; sem id explícito, vem do contador daquela família."""
    if explicit is not None:
        return str(explicit)
    return str(_s().next_id(table))


def write(
    table: str,
    row_id: int | str,
    data: dict[str, Any],
    *,
    owner_id: int | None,
    transaction_id: str | None = None,
    permissions: list[str] | None = None,
    create: bool = True,
) -> dict[str, Any]:
    """Cria ou atualiza uma linha do dono. Sem `transaction_id`, a chamada já é a escrita inteira."""
    grants = permissions if permissions is not None else (
        owner_permissions(owner_id) if owner_id is not None else None
    )
    # Qualquer datetime vira ISO: a coluna é `datetime` e o SDK serializa com json.dumps.
    payload = {
        key: (to_iso(value) if isinstance(value, datetime) else value)
        for key, value in data.items()
        if value is not None
    }
    if create:
        row = _s().create(table, row_id, payload, permissions=grants, transaction_id=transaction_id)
    else:
        row = _s().update(table, row_id, payload, permissions=grants, transaction_id=transaction_id)
    if owner_id is not None:
        _s().invalidate(owner_id)
    return normalize(table, row)


def change(
    table: str,
    row_id: int | str,
    data: dict[str, Any],
    *,
    owner_id: int | None,
    transaction_id: str | None = None,
) -> dict[str, Any]:
    return write(table, row_id, data, owner_id=owner_id, transaction_id=transaction_id, create=False)


def remove(table: str, row_id: int | str, owner_id: int | None = None) -> bool:
    gone = _s().delete(table, row_id)
    if owner_id is not None:
        _s().invalidate(owner_id)
    return gone


def conflict_free(call, *args: Any, **kwargs: Any) -> Any:
    """`409` no índice único quer dizer "já existe": quem chama decide se isso é sucesso."""
    try:
        return call(*args, **kwargs)
    except Conflict:
        return None
