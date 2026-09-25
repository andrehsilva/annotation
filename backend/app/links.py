"""Resolve `[[Nota]]` mentions written inside blocks into rows of `block_links`.

A mention is stored as a note id, so renaming the target keeps the link alive; the text itself is
rewritten to match (`rename_in_mentions`) because the raw `[[Título]]` is what the author reads.
"""

from __future__ import annotations

import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import acl
from .models import Block, BlockLink, Note

MENTION = re.compile(r"\[\[([^\[\]]+)\]\]")


def parse_mentions(text: str) -> list[str]:
    """Titles named by `[[…]]`, in the order they appear, blanks dropped."""
    return [match.strip() for match in MENTION.findall(text or "") if match.strip()]


def resolve(db: Session, titles: list[str], exclude_note_id: int, user_id: int) -> list[int]:
    """Ids of the notes those titles name; unknown titles and self-mentions are dropped.

    Only the author's own notes are looked up: `[[Título]]` must never reach into another account.
    """
    keys = {title.lower() for title in titles}
    if not keys:
        return []
    rows = db.execute(
        select(Note.id, func.lower(Note.title))
        .where(
            func.lower(Note.title).in_(keys),
            Note.notebook_id.in_(acl.readable_notebook_ids(user_id)),
        )
        .order_by(Note.id)
    ).all()
    found: dict[str, int] = {}
    for note_id, title in rows:
        if note_id != exclude_note_id and title not in found:
            found[title] = note_id  # the lowest id wins when two notes share a title
    linked: list[int] = []
    for title in titles:
        note_id = found.get(title.lower())
        if note_id is not None and note_id not in linked:
            linked.append(note_id)
    return linked


def reindex_block(db: Session, block: Block, user_id: int) -> None:
    """Rewrite one block's mentions from its current text; the caller commits."""
    db.execute(delete(BlockLink).where(BlockLink.block_id == block.id))
    if block.type != "text":
        return
    for note_id in resolve(db, parse_mentions(block.text), block.note_id, user_id):
        db.add(BlockLink(block_id=block.id, note_id=note_id))


def rename_in_mentions(db: Session, old_title: str, new_title: str, user_id: int) -> None:
    """Point every `[[old]]` of this user at the renamed note by rewriting that text."""
    old, new = (old_title or "").strip(), (new_title or "").strip()
    if not old or old == new:
        return
    db.flush()  # the rename may still be pending, and resolve() reads titles from the database
    pattern = f"%[[{_escaped(old.lower())}]]%"
    blocks = db.scalars(
        select(Block).where(
            Block.note_id.in_(acl.readable_note_ids(user_id)),
            func.lower(Block.text).like(pattern, escape="\\"),
        )
    ).all()
    for block in blocks:
        block.text = _swap(block.text, old, new)
        reindex_block(db, block, user_id)


def _escaped(title: str) -> str:
    return title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _swap(text: str, old: str, new: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"[[{new}]]" if match.group(1).strip().lower() == old.lower() else match.group(0)

    return MENTION.sub(replace, text or "")
