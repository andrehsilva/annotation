"""Query helpers shared by the routers: counters, summaries and full-text-ish search.

O Appwrite não tem `JOIN` nem `GROUP BY`: cada função aqui lê a **foto** do usuário
(`store().snapshot`) e conta/ordena em Python. Consulta pontual só onde a assinatura não traz o
dono (`block_counts_for_notes` e os quatro `note_*`, que recebem a nota), e sempre por `equal` com
no máximo 100 valores por chamada — o teto medido nesta instância.

Não há caderno: a **nota** é a unidade, e é ela que tem dono, papel e compartilhamento.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Iterable, Literal

from . import acl
from .values import UNTITLED
from .schemas import (
    Backlink,
    NoteOut,
    NoteRelated,
    NoteRelationOut,
    NoteSummary,
    RelatableNote,
    RelationEdge,
    SearchHit,
    BlockOut,
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
    """As tags de cada linha da junção (`note_tags`), na ordem do ORM.

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
    """O outro lado de um vínculo: a nota, como o `selectinload` dava."""
    notes = _by_ids(db, "notes", "$id", note_ids)
    return {note.id: note_ref(note) for note in notes}


# ------------------------------------------------------------------ contagens


def _block_counts(
    blocks: Iterable[documents.Row], bucket_of: dict[int, int]
) -> dict[int, dict[str, int]]:
    """O `GROUP BY` em Python: `bucket_of` diz em que balde (a nota) cada bloco cai."""
    counts: dict[int, dict[str, int]] = defaultdict(empty_counts)
    for block in blocks:
        bucket_id = bucket_of.get(block.note_id)
        if bucket_id is None:
            continue
        bucket = counts[bucket_id]
        bucket[block.type] = bucket.get(block.type, 0) + 1
    return counts


def block_counts_by_note(db: Store, user_id: int) -> dict[int, dict[str, int]]:
    photo = snapshot(db, user_id)
    return _block_counts(photo["blocks"], {note.id: note.id for note in photo["notes"]})


def block_counts_for_notes(db: Store, note_ids: list[int]) -> dict[int, dict[str, int]]:
    """`note_ids` always comes from an already-scoped query, so it needs no owner of its own."""
    blocks = _by_ids(db, "blocks", "note_id", note_ids)
    return _block_counts(blocks, {note_id: note_id for note_id in note_ids})


# ------------------------------------------------------------------ resumos


def block_authors(
    db: Store, viewer_id: int, blocks: Iterable[tuple[documents.Row, int]]
) -> dict[int, str]:
    """{id do bloco: nome de quem escreveu}, só para os blocos de outra conta.

    Cada item é `(bloco, dono da nota)`: o dono é a resposta para as linhas de antes de `created_by`,
    quando quem escrevia era ele. Numa nota só minha — o caso comum — nada é consultado.
    """
    pairs = [(block, block.created_by or owner_id) for block, owner_id in blocks]
    others = sorted({author for _block, author in pairs if author and author != viewer_id})
    if not others:
        return {}
    names = {
        documents.to_int(row["$id"]): (row.get("display_name") or row.get("email") or "")
        for row in db.page_in("users", "$id", [str(author) for author in others])
    }
    return {block.id: names[author] for block, author in pairs if names.get(author)}


def note_owner(photo: dict, note_id: int) -> int:
    """O dono da nota na foto: resposta para os blocos antigos, sem `created_by`."""
    for row in photo["notes"]:
        if row.id == note_id:
            return row.owner_id
    return 0


def _owner_names(db: Store, photo: dict) -> dict[int, str]:
    """Nome do dono de cada nota da foto, numa consulta só."""
    ids = sorted({str(row.owner_id) for row in photo["notes"]})
    if not ids:
        return {}
    return {
        documents.to_int(row["$id"]): (row.get("display_name") or row.get("email") or "")
        for row in db.page_in("users", "$id", ids)
    }


def _relations_touching(photo: dict) -> dict[int, int]:
    """Quantos vínculos (declarados ou citações) tocam cada nota da foto."""
    counted: dict[int, int] = defaultdict(int)
    for relation in photo["note_relations"]:
        counted[relation.source_id] += 1
        counted[relation.target_id] += 1
    blocks = {block.id: block.note_id for block in photo["blocks"]}
    for link in photo["block_links"]:
        counted[link.note_id] += 1  # a nota citada
        source = blocks.get(link.block_id)
        if source is not None:
            counted[source] += 1  # a nota que cita
    return counted


def note_summary(
    note: documents.Row,
    counts: dict[str, int] | None,
    relations_count: int = 0,
    role: str = "owner",
    owner_name: str = "",
    shared_groups: Iterable[str] = (),
    shared_people: int = 0,
) -> NoteSummary:
    """`counts` vem de fora: o resumo lê o que já está pendurado na linha, sem lazy load.

    `role`/`owner_name`/`shared_*` descrevem o compartilhamento desta nota com quem pediu — o dono
    vê com quem ela saiu, quem recebeu vê de quem ela veio.
    """
    return NoteSummary(
        id=note.id,
        title=note.title,
        position=note.position,
        created_at=note.created_at,
        updated_at=note.updated_at,
        tags=list(note.get("tags", ())),
        counts={**empty_counts(), **(counts or {})},
        excerpt=note_excerpt(note),
        relations_count=relations_count,
        role=role,
        owner_id=note.owner_id,
        owner_name=owner_name,
        shared=role != "owner",
        shared_groups=list(shared_groups),
        shared_people=shared_people,
    )


def list_note_summaries(db: Store, user_id: int) -> list[NoteSummary]:
    """As notas que a conta alcança — as dela e as compartilhadas com ela —, mais recentes primeiro."""
    photo = snapshot(db, user_id)
    counts = block_counts_by_note(db, user_id)
    contacts = _relations_touching(photo)
    owners = _owner_names(db, photo)
    notes = sorted(photo["notes"], key=_recent, reverse=True)
    # O papel custa uma varredura da foto por nota e responde duas perguntas: qual é o papel aqui e
    # de quais notas o compartilhamento de saída pode ser lido. Uma varredura, uma consulta em lote.
    roles = {row.id: acl.role_in_photo(photo, row.id) or "viewer" for row in notes}
    audience = acl.share_audience(db, [row for row in notes if roles[row.id] == "owner"])
    out = []
    for note in notes:
        groups, people = audience.get(note.id, ((), 0))
        out.append(
            note_summary(
                note,
                counts.get(note.id, {}),
                contacts.get(note.id, 0),
                roles[note.id],
                owners.get(note.owner_id, ""),
                groups,
                people,
            )
        )
    return out


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


def note_detail(db: Store, user_id: int, note: documents.Row) -> NoteOut:
    """A nota com os blocos, como o editor a recebe (uma consulta em lote para os autores)."""
    photo = snapshot(db, user_id)
    notes = {row.id: row for row in photo["notes"]}
    own = notes.get(note.id, note)
    blocks = sorted(
        (block for block in photo["blocks"] if block.note_id == note.id), key=_block_order
    )
    owners = _owner_names(db, photo)
    authors = block_authors(db, user_id, [(block, note_owner(photo, note.id)) for block in blocks])
    role = acl.role_in_photo(photo, note.id) or "viewer"
    # Só o dono tem público para fora; para os outros a nota é de outra conta e a consulta nem sai.
    groups, people = (
        acl.share_audience(db, [own]).get(note.id, ((), 0)) if role == "owner" else ((), 0)
    )
    return NoteOut(
        **note_summary(
            own,
            _block_counts(photo["blocks"], {note.id: note.id}).get(note.id, {}),
            _relations_touching(photo).get(note.id, 0),
            role,
            owners.get(own.owner_id, ""),
            groups,
            people,
        ).model_dump(),
        blocks=[
            BlockOut(
                id=block.id,
                note_id=block.note_id,
                position=block.position,
                type=block.type,
                text=block.text,
                language=block.language,
                url=block.url,
                caption=block.caption,
                author=authors.get(block.id, ""),
                created_at=block.created_at,
                updated_at=block.updated_at,
            )
            for block in blocks
        ],
        relations=note_relations_for(db, own),
    )


def note_ref(note: documents.Row) -> RelatableNote:
    """Label for a note seen from somewhere else (não há lazy load: a linha já está em mãos)."""
    return RelatableNote(id=note.id, title=note.title)


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
    """As notas que a conta alcança, mais recentes primeiro — é a lista principal do app."""
    notes = list_note_summaries(db, user_id)
    term = query.strip().lower()
    if not term:
        return notes[:limit]
    return [note for note in notes if _holds(note.title, term)][:limit]


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
    )


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
                note_id=block.note_id,
                title=f"{block.type} · {note.title or 'Nota sem título'}",
                snippet=" ".join(body.split())[:140],
            )
        )
    return hits
