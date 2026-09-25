import { GraphIcon, NoteBlank, Plus, Trash } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, KIND_ORDER, relativeTime } from "../lib/format";
import type { Notebook, Tag, TagUsage } from "../lib/types";
import { RelationsModal } from "./RelationsModal";
import { TagRow } from "./TagRow";
import { EmptyState } from "./ui";

interface NotebookViewProps {
  notebook: Notebook;
  tags: TagUsage[];
  onCreateTag: (name: string) => Promise<Tag | null>;
  onOpenNote: (noteId: number) => void;
  /** The written line becomes the note name; the note opens ready to be written. */
  onCreateNote: (name?: string) => void;
  onDeleteNote: (noteId: number) => void;
  onRename: (patch: { title?: string; description?: string }) => void;
  onDelete: () => void;
  onToggleTag: (tagId: number, attached: boolean) => void;
  onOpenNotebook: (id: number) => void;
}

export function NotebookView({
  notebook,
  tags,
  onCreateTag,
  onOpenNote,
  onCreateNote,
  onDeleteNote,
  onRename,
  onDelete,
  onToggleTag,
  onOpenNotebook,
}: NotebookViewProps) {
  const [title, setTitle] = useState(notebook.title);
  const [description, setDescription] = useState(notebook.description);
  const [draft, setDraft] = useState("");
  const [relationsOpen, setRelationsOpen] = useState(false);
  const captureRef = useRef<HTMLInputElement | null>(null);
  const descriptionRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    setTitle(notebook.title);
    setDescription(notebook.description);
  }, [notebook.id, notebook.title, notebook.description]);

  useEffect(() => {
    const element = descriptionRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [description]);

  /**
   * Typing anywhere in the notebook jumps into the capture field, so writing is always one key away.
   * Bound to the window: a keydown targeted at <body> never reaches this component's own subtree.
   */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key.length !== 1 || event.key === " ") return;
      const target = event.target;
      if (
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        (target instanceof HTMLElement && target.isContentEditable)
      ) {
        return;
      }
      captureRef.current?.focus();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const submitDraft = () => {
    const name = draft.trim();
    if (!name) {
      onCreateNote();
      return;
    }
    setDraft("");
    onCreateNote(name);
  };

  return (
    <div className="view">
      <header className="nb-head">
        <input
          className="nb-title-input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          onBlur={() => title.trim() && title !== notebook.title && onRename({ title: title.trim() })}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
          aria-label="Título do caderno"
        />
        <textarea
          ref={descriptionRef}
          className="nb-desc-input"
          value={description}
          placeholder="Descrição curta deste caderno"
          rows={1}
          onChange={(event) => setDescription(event.target.value)}
          onBlur={() =>
            description !== notebook.description && onRename({ description: description.trim() })
          }
        />

        <div className="nb-head-meta">
          <TagRow
            attached={notebook.tags}
            all={tags}
            onCreate={onCreateTag}
            onToggle={(tag, attached) => onToggleTag(tag.id, attached)}
          />
          <span className="meta-row">
            <span>{notebook.notes_count} notas</span>
            <span>atualizado {relativeTime(notebook.updated_at)}</span>
          </span>
        </div>

        <div className="nb-toolbar">
          <span className="nb-counts">
            {KIND_ORDER.filter((kind) => notebook.counts[kind] > 0).map((kind) => {
              const KindIcon = KIND_ICONS[kind];
              return (
                <span className="count-chip" key={kind} title={`${notebook.counts[kind]} ${KIND_LABELS[kind]}`}>
                  <KindIcon size={12} weight="bold" />
                  {notebook.counts[kind]}
                </span>
              );
            })}
          </span>
          <span className="nb-toolbar-actions">
            <button
              type="button"
              className="btn btn-ghost btn-compact"
              onClick={() => setRelationsOpen(true)}
              title="Cadernos que estas notas alcançam"
            >
              <GraphIcon size={15} />
              Afinidade
              {notebook.relations_count > 0 && (
                <span className="pill-count">{notebook.relations_count}</span>
              )}
            </button>
            <button
              type="button"
              className="icon-btn is-danger"
              onClick={onDelete}
              title="Apagar caderno"
              aria-label="Apagar caderno"
            >
              <Trash size={15} />
            </button>
          </span>
        </div>
      </header>

      <div className="quick-capture">
        <input
          ref={captureRef}
          className="input quick-capture-input"
          value={draft}
          placeholder="Nome da nota... (Enter cria e já abre para escrever)"
          maxLength={200}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              submitDraft();
            }
            if (event.key === "Escape") setDraft("");
          }}
          aria-label="Nome da nota nova"
        />
        <button type="button" className="btn btn-primary" onClick={submitDraft}>
          <Plus size={15} weight="bold" />
          Nova nota
        </button>
      </div>

      <section className="note-list">
        {notebook.notes.length === 0 ? (
          <EmptyState
            title="Caderno vazio"
            hint="Escreva na barra acima e dê Enter. Dentro da nota, / escolhe o tipo do bloco e # cria tags."
          />
        ) : (
          notebook.notes.map((note) => (
            <article className="note-card" key={note.id}>
              <button type="button" className="note-card-main" onClick={() => onOpenNote(note.id)}>
                <span className="note-card-title">{note.title || "Nota sem título"}</span>
                <span className="note-card-excerpt">{note.excerpt || "— vazia —"}</span>
                <span className="note-card-foot">
                  <span className="nb-counts">
                    {KIND_ORDER.filter((kind) => note.counts[kind] > 0).map((kind) => {
                      const KindIcon = KIND_ICONS[kind];
                      return (
                        <span className="count-chip" key={kind} title={KIND_LABELS[kind]}>
                          <KindIcon size={12} weight="bold" />
                          {note.counts[kind]}
                        </span>
                      );
                    })}
                  </span>
                  <span className="note-card-date">{relativeTime(note.updated_at)}</span>
                </span>
              </button>
              <button
                type="button"
                className="icon-btn is-tiny"
                onClick={() => onDeleteNote(note.id)}
                aria-label="Apagar nota"
              >
                <Trash size={13} />
              </button>
            </article>
          ))
        )}
      </section>

      {notebook.notes.length === 0 && (
        <p className="panel-hint">
          <NoteBlank size={13} /> Dica: dentro da nota, digite / em um bloco vazio para escolher
          texto, código, url, imagem ou vídeo.
        </p>
      )}

      {relationsOpen && (
        <RelationsModal
          notebook={notebook}
          onOpenNotebook={onOpenNotebook}
          onClose={() => setRelationsOpen(false)}
        />
      )}
    </div>
  );
}
