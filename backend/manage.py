"""User commands for when logging in is not an option: the admin forgot the password, or needs a second one.

    python manage.py list-users
    python manage.py create-user ana@casa.local --name Ana --admin
    python manage.py set-password ana@casa.local
    python manage.py set-role ana@casa.local user
    python manage.py deactivate ana@casa.local
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app import security, values
from app.store import documents, equal, order_asc, store
from app.store.documents import Row


def load_user(email: str) -> Row:
    user = documents.user_by_email(email)
    if user is None:
        sys.exit(f"[notai] usuário não encontrado: {email}")
    return user


def drop_sessions(user: Row) -> None:
    """Sessões abertas daquele usuário; o rowId é o hash do token, então o filtro é o `user_id`."""
    store().delete_where("sessions", [equal("user_id", str(user.id))])


def ask_password(explicit: str | None) -> str:
    if explicit:
        return explicit
    first = getpass.getpass("Senha: ")
    if first != getpass.getpass("Repita a senha: "):
        sys.exit("[notai] as senhas não batem")
    if len(first) < 8:
        sys.exit("[notai] a senha precisa de pelo menos 8 caracteres")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manage.py", description="Usuários do AnotAI")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list-users", help="lista e-mails, papéis e estado")

    create = commands.add_parser("create-user", help="cria um usuário")
    create.add_argument("email")
    create.add_argument("--name", default="")
    create.add_argument("--password", default=None, help="sem isso, a senha é pedida no terminal")
    create.add_argument("--admin", action="store_true", help="cria como administrador")

    for name, help_text in (
        ("set-password", "troca a senha e derruba as sessões abertas"),
        ("set-role", "define o papel"),
        ("activate", "reativa o acesso"),
        ("deactivate", "bloqueia o login"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("email")
        if name == "set-password":
            sub.add_argument("--password", default=None)
        if name == "set-role":
            sub.add_argument("role", choices=("admin", "user"))

    args = parser.parse_args(argv)

    if args.command == "list-users":
        users = documents.all_rows("users", [order_asc("email")])
        if not users:
            print("nenhum usuário ainda")
        for user in users:
            state = "ativo" if user.is_active else "desativado"
            last = user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else "nunca"
            print(f"{user.email}\t{user.role}\t{state}\túltimo acesso: {last}")
        return 0

    if args.command == "create-user":
        email = args.email.strip().lower()
        if documents.user_by_email(email) is not None:
            sys.exit(f"[notai] já existe: {email}")
        user = documents.write(
            "users",
            documents.record_id("users"),
            {
                "email": email,
                "display_name": args.name.strip() or email.split("@")[0],
                "password_hash": security.hash_password(ask_password(args.password)),
                "role": "admin" if args.admin else "user",
                "is_active": True,
                "created_at": values.utcnow(),
            },
            owner_id=None,
        )
        print(f"[notai] criado: {user.email} ({user.role})")
        return 0

    user = load_user(args.email)

    if args.command == "set-password":
        documents.change(
            "users",
            user.id,
            {"password_hash": security.hash_password(ask_password(args.password))},
            owner_id=None,
        )
        drop_sessions(user)
        print(f"[notai] senha trocada e sessões encerradas: {user.email}")
    elif args.command == "set-role":
        documents.change("users", user.id, {"role": args.role}, owner_id=None)
        print(f"[notai] {user.email} agora é {args.role}")
    elif args.command == "activate":
        documents.change("users", user.id, {"is_active": True}, owner_id=None)
        print(f"[notai] {user.email} pode entrar de novo")
    elif args.command == "deactivate":
        documents.change("users", user.id, {"is_active": False}, owner_id=None)
        drop_sessions(user)
        print(f"[notai] {user.email} bloqueado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
