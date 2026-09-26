"""Query helpers shared by the routers: counters, summaries and full-text-ish search.

O Appwrite não tem `JOIN` nem `GROUP BY`: cada função aqui lê a **foto** do usuário
(`store().snapshot`) e conta/ordena em Python. Consulta pontual só onde a assinatura não traz o
dono (`block_counts_for_notes` e os quatro `note_*`, que recebem a nota), e sempre por `equal` com
no máximo 100 valores por chamada — o teto medido nesta instância.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Iterable, Literal

from .markdown import UNTITLED
from .schemas import (
    Backlink,
    NoteRelated,
    NoteRelationOut,
    NotebookAffinity,
    NotebookOut,
    NotebookSummary,
    NoteSummary,
    RelatableNote,
    RelationEdge,
    SearchHit,
    empty_counts,
)
from .store import documents
from .store.client import Store, equal

EXCERPT_LENGTH = 180
# O servidor recusa `equal` com mais de 100 valores (medido): a consulta por lista vai fatiada.
QUERY_VALUES = 100
# Ordem de uma linha sem `created_at`: quem tem instante vem antes.
_EPOCH = datetime.min


# ------------------------------------------------------------------ foto


def snapshot(db: Store, user_id: int) -> dict[str, list[documents.Row]]:
    """A foto do usuário com as listas que o ORM pendurava em cada linha.

    Os blocos e as tags de uma nota não existem mais no modelo: quem monta um resumo lê a lista da
    própria linha, na mesma ordem de antes (posição do bloco, nome da tag). Pendurar é idempotente
    — a foto do store é o mesmo objeto enquanto o TTL durar — e evita uma consulta por nota.
    """
    photo = db.snapshot(user_id)
    blocks = _group(photo["blocks"], "note_id")
    tags = _tags_by(photo, "note_tags", "note_id")
    for note in photo["notes"]:
        note["blocks"] = sorted(blocks[note.id], key=_block_order)
        note["tags"] = tags.get(note.id, ())
    return photo


def _group(rows: list[documents.Row], column: str) -> dict[int, list[documents.Row]]:
    grouped: dict[int, list[documents.Row]] = defaultdict(list)
    for row in rows:
        grouped[getattr(row, column)].append(row)
    return grouped


def _tags_by(
    photo: dict[str, list[documents.Row]], table: str, column: str
) -> dict[int, list[documents.Row]]:
    """As tags de cada linha da junção (`note_tags`/`notebook_tags`), na ordem do ORM.

    Tag de outro dono não está na foto, então a linha da junção fica sem ela.
    """
    known = {tag.id: tag for tag in photo["tags"]}
    grouped: dict[int, list[documents.Row]] = defaultdict(list)
    for link in photo[table]:
        tag = known.get(link.tag_id)
        if tag is not None:
            grouped[getattr(link, column)].append(tag)
    return {key: sorted(value, key=_tag_order) for key, value in grouped.items()}


# ------------------------------------------------------------------ ordem


def _block_order(block: documents.Row) -> tuple[int, int]:
    """`order_by="Block.position"` do ORM; o id desempata posições iguais."""
    return (block.position, block.id)


def _tag_order(tag: documents.Row) -> tuple[str, int]:
    """`order_by="Tag.name"` do ORM; o id desempata nomes iguais."""
    return (tag.name, tag.id)


def _recent(row: documents.Row) -> tuple[datetime, int]:
    """`order_by(updated_at.desc(), id.desc())`: o id desempata, como a lista de notas pede."""
    return (row.updated_at, row.id)


def _latest(row: documents.Row) -> tuple[datetime, int]:
    """`order_by(updated_at.desc())` sem desempate: no empate o SQLite devolvia o id crescente."""
    return (row.updated_at, -row.id)


def _inserted(row: documents.Row) -> tuple[bool, datetime, str]:
    """A ordem que o `ORDER BY id` dava: quem nasceu antes vem antes.

    Vínculo e menção têm chave composta (`12_34`) como rowId, então só as linhas migradas com id
    numérico trazem `id`: a ordem sai do instante em que a linha nasceu — o `created_at` do SQLite
    veio junto na migração — e o rowId desempata. Linha sem instante vai para o fim.
    """
    return (row.created_at is None, row.created_at or _EPOCH, row.row_id)


# ------------------------------------------------------------------ consultas pontuais


def _by_ids(db: Store, table: str, column: str, ids: Iterable[int]) -> list[documents.Row]:
    """As linhas de `table` cujo `column` está em `ids`.

    Não existe `IN` nas queries do Appwrite: `equal` com vários valores é um OR, limitado a 100
    valores por chamada, então os ids vão em fatias desse tamanho.
    """
    values = sorted({int(value) for value in ids})
    rows: list[documents.Row] = []
    for start in range(0, len(values), QUERY_VALUES):
        chunk = [str(value) for value in values[start : start + QUERY_VALUES]]
        rows.extend(documents.many(table, db.page(table, [equal(column, *chunk)])))
    return rows


def _related(db: Store, note_ids: Iterable[int]) -> dict[int, RelatableNote]:
    """O outro lado de um vínculo: a nota e o nome do caderno dela, como o `selectinload` dava."""
    notes = _by_ids(db, "notes", "$id", note_ids)
    titles = {
        notebook.id: notebook.title
        for notebook in _by_ids(db, "notebooks", "$id", {note.notebook_id for note in notes})
    }
    return {note.id: note_ref(note, titles.get(note.notebook_id, "")) for note in notes}


# ------------------------------------------------------------------ contagens


def _block_counts(
    blocks: Iterable[documents.Row], bucket_of: dict[int, int]
) -> dict[int, dict[str, int]]:
    """O `GROUP BY` em Python: `bucket_of` diz em que balde (caderno ou nota) cada bloco cai."""
    counts: dict[int, dict[str, int]] = defaultdict(empty_counts)
    for block in blocks:
        bucket_id = bucket_of.get(block.note_id)
        if bucket_id is None:
            continue
        bucket = counts[bucket_id]
        bucket[block.type] = bucket.get(block.type, 0) + 1
    return counts


def block_counts_by_notebook(db: Store, user_id: int) -> dict[int, dict[str, int]]:
    photo = snapshot(db, user_id)
    return _block_counts(photo["blocks"], {note.id: note.notebook_id for note in photo["notes"]})


def block_counts_for_notes(db: Store, note_ids: list[int]) -> dict[int, dict[str, int]]:
    """`note_ids` always comes from an already-scoped query, so it needs no owner of its own."""
    blocks = _by_ids(db, "blocks", "note_id", note_ids)
    return _block_counts(blocks, {note_id: note_id for note_id in note_ids})


def note_counts_by_notebook(db: Store, user_id: int) -> dict[int, int]:
    return dict(Counter(note.notebook_id for note in snapshot(db, user_id)["notes"]))


# ------------------------------------------------------------------ resumos


def notebook_summary(
    notebook: documents.Row,
    notes_count: int,
    counts: dict[str, int],
    relations_count: int,
    tags: Iterable[documents.Row] = (),
) -> NotebookSummary:
    """`relations_count` here is how many other notebooks this one reaches through its notes.

    `tags` vem de fora: o caderno não carrega lista nenhuma e a linha que o `notebook_detail`
    recebe (um `get` pontual) traz só os campos dele.
    """
    return NotebookSummary(
        id=notebook.id,
        title=notebook.title,
        description=notebook.description,
        created_at=notebook.created_at,
        updated_at=notebook.updated_at,
        tags=list(tags),
        notes_count=notes_count,
        counts={**empty_counts(), **counts},
        relations_count=relations_count,
    )


def list_notebook_summaries(db: Store, user_id: int) -> list[NotebookSummary]:
    photo = snapshot(db, user_id)
    counts = block_counts_by_notebook(db, user_id)
    notes = note_counts_by_notebook(db, user_id)
    affinity = affinity_counts_by_notebook(db, user_id)
    tags = _tags_by(photo, "notebook_tags", "notebook_id")
    return [
        notebook_summary(
            notebook,
            notes.get(notebook.id, 0),
            counts.get(notebook.id, {}),
            affinity.get(notebook.id, 0),
            tags.get(notebook.id, ()),
        )
        for notebook in sorted(photo["notebooks"], key=lambda row: (row.title, row.id))
    ]


def note_excerpt(note: documents.Row) -> str:
    """Os blocos chegam na própria linha: é a lista que a `snapshot` pendura em cada nota."""
    for block in note.get("blocks", ()):
        if block.type in ("text", "code") and block.text.strip():
            return " ".join(block.text.split())[:EXCERPT_LENGTH]
        if block.caption.strip():
            return " ".join(block.caption.split())[:EXCERPT_LENGTH]
        if block.url.strip():
            return block.url.strip()[:EXCERPT_LENGTH]
    return ""


def note_summary(
    note: documents.Row, counts: dict[str, int] | None, notebook_title: str
) -> NoteSummary:
    """`counts` and the notebook name come from the caller so nothing lazy-loads per note."""
    return NoteSummary(
        id=note.id,
        notebook_id=note.notebook_id,
        notebook_title=notebook_title,
        title=note.title,
        position=note.position,
        created_at=note.created_at,
        updated_at=note.updated_at,
        tags=list(note.get("tags", ())),
        counts={**empty_counts(), **(counts or {})},
        excerpt=note_excerpt(note),
    )


def notebook_detail(db: Store, user_id: int, notebook: documents.Row) -> NotebookOut:
    photo = snapshot(db, user_id)
    notes = sorted(
        (note for note in photo["notes"] if note.notebook_id == notebook.id),
        key=lambda note: (note.position, note.id),
    )
    counts = _block_counts(photo["blocks"], {note.id: note.id for note in notes})
    affinity = notebook_affinity(db, user_id).get(notebook.id, [])
    tags = _tags_by(photo, "notebook_tags", "notebook_id")
    return NotebookOut(
        **notebook_summary(
            notebook,
            len(notes),
            block_counts_by_notebook(db, user_id).get(notebook.id, {}),
            len(affinity),
            tags.get(notebook.id, ()),
        ).model_dump(),
        notes=[note_summary(note, counts.get(note.id), notebook.title) for note in notes],
        affinity=affinity,
    )


def note_ref(note: documents.Row, notebook_title: str) -> RelatableNote:
    """Label for a note seen from somewhere else; o caderno vem de fora (não há lazy load)."""
    return RelatableNote(
        id=note.id,
        title=note.title,
        notebook_id=note.notebook_id,
        notebook_title=notebook_title,
    )


# ------------------------------------------------------------------ vínculos da nota


def note_relations_for(db: Store, note: documents.Row) -> list[NoteRelationOut]:
    """Every declared relation that touches this note, with the other side resolved."""
    rows = {row.row_id: row for row in _by_ids(db, "note_relations", "source_id", [note.id])}
    rows.update({row.row_id: row for row in _by_ids(db, "note_relations", "target_id", [note.id])})
    others = _related(
        db, [row.source_id if row.source_id != note.id else row.target_id for row in rows.values()]
    )
    relations: list[NoteRelationOut] = []
    for row in sorted(rows.values(), key=_inserted):
        outgoing = row.source_id == note.id
        other = others.get(row.target_id if outgoing else row.source_id)
        if other is None:  # o outro lado é de outra conta: o vínculo não é visível aqui
            continue
        relations.append(
            NoteRelationOut(id=row.id, label=row.label, outgoing=outgoing, other=other)
        )
    return relations


def note_mentions(db: Store, note: documents.Row) -> list[RelatableNote]:
    """Notes cited by `[[…]]` inside this note's blocks."""
    blocks = _by_ids(db, "blocks", "note_id", [note.id])
    links = sorted(
        _by_ids(db, "block_links", "block_id", [block.id for block in blocks]), key=_inserted
    )
    others = _related(db, [link.note_id for link in links])
    mentions: list[RelatableNote] = []
    for link in links:
        other = others.get(link.note_id)
        if other is not None and all(mention.id != other.id for mention in mentions):
            mentions.append(other)
    return mentions


def note_backlinks(db: Store, note: documents.Row) -> list[Backlink]:
    """Blocks in other notes that cite this one, with the line they came from."""
    links = sorted(_by_ids(db, "block_links", "note_id", [note.id]), key=_inserted)
    blocks = {
        block.id: block
        for block in _by_ids(db, "blocks", "$id", [link.block_id for link in links])
    }
    sources = _related(db, [block.note_id for block in blocks.values()])
    backlinks: list[Backlink] = []
    for link in links:
        block = blocks.get(link.block_id)
        if block is None:  # menção vinda de um bloco de outra conta
            continue
        source = sources.get(block.note_id)
        if source is None or source.id == note.id:  # citing yourself is not a backlink
            continue
        backlinks.append(
            Backlink(
                note=source,
                block_id=link.block_id,
                excerpt=" ".join(block.text.split())[:EXCERPT_LENGTH],
            )
        )
    return backlinks


def note_related(db: Store, note: documents.Row) -> NoteRelated:
    return NoteRelated(
        relations=note_relations_for(db, note),
        mentions=note_mentions(db, note),
        backlinks=note_backlinks(db, note),
    )


# ------------------------------------------------------------------ listas


def all_note_summaries(
    db: Store, user_id: int, query: str = "", limit: int = 300
) -> list[NoteSummary]:
    """Every note of this user, most recently edited first: the global notes list."""
    photo = snapshot(db, user_id)
    titles = {notebook.id: notebook.title for notebook in photo["notebooks"]}
    term = query.strip().lower()
    recent = sorted(photo["notes"], key=_recent, reverse=True)
    notes = [note for note in recent if _holds(note.title, term)][:limit]
    counts = _block_counts(photo["blocks"], {note.id: note.id for note in notes})
    return [
        note_summary(note, counts.get(note.id), titles.get(note.notebook_id, "")) for note in notes
    ]


def notebook_affinity(db: Store, user_id: int) -> dict[int, list[NotebookAffinity]]:
    """Notebook pairs reached through their notes, counted per crossing link.

    Two notes in the same notebook add nothing: affinity is about what leaves the notebook.
    """
    photo = snapshot(db, user_id)
    notes = {note.id: note for note in photo["notes"]}
    blocks = {block.id: block for block in photo["blocks"]}
    pairs: dict[tuple[int, int], int] = defaultdict(int)

    for relation in photo["note_relations"]:
        left = notes.get(relation.source_id)
        right = notes.get(relation.target_id)
        if left is None or right is None or left.notebook_id == right.notebook_id:
            continue
        pairs[_pair(left.notebook_id, right.notebook_id)] += 1

    for link in photo["block_links"]:
        block = blocks.get(link.block_id)
        target = notes.get(link.note_id)
        if block is None or target is None:
            continue
        source = notes.get(block.note_id)
        if source is None or source.notebook_id == target.notebook_id:
            continue
        pairs[_pair(source.notebook_id, target.notebook_id)] += 1

    titles = {notebook.id: notebook.title for notebook in photo["notebooks"]}
    affinity: dict[int, list[NotebookAffinity]] = defaultdict(list)
    for (left, right), count in pairs.items():
        affinity[left].append(
            NotebookAffinity(notebook_id=right, title=titles.get(right, ""), links_count=count)
        )
        affinity[right].append(
            NotebookAffinity(notebook_id=left, title=titles.get(left, ""), links_count=count)
        )
    for entries in affinity.values():
        entries.sort(key=lambda entry: (-entry.links_count, entry.title))
    return affinity


def affinity_counts_by_notebook(db: Store, user_id: int) -> dict[int, int]:
    """How many other notebooks each notebook reaches through its notes."""
    return {
        notebook_id: len(entries)
        for notebook_id, entries in notebook_affinity(db, user_id).items()
    }


def relation_edges(db: Store, user_id: int) -> list[RelationEdge]:
    """Every link between this user's notes, declared or cited, for the graph."""
    photo = snapshot(db, user_id)
    notes = {note.id: note for note in photo["notes"]}
    blocks = {block.id: block for block in photo["blocks"]}
    edges: list[RelationEdge] = []
    for relation in sorted(photo["note_relations"], key=_inserted):
        source = notes.get(relation.source_id)
        target = notes.get(relation.target_id)
        if source is None or target is None:
            continue
        edges.append(_edge("relation", relation, source, target, relation.label))

    for link in sorted(photo["block_links"], key=_inserted):
        block = blocks.get(link.block_id)
        target = notes.get(link.note_id)
        source = notes.get(block.note_id) if block is not None else None
        if source is None or target is None or source.id == target.id:
            continue
        edges.append(_edge("mention", link, source, target, ""))
    return edges


def _edge(
    kind: Literal["relation", "mention"],
    row: documents.Row,
    source: documents.Row,
    target: documents.Row,
    label: str,
) -> RelationEdge:
    """A chave é o rowId: nas linhas de chave composta (`12_34`) o `id` numérico não existe."""
    return RelationEdge(
        key=f"{kind}:{row.row_id}",
        kind=kind,
        id=row.id,
        label=label,
        source_id=source.id,
        target_id=target.id,
        source_title=source.title or UNTITLED,
        target_title=target.title or UNTITLED,
        source_notebook_id=source.notebook_id,
        target_notebook_id=target.notebook_id,
    )


def _pair(left: int, right: int) -> tuple[int, int]:
    return (left, right) if left < right else (right, left)


# ------------------------------------------------------------------ busca


def _holds(text: str, needle: str) -> bool:
    """Case-insensitive como o `lower()` do SQLite; sem dobrar acento, e sem fulltext."""
    return needle in text.lower()


def search(db: Store, user_id: int, query: str, limit: int = 8) -> list[SearchHit]:
    """Filtra em Python: o `search` do Appwrite não acha um termo que está lá (medido)."""
    term = query.strip()
    if not term:
        return []
    needle = term.lower()
    photo = snapshot(db, user_id)
    notes = {note.id: note for note in photo["notes"]}
    hits: list[SearchHit] = []

    listed = sorted(photo["notebooks"], key=lambda row: (row.title, row.id))
    for notebook in [
        row for row in listed if _holds(row.title, needle) or _holds(row.description, needle)
    ][:limit]:
        hits.append(
            SearchHit(
                kind="notebook",
                id=notebook.id,
                notebook_id=notebook.id,
                title=notebook.title,
                snippet=notebook.description[:120],
            )
        )

    counted = Counter(link.tag_id for link in photo["note_tags"])
    for tag in [row for row in sorted(photo["tags"], key=_tag_order) if _holds(row.name, needle)][
        :limit
    ]:
        hits.append(
            SearchHit(kind="tag", id=tag.id, title=tag.name, snippet=f"{counted[tag.id]} notas")
        )

    for note in [
        row for row in sorted(photo["notes"], key=_latest, reverse=True) if _holds(row.title, needle)
    ][:limit]:
        hits.append(
            SearchHit(
                kind="note",
                id=note.id,
                notebook_id=note.notebook_id,
                note_id=note.id,
                title=note.title or "Nota sem título",
                snippet=note_excerpt(note),
            )
        )

    for block in [
        row
        for row in sorted(photo["blocks"], key=_latest, reverse=True)
        if _holds(row.text, needle) or _holds(row.url, needle) or _holds(row.caption, needle)
    ][:limit]:
        note = notes.get(block.note_id)
        if note is None:
            continue
        body = block.text or block.caption or block.url
        hits.append(
            SearchHit(
                kind="block",
                id=block.id,
                notebook_id=note.notebook_id,
                note_id=block.note_id,
                title=f"{block.type} · {note.title or 'Nota sem título'}",
                snippet=" ".join(body.split())[:140],
            )
        )
    return hits
