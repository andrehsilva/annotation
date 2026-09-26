"""Render a note as the markdown file that goes to the Drive export.

One file per note, deterministic: the same note always yields the same bytes, which is what lets
the export compare checksums instead of timestamps.

As linhas chegam normalizadas do store (`note.title`, `block.text`, ...). Relacionamento não
existe no Appwrite, então quem chama monta os pedaços — blocos, tags e o título do caderno vêm do
`store().snapshot(user_id)`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from .store.documents import Row

UNTITLED = "Nota sem título"
MEDIA_PREFIX = "/media/"
UNSAFE_CHARS = '<>:"/\\|?*'
MAX_STEM = 120


def _iso_z(value: datetime) -> str:
    """Same conversion the API uses on the way out: naive UTC in, '...Z' out."""
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: str | None) -> str:
    """Column defaults only land on insert, so a block still in memory reads as empty."""
    return value or ""


def _one_line(text: str | None) -> str:
    return " ".join(_text(text).split())


def _render(block: Row, media_links: Mapping[str, str]) -> str:
    url = _text(block.url).strip()
    caption = _text(block.caption).strip()
    if url.startswith(MEDIA_PREFIX):
        url = media_links.get(url, url)
    if block.type == "code":
        fence = f"```{_text(block.language).strip()}"
        return f"{fence}\n{_text(block.text)}\n```"
    if block.type == "image":
        return f"![{caption}]({url})"
    if block.type == "video":
        return f"[▶ {caption or url}]({url})"
    if block.type == "url":
        return f"[{caption or url}]({url})"
    return _text(block.text)


def note_markdown(
    note: Row,
    blocks: Sequence[Row] = (),
    *,
    notebook_title: str = "",
    tags: Sequence[str] = (),
    media_links: Mapping[str, str] | None = None,
    related: Sequence[str] = (),
    mentions: Sequence[str] = (),
) -> str:
    """Front matter + heading + one section per block, media urls swapped for their Drive link.

    `blocks` (na ordem do editor), `tags` e `notebook_title` vêm de fora porque a linha normalizada
    não carrega relacionamento: no Appwrite, caderno e tags são consultas, não atributos.
    """
    links = media_links or {}
    title = _one_line(note.title) or UNTITLED
    front = [
        "---",
        f"notebook: {_one_line(notebook_title)}",
        f"note: {title}",
        f"tags: [{', '.join(_one_line(tag) for tag in tags)}]",
        f"related: [{', '.join(_one_line(other) for other in related)}]",
        f"mentions: [{', '.join(_one_line(other) for other in mentions)}]",
        f"created: {_iso_z(note.created_at)}",
        f"updated: {_iso_z(note.updated_at)}",
        f"notai_id: {note.id}",
        "---",
    ]
    parts = ["\n".join(front), "", f"# {title}"]
    for block in blocks:
        if not (
            _text(block.text).strip()
            or _text(block.url).strip()
            or _text(block.caption).strip()
        ):
            continue
        parts.extend(["", _render(block, links)])
    return "\n".join(parts) + "\n"


def file_stem(title: str, fallback: str) -> str:
    """Filesystem-safe file name (no extension) for a note, never empty."""
    cleaned = "".join("-" if char in UNSAFE_CHARS else char for char in title)
    cleaned = " ".join(cleaned.split()).strip(" .")[:MAX_STEM].strip(" .")
    return cleaned or fallback
