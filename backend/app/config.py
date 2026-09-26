"""Configuração do processo: lê `backend/.env` (fora do git) antes de qualquer módulo pedir env.

Em produção quem fornece as variáveis é o `EnvironmentFile` do systemd; este carregador existe para
o desenvolvimento local e para os scripts em `tools/`. Sem dependência nova: `python-dotenv` não é
usado aqui de propósito, o formato que precisamos é `CHAVE=valor` por linha.
"""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"

# Onde ficam as coisas que ainda são arquivo: os tokens do Google Drive de cada usuário.
DATA_DIR = Path(os.environ.get("CADERNO_DATA_DIR", BACKEND_DIR / "data")).resolve()


def load_env_file(path: Path | None = None) -> None:
    """Não sobrescreve o que já veio do ambiente: o systemd ganha do arquivo."""
    target = path or ENV_FILE
    if not target.exists():
        return
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()
