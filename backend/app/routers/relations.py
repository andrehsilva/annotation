from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import deps, services
from ..database import get_db
from ..models import User
from ..schemas import RelationEdge

router = APIRouter(prefix="/api/relations", tags=["relations"])


@router.get("", response_model=list[RelationEdge])
def list_relations(
    user: User = Depends(deps.current_user), db: Session = Depends(get_db)
) -> list[RelationEdge]:
    """Every link between notes, declared or cited, for the graph view."""
    return services.relation_edges(db, user.id)
