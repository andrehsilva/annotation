from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from .. import acl, deps, events, services
from ..database import get_db
from ..models import Block, Note, Notebook, User
from ..schemas import (
    NotebookIn,
    NotebookOut,
    NotebookPatch,
    NotebookSummary,
)

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


@router.get("", response_model=list[NotebookSummary])
def list_notebooks(
    user: User = Depends(deps.current_user), db: Session = Depends(get_db)
) -> list[NotebookSummary]:
    return services.list_notebook_summaries(db, user.id)


@router.post("", response_model=NotebookOut, status_code=status.HTTP_201_CREATED)
def create_notebook(
    payload: NotebookIn,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NotebookOut:
    notebook = Notebook(title=payload.title.strip(), description=payload.description.strip())
    notebook.notes.append(Note(title="", position=0, blocks=[Block(position=0, type="text")]))
    db.add(notebook)
    db.flush()
    acl.add_member(db, notebook.id, user.id)  # o dono nasce junto com o caderno
    events.record(db, user, "created", "notebook", notebook.title)
    db.commit()
    return services.notebook_detail(db, user.id, deps.notebook_for(db, user, notebook.id))


@router.get("/{notebook_id}", response_model=NotebookOut)
def get_notebook(
    notebook_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NotebookOut:
    notebook = deps.notebook_for(db, user, notebook_id, "viewer")
    return services.notebook_detail(db, user.id, notebook)


@router.patch("/{notebook_id}", response_model=NotebookOut)
def update_notebook(
    notebook_id: int,
    payload: NotebookPatch,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NotebookOut:
    notebook = deps.notebook_for(db, user, notebook_id)
    if payload.title is not None:
        notebook.title = payload.title.strip()
    if payload.description is not None:
        notebook.description = payload.description.strip()
    events.record(db, user, "updated", "notebook", notebook.title)
    db.commit()
    return services.notebook_detail(db, user.id, notebook)


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notebook(
    notebook_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> Response:
    notebook = deps.notebook_for(db, user, notebook_id)
    title = notebook.title  # o objeto some no delete, então o rótulo sai antes
    db.delete(notebook)
    events.record(db, user, "deleted", "notebook", title)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{notebook_id}/tags/{tag_id}", response_model=NotebookOut)
def attach_tag(
    notebook_id: int,
    tag_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NotebookOut:
    notebook = deps.notebook_for(db, user, notebook_id)
    tag = deps.tag_for(db, user, tag_id)
    if tag not in notebook.tags:
        notebook.tags.append(tag)
        events.record(db, user, "tagged", "notebook", notebook.title, tag.name)
        db.commit()
    return services.notebook_detail(db, user.id, notebook)


@router.delete("/{notebook_id}/tags/{tag_id}", response_model=NotebookOut)
def detach_tag(
    notebook_id: int,
    tag_id: int,
    user: User = Depends(deps.current_user),
    db: Session = Depends(get_db),
) -> NotebookOut:
    notebook = deps.notebook_for(db, user, notebook_id)
    tag = deps.tag_for(db, user, tag_id)
    if tag in notebook.tags:
        notebook.tags.remove(tag)
        events.record(db, user, "untagged", "notebook", notebook.title, tag.name)
        db.commit()
    return services.notebook_detail(db, user.id, notebook)
