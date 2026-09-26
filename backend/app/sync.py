"""Export engine: mirror every note to Drive as `NotAI/<Notebook>/<Note>.md`.

One-way and non-destructive — the app writes and renames, never deletes. Each note keeps its own
row in `drive_files`, so a run compares checksums locally and only touches what actually changed.

O dado vem todo do `store().snapshot(user_id)`: o Appwrite não tem `JOIN`, então a foto do usuário
traz cadernos, notas, blocos, tags e vínculos de uma vez, e o markdown é montado em memória. Os
tokens do Google continuam em arquivo (`drive_client.<id>.json`, `drive_token.<id>.json`).
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import threading
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from appwrite.exception import AppwriteException
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from . import drive
from .markdown import MEDIA_PREFIX, UNTITLED, file_stem, note_markdown
from .schemas import DriveStatus, SyncSummary
from .store import BUCKET_ID, Store, documents, store
from .store.documents import Row
from .values import utcnow

ROOT_FOLDER = "NotAI"
MEDIA_FOLDER = "_media"
FOLDER_MIME = "application/vnd.google-apps.folder"
MARKDOWN_MIME = "text/markdown"
MAX_MEDIA_BYTES = 20 * 1024 * 1024
RESUMABLE_ABOVE = 5 * 1024 * 1024

AUTO_SYNC_KEY = "auto_sync"
AUTO_SYNC_DEFAULT = "on"
DEFAULT_DELAY = 20
BUSY_DELAY = 10

# Dropped on disconnect: everything cached about the Drive tree of the account we left.
CONNECTION_KEYS = (
    "root_folder_id",
    "notebook_folders",
    "media_folder_id",
    "media_files",
    "last_sync_at",
    "last_summary",
    "last_error",
)

# A foto do usuário: as listas que o `snapshot` devolve, linha a linha no formato do app.
Photo = dict[str, list[Any]]

# One export lock and one debounce timer per user; `_guard` is the only lock touched by every user.
_guard = threading.Lock()
_locks: dict[int, threading.Lock] = {}
_timers: dict[int, threading.Timer] = {}
_running: set[int] = set()


class Busy(Exception):
    """Another export is already running."""


# ------------------------------------------------------------------- state


def _state_id(user_id: int, key: str) -> str:
    """Chave composta do `drive_state` é o rowId: `<user_id>_<chave>`."""
    return f"{user_id}_{key}"


def _get(db: Store, user_id: int, key: str, default: str = "") -> str:
    row = db.get("drive_state", _state_id(user_id, key))
    return (row or {}).get("value") or default


def _set(db: Store, user_id: int, key: str, value: str) -> None:
    """Linha de servidor (sem permissão de cliente): só a API key lê o estado do export."""
    row_id = _state_id(user_id, key)
    if db.get("drive_state", row_id) is None:
        db.create("drive_state", row_id, {"user_id": str(user_id), "key": key, "value": value})
    else:
        db.update("drive_state", row_id, {"value": value})


def _json_state(db: Store, user_id: int, key: str, default: object) -> object:
    """Parsed JSON state, falling back to `default` when absent or corrupted."""
    raw = _get(db, user_id, key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def status(db: Store, user_id: int) -> DriveStatus:
    """Mesmo formato de antes; o estado agora mora em `drive_state`, não numa sessão de banco."""
    summary = _json_state(db, user_id, "last_summary", None)
    return DriveStatus(
        connected=drive.is_connected(user_id),
        has_client_file=drive.has_client_file(user_id),
        auto_sync=_get(db, user_id, AUTO_SYNC_KEY, AUTO_SYNC_DEFAULT) == "on",
        pending=pending(user_id),
        last_sync_at=_get(db, user_id, "last_sync_at") or None,
        last_summary=SyncSummary.model_validate(summary) if summary else None,
        last_error=_get(db, user_id, "last_error") or None,
    )


def set_auto_sync(db: Store, user_id: int, enabled: bool) -> None:
    _set(db, user_id, AUTO_SYNC_KEY, "on" if enabled else "off")


def disconnect(db: Store, user_id: int) -> None:
    """Forget the token and every cached Drive id; Drive itself keeps its files."""
    drive.disconnect(user_id)
    for key in CONNECTION_KEYS:
        db.delete("drive_state", _state_id(user_id, key))


# --------------------------------------------------------------- scheduling


def _user_lock(user_id: int) -> threading.Lock:
    """The export lock of one user; created on first use and never removed."""
    with _guard:
        return _locks.setdefault(user_id, threading.Lock())


@contextmanager
def exclusive(user_id: int, timeout: float = 60) -> Iterator[None]:
    """Hold that user's export lock, or raise `Busy` when their run is still going."""
    lock = _user_lock(user_id)
    if not lock.acquire(timeout=timeout):
        raise Busy("sincronização em andamento")
    try:
        yield
    finally:
        lock.release()


def pending(user_id: int) -> bool:
    with _guard:
        return user_id in _timers or user_id in _running


def schedule_sync(user_id: int, delay: int = DEFAULT_DELAY) -> None:
    """Debounce that user's export: every write restarts the timer, so a burst becomes one run."""
    if not drive.is_connected(user_id):
        return
    if _get(store(), user_id, AUTO_SYNC_KEY, AUTO_SYNC_DEFAULT) != "on":
        return
    with _guard:
        timer = _timers.get(user_id)
        if timer is not None:
            timer.cancel()
        timer = threading.Timer(delay, _run_background, args=(user_id,))
        timer.daemon = True
        _timers[user_id] = timer
        timer.start()


def _run_background(user_id: int) -> None:
    with _guard:
        _timers.pop(user_id, None)
    lock = _user_lock(user_id)
    if not lock.acquire(blocking=False):
        schedule_sync(user_id, delay=BUSY_DELAY)
        return
    try:
        with _guard:
            _running.add(user_id)
        try:
            export_notes(store(), user_id)
        except Exception as error:  # noqa: BLE001 - a background thread must not die
            _record_error(user_id, error)
    finally:
        with _guard:
            _running.discard(user_id)
        lock.release()


def _record_error(user_id: int, error: BaseException) -> None:
    record_failure(store(), user_id, error)


def error_message(error: BaseException) -> str:
    """Short, user-facing reason for a failed run (never a traceback)."""
    if isinstance(error, RefreshError):  # google-auth refreshing on a 401 mid-call
        return drive.EXPIRED
    if isinstance(error, HttpError):
        reason = getattr(error, "reason", "") or str(error)
        return f"Drive: {getattr(error.resp, 'status', '?')} {reason}".strip()
    if isinstance(error, (TransportError, OSError)):  # offline, DNS down, connection refused
        return "sem conexão com o Google Drive"
    return str(error) or type(error).__name__


def record_failure(db: Store, user_id: int, error: BaseException) -> str:
    """Store why a run failed; a refused refresh also drops the dead token."""
    if isinstance(error, RefreshError):
        drive.disconnect(user_id)
    message = error_message(error)
    _set(db, user_id, "last_error", message)
    return message


# ------------------------------------------------------------------ export


def export_notes(db: Store, user_id: int) -> SyncSummary:
    """Send every note this user can read whose markdown changed and record the run."""
    try:
        return _export(db, user_id)
    except Exception as error:
        # Sem transação para desfazer: cada linha já gravada é fato consumado, e o motivo da parada
        # fica no estado do export para o painel mostrar.
        record_failure(db, user_id, error)
        raise


def _export(db: Store, user_id: int) -> SyncSummary:
    service = drive.service(user_id)
    photo = _photo(db, user_id)
    notebooks = _notebooks(db, photo)
    notes = photo["notes"]
    blocks = _blocks_by_note(photo["blocks"])
    tags = _tag_names(photo)

    root_id, created = _ensure_root(service, db, user_id)
    folders_created = int(created)
    folders, created = _notebook_folders(service, db, user_id, root_id, notebooks)
    folders_created += created

    names = _file_names(notes)
    media_links, media_sent, skipped_media, errors = _media(service, db, user_id, root_id, photo)
    links = _link_titles(photo)

    notes_sent = 0
    notes_unchanged = 0
    for note in notes:
        notebook = notebooks.get(note.notebook_id)
        folder = folders.get(note.notebook_id)
        if notebook is None or folder is None:  # the notebook went away mid-run
            continue
        filename = names[note.id]
        path = f"{folder['name']}/{filename}"
        related, mentions = links.get(note.id, ((), ()))
        markdown = note_markdown(
            note,
            blocks.get(note.id, []),
            notebook_title=notebook.title,
            tags=tags.get(note.id, []),
            media_links=media_links,
            related=related,
            mentions=mentions,
        )
        checksum = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        try:
            row = db.get("drive_files", note.id)
            if row is None:
                file_id = _upload_markdown(service, markdown, filename, folder["id"])
                _remember(db, note.id, file_id, folder["id"], path, checksum, create=True)
                notes_sent += 1
            else:
                moved = row.get("folder_id") != folder["id"] or row.get("drive_path") != path
                changed = row.get("checksum") != checksum
                if moved:
                    _move(service, row["file_id"], filename, folder["id"], row.get("folder_id"))
                if changed:
                    _replace_markdown(service, row["file_id"], markdown)
                if moved or changed:
                    _remember(db, note.id, row["file_id"], folder["id"], path, checksum, create=False)
                    notes_sent += 1
                else:
                    notes_unchanged += 1
        except Exception as error:  # noqa: BLE001 - reported in the summary, then stop
            errors.append(f"{filename}: {error_message(error)}")
            break

    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = SyncSummary(
        notes_sent=notes_sent,
        notes_unchanged=notes_unchanged,
        folders_created=folders_created,
        media_sent=media_sent,
        skipped_media=skipped_media,
        errors=errors,
        at=at,
    )
    _set(db, user_id, "last_sync_at", at)
    _set(db, user_id, "last_summary", summary.model_dump_json())
    _set(db, user_id, "last_error", "; ".join(errors))
    return summary


def _remember(
    db: Store,
    note_id: int,
    file_id: str,
    folder_id: str,
    path: str,
    checksum: str,
    *,
    create: bool,
) -> None:
    """Uma linha por nota (`rowId` = id da nota): é ela que diz o que já está no Drive."""
    data = {
        "file_id": file_id,
        "folder_id": folder_id,
        "drive_path": path,
        "checksum": checksum,
        "synced_at": documents.to_iso(utcnow()),
    }
    if create:
        db.create("drive_files", note_id, data)
    else:
        db.update("drive_files", note_id, data)


# ------------------------------------------------------------------- dados


def _photo(db: Store, user_id: int) -> Photo:
    """A foto do usuário, linha a linha no formato do app (`note.title`, `block.position`)."""
    return {
        table: [row if isinstance(row, Row) else documents.normalize(table, row) for row in rows]
        for table, rows in db.snapshot(user_id).items()
    }


def _notebooks(db: Store, photo: Photo) -> dict[int, Row]:
    """Todo caderno legível; o snapshot traz só os próprios, o compartilhado vem por id."""
    known = {row.id: row for row in photo["notebooks"]}
    wanted = {row.notebook_id for row in photo["notes"]} | {
        documents.to_int(row["notebook_id"]) for row in photo["notebook_members"]
    }
    for notebook_id in sorted(wanted - known.keys()):
        row = documents.get("notebooks", notebook_id)
        if row is not None:
            known[notebook_id] = row
    return known


def _blocks_by_note(rows: Iterable[Row]) -> dict[int, list[Row]]:
    """Blocos por nota na ordem do editor: é ela que dá o mesmo markdown (e o mesmo checksum)."""
    grouped: dict[int, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[row.note_id].append(row)
    return {
        note_id: sorted(item, key=lambda row: (row.position, row.id))
        for note_id, item in grouped.items()
    }


def _tag_names(photo: Photo) -> dict[int, list[str]]:
    """Nomes das tags por nota, em ordem alfabética — o `order_by(Tag.name)` de antes."""
    names = {row.id: row.name for row in photo["tags"]}
    grouped: dict[int, list[str]] = defaultdict(list)
    for row in photo["note_tags"]:
        name = names.get(documents.to_int(row["tag_id"]))
        if name:
            grouped[documents.to_int(row["note_id"])].append(name)
    return {note_id: sorted(item) for note_id, item in grouped.items()}


def _link_titles(photo: Photo) -> dict[int, tuple[list[str], list[str]]]:
    """Per note: the titles it relates to, then the ones it cites in its blocks."""
    notes = {row.id: row for row in photo["notes"]}
    blocks = {row.id: row for row in photo["blocks"]}
    titles: dict[int, tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
    for relation in photo["note_relations"]:
        for source, target in (
            (relation.source_id, relation.target_id),
            (relation.target_id, relation.source_id),
        ):
            if source in notes and target in notes:
                titles[source][0].append(notes[target].title or UNTITLED)

    # Mesma ordem da consulta de antes: nota citante, posição do bloco, id do vínculo.
    def _order(link: Row) -> tuple[int, int, int]:
        block = blocks.get(link.block_id)
        return (block.note_id, block.position, link.id) if block else (-1, 0, link.id)

    for link in sorted(photo["block_links"], key=_order):
        block = blocks.get(link.block_id)
        if block is None:
            continue
        mentioned = notes.get(link.note_id)
        label = (mentioned.title if mentioned else "") or UNTITLED
        if label not in titles[block.note_id][1]:
            titles[block.note_id][1].append(label)
    return titles


def _file_names(notes: Sequence[Row]) -> dict[int, str]:
    """One deterministic file name per note; equal stems in a notebook both get their id."""
    stems = {note.id: file_stem(note.title, f"nota-{note.id}") for note in notes}
    shared = Counter((note.notebook_id, stems[note.id]) for note in notes)
    return {
        note.id: (
            f"{stems[note.id]} ({note.id}).md"
            if shared[(note.notebook_id, stems[note.id])] > 1
            else f"{stems[note.id]}.md"
        )
        for note in notes
    }


# ------------------------------------------------------------------ folders


def _ensure_root(service, db: Store, user_id: int) -> tuple[str, bool]:
    folder_id = _get(db, user_id, "root_folder_id")
    if folder_id:
        return folder_id, False
    folder_id = _create_folder(service, ROOT_FOLDER, None)
    _set(db, user_id, "root_folder_id", folder_id)
    return folder_id, True


def _notebook_folders(
    service, db: Store, user_id: int, root_id: str, notebooks: dict[int, Row]
) -> tuple[dict[int, dict[str, str]], int]:
    """Folder per readable notebook, keyed by notebook id so renaming keeps the same folder."""
    known: dict[str, dict[str, str]] = _json_state(db, user_id, "notebook_folders", {})  # type: ignore[assignment]
    created = 0
    for notebook_id, notebook in sorted(notebooks.items()):
        name = file_stem(notebook.title, f"caderno-{notebook_id}")
        entry = known.get(str(notebook_id))
        if entry is None:
            known[str(notebook_id)] = {"id": _create_folder(service, name, root_id), "name": name}
            created += 1
        elif entry.get("name") != name:
            service.files().update(
                fileId=entry["id"], body={"name": name}, fields="id"
            ).execute()
            entry["name"] = name
    _set(db, user_id, "notebook_folders", json.dumps(known))
    return {int(key): value for key, value in known.items()}, created


def _ensure_media_folder(service, db: Store, user_id: int, root_id: str) -> str:
    folder_id = _json_state(db, user_id, "media_folder_id", "")
    if folder_id:
        return str(folder_id)
    folder_id = _create_folder(service, MEDIA_FOLDER, root_id)
    _set(db, user_id, "media_folder_id", folder_id)
    return folder_id


def _create_folder(service, name: str, parent_id: str | None) -> str:
    body: dict[str, object] = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id is not None:
        body["parents"] = [parent_id]
    return service.files().create(body=body, fields="id").execute()["id"]


# -------------------------------------------------------------------- media


def _media(
    service, db: Store, user_id: int, root_id: str, photo: Photo
) -> tuple[dict[str, str], int, int, list[str]]:
    """Sobe os arquivos do bucket que estas notas citam; devolve `url -> link` para o markdown."""
    urls = sorted({row.url for row in photo["blocks"] if row.url.startswith(MEDIA_PREFIX)})
    known: dict[str, dict[str, str]] = _json_state(db, user_id, "media_files", {})  # type: ignore[assignment]
    links: dict[str, str] = {}
    errors: list[str] = []
    folder_id: str | None = None
    sent = 0
    skipped = 0

    for url in urls:
        name = Path(url).name
        cached = known.get(url)
        if cached and cached.get("link"):
            links[url] = cached["link"]
            continue
        row = _media_row(photo, name)
        if row is None or row.size > MAX_MEDIA_BYTES:
            skipped += 1
            continue
        data = _media_bytes(db, row.row_id)
        if data is None or len(data) > MAX_MEDIA_BYTES:
            skipped += 1
            continue
        if folder_id is None:
            folder_id = _ensure_media_folder(service, db, user_id, root_id)
        try:
            uploaded = _upload_media(service, name, data, folder_id)
        except Exception as error:  # noqa: BLE001 - one bad file must not stop the export
            errors.append(f"{name}: {error_message(error)}")
            continue
        known[url] = uploaded
        links[url] = uploaded["link"]
        _set(db, user_id, "media_files", json.dumps(known))
        sent += 1
    return links, sent, skipped, errors


def _media_row(photo: Photo, filename: str) -> Row | None:
    """A linha do arquivo: a foto traz as do dono, o resto (nota compartilhada) vem por id."""
    for row in photo["media_files"]:
        if row.filename == filename:
            return row
    return documents.media_by_filename(filename)


def _media_bytes(db: Store, filename: str) -> bytes | None:
    """Bytes do bucket; `None` quando só a linha sobrou (o arquivo não está mais lá)."""
    try:
        return db.storage.get_file_view(BUCKET_ID, filename)
    except AppwriteException as error:
        if error.code == 404:
            return None
        raise


def _markdown_media(markdown: str) -> MediaIoBaseUpload:
    return MediaIoBaseUpload(BytesIO(markdown.encode("utf-8")), mimetype=MARKDOWN_MIME)


def _upload_markdown(service, markdown: str, name: str, folder_id: str) -> str:
    created = (
        service.files()
        .create(
            body={"name": name, "parents": [folder_id], "mimeType": MARKDOWN_MIME},
            media_body=_markdown_media(markdown),
            fields="id",
        )
        .execute()
    )
    return created["id"]


def _replace_markdown(service, file_id: str, markdown: str) -> None:
    service.files().update(
        fileId=file_id, media_body=_markdown_media(markdown), fields="id"
    ).execute()


def _move(service, file_id: str, name: str, folder_id: str, old_folder_id: str) -> None:
    """Rename and/or reparent in one call, keeping the same Drive file id."""
    extra: dict[str, str] = {}
    if folder_id != old_folder_id:
        extra = {"addParents": folder_id, "removeParents": old_folder_id}
    service.files().update(fileId=file_id, body={"name": name}, fields="id", **extra).execute()


def _upload_media(service, name: str, data: bytes, folder_id: str) -> dict[str, str]:
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    media = MediaIoBaseUpload(BytesIO(data), mimetype=mime, resumable=len(data) > RESUMABLE_ABOVE)
    created = (
        service.files()
        .create(
            body={"name": name, "parents": [folder_id]},
            media_body=media,
            fields="id,webViewLink",
        )
        .execute()
    )
    return {"id": created["id"], "link": created["webViewLink"]}
