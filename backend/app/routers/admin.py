"""Administração de contas. Toda rota aqui é de admin, e a conta que age não pode se trancar fora.

A leitura é a foto do usuário (`store().snapshot`): o que antes era um `GROUP BY` agora é contagem
em memória sobre as linhas já lidas. Escrita é transação do store, com o evento de auditoria no
mesmo commit — é o commit único de antes.
"""

from __future__ import annotations

from typing import Any

from appwrite.exception import AppwriteException
from fastapi import APIRouter, Depends, HTTPException, Response, status

from .. import events
from ..deps import admin_user, get_db
from ..schemas import (
    AdminPasswordIn,
    AdminUserOut,
    GroupDetail,
    GroupIn,
    GroupOut,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)
from ..security import hash_password
from ..store import BUCKET_ID, Conflict, IN_VALUES, Store, documents, equal, order_asc
from ..store.documents import Row
from ..values import utcnow

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _photo(db: Store, user_id: int) -> dict[str, list[Any]]:
    """A foto do usuário, linha a linha no formato do app (`note.title`, `row.size`)."""
    return {
        table: [row if isinstance(row, Row) else documents.normalize(table, row) for row in rows]
        for table, rows in db.snapshot(user_id, fresh=True).items()
    }


def _summary(db: Store, user: Row) -> AdminUserOut:
    photo = _photo(db, user.id)
    return AdminUserOut(
        **UserOut.model_validate(user).model_dump(),
        notes=len(photo["notes"]),
        blocks=len(photo["blocks"]),
        media_bytes=sum(int(row["size"] or 0) for row in photo["media_files"]),
    )


def _load(db: Store, user_id: int) -> Row:
    user = documents.get("users", user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")
    return user


def _other_active_admin(db: Store, user: Row) -> bool:
    """Algum outro admin ativo? É ele que impede a última conta de ser rebaixada ou apagada."""
    for row in db.page("users", [equal("role", "admin")]):
        if documents.to_int(row["$id"]) == user.id:
            continue
        if bool(row.get("is_active", True)):
            return True
    return False


def _drop_sessions(db: Store, user_id: int) -> None:
    """O rowId da sessão é o hash do token, então quem identifica o dono é a coluna `user_id`."""
    db.delete_where("sessions", [equal("user_id", str(user_id))])


def _group_out(db: Store, row: Row) -> GroupOut:
    members = db.count("group_members", [equal("group_id", str(row.id))])
    return GroupOut(id=row.id, name=row.name, created_at=row.created_at, members=members)


def _load_group(db: Store, group_id: int) -> Row:
    group = documents.get("groups", group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo não encontrado")
    return group


@router.get("/groups", response_model=list[GroupOut])
def list_groups(db: Store = Depends(get_db), _admin: Row = Depends(admin_user)) -> list[GroupOut]:
    rows = sorted(documents.all_rows("groups"), key=lambda row: row.name.lower())
    return [_group_out(db, row) for row in rows]


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: GroupIn, db: Store = Depends(get_db), admin: Row = Depends(admin_user)
) -> GroupOut:
    """Grupo nasce vazio; quem entra nele é decisão separada, membro a membro."""
    name = payload.name.strip()
    with db.transaction() as tx:
        group = documents.write(
            "groups",
            documents.record_id("groups"),
            {"name": name, "created_by": str(admin.id), "created_at": utcnow()},
            owner_id=None,
            transaction_id=tx,
        )
        db.stage(tx, [events.operation(admin.id, "created", "group", name)])
    return _group_out(db, group)


@router.get("/groups/{group_id}", response_model=GroupDetail)
def inspect_group(
    group_id: int, db: Store = Depends(get_db), _admin: Row = Depends(admin_user)
) -> GroupDetail:
    group = _load_group(db, group_id)
    rows = list(db.page("group_members", [equal("group_id", str(group_id))]))
    return GroupDetail(
        **_group_out(db, group).model_dump(),
        member_ids=sorted(documents.to_int(row["user_id"]) for row in rows),
    )


@router.patch("/groups/{group_id}", response_model=GroupOut)
def rename_group(
    group_id: int,
    payload: GroupIn,
    db: Store = Depends(get_db),
    admin: Row = Depends(admin_user),
) -> GroupOut:
    group = _load_group(db, group_id)
    name = payload.name.strip()
    with db.transaction() as tx:
        group = documents.change("groups", group.id, {"name": name}, owner_id=None, transaction_id=tx)
        db.stage(tx, [events.operation(admin.id, "updated", "group", name)])
    return _group_out(db, group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: int, db: Store = Depends(get_db), admin: Row = Depends(admin_user)
) -> Response:
    """Apaga o grupo, seus vínculos com cadernos e as fotos de quem participava.

    Os cadernos não são tocados: quem perde o acesso é quem estava no grupo.
    """
    group = _load_group(db, group_id)
    members = [documents.to_int(row["user_id"]) for row in db.page("group_members", [equal("group_id", str(group_id))])]
    with db.transaction() as tx:
        db.stage(tx, [events.operation(admin.id, "deleted", "group", group.name)])
    db.delete_where("group_members", [equal("group_id", str(group_id))])
    db.delete_where("note_groups", [equal("group_id", str(group_id))])
    documents.remove("groups", group_id)
    for user_id in members:
        db.invalidate(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_group_member(
    group_id: int,
    user_id: int,
    db: Store = Depends(get_db),
    admin: Row = Depends(admin_user),
) -> Response:
    """Idempotente (`PUT`): repetir não duplica nem reclama — é assim que a tela manda."""
    group = _load_group(db, group_id)
    user = _load(db, user_id)
    documents.conflict_free(
        documents.write,
        "group_members",
        f"{group_id}_{user_id}",
        {"group_id": str(group_id), "user_id": str(user_id), "created_at": utcnow()},
        owner_id=None,
    )
    with db.transaction() as tx:
        db.stage(
            tx,
            [events.operation(admin.id, "tagged", "group", group.name, user.email)],
        )
    db.invalidate(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_group_member(
    group_id: int,
    user_id: int,
    db: Store = Depends(get_db),
    admin: Row = Depends(admin_user),
) -> Response:
    group = _load_group(db, group_id)
    user = _load(db, user_id)
    documents.remove("group_members", f"{group_id}_{user_id}")
    with db.transaction() as tx:
        db.stage(tx, [events.operation(admin.id, "untagged", "group", group.name, user.email)])
    db.invalidate(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users", response_model=list[AdminUserOut])
def list_users(db: Store = Depends(get_db), _admin: Row = Depends(admin_user)) -> list[AdminUserOut]:
    users = documents.all_rows("users", [order_asc("email")])
    return [_summary(db, user) for user in users]


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateIn, db: Store = Depends(get_db), admin: Row = Depends(admin_user)
) -> AdminUserOut:
    if documents.user_by_email(payload.email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe um usuário com esse e-mail")
    data = {
        "email": payload.email,
        "display_name": payload.display_name or payload.email.split("@")[0],
        "password_hash": hash_password(payload.password),
        "role": payload.role,
        "is_active": True,
        "created_at": utcnow(),
    }
    try:
        with db.transaction() as tx:
            # Linha de servidor (sem permissão de cliente): entra pelo `create_row` da transação
            # para que o evento de auditoria fique no mesmo commit.
            user = documents.write(
                "users",
                documents.record_id("users"),
                data,
                owner_id=None,
                transaction_id=tx,
            )
            db.stage(tx, [events.operation(admin.id, "created", "user", user.email)])
    except Conflict as error:
        # O índice unique do e-mail só estoura no commit, e a transação traduz isso para `Conflict`:
        # duas contas com o mesmo e-mail ao mesmo tempo caem no mesmo 409 da checagem acima.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Já existe um usuário com esse e-mail"
        ) from error
    return _summary(db, user)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    payload: UserUpdateIn,
    db: Store = Depends(get_db),
    admin: Row = Depends(admin_user),
) -> AdminUserOut:
    user = _load(db, user_id)
    demoting = payload.role is not None and payload.role != "admin" and user.role == "admin"
    disabling = payload.is_active is False and user.is_active
    if user.id == admin.id and (demoting or disabling):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Você não pode rebaixar nem desativar a própria conta"
        )
    if (demoting or disabling) and not _other_active_admin(db, user):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Esse é o último admin ativo; promova outro antes"
        )
    data: dict[str, Any] = {}
    if payload.display_name is not None:
        data["display_name"] = payload.display_name.strip()
    if payload.role is not None:
        data["role"] = payload.role
    if payload.is_active is not None:
        data["is_active"] = payload.is_active
    with db.transaction() as tx:
        if data:
            user = documents.change("users", user.id, data, owner_id=None, transaction_id=tx)
        db.stage(tx, [events.operation(admin.id, "updated", "user", user.email)])
    if payload.is_active is False:
        _drop_sessions(db, user.id)
    return _summary(db, user)


@router.post("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: int,
    payload: AdminPasswordIn,
    db: Store = Depends(get_db),
    admin: Row = Depends(admin_user),
) -> Response:
    user = _load(db, user_id)
    with db.transaction() as tx:
        documents.change(
            "users",
            user.id,
            {"password_hash": hash_password(payload.password)},
            owner_id=None,
            transaction_id=tx,
        )
        db.stage(tx, [events.operation(admin.id, "reset", "user", user.email)])
    _drop_sessions(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _remove_media(db: Store, user_id: int, filename: str) -> None:
    """O arquivo do bucket sai antes da linha: se algo falhar, a linha ainda aponta para ele."""
    try:
        db.storage.delete_file(BUCKET_ID, filename)
    except AppwriteException as error:
        if error.code != 404:  # arquivo já ausente: a linha tem de sair do mesmo jeito
            raise
    documents.remove("media_files", filename, owner_id=user_id)


def _notes_to_purge(
    db: Store, user_id: int, photo: dict[str, list[Any]]
) -> tuple[set[int], set[int]]:
    """Notas que ficam sem ninguém; na compartilhada a conta apenas sai, sem levar o trabalho.

    Devolve também os ids dos outros membros encontrados: a foto deles muda (a conta sai da lista e
    o papel pode mudar de mão), e `delete_where`/`update` crus não invalidam o cache por usuário.
    """
    candidates = {row.note_id for row in photo["note_members"]} | {
        row.id for row in photo["notes"]
    }
    doomed: set[int] = set()
    affected: set[int] = set()
    for note_id in sorted(candidates):
        others = [
            row
            for row in db.page("note_members", [equal("note_id", str(note_id))])
            if documents.to_int(row["user_id"]) != user_id
        ]
        if not others:
            doomed.add(note_id)
            continue
        affected.update(documents.to_int(row["user_id"]) for row in others)
        if not any(row.get("role") == "owner" for row in others):
            # A nota fica sem dono: o membro mais antigo herda o papel.
            heir = min(others, key=lambda row: documents.to_int(row["user_id"]))
            db.update("note_members", heir["$id"], {"role": "owner"})
    return doomed, affected


def purge_user(db: Store, user_id: int) -> None:
    """Apaga tudo que é da conta, de filho para pai, sem deixar linha órfã.

    Ordem, e por quê:

    1. nota compartilhada: repassa o `owner` ao membro mais antigo e tira as participações da conta
       (antes de qualquer bloco, porque é a lista de membros que decide o que sobra);
    2. arquivos do bucket e suas linhas em `media_files`;
    3. menções (`block_links`, por nota citada e por bloco citante) — apontam para notas e blocos;
    4. vínculos (`note_relations`, por origem e por destino);
    5. `note_tags` por nota e por tag (uma linha sobrevivente apontando para uma tag apagada seria
       órfã);
    6. blocos, depois notas;
    7. as tags do dono;
    8. eventos e as sessões da conta.

    Idempotente: cada passo tolera o que já não existe (delete de ausente é `False`, `delete_where`
    devolve 0), então repetir a chamada termina igual.
    """
    photo = _photo(db, user_id)
    doomed, affected = _notes_to_purge(db, user_id, photo)
    db.delete_where("note_members", [equal("user_id", str(user_id))])
    # As linhas de grupo das notas que ficam órfãs: `equal` com muitos valores vira um OR gigante, e
    # o servidor recusa acima de 100 (mesmo teto das outras consultas por lista).
    doomed_ids = [str(note_id) for note_id in sorted(doomed)]
    for start in range(0, len(doomed_ids), IN_VALUES):
        chunk = doomed_ids[start : start + IN_VALUES]
        db.delete_where("note_groups", [equal("note_id", *chunk)])

    note_ids = sorted(row.id for row in photo["notes"] if row.id in doomed)
    block_ids = sorted(row.id for row in photo["blocks"] if row.note_id in note_ids)
    tag_ids = sorted(row.id for row in photo["tags"])

    for row in photo["media_files"]:
        _remove_media(db, user_id, row.row_id)

    for note_id in note_ids:
        db.delete_where("block_links", [equal("note_id", str(note_id))])
        db.delete_where("note_relations", [equal("source_id", str(note_id))])
        db.delete_where("note_relations", [equal("target_id", str(note_id))])
        db.delete_where("note_tags", [equal("note_id", str(note_id))])
    for block_id in block_ids:
        db.delete_where("block_links", [equal("block_id", str(block_id))])
    for tag_id in tag_ids:
        db.delete_where("note_tags", [equal("tag_id", str(tag_id))])

    for block_id in block_ids:
        documents.remove("blocks", block_id, owner_id=user_id)
    for note_id in note_ids:
        documents.remove("notes", note_id, owner_id=user_id)
        # O espelho é por conta: sai só o de quem está indo embora (o do colega que fica continua
    for tag_id in tag_ids:
        documents.remove("tags", tag_id, owner_id=user_id)

    db.delete_where("events", [equal("user_id", str(user_id))])
    _drop_sessions(db, user_id)
    # A foto de quem ficou mudou (o membro saiu, o papel trocou de mão) e nenhuma das escritas
    # acima é do tipo que invalida sozinha: o TTL curto não pode devolver a nota antiga.
    for other_id in sorted(affected):
        db.invalidate(other_id)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int, db: Store = Depends(get_db), admin: Row = Depends(admin_user)
) -> Response:
    """Leva junto tudo que é da conta: notas, blocos, tags e arquivos."""
    user = _load(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não pode apagar a própria conta")
    if user.role == "admin" and user.is_active and not _other_active_admin(db, user):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esse é o último admin ativo")

    email = user.email  # o usuário some no purge, então o rótulo sai antes
    purge_user(db, user.id)
    # `delete_row` do store não aceita transação, então a linha sai na hora e o evento entra no
    # commit dele: o rastro de auditoria nunca fica sem o "quem apagou".
    with db.transaction() as tx:
        documents.remove("users", user.id)
        db.stage(tx, [events.operation(admin.id, "deleted", "user", email)])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
