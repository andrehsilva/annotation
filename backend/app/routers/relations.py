from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import deps, services
from ..schemas import RelationEdge
from ..store import Store
from ..store.documents import Row

router = APIRouter(prefix="/api/relations", tags=["relations"])


@router.get("", response_model=list[RelationEdge])
def list_relations(
    user: Row = Depends(deps.current_user), db: Store = Depends(deps.get_db)
) -> list[RelationEdge]:
    """Todo vínculo entre notas, declarado ou citado, para a visão de grafo."""
    return services.relation_edges(db, user.id)
