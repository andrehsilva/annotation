"""Drive export routes: connect, settings and the manual sync button, all scoped to the caller."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from .. import deps, drive, sync
from ..deps import get_db
from ..schemas import DriveSettings, DriveStatus, SyncSummary
from ..store import Store
from ..store.documents import Row

router = APIRouter(prefix="/api/drive", tags=["drive"])

# O fluxo OAuth bloqueia o worker até o navegador voltar (ou até o timeout de `drive.CONNECT_TIMEOUT`):
# sem estes dois limites, uma conta só segura o processo inteiro. Dois fluxos simultâneos bastam para
# o uso real — conectar é um passo único de configuração.
CONNECT_SLOTS = threading.BoundedSemaphore(2)
CONNECTING: set[int] = set()
CONNECTING_LOCK = threading.Lock()


def _claim_connect_slot(user_id: int) -> None:
    with CONNECTING_LOCK:
        if user_id in CONNECTING:
            raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma conexão em andamento.")
        if not CONNECT_SLOTS.acquire(blocking=False):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Muitas conexões em andamento. Tente de novo em instantes.",
            )
        CONNECTING.add(user_id)


def _release_connect_slot(user_id: int) -> None:
    with CONNECTING_LOCK:
        CONNECTING.discard(user_id)
    CONNECT_SLOTS.release()


@router.get("/status", response_model=DriveStatus)
def drive_status(
    db: Store = Depends(get_db), user: Row = Depends(deps.current_user)
) -> DriveStatus:
    return sync.status(db, user.id)


# Um `credentials.json` tem poucos KB; o teto evita carregar o corpo inteiro para depois recusar.
MAX_CLIENT_FILE = 256 * 1024


def _read_client_file(file: UploadFile) -> bytes:
    raw = file.file.read(MAX_CLIENT_FILE + 1)
    if len(raw) > MAX_CLIENT_FILE:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Arquivo acima de {MAX_CLIENT_FILE // 1024} KB: isso não é um credentials.json.",
        )
    return raw


@router.post("/client-file", response_model=DriveStatus)
def upload_client_file(
    file: UploadFile = File(...),
    db: Store = Depends(get_db),
    user: Row = Depends(deps.current_user),
) -> DriveStatus:
    try:
        drive.save_client_file(user.id, _read_client_file(file))
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    return sync.status(db, user.id)


@router.post("/connect", response_model=DriveStatus)
def connect(db: Store = Depends(get_db), user: Row = Depends(deps.current_user)) -> DriveStatus:
    if not drive.has_client_file(user.id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Coloque o credentials.json em {drive.client_file(user.id)}",
        )
    _claim_connect_slot(user.id)
    try:
        drive.connect(user.id)
    except drive.ConnectTimeout as error:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(error)) from error
    except HttpError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, sync.error_message(error)) from error
    except ValueError as error:  # client file that is not a "Desktop app" secret
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    finally:
        _release_connect_slot(user.id)
    return sync.status(db, user.id)


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(db: Store = Depends(get_db), user: Row = Depends(deps.current_user)) -> Response:
    sync.disconnect(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/settings", response_model=DriveStatus)
def update_settings(
    payload: DriveSettings,
    db: Store = Depends(get_db),
    user: Row = Depends(deps.current_user),
) -> DriveStatus:
    sync.set_auto_sync(db, user.id, payload.auto_sync)
    return sync.status(db, user.id)


@router.post("/sync", response_model=SyncSummary)
def sync_now(db: Store = Depends(get_db), user: Row = Depends(deps.current_user)) -> SyncSummary:
    if not drive.is_connected(user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "não conectado ao Google Drive")
    try:
        with sync.exclusive(user.id, timeout=60):
            return sync.export_notes(db, user.id)
    except sync.Busy as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except drive.NotConnected as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except RefreshError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, sync.error_message(error)) from error
    except (HttpError, TransportError, OSError) as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, sync.error_message(error)) from error
