"""Who may see which notebook — the single place that answers it.

Today every notebook has exactly one member (`owner`), written when the notebook is created. Sharing
means inserting another row here; no router changes.
"""

from __future__ import annotations

from sqlalchemy import Select, insert, select
from sqlalchemy.orm import Session

from .models import Block, Note, notebook_members

ROLE_RANK: dict[str, int] = {"viewer": 0, "editor": 1, "owner": 2}


def role_for(db: Session, user_id: int, notebook_id: int) -> str | None:
    return db.scalar(
        select(notebook_members.c.role).where(
            notebook_members.c.user_id == user_id,
            notebook_members.c.notebook_id == notebook_id,
        )
    )


def allows(role: str | None, minimum: str) -> bool:
    return role is not None and ROLE_RANK.get(role, -1) >= ROLE_RANK[minimum]


def readable_notebook_ids(user_id: int) -> Select:
    """Subquery for `Notebook.id.in_(...)`: every notebook the user can at least read."""
    return select(notebook_members.c.notebook_id).where(notebook_members.c.user_id == user_id)


def writable_notebook_ids(user_id: int) -> Select:
    return select(notebook_members.c.notebook_id).where(
        notebook_members.c.user_id == user_id,
        notebook_members.c.role.in_(("owner", "editor")),
    )


def readable_note_ids(user_id: int) -> Select:
    """Notes and blocks hang off notebooks, so this is what filters them."""
    return select(Note.id).where(Note.notebook_id.in_(readable_notebook_ids(user_id)))


def readable_block_ids(user_id: int) -> Select:
    return select(Block.id).where(Block.note_id.in_(readable_note_ids(user_id)))


def add_member(db: Session, notebook_id: int, user_id: int, role: str = "owner") -> None:
    db.execute(
        insert(notebook_members).values(notebook_id=notebook_id, user_id=user_id, role=role)
    )
