"""FastAPI application for NotAI: users, notebooks, notes, blocks, tags, relations.

O app não guarda mais dado nenhum em SQLite: `app/store/` fala com o Appwrite (TablesDB + Storage) e
o processo é um BFF fino — contrato HTTP intacto, regra de negócio e agregação aqui.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import bootstrap, deps, sync
from .routers import (
    admin,
    auth,
    blocks,
    drive,
    events,
    media,
    notebooks,
    notes,
    relations,
    search,
    tags,
)

ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Sem migração de banco: o schema é versionado em `tools/appwrite_schema.py`.

    Só resta garantir que exista um admin — sem ele ninguém conseguiria entrar na primeira subida.
    """
    bootstrap.ensure_admin()
    yield


app = FastAPI(title="NotAI API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(notebooks.router)
app.include_router(notes.router)
app.include_router(blocks.router)
app.include_router(tags.router)
app.include_router(media.router)
app.include_router(media.files_router)
app.include_router(search.router)
app.include_router(relations.router)
app.include_router(events.router)
app.include_router(drive.router)


@app.middleware("http")
async def refuse_foreign_origin(request: Request, call_next):
    """The session rides in a cookie, so a write has to come from a page of this same app."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        same_host = host is not None and origin == f"{request.url.scheme}://{host}"
        if origin is not None and not same_host and origin not in ALLOWED_ORIGINS:
            return JSONResponse({"detail": "Origem não permitida"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def schedule_sync_after_write(request: Request, call_next):
    """Every successful write to /api reschedules that user's Drive export."""
    response = await call_next(request)
    if (
        request.method != "GET"
        and request.url.path.startswith("/api/")
        and response.status_code < 400
    ):
        user_id = deps.session_user_id(request)
        if user_id is not None:
            sync.schedule_sync(user_id)
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------- DIAGNÓSTICO (temporário)
# Conta e cronometra cada chamada ao Appwrite e devolve no header: tempo do handler, tempo de I/O,
# número de chamadas e as três mais caras. Sai do arquivo assim que a causa da lentidão for medida.
import os as _os
import threading as _threading
import time as _time

from .store import client as _client

_DIAG_LOCK = _threading.Lock()
_DIAG: dict = {"calls": 0, "io": 0.0, "by": {}, "tx": 0.0}


class _Timed:
    """Proxy que cronometra qualquer método do serviço do SDK do Appwrite."""

    def __init__(self, target, sink, name):
        self._target, self._sink, self._name = target, sink, name

    def __getattr__(self, attr):
        value = getattr(self._target, attr)
        if attr.startswith("_") or not callable(value):
            return value

        def wrapped(*args, **kwargs):
            started = _time.perf_counter()
            try:
                return value(*args, **kwargs)
            finally:
                took = _time.perf_counter() - started
                entry = self._sink["by"].setdefault(f"{self._name}.{attr}", [0, 0.0])
                entry[0] += 1
                entry[1] += took
                self._sink["calls"] += 1
                self._sink["io"] += took

        return wrapped


def _install_diag() -> None:
    instance = _client.store()
    instance.tables = _Timed(instance.tables, _DIAG, "tables")
    instance.storage = _Timed(instance.storage, _DIAG, "storage")


_install_diag()


@app.middleware("http")
async def diag_timing(request: Request, call_next):
    with _DIAG_LOCK:
        _DIAG.update(calls=0, io=0.0, tx=0.0, by={})
    started = _time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:  # DIAGNÓSTICO: o traceback volta no corpo (o Loki do painel está fora)
        import traceback as _traceback

        return JSONResponse(
            {"diag": f"{type(error).__name__}: {error}", "trace": _traceback.format_exc()[-2500:]},
            status_code=500,
        )
    duration = _time.perf_counter() - started
    with _DIAG_LOCK:
        top = sorted(_DIAG["by"].items(), key=lambda item: -item[1][1])[:3]
        summary = ", ".join(f"{name}={data[0]}x{data[1]:.2f}" for name, data in top)
        calls, io_total = _DIAG["calls"], _DIAG["io"]
    response.headers["X-BFF-Time"] = f"{duration:.3f}"
    response.headers["X-BFF-IO"] = f"{io_total:.3f}s/{calls}calls"
    response.headers["X-BFF-TOP"] = summary
    with _DIAG_LOCK:
        try:
            cache = _client.store()._snapshots.get(1)
            state = (
                f"notes={len(cache[1]['notes'])} blocks={len(cache[1]['blocks'])} "
                f"notebooks={len(cache[1]['notebooks'])} dirty={','.join(sorted(cache[2])) or '-'}"
                if cache
                else "sem-foto"
            )
            reloads = " | ".join(_client.DIAG_RELOAD[-2:])
        except Exception as error:  # nunca deixa o diagnóstico derrubar a resposta
            state, reloads = f"erro: {error}", "-"
    response.headers["X-BFF-CACHE"] = state
    response.headers["X-BFF-RELOAD"] = reloads
    return response
