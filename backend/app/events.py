"""Who did what: one row per write, and the little feed the bell shows at the top of the app.

The row is added, never committed, by `record` — the caller's commit carries it, so an action that
fails halfway leaves no trace.
"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .models import Event, User, utcnow

FEED_LIMIT = 5
FEED_MAX = 50

ACTIONS = (
    "created",
    "updated",
    "deleted",
    "tagged",
    "untagged",
    "linked",
    "unlinked",
    "uploaded",
)

ENTITIES = ("notebook", "note", "block", "tag", "relation", "media", "user")


def record(
    db: Session, user: User, action: str, entity: str, target: str = "", detail: str = ""
) -> None:
    db.add(
        Event(
            user_id=user.id,
            action=action,
            entity=entity,
            target=" ".join((target or "").split())[:200],
            detail=" ".join((detail or "").split())[:80],
        )
    )


def visible(user: User) -> Select:
    """The admin watches the whole platform; everybody else only their own moves."""
    statement = select(Event)
    if user.role != "admin":
        statement = statement.where(Event.user_id == user.id)
    return statement


def feed(db: Session, user: User, limit: int = FEED_LIMIT) -> list[Event]:
    statement = visible(user).order_by(Event.created_at.desc(), Event.id.desc()).limit(limit)
    return list(db.scalars(statement).all())


def unseen(db: Session, user: User) -> int:
    statement = visible(user)
    if user.activity_seen_at is not None:
        statement = statement.where(Event.created_at > user.activity_seen_at)
    return db.scalar(select(func.count()).select_from(statement.subquery())) or 0


def mark_seen(db: Session, user: User) -> None:
    user.activity_seen_at = utcnow()


def actors(db: Session, rows: list[Event]) -> dict[int, str]:
    """Name for each author in the page of rows, in one query."""
    ids = {row.user_id for row in rows}
    if not ids:
        return {}
    people = db.scalars(select(User).where(User.id.in_(ids))).all()
    return {person.id: person.display_name or person.email for person in people}
