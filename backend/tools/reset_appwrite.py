"""Zera a instância do NotAI: tabelas, bucket, contadores e sessões; recria só o admin.

    python tools/reset_appwrite.py --dry-run          # mostra o que existe e o que sairia
    python tools/reset_appwrite.py --yes --email x@y  # apaga e recria o admin

O `--yes` é obrigatório de propósito: isto apaga **tudo** do database e do bucket do app — inclusive
mídia — e reinicia os contadores de id (a próxima linha de cada família nasce com id 1). As sessões
caem junto, então quem estava logado entra de novo.

A senha do admin:
* `--password <texto>` usa a que você passar;
* sem isso, reaproveita o hash da linha atual, se ela existir (a senha que já funciona continua valendo);
* se a tabela estiver vazia e você não passar nada, o `ensure_admin` do app cria com senha sorteada.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app import security  # noqa: E402
from app.store import documents, store  # noqa: E402
from app.store.client import BUCKET_ID, DATABASE_ID  # noqa: E402
from app.values import utcnow  # noqa: E402

# Ordem de dependência: filho antes do pai, para nada ficar apontando para linha apagada.
TABLES = (
    "note_tags",
    "note_groups",
    "group_members",
    "block_links",
    "note_relations",
    "note_members",
    "groups",
    "blocks",
    "notes",
    "tags",
    "media_files",
    "events",
    "gist_files",
    "sessions",
    "users",
    "counters",
    "schema_version",
)


def existing() -> set[str]:
    """As tabelas que existem na instância.

    O schema é a fonte da verdade, mas a instância pode estar atrás (ou à frente) dele: sem esta
    checagem, uma tabela que não existe derruba o `count` e a limpeza nem começa.
    """
    rows = store().tables.list_tables(DATABASE_ID).get("tables", [])
    return {row.get("$id") or row.get("id") for row in rows}


def snapshot(tables: set[str]) -> dict[str, int]:
    s = store()
    return {table: s.count(table) for table in TABLES if table in tables}


def show(title: str, counts: dict[str, int], arquivos: list[str]) -> None:
    print(f"[reset] {title}")
    for table, total in counts.items():
        if total:
            print(f"    {table:<18} {total}")
    print(f"    bucket {BUCKET_ID}: {len(arquivos)} arquivo(s)")


def wipe(apply: bool) -> tuple[dict[str, int], list[str]]:
    s = store()
    aqui = existing()
    faltando = [table for table in TABLES if table not in aqui]
    antes = snapshot(aqui)
    arquivos = [f["$id"] for f in s.storage.list_files(BUCKET_ID).get("files", [])]
    show("antes", antes, arquivos)
    if faltando:
        print(f"[reset] fora da instância (nada a apagar): {', '.join(faltando)}")
    if not apply:
        print("[reset] dry-run: nada foi apagado")
        return antes, arquivos

    for table in [name for name in TABLES if name in aqui]:
        removidas = s.delete_where(table, [])
        if removidas:
            print(f"    - {table:<18} {removidas} linha(s)")
    for nome in arquivos:
        try:
            s.storage.delete_file(BUCKET_ID, nome)
        except Exception as error:  # noqa: BLE001 - arquivo já ausente não é problema
            print(f"    ! arquivo {nome}: {str(error)[:60]}")
    print(f"    - bucket {BUCKET_ID}: {len(arquivos)} arquivo(s) apagado(s)")
    depois = snapshot(aqui)
    if any(depois.values()):
        sys.exit(f"[reset] sobrou linha: {depois}")
    print("[reset] tabelas vazias e contadores zerados (o próximo id de cada família é 1)")
    return antes, arquivos


def ensure_user(email: str, password: str | None, hash_atual: str | None) -> None:
    if documents.user_by_email(email) is not None:
        print(f"[reset] {email} já existe")
        return
    if password:
        hashed = security.hash_password(password)
    elif hash_atual:
        hashed = hash_atual  # mesma senha de antes: o hash é portável
        print("[reset] reaproveitando o hash da linha anterior (a senha atual continua valendo)")
    else:
        sys.exit("[reset] sem usuário anterior: passe --password para criar o admin agora")
    row_id = documents.record_id("users")
    user = documents.write(
        "users",
        row_id,
        {
            "email": email.strip().lower(),
            "display_name": "Admin",
            "password_hash": hashed,
            "role": "admin",
            "is_active": True,
            "created_at": utcnow(),
        },
        owner_id=None,
    )
    print(f"[reset] admin criado: {user.email} (id {user.id}, papel {user.role})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reset_appwrite.py", description="Zera a instância do NotAI")
    parser.add_argument("--dry-run", action="store_true", help="só mostra o que existe")
    parser.add_argument("--yes", action="store_true", help="confirma a destruição dos dados")
    parser.add_argument("--email", default="andrehrsilva@gmail.com")
    parser.add_argument("--password", default=None, help="sem isso, mantém a senha atual do admin")
    args = parser.parse_args(argv)

    if not (args.dry_run or args.yes):
        parser.error("use --dry-run para olhar ou --yes para apagar de verdade")

    s = store()
    print(f"[reset] database {DATABASE_ID} em {s.client._endpoint if hasattr(s.client, '_endpoint') else ''}".rstrip())
    atual = documents.user_by_email(args.email)
    hash_atual = atual.password_hash if atual else None

    if not args.dry_run:
        wipe(apply=True)
    else:
        wipe(apply=False)
        print("[reset] dry-run não cria o admin")
        return 0

    ensure_user(args.email, args.password, hash_atual)
    depois = snapshot(existing())
    show("depois", depois, [f["$id"] for f in s.storage.list_files(BUCKET_ID).get("files", [])])
    print("[reset] pronto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
