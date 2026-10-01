"""A nota como markdown — o que vai para o gist.

Uma nota vira um `.md`: cabeçalho (`# título`), um pedaço por bloco, na ordem do editor. As linhas
chegam normalizadas do store (`note.title`, `block.text`, ...); as tags vêm de fora, porque no
Appwrite elas são consulta, não atributo.

O nome do arquivo dentro do gist também sai daqui: é o título em forma segura, com `.md` no fim.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from .store.documents import Row
from .values import UNTITLED

UNSAFE_CHARS = '<>:"/\\|?*'
MAX_STEM = 120
# O gist aceita um nome de arquivo; o caminho é sempre plano.
EXTENSION = ".md"


def _iso_z(value: datetime) -> str:
    """Mesma conversão da API na saída: UTC ingênuo entra, '...Z' sai."""
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: str | None) -> str:
    """Os defaults de coluna só entram no insert: um bloco ainda em memória lê vazio."""
    return value or ""


def _one_line(text: str | None) -> str:
    return " ".join(_text(text).split())


def _render(block: Row) -> str:
    url = _text(block.url).strip()
    caption = _text(block.caption).strip()
    if block.type == "code":
        return f"```{_text(block.language).strip()}\n{_text(block.text)}\n```"
    if block.type == "image":
        return f"![{caption}]({url})"
    if block.type == "video":
        return f"[▶ {caption or url}]({url})"
    if block.type == "pdf":
        return f"[PDF {caption or url}]({url})"
    if block.type == "url":
        return f"[{caption or url}]({url})"
    return _text(block.text)


def note_markdown(
    note: Row,
    blocks: Sequence[Row] = (),
    *,
    tags: Sequence[str] = (),
) -> str:
    """`# título`, os blocos na ordem do editor e, no fim, as tags — quando existirem."""
    title = _one_line(note.title) or UNTITLED
    parts = [f"# {title}"]
    for block in blocks:
        if not (
            _text(block.text).strip() or _text(block.url).strip() or _text(block.caption).strip()
        ):
            continue
        parts.extend(["", _render(block)])
    tags_line = ", ".join(_one_line(tag) for tag in tags if _one_line(tag))
    if tags_line:
        parts.extend(["", f"<sub>tags: {tags_line}</sub>"])
    parts.extend(["", f"<sub>atualizado {_iso_z(note.updated_at)} · AnotAI #{note.id}</sub>"])
    return "\n".join(parts) + "\n"


def gist_filename(title: str, note_id: int) -> str:
    """Nome do arquivo dentro do gist: o título em forma segura, nunca vazio nem repetido."""
    cleaned = "".join("-" if char in UNSAFE_CHARS else char for char in title)
    cleaned = " ".join(cleaned.split()).strip(" .")[:MAX_STEM].strip(" .")
    # O id no fim evita que duas notas de mesmo título se sobrescrevam ao subir para a mesma conta.
    return f"{cleaned or f'nota-{note_id}'}{EXTENSION}"
