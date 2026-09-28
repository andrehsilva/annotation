"""Drive export routes: connect, settings and the manual sync button, all scoped to the caller."""

from __future__ import annotations

import secrets
import threading
import time

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from .. import deps, drive, sync
from ..deps import get_db
from ..schemas import DriveCallbackIn, DriveConnectOut, DriveSettings, DriveStatus, SyncSummary
from ..store import Store
from ..store.documents import Row

router = APIRouter(prefix="/api/drive", tags=["drive"])

# O `state` e o `code_verifier` (PKCE) entregues a cada conta, para conferir o que volta colado na
# tela. Vivem no processo (é o mesmo que atende a tela) e valem por `drive.AUTHORIZE_TTL`: passou
# disso, a conexão é recomeçada.
PENDING: dict[int, tuple[str, str, float]] = {}
PENDING_LOCK = threading.Lock()


def _pending(user_id: int) -> tuple[str, str]:
    """`(state, code_verifier)` da tentativa em voo; sem ela, a conexão precisa recomeçar."""
    with PENDING_LOCK:
        entry = PENDING.get(user_id)
    if entry is None or entry[2] < time.monotonic():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Comece de novo pelo botão “Conectar com o Google”."
        )
    return entry[0], entry[1]


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


@router.post("/connect", response_model=DriveConnectOut)
def connect(db: Store = Depends(get_db), user: Row = Depends(deps.current_user)) -> DriveConnectOut:
    """Devolve a URL de consentimento: quem abre é o navegador do usuário, não o servidor."""
    if not drive.has_client_file(user.id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Coloque o credentials.json em {drive.client_file(user.id)}",
        )
    state = secrets.token_urlsafe(16)
    url, verifier = drive.auth_url(user.id, state)
    with PENDING_LOCK:
        PENDING[user.id] = (state, verifier, time.monotonic() + drive.AUTHORIZE_TTL)
    return DriveConnectOut(url=url)


@router.post("/connect/code", response_model=DriveStatus)
def connect_code(
    payload: DriveCallbackIn,
    db: Store = Depends(get_db),
    user: Row = Depends(deps.current_user),
) -> DriveStatus:
    """Fecha a conexão com o que o usuário colou de volta: a URL de retorno ou só o código."""
    state, verifier = _pending(user.id)
    try:
        drive.finish(user.id, payload.callback, state, verifier)
    except drive.BadCallback as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    except drive.ExchangeUnavailable as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    with PENDING_LOCK:
        PENDING.pop(user.id, None)  # conectado: nem o `state` nem o verifier servem mais
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
