"""Pydantic request/response contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from .values import BLOCK_TYPES

BlockType = Literal["text", "code", "url", "image", "video", "pdf"]

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
    # Quem escreveu o bloco, quando não é quem está lendo: é o que a nota compartilhada mostra em cada
    # bloco. Vazio para os blocos da própria conta (e para um autor já apagado).
    author: str = ""
    created_at: UTCDateTime
    updated_at: UTCDateTime


# Tetos do conteúdo. O texto do bloco é a única coluna grande do app e a foto do usuário (usada por
# quase toda rota) fica inteira em memória por 30 s: sem teto, um usuário enche a RAM do processo
# compartilhado. 100 mil caracteres é ~50x o maior bloco real.
MAX_BLOCK_TEXT = 100_000


class BlockIn(BaseModel):
    type: BlockType = "text"
    text: str = Field(default="", max_length=MAX_BLOCK_TEXT)
    language: str = Field(default="", max_length=40)
    url: str = Field(default="", max_length=2000)
    caption: str = Field(default="", max_length=1000)
    position: int | None = None


class BlockPatch(BaseModel):
    type: BlockType | None = None
    text: str | None = Field(default=None, max_length=MAX_BLOCK_TEXT)
    language: str | None = Field(default=None, max_length=40)
    url: str | None = Field(default=None, max_length=2000)
    caption: str | None = Field(default=None, max_length=1000)


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
    author: str = ""
    updated_at: UTCDateTime
    note_id: int
    note_title: str


class NoteSummary(ORMModel):
    """Uma nota na lista: é a unidade do app — tem dono, papel e compartilhamento próprios."""

    id: int
    title: str
    position: int
    created_at: UTCDateTime
    updated_at: UTCDateTime
    tags: list[TagOut]
    counts: dict[str, int]
    excerpt: str
    # Quantos vínculos (declarados ou citações) tocam esta nota.
    relations_count: int = 0
    # Compartilhamento: o papel de quem pediu (owner/editor/viewer), de quem é a nota e, para o dono,
    # com que grupos ela saiu daqui.
    role: str = "owner"
    owner_id: int
    owner_name: str = ""
    shared: bool = False
    shared_groups: list[str] = []
    shared_people: int = 0


class NoteOut(NoteSummary):
    blocks: list[BlockOut]
    relations: list[NoteRelationOut] = []


class NoteIn(BaseModel):
    title: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=MAX_BLOCK_TEXT)


class NotePatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    position: int | None = None


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


class RelatableNote(BaseModel):
    """A note seen from another one: enough to label it and open it."""

    id: int
    title: str


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


class NoteMemberOut(BaseModel):
    """Quem alcança a nota: o dono, os membros diretos e os que vêm por grupo."""

    user_id: int
    display_name: str
    email: str
    role: str
    owner: bool
    groups: list[str] = []


class NoteGroupIn(BaseModel):
    role: str = "editor"


class NoteGroupOut(BaseModel):
    """Um grupo da nota, como o painel de compartilhar mostra."""

    group_id: int
    name: str
    role: str
    members: int


class NoteSharingOut(BaseModel):
    """O painel de compartilhar: quem alcança, com qual grupo e com quais eu posso compartilhar."""

    role: str
    can_share: bool
    members: list[NoteMemberOut]
    groups: list[NoteGroupOut]
    available: list[GroupOut]


class GroupOut(BaseModel):
    id: int
    name: str
    created_at: UTCDateTime
    members: int


class GroupDetail(GroupOut):
    member_ids: list[int]


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class NotebookIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)


class NotebookPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class MediaOut(BaseModel):
    url: str
    kind: Literal["image", "video", "pdf"]
    name: str
    size: int


class SearchHit(BaseModel):
    kind: Literal["note", "block", "tag"]
    id: int
    note_id: int | None = None
    title: str
    snippet: str


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]


class Stats(BaseModel):
    notes: int
    blocks: int
    tags: int
    relations: int
    counts: dict[str, int]


class GithubStatus(BaseModel):
    """O estado da publicação: se há token salvo e o link do que já saiu."""

    connected: bool
    published: list[dict] = []


class GistOut(BaseModel):
    """O link do gist da nota; `updated` diz se ele já existia (foi atualizado, não criado)."""

    url: str
    updated: bool


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
    # Nulo = a introdução do primeiro login ainda não foi dispensada: o SPA a abre ao entrar.
    welcome_seen_at: UTCDateTime | None = None


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
    notes: int
    blocks: int
    media_bytes: int


def empty_counts() -> dict[str, int]:
    return {block_type: 0 for block_type in BLOCK_TYPES}
