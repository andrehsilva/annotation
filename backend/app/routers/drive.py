"""Drive export routes: connect, settings and the manual sync button, all scoped to the caller."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from .. import deps, drive, sync
from ..database import get_db
from ..models import User
from ..schemas import DriveSettings, DriveStatus, SyncSummary

router = APIRouter(prefix="/api/drive", tags=["drive"])


@router.get("/status", response_model=DriveStatus)
def drive_status(
    db: Session = Depends(get_db), user: User = Depends(deps.current_user)
) -> DriveStatus:
    return sync.status(db, user.id)


@router.post("/client-file", response_model=DriveStatus)
def upload_client_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(deps.current_user),
) -> DriveStatus:
    try:
        drive.save_client_file(user.id, file.file.read())
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    return sync.status(db, user.id)


@router.post("/connect", response_model=DriveStatus)
def connect(db: Session = Depends(get_db), user: User = Depends(deps.current_user)) -> DriveStatus:
    if not drive.has_client_file(user.id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Coloque o credentials.json em {drive.client_file(user.id)}",
        )
    try:
        drive.connect(user.id)
    except HttpError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, sync.error_message(error)) from error
    except ValueError as error:  # client file that is not a "Desktop app" secret
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    return sync.status(db, user.id)


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(db: Session = Depends(get_db), user: User = Depends(deps.current_user)) -> Response:
    sync.disconnect(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/settings", response_model=DriveStatus)
def update_settings(
    payload: DriveSettings,
    db: Session = Depends(get_db),
    user: User = Depends(deps.current_user),
) -> DriveStatus:
    sync.set_auto_sync(db, user.id, payload.auto_sync)
    return sync.status(db, user.id)


@router.post("/sync", response_model=SyncSummary)
def sync_now(db: Session = Depends(get_db), user: User = Depends(deps.current_user)) -> SyncSummary:
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
