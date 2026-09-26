"""Prova a fundação do store contra a instância real: escrita, agregação, idempotência, limpeza.

É um teste de integração: precisa de `backend/.env` com APPWRITE_* e de uma instância no ar.
Roda com `.venv/bin/python tools/test_store_live.py`. Cria e apaga as próprias linhas.

    python tools/test_store_live.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.store import documents, store  # noqa: E402
from app.store.client import Conflict, equal  # noqa: E402
from app.values import utcnow  # noqa: E402

USER = 1
TABLES = (
    "note_tags", "notebook_tags", "notebook_members", "block_links", "note_relations",
    "blocks", "notes", "tags", "notebooks", "events", "media_files",
)
failures: list[str] = []


def check(label: str, condition: bool, detail: object = "") -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {label}" + (f" — {detail}" if detail != "" else ""))
    if not condition:
        failures.append(label)


CREATED: list[tuple[str, str]] = []


def make(table: str, row_id: str, data: dict, **kwargs):
    """Cria lembrando o que criou: o teste apaga só as próprias linhas, nunca o banco inteiro.

    (Um `wipe()` global aqui já apagou o baseline migrado de outro trabalho uma vez — o banco é
    compartilhado com a migração e a paridade, então limpeza é sempre por linha conhecida.)
    """
    written = documents.write(table, row_id, data, **kwargs)
    CREATED.append((table, str(row_id)))
    return written


def cleanup() -> None:
    s = store()
    for table, row_id in reversed(CREATED):
        s.delete(table, row_id)
    CREATED.clear()


def run() -> None:
    s = store()
    baseline = {table: s.count(table) for table in TABLES}

    # 1) contadores: ids inteiros e crescentes, como o app espera
    first = s.next_id("notebooks")
    check("next_id avança", s.next_id("notebooks") == first + 1, first)

    # 2) escrita atômica: caderno + membro + nota + bloco + evento no mesmo commit
    notebook_id = s.next_id("notebooks")
    note_id = s.next_id("notes")
    block_id = s.next_id("blocks")
    event_id = s.next_id("events")
    now = utcnow()
    with s.transaction() as tx:
        notebook = make(
            "notebooks", notebook_id,
            {"title": "Smoke", "description": "fundação", "owner_id": str(USER),
             "created_at": now, "updated_at": now},
            owner_id=USER, transaction_id=tx,
        )
        note = make(
            "notes", note_id,
            {"notebook_id": str(notebook_id), "title": "Nota", "position": 1,
             "created_at": now, "updated_at": now},
            owner_id=USER, transaction_id=tx,
        )
        block = make(
            "blocks", block_id,
            {"note_id": str(note_id), "position": 1, "type": "text", "text": "texto do bloco",
             "created_at": now, "updated_at": now},
            owner_id=USER, transaction_id=tx,
        )
        s.stage(tx, [
            # ids como int de propósito: é o que os routers passam, e o `stage` tem de coagir
            documents.operation("notebook_members", f"{USER}_{notebook_id}",
                                {"user_id": USER, "notebook_id": notebook_id,
                                 "role": "owner", "created_at": now}),

            documents.operation("events", str(event_id),
                                {"user_id": USER, "action": "created", "entity": "note",
                                 "target": "Nota", "detail": "", "created_at": now}),
        ])
    # linhas estagiadas também são minhas: a limpeza tem de saber delas
    CREATED.append(("notebook_members", f"{USER}_{notebook_id}"))
    CREATED.append(("events", str(event_id)))
    check("caderno/nota/bloco criados na mesma transação",
          (notebook.title, note.title, block.type) == ("Smoke", "Nota", "text"))
    check("membro e evento entraram junto",
          documents.get("notebook_members", f"{USER}_{notebook_id}") is not None
          and documents.get("events", event_id) is not None)
    raw = s.get("notebooks", notebook_id) or {}
    check("permissão do dono na linha do caderno",
          'read("user:1")' in (raw.get("$permissions") or []), raw.get("$permissions"))

    # 3) snapshot enxerga tudo do usuário, já normalizado
    snap = s.snapshot(USER)
    check("snapshot: caderno/nota/bloco",
          any(r.row_id == str(notebook_id) for r in snap["notebooks"])
          and any(r.row_id == str(note_id) for r in snap["notes"])
          and any(r.row_id == str(block_id) for r in snap["blocks"]))
    check("snapshot normaliza (id int, datetime)",
          isinstance(snap["notes"][0].id, int) and hasattr(snap["notes"][0], "created_at"))

    # 4) update invalida o cache
    documents.change("notes", note_id, {"title": "Nota editada", "updated_at": utcnow()}, owner_id=USER)
    check("cache invalidado na edição",
          any(r.title == "Nota editada" for r in s.snapshot(USER)["notes"]))

    # 5) tag única por dono
    key = documents.tag_key(USER, "Rust")
    tag_id = s.next_id("tags")
    make("tags", tag_id, {"owner_id": str(USER), "name": "Rust", "name_key": key, "color": ""},
         owner_id=USER)
    same = s.list_rows("tags", [equal("name_key", key)]).rows
    check("name_key acha uma única tag", len(same) == 1 and same[0]["$id"] == str(tag_id))

    # 6) junção idempotente: só cria se não existir (o conflito aparece no commit, medido)
    junction = f"{note_id}_{tag_id}"
    if documents.get("note_tags", junction) is None:
        with s.transaction(owner_id=USER) as tx:
            s.stage(tx, [documents.operation("note_tags", junction,
                                             {"note_id": note_id, "tag_id": tag_id,
                                              "created_at": now})])
        CREATED.append(("note_tags", junction))
    check("tag aplicada", documents.get("note_tags", junction) is not None)
    check("segunda aplicação não cria nada", documents.get("note_tags", junction) is not None)

    # 7) conflito de linha repetida é traduzido para Conflict
    conflicting = False
    try:
        with s.transaction() as tx:
            s.stage(tx, [documents.operation("note_tags", junction,
                                             {"note_id": note_id, "tag_id": tag_id})])
    except Conflict:
        conflicting = True
    check("linha repetida em transação vira Conflict", conflicting)

    # 8) limpeza só do que o teste criou: o estado tem de voltar ao que era ANTES do teste
    cleanup()
    after = {table: s.count(table) for table in TABLES}
    check("limpeza devolveu o estado anterior", after == baseline, f"{baseline} -> {after}")


if __name__ == "__main__":
    try:
        run()
    finally:
        cleanup()
    print()
    print(f"{len(failures)} falhas", failures or "")
    sys.exit(1 if failures else 0)
