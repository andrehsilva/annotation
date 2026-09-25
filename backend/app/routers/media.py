"""Local media store. Uploads land in <data>/media and are served from /media."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import deps, events
from ..database import MEDIA_DIR, get_db
from ..models import MediaFile, User
from ..schemas import MediaOut

router = APIRouter(prefix="/api/media", tags=["media"])

# Sem prefixo: a URL que o dono vê (`/media/<arquivo>`) é a mesma gravada no bloco.
files_router = APIRouter()

MAX_BYTES = 256 * 1024 * 1024

EXTENSIONS: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/ogg": ".ogv",
    "video/quicktime": ".mov",
}


@router.post("", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
def upload(
    file: UploadFile = File(...),
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> MediaOut:
    content_type = (file.content_type or "").lower()
    if content_type not in EXTENSIONS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Tipo não suportado: {content_type or 'desconhecido'}",
        )
    suffix = Path(file.filename or "").suffix.lower()
    extension = suffix if suffix in set(EXTENSIONS.values()) else EXTENSIONS[content_type]
    target = MEDIA_DIR / f"{uuid.uuid4().hex}{extension}"
    with target.open("wb") as sink:
        shutil.copyfileobj(file.file, sink, length=1024 * 1024)
    size = target.stat().st_size
    if size > MAX_BYTES:
        target.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Arquivo acima de 256 MB")
    db.add(
        MediaFile(
            owner_id=user.id,
            filename=target.name,
            original_name=file.filename or target.name,
            content_type=content_type,
            size=size,
        )
    )
    events.record(db, user, "uploaded", "media", file.filename or target.name)
    db.commit()
    return MediaOut(
        url=f"/media/{target.name}",
        kind="video" if content_type.startswith("video/") else "image",
        name=file.filename or target.name,
        size=size,
    )


@files_router.get("/media/{filename}", response_class=FileResponse)
def get_media(
    filename: str,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve o arquivo só para o dono; um id alheio responde 404 como qualquer outro."""
    media = db.scalars(select(MediaFile).where(MediaFile.filename == filename)).one_or_none()
    if media is None or media.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado")
    return FileResponse(MEDIA_DIR / media.filename, media_type=media.content_type or None)
