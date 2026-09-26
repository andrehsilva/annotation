"""Login, logout and the session cookie. The cookie carries the secret; `sessions` carries its hash."""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .. import security, values
from ..deps import COOKIE_NAME, current_user, get_db
from ..schemas import CredentialsIn, PasswordChangeIn, UserOut
from ..store import Store, documents, equal
from ..store.documents import Row

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_MAX_AGE = int(security.SESSION_TTL.total_seconds())
# Em produção o cookie só viaja em HTTPS; em dev (http://localhost) o padrão desligado deixa entrar.
COOKIE_SECURE = os.environ.get("CADERNO_COOKIE_SECURE", "").strip().lower() in ("1", "true")


class Attempts:
    """In-memory slowdown after repeated failures: one process, one small app, no storage.

    A chave é o e-mail, mas a memória tem teto: sem poda, um anônimo que varia o e-mail a cada
    tentativa cria uma entrada por requisição até derrubar o processo. `KEYS_MAX` mantém o
    dicionário limitado e a poda por janela roda a cada `check`.
    """

    WINDOW = 15 * 60
    LIMIT = 5
    KEYS_MAX = 5000

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}

    def _prune(self, now: float) -> None:
        if len(self._hits) <= self.KEYS_MAX:
            return
        for key in [k for k, hits in self._hits.items() if not hits or now - hits[-1] > self.WINDOW]:
            self._hits.pop(key, None)
        # Ainda grande (tudo dentro da janela): descarta os mais antigos até caber no teto.
        while len(self._hits) > self.KEYS_MAX:
            self._hits.pop(next(iter(self._hits)), None)

    def check(self, key: str) -> None:
        now = time.monotonic()
        self._prune(now)
        recent = [hit for hit in self._hits.get(key, []) if now - hit < self.WINDOW]
        self._hits[key] = recent
        if len(recent) >= self.LIMIT:
            wait = int(self.WINDOW - (now - recent[0])) + 1
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Tentativas demais. Tente de novo em alguns minutos.",
                headers={"Retry-After": str(wait)},
            )

    def fail(self, key: str) -> None:
        self._hits.setdefault(key, []).append(time.monotonic())

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)


attempts = Attempts()


@router.post("/login", response_model=UserOut)
def login(payload: CredentialsIn, response: Response, db: Store = Depends(get_db)) -> UserOut:
    attempts.check(payload.email)
    user = documents.user_by_email(payload.email)
    # Always hash something, so "e-mail não existe" and "senha errada" cost the same.
    stored = user.password_hash if user else security.DUMMY_HASH
    if not security.verify_password(payload.password, stored) or user is None:
        attempts.fail(payload.email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha inválidos")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuário desativado")
    attempts.clear(payload.email)
    token = security.new_session_token()
    now = values.utcnow()
    # Linha de servidor: sem permissão de cliente, só a API key lê o hash da sessão.
    documents.write(
        "sessions",
        documents.session_id(security.hash_token(token)),
        {
            "user_id": str(user.id),
            "created_at": now,
            "expires_at": now + security.SESSION_TTL,
            "last_seen_at": now,
        },
        owner_id=None,
    )
    user = documents.change("users", user.id, {"last_login_at": now}, owner_id=None)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Store = Depends(get_db)) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.delete("sessions", documents.session_id(security.hash_token(token)))
    response.delete_cookie(COOKIE_NAME, path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: Row = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeIn,
    request: Request,
    user: Row = Depends(current_user),
    db: Store = Depends(get_db),
) -> Response:
    """Own password only: the admin resets other people's, this is the self-service door."""
    if not security.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Senha atual incorreta")
    documents.change(
        "users", user.id, {"password_hash": security.hash_password(payload.new_password)}, owner_id=None
    )
    # A sessão atual fica: o rowId das outras é o hash de cada token, então o filtro é aqui.
    # `session_id` trunca o sha256 em 32 chars (o rowId do Appwrite aceita 36): comparar com o hash
    # inteiro nunca casava e a troca de senha derrubava também a sessão de quem trocou.
    keep = documents.session_id(security.hash_token(request.cookies.get(COOKIE_NAME, "")))
    for session in documents.all_rows("sessions", [equal("user_id", str(user.id))]):
        if session.row_id != keep:
            db.delete("sessions", session.row_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
