"""Os grupos de que a conta participa — a lista que o painel de compartilhar oferece.

Grupo é o público do compartilhamento: quem está nele alcança o caderno que o dono compartilhou com
o grupo (inclusive quem entrar depois). Criar e manter grupos é do admin (`/api/admin/groups`); aqui
qualquer conta lê só os seus, que é o que o dono precisa para escolher com quem compartilhar.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import acl
from ..deps import current_user, get_db
from ..schemas import GroupOut
from ..store import Store
from ..store.documents import Row

router = APIRouter(prefix="/api/groups", tags=["groups"])


@router.get("", response_model=list[GroupOut])
def list_my_groups(db: Store = Depends(get_db), user: Row = Depends(current_user)) -> list[GroupOut]:
    return [
        GroupOut(id=group.id, name=group.name, created_at=group.created_at, members=0)
        for group in acl.my_groups(db, user.id)
    ]
