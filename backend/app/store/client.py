"""A única porta para o Appwrite: queries, linhas, transações, ids e cache.

`app/routers/*` e `app/services.py` nunca importam o SDK — falam com este módulo.

Dialeto da instância (medido, ver `tools/appwrite_schema.py`): só query no formato JSON; coluna de
texto é `string`; escrever em coluna recém-criada falha até ela ficar `available`; `create_operations`
descarta permissões de linha, por isso a entidade entra por `create_row(transaction_id=...)`.

O cache é por usuário e de vida curta: o BFF é um processo só, e as agregações que antes eram um
`GROUP BY` viram contagem em memória sobre a página já lida.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from appwrite.client import Client
from appwrite.exception import AppwriteException
from appwrite.services.storage import Storage
from appwrite.services.tables_db import TablesDB

from .. import config  # noqa: F401  (carrega backend/.env antes de ler o ambiente)

DATABASE_ID = os.environ.get("APPWRITE_DATABASE_ID", "notai")
BUCKET_ID = os.environ.get("APPWRITE_MEDIA_BUCKET_ID", "media")

# Teto de linhas por página nesta instância é livre; 100 mantém o número de requisições previsível.
PAGE = 100
# Quanto tempo uma foto do usuário pode ser reaproveitada antes de outra leitura. Toda escrita
# invalida, então o TTL só protege contra leitura repetida — e leitura repetida é o caso comum.
SNAPSHOT_TTL = float(os.environ.get("NOTAI_SNAPSHOT_TTL", "30"))
# `equal` aceita vários valores (é um IN), mas o teto medido é 100 por consulta.
IN_VALUES = 100
# Quantas requisições simultâneas ao Appwrite. A foto é uma dúzia de consultas curtas e o BFF passa
# a maior parte do tempo esperando a rede: em série davam ~4,5 s por lista de cadernos (medido).
SNAPSHOT_WORKERS = int(os.environ.get("NOTAI_SNAPSHOT_WORKERS", "8"))

SERVER_ONLY: list[str] = []

# Campos que são id de outra linha: no Appwrite a coluna é `string` e o SDK não converte — mandar
# `user.id` (int) reprova com "invalid type" (medido). Coagimos aqui, na porta de entrada, para
# nenhum router/função precisar lembrar do `str(...)`.
ID_FIELDS = frozenset({
    "user_id", "owner_id", "notebook_id", "note_id", "block_id", "tag_id",
    "source_id", "target_id", "file_id", "folder_id",
})


def owner_permissions(user_id: str | int) -> list[str]:
    """`read`/`update`/`delete` para o dono: a mesma regra que o app já aplica em toda rota."""
    who = f"user:{user_id}"
    return [f'read("{who}")', f'update("{who}")', f'delete("{who}")']


# ------------------------------------------------------------------ queries JSON


def q(**kwargs: Any) -> str:
    return json.dumps(kwargs)


def limit(count: int = PAGE) -> str:
    return q(method="limit", values=[count])


def offset(count: int) -> str:
    return q(method="offset", values=[count])


def order_asc(attribute: str) -> str:
    return q(method="orderAsc", attribute=attribute)


def order_desc(attribute: str) -> str:
    return q(method="orderDesc", attribute=attribute)


def equal(attribute: str, *values: Any) -> str:
    return q(method="equal", attribute=attribute, values=list(values))


def not_equal(attribute: str, *values: Any) -> str:
    return q(method="notEqual", attribute=attribute, values=list(values))


def is_null(attribute: str) -> str:
    return q(method="isNull", attribute=attribute)


def is_not_null(attribute: str) -> str:
    return q(method="isNotNull", attribute=attribute)


def cursor_after(row_id: str) -> str:
    return q(method="cursorAfter", values=[row_id])


def select(*attributes: str) -> str:
    return q(method="select", values=list(attributes))


def all_of(*queries: str) -> list[str]:
    """As queries JSON já são combinadas com AND pelo servidor: basta agrupá-las."""
    return [item for item in queries if item]


class Conflict(Exception):
    """`$id` ou índice único já ocupado (409)."""


class Reply:
    """Resposta crua do Appwrite, com a checagem de erro em um lugar só."""

    def __init__(self, raw: Any) -> None:
        self.raw = raw

    @property
    def total(self) -> int:
        return int((self.raw or {}).get("total") or 0)

    @property
    def rows(self) -> list[dict[str, Any]]:
        return list((self.raw or {}).get("rows") or [])


# ------------------------------------------------------------------ store


class Store:
    def __init__(self) -> None:
        endpoint = os.environ.get("APPWRITE_ENDPOINT", "")
        project = os.environ.get("APPWRITE_PROJECT_ID", "")
        key = os.environ.get("APPWRITE_API_KEY", "")
        if not (endpoint and project and key):
            raise RuntimeError(
                "Appwrite não configurado: defina APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID e "
                "APPWRITE_API_KEY (em backend/.env ou no ambiente)"
            )
        self.client = Client().set_endpoint(endpoint).set_project(project).set_key(key)
        self.tables = TablesDB(self.client)
        self.storage = Storage(self.client)
        self._lock = threading.Lock()
        self._snapshots: dict[int, tuple[float, dict[str, list[dict[str, Any]]], set[str]]] = {}
        # Tabelas tocadas por este thread desde a última `invalidate`: é o que diz *o que* da foto
        # precisa ser relido, em vez de descartar as dez tabelas por causa de uma linha.
        self._local = threading.local()

    def _touched(self, table: str) -> None:
        touched = getattr(self._local, "tables", None)
        if touched is None:
            touched = self._local.tables = set()
        touched.add(table)

    # -------------------------------------------------- leitura

    def list_rows(self, table: str, queries: list[str] | None = None) -> Reply:
        return Reply(self.tables.list_rows(DATABASE_ID, table, queries=queries or []))

    def page(
        self,
        table: str,
        queries: list[str] | None = None,
        ceiling: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Percorre todas as páginas com `limit`+`offset` (o cursor exige ordem estável)."""
        base = list(queries or [])
        start = 0
        got = 0
        while True:
            reply = self.list_rows(table, base + [limit(PAGE), offset(start)])
            if not reply.rows:
                return
            for row in reply.rows:
                yield row
                got += 1
                if ceiling is not None and got >= ceiling:
                    return
            if len(reply.rows) < PAGE:
                return
            start += PAGE

    def get(self, table: str, row_id: str | int) -> dict[str, Any] | None:
        try:
            return self.tables.get_row(DATABASE_ID, table, str(row_id))
        except AppwriteException as error:
            if error.code == 404:
                return None
            raise

    def count(self, table: str, queries: list[str] | None = None) -> int:
        reply = self.list_rows(table, list(queries or []) + [limit(1)])
        return reply.total

    # -------------------------------------------------- escrita

    def create(
        self,
        table: str,
        row_id: str | int,
        data: dict[str, Any],
        permissions: list[str] | None = None,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        self._touched(table)
        try:
            return self.tables.create_row(
                DATABASE_ID,
                table,
                str(row_id),
                _clean(data),
                permissions=SERVER_ONLY if permissions is None else permissions,
                transaction_id=transaction_id,
            )
        except AppwriteException as error:
            if error.code == 409:
                raise Conflict(f"{table}/{row_id} já existe") from error
            raise

    def update(
        self,
        table: str,
        row_id: str | int,
        data: dict[str, Any] | None = None,
        permissions: list[str] | None = None,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        self._touched(table)
        return self.tables.update_row(
            DATABASE_ID,
            table,
            str(row_id),
            _clean(data or {}),
            permissions=permissions,
            transaction_id=transaction_id,
        )

    def delete(self, table: str, row_id: str | int) -> bool:
        self._touched(table)
        try:
            self.tables.delete_row(DATABASE_ID, table, str(row_id))
            return True
        except AppwriteException as error:
            if error.code == 404:
                return False
            raise

    def delete_where(self, table: str, queries: list[str], batch: int = PAGE) -> int:
        """Apaga tudo que casa com as queries, em páginas (a rota de bulk é instável aqui)."""
        self._touched(table)
        removed = 0
        while True:
            rows = self.list_rows(table, list(queries) + [limit(batch)]).rows
            if not rows:
                return removed
            for row in rows:
                if self.delete(table, row["$id"]):
                    removed += 1
            if len(rows) < batch:
                return removed

    # -------------------------------------------------- transação

    @contextmanager
    def transaction(self, ttl: int = 60, owner_id: int | str | None = None) -> Iterator[str]:
        """Tudo que entrar com `transaction_id` só existe depois do commit.

        `create_operations` (eventos, vínculos, tags) entra aqui; a entidade principal vem por
        `create_row(..., transaction_id=)` porque é a única forma de gravar permissões na linha.

        A leitura **não enxerga linha estagiada** (medido), então a foto do usuário nasce velha se já
        estiver em cache: passe `owner_id` e ela é descartada no commit — `stage` e `delete_where`
        não têm como saber de quem é a linha, e essa era a pegadinha.
        """
        transaction_id = self.tables.create_transaction(ttl)["$id"]
        try:
            yield transaction_id
        except Exception:
            try:
                self.tables.update_transaction(transaction_id, rollback=True)
            except AppwriteException:
                pass
            raise
        try:
            self.tables.update_transaction(transaction_id, commit=True)
        except AppwriteException as error:
            # Medido nesta instância: linha repetida ou índice único violado só aparece AQUI, no
            # commit (`create_operations` não valida na hora) — e chega como "transaction has a
            # conflict". Traduzimos para a mesma `Conflict` que o create direto levanta.
            if error.code == 409:
                raise Conflict(
                    "a transação conflitou: alguma linha já existia ou um índice único foi violado"
                ) from error
            raise
        if owner_id is not None:
            self.invalidate(owner_id)

    def stage(self, transaction_id: str, operations: list[dict[str, Any]]) -> None:
        """Operações extras na mesma transação (sem permissão: a rota descarta).

        Cada `data` passa pelo mesmo `_clean` da escrita direta: a coluna de id é `string` e o
        servidor recusa `int` — sem isso, `user_id`/`notebook_id` vindos do banco estouravam só no
        commit, com "invalid type" (medido).
        """
        if not operations:
            return
        for operation in operations:
            table = operation.get("tableId")
            if isinstance(table, str) and table:
                self._touched(table)
        cleaned = [
            {**operation, "data": _clean(operation.get("data") or {})}
            for operation in operations
        ]
        self.tables.create_operations(transaction_id, cleaned)

    # -------------------------------------------------- ids

    def next_id(self, kind: str) -> int:
        """Contador por família de entidade, na tabela `counters` (incremento atômico).

        O incremento é a primeira tentativa: a leitura de guarda custava uma ida a mais por id
        sorteado — quatro por caderno criado, ~40 ms cada nesta instância. A linha só não existe na
        primeira vez de cada família, e aí o `create` resolve (com `Conflict` se outro pediu antes).
        """
        try:
            row = self.tables.increment_row_column(DATABASE_ID, "counters", kind, "value", 1)
            return int(row["value"])
        except AppwriteException as error:
            if error.code != 404:
                raise
        try:
            self.create("counters", kind, {"value": 1})
            return 1
        except Conflict:
            row = self.tables.increment_row_column(DATABASE_ID, "counters", kind, "value", 1)
            return int(row["value"])

    # -------------------------------------------------- cache por usuário

    # As três ondas de dependência do `load_snapshot`, reaproveitadas para reler só o que sujou.
    WAVES = (
        ("notebook_members", "notebooks", "tags", "media_files"),
        ("notes", "notebook_tags"),
        ("blocks", "note_tags", "block_links", "note_relations"),
    )

    def snapshot(self, user_id: int | str, fresh: bool = False) -> dict[str, list[dict[str, Any]]]:
        """Todos os dados de um usuário, paginados de uma vez e guardados por alguns segundos.

        As queries do Appwrite não têm `GROUP BY`/`JOIN`: as agregações do app contam em memória
        sobre esta foto, e o cache evita uma varredura por requisição. Depois de uma escrita entra
        só o que a escrita tocou (`_reload`) — reler as dez tabelas custava ~0,5 s por escrita.
        """
        key = int(user_id)
        now = time.monotonic()
        with self._lock:
            cached = self._snapshots.get(key)
            if not fresh and cached is not None and not cached[2] and now - cached[0] < SNAPSHOT_TTL:
                return cached[1]
        if not fresh and cached is not None and cached[2]:
            photo = self._reload(key, cached[1], cached[2])
        else:
            photo = {table: self._normalize(table, rows) for table, rows in self.load_snapshot(key).items()}
        with self._lock:
            self._snapshots[key] = (time.monotonic(), photo, set())
        return photo

    @staticmethod
    def _normalize(table: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Import tardio de propósito: `documents` importa este módulo, então a normalização
        # (linha crua -> `Row` com id int e datetime) acontece aqui, não no topo.
        from . import documents

        return [documents.normalize(table, row) for row in rows]

    def invalidate(self, user_id: int | str) -> None:
        """Marca para releitura as tabelas que este thread tocou.

        Sem toque registrado (uma escrita fora das rotas conhecidas) a foto inteira é relida, que é
        o comportamento antigo — o registro só estreita o que precisa voltar ao banco.
        """
        touched = getattr(self._local, "tables", None)
        self._local.tables = set()
        with self._lock:
            cached = self._snapshots.get(int(user_id))
            if cached is None:
                return
            loaded_at, photo, dirty = cached
            self._snapshots[int(user_id)] = (loaded_at, photo, dirty | (touched or set(photo)))

    def _reload(
        self, user_id: int, photo: dict[str, list[dict[str, Any]]], dirty: set[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Relê só as tabelas sujas, na mesma ordem de dependência da carga completa.

        Tabelas que não fazem parte da foto (contadores, eventos, espelho do Drive) não têm o que
        reler. Quando a lista de ids de caderno — ou de nota — muda, o que sai dela também volta:
        sem isso uma nota nova não apareceria, porque o `page_in` das ondas seguintes sai da foto.
        """
        if not set(photo) <= {name for wave in self.WAVES for name in wave}:
            return {table: self._normalize(table, rows) for table, rows in self.load_snapshot(user_id).items()}
        who = str(user_id)
        fresh = dict(photo)
        todo = set(dirty)

        def notebook_ids(source: dict[str, list[dict[str, Any]]]) -> list[str]:
            # A foto já é normalizada: `row_id` é o id cru do Appwrite e os campos de id de relação
            # viram int no modelo antigo — o `page_in` da onda seguinte quer todos como string.
            return sorted(
                {str(row["notebook_id"]) for row in source["notebook_members"]}
                | {str(row["row_id"]) for row in source["notebooks"]}
            )

        def note_ids(source: dict[str, list[dict[str, Any]]]) -> list[str]:
            return sorted(str(row["row_id"]) for row in source["notes"])

        def load(name: str) -> list[dict[str, Any]]:
            # Os ids saem da foto já atualizada pelas ondas anteriores: uma nota nova só aparece no
            # `page_in` da onda 3 se a lista dela vier das notas que acabaram de voltar do banco.
            nb_ids, nt_ids = notebook_ids(fresh), note_ids(fresh)
            if name == "notebook_members":
                return list(self.page("notebook_members", [equal("user_id", who)]))
            if name == "notebooks":
                return list(self.page("notebooks", [equal("owner_id", who)]))
            if name == "tags":
                return list(self.page("tags", [equal("owner_id", who)]))
            if name == "media_files":
                return list(self.page("media_files", [equal("owner_id", who)]))
            if name == "notes":
                return list(self.page_in("notes", "notebook_id", nb_ids))
            if name == "notebook_tags":
                return list(self.page_in("notebook_tags", "notebook_id", nb_ids))
            if name == "blocks":
                return list(self.page_in("blocks", "note_id", nt_ids))
            if name == "note_tags":
                return list(self.page_in("note_tags", "note_id", nt_ids))
            if name == "block_links":
                return list(self.page_in("block_links", "note_id", nt_ids))
            return self._relations_for_snapshot(nt_ids)

        before_notebooks, before_notes = notebook_ids(photo), note_ids(photo)
        for index, wave in enumerate(self.WAVES):
            pending = [name for name in wave if name in todo]
            if pending:
                with ThreadPoolExecutor(max_workers=SNAPSHOT_WORKERS) as pool:
                    futures = {name: pool.submit(load, name) for name in pending}
                    for name, future in futures.items():
                        fresh[name] = self._normalize(name, future.result())
            # Ids que mudaram puxam as ondas seguintes: o que sai deles ficou velho junto.
            if index == 0 and notebook_ids(fresh) != before_notebooks:
                todo |= set(self.WAVES[1]) | set(self.WAVES[2])
            if index == 1 and note_ids(fresh) != before_notes:
                todo |= set(self.WAVES[2])
        return fresh

    def load_snapshot(self, user_id: int) -> dict[str, list[dict[str, Any]]]:
        """Carrega as tabelas do usuário em três ondas paralelas (caderno → nota → bloco).

        A ordem das dependências é o que define as ondas: sem os ids dos cadernos não há como pedir
        as notas, e sem os das notas não há como pedir blocos/junções. Dentro de cada onda tudo vai
        junto — é o que derruba a latência de ~12 idas e voltas em série para ~3.
        """
        who = str(user_id)
        with ThreadPoolExecutor(max_workers=SNAPSHOT_WORKERS) as pool:
            members_f = pool.submit(lambda: list(self.page("notebook_members", [equal("user_id", who)])))
            owned_f = pool.submit(lambda: list(self.page("notebooks", [equal("owner_id", who)])))
            tags_f = pool.submit(lambda: list(self.page("tags", [equal("owner_id", who)])))
            media_f = pool.submit(lambda: list(self.page("media_files", [equal("owner_id", who)])))
            members, owned, tags, media = members_f.result(), owned_f.result(), tags_f.result(), media_f.result()

            notebook_ids = sorted(
                {row["notebook_id"] for row in members} | {row["$id"] for row in owned}
            )
            with ThreadPoolExecutor(max_workers=2) as second:
                notes_f = second.submit(lambda: list(self.page_in("notes", "notebook_id", notebook_ids)))
                notebook_tags_f = second.submit(
                    lambda: list(self.page_in("notebook_tags", "notebook_id", notebook_ids))
                )
                notes, notebook_tags = notes_f.result(), notebook_tags_f.result()
            note_ids = sorted(note["$id"] for note in notes)

            with ThreadPoolExecutor(max_workers=SNAPSHOT_WORKERS) as third:
                blocks_f = third.submit(lambda: list(self.page_in("blocks", "note_id", note_ids)))
                note_tags_f = third.submit(lambda: list(self.page_in("note_tags", "note_id", note_ids)))
                links_f = third.submit(lambda: list(self.page_in("block_links", "note_id", note_ids)))
                relations_f = third.submit(self._relations_for_snapshot, note_ids)
                blocks, note_tags, links, relations = (
                    blocks_f.result(), note_tags_f.result(), links_f.result(), relations_f.result(),
                )

        return {
            "notebooks": owned,
            "notebook_members": members,
            "notes": notes,
            "blocks": blocks,
            "tags": tags,
            "notebook_tags": notebook_tags,
            "note_tags": note_tags,
            "note_relations": relations,
            "block_links": links,
            "media_files": media,
        }

    def page_in(self, table: str, attribute: str, ids: list[str]) -> Iterator[dict[str, Any]]:
        """Página por lista de ids: `equal` com vários valores é um IN (teto de 100 por consulta).

        Uma consulta por tabela em vez de uma por pai — foi o que tirou a lista de cadernos de ~4,5 s
        para ~1,7 s (medido) e continua valendo quando o usuário tem mais de 100 cadernos/notas.
        """
        if not ids:
            return
        for start in range(0, len(ids), IN_VALUES):
            chunk = ids[start : start + IN_VALUES]
            yield from self.page(table, [equal(attribute, *chunk)])

    def _relations_for_snapshot(self, note_ids: list[str]) -> list[dict[str, Any]]:
        """Vínculos que tocam alguma nota do usuário, sem repetir o mesmo par duas vezes."""
        if not note_ids:
            return []
        rows: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [
                pool.submit(lambda attr=attr: list(self.page_in("note_relations", attr, note_ids)))
                for attr in ("source_id", "target_id")
            ]
            for future in pending:
                for row in future.result():
                    rows[row["$id"]] = row
        return list(rows.values())


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Tira `None` e serializa `datetime` — o SDK manda JSON, e datetime não passa.

    `None` explícito o servidor recusa em coluna não-requerida de forma inconsistente; e esquecer a
    conversão de data estourava só na hora do `json.dumps` (medido).
    """
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, datetime):
            cleaned[key] = to_iso_utc(value)
        elif key in ID_FIELDS and isinstance(value, (int, str)) and not isinstance(value, bool):
            cleaned[key] = str(value)
        else:
            cleaned[key] = value
    return cleaned


def to_iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"


_store: Store | None = None
_store_lock = threading.Lock()


def store() -> Store:
    global _store
    with _store_lock:
        if _store is None:
            _store = Store()
        return _store
