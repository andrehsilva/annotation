from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import deps, services
from ..schemas import SearchResults, Stats, empty_counts
from ..store import Store
from ..store.documents import Row

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=SearchResults)
def search(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=8, ge=1, le=30),
    user: Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> SearchResults:
    return SearchResults(query=q, hits=services.search(db, user.id, q, limit))


@router.get("/stats", response_model=Stats)
def stats(
    user: Row = Depends(deps.current_user), db: Store = Depends(deps.get_db)
) -> Stats:
    """Totais do painel: só o que é do dono, nunca o banco inteiro.

    A foto do usuário já é a lista do que ele alcança (cadernos próprios + onde é membro, e as
    notas/blocos desses cadernos), então contar é varrer essa foto — não existe `GROUP BY` aqui.
    """
    photo = db.snapshot(user.id)
    notebook_ids = {row.id for row in photo["notebooks"]} | {
        row.notebook_id for row in photo["notebook_members"]
    }
    note_ids = {row.id for row in photo["notes"]}
    counts = empty_counts()
    for block in photo["blocks"]:
        counts[block.type] = counts.get(block.type, 0) + 1
    return Stats(
        notebooks=len(notebook_ids),
        notes=len(note_ids),
        blocks=len(photo["blocks"]),
        tags=len(photo["tags"]),
        relations=sum(
            1
            for row in photo["note_relations"]
            if row.source_id in note_ids and row.target_id in note_ids
        ),
        counts=counts,
    )
