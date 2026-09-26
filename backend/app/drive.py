"""Google Drive OAuth for the export: one client/token pair per user, scope `drive.file`.

`drive.file` only sees files this app created, so the export owns everything under `NotAI/` and
never touches the rest of the user's Drive.
"""

from __future__ import annotations

import json
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from .config import DATA_DIR

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

BAD_CLIENT_FILE = (
    "JSON inválido: envie o arquivo de cliente OAuth do tipo 'Aplicativo para computador'"
)
EXPIRED = "autorização expirada — conecte de novo"


class NotConnected(Exception):
    """No usable token on disk."""


def client_file(user_id: int) -> Path:
    """The OAuth client json uploaded by this user."""
    return DATA_DIR / f"drive_client.{user_id}.json"


def token_file(user_id: int) -> Path:
    """The stored authorization for this user's own Drive account."""
    return DATA_DIR / f"drive_token.{user_id}.json"


def has_client_file(user_id: int) -> bool:
    return client_file(user_id).exists()


def is_connected(user_id: int) -> bool:
    """Cheap check for the UI: a token file that still parses. Expiry surfaces on the next call."""
    path = token_file(user_id)
    if not path.exists():
        return False
    try:
        Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, json.JSONDecodeError):
        return False
    return True


def credentials(user_id: int) -> Credentials:
    """Load and refresh the stored token; drop it when the refresh is refused."""
    path = token_file(user_id)
    if not path.exists():
        raise NotConnected("não conectado ao Google Drive")
    try:
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, json.JSONDecodeError) as error:
        path.unlink(missing_ok=True)
        raise NotConnected("token ilegível — conecte de novo") from error

    if not creds.valid:
        if not creds.refresh_token:
            path.unlink(missing_ok=True)
            raise NotConnected(EXPIRED)
        try:
            creds.refresh(Request())
        except RefreshError as error:
            path.unlink(missing_ok=True)
            raise NotConnected(EXPIRED) from error
        path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def service(user_id: int) -> Resource:
    return build("drive", "v3", credentials=credentials(user_id), cache_discovery=False)


def save_client_file(user_id: int, raw: bytes) -> None:
    """Store the OAuth client json downloaded from Google Cloud (type 'Desktop app')."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(BAD_CLIENT_FILE) from error
    if not isinstance(payload, dict) or "installed" not in payload:
        raise ValueError(BAD_CLIENT_FILE)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client_file(user_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def connect(user_id: int) -> None:
    """Open the browser and block until the loopback redirect carries the authorization code."""
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file(user_id)), SCOPES)
    creds = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=True,
        success_message="Pode fechar esta aba e voltar ao AnotAI.",
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    token_file(user_id).write_text(creds.to_json(), encoding="utf-8")


def disconnect(user_id: int) -> None:
    """Forget the token; the cached Drive folder ids are dropped by the caller."""
    token_file(user_id).unlink(missing_ok=True)


def forget_files(user_id: int) -> None:
    """Drop the client json and the token together: the account is going away."""
    client_file(user_id).unlink(missing_ok=True)
    token_file(user_id).unlink(missing_ok=True)
