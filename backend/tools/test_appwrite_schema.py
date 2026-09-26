"""Throwaway: prova a lógica de provisionamento do tools/appwrite_schema.py com clientes falsos."""

from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, "/home/andrerodrigues/Documentos/projetcs/annotation/backend")
os.environ.setdefault("APPWRITE_ENDPOINT", "https://example.invalid/v1")
os.environ.setdefault("APPWRITE_PROJECT_ID", "fake")
os.environ.setdefault("APPWRITE_API_KEY", "fake")

import tools.appwrite_schema as schema  # noqa: E402


class FakeAppwriteException(schema.AppwriteException):
    pass


class FakeTables:
    def __init__(self, client):
        self.databases: dict[str, dict[str, dict]] = {}  # db -> table -> {"columns", "indexes"}

    def get(self, database_id):
        if database_id not in self.databases:
            raise FakeAppwriteException("not found", 404)
        return {"$id": database_id}

    def create(self, database_id, name, enabled=None):
        self.databases[database_id] = {}
        return {"$id": database_id}

    def get_table(self, database_id, table_id):
        if table_id not in self.databases.get(database_id, {}):
            raise FakeAppwriteException("not found", 404)
        return {"$id": table_id}

    def create_table(self, database_id, table_id, name, permissions=None, row_security=None, columns=None, indexes=None):
        self.databases.setdefault(database_id, {})[table_id] = {
            "columns": {c["key"]: {"status": "available", "type": c["type"]} for c in columns or []},
            "indexes": {},
        }
        return {"$id": table_id}

    def list_tables(self, database_id, queries=None, search=None, total=None):
        if database_id not in self.databases:
            raise FakeAppwriteException("not found", 404)
        return {"total": len(self.databases[database_id]), "tables": [{"$id": k} for k in self.databases[database_id]]}

    def list_columns(self, database_id, table_id, queries=None, total=None):
        # Dicionário, como o SDK deste dialeto devolve de verdade (não modelo).
        return {"total": 0, "columns": [{"key": k, "status": v["status"]} for k, v in self.databases[database_id][table_id]["columns"].items()]}

    def list_indexes(self, database_id, table_id, queries=None, total=None):
        return {"total": 0, "indexes": [{"key": k} for k in self.databases[database_id][table_id]["indexes"]]}

    def create_index(self, database_id, table_id, key, type, columns, **kwargs):
        self.databases[database_id][table_id]["indexes"][key] = {"type": type, "columns": columns}
        return {"key": key}

    def __getattr__(self, name):
        if not name.startswith("create_") or not name.endswith("_column"):
            raise AttributeError(name)

        def create_column(database_id, table_id, key, *args, **kwargs):
            self.databases[database_id][table_id]["columns"][key] = {
                "status": "available",
                "type": name[len("create_") : -len("_column")],
            }
            return {"key": key}

        return create_column


class FakeStorage:
    def __init__(self, client):
        self.buckets: dict[str, dict] = {}

    def get_bucket(self, bucket_id):
        if bucket_id not in self.buckets:
            raise FakeAppwriteException("not found", 404)
        return dict(self.buckets[bucket_id])

    def create_bucket(self, bucket_id, name, permissions=None, file_security=None, enabled=None,
                      maximum_file_size=None, allowed_file_extensions=None, compression=None,
                      encryption=None, antivirus=None, transformations=None):
        self.buckets[bucket_id] = {
            "maximumFileSize": maximum_file_size,
            "name": name,
        }
        return self.get_bucket(bucket_id)

    def update_bucket(self, bucket_id, name, **kwargs):
        self.buckets[bucket_id].update(
            {"maximumFileSize": kwargs["maximum_file_size"]}
            if kwargs.get("maximum_file_size") is not None
            else {}
        )
        return self.get_bucket(bucket_id)


schema.TablesDB = FakeTables
schema.Storage = FakeStorage

tables = FakeTables(None)
storage = FakeStorage(None)
real_tables, real_storage = schema.TablesDB, schema.Storage
schema.TablesDB = lambda client: tables
schema.Storage = lambda client: storage

failures: list[str] = []


def check(label, condition):
    print(f"{'ok  ' if condition else 'FAIL'} {label}")
    if not condition:
        failures.append(label)


# 1) checagem em instância vazia: relata e sai 1
code = schema.run(apply=False)
check("--check em instância vazia devolve 1", code == 1)

# 2) apply cria tudo
code = schema.run(apply=True)
check("--apply devolve 0", code == 0)
check("database criado", schema.DATABASE_ID in tables.databases)
check("17 tabelas criadas", len(tables.databases[schema.DATABASE_ID]) == len(schema.TABLE_SPECS))
expected_indexes = sum(len(s["indexes"]) for s in schema.TABLE_SPECS)
created_indexes = sum(
    len(t["indexes"]) for t in tables.databases[schema.DATABASE_ID].values()
)
check(f"{expected_indexes} índices criados", created_indexes == expected_indexes)
check("bucket criado com 256 MB", storage.buckets[schema.BUCKET_ID]["maximumFileSize"] == schema.MAX_MEDIA_BYTES)

# 3) rodar de novo não muda nada: cada create_* vira erro se for chamado
before = len(tables.databases[schema.DATABASE_ID])
calls: list[str] = []


def explode(name, original):
    def wrapper(*args, **kwargs):
        calls.append(name)
        return original(*args, **kwargs)

    return wrapper


for service in (tables, storage):
    for attr in dir(service):
        if attr.startswith(("create", "update")):
            setattr(service, attr, explode(attr, getattr(service, attr)))

code = schema.run(apply=True)
check("segunda passada devolve 0", code == 0)
check("segunda passada não cria nada", calls == [])
check("nenhuma tabela a mais", len(tables.databases[schema.DATABASE_ID]) == before)

# 4) instância atrás do schema: falta uma coluna e um índice → apply cria só eles
del tables.databases[schema.DATABASE_ID]["blocks"]["columns"]["caption"]
del tables.databases[schema.DATABASE_ID]["notes"]["indexes"]["idx_notes_position"]
calls.clear()
schema.run(apply=True)
check(
    "coluna faltante criada",
    "caption" in tables.databases[schema.DATABASE_ID]["blocks"]["columns"],
)
check("índice faltante criado", calls.count("create_index") == 1)
check("mais nada criado", sorted(set(c for c in calls if c.startswith("create_table"))) == [])

# 5) bucket pequeno demais é corrigido
storage.buckets[schema.BUCKET_ID]["maximumFileSize"] = 30_000_000
calls.clear()
schema.run(apply=True)
check("limite do bucket corrigido", "update_bucket" in calls)

print()
print("FALHAS:" if failures else "tudo passou", failures or "")
sys.exit(1 if failures else 0)
