"""Populate the database with a realistic demo workspace.

    python seed.py                      # o dono é o admin existente
    python seed.py --email ana@casa.io  # os dados de demonstração são dessa pessoa
    python seed.py --reset              # apaga antes só os dados do usuário alvo
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable

from app import bootstrap, events, links, services
from app.store import documents, equal, store
from app.store.documents import Row

NOTEBOOKS: list[dict] = [
    {
        "title": "Oh My Posh",
        "description": "Notas de manutenção: releases, segmentos e a integração com o Claude Code.",
        "tags": ["release", "docs"],
        "notes": [
            {
                "title": "Studio, Native Git, and a Leaner Binary",
                "tags": ["release", "performance"],
                "blocks": [
                    ("text", {"text": "A few changes landed recently that make Oh My Posh faster to run and easier to configure. Here's what's new: a live theme editor with a bridge to the Configurator, a native git integration, a background daemon that keeps your prompt warm, and a binary that keeps getting smaller."}),
                    ("code", {"language": "bash", "text": "winget install JanDeDobbeleer.OhMyPosh --source winget\noh-my-posh config export --output ~/theme.omp.json"}),
                    ("url", {"url": "https://ohmyposh.dev/docs/installation/windows", "caption": "Installation guide"}),
                    ("text", {"text": "O daemon deixa o prompt quente: a primeira execução precisa carregar o tema, as seguintes só conversam com o processo em background."}),
                ],
            },
            {
                "title": "Claude Code statusline",
                "tags": ["claude-code"],
                "blocks": [
                    ("text", {"text": "Terminal customization just got a lot smarter. Oh My Posh now integrates with Claude Code through its statusline functionality, bringing real-time AI session information and development context directly into your Claude Code prompt."}),
                    ("code", {"language": "json", "text": '{\n  "statusLine": {\n    "type": "command",\n    "command": "oh-my-posh claude"\n  }\n}'}),
                    ("image", {"url": "", "caption": "Sessão do Claude Code com o segmento de contexto ativo"}),
                    ("video", {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "caption": "Demo do statusline"}),
                ],
            },
        ],
    },
    {
        "title": "Estudos de Rust",
        "description": "Anotações de leitura: ownership, async e o ecossistema de crates.",
        "tags": ["estudo", "rust"],
        "notes": [
            {
                "title": "Ownership em uma frase",
                "tags": ["estudo"],
                "blocks": [
                    ("text", {"text": "Cada valor tem exatamente um dono; quando o dono sai de escopo o valor é liberado. Empréstimos são temporários e o compilador garante que nenhum deles sobrevive ao dono."}),
                    ("code", {"language": "rust", "text": "fn main() {\n    let s = String::from(\"caderno\");\n    let len = s.len(); // borrow\n    println!(\"{s} tem {len} bytes\");\n}"}),
                    ("url", {"url": "https://doc.rust-lang.org/book/ch04-00-understanding-ownership.html", "caption": "The Rust Book, capítulo 4"}),
                ],
            },
            {
                "title": "Tokio em 5 linhas",
                "tags": ["estudo", "rust"],
                "blocks": [
                    ("code", {"language": "rust", "text": "#[tokio::main]\nasync fn main() {\n    let body = reqwest::get(\"https://ohmyposh.dev\").await.unwrap().text().await.unwrap();\n    println!(\"{}\", body.len());\n}"}),
                    ("text", {"text": "O runtime tem dois sabores: multi-thread para servidores, current-thread para testes determinísticos."}),
                ],
            },
        ],
    },
    {
        "title": "Ideias soltas",
        "description": "Backlog de produto e atalhos que quero testar no editor.",
        "tags": ["ideias"],
        "notes": [
            {
                "title": "Atalhos do editor",
                "tags": ["ideias"],
                "blocks": [
                    ("text", {"text": "Alt+Espaço troca o tipo do bloco: texto, código, url, imagem, vídeo. Ctrl+Espaço cria ou insere uma tag. Ctrl+K busca em tudo."}),
                    ("text", {"text": ""}),
                ],
            }
        ],
    },
]


def seed_owner(email: str | None) -> Row:
    """O dono dos dados de demonstração: o e-mail pedido ou, por padrão, o admin da casa."""
    if email is None:
        return bootstrap.ensure_admin()
    user = documents.user_by_email(email)
    if user is None:
        sys.exit(f"[notai] usuário não encontrado: {email}")
    return user


def _drop(table: str, column: str, values: Iterable[int]) -> None:
    """Apaga as linhas de `table` cujo `column` está em `values`.

    `equal` com vários valores é um OR e o servidor aceita `services.QUERY_VALUES` por chamada: os
    ids vão em lotes desse tamanho. Sem FK nem cascata, a ordem das chamadas é a das dependências.
    """
    chunk = [str(value) for value in sorted(set(values))]
    for start in range(0, len(chunk), services.QUERY_VALUES):
        store().delete_where(table, [equal(column, *chunk[start : start + services.QUERY_VALUES])])


def reset_user(user: Row) -> None:
    """Apaga só os dados do usuário alvo, das folhas para a raiz.

    O que entra na conta é o caderno que ele **possui** (a linha de membro com papel `owner`); o
    caderno de outro dono em que ele seja convidado nunca entra, mesmo que ele seja membro dele.
    """
    photo = store().snapshot(user.id, fresh=True)
    owned = {
        member.notebook_id
        for member in photo["notebook_members"]
        if member.user_id == user.id and member.role == "owner"
    }
    notes = {note.id for note in photo["notes"] if note.notebook_id in owned}
    blocks = {block.id for block in photo["blocks"] if block.note_id in notes}

    # a cascata que o banco fazia, agora explícita: menções, tags e vínculos saem antes das linhas
    # que os sustentam, e o evento de auditoria é o último da conta
    _drop("block_links", "block_id", blocks)
    _drop("block_links", "note_id", notes)
    _drop("note_tags", "note_id", notes)
    _drop("note_relations", "source_id", notes)
    _drop("note_relations", "target_id", notes)
    _drop("blocks", "$id", blocks)
    _drop("notes", "$id", notes)
    _drop("notebook_tags", "notebook_id", owned)
    _drop("notebook_members", "notebook_id", owned)
    _drop("notebooks", "$id", owned)
    _drop("tags", "owner_id", [user.id])
    _drop("events", "user_id", [user.id])
    store().invalidate(user.id)  # a foto lida aqui ainda é a de antes deste reset


def seed(reset: bool, email: str | None = None) -> None:
    user = seed_owner(email)
    if reset:
        reset_user(user)

    tags: dict[str, Row] = {}

    def tag(name: str) -> Row:
        """Tag é do usuário: o mesmo nome em outra conta é outra tag (o `name_key` as separa).

        O nome único por dono é o índice unique de `name_key`, e ele só aparece no commit: a
        consulta vem antes para reaproveitar a tag existente em vez de bater no 409 lá na frente.
        """
        key = documents.tag_key(user.id, name)
        found = tags.get(key)
        if found is None:
            existing = documents.many(
                "tags", store().list_rows("tags", [equal("name_key", key)]).rows
            )
            if existing:
                found = existing[0]
            else:
                with store().transaction() as tx:
                    found = documents.write(
                        "tags",
                        documents.record_id("tags"),
                        {
                            "owner_id": str(user.id),
                            "name": name,
                            "name_key": key,
                            "color": "",
                            "created_at": documents.now(),
                        },
                        owner_id=user.id,
                        transaction_id=tx,
                    )
                    store().stage(tx, [events.operation(user.id, "created", "tag", name)])
            tags[key] = found
        return found

    first_note: dict[str, int] = {}
    titles: dict[int, str] = {}
    blocks: list[Row] = []
    for spec in NOTEBOOKS:
        # A tag é linha própria do dono e entra por `write`; resolvida antes, a transação do caderno
        # fica só com a entidade principal e as junções dela.
        notebook_tags = [tag(name) for name in spec["tags"]]
        with store().transaction() as tx:
            now = documents.now()
            notebook = documents.write(
                "notebooks",
                documents.record_id("notebooks"),
                {
                    "title": spec["title"],
                    "description": spec["description"],
                    "owner_id": str(user.id),
                    "created_at": now,
                    "updated_at": now,
                },
                owner_id=user.id,
                transaction_id=tx,
            )
            store().stage(
                tx,
                [
                    # O dono vem de notebook_members, não do caderno: sem esta linha ele nasce sem
                    # ninguém. Os ids compostos são o rowId de cada junção, e toda coluna de id é
                    # `string` no Appwrite — o int do contador vira texto aqui.
                    documents.operation(
                        "notebook_members",
                        f"{user.id}_{notebook.id}",
                        {
                            "user_id": str(user.id),
                            "notebook_id": str(notebook.id),
                            "role": "owner",
                            "created_at": now,
                        },
                    ),
                    *[
                        documents.operation(
                            "notebook_tags",
                            f"{notebook.id}_{row.id}",
                            {
                                "notebook_id": str(notebook.id),
                                "tag_id": str(row.id),
                                "created_at": now,
                            },
                        )
                        for row in notebook_tags
                    ],
                    events.operation(user.id, "created", "notebook", spec["title"]),
                ],
            )
        for note_position, note_spec in enumerate(spec["notes"]):
            note_tags = [tag(name) for name in note_spec["tags"]]
            with store().transaction() as tx:
                now = documents.now()
                note = documents.write(
                    "notes",
                    documents.record_id("notes"),
                    {
                        "notebook_id": str(notebook.id),
                        "title": note_spec["title"],
                        "position": note_position,
                        "created_at": now,
                        "updated_at": now,
                    },
                    owner_id=user.id,
                    transaction_id=tx,
                )
                for block_position, (block_type, payload) in enumerate(note_spec["blocks"]):
                    blocks.append(
                        documents.write(
                            "blocks",
                            documents.record_id("blocks"),
                            {
                                "note_id": str(note.id),
                                "position": block_position,
                                "type": block_type,
                                **payload,
                                "created_at": now,
                                "updated_at": now,
                            },
                            owner_id=user.id,
                            transaction_id=tx,
                        )
                    )
                store().stage(
                    tx,
                    [
                        *[
                            documents.operation(
                                "note_tags",
                                f"{note.id}_{row.id}",
                                {
                                    "note_id": str(note.id),
                                    "tag_id": str(row.id),
                                    "created_at": now,
                                },
                            )
                            for row in note_tags
                        ],
                        # A nota, os blocos dela e a auditoria são um commit só.
                        events.operation(user.id, "created", "note", note_spec["title"]),
                    ],
                )
            titles[note.id] = note_spec["title"]
            first_note.setdefault(spec["title"], note.id)

    # A relação agora é entre notas: cada vínculo de caderno virou um vínculo entre a primeira
    # nota de cada lado (a tabela de vínculo entre cadernos não existe mais).
    declared = [
        (first_note["Oh My Posh"], first_note["Ideias soltas"], "mesmo produto"),
        (first_note["Estudos de Rust"], first_note["Oh My Posh"], "inspira performance"),
    ]
    with store().transaction() as tx:
        store().stage(
            tx,
            [
                *[
                    documents.operation(
                        "note_relations",
                        f"{source_id}_{target_id}",
                        {
                            "source_id": str(source_id),
                            "target_id": str(target_id),
                            "label": label,
                            "created_at": documents.now(),
                        },
                    )
                    for source_id, target_id, label in declared
                ],
                *[
                    events.operation(
                        user.id,
                        "linked",
                        "relation",
                        f"{titles[source_id]} → {titles[target_id]}",
                    )
                    for source_id, target_id, _ in declared
                ],
            ],
        )

    # Menção `[[Título]]` só se resolve quando o texto já existe — inclusive o das notas criadas
    # nesta mesma rodada. Bloco novo não tem vínculo antigo para derrubar, então só vale reindexar
    # o que traz `[[…]]` no texto.
    citing = [block for block in blocks if links.parse_mentions(block.text)]
    if citing:
        with store().transaction() as tx:
            for block in citing:
                links.reindex_block(store(), block, user.id, tx)

    print(f"seed ok: {len(NOTEBOOKS)} cadernos para {user.email}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="seed.py", description="Dados de demonstração do NotAI")
    parser.add_argument("--reset", action="store_true", help="apaga antes os dados do usuário alvo")
    parser.add_argument("--email", default=None, help="dono dos dados (padrão: o admin existente)")
    args = parser.parse_args(argv)
    seed(reset=args.reset, email=args.email)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
