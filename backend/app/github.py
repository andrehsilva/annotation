"""Publicar a nota como **gist** no GitHub, com o token pessoal de quem publica.

O app fala com a API do GitHub direto (`urllib`, sem dependência nova): valida o token em `/user`,
cria o gist em `POST /gists` e atualiza em `PATCH /gists/{id}`. O conteúdo é o markdown da nota
(`markdown.note_markdown`), que é o que o GitHub renderiza com realce de sintaxe.

Gist é **público ou secreto**, não privado: secreto quer dizer *não listado* — quem tem o link vê.
Quem decide publicar é o dono da nota, e o token é dele (cada conta publica na própria conta).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

API = "https://api.github.com"
TIMEOUT = 20
# O GitHub exige um User-Agent; sem ele a resposta é 403.
USER_AGENT = "NotAI"

# O que o GitHub responde quando o token não vale, não tem escopo de gist, ou o limite estourou.
NOT_CONNECTED = "Nenhum token do GitHub salvo"
BAD_TOKEN = "O GitHub recusou o token: confira se ele existe e tem o escopo `gist`"
GONE = "O gist não existe mais no GitHub"
RATE_LIMITED = "O GitHub pediu calma (limite de requisições): tente de novo em alguns minutos"


class GithubError(Exception):
    """Falha de conversa com o GitHub, já em português e sem o token no meio."""


def _call(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Uma chamada à API do GitHub. O token vai no cabeçalho e nunca aparece em mensagem."""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{API}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise GithubError(BAD_TOKEN) from error
        if error.code == 404:
            raise GithubError(GONE) from error
        if error.code == 403:
            raise GithubError(RATE_LIMITED) from error
        if error.code == 422:
            raise GithubError("O GitHub recusou o conteúdo do gist") from error
        raise GithubError(f"O GitHub respondeu {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise GithubError("Não deu para falar com o GitHub agora") from error
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise GithubError("O GitHub devolveu algo que não é JSON") from error


def whoami(token: str) -> str:
    """O login de quem é o token — é o que a tela mostra ao conectá-lo."""
    data = _call("GET", "/user", token)
    login = str(data.get("login") or "")
    if not login:
        raise GithubError(BAD_TOKEN)
    return login


def publish(token: str, filename: str, content: str, description: str, gist_id: str = "") -> dict[str, str]:
    """Cria o gist ou atualiza o que já existe; devolve `id` e `url` (o link é o `html_url`)."""
    payload = {
        "description": description,
        "files": {filename: {"content": content}},
    }
    if gist_id:
        data = _call("PATCH", f"/gists/{gist_id}", token, payload)
    else:
        data = _call("POST", "/gists", token, {**payload, "public": False})
    url = str(data.get("html_url") or "")
    new_id = str(data.get("id") or gist_id)
    if not url or not new_id:
        raise GithubError("O GitHub não devolveu o link do gist")
    return {"id": new_id, "url": url}


def unpublish(token: str, gist_id: str) -> None:
    """Apaga o gist no GitHub; um gist que já não existe conta como sucesso."""
    try:
        _call("DELETE", f"/gists/{gist_id}", token)
    except GithubError as error:
        if GONE not in str(error):
            raise
