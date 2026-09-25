"""Export engine: mirror every note to Drive as `NotAI/<Notebook>/<Note>.md`.

One-way and non-destructive — the app writes and renames, never deletes. Each note keeps its own
row in `drive_files`, so a run compares checksums locally and only touches what actually changed.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import threading
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import acl, drive
from .database import MEDIA_DIR, SessionLocal
from .markdown import MEDIA_PREFIX, UNTITLED, file_stem, note_markdown
from .models import Block, BlockLink, DriveFile, DriveState, Note, NoteRelation, Notebook, utcnow
from .schemas import DriveStatus, SyncSummary

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

# One export lock and one debounce timer per user; `_guard` is the only lock touched by every user.
_guard = threading.Lock()
_locks: dict[int, threading.Lock] = {}
_timers: dict[int, threading.Timer] = {}
_running: set[int] = set()


class Busy(Exception):
    """Another export is already running."""


# ------------------------------------------------------------------- state


def _get(db: Session, user_id: int, key: str, default: str = "") -> str:
    row = db.get(DriveState, (user_id, key))
    return row.value if row is not None else default


def _set(db: Session, user_id: int, key: str, value: str) -> None:
    row = db.get(DriveState, (user_id, key))
    if row is None:
        db.add(DriveState(user_id=user_id, key=key, value=value))
    else:
        row.value = value


def _json_state(db: Session, user_id: int, key: str, default: object) -> object:
    """Parsed JSON state, falling back to `default` when absent or corrupted."""
    raw = _get(db, user_id, key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def status(db: Session, user_id: int) -> DriveStatus:
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


def set_auto_sync(db: Session, user_id: int, enabled: bool) -> None:
    _set(db, user_id, AUTO_SYNC_KEY, "on" if enabled else "off")
    db.commit()


def disconnect(db: Session, user_id: int) -> None:
    """Forget the token and every cached Drive id; Drive itself keeps its files."""
    drive.disconnect(user_id)
    for key in CONNECTION_KEYS:
        row = db.get(DriveState, (user_id, key))
        if row is not None:
            db.delete(row)
    db.commit()


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
    with SessionLocal() as db:
        if _get(db, user_id, AUTO_SYNC_KEY, AUTO_SYNC_DEFAULT) != "on":
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
        with SessionLocal() as db:
            try:
                export_notes(db, user_id)
            except Exception as error:  # noqa: BLE001 - a background thread must not die
                _record_error(user_id, error)
    finally:
        with _guard:
            _running.discard(user_id)
        lock.release()


def _record_error(user_id: int, error: BaseException) -> None:
    with SessionLocal() as db:
        record_failure(db, user_id, error)
        db.commit()


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


def record_failure(db: Session, user_id: int, error: BaseException) -> str:
    """Store why a run failed; a refused refresh also drops the dead token."""
    if isinstance(error, RefreshError):
        drive.disconnect(user_id)
    message = error_message(error)
    _set(db, user_id, "last_error", message)
    return message


# ------------------------------------------------------------------ export


def export_notes(db: Session, user_id: int) -> SyncSummary:
    """Send every note this user can read whose markdown changed and record the run."""
    try:
        return _export(db, user_id)
    except Exception as error:
        db.rollback()
        record_failure(db, user_id, error)
        db.commit()
        raise


def _export(db: Session, user_id: int) -> SyncSummary:
    service = drive.service(user_id)

    root_id, created = _ensure_root(service, db, user_id)
    folders_created = int(created)
    folders, created = _notebook_folders(service, db, user_id, root_id)
    folders_created += created

    notes = db.scalars(
        select(Note)
        .where(Note.notebook_id.in_(acl.readable_notebook_ids(user_id)))
        .options(
            selectinload(Note.notebook), selectinload(Note.blocks), selectinload(Note.tags)
        )
    ).all()
    names = _file_names(notes)
    media_links, media_sent, skipped_media, errors = _media(service, db, user_id, root_id)
    links = _link_titles(db, user_id)

    notes_sent = 0
    notes_unchanged = 0
    for note in notes:
        folder = folders.get(note.notebook_id)
        if folder is None:  # the notebook went away mid-run
            continue
        filename = names[note.id]
        path = f"{folder['name']}/{filename}"
        related, mentions = links.get(note.id, ((), ()))
        markdown = note_markdown(note, media_links, related, mentions)
        checksum = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        try:
            row = db.scalar(select(DriveFile).where(DriveFile.note_id == note.id))
            if row is None:
                file_id = _upload_markdown(service, markdown, filename, folder["id"])
                db.add(
                    DriveFile(
                        note_id=note.id,
                        file_id=file_id,
                        folder_id=folder["id"],
                        drive_path=path,
                        checksum=checksum,
                    )
                )
                notes_sent += 1
            else:
                moved = row.folder_id != folder["id"] or row.drive_path != path
                changed = row.checksum != checksum
                if moved:
                    _move(service, row.file_id, filename, folder["id"], row.folder_id)
                    row.folder_id = folder["id"]
                    row.drive_path = path
                if changed:
                    _replace_markdown(service, row.file_id, markdown)
                    row.checksum = checksum
                if moved or changed:
                    row.synced_at = utcnow()
                    notes_sent += 1
                else:
                    notes_unchanged += 1
            db.commit()  # per note: the run stays consistent if it is interrupted
        except Exception as error:  # noqa: BLE001 - reported in the summary, then stop
            db.rollback()
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
    db.commit()
    return summary


def _link_titles(db: Session, user_id: int) -> dict[int, tuple[list[str], list[str]]]:
    """Per note: the titles it relates to, then the ones it cites in its blocks."""
    titles: dict[int, tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
    readable = acl.readable_note_ids(user_id)
    relations = db.scalars(
        select(NoteRelation)
        .where(NoteRelation.source_id.in_(readable), NoteRelation.target_id.in_(readable))
        .options(
            selectinload(NoteRelation.source), selectinload(NoteRelation.target)
        )
    ).all()
    for relation in relations:
        titles[relation.source_id][0].append(relation.target.title or UNTITLED)
        titles[relation.target_id][0].append(relation.source.title or UNTITLED)

    rows = db.execute(
        select(Block.note_id, Note.title)
        .select_from(BlockLink)
        .join(Block, Block.id == BlockLink.block_id)
        .join(Note, Note.id == BlockLink.note_id)
        .where(Block.note_id.in_(readable))
        .order_by(Block.note_id, Block.position, BlockLink.id)
    ).all()
    for note_id, title in rows:
        label = title or UNTITLED
        if label not in titles[note_id][1]:
            titles[note_id][1].append(label)
    return titles


def _file_names(notes: Sequence[Note]) -> dict[int, str]:
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


def _ensure_root(service, db: Session, user_id: int) -> tuple[str, bool]:
    folder_id = _get(db, user_id, "root_folder_id")
    if folder_id:
        return folder_id, False
    folder_id = _create_folder(service, ROOT_FOLDER, None)
    _set(db, user_id, "root_folder_id", folder_id)
    db.commit()
    return folder_id, True


def _notebook_folders(
    service, db: Session, user_id: int, root_id: str
) -> tuple[dict[int, dict[str, str]], int]:
    """Folder per readable notebook, keyed by notebook id so renaming keeps the same folder."""
    known: dict[str, dict[str, str]] = _json_state(db, user_id, "notebook_folders", {})  # type: ignore[assignment]
    created = 0
    notebooks = db.scalars(
        select(Notebook).where(Notebook.id.in_(acl.readable_notebook_ids(user_id)))
    ).all()
    for notebook in notebooks:
        name = file_stem(notebook.title, f"caderno-{notebook.id}")
        entry = known.get(str(notebook.id))
        if entry is None:
            known[str(notebook.id)] = {"id": _create_folder(service, name, root_id), "name": name}
            created += 1
        elif entry.get("name") != name:
            service.files().update(
                fileId=entry["id"], body={"name": name}, fields="id"
            ).execute()
            entry["name"] = name
    _set(db, user_id, "notebook_folders", json.dumps(known))
    db.commit()
    return {int(key): value for key, value in known.items()}, created


def _ensure_media_folder(service, db: Session, user_id: int, root_id: str) -> str:
    folder_id = _json_state(db, user_id, "media_folder_id", "")
    if folder_id:
        return str(folder_id)
    folder_id = _create_folder(service, MEDIA_FOLDER, root_id)
    _set(db, user_id, "media_folder_id", folder_id)
    db.commit()
    return folder_id


def _media(
    service, db: Session, user_id: int, root_id: str
) -> tuple[dict[str, str], int, int, list[str]]:
    """Upload the local files these notes reference; returns `url -> Drive link` for the markdown."""
    urls = db.scalars(
        select(Block.url)
        .where(
            Block.url.like(f"{MEDIA_PREFIX}%"),
            Block.note_id.in_(acl.readable_note_ids(user_id)),
        )
        .distinct()
    ).all()
    known: dict[str, dict[str, str]] = _json_state(db, user_id, "media_files", {})  # type: ignore[assignment]
    links: dict[str, str] = {}
    errors: list[str] = []
    folder_id: str | None = None
    sent = 0
    skipped = 0

    for url in urls:
        cached = known.get(url)
        if cached and cached.get("link"):
            links[url] = cached["link"]
            continue
        path = MEDIA_DIR / Path(url).name
        if not path.is_file() or path.stat().st_size > MAX_MEDIA_BYTES:
            skipped += 1
            continue
        if folder_id is None:
            folder_id = _ensure_media_folder(service, db, user_id, root_id)
        try:
            uploaded = _upload_media(service, path, folder_id)
        except Exception as error:  # noqa: BLE001 - one bad file must not stop the export
            errors.append(f"{path.name}: {error_message(error)}")
            continue
        known[url] = uploaded
        links[url] = uploaded["link"]
        _set(db, user_id, "media_files", json.dumps(known))
        db.commit()
        sent += 1
    return links, sent, skipped, errors


def _create_folder(service, name: str, parent_id: str | None) -> str:
    body: dict[str, object] = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id is not None:
        body["parents"] = [parent_id]
    return service.files().create(body=body, fields="id").execute()["id"]


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


def _upload_media(service, path: Path, folder_id: str) -> dict[str, str]:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    size = path.stat().st_size
    with path.open("rb") as handle:
        media = MediaIoBaseUpload(handle, mimetype=mime, resumable=size > RESUMABLE_ABOVE)
        created = (
            service.files()
            .create(
                body={"name": path.name, "parents": [folder_id]},
                media_body=media,
                fields="id,webViewLink",
            )
            .execute()
        )
    return {"id": created["id"], "link": created["webViewLink"]}
