"""Mídia no bucket do Appwrite: o upload vira arquivo do bucket e a linha em `media_files`.

Nada passa por disco local — o app só fala com o Storage. O teto aqui é o teto real do servidor
(`_APP_STORAGE_LIMIT` da VPS), porque o bucket não aceita `maximumFileSize` acima dele.
"""

from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path

from appwrite.exception import AppwriteException
from appwrite.input_file import InputFile
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from .. import deps, events, values
from ..deps import get_db
from ..schemas import MediaOut
from ..store import BUCKET_ID, Store, documents
from ..store.documents import Row

router = APIRouter(prefix="/api/media", tags=["media"])

# Sem prefixo: a URL que o dono vê (`/media/<arquivo>`) é a mesma gravada no bloco.
files_router = APIRouter()

# Teto do bucket: o Appwrite recusa `maximumFileSize` acima de `_APP_STORAGE_LIMIT` (30 MB nesta
# VPS). Recusar aqui evita o 400 do servidor e deixa a mensagem no idioma do app — os 256 MB do
# modelo antigo só voltam depois de subir a variável no servidor.
MAX_BYTES = 30_000_000
CHUNK = 1024 * 1024

TOO_BIG = f"Arquivo acima de {MAX_BYTES // 1_000_000} MB: o servidor recusa acima disso"

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


def _read(file: UploadFile) -> bytes:
    """Lê em blocos e para no teto: recusar não pode custar a memória do arquivo inteiro."""
    sink = BytesIO()
    size = 0
    while True:
        chunk = file.file.read(CHUNK)
        if not chunk:
            return sink.getvalue()
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, TOO_BIG)
        sink.write(chunk)


def _discard(db: Store, filename: str) -> None:
    """A linha não entrou: arquivo sozinho no bucket não serve para nada."""
    try:
        db.storage.delete_file(BUCKET_ID, filename)
    except AppwriteException:
        pass


@router.post("", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
def upload(
    file: UploadFile = File(...),
    user: Row = Depends(deps.current_user),
    db: Store = Depends(get_db),
) -> MediaOut:
    content_type = (file.content_type or "").lower()
    if content_type not in EXTENSIONS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Tipo não suportado: {content_type or 'desconhecido'}",
        )
    suffix = Path(file.filename or "").suffix.lower()
    extension = suffix if suffix in set(EXTENSIONS.values()) else EXTENSIONS[content_type]
    payload = _read(file)
    # O rowId de `media_files` é o nome do arquivo: o mesmo que a URL `/media/<nome>` usa.
    filename = f"{uuid.uuid4().hex}{extension}"
    original_name = file.filename or filename
    db.storage.create_file(
        BUCKET_ID,
        filename,
        InputFile.from_bytes(payload, filename, content_type),
        permissions=[f'read("user:{user.id}")'],  # o dono é o único que lê o arquivo
    )
    try:
        # `owner_id` descarta a foto do dono já no commit: a linha nova só existe lá, e a leitura
        # logo depois não pode receber a foto antiga do TTL.
        with db.transaction(owner_id=user.id) as tx:
            documents.write(
                "media_files",
                filename,
                {
                    "owner_id": str(user.id),
                    "original_name": original_name,
                    "content_type": content_type,
                    "size": len(payload),
                    "created_at": values.utcnow(),
                },
                owner_id=user.id,
                transaction_id=tx,
            )
            db.stage(tx, [events.operation(user.id, "uploaded", "media", original_name)])
    except Exception:
        _discard(db, filename)
        raise
    return MediaOut(
        url=f"/media/{filename}",
        kind="video" if content_type.startswith("video/") else "image",
        name=original_name,
        size=len(payload),
    )


@files_router.get("/media/{filename}", response_class=Response)
def get_media(
    filename: str,
    user: Row = Depends(deps.current_user),
    db: Store = Depends(get_db),
) -> Response:
    """Serve o arquivo só para o dono; um id alheio responde 404 como qualquer outro."""
    media = documents.media_by_filename(filename)
    if media is None or media.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado")
    return Response(
        content=db.storage.get_file_view(BUCKET_ID, media.row_id),
        media_type=media.content_type or None,
        # `private, no-store` porque a URL tem extensão de arquivo: cachê compartilhado à frente
        # (Cloudflare, que cacheia .png/.mp4 por padrão) guardaria a resposta do dono e a serviria
        # a quem não tem sessão — medido na instância de produção, com o arquivo respondendo 200
        # sem cookie depois de um único acesso autenticado.
        headers={"Cache-Control": "private, no-store"},
    )
