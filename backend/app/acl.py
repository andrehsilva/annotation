"""Quem pode ver/editar cada caderno — o único lugar que responde isso.

Um caderno tem um **dono** (a conta que o criou) e pode ser **compartilhado com grupos**. O grupo é o
público do compartilhamento: quem está no grupo alcança o caderno, inclusive quem entrar no grupo
depois. O papel efetivo de alguém é o **maior** entre a linha direta em `notebook_members` e o que os
grupos dela concedem em `notebook_groups`.

Matriz de papéis por operação (o `minimum` que cada rota passa para `deps.notebook_for`):

| operação                                        | mínimo |
| ----------------------------------------------- | ------ |
| ler caderno, notas, blocos, tags, busca, grafo    | viewer |
| criar nota, bloco, vínculo e tag                  | editor |
| editar/apagar um **bloco**                        | só quem o escreveu |
| renomear/apagar o caderno e **compartilhar**      | owner  |

Só o dono compartilha: ninguém amplia a audiência sem ele saber.
"""

from __future__ import annotations

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


def direct_role(db: Store, user_id: int, notebook_id: int) -> str | None:
    """A linha de vínculo do próprio usuário (rowId composto, leitura pontual e autoritativa)."""
    member = documents.get("notebook_members", f"{user_id}_{notebook_id}")
    if member is not None:
        return member.role
    for row in db.snapshot(user_id)["notebook_members"]:
        if row.notebook_id == notebook_id:
            return row.role
    return None


def group_role(photo: dict, notebook_id: int) -> str | None:
    """O maior papel concedido pelos grupos do usuário que alcançam este caderno."""
    mine = {row.group_id for row in photo["group_members"]}
    granted = [
        row.role
        for row in photo["notebook_groups"]
        if row.notebook_id == notebook_id and row.group_id in mine
    ]
    return max(granted, key=rank, default=None)


def role_in_photo(photo: dict, notebook_id: int) -> str | None:
    """O papel efetivo só com o que já está na foto — para listar cadernos sem uma ida por caderno."""
    direct = max(
        (row.role for row in photo["notebook_members"] if row.notebook_id == notebook_id),
        key=rank,
        default=None,
    )
    granted = group_role(photo, notebook_id)
    return granted if rank(granted) > rank(direct) else direct


def role_for(db: Store, user_id: int, notebook_id: int) -> str | None:
    """Papel efetivo: o maior entre a linha direta e o que os grupos concedem."""
    direct = direct_role(db, user_id, notebook_id)
    if rank(direct) == ROLE_RANK["owner"]:
        return direct  # dono é dono: não precisa olhar grupo nenhum
    granted = group_role(db.snapshot(user_id), notebook_id)
    return granted if rank(granted) > rank(direct) else direct


def is_owner(db: Store, user_id: int, notebook_id: int) -> bool:
    return direct_role(db, user_id, notebook_id) == "owner"


def owns_block(photo: dict, user_id: int, block: Row, notebook_id: int) -> bool:
    """O bloco é de quem está pedindo?

    `editor` escreve o que quiser, mas **não mexe no que é dos outros**: o conteúdo responde por quem
    o escreveu. Sem `created_by` (linha de antes da coluna) o autor é o dono do caderno, que era quem
    escrevia.
    """
    if block.created_by:
        return block.created_by == user_id
    return role_in_photo(photo, notebook_id) == "owner"


def readable_notebook_ids(db: Store, user_id: int) -> list[str]:
    """Todo caderno que a conta alcança: de que é dona, de que é membro e os dos grupos dela."""
    return Store.notebook_ids_of(db.snapshot(user_id))


def my_groups(db: Store, user_id: int) -> list[Row]:
    """Os grupos de que a conta participa — é a lista que o painel de compartilhar oferece."""
    return sorted(db.snapshot(user_id)["groups"], key=lambda row: row.name.lower())


def members_of(db: Store, notebook_id: int) -> list[dict]:
    """Quem alcança o caderno, direto ou por grupo, com o papel efetivo de cada um.

    A lista é montada no servidor (o Appwrite não tem JOIN): membros diretos, grupos do caderno e os
    membros desses grupos, resolvidos em paralelo.
    """
    direct = list(db.page("notebook_members", [equal("notebook_id", str(notebook_id))]))
    shares = list(db.page("notebook_groups", [equal("notebook_id", str(notebook_id))]))
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


def member_ids(db: Store, notebook_id: int) -> set[int]:
    """Todo mundo que alcança o caderno (direto ou por grupo): é a lista que invalida a foto."""
    direct = db.page("notebook_members", [equal("notebook_id", str(notebook_id))])
    ids = {documents.to_int(row["user_id"]) for row in direct}
    shares = list(db.page("notebook_groups", [equal("notebook_id", str(notebook_id))]))
    if shares:
        group_ids = [row["group_id"] for row in shares]
        for row in db.page_in("group_members", "group_id", group_ids):
            ids.add(documents.to_int(row["user_id"]))
    return ids


def touch_notebook(db: Store, notebook_id: int) -> None:
    """Descarta a foto de todos os membros do caderno: quem não escreveu precisa ver o que mudou.

    O cache é por usuário (TTL de 30 s) e a escrita só invalida a foto de quem escreveu; sem isto o
    colega ficaria até meio minuto com a versão velha do caderno compartilhado.
    """
    for user_id in member_ids(db, notebook_id):
        db.invalidate(user_id)


def share_group(db: Store, notebook_id: int, group_id: int, role: str) -> None:
    """Caderno → grupo, com o papel que vale para todo mundo dele.

    Repetir o mesmo grupo não é erro nem duplica: a linha é a mesma (`rowId`) e o papel é reescrito —
    é assim que a tela troca um `editor` por `viewer` sem tirar e pôr de novo. Linha de servidor (sem
    permissão de cliente, como o resto que a API key lê) e foto dos membros descartada na hora.
    """
    row_id = f"{notebook_id}_{group_id}"
    try:
        documents.write(
            "notebook_groups",
            row_id,
            {
                "notebook_id": str(notebook_id),
                "group_id": str(group_id),
                "role": role,
                "created_at": documents.now(),
            },
            owner_id=None,
        )
    except Conflict:
        documents.change("notebook_groups", row_id, {"role": role}, owner_id=None)
    touch_notebook(db, notebook_id)


def unshare_group(db: Store, notebook_id: int, group_id: int) -> bool:
    gone = documents.remove("notebook_groups", f"{notebook_id}_{group_id}")
    touch_notebook(db, notebook_id)
    return gone


# ------------------------------------------------------------------- escrita


def add_member(db: Store, notebook_id: int, user_id: int, actor_id: int | None = None, role: str = "owner") -> None:
    """O dono nasce junto com o caderno; a linha pertence a ele e invalida a foto dele."""
    documents.write(
        "notebook_members",
        f"{user_id}_{notebook_id}",
        {
            "user_id": str(user_id),
            "notebook_id": str(notebook_id),
            "role": role,
            "created_at": documents.now(),
        },
        owner_id=actor_id if actor_id is not None else user_id,
    )
