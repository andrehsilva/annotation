"""Query helpers shared by the routers: counters, summaries and full-text-ish search."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from . import acl
from .markdown import UNTITLED
from .models import Block, BlockLink, Note, NoteRelation, Notebook, Tag
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

EXCERPT_LENGTH = 180


def block_counts_by_notebook(db: Session, user_id: int) -> dict[int, dict[str, int]]:
    rows = db.execute(
        select(Note.notebook_id, Block.type, func.count(Block.id))
        .join(Block, Block.note_id == Note.id)
        .where(Note.notebook_id.in_(acl.readable_notebook_ids(user_id)))
        .group_by(Note.notebook_id, Block.type)
    ).all()
    counts: dict[int, dict[str, int]] = defaultdict(empty_counts)
    for notebook_id, block_type, total in rows:
        counts[notebook_id][block_type] = total
    return counts


def block_counts_for_notes(db: Session, note_ids: list[int]) -> dict[int, dict[str, int]]:
    """`note_ids` always comes from an already-scoped query, so it needs no owner of its own."""
    counts: dict[int, dict[str, int]] = defaultdict(empty_counts)
    if not note_ids:
        return counts
    rows = db.execute(
        select(Block.note_id, Block.type, func.count(Block.id))
        .where(Block.note_id.in_(note_ids))
        .group_by(Block.note_id, Block.type)
    ).all()
    for note_id, block_type, total in rows:
        counts[note_id][block_type] = total
    return counts


def note_counts_by_notebook(db: Session, user_id: int) -> dict[int, int]:
    rows = db.execute(
        select(Note.notebook_id, func.count(Note.id))
        .where(Note.notebook_id.in_(acl.readable_notebook_ids(user_id)))
        .group_by(Note.notebook_id)
    ).all()
    return {notebook_id: total for notebook_id, total in rows}


def notebook_summary(
    notebook: Notebook,
    notes_count: int,
    counts: dict[str, int],
    relations_count: int,
) -> NotebookSummary:
    """`relations_count` here is how many other notebooks this one reaches through its notes."""
    return NotebookSummary(
        id=notebook.id,
        title=notebook.title,
        description=notebook.description,
        created_at=notebook.created_at,
        updated_at=notebook.updated_at,
        tags=notebook.tags,
        notes_count=notes_count,
        counts={**empty_counts(), **counts},
        relations_count=relations_count,
    )


def list_notebook_summaries(db: Session, user_id: int) -> list[NotebookSummary]:
    notebooks = db.scalars(
        select(Notebook)
        .where(Notebook.id.in_(acl.readable_notebook_ids(user_id)))
        .options(selectinload(Notebook.tags))
        .order_by(Notebook.title)
    ).all()
    counts = block_counts_by_notebook(db, user_id)
    notes = note_counts_by_notebook(db, user_id)
    affinity = affinity_counts_by_notebook(db, user_id)
    return [
        notebook_summary(
            notebook,
            notes.get(notebook.id, 0),
            counts.get(notebook.id, {}),
            affinity.get(notebook.id, 0),
        )
        for notebook in notebooks
    ]


def note_excerpt(note: Note) -> str:
    for block in note.blocks:
        if block.type in ("text", "code") and block.text.strip():
            return " ".join(block.text.split())[:EXCERPT_LENGTH]
        if block.caption.strip():
            return " ".join(block.caption.split())[:EXCERPT_LENGTH]
        if block.url.strip():
            return block.url.strip()[:EXCERPT_LENGTH]
    return ""


def note_summary(note: Note, counts: dict[str, int] | None, notebook_title: str) -> NoteSummary:
    """`counts` and the notebook name come from the caller so nothing lazy-loads per note."""
    return NoteSummary(
        id=note.id,
        notebook_id=note.notebook_id,
        notebook_title=notebook_title,
        title=note.title,
        position=note.position,
        created_at=note.created_at,
        updated_at=note.updated_at,
        tags=note.tags,
        counts={**empty_counts(), **(counts or {})},
        excerpt=note_excerpt(note),
    )


def notebook_detail(db: Session, user_id: int, notebook: Notebook) -> NotebookOut:
    notes = notebook.notes
    counts = block_counts_for_notes(db, [note.id for note in notes])
    affinity = notebook_affinity(db, user_id).get(notebook.id, [])
    return NotebookOut(
        **notebook_summary(
            notebook,
            len(notes),
            block_counts_by_notebook(db, user_id).get(notebook.id, {}),
            len(affinity),
        ).model_dump(),
        notes=[note_summary(note, counts.get(note.id), notebook.title) for note in notes],
        affinity=affinity,
    )


def note_ref(note: Note) -> RelatableNote:
    """Label for a note seen from somewhere else; expects `note.notebook` to be loaded."""
    return RelatableNote(
        id=note.id,
        title=note.title,
        notebook_id=note.notebook_id,
        notebook_title=note.notebook.title,
    )


def note_relations_for(db: Session, note: Note) -> list[NoteRelationOut]:
    """Every declared relation that touches this note, with the other side resolved."""
    rows = db.scalars(
        select(NoteRelation)
        .options(
            selectinload(NoteRelation.source).selectinload(Note.notebook),
            selectinload(NoteRelation.target).selectinload(Note.notebook),
        )
        .where(or_(NoteRelation.source_id == note.id, NoteRelation.target_id == note.id))
        .order_by(NoteRelation.id)
    ).all()
    relations: list[NoteRelationOut] = []
    for relation in rows:
        outgoing = relation.source_id == note.id
        other = relation.target if outgoing else relation.source
        relations.append(
            NoteRelationOut(
                id=relation.id,
                label=relation.label,
                outgoing=outgoing,
                other=note_ref(other),
            )
        )
    return relations


def note_mentions(db: Session, note: Note) -> list[RelatableNote]:
    """Notes cited by `[[…]]` inside this note's blocks."""
    rows = db.scalars(
        select(BlockLink)
        .join(Block, Block.id == BlockLink.block_id)
        .options(selectinload(BlockLink.note).selectinload(Note.notebook))
        .where(Block.note_id == note.id)
        .order_by(BlockLink.id)
    ).all()
    mentions: list[RelatableNote] = []
    for link in rows:
        if all(mention.id != link.note_id for mention in mentions):
            mentions.append(note_ref(link.note))
    return mentions


def note_backlinks(db: Session, note: Note) -> list[Backlink]:
    """Blocks in other notes that cite this one, with the line they came from."""
    rows = db.scalars(
        select(BlockLink)
        .options(
            selectinload(BlockLink.block).selectinload(Block.note).selectinload(Note.notebook)
        )
        .where(BlockLink.note_id == note.id)
        .order_by(BlockLink.id)
    ).all()
    backlinks: list[Backlink] = []
    for link in rows:
        source = link.block.note
        if source.id == note.id:  # citing yourself is not a backlink
            continue
        backlinks.append(
            Backlink(
                note=note_ref(source),
                block_id=link.block_id,
                excerpt=" ".join((link.block.text or "").split())[:EXCERPT_LENGTH],
            )
        )
    return backlinks


def note_related(db: Session, note: Note) -> NoteRelated:
    return NoteRelated(
        relations=note_relations_for(db, note),
        mentions=note_mentions(db, note),
        backlinks=note_backlinks(db, note),
    )


def all_note_summaries(db: Session, user_id: int, query: str = "", limit: int = 300) -> list[NoteSummary]:
    """Every note of this user, most recently edited first: the global notes list."""
    statement = (
        select(Note)
        .where(Note.notebook_id.in_(acl.readable_notebook_ids(user_id)))
        .options(selectinload(Note.notebook), selectinload(Note.tags))
        .order_by(Note.updated_at.desc(), Note.id.desc())
        .limit(limit)
    )
    term = query.strip().lower()
    if term:
        statement = statement.where(func.lower(Note.title).like(f"%{term}%"))
    notes = db.scalars(statement).all()
    counts = block_counts_for_notes(db, [note.id for note in notes])
    return [
        note_summary(note, counts.get(note.id), note.notebook.title) for note in notes
    ]


def notebook_affinity(db: Session, user_id: int) -> dict[int, list[NotebookAffinity]]:
    """Notebook pairs reached through their notes, counted per crossing link.

    Two notes in the same notebook add nothing: affinity is about what leaves the notebook.
    """
    scope = acl.readable_notebook_ids(user_id)
    source_note = aliased(Note)
    target_note = aliased(Note)
    pairs: dict[tuple[int, int], int] = defaultdict(int)

    for left, right in db.execute(
        select(source_note.notebook_id, target_note.notebook_id)
        .select_from(NoteRelation)
        .join(source_note, source_note.id == NoteRelation.source_id)
        .join(target_note, target_note.id == NoteRelation.target_id)
        .where(source_note.notebook_id.in_(scope))
    ).all():
        if left != right:
            pairs[_pair(left, right)] += 1

    block_note = aliased(Note)
    for left, right in db.execute(
        select(block_note.notebook_id, target_note.notebook_id)
        .select_from(BlockLink)
        .join(Block, Block.id == BlockLink.block_id)
        .join(block_note, block_note.id == Block.note_id)
        .join(target_note, target_note.id == BlockLink.note_id)
        .where(block_note.notebook_id.in_(scope))
    ).all():
        if left != right:
            pairs[_pair(left, right)] += 1

    titles = dict(
        db.execute(select(Notebook.id, Notebook.title).where(Notebook.id.in_(scope))).all()
    )
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


def affinity_counts_by_notebook(db: Session, user_id: int) -> dict[int, int]:
    """How many other notebooks each notebook reaches through its notes."""
    return {
        notebook_id: len(entries)
        for notebook_id, entries in notebook_affinity(db, user_id).items()
    }


def relation_edges(db: Session, user_id: int) -> list[RelationEdge]:
    """Every link between this user's notes, declared or cited, for the graph."""
    edges: list[RelationEdge] = []
    relations = db.scalars(
        select(NoteRelation)
        .options(
            selectinload(NoteRelation.source).selectinload(Note.notebook),
            selectinload(NoteRelation.target).selectinload(Note.notebook),
        )
        .where(
            NoteRelation.source_id.in_(acl.readable_note_ids(user_id)),
            NoteRelation.target_id.in_(acl.readable_note_ids(user_id)),
        )
        .order_by(NoteRelation.id)
    ).all()
    for relation in relations:
        edges.append(_edge("relation", relation.id, relation.source, relation.target, relation.label))

    links = db.scalars(
        select(BlockLink)
        .options(
            selectinload(BlockLink.block).selectinload(Block.note).selectinload(Note.notebook),
            selectinload(BlockLink.note).selectinload(Note.notebook),
        )
        .where(BlockLink.block_id.in_(acl.readable_block_ids(user_id)))
        .order_by(BlockLink.id)
    ).all()
    for link in links:
        source = link.block.note
        if source.id != link.note_id:
            edges.append(_edge("mention", link.id, source, link.note, ""))
    return edges


def _edge(
    kind: Literal["relation", "mention"], edge_id: int, source: Note, target: Note, label: str
) -> RelationEdge:
    return RelationEdge(
        key=f"{kind}:{edge_id}",
        kind=kind,
        id=edge_id,
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


def search(db: Session, user_id: int, query: str, limit: int = 8) -> list[SearchHit]:
    term = query.strip()
    if not term:
        return []
    pattern = f"%{term.lower()}%"
    hits: list[SearchHit] = []

    notebooks = db.scalars(
        select(Notebook)
        .where(
            Notebook.id.in_(acl.readable_notebook_ids(user_id)),
            func.lower(Notebook.title).like(pattern)
            | func.lower(Notebook.description).like(pattern),
        )
        .order_by(Notebook.title)
        .limit(limit)
    ).all()
    for notebook in notebooks:
        hits.append(
            SearchHit(
                kind="notebook",
                id=notebook.id,
                notebook_id=notebook.id,
                title=notebook.title,
                snippet=notebook.description[:120],
            )
        )

    tags = db.scalars(
        select(Tag)
        .where(Tag.owner_id == user_id, func.lower(Tag.name).like(pattern))
        .order_by(Tag.name)
        .limit(limit)
    ).all()
    for tag in tags:
        hits.append(
            SearchHit(kind="tag", id=tag.id, title=tag.name, snippet=f"{len(tag.notes)} notas")
        )

    notes = db.scalars(
        select(Note)
        .where(
            Note.notebook_id.in_(acl.readable_notebook_ids(user_id)),
            func.lower(Note.title).like(pattern),
        )
        .order_by(Note.updated_at.desc())
        .limit(limit)
    ).all()
    for note in notes:
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

    blocks = db.scalars(
        select(Block)
        .where(
            Block.note_id.in_(acl.readable_note_ids(user_id)),
            or_(
                func.lower(Block.text).like(pattern),
                func.lower(Block.url).like(pattern),
                func.lower(Block.caption).like(pattern),
            ),
        )
        .order_by(Block.updated_at.desc())
        .limit(limit)
    ).all()
    for block in blocks:
        body = block.text or block.caption or block.url
        hits.append(
            SearchHit(
                kind="block",
                id=block.id,
                notebook_id=block.note.notebook_id,
                note_id=block.note_id,
                title=f"{block.type} · {block.note.title or 'Nota sem título'}",
                snippet=" ".join(body.split())[:140],
            )
        )
    return hits
