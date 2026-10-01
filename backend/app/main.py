"""FastAPI application for AnotAI: users, notes, blocks, tags, relations.

O app não guarda mais dado nenhum em SQLite: `app/store/` fala com o Appwrite (TablesDB + Storage) e
o processo é um BFF fino — contrato HTTP intacto, regra de negócio e agregação aqui.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import bootstrap, deps
from .routers import (
    admin,
    auth,
    blocks,
    events,
    github,
    groups,
    media,
    notes,
    relations,
    search,
    tags,
)

# Origens de desenvolvimento só entram se pedidas no ambiente: em produção o SPA é same-origin
# (o nginx serve a página e faz proxy de `/api`), então a lista vazia é a configuração certa — e ela
# também é a exceção do guard de escrita, então manter localhost aqui abriria a porta para qualquer
# processo local que suba um servidor na 5173.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CADERNO_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Sem migração de banco: o schema é versionado em `tools/appwrite_schema.py`.

    Só resta garantir que exista um admin — sem ele ninguém conseguiria entrar na primeira subida.
    """
    bootstrap.ensure_admin()
    yield


app = FastAPI(title="AnotAI API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(notes.router)
app.include_router(blocks.router)
app.include_router(tags.router)
app.include_router(media.router)
app.include_router(media.files_router)
app.include_router(search.router)
app.include_router(relations.router)
app.include_router(events.router)
app.include_router(github.router)
app.include_router(groups.router)


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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
