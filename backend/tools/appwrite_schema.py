"""Schema do Appwrite como código: database, tabelas, índices e o bucket de mídia do NotAI.

    python tools/appwrite_schema.py --spec     # imprime o schema declarado, sem falar com a rede
    python tools/appwrite_schema.py --check    # diz o que falta na instância, não cria nada
    python tools/appwrite_schema.py --apply    # cria o que falta (idempotente)

Toda decisão de forma está no SPEC abaixo e vem de `app/models.py`:

* chave composta: as junções que **não expõem id** (`note_tags`, `note_members`, `group_members`)
  usam o rowId composto (`"<a>_<b>"`) — o `$id` é a chave primária e o "único por par" sai de graça.
  Já `note_relations` e `block_links` usam rowId **numérico** com índice `unique` no par, porque o id
  delas vai para a API e o SPA usa no `DELETE`; medido: índice unique de duas colunas funciona aqui e
  o par repetido responde 409;
* `tags.name_key` (`"<owner_id>::<nome minúsculo>"`) existe porque o índice unique do Appwrite é
  global e de uma coluna só — é ele que reproduz "nome único por dono";
* nenhuma coluna de relationship: as ligações são string indexada, iguais às do SQLite, para não
  herdar a proibição de bulk em tabela com relationship nem depender de cascata do servidor;
* `row_security=True` e permissões de tabela vazias: quem escreve é a API key (que ignora
  permissões) e as permissões de linha são gravadas por linha, com o dono, na hora da escrita.

Dialeto desta instância (`appwrite.sacadaweb.com.br`, reportando 1.8.1) — **verificado por probe**,
não pelo que a doc diz, porque diverge:

| o que | nesta instância |
|---|---|
| coluna de texto | só `string` com `size` (não existe `varchar`, `text`, `mediumtext`, `longtext`) |
| `size` | aceita de 16 a 268435456 e é **enforçado na escrita** (valor maior → 400) |
| tipo | `string`, `integer`, `boolean`, `datetime` (+ `email`/`enum`/`url`, que são string por dentro) |
| `create_table(columns=[...], indexes=[...])` | **ignora as colunas** — cada coluna é uma chamada própria |
| criação de coluna | assíncrona: `processing` → `available`; escrever antes disso dá `Unknown attribute` |
| query (`list_rows`) | só o dialeto **JSON**: `{"method":"limit","values":[10]}`, `{"method":"equal","attribute":"x","values":["y"]}` — o formato `limit(10)` responde 400 |
| `search` | exige índice fulltext, e mesmo com ele não achou termo existente → não confiar |
| transação | `create_transaction` + `create_operations` + commit/rollback funcionam (a auditoria entra no mesmo commit) |
| `total=False` | recusado; sempre vem `total` |
| teto de upload | o bucket não aceita `maximumFileSize` acima de `_APP_STORAGE_LIMIT` (30 MB no padrão): para os 256 MB do app é preciso subir essa variável no `.env` do Appwrite e recriar o stack |

Config: APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID, APPWRITE_API_KEY, APPWRITE_DATABASE_ID (notai),
APPWRITE_MEDIA_BUCKET_ID (media) — direto do ambiente ou de `backend/.env`.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any

from appwrite.client import Client
from appwrite.enums.compression import Compression
from appwrite.exception import AppwriteException
from appwrite.services.storage import Storage
from appwrite.services.tables_db import TablesDB


def load_dotenv() -> None:
    """`backend/.env` (fora do git) com APPWRITE_* — o mesmo arquivo que o BFF vai ler.

    Roda no import, antes das constantes abaixo: `APPWRITE_DATABASE_ID` do arquivo precisa valer
    já na primeira leitura.
    """
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

DATABASE_ID = os.environ.get("APPWRITE_DATABASE_ID", "notai")
BUCKET_ID = os.environ.get("APPWRITE_MEDIA_BUCKET_ID", "media")
DATABASE_NAME = "NotAI"

# 256 MB por arquivo, o mesmo teto do endpoint de upload do app.
MAX_MEDIA_BYTES = 256 * 1024 * 1024
# Teto do servidor: o bucket não passa de `_APP_STORAGE_LIMIT` (30 MB no padrão do Appwrite).
# Enquanto o `.env` do Appwrite não subir, o bucket fica neste valor — e o script diz isso.
SERVER_STORAGE_CAP = 30_000_000
MEDIA_EXTENSIONS = [
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "avif",
    "svg",
    "mp4",
    "webm",
    "ogv",
    "mov",
    "pdf",
]

OWNER = "owner_id"
TEXT_LIMIT = 16777215  # 16 MB: o texto de um bloco cabe inteiro numa coluna string

# Tipos aceitos nesta instância. `size` só vale para `string`.
CREATE_COLUMN: dict[str, str] = {
    "string": "create_string_column",
    "integer": "create_integer_column",
    "boolean": "create_boolean_column",
    "datetime": "create_datetime_column",
}
INDEX_TYPES = ("key", "unique", "fulltext")


def col(key: str, type_: str, required: bool = False, size: int | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {"key": key, "type": type_, "required": required}
    if size is not None:
        spec["size"] = size
    return spec


TABLE_SPECS: list[dict[str, Any]] = [
    {
        "id": "users",
        "name": "Usuários",
        "columns": [
            col("email", "string", True, 160),
            col("display_name", "string", size=80),
            col("password_hash", "string", True, 200),
            col("role", "string", True, 16),
            col("is_active", "boolean", True),
            col("created_at", "datetime"),
            col("last_login_at", "datetime"),
            col("activity_seen_at", "datetime"),
            # Nulo = a introdução do primeiro login ainda não foi dispensada, e ela abre no login.
            col("welcome_seen_at", "datetime"),
        ],
        "indexes": [{"key": "uq_users_email", "type": "unique", "columns": ["email"]}],
    },
    {
        "id": "sessions",
        "name": "Sessões",
        # rowId = sha256 do token: a chave primária já é o índice único de hoje.
        "columns": [
            col("user_id", "string", True, 36),
            col("created_at", "datetime"),
            col("expires_at", "datetime", True),
            col("last_seen_at", "datetime"),
        ],
        "indexes": [{"key": "idx_sessions_user", "type": "key", "columns": ["user_id"]}],
    },
    {
        "id": "groups",
        "name": "Grupos",
        # Grupos de contas, criados e mantidos pelo admin: são eles o público do compartilhamento.
        "columns": [
            col("name", "string", True, 60),
            col("created_by", "string", True, 36),
            col("created_at", "datetime"),
        ],
        "indexes": [],
    },
    {
        "id": "group_members",
        "name": "Membros do grupo",
        # rowId = "<group_id>_<user_id>"
        "columns": [
            col("group_id", "string", True, 36),
            col("user_id", "string", True, 36),
            col("created_at", "datetime"),
        ],
        "indexes": [
            {"key": "idx_group_members_group", "type": "key", "columns": ["group_id"]},
            {"key": "idx_group_members_user", "type": "key", "columns": ["user_id"]},
        ],
    },
    {
        # A nota é a unidade do app: tem dono, é ela que se compartilha e se relaciona. `position` é a
        # ordem na lista de quem pediu; `owner` é quem a criou.
        "id": "notes",
        "name": "Notas",
        "columns": [
            col(OWNER, "string", True, 36),
            col("title", "string", size=200),
            col("position", "integer", True),
            col("created_at", "datetime"),
            col("updated_at", "datetime"),
        ],
        "indexes": [
            {"key": "idx_notes_owner", "type": "key", "columns": [OWNER]},
            {"key": "idx_notes_position", "type": "key", "columns": ["position"]},
            {"key": "idx_notes_updated", "type": "key", "columns": ["updated_at"]},
        ],
    },
    {
        "id": "blocks",
        "name": "Blocos",
        "columns": [
            col("note_id", "string", True, 36),
            col("position", "integer", True),
            col("type", "string", True, 16),
            col("text", "string", size=TEXT_LIMIT),
            col("language", "string", size=40),
            col("url", "string", size=2000),
            col("caption", "string", size=2000),
            # Quem escreveu o bloco: é o que a nota compartilhada mostra em cada bloco que não é seu.
            # Vazio nas linhas de antes desta coluna — quem escrevia, aí, era o dono da nota.
            col("created_by", "string", False, 36),
            col("created_at", "datetime"),
            col("updated_at", "datetime"),
        ],
        "indexes": [
            {"key": "idx_blocks_note", "type": "key", "columns": ["note_id"]},
            {"key": "idx_blocks_position", "type": "key", "columns": ["position"]},
            {"key": "idx_blocks_type", "type": "key", "columns": ["type"]},
        ],
    },
    {
        "id": "tags",
        "name": "Tags",
        "columns": [
            col(OWNER, "string", True, 36),
            col("name", "string", True, 60),
            col("name_key", "string", True, 160),
            col("color", "string", size=16),
            col("created_at", "datetime"),
        ],
        "indexes": [
            {"key": "uq_tags_name_key", "type": "unique", "columns": ["name_key"]},
            {"key": "idx_tags_owner", "type": "key", "columns": [OWNER]},
        ],
    },
    {
        "id": "note_members",
        "name": "Membros da nota",
        # rowId = "<user_id>_<note_id>"
        "columns": [
            col("user_id", "string", True, 36),
            col("note_id", "string", True, 36),
            col("role", "string", True, 16),
            col("created_at", "datetime"),
        ],
        "indexes": [
            {"key": "idx_note_members_user", "type": "key", "columns": ["user_id"]},
            {"key": "idx_note_members_note", "type": "key", "columns": ["note_id"]},
        ],
    },
    {
        "id": "note_groups",
        "name": "Grupos da nota",
        # rowId = "<note_id>_<group_id>": a nota compartilhada com o grupo, com o papel que vale para
        # todo mundo dele (o mais alto entre esta linha e a linha direta do membro).
        "columns": [
            col("note_id", "string", True, 36),
            col("group_id", "string", True, 36),
            col("role", "string", True, 16),
            col("created_at", "datetime"),
        ],
        "indexes": [
            {"key": "idx_note_groups_note", "type": "key", "columns": ["note_id"]},
            {"key": "idx_note_groups_group", "type": "key", "columns": ["group_id"]},
        ],
    },
    {
        "id": "note_tags",
        "name": "Tags da nota",
        # rowId = "<note_id>_<tag_id>"
        "columns": [
            col("note_id", "string", True, 36),
            col("tag_id", "string", True, 36),
            col("created_at", "datetime"),
        ],
        "indexes": [
            {"key": "idx_note_tags_note", "type": "key", "columns": ["note_id"]},
            {"key": "idx_note_tags_tag", "type": "key", "columns": ["tag_id"]},
        ],
    },
    {
        "id": "note_relations",
        "name": "Vínculos entre notas",
        # rowId numérico (o id vai para a API e o SPA usa no DELETE), com unique no par:
        # (A,B) e (B,A) continuam sendo duas linhas, e o repetido responde 409.
        "columns": [
            col("source_id", "string", True, 36),
            col("target_id", "string", True, 36),
            col("label", "string", size=80),
            col("created_at", "datetime"),
        ],
        "indexes": [
            {"key": "idx_relations_source", "type": "key", "columns": ["source_id"]},
            {"key": "idx_relations_target", "type": "key", "columns": ["target_id"]},
            {"key": "uq_relations_pair", "type": "unique", "columns": ["source_id", "target_id"]},
        ],
    },
    {
        "id": "block_links",
        "name": "Menções de bloco",
        # rowId numérico, pelo mesmo motivo das relações; o par é único.
        "columns": [
            col("block_id", "string", True, 36),
            col("note_id", "string", True, 36),
            col("created_at", "datetime"),
        ],
        "indexes": [
            {"key": "idx_block_links_block", "type": "key", "columns": ["block_id"]},
            {"key": "idx_block_links_note", "type": "key", "columns": ["note_id"]},
            {"key": "uq_block_links", "type": "unique", "columns": ["block_id", "note_id"]},
        ],
    },
    {
        "id": "media_files",
        "name": "Arquivos enviados",
        # rowId = nome do arquivo no bucket, que já é único por construção
        "columns": [
            col(OWNER, "string", True, 36),
            col("original_name", "string", size=255),
            col("content_type", "string", size=80),
            col("size", "integer"),
            col("created_at", "datetime"),
        ],
        "indexes": [{"key": "idx_media_owner", "type": "key", "columns": [OWNER]}],
    },
    {
        "id": "events",
        "name": "Atividade",
        # `note_id` é o que deixa quem recebeu a nota compartilhada ver a atividade dela (o evento
        # continua sendo de quem agiu; a coluna diz onde a ação aconteceu).
        "columns": [
            col("user_id", "string", True, 36),
            col("action", "string", True, 24),
            col("entity", "string", True, 24),
            col("target", "string", size=200),
            col("detail", "string", size=80),
            col("note_id", "string", False, 36),
            col("created_at", "datetime", True),
        ],
        "indexes": [
            {"key": "idx_events_user", "type": "key", "columns": ["user_id"]},
            {"key": "idx_events_note", "type": "key", "columns": ["note_id"]},
            {"key": "idx_events_created", "type": "key", "columns": ["created_at"]},
        ],
    },
    {
        "id": "drive_files",
        "name": "Arquivos no Drive",
        # rowId = "<user_id>_<note_id>": o espelho é de **cada conta**. Com a nota compartilhada,
        # o rowId só pela nota fazia dois membros disputarem a mesma linha — o segundo encontrava a
        # linha do primeiro e concluía que a nota dele já estava no Drive.
        "columns": [
            col("user_id", "string", True, 36),
            col("file_id", "string", size=64),
            col("folder_id", "string", size=64),
            col("drive_path", "string", size=400),
            col("checksum", "string", size=64),
            col("synced_at", "datetime"),
        ],
        "indexes": [{"key": "idx_drive_files_user", "type": "key", "columns": ["user_id"]}],
    },
    {
        "id": "drive_state",
        "name": "Estado do export",
        # rowId = "<user_id>_<key>"
        "columns": [
            col("user_id", "string", True, 36),
            col("key", "string", True, 40),
            col("value", "string", size=4000),
        ],
        "indexes": [{"key": "idx_drive_state_user", "type": "key", "columns": ["user_id"]}],
    },
    {
        "id": "counters",
        "name": "Contadores de id",
        # rowId = nome do contador ("note", "block", ...). Avança com incrementRowColumn.
        "columns": [col("value", "integer", True)],
        "indexes": [],
    },
    {
        "id": "schema_version",
        "name": "Versão do schema",
        "columns": [col("version", "string", True, 16), col("applied_at", "datetime")],
        "indexes": [],
    },
]

BUCKET_SPEC: dict[str, Any] = {
    "id": BUCKET_ID,
    "name": "NotAI media",
    "file_security": True,
    "maximum_file_size": MAX_MEDIA_BYTES,
    "allowed_file_extensions": MEDIA_EXTENSIONS,
    "compression": Compression.NONE,  # imagem/vídeo já vêm comprimidos
    "encryption": True,
    "antivirus": False,  # sem ClamAV configurado na instância
    "transformations": True,
}

def log(message: str) -> None:
    print(message, flush=True)


# `create_string_column` é o único criador de texto deste dialeto: o aviso do SDK é ruído aqui.
warnings.filterwarnings("ignore", message="Call to deprecated function 'create_string_column'")


def report_storage_cap(error: AppwriteException) -> None:
    log(
        f"[schema] servidor recusou {MAX_MEDIA_BYTES // 1024 // 1024} MB ({error.message}); "
        f"bucket fica em {SERVER_STORAGE_CAP // 1000 // 1000} MB até subir `_APP_STORAGE_LIMIT` "
        "no .env do Appwrite e recriar o stack"
    )


def client() -> Client:
    for name in ("APPWRITE_ENDPOINT", "APPWRITE_PROJECT_ID", "APPWRITE_API_KEY"):
        if not os.environ.get(name):
            log(f"[schema] falta {name} no ambiente (ou em backend/.env)")
            sys.exit(2)
    return (
        Client()
        .set_endpoint(os.environ["APPWRITE_ENDPOINT"])
        .set_project(os.environ["APPWRITE_PROJECT_ID"])
        .set_key(os.environ["APPWRITE_API_KEY"])
    )


def is_missing(error: AppwriteException) -> bool:
    return error.code == 404


def create_column(tables: TablesDB, table_id: str, spec: dict[str, Any]) -> None:
    method = getattr(tables, CREATE_COLUMN[spec["type"]])
    if spec["type"] == "string":
        method(DATABASE_ID, table_id, spec["key"], spec["size"], spec["required"])
    else:
        method(DATABASE_ID, table_id, spec["key"], spec["required"])


def wait_columns(tables: TablesDB, table_id: str, keys: list[str], timeout: float = 180) -> None:
    """Tabela e coluna nascem em `processing`; escrever antes disso dá `Unknown attribute`."""
    deadline = time.monotonic() + timeout
    pending = set(keys)
    while pending and time.monotonic() < deadline:
        try:
            listed = tables.list_columns(DATABASE_ID, table_id)
            existing = {c["key"]: c.get("status") for c in listed["columns"]}
        except AppwriteException as error:
            if not is_missing(error):
                raise
            existing = {}
        for key in list(pending):
            if existing.get(key) == "available":
                pending.discard(key)
        if pending:
            time.sleep(1)
    if pending:
        log(f"[schema] ainda processando em {table_id}: {', '.join(sorted(pending))}")


# ------------------------------------------------------------------ tabelas


def ensure_table(tables: TablesDB, spec: dict[str, Any], apply: bool) -> bool:
    """Devolve True quando criou ou quando algo falta. `apply=False` só relata."""
    table_id = spec["id"]
    try:
        tables.get_table(DATABASE_ID, table_id)
    except AppwriteException as error:
        if not is_missing(error):
            raise
        # Tabela ausente implica colunas e índices ausentes: em --check não há o que inspecionar.
        if not apply:
            log(
                f"[schema] falta tabela {table_id} "
                f"({len(spec['columns'])} colunas, {len(spec['indexes'])} índices)"
            )
            return True
        tables.create_table(
            database_id=DATABASE_ID,
            table_id=table_id,
            name=spec["name"],
            permissions=[],
            row_security=True,
        )
        log(f"[schema] + tabela {table_id}")
        for column in spec["columns"]:
            create_column(tables, table_id, column)
        wait_columns(tables, table_id, [c["key"] for c in spec["columns"]])
        changed = True
    else:
        changed = False

    if not changed:
        listed = tables.list_columns(DATABASE_ID, table_id)
        have = {c["key"] for c in listed["columns"]}
        added = False
        for column in spec["columns"]:
            if column["key"] in have:
                continue
            if not apply:
                log(f"[schema] falta coluna {table_id}.{column['key']}")
                changed = True
                continue
            create_column(tables, table_id, column)
            log(f"[schema] + coluna {table_id}.{column['key']}")
            changed = added = True
        if added:
            wait_columns(tables, table_id, [c["key"] for c in spec["columns"]])

    listed = tables.list_indexes(DATABASE_ID, table_id)
    index_keys = {i["key"] for i in listed["indexes"]}
    for index in spec["indexes"]:
        if index["key"] in index_keys:
            continue
        if not apply:
            log(f"[schema] falta índice {table_id}.{index['key']}")
            changed = True
            continue
        tables.create_index(
            database_id=DATABASE_ID,
            table_id=table_id,
            key=index["key"],
            type=index["type"],
            columns=index["columns"],
        )
        log(f"[schema] + índice {table_id}.{index['key']}")
        changed = True
    return changed


def ensure_database(tables: TablesDB, apply: bool) -> bool:
    """`get(database)` está quebrado nesta instância (resposta sem campos que o SDK exige);
    `list_tables` é a sonda confiável: 404 quando o database não existe."""
    try:
        tables.list_tables(DATABASE_ID)
        return False
    except AppwriteException as error:
        if not is_missing(error):
            raise
    if apply:
        tables.create(database_id=DATABASE_ID, name=DATABASE_NAME)
    log(f"[schema] {'+' if apply else 'falta'} database {DATABASE_ID}")
    return True


def ensure_bucket(storage: Storage, apply: bool) -> bool:
    try:
        bucket = storage.get_bucket(BUCKET_ID)
    except AppwriteException as error:
        if not is_missing(error):
            raise
        if apply:
            try:
                storage.create_bucket(
                    bucket_id=BUCKET_ID,
                    name=BUCKET_SPEC["name"],
                    permissions=[],
                    file_security=BUCKET_SPEC["file_security"],
                    enabled=True,
                    maximum_file_size=BUCKET_SPEC["maximum_file_size"],
                    allowed_file_extensions=BUCKET_SPEC["allowed_file_extensions"],
                    compression=BUCKET_SPEC["compression"],
                    encryption=BUCKET_SPEC["encryption"],
                    antivirus=BUCKET_SPEC["antivirus"],
                    transformations=BUCKET_SPEC["transformations"],
                )
            except AppwriteException as refused:
                if refused.code != 400 or "maximumFileSize" not in str(refused.message):
                    raise
                report_storage_cap(refused)
                storage.create_bucket(
                    bucket_id=BUCKET_ID,
                    name=BUCKET_SPEC["name"],
                    permissions=[],
                    file_security=BUCKET_SPEC["file_security"],
                    enabled=True,
                    maximum_file_size=SERVER_STORAGE_CAP,
                    allowed_file_extensions=BUCKET_SPEC["allowed_file_extensions"],
                    compression=BUCKET_SPEC["compression"],
                    encryption=BUCKET_SPEC["encryption"],
                    antivirus=BUCKET_SPEC["antivirus"],
                    transformations=BUCKET_SPEC["transformations"],
                )
        log(f"[schema] {'+' if apply else 'falta'} bucket {BUCKET_ID}")
        return True
    # O SDK deste dialeto devolve dicionário, não modelo: a chave é a do JSON da API.
    changed = False
    current = int(bucket.get("maximumFileSize") or 0)
    extensions = [str(value) for value in (bucket.get("allowedFileExtensions") or [])]
    missing_types = [value for value in MEDIA_EXTENSIONS if value not in extensions]
    if missing_types:
        # O `--check` só olhava o tamanho, e foi assim que o `.pdf` ficou de fora do bucket mesmo
        # estando no schema e no app: o upload de PDF respondia "File extension not allowed".
        if apply:
            storage.update_bucket(
                bucket_id=BUCKET_ID,
                name=BUCKET_SPEC["name"],
                maximum_file_size=current or SERVER_STORAGE_CAP,
                allowed_file_extensions=MEDIA_EXTENSIONS,
            )
        log(
            f"[schema] {'~' if apply else 'falta'} bucket {BUCKET_ID} aceitar "
            f"{', '.join(missing_types)}"
        )
        changed = True
    if current < MAX_MEDIA_BYTES:
        if apply:
            try:
                storage.update_bucket(
                    bucket_id=BUCKET_ID,
                    name=BUCKET_SPEC["name"],
                    maximum_file_size=MAX_MEDIA_BYTES,
                    allowed_file_extensions=BUCKET_SPEC["allowed_file_extensions"],
                )
            except AppwriteException as refused:
                if refused.code != 400 or "maximumFileSize" not in str(refused.message):
                    raise
                report_storage_cap(refused)
        log(f"[schema] {'~' if apply else 'falta'} limite do bucket {BUCKET_ID} subindo para 256 MB")
        changed = True
    return changed


# ------------------------------------------------------------------ comandos


def column_label(column: dict[str, Any]) -> str:
    label = f"{column['key']}:{column['type']}"
    if column.get("size"):
        label += f"({column['size']})"
    return label + ("!" if column["required"] else "")


def print_spec() -> None:
    log(f"database {DATABASE_ID} ({DATABASE_NAME}) — row_security em todas as tabelas")
    for spec in TABLE_SPECS:
        log(f"  {spec['id']:<18} {', '.join(column_label(c) for c in spec['columns'])}")
        for index in spec["indexes"]:
            log(f"  {'':<18} {index['type']:<8} {index['key']} ({', '.join(index['columns'])})")
    log(
        f"bucket {BUCKET_ID}: file_security, {MAX_MEDIA_BYTES // 1024 // 1024} MB, "
        f"{', '.join(MEDIA_EXTENSIONS)}"
    )


def prune(tables: TablesDB, apply: bool) -> bool:
    """O que está na instância e **não** está no schema: tabelas e colunas que sobraram.

    O schema é a fonte da verdade, então o que saiu dele tem de sair da instância — foi assim que o
    caderno deixou de existir: as quatro tabelas dele e a coluna `notes.notebook_id`. Apagar é
    destrutivo, então só com `--prune` explícito; sem ele, isto é relatório (e o `--check` acusa).
    """
    known = {spec["id"]: spec for spec in TABLE_SPECS}
    changed = False
    try:
        rows = tables.list_tables(DATABASE_ID).get("tables", [])
    except AppwriteException as error:
        # Database ausente (instância nova): não há sobra para procurar — quem cria é o `--apply`.
        if is_missing(error):
            return False
        raise
    for row in rows:
        table_id = row.get("$id") or row.get("id")
        spec = known.get(table_id)
        if spec is None:
            if apply:
                tables.delete_table(DATABASE_ID, table_id)
            log(f"[schema] {'-' if apply else 'sobra'} tabela {table_id}")
            changed = True
            continue
        if apply and not all(column["key"] in {c["key"] for c in spec["columns"]} for column in row.get("columns", [])):
            pass  # as colunas são conferidas abaixo, uma a uma
        for column in row.get("columns") or []:
            key = column.get("key")
            if key in {c["key"] for c in spec["columns"]}:
                continue
            # Índice que usa a coluna sai antes dela, senão o servidor recusa a remoção.
            for index in row.get("indexes") or []:
                if key in (index.get("columns") or []):
                    if apply:
                        tables.delete_index(DATABASE_ID, table_id, index.get("key") or index.get("$id"))
                    log(f"[schema] {'-' if apply else 'sobra'} índice {table_id}.{index.get('key')}")
                    changed = True
            if apply:
                tables.delete_column(DATABASE_ID, table_id, key)
            log(f"[schema] {'-' if apply else 'sobra'} coluna {table_id}.{key}")
            changed = True
    return changed


def run(apply: bool, prune_extra: bool = False) -> int:
    connection = client()
    tables = TablesDB(connection)
    storage = Storage(connection)

    try:
        missing = ensure_database(tables, apply)
        for spec in TABLE_SPECS:
            missing = ensure_table(tables, spec, apply) or missing
        missing = ensure_bucket(storage, apply) or missing
        # Sem `--prune` isto é relatório: o que saiu do schema aparece no `--check` (e no `--apply`
        # como sobra), mas nada é apagado sem a flag explícita.
        missing = prune(tables, apply=apply and prune_extra) or missing
    except AppwriteException as error:
        log(f"[schema] Appwrite recusou ({error.code} {error.type}): {error.message}")
        return 2

    if missing and not apply:
        log("[schema] instância atrás do schema: rode --apply")
        return 1
    log("[schema] schema em dia" if not missing else "[schema] aplicado")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="appwrite_schema.py", description="Schema do NotAI no Appwrite")
    parser.add_argument("--spec", action="store_true", help="imprime o schema declarado (offline)")
    parser.add_argument("--check", action="store_true", help="relata o que falta, sem criar nada")
    parser.add_argument("--apply", action="store_true", help="cria o que falta")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="com --apply, apaga tabela/coluna que saiu do schema (destrutivo)",
    )
    args = parser.parse_args(argv)

    if args.spec:
        print_spec()
        return 0
    if not (args.check or args.apply):
        parser.error("escolha --spec, --check ou --apply")
    if args.prune and not args.apply:
        parser.error("--prune só faz sentido junto com --apply")
    return run(apply=args.apply, prune_extra=args.prune)


if __name__ == "__main__":
    raise SystemExit(main())
