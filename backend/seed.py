"""Populate the database with a realistic demo workspace.

    python seed.py                      # o dono é o admin existente
    python seed.py --email ana@casa.io  # os dados de demonstração são dessa pessoa
    python seed.py --reset              # apaga antes só os dados do usuário alvo
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from app import acl, bootstrap
from app.database import Base, SessionLocal, engine
from app.models import Block, Note, NoteRelation, Notebook, Tag, User, notebook_members

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


def seed_owner(email: str | None) -> User:
    """O dono dos dados de demonstração: o e-mail pedido ou, por padrão, o admin da casa."""
    if email is None:
        return bootstrap.ensure_admin()
    with SessionLocal() as db:
        user = db.query(User).filter(func.lower(User.email) == email.strip().lower()).one_or_none()
    if user is None:
        sys.exit(f"[notai] usuário não encontrado: {email}")
    return user


def seed(reset: bool, email: str | None = None) -> None:
    Base.metadata.create_all(engine)
    user = seed_owner(email)
    with SessionLocal() as db:
        if reset:
            # Só o que é do usuário alvo: os cadernos que ele possui levam notas, blocos, menções e
            # relações junto (FK ON DELETE CASCADE) e as tags saem pelo owner_id. Caderno de outro
            # dono nunca entra na lista, mesmo que o usuário seja membro dele.
            owned = select(notebook_members.c.notebook_id).where(
                notebook_members.c.user_id == user.id,
                notebook_members.c.role == "owner",
            )
            db.query(Notebook).filter(Notebook.id.in_(owned)).delete(synchronize_session=False)
            db.query(Tag).filter(Tag.owner_id == user.id).delete(synchronize_session=False)
            db.commit()

        tags: dict[str, Tag] = {}

        def tag(name: str) -> Tag:
            """Tag é do usuário: o mesmo nome em outra conta é outra tag."""
            if name not in tags:
                tags[name] = (
                    db.query(Tag)
                    .filter(Tag.name == name, Tag.owner_id == user.id)
                    .one_or_none()
                    or Tag(name=name, owner_id=user.id)
                )
                db.add(tags[name])
                db.flush()
            return tags[name]

        created: dict[str, Notebook] = {}
        for spec in NOTEBOOKS:
            notebook = Notebook(title=spec["title"], description=spec["description"])
            db.add(notebook)
            db.flush()
            # O dono vem de notebook_members, não do caderno: sem esta linha ele nasce sem ninguém.
            acl.add_member(db, notebook.id, user.id)
            notebook.tags = [tag(name) for name in spec["tags"]]
            for note_position, note_spec in enumerate(spec["notes"]):
                note = Note(title=note_spec["title"], position=note_position)
                note.tags = [tag(name) for name in note_spec["tags"]]
                for block_position, (block_type, payload) in enumerate(note_spec["blocks"]):
                    note.blocks.append(Block(position=block_position, type=block_type, **payload))
                notebook.notes.append(note)
            created[spec["title"]] = notebook
        db.flush()

        # A relação agora é entre notas: cada vínculo de caderno virou um vínculo entre a primeira
        # nota de cada lado (a tabela de vínculo entre cadernos não existe mais).
        first_note = {title: notebook.notes[0].id for title, notebook in created.items()}
        db.add_all(
            [
                NoteRelation(
                    source_id=first_note["Oh My Posh"],
                    target_id=first_note["Ideias soltas"],
                    label="mesmo produto",
                ),
                NoteRelation(
                    source_id=first_note["Estudos de Rust"],
                    target_id=first_note["Oh My Posh"],
                    label="inspira performance",
                ),
            ]
        )
        db.commit()

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
