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
    "application/pdf": ".pdf",
}

# O PDF é documento, não mídia embutida: `<img>`/`<video>` não desenham um PDF, e o bloco o abre numa
# aba nova. Só para ele o `Content-Disposition` é `inline`, que é o que deixa o visualizador do
# navegador desenhá-lo — o resto continua `attachment` (um SVG aberto como página executaria script
# na origem do app). O `sandbox` do CSP segue valendo no PDF: ele desenha, mas em origem opaca.
INLINE_TYPES = frozenset({"application/pdf"})


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


def _store(db: Store, filename: str, payload: bytes, content_type: str, user_id: int) -> None:
    """Grava no bucket traduzindo a recusa do Appwrite: sem isto o cliente recebia um `500` seco.

    O bucket é quem manda na extensão (`allowed_file_extensions`, o schema o mantém em dia) e, quando
    o Storage do Appwrite está fora, o erro chega como página HTML do Cloudflare — as duas coisas
    viravam "Internal Server Error" na tela, sem dizer o que fazer.
    """
    try:
        db.storage.create_file(
            BUCKET_ID,
            filename,
            InputFile.from_bytes(payload, filename, content_type),
            permissions=[f'read("user:{user_id}")'],  # o dono é o único que lê o arquivo
        )
    except AppwriteException as error:
        if error.code == 400 and "extension" in str(error.message).lower():
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "O bucket do servidor recusa este tipo de arquivo — rode "
                "`tools/appwrite_schema.py --apply` para pôr a lista de extensões em dia",
            ) from error
        if error.code and error.code >= 500:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "O armazenamento do Appwrite não respondeu agora. Tente de novo em instantes",
            ) from error
        raise


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
    _store(db, filename, payload, content_type, user.id)
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
    kind = "video" if content_type.startswith("video/") else "image"
    return MediaOut(
        url=f"/media/{filename}",
        kind="pdf" if content_type in INLINE_TYPES else kind,
        name=original_name,
        size=len(payload),
    )


def _shared_with_me(db: Store, user: Row, filename: str) -> bool:
    """O arquivo entra em alguma nota de caderno que eu alcanço?

    O arquivo é do dono, mas a nota que o cita pode estar num caderno com mais membros — quem lê a
    nota precisa ver a imagem dela. O que continua fechado é arquivo que não aparece em nada meu:
    é a mesma regra do caderno compartilhado, aplicada à mídia.
    """
    url = f"/media/{filename}"
    photo = db.snapshot(user.id)
    note_ids = {note.id for note in photo["notes"]}
    return any(block.url == url for block in photo["blocks"] if block.note_id in note_ids)


@files_router.get("/media/{filename}", response_class=Response)
def get_media(
    filename: str,
    user: Row = Depends(deps.current_user),
    db: Store = Depends(get_db),
) -> Response:
    """Serve o arquivo só para o dono; um id alheio responde 404 como qualquer outro."""
    media = documents.media_by_filename(filename)
    if media is None or (media.owner_id != user.id and not _shared_with_me(db, user, filename)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado")
    # Nome seguro para o cabeçalho: sem quebra de linha nem aspas, que reinventariam o header.
    raw_name = media.original_name or filename
    safe_name = "".join(ch for ch in raw_name if ch.isascii() and ch not in '"\\\r\n') or filename
    content_type = (media.content_type or "").lower()
    # PDF desenha só como documento: o bloco o abre em aba nova e o `inline` é o que deixa o
    # visualizador do navegador desenhá-lo (medido no Chromium: com `attachment` a navegação é
    # abortada e o arquivo vira download). O `sandbox` segue no CSP, então ele desenha em origem opaca.
    disposition = "inline" if content_type in INLINE_TYPES else "attachment"
    return Response(
        content=db.storage.get_file_view(BUCKET_ID, media.row_id),
        media_type=media.content_type or None,
        # `private, no-store` porque a URL tem extensão de arquivo: cachê compartilhado à frente
        # (Cloudflare, que cacheia .png/.mp4 por padrão) guardaria a resposta do dono e a serviria
        # a quem não tem sessão — medido na instância de produção, com o arquivo respondendo 200
        # sem cookie depois de um único acesso autenticado.
        #
        # `attachment` + `nosniff` + CSP sem origem: um SVG enviado aqui executa script se for aberto
        # como página, e essa página seria a origem do app (o cookie é HttpOnly, mas o script fala
        # com a API). `<img>`/`<video>` ignoram o Content-Disposition, então a nota segue mostrando
        # a mídia normalmente.
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'{disposition}; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
