"""Quem pode ver/editar cada nota — o único lugar que responde isso.

Uma nota tem um **dono** (a conta que a criou) e pode ser **compartilhada com grupos**. O grupo é o
público do compartilhamento: quem está no grupo alcança a nota, inclusive quem entrar no grupo
depois. O papel efetivo de alguém é o **maior** entre a linha direta em `note_members` e o que os
grupos dela concedem em `note_groups`.

Não existe mais caderno: a nota é a unidade — ela guarda os blocos, é ela que se compartilha e é
entre notas que os vínculos acontecem.

Matriz de papéis por operação (o `minimum` que cada rota passa para `deps.note_for`):

| operação                                        | mínimo |
| ----------------------------------------------- | ------ |
| ler a nota, seus blocos, tags, busca, grafo       | viewer |
| criar bloco, vínculo e tag                        | editor |
| editar/apagar um **bloco**                        | só quem o escreveu |
| renomear/apagar a nota e **compartilhar**         | owner  |

Só o dono compartilha: ninguém amplia a audiência sem ele saber.
"""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from .store import documents
from .store.client import SNAPSHOT_WORKERS, Conflict, Store, equal
from .store.documents import Row

ROLE_RANK: dict[str, int] = {"viewer": 0, "editor": 1, "owner": 2}
ROLES = ("viewer", "editor")


def rank(role: str | None) -> int:
    return ROLE_RANK.get(role or "", -1)


def allows(role: str | None, minimum: str) -> bool:
    return role is not None and rank(role) >= ROLE_RANK[minimum]


# ------------------------------------------------------------------ consulta


def direct_role(db: Store, user_id: int, note_id: int) -> str | None:
    """A linha de vínculo do próprio usuário (rowId composto, leitura pontual e autoritativa)."""
    member = documents.get("note_members", f"{user_id}_{note_id}")
    if member is not None:
        return member.role
    for row in db.snapshot(user_id)["note_members"]:
        if row.note_id == note_id:
            return row.role
    return None


def group_role(photo: dict, note_id: int) -> str | None:
    """O maior papel concedido pelos grupos do usuário que alcançam esta nota."""
    mine = {row.group_id for row in photo["group_members"]}
    granted = [
        row.role
        for row in photo["note_groups"]
        if row.note_id == note_id and row.group_id in mine
    ]
    return max(granted, key=rank, default=None)


def role_in_photo(photo: dict, note_id: int) -> str | None:
    """O papel efetivo só com o que já está na foto — para listar notas sem uma ida por nota."""
    direct = max(
        (row.role for row in photo["note_members"] if row.note_id == note_id),
        key=rank,
        default=None,
    )
    granted = group_role(photo, note_id)
    return granted if rank(granted) > rank(direct) else direct


def role_for(db: Store, user_id: int, note_id: int) -> str | None:
    """Papel efetivo: o maior entre a linha direta e o que os grupos concedem."""
    direct = direct_role(db, user_id, note_id)
    if rank(direct) == ROLE_RANK["owner"]:
        return direct  # dono é dono: não precisa olhar grupo nenhum
    granted = group_role(db.snapshot(user_id), note_id)
    return granted if rank(granted) > rank(direct) else direct


def is_owner(db: Store, user_id: int, note_id: int) -> bool:
    return direct_role(db, user_id, note_id) == "owner"


def owns_block(photo: dict, user_id: int, block: Row, note_id: int) -> bool:
    """O bloco é de quem está pedindo?

    `editor` escreve o que quiser, mas **não mexe no que é dos outros**: o conteúdo responde por quem
    o escreveu. Sem `created_by` (linha de antes da coluna) o autor é o dono da nota, que era quem
    escrevia.
    """
    if block.created_by:
        return block.created_by == user_id
    return role_in_photo(photo, note_id) == "owner"


def readable_note_ids(db: Store, user_id: int) -> list[str]:
    """Toda nota que a conta alcança: de que é dona, de que é membro e as dos grupos dela."""
    return Store.note_ids_of(db.snapshot(user_id))


def my_groups(db: Store, user_id: int) -> list[Row]:
    """Os grupos de que a conta participa — é a lista que o painel de compartilhar oferece."""
    return sorted(db.snapshot(user_id)["groups"], key=lambda row: row.name.lower())


def members_of(db: Store, note_id: int) -> list[dict]:
    """Quem alcança a nota, direto ou por grupo, com o papel efetivo de cada um.

    A lista é montada no servidor (o Appwrite não tem JOIN): membros diretos, grupos da nota e os
    membros desses grupos, resolvidos em paralelo.
    """
    direct = list(db.page("note_members", [equal("note_id", str(note_id))]))
    shares = list(db.page("note_groups", [equal("note_id", str(note_id))]))
    group_ids = [row["group_id"] for row in shares]
    with ThreadPoolExecutor(max_workers=SNAPSHOT_WORKERS) as pool:
        group_rows_f = pool.submit(lambda: list(db.page_in("groups", "$id", group_ids)))
        members_f = pool.submit(lambda: list(db.page_in("group_members", "group_id", group_ids)))
        group_rows, group_members = group_rows_f.result(), members_f.result()

    effective: dict[int, str] = {}
    for row in direct:
        effective[documents.to_int(row["user_id"])] = row.get("role") or "viewer"
    per_group = {row["group_id"]: row.get("role") or "viewer" for row in shares}
    for row in group_members:
        user_id = documents.to_int(row["user_id"])
        granted = per_group.get(row["group_id"], "viewer")
        if rank(granted) > rank(effective.get(user_id)):
            effective[user_id] = granted

    people = {
        documents.to_int(row["$id"]): row
        for row in db.page_in("users", "$id", [str(uid) for uid in effective])
    }
    out = []
    for user_id, role in sorted(effective.items(), key=lambda item: -rank(item[1])):
        user = people.get(user_id)
        if user is None:  # conta apagada no meio do caminho
            continue
        out.append(
            {
                "user_id": user_id,
                "display_name": user.get("display_name") or user.get("email") or "",
                "email": user.get("email") or "",
                "role": role,
                "owner": role == "owner",
                "groups": sorted(
                    group_row.get("name") or ""
                    for group_row in group_rows
                    for member in group_members
                    if member["group_id"] == group_row["$id"]
                    and documents.to_int(member["user_id"]) == user_id
                ),
            }
        )
    return out


def member_ids(db: Store, note_id: int) -> set[int]:
    """Todo mundo que alcança a nota (direto ou por grupo): é a lista que invalida a foto."""
    direct = db.page("note_members", [equal("note_id", str(note_id))])
    ids = {documents.to_int(row["user_id"]) for row in direct}
    shares = list(db.page("note_groups", [equal("note_id", str(note_id))]))
    if shares:
        group_ids = [row["group_id"] for row in shares]
        for row in db.page_in("group_members", "group_id", group_ids):
            ids.add(documents.to_int(row["user_id"]))
    return ids


def share_audience(db: Store, notes: Iterable[Row]) -> dict[int, tuple[list[str], int]]:
    """Para cada nota **minha** que saiu daqui: os grupos com que ela está compartilhada e quem eles levam.

    A foto não responde isto: ela carrega `note_groups` pelos grupos de que a conta participa, e o
    dono normalmente **não** está no grupo com quem compartilhou — sem esta consulta o compartilhamento
    de saída fica invisível para quem o fez. Uma consulta em lote por nota resolve a lista inteira,
    e o dono não entra na conta da audiência: ele já está aqui.
    """
    owners = {note.id: note.owner_id for note in notes}
    if not owners:
        return {}
    shares = list(db.page_in("note_groups", "note_id", [str(note_id) for note_id in owners]))
    if not shares:
        return {}
    group_ids = sorted({row["group_id"] for row in shares})
    names = {row["$id"]: row.get("name") or "" for row in db.page_in("groups", "$id", group_ids)}
    audience: dict[str, set[int]] = {}
    for row in db.page_in("group_members", "group_id", group_ids):
        audience.setdefault(row["group_id"], set()).add(documents.to_int(row["user_id"]))

    groups_of: dict[int, list[str]] = {}
    people_of: dict[int, set[int]] = {}
    for row in shares:
        note_id = documents.to_int(row["note_id"])
        group_id = row["group_id"]
        groups_of.setdefault(note_id, []).append(names.get(group_id, ""))
        # Um grupo apagado no meio do caminho deixa a linha órfã: a nota continua compartilhada,
        # só que com um público que não existe mais.
        people_of.setdefault(note_id, set()).update(audience.get(group_id, ()))
    return {
        note_id: (
            sorted(name for name in groups if name),
            len(people_of[note_id] - {owners.get(note_id, 0)}),
        )
        for note_id, groups in groups_of.items()
    }


# O que pendura numa nota: qualquer escrita nela pode ter mexido em um destes.
NOTE_TABLES = {"notes", "blocks", "note_tags", "note_relations", "block_links", "note_members", "note_groups"}


def touch_note(db: Store, note_id: int, skip: int | None = None) -> None:
    """Marca o que pendura na nota como velho na foto dos **outros** membros: eles precisam ver a mudança.

    `skip` é quem escreveu: a foto dele já recebeu a linha no commit (o `remember`/`staged`), e
    mandá-lo reler o Appwrite agora poderia trazer o estado anterior à gravação. Para os demais — que
    não têm a linha em mãos — o TTL de 30 s do cache é que estava decidindo quando a nota
    compartilhada aparecia.
    """
    for user_id in member_ids(db, note_id):
        if skip is not None and user_id == skip:
            continue
        db.touch(user_id, NOTE_TABLES)


def share_group(db: Store, note_id: int, group_id: int, role: str) -> None:
    """Nota → grupo, com o papel que vale para todo mundo dele.

    Repetir o mesmo grupo não é erro nem duplica: a linha é a mesma (`rowId`) e o papel é reescrito —
    é assim que a tela troca um `editor` por `viewer` sem tirar e pôr de novo. Linha de servidor (sem
    permissão de cliente, como o resto que a API key lê) e foto dos membros descartada na hora.
    """
    row_id = f"{note_id}_{group_id}"
    try:
        documents.write(
            "note_groups",
            row_id,
            {
                "note_id": str(note_id),
                "group_id": str(group_id),
                "role": role,
                "created_at": documents.now(),
            },
            owner_id=None,
        )
    except Conflict:
        documents.change("note_groups", row_id, {"role": role}, owner_id=None)
    touch_note(db, note_id)


def unshare_group(db: Store, note_id: int, group_id: int) -> bool:
    gone = documents.remove("note_groups", f"{note_id}_{group_id}")
    touch_note(db, note_id)
    return gone


# ------------------------------------------------------------------- escrita


def add_member(db: Store, note_id: int, user_id: int, actor_id: int | None = None, role: str = "owner") -> None:
    """O dono nasce junto com a nota; a linha pertence a ele e invalida a foto dele."""
    documents.write(
        "note_members",
        f"{user_id}_{note_id}",
        {
            "user_id": str(user_id),
            "note_id": str(note_id),
            "role": role,
            "created_at": documents.now(),
        },
        owner_id=actor_id if actor_id is not None else user_id,
    )
