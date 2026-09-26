"""Pydantic request/response contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from .values import BLOCK_TYPES

BlockType = Literal["text", "code", "url", "image", "video"]

UTCDateTime = Annotated[
    datetime,
    PlainSerializer(
        lambda value: value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        return_type=str,
        when_used="json",
    ),
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TagOut(ORMModel):
    id: int
    name: str
    color: str


class TagUsage(TagOut):
    notebooks_count: int
    notes_count: int


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(default="", max_length=16)

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("tag name cannot be blank")
        return trimmed


class BlockOut(ORMModel):
    id: int
    note_id: int
    position: int
    type: BlockType
    text: str
    language: str
    url: str
    caption: str
    created_at: UTCDateTime
    updated_at: UTCDateTime


class BlockIn(BaseModel):
    type: BlockType = "text"
    text: str = ""
    language: str = ""
    url: str = ""
    caption: str = ""
    position: int | None = None


class BlockPatch(BaseModel):
    type: BlockType | None = None
    text: str | None = None
    language: str | None = None
    url: str | None = None
    caption: str | None = None


class BlockReorder(BaseModel):
    block_ids: list[int]


class BlockListItem(BaseModel):
    """Flat view of every block of a kind, with enough context to jump back to its note."""

    id: int
    type: BlockType
    text: str
    language: str
    url: str
    caption: str
    updated_at: UTCDateTime
    note_id: int
    note_title: str
    notebook_id: int
    notebook_title: str


class NoteOut(ORMModel):
    id: int
    notebook_id: int
    title: str
    position: int
    created_at: UTCDateTime
    updated_at: UTCDateTime
    tags: list[TagOut]
    blocks: list[BlockOut]
    relations: list[NoteRelationOut] = []


class NoteSummary(ORMModel):
    id: int
    notebook_id: int
    notebook_title: str
    title: str
    position: int
    created_at: UTCDateTime
    updated_at: UTCDateTime
    tags: list[TagOut]
    counts: dict[str, int]
    excerpt: str


class NoteIn(BaseModel):
    title: str = Field(default="", max_length=200)
    text: str = ""


class NotePatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    position: int | None = None


class NotebookRef(ORMModel):
    id: int
    title: str


class RelationEdge(BaseModel):
    """A link between two notes: declared by hand or cited with `[[…]]`."""

    key: str
    kind: Literal["relation", "mention"]
    id: int
    label: str
    source_id: int
    target_id: int
    source_title: str
    target_title: str
    source_notebook_id: int
    target_notebook_id: int


class RelatableNote(BaseModel):
    """A note seen from another one: enough to label it, open it and place it in its notebook."""

    id: int
    title: str
    notebook_id: int
    notebook_title: str


class NoteRelationOut(BaseModel):
    id: int
    label: str
    outgoing: bool
    other: RelatableNote


class NoteRelationIn(BaseModel):
    target_id: int
    label: str = Field(default="", max_length=80)


class Backlink(BaseModel):
    note: RelatableNote
    block_id: int
    excerpt: str


class NoteRelated(BaseModel):
    """Everything around one note: declared relations, notes it cites, and who cites it."""

    relations: list[NoteRelationOut]
    mentions: list[RelatableNote]
    backlinks: list[Backlink]


class NotebookAffinity(BaseModel):
    """A notebook reached through its notes, with how many note links cross over."""

    notebook_id: int
    title: str
    links_count: int


class NotebookSummary(ORMModel):
    id: int
    title: str
    description: str
    created_at: UTCDateTime
    updated_at: UTCDateTime
    tags: list[TagOut]
    notes_count: int
    counts: dict[str, int]
    relations_count: int


class NotebookOut(NotebookSummary):
    notes: list[NoteSummary]
    affinity: list[NotebookAffinity]


class NotebookIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)


class NotebookPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class MediaOut(BaseModel):
    url: str
    kind: Literal["image", "video"]
    name: str
    size: int


class SearchHit(BaseModel):
    kind: Literal["notebook", "note", "block", "tag"]
    id: int
    notebook_id: int | None = None
    note_id: int | None = None
    title: str
    snippet: str


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]


class Stats(BaseModel):
    notebooks: int
    notes: int
    blocks: int
    tags: int
    relations: int
    counts: dict[str, int]


class SyncSummary(BaseModel):
    notes_sent: int
    notes_unchanged: int
    folders_created: int
    media_sent: int
    skipped_media: int
    errors: list[str]
    at: str


class DriveStatus(BaseModel):
    connected: bool
    has_client_file: bool
    auto_sync: bool
    pending: bool
    last_sync_at: str | None = None
    last_summary: SyncSummary | None = None
    last_error: str | None = None


class DriveSettings(BaseModel):
    auto_sync: bool


class EventOut(ORMModel):
    id: int
    action: str
    entity: str
    target: str
    detail: str
    created_at: UTCDateTime
    actor: str  # who did it; on a regular account it is always the reader
    mine: bool


class EventFeed(BaseModel):
    items: list[EventOut]
    unread: int


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class CredentialsIn(BaseModel):
    email: str = Field(max_length=160)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return value.strip().lower()


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class UserOut(ORMModel):
    id: int
    email: str
    display_name: str
    role: Literal["admin", "user"]
    is_active: bool
    created_at: UTCDateTime
    last_login_at: UTCDateTime | None = None


class UserCreateIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=160)
    display_name: str = Field(default="", max_length=80)
    password: str = Field(min_length=8, max_length=200)
    role: Literal["admin", "user"] = "user"

    @field_validator("email")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("display_name")
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()


class UserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None


class AdminPasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class AdminUserOut(UserOut):
    notebooks: int
    notes: int
    blocks: int
    media_bytes: int


def empty_counts() -> dict[str, int]:
    return {block_type: 0 for block_type in BLOCK_TYPES}
