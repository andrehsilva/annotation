"""SQLAlchemy models: notebook -> notes -> blocks, plus tags and notebook relations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# A note can freely mix these; order matters (Alt+Space cycles through it).
BLOCK_TYPES: tuple[str, ...] = ("text", "code", "url", "image", "video")


def utcnow() -> datetime:
    """Naive UTC; SQLite stores no offset, so the API re-attaches 'Z' on the way out."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


notebook_tags = Table(
    "notebook_tags",
    Base.metadata,
    Column("notebook_id", ForeignKey("notebooks.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

note_tags = Table(
    "note_tags",
    Base.metadata,
    Column("note_id", ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    """Login identity. Nothing but notebooks holds data, and notebooks hang off membership."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80), default="")
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16), default="user")  # "admin" | "user"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Everything up to this instant has been read on the bell; per account, not per browser.
    activity_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Event(Base):
    """One thing somebody did. The bell shows the last few, scoped by who may see them."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(16))  # created | updated | deleted | linked | ...
    entity: Mapped[str] = mapped_column(String(16))  # notebook | note | block | tag | relation | ...
    target: Mapped[str] = mapped_column(String(200), default="")  # label kept even if it is deleted
    # Second label for the actions that have two parts, like "tag X on note Y".
    detail: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SessionToken(Base):
    """Server-side session: the cookie carries the secret, this table only its sha256."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship()


notebook_members = Table(
    "notebook_members",
    Base.metadata,
    Column("notebook_id", ForeignKey("notebooks.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    # owner > editor > viewer. Sharing (fase 2) is a new row here, not a new access path.
    Column("role", String(16), nullable=False, default="owner"),
    Column("created_at", DateTime, default=utcnow),
)


class MediaFile(Base):
    """One uploaded file; its owner decides whether /media serves it."""

    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(120), unique=True)
    original_name: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(80), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notebook(Base):
    __tablename__ = "notebooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    notes: Mapped[list["Note"]] = relationship(
        back_populates="notebook",
        cascade="all, delete-orphan",
        order_by="Note.position",
    )
    tags: Mapped[list["Tag"]] = relationship(
        secondary=notebook_tags,
        back_populates="notebooks",
        order_by="Tag.name",
    )


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    notebook_id: Mapped[int] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    notebook: Mapped[Notebook] = relationship(back_populates="notes")
    blocks: Mapped[list["Block"]] = relationship(
        back_populates="note",
        cascade="all, delete-orphan",
        order_by="Block.position",
    )
    tags: Mapped[list["Tag"]] = relationship(
        secondary=note_tags,
        back_populates="notes",
        order_by="Tag.name",
    )


class Block(Base):
    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(16), default="text")
    text: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(40), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    note: Mapped[Note] = relationship(back_populates="blocks")


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_tag_owner_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    color: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    notebooks: Mapped[list[Notebook]] = relationship(
        secondary=notebook_tags, back_populates="tags"
    )
    notes: Mapped[list[Note]] = relationship(secondary=note_tags, back_populates="tags")


class DriveFile(Base):
    """Which Drive file mirrors a note; the row dies with the note, the Drive file does not."""

    __tablename__ = "drive_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), unique=True, index=True
    )
    file_id: Mapped[str] = mapped_column(String(64))
    folder_id: Mapped[str] = mapped_column(String(64))
    drive_path: Mapped[str] = mapped_column(String(400))  # "Caderno/Nota.md"
    checksum: Mapped[str] = mapped_column(String(64))  # sha256 of the markdown already sent
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DriveState(Base):
    """Tiny key/value bag for the Drive export, one bag per user: folder ids, media links, last run."""

    __tablename__ = "drive_state"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class NoteRelation(Base):
    """Undirected-in-practice link between two notes; direction only names the author."""

    __tablename__ = "note_relations"
    __table_args__ = (UniqueConstraint("source_id", "target_id", name="uq_note_relation_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    source: Mapped[Note] = relationship(foreign_keys=[source_id])
    target: Mapped[Note] = relationship(foreign_keys=[target_id])


class BlockLink(Base):
    """A `[[Nota]]` mention inside a block, resolved to the note it names."""

    __tablename__ = "block_links"
    __table_args__ = (UniqueConstraint("block_id", "note_id", name="uq_block_link"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id", ondelete="CASCADE"), index=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    block: Mapped[Block] = relationship()
    note: Mapped[Note] = relationship()
