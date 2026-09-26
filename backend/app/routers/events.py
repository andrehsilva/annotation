"""O feed de atividade atrás da campainha: as últimas ações e quantas ainda não foram vistas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from .. import deps, events
from ..schemas import EventFeed, EventOut
from ..store import Store
from ..store.documents import Row

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=EventFeed)
def list_events(
    limit: int = Query(events.FEED_LIMIT, ge=1, le=events.FEED_MAX),
    user: Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> EventFeed:
    rows = events.feed(db, user, limit)
    names = events.actors(db, rows)
    return EventFeed(
        items=[
            EventOut(
                id=row.id,
                action=row.action,
                entity=row.entity,
                target=row.target,
                detail=row.detail,
                created_at=row.created_at,
                actor=names.get(row.user_id, ""),
                mine=row.user_id == user.id,
            )
            for row in rows
        ],
        unread=events.unseen(db, user),
    )


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(user: Row = Depends(deps.current_user), db: Store = Depends(deps.get_db)) -> Response:
    events.mark_seen(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
