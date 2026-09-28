"""Google Drive OAuth for the export: one client/token pair per user, scope `drive.file`.

`drive.file` only sees files this app created, so the export owns everything under `NotAI/` and
never touches the rest of the user's Drive.

A conexão é em dois passos, porque o servidor não tem navegador: `auth_url` devolve a tela de
consentimento para o usuário abrir, e `finish` troca o `code` que ele cola de volta pelo token.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google.auth.exceptions import RefreshError, TransportError
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


# O retorno do OAuth é loopback (`http://localhost:<porta>/`), o único `redirect_uri` que um cliente
# "Aplicativo para computador" aceita. Ninguém escuta nessa porta do lado do usuário — nem aqui (o app
# roda num contêiner) —, então o navegador erra ao voltar e é a **barra de endereço** que guarda o
# `code`: é ela que a tela pede de volta. O fluxo antigo (`run_local_server`) só funcionava com
# navegador na mesma máquina do servidor, e por isso a conexão quebrava em produção.
LOOPBACK = "http://localhost:8765/"
AUTHORIZE_TTL = 15 * 60  # a janela em que o `state` entregue à tela ainda vale


class BadCallback(Exception):
    """O que foi colado não é um retorno de autorização, ou o Google recusou o código."""


class ExchangeUnavailable(Exception):
    """A troca do código pelo token não chegou ao Google."""


def _flow(user_id: int) -> InstalledAppFlow:
    """O mesmo `redirect_uri` na autorização e na troca: o Google confere que são iguais."""
    return InstalledAppFlow.from_client_secrets_file(
        str(client_file(user_id)), SCOPES, redirect_uri=LOOPBACK
    )


def auth_url(user_id: int, state: str) -> tuple[str, str]:
    """A URL de consentimento e o `code_verifier` (PKCE) que ela embutiu.

    O PKCE é gerado por tentativa e a troca acontece noutra chamada, com outro objeto de flow: sem
    guardar o verifier aqui, o Google recusaria a troca por `code_challenge` não bater. `offline` com
    `prompt=consent` é o que garante o `refresh_token` — sem ele o export morreria em uma hora.
    """
    flow = _flow(user_id)
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
    return url, flow.code_verifier


def parse_callback(value: str) -> tuple[str, str]:
    """`(code, state)` do que o usuário colou: a URL de retorno inteira ou só o código."""
    text = value.strip()
    if not text:
        raise BadCallback("Cole a URL da página de retorno (ou só o código).")
    if not text.startswith("http"):
        return text, ""
    query = parse_qs(urlparse(text).query)
    refused = (query.get("error") or [""])[0]
    if refused:
        raise BadCallback(f"O Google recusou a autorização: {refused}")
    code = (query.get("code") or [""])[0]
    if not code:
        raise BadCallback("Essa URL é a da tela de autorização, não a do retorno com o código.")
    return code, (query.get("state") or [""])[0]


def finish(user_id: int, callback: str, state: str, verifier: str) -> None:
    """Troca o `code` colado pelo token e grava o token desta conta.

    O `state` só é conferido quando veio junto: o `code` já é casado com o `client_id` desta conta (a
    troca usa o secret dela), então quem não tem o arquivo do cliente não consegue forjar um.
    """
    code, got = parse_callback(callback)
    if got and got != state:
        raise BadCallback("Este retorno é de outra tentativa de conexão. Comece de novo.")
    flow = _flow(user_id)
    flow.code_verifier = verifier  # o PKCE é da tentativa que gerou a URL, não deste objeto
    try:
        flow.fetch_token(code=code)
    except (TransportError, OSError) as error:
        raise ExchangeUnavailable(str(error)) from error
    except Exception as error:  # noqa: BLE001 — a recusa vem do oauthlib ou do requests
        raise BadCallback(f"O Google recusou o código ({error})") from error
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    token_file(user_id).write_text(flow.credentials.to_json(), encoding="utf-8")


def disconnect(user_id: int) -> None:
    """Forget the token; the cached Drive folder ids are dropped by the caller."""
    token_file(user_id).unlink(missing_ok=True)


def forget_files(user_id: int) -> None:
    """Drop the client json and the token together: the account is going away."""
    client_file(user_id).unlink(missing_ok=True)
    token_file(user_id).unlink(missing_ok=True)
