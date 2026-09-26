"""Copia o SQLite do NotAI para o Appwrite preservando os ids que já existem.

    python tools/migrate_sqlite.py --dry-run                 # só lê o SQLite e relata as contagens
    python tools/migrate_sqlite.py --apply                   # copia tudo (idempotente)
    python tools/migrate_sqlite.py --apply --only users,notes

O arquivo de origem é aberto em **modo somente-leitura** (`file:...?mode=ro`): a migração nunca
escreve no SQLite, que continua sendo a fonte da verdade até o corte. O destino é a instância
descrita em `backend/.env` (as mesmas variáveis que `app.store` lê).

## tabela → rowId

O `$id` do Appwrite é a chave primária (não há autoincremento), então cada id legado entra
**verbatim como string** e as chaves compostas das junções viram o próprio rowId — o "único por
par" do SQLite sai de graça:

| tabela | rowId | permissão da linha | observação |
|---|---|---|---|
| `users` | `id` | nenhuma (servidor) | carrega o hash da senha |
| `sessions` | — | — | **não migra**: o sha256 tem 64 chars e o rowId aceita 36; sessão é estado efêmero — quem tinha sessão entra de novo |
| `notebooks` | `id` | dono | `owner_id` vem do membro com papel `owner` |
| `notebook_members` | `<user_id>_<notebook_id>` | do membro | |
| `notes` | `id` | dono do caderno | |
| `blocks` | `id` | dono do caderno | |
| `tags` | `id` | dono | `name_key = "<owner_id>::<nome minúsculo>"` reproduz o único por dono |
| `notebook_tags` | `<notebook_id>_<tag_id>` | nenhuma | junção |
| `note_tags` | `<note_id>_<tag_id>` | nenhuma | junção |
| `note_relations` | `id` | nenhuma | o par é único no índice `uq_relations_pair` (source_id, target_id) |
| `block_links` | `id` | nenhuma | o par é único no índice `uq_block_links` (block_id, note_id) |
| `media_files` | `filename` | dono | o `id` numérico é descartado; os bytes vão para o bucket |
| `events` | `id` | nenhuma | auditoria |
| `drive_files` | `note_id` | nenhuma (servidor) | o `id` numérico é descartado |
| `drive_state` | `<user_id>_<chave>` | nenhuma (servidor) | |
| `counters` | nome da família | nenhuma (servidor) | ajustado ao maior id de cada família |

Junções e eventos entram **sem permissão** porque é assim que o app os cria (`store().stage`, que
não grava permissões); quem lê é a API key. `users`, `drive_files`, `drive_state` e `counters`
também: são linhas de servidor.

Numa reexecução o `409` do par repetido (`uq_relations_pair`, `uq_block_links`) e o do `$id` já
existente se confundem: por isso o script confere se a linha existe antes de chamar o 409 de
sucesso — par repetido de verdade vira problema no relatório.

## Ordem e idempotência

A ordem é a das dependências (`users` → `notebooks` → `notebook_members` → `notes` → `blocks` →
`tags` → junções → `note_relations` → `block_links` → `media_files` → `events` → `drive_files` →
`drive_state` → `counters` → bucket) e `--only` só recorta essa lista, nunca a reordena.

Rodar duas vezes não duplica: o `409` do `$id` (ou do índice único de `tags.name_key`) é contado
como "já existia". Quando o 409 acontece **sem** a linha existir, é colisão de índice único (duas
tags com o mesmo `name_key`, por exemplo) e o script conta isso como problema, não como sucesso.

O esquema do SQLite está transcrito abaixo em SQL puro só para conferir o arquivo de origem e
documentar o mapeamento — a migração não importa `app/models.py`, que vai ser removido.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

TOOLS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TOOLS_DIR.parent
# `python backend/tools/migrate_sqlite.py` (fora de backend/) também precisa achar o pacote `app`.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import config  # noqa: E402  — carrega backend/.env e define DATA_DIR

# Esquema do SQLite como estava (transcrito do `sqlite_master`), só como contrato de leitura.
SCHEMA = """
CREATE TABLE users (
    id INTEGER NOT NULL,
    email VARCHAR(160) NOT NULL,
    display_name VARCHAR(80) NOT NULL,
    password_hash VARCHAR(200) NOT NULL,
    role VARCHAR(16) NOT NULL,
    is_active BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    last_login_at DATETIME,
    activity_seen_at DATETIME,
    PRIMARY KEY (id)
);
CREATE TABLE sessions (
    token_hash VARCHAR(64) NOT NULL,
    user_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    last_seen_at DATETIME NOT NULL,
    PRIMARY KEY (token_hash),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE TABLE notebooks (
    id INTEGER NOT NULL,
    title VARCHAR(160) NOT NULL,
    description TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);
CREATE TABLE notebook_members (
    notebook_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role VARCHAR(16) NOT NULL,
    created_at DATETIME,
    PRIMARY KEY (notebook_id, user_id),
    FOREIGN KEY(notebook_id) REFERENCES notebooks (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE TABLE notes (
    id INTEGER NOT NULL,
    notebook_id INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    position INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(notebook_id) REFERENCES notebooks (id) ON DELETE CASCADE
);
CREATE TABLE blocks (
    id INTEGER NOT NULL,
    note_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    type VARCHAR(16) NOT NULL,
    text TEXT NOT NULL,
    language VARCHAR(40) NOT NULL,
    url TEXT NOT NULL,
    caption TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(note_id) REFERENCES notes (id) ON DELETE CASCADE
);
CREATE TABLE tags (
    id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    name VARCHAR(60) NOT NULL,
    color VARCHAR(16) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_tag_owner_name UNIQUE (owner_id, name),
    FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE TABLE notebook_tags (
    notebook_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (notebook_id, tag_id),
    FOREIGN KEY(notebook_id) REFERENCES notebooks (id) ON DELETE CASCADE,
    FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
);
CREATE TABLE note_tags (
    note_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (note_id, tag_id),
    FOREIGN KEY(note_id) REFERENCES notes (id) ON DELETE CASCADE,
    FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
);
CREATE TABLE note_relations (
    id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    label VARCHAR(80) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_note_relation_pair UNIQUE (source_id, target_id),
    FOREIGN KEY(source_id) REFERENCES notes (id) ON DELETE CASCADE,
    FOREIGN KEY(target_id) REFERENCES notes (id) ON DELETE CASCADE
);
CREATE TABLE block_links (
    id INTEGER NOT NULL,
    block_id INTEGER NOT NULL,
    note_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_block_link UNIQUE (block_id, note_id),
    FOREIGN KEY(block_id) REFERENCES blocks (id) ON DELETE CASCADE,
    FOREIGN KEY(note_id) REFERENCES notes (id) ON DELETE CASCADE
);
CREATE TABLE media_files (
    id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    filename VARCHAR(120) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    content_type VARCHAR(80) NOT NULL,
    size INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE (filename)
);
CREATE TABLE events (
    id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    action VARCHAR(16) NOT NULL,
    entity VARCHAR(16) NOT NULL,
    target VARCHAR(200) NOT NULL,
    detail VARCHAR(80) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE TABLE drive_files (
    id INTEGER NOT NULL,
    note_id INTEGER NOT NULL,
    file_id VARCHAR(64) NOT NULL,
    folder_id VARCHAR(64) NOT NULL,
    drive_path VARCHAR(400) NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    synced_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(note_id) REFERENCES notes (id) ON DELETE CASCADE
);
CREATE TABLE drive_state (
    user_id INTEGER NOT NULL,
    "key" VARCHAR(40) NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, "key"),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
"""

# `counters` no Appwrite tem o nome da família como rowId e é o que `documents.record_id` lê.
COUNTER_FAMILIES = (
    "notebooks",
    "notes",
    "blocks",
    "tags",
    "users",
    "events",
    "note_relations",
    "block_links",
)

# Tabelas do SQLite que **de propósito** não migram: o relatório e o `--only` dizem por quê.
SKIP_REASON = {
    "sessions": (
        "estado efêmero e o sha256 (64 chars) não cabe no rowId de 36; "
        "quem tinha sessão entra de novo"
    ),
}


# ------------------------------------------------------------------ conversão


def moment(value: Any) -> datetime | None:
    """SQLite grava `YYYY-MM-DD HH:MM:SS.ffffff`; o store quer `datetime` (UTC ingênuo)."""
    if value is None or value == "":
        return None
    text = str(value).strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def whole(value: Any) -> int | None:
    return None if value is None else int(value)


def flag(value: Any) -> bool:
    return bool(value)


def name_key(owner_id: Any, name: Any) -> str:
    """A chave do índice unique global de `tags`: o que era "único por dono" no SQLite."""
    return f"{owner_id}::{str(name or '').strip().lower()}"


# ------------------------------------------------------------------ origem


class Source:
    """O SQLite, somente-leitura, com os mapas derivados que o esquema antigo não guardava."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        self._owners = self._load_owners()
        self._note_notebook = {
            int(row["id"]): int(row["notebook_id"])
            for row in self.rows("SELECT id, notebook_id FROM notes")
        }

    def close(self) -> None:
        self.connection.close()

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return list(self.connection.execute(sql, params))

    def scalar(self, sql: str) -> Any:
        row = self.connection.execute(sql).fetchone()
        return None if row is None else row[0]

    def table_names(self) -> set[str]:
        return {
            str(row["name"])
            for row in self.rows("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not str(row["name"]).startswith("sqlite_")
        }

    def columns(self, table: str) -> list[str]:
        return [str(row["name"]) for row in self.rows(f'PRAGMA table_info("{table}")')]

    def _load_owners(self) -> dict[int, int]:
        """`notebooks` nunca teve `owner_id`: o dono é o membro com papel `owner`.

        Sem membro `owner` (dado antigo), vale o menor `user_id` de qualquer papel; sem membro
        nenhum, o caderno não tem dono possível e a linha é relatada como pulada.
        """
        members: dict[int, list[tuple[str, int]]] = {}
        for row in self.rows("SELECT notebook_id, user_id, role FROM notebook_members"):
            members.setdefault(int(row["notebook_id"]), []).append((str(row["role"]), int(row["user_id"])))
        owners: dict[int, int] = {}
        for notebook_id, people in members.items():
            people.sort(key=lambda item: (item[0] != "owner", item[1]))
            owners[notebook_id] = people[0][1]
        return owners

    def owner_of_notebook(self, notebook_id: int | None) -> int | None:
        return None if notebook_id is None else self._owners.get(int(notebook_id))

    def owner_of_note(self, note_id: int | None) -> int | None:
        if note_id is None:
            return None
        notebook_id = self._note_notebook.get(int(note_id))
        return self.owner_of_notebook(notebook_id)


@dataclass(frozen=True)
class Record:
    """Uma linha pronta para o `documents.write`."""

    table: str
    row_id: str
    data: dict[str, Any]
    owner_id: int | None = None
    problem: str = ""


Reader = Callable[[Source], Iterator[Record]]


# ------------------------------------------------------------------ leitores


def read_users(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM users ORDER BY id"):
        yield Record(
            "users",
            str(row["id"]),
            {
                "email": row["email"],
                "display_name": row["display_name"],
                "password_hash": row["password_hash"],
                "role": row["role"],
                "is_active": flag(row["is_active"]),
                "created_at": moment(row["created_at"]),
                "last_login_at": moment(row["last_login_at"]),
                "activity_seen_at": moment(row["activity_seen_at"]),
            },
        )


def read_notebooks(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM notebooks ORDER BY id"):
        owner = source.owner_of_notebook(row["id"])
        yield Record(
            "notebooks",
            str(row["id"]),
            {
                "title": row["title"],
                "description": row["description"],
                "owner_id": None if owner is None else str(owner),
                "created_at": moment(row["created_at"]),
                "updated_at": moment(row["updated_at"]),
            },
            owner_id=owner,
            problem="" if owner is not None else "caderno sem membro: não há dono para a linha",
        )


def read_members(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM notebook_members ORDER BY notebook_id, user_id"):
        user_id, notebook_id = int(row["user_id"]), int(row["notebook_id"])
        yield Record(
            "notebook_members",
            f"{user_id}_{notebook_id}",
            {
                "user_id": str(user_id),
                "notebook_id": str(notebook_id),
                "role": row["role"],
                "created_at": moment(row["created_at"]),
            },
            owner_id=user_id,
        )


def read_notes(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM notes ORDER BY id"):
        owner = source.owner_of_notebook(row["notebook_id"])
        yield Record(
            "notes",
            str(row["id"]),
            {
                "notebook_id": str(row["notebook_id"]),
                "title": row["title"],
                "position": whole(row["position"]),
                "created_at": moment(row["created_at"]),
                "updated_at": moment(row["updated_at"]),
            },
            owner_id=owner,
            problem="" if owner is not None else "nota de caderno sem dono",
        )


def read_blocks(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM blocks ORDER BY id"):
        owner = source.owner_of_note(row["note_id"])
        yield Record(
            "blocks",
            str(row["id"]),
            {
                "note_id": str(row["note_id"]),
                "position": whole(row["position"]),
                "type": row["type"],
                "text": row["text"],
                "language": row["language"],
                "url": row["url"],
                "caption": row["caption"],
                "created_at": moment(row["created_at"]),
                "updated_at": moment(row["updated_at"]),
            },
            owner_id=owner,
            problem="" if owner is not None else "bloco de nota sem dono",
        )


def read_tags(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM tags ORDER BY id"):
        owner = int(row["owner_id"])
        yield Record(
            "tags",
            str(row["id"]),
            {
                "owner_id": str(owner),
                "name": row["name"],
                "name_key": name_key(owner, row["name"]),
                "color": row["color"],
                "created_at": moment(row["created_at"]),
            },
            owner_id=owner,
        )


def read_notebook_tags(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM notebook_tags ORDER BY notebook_id, tag_id"):
        notebook_id, tag_id = str(row["notebook_id"]), str(row["tag_id"])
        yield Record(
            "notebook_tags", f"{notebook_id}_{tag_id}",
            {"notebook_id": notebook_id, "tag_id": tag_id},
        )


def read_note_tags(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM note_tags ORDER BY note_id, tag_id"):
        note_id, tag_id = str(row["note_id"]), str(row["tag_id"])
        yield Record("note_tags", f"{note_id}_{tag_id}", {"note_id": note_id, "tag_id": tag_id})


def read_relations(source: Source) -> Iterator[Record]:
    """rowId = id do SQLite; o par (source_id, target_id) é único no índice `uq_relations_pair`."""
    for row in source.rows("SELECT * FROM note_relations ORDER BY id"):
        yield Record(
            "note_relations",
            str(row["id"]),
            {
                "source_id": str(row["source_id"]),
                "target_id": str(row["target_id"]),
                "label": row["label"],
                "created_at": moment(row["created_at"]),
            },
        )


def read_block_links(source: Source) -> Iterator[Record]:
    """rowId = id do SQLite; o par (block_id, note_id) é único no índice `uq_block_links`."""
    for row in source.rows("SELECT * FROM block_links ORDER BY id"):
        yield Record(
            "block_links",
            str(row["id"]),
            {
                "block_id": str(row["block_id"]),
                "note_id": str(row["note_id"]),
                "created_at": moment(row["created_at"]),
            },
        )


def read_media(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM media_files ORDER BY id"):
        owner = int(row["owner_id"])
        yield Record(
            "media_files",
            str(row["filename"]),
            {
                "owner_id": str(owner),
                "original_name": row["original_name"],
                "content_type": row["content_type"],
                "size": whole(row["size"]),
                "created_at": moment(row["created_at"]),
            },
            owner_id=owner,
        )


def read_events(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM events ORDER BY id"):
        yield Record(
            "events",
            str(row["id"]),
            {
                "user_id": str(row["user_id"]),
                "action": row["action"],
                "entity": row["entity"],
                "target": row["target"],
                "detail": row["detail"],
                "created_at": moment(row["created_at"]),
            },
        )


def read_drive_files(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM drive_files ORDER BY id"):
        yield Record(
            "drive_files",
            str(row["note_id"]),
            {
                "file_id": row["file_id"],
                "folder_id": row["folder_id"],
                "drive_path": row["drive_path"],
                "checksum": row["checksum"],
                "synced_at": moment(row["synced_at"]),
            },
        )


def read_drive_state(source: Source) -> Iterator[Record]:
    for row in source.rows("SELECT * FROM drive_state ORDER BY user_id, key"):
        user_id, key = int(row["user_id"]), str(row["key"])
        yield Record(
            "drive_state",
            f"{user_id}_{key}",
            {"user_id": str(user_id), "key": key, "value": row["value"] or ""},
        )


# A ordem é a das dependências: caderno antes de membro/nota, nota antes de bloco, etc.
TABLES: tuple[tuple[str, Reader], ...] = (
    ("users", read_users),
    # `sessions` não entra: é estado efêmero e o sha256 (64 chars) não cabe no rowId de 36.
    # Quem tinha sessão entra de novo; o login cria a linha com `documents.session_id`.
    ("notebooks", read_notebooks),
    ("notebook_members", read_members),
    ("notes", read_notes),
    ("blocks", read_blocks),
    ("tags", read_tags),
    ("notebook_tags", read_notebook_tags),
    ("note_tags", read_note_tags),
    ("note_relations", read_relations),
    ("block_links", read_block_links),
    ("media_files", read_media),
    ("events", read_events),
    ("drive_files", read_drive_files),
    ("drive_state", read_drive_state),
)

TABLE_ORDER = tuple(name for name, _ in TABLES)


# ------------------------------------------------------------------ esquema


def declared_columns() -> dict[str, list[str]]:
    """Lê o `SCHEMA` acima: {tabela: [colunas]}. Nenhuma dependência do SQLite."""
    tables: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in SCHEMA.splitlines():
        line = raw.strip().rstrip(",")
        if not line:
            continue
        if line.upper().startswith("CREATE TABLE"):
            current = []
            tables[line.split()[2].strip("((")] = current
            continue
        if line.startswith(")"):
            current = None
            continue
        if current is None:
            continue
        if line.split()[0].upper() in {"PRIMARY", "UNIQUE", "FOREIGN", "CONSTRAINT", "CHECK"}:
            continue
        current.append(line.split()[0].strip('"'))
    return tables


def check_schema(source: Source) -> tuple[list[str], list[str]]:
    """Confere o arquivo contra o `SCHEMA` transcrito: (erros, avisos).

    Tabela ou coluna que os SELECTs usam e não existe é erro (a leitura falharia torto); tabela
    a mais no arquivo é só aviso — dado antigo que este script não conhece.
    """
    errors: list[str] = []
    warnings: list[str] = []
    declared = declared_columns()
    found = source.table_names()
    for table in sorted(declared.keys() - found):
        errors.append(f"[esquema] tabela ausente no SQLite: {table}")
    for table in sorted(found - declared.keys()):
        warnings.append(f"[esquema] tabela não prevista no SCHEMA: {table}")
    for table, columns in declared.items():
        if table not in found:
            continue
        actual = set(source.columns(table))
        for column in columns:
            if column not in actual:
                errors.append(f"[esquema] coluna ausente: {table}.{column}")
    return errors, warnings


# ------------------------------------------------------------------ leitura por tabela


@dataclass
class Tally:
    read: int = 0
    created: int = 0
    existed: int = 0
    skipped: int = 0
    failed: int = 0
    highest: int = 0  # maior id numérico visto: é o valor que `counters` guarda
    problems: list[str] = field(default_factory=list)

    def read_line(self, label: str) -> str:
        tail = f", {self.skipped} puladas" if self.skipped else ""
        return f"{label}: {self.read} linhas{tail}"

    def write_line(self, label: str) -> str:
        parts = [f"{self.created} criadas", f"{self.existed} já existiam"]
        if self.skipped:
            parts.append(f"{self.skipped} puladas")
        if self.failed:
            parts.append(f"{self.failed} falharam")
        return f"{label}: {self.read} linhas lidas — " + ", ".join(parts)


def collect(source: Source, name: str, reader: Reader) -> tuple[list[Record], Tally]:
    """Lê a tabela **uma vez**: linhas prontas para escrita, contagens e problemas.

    Duas linhas que colidiriam no destino (rowId repetido, `name_key` de tag repetido) são
    puladas já aqui — escrever a segunda só produziria um 409 que se confundiria com o
    "já existe" da reexecução.
    """
    records: list[Record] = []
    counts = Tally()
    row_ids: set[str] = set()
    tag_keys: dict[str, str] = {}
    for record in reader(source):
        counts.read += 1
        reason = record.problem
        if not reason and record.row_id in row_ids:
            reason = "rowId repetido no SQLite"
        if record.table == "tags":
            key = str(record.data.get("name_key") or "")
            if not reason and key in tag_keys:
                reason = f"name_key repetido com a tag {tag_keys[key]} ({key})"
        if reason:
            counts.skipped += 1
            counts.problems.append(f"{name}/{record.row_id}: {reason}")
            continue
        row_ids.add(record.row_id)
        if record.row_id.isdigit():
            counts.highest = max(counts.highest, int(record.row_id))
        if record.table == "tags":
            tag_keys[str(record.data.get("name_key") or "")] = record.row_id
        records.append(record)
    return records, counts


def media_files_of(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file())


def media_report(directory: Path, rows: set[str]) -> tuple[list[Path], list[str], list[str]]:
    """Arquivos em disco, arquivos sem linha (sem dono) e linhas sem arquivo."""
    disk = media_files_of(directory)
    names = {path.name for path in disk}
    return disk, sorted(names - rows), sorted(rows - names)


# ------------------------------------------------------------------ dry-run


def dry_run(source: Source, readers: list[tuple[str, Reader]], media_dir: Path) -> int:
    """Relatório de contagens: só lê o SQLite e o diretório de mídia, nenhuma rede."""
    print(f"[origem] {source.path} (somente-leitura)")
    selected = {name for name, _ in readers}
    broken = 0
    filenames: set[str] = set()
    for name, reader in readers:
        records, counts = collect(source, name, reader)
        print("[dry-run] " + counts.read_line(name))
        for problem in counts.problems:
            print(f"[dry-run]   aviso: {problem}")
        broken += counts.skipped
        if name in COUNTER_FAMILIES:
            print(f"[dry-run] counters[{name}] = {counts.highest}")
        if name == "media_files":
            filenames = {record.row_id for record in records}
    if "media_files" in selected:
        disk, orphans, missing = media_report(media_dir, filenames)
        print(f"[dry-run] mídia: {len(disk)} arquivos em {media_dir}, {len(filenames)} linhas")
        for name in orphans:
            broken += 1
            print(f"[dry-run]   aviso: {name} está em disco sem linha em media_files (sem dono)")
        for name in missing:
            broken += 1
            print(f"[dry-run]   aviso: {name} tem linha em media_files mas não está em disco")
    print(f"[dry-run] sessions: não migra ({SKIP_REASON['sessions']})")
    print("[dry-run] nada foi escrito no Appwrite; use --apply para copiar.")
    return 1 if broken else 0


# ------------------------------------------------------------------ apply


def apply(source: Source, readers: list[tuple[str, Reader]], media_dir: Path) -> int:
    from appwrite.exception import AppwriteException
    from appwrite.input_file import InputFile

    from app.store import documents, store
    from app.store.client import DATABASE_ID, Conflict

    destination = store()
    selected = {name for name, _ in readers}
    print(f"[destino] database {DATABASE_ID} — {len(readers)} tabelas na fila")
    broken = 0
    filenames: set[str] = set()
    for name, reader in readers:
        records, counts = collect(source, name, reader)
        for record in records:
            try:
                documents.write(
                    record.table, record.row_id, record.data, owner_id=record.owner_id
                )
                counts.created += 1
            except Conflict:
                if destination.get(record.table, record.row_id) is not None:
                    counts.existed += 1
                else:
                    counts.failed += 1
                    counts.problems.append(
                        f"{record.row_id}: 409 sem a linha existir — índice único ocupado por "
                        f"outra linha (name_key compartilhado?)"
                    )
            except AppwriteException as error:
                counts.failed += 1
                counts.problems.append(f"{record.row_id}: {error}")
        print(counts.write_line(name))
        for problem in counts.problems:
            print(f"[{name}]   {problem}")
        broken += counts.skipped + counts.failed
        if name in COUNTER_FAMILIES:
            adjust_counter(destination, name, counts.highest)
        if name == "media_files":
            filenames = {record.row_id for record in records}
    if "media_files" in selected:
        broken += push_media(destination, InputFile, AppwriteException, media_dir, filenames)
    return 1 if broken else 0


def adjust_counter(destination: Any, family: str, highest: int) -> None:
    """`documents.record_id` lê este contador: ele guarda o **último** id usado, e nunca abaixa."""
    from app.store.client import Conflict

    row = destination.get("counters", family)
    if row is None:
        try:
            destination.create("counters", family, {"value": highest})
        except Conflict:
            row = destination.get("counters", family)
        else:
            print(f"[counters] {family} = {highest} (criado)")
            return
    current = int((row or {}).get("value") or 0)
    if current >= highest:
        print(f"[counters] {family}: {current} (já à frente de {highest})")
        return
    destination.update("counters", family, {"value": highest})
    print(f"[counters] {family}: {current} → {highest}")


def push_media(
    destination: Any, input_file: Any, exception: Any, directory: Path, rows: set[str]
) -> int:
    """Sobe os bytes de `data/media` para o bucket, com a permissão de leitura do dono.

    O arquivo do bucket tem o mesmo `rowId` da linha `media_files` (o nome do arquivo), então
    reexecutar só confere se ele já está lá.
    """
    from app.store.client import BUCKET_ID

    disk, orphans, missing = media_report(directory, rows)
    print(f"[media] {len(disk)} arquivos em {directory}, {len(rows)} linhas em media_files")
    broken = 0
    for name in orphans:
        broken += 1
        print(f"[media] {name}: arquivo em disco sem linha em media_files (sem dono), pulado")
    for name in missing:
        broken += 1
        print(f"[media] {name}: linha em media_files sem arquivo em disco — nada a subir")
    for path in disk:
        row = destination.get("media_files", path.name)
        if row is None:
            continue
        try:
            destination.storage.get_file(BUCKET_ID, path.name)
        except exception as error:
            if error.code != 404:
                broken += 1
                print(f"[media] {path.name}: {error}")
                continue
        else:
            print(f"[media] {path.name}: já estava no bucket")
            continue
        try:
            destination.storage.create_file(
                BUCKET_ID,
                path.name,
                input_file.from_path(str(path)),
                permissions=[f'read("user:{row["owner_id"]}")'],
            )
            print(f"[media] {path.name}: enviado ({path.stat().st_size} bytes)")
        except exception as error:
            broken += 1
            print(f"[media] {path.name}: {error}")
    return broken


# ------------------------------------------------------------------ cli


def select_tables(only: str) -> list[tuple[str, Reader]]:
    if not only.strip():
        return list(TABLES)
    wanted = [name.strip() for name in only.split(",") if name.strip()]
    unknown = [name for name in wanted if name not in TABLE_ORDER]
    if unknown:
        hints = "".join(
            f"\n  {name}: {SKIP_REASON[name]}" for name in unknown if name in SKIP_REASON
        )
        raise SystemExit(
            f"--only desconhecido: {', '.join(unknown)} (válidos: {', '.join(TABLE_ORDER)}){hints}"
        )
    chosen = set(wanted)
    return [(name, reader) for name, reader in TABLES if name in chosen]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="migrate_sqlite.py",
        description="Copia o SQLite do NotAI para o Appwrite preservando os ids como rowId.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="relatório de contagens, sem rede")
    mode.add_argument("--apply", action="store_true", help="copia as linhas (idempotente)")
    parser.add_argument(
        "--db", default=str(config.DATA_DIR / "caderno.db"), help="arquivo SQLite de origem"
    )
    parser.add_argument(
        "--media", default=str(config.DATA_DIR / "media"), help="diretório dos arquivos enviados"
    )
    parser.add_argument(
        "--only",
        default="",
        help=f"tabelas separadas por vírgula, na ordem de {TABLE_ORDER[0]}… (padrão: todas)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    database = Path(args.db)
    if not database.is_file():
        raise SystemExit(f"SQLite não encontrado: {database}")
    readers = select_tables(args.only)
    source = Source(database)
    try:
        errors, warnings = check_schema(source)
        for warning in warnings:
            print(warning)
        if errors:
            for error in errors:
                print(error)
            raise SystemExit(f"{database} não bate com o esquema esperado; nada foi tocado")
        if args.dry_run:
            return dry_run(source, readers, Path(args.media))
        return apply(source, readers, Path(args.media))
    finally:
        source.close()


if __name__ == "__main__":
    raise SystemExit(main())
