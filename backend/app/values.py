"""Valores que não são nem configuração nem dado: o que o app considera um bloco e o "agora".

`utcnow` devolve UTC **ingênuo** de propósito — é o formato que o SQLite gravava e que a API
serializa com `Z` na saída. Manter isso evita mexer em todo o resto do app.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Uma nota mistura estes tipos livremente; a ordem importa (Alt+Espaço cicla por ela).
BLOCK_TYPES: tuple[str, ...] = ("text", "code", "url", "image", "video")

ROLES: tuple[str, ...] = ("admin", "user")

# Papéis de quem participa de um caderno, do mais fraco ao mais forte.
ROLE_RANK: dict[str, int] = {"viewer": 0, "editor": 1, "owner": 2}

ACTIONS: tuple[str, ...] = (
    "created",
    "updated",
    "deleted",
    "tagged",
    "untagged",
    "linked",
    "unlinked",
    "uploaded",
    "reset",
)

ENTITIES: tuple[str, ...] = ("notebook", "note", "block", "tag", "relation", "media", "user")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
