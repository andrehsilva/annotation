"""The activity feed behind the bell: the last few actions, plus how many are unread."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from .. import deps, events
from ..database import get_db
from ..models import User
from ..schemas import EventFeed, EventOut

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=EventFeed)
def list_events(
    limit: int = Query(events.FEED_LIMIT, ge=1, le=events.FEED_MAX),
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
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
def mark_read(
    user: User = Depends(deps.current_user), db: Session = Depends(get_db)
) -> Response:
    events.mark_seen(db, user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
