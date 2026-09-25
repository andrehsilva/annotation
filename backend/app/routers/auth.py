"""Login, logout and the session cookie. The cookie carries the secret; `sessions` carries its hash."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import security
from ..database import get_db
from ..deps import COOKIE_NAME, current_user
from ..models import SessionToken, User, utcnow
from ..schemas import CredentialsIn, PasswordChangeIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_MAX_AGE = int(security.SESSION_TTL.total_seconds())


class Attempts:
    """In-memory slowdown after repeated failures: one process, one small app, no storage."""

    WINDOW = 15 * 60
    LIMIT = 5

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str) -> None:
        now = time.monotonic()
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
def login(payload: CredentialsIn, response: Response, db: Session = Depends(get_db)) -> UserOut:
    attempts.check(payload.email)
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    # Always hash something, so "e-mail não existe" and "senha errada" cost the same.
    stored = user.password_hash if user else security.DUMMY_HASH
    if not security.verify_password(payload.password, stored) or user is None:
        attempts.fail(payload.email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha inválidos")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuário desativado")
    attempts.clear(payload.email)
    token = security.new_session_token()
    now = utcnow()
    db.add(
        SessionToken(
            token_hash=security.hash_token(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + security.SESSION_TTL,
            last_seen_at=now,
        )
    )
    user.last_login_at = now
    db.commit()
    response.set_cookie(
        COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax", path="/"
    )
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute(
            delete(SessionToken).where(SessionToken.token_hash == security.hash_token(token))
        )
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Own password only: the admin resets other people's, this is the self-service door."""
    if not security.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Senha atual incorreta")
    user.password_hash = security.hash_password(payload.new_password)
    keep = security.hash_token(request.cookies.get(COOKIE_NAME, ""))
    db.execute(
        delete(SessionToken).where(
            SessionToken.user_id == user.id, SessionToken.token_hash != keep
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
