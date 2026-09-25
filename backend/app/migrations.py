"""Schema and row steps for databases that predate users.

`create_all` only adds missing *tables* — it never touches an existing one. So the two tables that
need a new column plus a new key (`tags`, `drive_state`) are recreated here with the canonical SQLite
recipe (recreate, copy, drop, rename) and everything that existed before users is handed to the admin.
Every step is guarded, so a restart after the first successful run changes nothing.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from .models import utcnow

# Foreign keys must be off around the rebuilds: dropping `tags` would otherwise cascade into
# `note_tags`/`notebook_tags`. The recipe is SQLite's own ("Making Other Kinds Of Table Schema
# Changes"): recreate, copy, drop, rename, check, commit.
TAGS_TABLE = """
CREATE TABLE tags_rebuilt (
    id INTEGER NOT NULL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(60) NOT NULL,
    color VARCHAR(16) NOT NULL,
    created_at DATETIME NOT NULL,
    CONSTRAINT uq_tag_owner_name UNIQUE (owner_id, name)
)
"""

DRIVE_STATE_TABLE = """
CREATE TABLE drive_state_rebuilt (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key VARCHAR(40) NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
)
"""


def _tables(target) -> set[str]:
    rows = target.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def _columns(target, table: str) -> set[str]:
    rows = target.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _database_file(engine: Engine) -> Path | None:
    url = make_url(str(engine.url))
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database)


def pending(engine: Engine) -> bool:
    """True when the file still has the pre-users shape — then it gets a backup before anything runs."""
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        tables = _tables(cursor)
        if "users" not in tables:
            return True
        if "tags" in tables and "owner_id" not in _columns(cursor, "tags"):
            return True
        if "drive_state" in tables and "user_id" not in _columns(cursor, "drive_state"):
            return True
        if "activity_seen_at" not in _columns(cursor, "users"):
            return True
        return False
    finally:
        raw.close()


def snapshot(engine: Engine) -> Path | None:
    """Copy the SQLite file next to itself; nothing is ever deleted by the migration."""
    path = _database_file(engine)
    if path is None or not path.exists():
        return None
    target = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, target)
    return target


def add_columns(engine: Engine) -> None:
    """Plain new columns on tables that already exist: `create_all` never adds one.

    Runs before anything reads those tables through the ORM — otherwise the SELECT already carries
    the new column and the whole start fails.
    """
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        tables = _tables(cursor)
        if "users" in tables and "activity_seen_at" not in _columns(cursor, "users"):
            cursor.execute("ALTER TABLE users ADD COLUMN activity_seen_at DATETIME")
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def run(engine: Engine, owner_id: int) -> None:
    """Rebuild `tags` and `drive_state` when they still lack the owner column."""
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        tables = _tables(cursor)
        if "tags" in tables and "owner_id" not in _columns(cursor, "tags"):
            cursor.execute(TAGS_TABLE)
            cursor.execute(
                "INSERT INTO tags_rebuilt (id, owner_id, name, color, created_at)"
                " SELECT id, ?, name, color, created_at FROM tags",
                (owner_id,),
            )
            cursor.execute("DROP TABLE tags")
            cursor.execute("ALTER TABLE tags_rebuilt RENAME TO tags")
            cursor.execute("CREATE INDEX ix_tags_owner_id ON tags (owner_id)")
        if "drive_state" in tables and "user_id" not in _columns(cursor, "drive_state"):
            cursor.execute(DRIVE_STATE_TABLE)
            cursor.execute(
                "INSERT INTO drive_state_rebuilt (user_id, key, value)"
                " SELECT ?, key, value FROM drive_state",
                (owner_id,),
            )
            cursor.execute("DROP TABLE drive_state")
            cursor.execute("ALTER TABLE drive_state_rebuilt RENAME TO drive_state")
        broken = cursor.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(f"migração deixaria {len(broken)} referências quebradas: {broken[:3]}")
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys=ON")
        raw.close()


def _stamp() -> str:
    """SQLAlchemy's SQLite dialect stores DATETIME as `YYYY-MM-DD HH:MM:SS.ffffff`."""
    return utcnow().isoformat(sep=" ")


def backfill(engine: Engine, owner_id: int, media_dir: Path) -> None:
    """Hand everything that predates users to the admin: tags, Drive state, notebooks, media files."""
    stamp = _stamp()
    with engine.begin() as conn:
        conn.execute(text("UPDATE tags SET owner_id = :owner WHERE owner_id IS NULL"), {"owner": owner_id})
        conn.execute(
            text("UPDATE drive_state SET user_id = :owner WHERE user_id IS NULL"), {"owner": owner_id}
        )
        conn.execute(
            text(
                "INSERT INTO notebook_members (notebook_id, user_id, role, created_at)"
                " SELECT id, :owner, 'owner', :stamp FROM notebooks"
                " WHERE id NOT IN (SELECT notebook_id FROM notebook_members)"
            ),
            {"owner": owner_id, "stamp": stamp},
        )
        known = {row[0] for row in conn.execute(text("SELECT filename FROM media_files"))}
        for file in sorted(media_dir.glob("*")):
            if not file.is_file() or file.name in known:
                continue
            conn.execute(
                text(
                    "INSERT INTO media_files (owner_id, filename, original_name, content_type, size, created_at)"
                    " VALUES (:owner, :name, :name, '', :size, :stamp)"
                ),
                {"owner": owner_id, "name": file.name, "size": file.stat().st_size, "stamp": stamp},
            )


def move_drive_files(data_dir: Path, owner_id: int) -> None:
    """The single Drive connection that existed before users becomes the admin's."""
    for legacy, per_user in (
        ("drive_client.json", f"drive_client.{owner_id}.json"),
        ("drive_token.json", f"drive_token.{owner_id}.json"),
    ):
        source, target = data_dir / legacy, data_dir / per_user
        if source.exists() and not target.exists():
            source.rename(target)
