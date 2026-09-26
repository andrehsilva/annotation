"""Resolve `[[Nota]]` mentions written inside blocks into rows of `block_links`.

A mention is stored as a note id, so renaming the target keeps the link alive; the text itself is
rewritten to match (`rename_in_mentions`) because the raw `[[Título]]` is what the author reads.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .store import documents
from .store.client import Store, equal

MENTION = re.compile(r"\[\[([^\[\]]+)\]\]")


def parse_mentions(text: str) -> list[str]:
    """Titles named by `[[…]]`, in the order they appear, blanks dropped."""
    return [match.strip() for match in MENTION.findall(text or "") if match.strip()]


def resolve(db: Store, titles: list[str], exclude_note_id: int, user_id: int) -> list[int]:
    """Ids of the notes those titles name; unknown titles and self-mentions are dropped.

    Only the author's own notes are looked up: `[[Título]]` must never reach into another account.
    A foto do usuário já é esse escopo — as notas dela são as das notas legíveis por ele.
    """
    if not {title.lower() for title in titles}:
        return []
    return _pick(_titles(db.snapshot(user_id)["notes"]), titles, exclude_note_id)


def reindex_block(db: Store, block, user_id: int, transaction_id: str | None = None) -> None:
    """Rewrite one block's mentions from its current text; the caller commits."""
    _drop(db, block.id)
    if block.type != "text":
        return
    mentions = parse_mentions(block.text)
    cited = _pick(_titles(db.snapshot(user_id)["notes"]), mentions, block.note_id)
    _relink(db, block, user_id, cited, transaction_id)


def rename_in_mentions(
    db: Store, old_title: str, new_title: str, user_id: int, transaction_id: str | None = None
) -> None:
    """Point every `[[old]]` of this user at the renamed note by rewriting that text."""
    old, new = (old_title or "").strip(), (new_title or "").strip()
    if not old or old == new:
        return
    # Uma foto só para a varredura inteira: escrever um bloco invalida a foto do usuário e reler
    # no meio do caminho traria o texto antigo de novo (a transação ainda não commitou).
    photo = db.snapshot(user_id)
    titles = _titles(photo["notes"])
    renamed = titles.get(old.lower())
    if renamed is not None:
        # O título novo ainda não aparece na foto (a rota o grava na mesma transação): quem citava
        # `[[velho]]` passa a citar `[[novo]]` apontando para a mesma nota. Menor id continua vencendo.
        current = titles.get(new.lower())
        titles[new.lower()] = renamed if current is None else min(current, renamed)
    needle = f"[[{old.lower()}]]"
    for block in photo["blocks"]:
        if needle not in (block.text or "").lower():
            continue
        text = _swap(block.text, old, new)
        documents.change(
            "blocks",
            block.id,
            {"text": text, "updated_at": documents.now()},
            owner_id=user_id,
            transaction_id=transaction_id,
        )
        _drop(db, block.id)
        cited = _pick(titles, parse_mentions(text), block.note_id)
        _relink(db, block, user_id, cited, transaction_id)


def _titles(notes: Iterable[documents.Row]) -> dict[str, int]:
    """`{título em minúsculas: menor id}` — o desempate que o app já usava para título repetido."""
    found: dict[str, int] = {}
    for note in notes:
        key = note.title.lower()
        if key not in found or note.id < found[key]:
            found[key] = note.id
    return found


def _pick(titles: dict[str, int], names: list[str], exclude_note_id: int) -> list[int]:
    """Ids na ordem em que os títulos aparecem, sem repetir e sem a própria nota."""
    linked: list[int] = []
    for name in names:
        note_id = titles.get(name.lower())
        if note_id is not None and note_id != exclude_note_id and note_id not in linked:
            linked.append(note_id)
    return linked


def _drop(db: Store, block_id: int) -> None:
    """Some com os vínculos antigos do bloco antes de recriá-los.

    O delete sai na hora (o `Store` não apaga dentro da transação) — e é isso que garante que o par
    `(block_id, note_id)` não colida com o índice unique no commit das menções novas.
    """
    db.delete_where("block_links", [equal("block_id", str(block_id))])


def _relink(
    db: Store, block, user_id: int, note_ids: list[int], transaction_id: str | None
) -> None:
    """As menções entram no commit da escrita do bloco (ou num só, quando não há transação)."""
    if not note_ids:
        return
    operations = [
        documents.operation(
            "block_links",
            documents.record_id("block_links"),
            {
                "block_id": str(block.id),
                "note_id": str(note_id),
                "created_at": documents.now(),
            },
        )
        for note_id in note_ids
    ]
    if transaction_id is None:
        with db.transaction() as tx:
            db.stage(tx, operations)
        db.invalidate(user_id)  # quem abriu a transação aqui foi este helper
        return
    db.stage(transaction_id, operations)


def _swap(text: str, old: str, new: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"[[{new}]]" if match.group(1).strip().lower() == old.lower() else match.group(0)

    return MENTION.sub(replace, text or "")
