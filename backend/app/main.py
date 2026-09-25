"""FastAPI application for NotAI: users, notebooks, notes, blocks, tags, relations."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import bootstrap, deps, migrations, sync
from .database import DATA_DIR, MEDIA_DIR, Base, engine
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
    if migrations.pending(engine):
        backup = migrations.snapshot(engine)
        if backup is not None:
            print(f"[notai] backup do banco antes da migração: {backup.name}", flush=True)
    Base.metadata.create_all(engine)
    migrations.add_columns(engine)
    owner = bootstrap.ensure_admin()
    migrations.run(engine, owner.id)
    migrations.backfill(engine, owner.id, MEDIA_DIR)
    migrations.move_drive_files(DATA_DIR, owner.id)
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
