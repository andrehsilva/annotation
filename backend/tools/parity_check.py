"""Paridade do contrato HTTP do NotAI: grava um roteiro de requisições e compara a reexecução.

    python tools/parity_check.py record --base http://127.0.0.1:8000 --email voce@exemplo.com
    python tools/parity_check.py replay --base http://127.0.0.1:8000

`record` roda o roteiro contra um servidor **no ar** e grava cada resposta em
`backend/tools/fixtures/*.json`; `replay` roda exatamente o mesmo roteiro (mesmas requisições, ids
em sequência) e compara resposta por resposta. É assim que a troca do SQLite pelo Appwrite é
conferida: as duas execuções passam pelo mesmo contrato e o diff mostra o que mudou.

O roteiro cria o próprio cenário — um caderno `parity-check`, duas notas, blocos, uma tag com nome
sorteado, um vínculo e um upload — e **apaga tudo no fim** (nota, tag e caderno), para não mexer no
dado real do usuário. O que sobra é a linha de mídia sem endpoint de remoção e as linhas de
auditoria no feed, que é aceitável.

## O que o diff normaliza, e por quê

| o que | vira | por quê |
|---|---|---|
| ids que o **próprio roteiro** criou (caderno, nota, bloco, tag, vínculo, arquivo) | `<id:caderno>`, `<id:nota>`, … | o contador do destino é outro; comparar o número exato acusaria divergência em tudo |
| nomes sorteados (a tag) | `<tag:nome>` | o nome é sorteado a cada execução para o delete ser seguro |
| timestamps ISO (`created_at`, `updated_at`, `last_login_at`, `last_seen_at`, `activity_seen_at`, `expires_at`, `synced_at`, `at`) | `<timestamp>` | o relógio avança entre a gravação e a reexecução |
| `unread` (contagem derivada do relógio) | `<contagem>` | é "eventos depois do último visto": qualquer escrita muda |
| `id` dos itens do feed de eventos | `<id:evento>` | o id depende de quantas linhas o log já tinha |

**Nada mais é mascarado, de propósito**: `/api/stats`, `counts`, `notes_count`, `position`,
`notebook_id` das notas reais, títulos, trechos e `size` de mídia são comparados **crus** — é o
sinal de paridade. Por isso a gravação e a reexecução precisam ser feitas em sequência, contra a
mesma base de dados, sem outra escrita no meio (e com o mesmo arquivo de mídia, que é fixo).

Status de cada passo entra na comparação: uma rota que passe a responder 500 ou 404 aparece como
`diff` mesmo que o corpo até se pareça.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TOOLS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TOOLS_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import config  # noqa: E402  — carrega backend/.env (CADERNO_ADMIN_EMAIL/PASSWORD)

FIXTURES_DIR = TOOLS_DIR / "fixtures"
MANIFEST = "manifest.json"
DEFAULT_BASE = "http://127.0.0.1:8000"
TIMEOUT = 15

# O cenário do roteiro: títulos fixos (o diff compara o texto) e conteúdo fixo.
NOTEBOOK = {"title": "parity-check", "description": "caderno temporário de tools/parity_check.py"}
FIRST_NOTE = {"title": "parity-nota", "text": "texto inicial do teste de paridade"}
SECOND_NOTE = {"title": "parity-alvo", "text": "nota alvo do vínculo"}
BLOCK = {"type": "code", "text": "print(1)", "language": "python"}
BLOCK_PATCH = {"text": "print(2)"}
LINK_LABEL = "depende"
TAG_COLOR = "#1f6feb"
QUERY = "parity"
# PNG 1x1 fixo: o hash e o tamanho gravados no replay só valem se os bytes não mudarem.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f9d0000000049454e44ae426082"
)


# ------------------------------------------------------------------ normalização


TIMESTAMP_KEYS = frozenset(
    {
        "created_at",
        "updated_at",
        "synced_at",
        "expires_at",
        "last_login_at",
        "last_seen_at",
        "activity_seen_at",
        "at",
    }
)
# Contagem que anda com o relógio (eventos depois do último "visto"), não com o dado.
CLOCK_COUNTS = frozenset({"unread"})
ID_KEYS = frozenset(
    {"id", "notebook_id", "note_id", "block_id", "tag_id", "source_id", "target_id"}
)


def is_iso(text: str) -> bool:
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


# Ordem determinística para desempatar um id cru que sirva a mais de uma espécie.
TOKEN_PRIORITY = {
    "<id:caderno>": 0,
    "<id:nota>": 1,
    "<id:bloco>": 2,
    "<id:tag>": 3,
    "<id:vinculo>": 4,
    "<id:midia>": 5,
    "<tag:nome>": 6,
    "<id:evento>": 90,
}


@dataclass
class Masks:
    """O que o roteiro descobriu e precisa mascarar antes de comparar.

    `exact` casa o valor inteiro (ids numéricos e nomes); `embedded` casa **dentro** de strings
    (`/media/<uuid>.png`, o nome da tag dentro de um trecho de busca) e só recebe valores longos e
    únicos — um id numérico como "1" trocado como substring corromperia qualquer texto.
    """

    exact: dict[str, set[str]] = field(default_factory=dict)
    embedded: dict[str, str] = field(default_factory=dict)

    def add(self, value: Any, token: str, embed: bool = False) -> None:
        """Guarda **todos** os rótulos de um valor cru.

        Ids do SQLite são por tabela, então `tags.id = 1` e `note_relations.id = 1` coexistem — e no
        Appwrite os contadores também são por família, então a colisão volta a acontecer. Guardar o
        conjunto e resolver por prioridade fixa (`resolve`) é o que mantém gravação e replay no mesmo
        rótulo, independente da ordem em que o roteiro descobriu cada id.
        """
        if value is None or value == "":
            return
        self.exact.setdefault(str(value), set()).add(token)
        if embed:
            self.embedded[str(value)] = token

    def resolve(self, value: Any) -> str | None:
        tokens = self.exact.get(str(value))
        if not tokens:
            return None
        if len(tokens) == 1:
            return next(iter(tokens))
        return min(tokens, key=lambda token: TOKEN_PRIORITY.get(token, 99))


def mask_text(text: str, masks: Masks) -> str:
    for value, token in masks.embedded.items():
        if value in text:
            text = text.replace(value, token)
    return text


def normalize_body(body: Any, masks: Masks) -> Any:
    if isinstance(body, dict):
        return {key: normalize_value(key, value, masks) for key, value in body.items()}
    if isinstance(body, list):
        return [normalize_body(item, masks) for item in body]
    return mask_text(body, masks) if isinstance(body, str) else body


def normalize_value(key: str, value: Any, masks: Masks) -> Any:
    if key in TIMESTAMP_KEYS and isinstance(value, str):
        # Só mascara o que **é** um instante: formato quebrado fica cru e aparece no diff.
        return "<timestamp>" if is_iso(value) else value
    if key in CLOCK_COUNTS and isinstance(value, (int, float)) and not isinstance(value, bool):
        return "<contagem>"
    if key in ID_KEYS or key.endswith("_id"):
        token = masks.resolve(value)
        if token is not None:
            return token
        return mask_text(value, masks) if isinstance(value, str) else value
    if isinstance(value, str):
        return mask_text(value, masks)
    return normalize_body(value, masks)


def diff(recorded: Any, actual: Any, path: str = "") -> list[str]:
    """Lista dos caminhos que divergem, no formato `campo.subcampo: gravado != replay`."""
    if isinstance(recorded, dict) and isinstance(actual, dict):
        lines: list[str] = []
        for key in sorted(set(recorded) | set(actual)):
            where = f"{path}.{key}" if path else key
            if key not in recorded:
                lines.append(f"{where}: só na reexecução")
            elif key not in actual:
                lines.append(f"{where}: só na gravação")
            else:
                lines.extend(diff(recorded[key], actual[key], where))
        return lines
    if isinstance(recorded, list) and isinstance(actual, list):
        if len(recorded) != len(actual):
            return [f"{path or '.'}: {len(recorded)} itens na gravação, {len(actual)} na reexecução"]
        lines = []
        for index, (left, right) in enumerate(zip(recorded, actual)):
            lines.extend(diff(left, right, f"{path}[{index}]"))
        return lines
    if isinstance(recorded, bool) != isinstance(actual, bool) or recorded != actual:
        return [f"{path or '.'}: {short(recorded)} != {short(actual)}"]
    return []


def short(value: Any, limit: int = 90) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ------------------------------------------------------------------ http


class Api:
    """HTTP cru com o cookie da sessão (`urllib`): o projeto não tem cliente HTTP próprio."""

    def __init__(self, base: str, email: str, password: str, timeout: int = TIMEOUT) -> None:
        self.base = base.rstrip("/")
        self.email = email
        self.password = password
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.session = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        # Sem cookie: é este opener que prova o 401 da rota autenticada.
        self.anonymous = urllib.request.build_opener()

    def send(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        anonymous: bool = False,
    ) -> tuple[int, bytes, str]:
        request = urllib.request.Request(self.base + path, data=body, method=method)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        opener = self.anonymous if anonymous else self.session
        try:
            with opener.open(request, timeout=self.timeout) as response:
                return response.status, response.read(), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers.get("Content-Type", "")

    def json_call(
        self,
        method: str,
        path: str,
        payload: Any = None,
        anonymous: bool = False,
    ) -> tuple[int, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {} if body is None else {"Content-Type": "application/json"}
        status, raw, _ = self.send(method, path, body, headers, anonymous)
        return status, decode(raw)

    def upload(self, path: str, filename: str, content_type: str, data: bytes) -> tuple[int, Any]:
        boundary = "----parity-check-boundary"
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        body = head + data + f"\r\n--{boundary}--\r\n".encode()
        status, raw, _ = self.send(
            "POST", path, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        return status, decode(raw)


def decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw.decode("utf-8", "replace")}


def preflight(api: Api) -> None:
    """Falha com mensagem clara quando não há servidor no ar: sem ele não há o que gravar."""
    try:
        status, body = api.json_call("GET", "/api/health")
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise SystemExit(
            f"nenhum servidor respondeu em {api.base} ({reason}).\n"
            "Suba o BFF (`uvicorn app.main:app --port 8000`) ou aponte --base para o servidor certo."
        ) from error
    if status != 200 or not isinstance(body, dict) or body.get("status") != "ok":
        raise SystemExit(f"{api.base}/api/health respondeu {status} {short(body)}")


# ------------------------------------------------------------------ roteiro


@dataclass(frozen=True)
class Step:
    name: str
    expect: int
    call: Callable[["Run"], tuple[int, Any]]
    kind: str = "json"


class Run:
    """Estado do roteiro: ids descobertos, o que precisa ser mascarado e o cookie da sessão."""

    def __init__(self, api: Api) -> None:
        self.api = api
        self.tag_name = f"parity-{uuid.uuid4().hex[:8]}"
        self.ctx: dict[str, Any] = {}
        self.masks = Masks()

    def mask(self, value: Any, token: str, embed: bool = False) -> None:
        self.masks.add(value, token, embed=embed)

    def mask_note(self, body: Any, token: str = "<id:nota>") -> None:
        """Registra o id da nota e o dos blocos/tags/vínculos que vierem junto (o agregado)."""
        if not isinstance(body, dict):
            return
        self.mask(body.get("id"), token)
        for block in body.get("blocks") or []:
            self.mask(block.get("id"), "<id:bloco>")
        for tag in body.get("tags") or []:
            self.mask(tag.get("id"), "<id:tag>")
        for relation in body.get("relations") or []:
            self.mask(relation.get("id"), "<id:vinculo>")
            self.mask((relation.get("other") or {}).get("id"), "<id:nota>")


def step_health(run: Run) -> tuple[int, Any]:
    return run.api.json_call("GET", "/api/health")


def step_login(run: Run) -> tuple[int, Any]:
    return run.api.json_call(
        "POST", "/api/auth/login", {"email": run.api.email, "password": run.api.password}
    )


def step_me(run: Run) -> tuple[int, Any]:
    return run.api.json_call("GET", "/api/auth/me")


def step_me_without_cookie(run: Run) -> tuple[int, Any]:
    """401 sem sessão: a rota autenticada não pode responder nada sem o cookie."""
    return run.api.json_call("GET", "/api/auth/me", anonymous=True)


def step_stats_baseline(run: Run) -> tuple[int, Any]:
    return run.api.json_call("GET", "/api/stats")


def step_create_notebook(run: Run) -> tuple[int, Any]:
    status, body = run.api.json_call("POST", "/api/notebooks", NOTEBOOK)
    if isinstance(body, dict):
        run.mask(body.get("id"), "<id:caderno>")
        run.ctx["notebook"] = body.get("id")
        # o caderno nasce com uma nota vazia: o id dela é do destino, não comparável
        for note in body.get("notes") or []:
            run.mask(note.get("id"), "<id:nota>")
            for block in note.get("blocks") or []:
                run.mask(block.get("id"), "<id:bloco>")
    return status, body


def step_create_note(run: Run) -> tuple[int, Any]:
    status, body = run.api.json_call(
        "POST", f"/api/notebooks/{run.ctx['notebook']}/notes", FIRST_NOTE
    )
    run.mask_note(body)
    if isinstance(body, dict):
        run.ctx["note"] = body.get("id")
        blocks = body.get("blocks") or []
        if blocks:
            run.ctx["block"] = blocks[0].get("id")
    return status, body


def step_create_block(run: Run) -> tuple[int, Any]:
    status, body = run.api.json_call("POST", f"/api/notes/{run.ctx['note']}/blocks", BLOCK)
    if isinstance(body, dict):
        run.mask(body.get("id"), "<id:bloco>")
        run.ctx["second_block"] = body.get("id")
    return status, body


def step_patch_block(run: Run) -> tuple[int, Any]:
    return run.api.json_call("PATCH", f"/api/blocks/{run.ctx['second_block']}", BLOCK_PATCH)


def step_list_blocks(run: Run) -> tuple[int, Any]:
    return run.api.json_call("GET", "/api/blocks?type=code&limit=5")


def step_reorder_blocks(run: Run) -> tuple[int, Any]:
    ordered = [run.ctx["second_block"], run.ctx["block"]]
    return run.api.json_call("POST", f"/api/notes/{run.ctx['note']}/blocks/reorder",
                             {"block_ids": ordered})


def step_create_tag(run: Run) -> tuple[int, Any]:
    status, body = run.api.json_call("POST", "/api/tags", {"name": run.tag_name, "color": TAG_COLOR})
    # Sorteado a cada execução e citado dentro de trechos/títulos: casa também como substring.
    run.mask(run.tag_name, "<tag:nome>", embed=True)
    if isinstance(body, dict):
        run.mask(body.get("id"), "<id:tag>")
        run.ctx["tag"] = body.get("id")
    return status, body


def step_attach_tag(run: Run) -> tuple[int, Any]:
    status, body = run.api.json_call("POST", f"/api/notes/{run.ctx['note']}/tags/{run.ctx['tag']}")
    run.mask_note(body)
    return status, body


def step_list_tags(run: Run) -> tuple[int, Any]:
    return run.api.json_call("GET", "/api/tags")


def step_create_target_note(run: Run) -> tuple[int, Any]:
    status, body = run.api.json_call(
        "POST", f"/api/notebooks/{run.ctx['notebook']}/notes", SECOND_NOTE
    )
    run.mask_note(body)
    if isinstance(body, dict):
        run.ctx["target"] = body.get("id")
    return status, body


def step_create_relation(run: Run) -> tuple[int, Any]:
    status, body = run.api.json_call(
        "POST",
        f"/api/notes/{run.ctx['note']}/relations",
        {"target_id": run.ctx["target"], "label": LINK_LABEL},
    )
    for relation in (body or {}).get("relations") or []:
        run.mask(relation.get("id"), "<id:vinculo>")
        run.mask((relation.get("other") or {}).get("id"), "<id:nota>")
    return status, body


def step_related(run: Run) -> tuple[int, Any]:
    status, body = run.api.json_call("GET", f"/api/notes/{run.ctx['note']}/related")
    for relation in (body or {}).get("relations") or []:
        run.mask(relation.get("id"), "<id:vinculo>")
        run.mask((relation.get("other") or {}).get("id"), "<id:nota>")
    for note in (body or {}).get("mentions") or []:
        run.mask(note.get("id"), "<id:nota>")
    for backlink in (body or {}).get("backlinks") or []:
        run.mask((backlink.get("note") or {}).get("id"), "<id:nota>")
        run.mask(backlink.get("block_id"), "<id:bloco>")
    return status, body


def step_get_note(run: Run) -> tuple[int, Any]:
    status, body = run.api.json_call("GET", f"/api/notes/{run.ctx['note']}")
    run.mask_note(body)
    return status, body


def step_list_notes(run: Run) -> tuple[int, Any]:
    return run.api.json_call("GET", f"/api/notes?q={QUERY}&limit=10")


def step_search(run: Run) -> tuple[int, Any]:
    return run.api.json_call("GET", f"/api/search?q={QUERY}&limit=10")


def step_stats(run: Run) -> tuple[int, Any]:
    return run.api.json_call("GET", "/api/stats")


def step_events(run: Run) -> tuple[int, Any]:
    status, body = run.api.json_call("GET", "/api/events?limit=5")
    # O id do evento vem do log de auditoria e anda com qualquer escrita: mascarado aqui, onde o
    # contexto é conhecido (o normalizador não sabe distinguir este `id` dos outros).
    if isinstance(body, dict):
        for item in body.get("items") or []:
            if isinstance(item, dict):
                item["id"] = "<id:evento>"
    return status, body


def step_media_upload(run: Run) -> tuple[int, Any]:
    status, body = run.api.upload("/api/media", "parity.png", "image/png", PNG)
    if isinstance(body, dict):
        url = str(body.get("url") or "")
        # O nome do arquivo é um uuid e aparece dentro da URL: casa como substring.
        run.mask(url.rsplit("/", 1)[-1], "<id:midia>", embed=True)
        run.ctx["media_url"] = url
    return status, body


def step_media_get(run: Run) -> tuple[int, Any]:
    url = run.ctx.get("media_url")
    if not url:
        return 0, {"pulado": "o upload não devolveu URL"}
    status, raw, content_type = run.api.send("GET", url)
    return status, {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "content_type": content_type.split(";")[0].strip(),
    }


def step_media_missing(run: Run) -> tuple[int, Any]:
    return run.api.json_call("GET", "/media/parity-inexistente.png")


def step_note_missing(run: Run) -> tuple[int, Any]:
    """404 para id que não existe — diferente do 404 para recurso de outra conta."""
    return run.api.json_call("GET", "/api/notes/99999999")


def step_delete_note(run: Run) -> tuple[int, Any]:
    if run.ctx.get("note") is None:
        return 0, {"pulado": "a nota não chegou a ser criada"}
    return run.api.json_call("DELETE", f"/api/notes/{run.ctx['note']}")


def step_delete_tag(run: Run) -> tuple[int, Any]:
    if run.ctx.get("tag") is None:
        return 0, {"pulado": "a tag não chegou a ser criada"}
    return run.api.json_call("DELETE", f"/api/tags/{run.ctx['tag']}")


def step_delete_notebook(run: Run) -> tuple[int, Any]:
    if run.ctx.get("notebook") is None:
        return 0, {"pulado": "o caderno não chegou a ser criado"}
    return run.api.json_call("DELETE", f"/api/notebooks/{run.ctx['notebook']}")


def step_stats_after(run: Run) -> tuple[int, Any]:
    """Depois da limpeza os totais voltam ao ponto de partida: prova que nada ficou órfão."""
    return run.api.json_call("GET", "/api/stats")


STEPS: tuple[Step, ...] = (
    Step("health", 200, step_health),
    Step("login", 200, step_login),
    Step("me", 200, step_me),
    Step("me_sem_cookie", 401, step_me_without_cookie),
    Step("stats_inicial", 200, step_stats_baseline),
    Step("criar_caderno", 201, step_create_notebook),
    Step("criar_nota", 201, step_create_note),
    Step("criar_bloco", 201, step_create_block),
    Step("editar_bloco", 200, step_patch_block),
    Step("listar_blocos", 200, step_list_blocks),
    Step("reordenar_blocos", 200, step_reorder_blocks),
    Step("criar_tag", 201, step_create_tag),
    Step("aplicar_tag", 200, step_attach_tag),
    Step("listar_tags", 200, step_list_tags),
    Step("criar_nota_alvo", 201, step_create_target_note),
    Step("criar_vinculo", 200, step_create_relation),
    Step("relacionadas", 200, step_related),
    Step("ler_nota", 200, step_get_note),
    Step("listar_notas", 200, step_list_notes),
    Step("busca", 200, step_search),
    Step("stats", 200, step_stats),
    Step("eventos", 200, step_events),
    Step("subir_midia", 201, step_media_upload),
    Step("ler_midia", 200, step_media_get, kind="bytes"),
    Step("midia_inexistente", 404, step_media_missing),
    Step("nota_inexistente", 404, step_note_missing),
    Step("apagar_nota", 204, step_delete_note),
    Step("apagar_tag", 204, step_delete_tag),
    Step("apagar_caderno", 204, step_delete_notebook),
    Step("stats_depois", 200, step_stats_after),
)


def execute(run: Run) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for step in STEPS:
        try:
            status, body = step.call(run)
        except KeyError as missing:
            # Um passo anterior falhou e não deixou o id de que este precisa: registra a falha e
            # segue, para a limpeza do que chegou a ser criado ainda rodar.
            status, body = 0, {"pulado": f"o passo anterior não forneceu {missing}"}
        except urllib.error.URLError as error:
            raise SystemExit(f"{step.name}: o servidor caiu no meio do roteiro ({error})") from error
        records.append({"step": step.name, "kind": step.kind, "status": status, "body": body})
    return records


# ------------------------------------------------------------------ fixtures


def fixture_name(index: int, step: str) -> str:
    return f"{index:02d}-{step.replace('_', '-')}.json"


def normalize_records(records: list[dict[str, Any]], masks: Masks) -> list[dict[str, Any]]:
    return [{**record, "body": normalize_body(record["body"], masks)} for record in records]


def write_fixtures(directory: Path, api: Api, records: list[dict[str, Any]], masks: Masks) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for stale in sorted(directory.glob("*.json")):
        stale.unlink()
    by_token: dict[str, list[str]] = {}
    for value, tokens in masks.exact.items():
        for token in tokens:
            by_token.setdefault(token, []).append(value)
    manifest: dict[str, Any] = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base": api.base,
        "steps": [],
        "masked": {token: sorted(values) for token, values in sorted(by_token.items())},
    }
    for index, record in enumerate(records, start=1):
        name = fixture_name(index, str(record["step"]))
        (directory / name).write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest["steps"].append(
            {"index": index, "name": record["step"], "file": name, "status": record["status"]}
        )
    (directory / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_fixtures(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = directory / MANIFEST
    if not manifest_path.is_file():
        raise SystemExit(
            f"não há fixtures em {directory}.\n"
            "Rode primeiro `python tools/parity_check.py record --base <url>` com o servidor no ar."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = [
        entry["file"]
        for entry in manifest["steps"]
        if not (directory / entry["file"]).is_file()
    ]
    if missing:
        raise SystemExit(f"fixtures incompletas em {directory}: falta {', '.join(missing)}")
    records = [
        json.loads((directory / entry["file"]).read_text(encoding="utf-8"))
        for entry in manifest["steps"]
    ]
    return manifest, records


# ------------------------------------------------------------------ relatório


MASK_NOTE = (
    "[mask] ids criados pelo roteiro (caderno, nota, bloco, tag, vínculo, mídia) → <id:*>; "
    "nome sorteado da tag → <tag:nome>; timestamps ISO (created_at, updated_at, last_login_at, "
    "last_seen_at, activity_seen_at, expires_at, synced_at, at) → <timestamp>; `unread` → "
    "<contagem>; id dos eventos → <id:evento>. Contagens de /api/stats, counts, notes_count e "
    "size de mídia ficam **cruas**: são o sinal de paridade."
)


def report(rows: list[tuple[Step, str, list[str]]]) -> None:
    for step, mark, lines in rows:
        print(f"  {mark:<4} {step.name}")
        for line in lines[:4]:
            print(f"       - {line}")
        if len(lines) > 4:
            print(f"       - (+{len(lines) - 4} divergências)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parity_check.py",
        description=(
            "Roteiro de requisições contra um servidor no ar: `record` grava as respostas em "
            f"{FIXTURES_DIR}, `replay` reexecuta e compara."
        ),
        epilog=MASK_NOTE,
    )
    modes = parser.add_subparsers(dest="mode", required=True)
    for name, text in (
        ("record", "grava as respostas do roteiro em backend/tools/fixtures/*.json"),
        ("replay", "reexecuta o roteiro e compara com as fixtures gravadas"),
    ):
        sub = modes.add_parser(name, help=text, description=text)
        sub.add_argument("--base", default=DEFAULT_BASE, help=f"raiz do servidor ({DEFAULT_BASE})")
        sub.add_argument(
            "--email",
            default=os.environ.get("CADERNO_ADMIN_EMAIL", ""),
            help="login do usuário de teste (padrão: CADERNO_ADMIN_EMAIL)",
        )
        sub.add_argument(
            "--password",
            default=os.environ.get("CADERNO_ADMIN_PASSWORD", ""),
            help="senha do usuário de teste (padrão: CADERNO_ADMIN_PASSWORD)",
        )
        sub.add_argument("--fixtures", default=str(FIXTURES_DIR), help="diretório das fixtures")
        sub.add_argument("--timeout", type=int, default=TIMEOUT, help="segundos por requisição")
    args = parser.parse_args(argv)

    if not args.email or not args.password:
        raise SystemExit(
            "informe --email/--password (ou defina CADERNO_ADMIN_EMAIL e CADERNO_ADMIN_PASSWORD "
            "em backend/.env): o roteiro precisa entrar no app."
        )

    directory = Path(args.fixtures)
    recorded: list[dict[str, Any]] = []
    if args.mode == "replay":
        manifest, recorded = load_fixtures(directory)
        if len(recorded) != len(STEPS):
            raise SystemExit(
                f"as fixtures em {directory} têm {len(recorded)} passos e o roteiro tem "
                f"{len(STEPS)}: regrave com `record`."
            )
        print(f"[replay] {args.base} contra fixtures de {manifest['recorded_at']} ({manifest['base']})")
    else:
        print(f"[record] {args.base} → {directory}")

    api = Api(args.base, args.email, args.password, args.timeout)
    preflight(api)
    run = Run(api)
    records = normalize_records(execute(run), run.masks)

    if args.mode == "record":
        broken = [
            step.name
            for step, record in zip(STEPS, records)
            if record["status"] != step.expect
        ]
        for step, record in zip(STEPS, records):
            if record["status"] != step.expect:
                print(
                    f"  ERRO {step.name}: esperado {step.expect}, veio {record['status']} "
                    f"{short(record['body'])}"
                )
        write_fixtures(directory, api, records, run.masks)
        print(f"[record] {len(records)} passos gravados em {directory}")
        print(MASK_NOTE)
        if broken:
            print(f"[erro] o servidor não respondeu o esperado em: {', '.join(broken)}")
            return 1
        return 0

    rows: list[tuple[Step, str, list[str]]] = []
    for step, saved, fresh in zip(STEPS, recorded, records):
        lines = diff(saved, fresh)
        if saved.get("step") != step.name:
            lines.insert(0, f"passo gravado como {saved.get('step')!r} e não {step.name!r}")
        rows.append((step, "ok" if not lines else "diff", lines))
    report(rows)
    print(MASK_NOTE)
    diverged = [step.name for step, mark, _ in rows if mark == "diff"]
    if diverged:
        print(f"[diff] {len(diverged)} de {len(rows)} passos divergiram: {', '.join(diverged)}")
        return 1
    print(f"[ok] {len(rows)} passos idênticos às fixtures gravadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
