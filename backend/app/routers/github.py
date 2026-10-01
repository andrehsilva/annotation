"""Publicar a nota como gist no GitHub — o token, o status e a publicação em si.

O token é **pessoal**: cada conta conecta o seu, e o que sai daqui vai para o GitHub de quem
publicou. Quem publica é o **dono** da nota: publicar manda o conteúdo para fora do app, e essa
decisão é de quem responde por ele (como compartilhar).
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from .. import deps, events, github, markdown, services
from ..schemas import GistOut, GithubStatus
from ..store import documents, store
from ..store.client import Store, equal

router = APIRouter(prefix="/api/github", tags=["github"])


class TokenIn(BaseModel):
    token: str = Field(min_length=8, max_length=200)


def _token(user: documents.Row) -> str:
    """O token da conta; sem ele a publicação nem começa."""
    token = (user.get("github_token") or "").strip()
    if not token:
        raise HTTPException(status.HTTP_409_CONFLICT, github.NOT_CONNECTED)
    return token


def _mirror(db: Store, user_id: int, note_id: int) -> documents.Row | None:
    return documents.get("gist_files", f"{user_id}_{note_id}")


def _note_blocks(db: Store, user_id: int, note_id: int) -> list[documents.Row]:
    photo = services.snapshot(db, user_id)
    return sorted(
        (block for block in photo["blocks"] if block.note_id == note_id),
        key=lambda block: (block.position, block.id),
    )


def _note_tags(db: Store, user_id: int, note_id: int) -> list[str]:
    photo = services.snapshot(db, user_id)
    tagged = {link.tag_id for link in photo["note_tags"] if link.note_id == note_id}
    return [tag.name for tag in photo["tags"] if tag.id in tagged]


def _content(db: Store, user_id: int, note: documents.Row) -> tuple[str, str]:
    """O markdown da nota e o checksum dele: é o checksum que diz se o gist precisa subir de novo."""
    body = markdown.note_markdown(note, _note_blocks(db, user_id, note.id), tags=_note_tags(db, user_id, note.id))
    return body, hashlib.sha256(body.encode("utf-8")).hexdigest()


@router.get("/status", response_model=GithubStatus)
def get_status(
    user: documents.Row = Depends(deps.current_user), db: Store = Depends(deps.get_db)
) -> GithubStatus:
    """Se a conta já tem token e o que saiu daqui (o link de cada nota publicada)."""
    published = list(db.page("gist_files", [equal("user_id", str(user.id))]))
    return GithubStatus(
        connected=bool((user.get("github_token") or "").strip()),
        published=[
            {"note_id": documents.to_int(row["note_id"]), "url": row.get("gist_url") or ""}
            for row in published
        ],
    )


@router.put("/token", response_model=GithubStatus)
def set_token(
    payload: TokenIn,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> GithubStatus:
    """Guarda o token pessoal — depois de conferir com o GitHub que ele vale.

    A linha é de servidor (`owner_id=None`): só a API key lê o token, e ele nunca volta na resposta.
    """
    token = payload.token.strip()
    try:
        github.whoami(token)
    except github.GithubError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    documents.change("users", user.id, {"github_token": token}, owner_id=None)
    with store().transaction() as tx:
        store().stage(tx, [events.operation(user.id, "connected", "github", "token salvo")])
    return get_status(user=documents.get("users", user.id), db=db)


@router.delete("/token", response_model=GithubStatus)
def forget_token(
    user: documents.Row = Depends(deps.current_user), db: Store = Depends(deps.get_db)
) -> GithubStatus:
    """Esquece o token; **nada é apagado no GitHub** (os gists continuam lá, como o usuário os deixou)."""
    # String vazia, não `None`: o `write` descarta valores nulos e a atualização ficaria sem dado
    # nenhum (o Appwrite recusa). Vazio é "sem token" para tudo o que lê esta coluna.
    documents.change("users", user.id, {"github_token": ""}, owner_id=None)
    with store().transaction() as tx:
        store().stage(tx, [events.operation(user.id, "disconnected", "github", "token esquecido")])
    return get_status(user=documents.get("users", user.id), db=db)


@router.post("/notes/{note_id}", response_model=GistOut)
def publish_note(
    note_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> GistOut:
    """Publica a nota (ou atualiza o gist dela) e devolve o link.

    Chama o GitHub **antes** de gravar o espelho: se a chamada falhar, nada fica meio publicado. O
    `checksum` do markdown guarda o que foi enviado, então publicar de novo sem mudança devolve o
    mesmo link sem tocar no gist.
    """
    note = deps.note_for(db, user, note_id, "owner")
    token = _token(user)
    body, checksum = _content(db, user.id, note)
    mirror = _mirror(db, user.id, note_id)
    filename = markdown.gist_filename(note.title, note.id)
    if mirror is not None and mirror.get("checksum") == checksum:
        return GistOut(url=mirror.get("gist_url") or "", updated=False)
    try:
        result = github.publish(
            token,
            filename,
            body,
            description=note.title.strip() or "Nota do AnotAI",
            gist_id=(mirror.get("gist_id") or "") if mirror is not None else "",
        )
    except github.GithubError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error

    row_id = f"{user.id}_{note_id}"
    data = {
        "user_id": str(user.id),
        "note_id": str(note_id),
        "gist_id": result["id"],
        "gist_url": result["url"],
        "checksum": checksum,
        "published_at": documents.now(),
    }
    if mirror is None:
        documents.write("gist_files", row_id, data, owner_id=None)
    else:
        documents.change("gist_files", row_id, data, owner_id=None)
    with store().transaction() as tx:
        store().stage(
            tx, [events.operation(user.id, "published", "github", note.title or "nota", note_id=note.id)]
        )
    return GistOut(url=result["url"], updated=mirror is not None)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def unpublish_note(
    note_id: int,
    user: documents.Row = Depends(deps.current_user),
    db: Store = Depends(deps.get_db),
) -> Response:
    """Apaga o gist no GitHub e esquece o espelho."""
    deps.note_for(db, user, note_id, "owner")
    mirror = _mirror(db, user.id, note_id)
    if mirror is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    try:
        github.unpublish(_token(user), mirror.get("gist_id") or "")
    except github.GithubError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    documents.remove("gist_files", mirror.row_id)
    with store().transaction() as tx:
        store().stage(tx, [events.operation(user.id, "unpublished", "github", "gist apagado", note_id=note_id)])
    return Response(status_code=status.HTTP_204_NO_CONTENT)

