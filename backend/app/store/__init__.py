"""Camada de dados do NotAI: o Appwrite é a única fonte, este pacote é a única porta.

`client.py` fala HTTP com o Appwrite (queries JSON, paginação, transações, contadores, cache por
usuário). `documents.py` traduz linha ↔ modelo antigo e concentra as escritas com auditoria.
"""

from . import documents  # noqa: F401
from .client import (  # noqa: F401
    BUCKET_ID,
    DATABASE_ID,
    SERVER_ONLY,
    Conflict,
    Store,
    all_of,
    equal,
    is_null,
    limit,
    offset,
    order_asc,
    order_desc,
    owner_permissions,
    q,
    store,
)

__all__ = ["store", "documents", "Store", "Conflict", "q", "equal", "limit", "order_asc", "order_desc"]
